"""handlers/extended.py — Phase 6b: transactions, Analytics, Backup/Restore.

Three service surfaces added:

- Multi-document transactions (`cb_transaction_run`) — wrap cluster.transactions.run
  with a serialized operation list. Each op is one of insert/upsert/replace/
  remove against the configured CB_BUCKET/CB_SCOPE/CB_COLLECTION. The MCP
  builds the callable that the SDK requires.

- Analytics service (`cb_analytics_query`) — wraps cluster.analytics_query.
  Like cb_query, marked destructiveHint=true but always loaded — DML is
  blocked internally in read-only mode.

- Backup / Restore service (`admin_backup_*`) — wraps the backup service REST
  endpoints at /_p/backup/api/v1/... on the cluster manager. Requires the
  backup service to be running on at least one node.

Explicitly deferred to Phase 6c:
  - Eventing service tools (functions, debugger, statistics)
  - Sync Gateway tools (separate product with separate REST API)
  - Read-then-conditional-write transaction patterns (the LLM-in-the-loop
    timing makes these awkward; the simple write-batch pattern handles 80%
    of multi-doc atomicity needs).
"""

from __future__ import annotations

from mcp.types import TextContent, Tool, ToolAnnotations

from .shared import (
    admin_request,
    block_dml_if_readonly,
    err,
    get_sdk_connection,
    ok,
    quote_path,
)

# ── Transaction op translation ───────────────────────────────────────────────


def _translate_txn_op(ctx, collection, op: dict) -> None:
    """Apply a single operation to the transaction context.

    For replace and remove, the SDK requires a prior get within the same
    transaction (the API is built around TransactionGetResult, not raw keys).
    We do the implicit get for the caller — fail-fast if the doc is missing
    so the whole transaction rolls back rather than getting partway through.
    """
    kind = op.get("op")
    key = op.get("key", "")

    if kind == "insert":
        ctx.insert(collection, key, op["document"])
    elif kind == "upsert":
        ctx.upsert(collection, key, op["document"])
    elif kind == "replace":
        got = ctx.get(collection, key)
        ctx.replace(got, op["document"])
    elif kind == "remove":
        got = ctx.get(collection, key)
        ctx.remove(got)
    else:
        raise ValueError(
            f"unsupported transaction op '{kind}'; expected one of: "
            "insert, upsert, replace, remove"
        )


# ── Tool definitions ─────────────────────────────────────────────────────────

TOOLS: list[Tool] = [
    # ── Multi-document transactions ─────────────────────────────────────
    Tool(
        name="cb_transaction_run",
        description=(
            "Execute multiple KV mutations atomically across documents in a "
            "single ACID transaction. All ops succeed or all roll back. "
            "Supports insert / upsert / replace / remove ops on documents in "
            "the configured CB_BUCKET/CB_SCOPE/CB_COLLECTION. For replace and "
            "remove, the transaction issues an implicit get inside the txn "
            "(fails the transaction if the doc is missing). Requires "
            "confirm:true. Currently scoped to write-only ops; read-then-"
            "conditional-write is deferred (see CHANGES Phase 6b)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "operations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {
                                "type": "string",
                                "enum": ["insert", "upsert", "replace", "remove"],
                            },
                            "key": {"type": "string"},
                            "document": {
                                "type": "object",
                                "description": "Required for insert/upsert/replace",
                            },
                        },
                        "required": ["op", "key"],
                    },
                    "minItems": 1,
                },
                "durability": {
                    "type": "string",
                    "enum": [
                        "NONE",
                        "MAJORITY",
                        "MAJORITY_AND_PERSIST_TO_ACTIVE",
                        "PERSIST_TO_MAJORITY",
                    ],
                    "description": "Optional per-transaction durability override",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Transaction timeout (default 15s in SDK)",
                },
                "confirm": {"type": "boolean"},
            },
            "required": ["operations"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
        ),
    ),
    # ── Analytics service ───────────────────────────────────────────────
    Tool(
        name="cb_analytics_query",
        description=(
            "Run a SQL++-for-Analytics query against the Analytics service. "
            "Similar to cb_query but goes through cluster.analytics_query "
            "(separate service, separate dialect, often used for ad-hoc "
            "analytical workloads over Analytics datasets / shadow datasets). "
            "When CB_MCP_READ_ONLY_MODE=true, DML / DDL statements are blocked "
            "(same regex as cb_query). The Analytics service must be running "
            "on at least one node."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "statement": {"type": "string"},
                "params": {
                    "type": "object",
                    "description": "Named parameters bound via $name placeholders",
                },
                "timeout_seconds": {"type": "integer"},
            },
            "required": ["statement"],
        },
        # destructiveHint mirrors cb_query — the tool stays loaded in read-only
        # mode (special case in server.py) and DML is gated internally.
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
        ),
    ),
    # ── Backup / Restore ────────────────────────────────────────────────
    Tool(
        name="admin_backup_repository_list",
        description=(
            "List active backup repositories on the backup service. Requires "
            "the backup service to be running on at least one node."
        ),
        inputSchema={"type": "object", "properties": {}},
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        ),
    ),
    Tool(
        name="admin_backup_repository_get",
        description="Get details of a specific backup repository.",
        inputSchema={
            "type": "object",
            "properties": {"repository_id": {"type": "string"}},
            "required": ["repository_id"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        ),
    ),
    Tool(
        name="admin_backup_list",
        description="List all backups stored in a repository.",
        inputSchema={
            "type": "object",
            "properties": {"repository_id": {"type": "string"}},
            "required": ["repository_id"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        ),
    ),
    Tool(
        name="admin_backup_run",
        description=(
            "Trigger a backup operation on the specified repository. Returns "
            "task ID; monitor progress with admin_cluster_tasks."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repository_id": {"type": "string"},
                "full_backup": {
                    "type": "boolean",
                    "description": "Default false (incremental); true = full backup",
                },
            },
            "required": ["repository_id"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
        ),
    ),
    Tool(
        name="admin_backup_restore_run",
        description=(
            "Trigger a restore operation. This can overwrite data in the "
            "target cluster — review carefully. Requires confirm:true."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repository_id": {"type": "string"},
                "target": {
                    "type": "object",
                    "description": (
                        "Restore target configuration object. Typical fields: "
                        "filter_keys, filter_values, mappings, include, exclude. "
                        "See Couchbase Backup Service REST docs for the full shape."
                    ),
                },
                "confirm": {"type": "boolean"},
            },
            "required": ["repository_id", "target"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
        ),
    ),
]


# ── Handler dispatch ─────────────────────────────────────────────────────────


def handle(name: str, args: dict) -> list[TextContent]:
    try:
        if name == "cb_transaction_run":
            return _transaction(args)

        if name == "cb_analytics_query":
            return _analytics(args)

        if name == "admin_backup_repository_list":
            return ok(admin_request("GET", "/_p/backup/api/v1/cluster/self/repository"))

        if name == "admin_backup_repository_get":
            rid = quote_path(args["repository_id"])
            return ok(
                admin_request("GET", f"/_p/backup/api/v1/cluster/self/repository/{rid}")
            )

        if name == "admin_backup_list":
            rid = quote_path(args["repository_id"])
            return ok(
                admin_request(
                    "GET", f"/_p/backup/api/v1/cluster/self/repository/{rid}/backups"
                )
            )

        if name == "admin_backup_run":
            rid = quote_path(args["repository_id"])
            payload: dict = {}
            if args.get("full_backup"):
                payload["full_backup"] = True
            return ok(
                admin_request(
                    "POST",
                    f"/_p/backup/api/v1/cluster/self/repository/{rid}/backup",
                    data=payload if payload else None,
                    json_body=True,
                )
            )

        if name == "admin_backup_restore_run":
            rid = quote_path(args["repository_id"])
            return ok(
                admin_request(
                    "POST",
                    f"/_p/backup/api/v1/cluster/self/repository/{rid}/restore",
                    data=args["target"],
                    json_body=True,
                )
            )

        return err(f"Unknown extended tool: {name}", tool=name)

    except Exception as exc:
        return err(f"{type(exc).__name__}: {exc}", tool=name, args=args)


# ── Tool implementations ─────────────────────────────────────────────────────


def _transaction(args: dict) -> list[TextContent]:
    """Run a multi-doc transaction."""
    operations = args.get("operations")
    if not isinstance(operations, list) or not operations:
        return err("operations must be a non-empty array", tool="cb_transaction_run")

    # Pre-validate ops before connecting — gives a clean error before any
    # cluster interaction.
    for i, op in enumerate(operations):
        kind = op.get("op")
        if kind not in ("insert", "upsert", "replace", "remove"):
            return err(
                f"operation[{i}] has unsupported op '{kind}'; expected "
                "insert, upsert, replace, or remove",
                tool="cb_transaction_run",
            )
        if not op.get("key"):
            return err(
                f"operation[{i}] is missing required `key`",
                tool="cb_transaction_run",
            )
        if kind in ("insert", "upsert", "replace") and "document" not in op:
            return err(
                f"operation[{i}] is missing `document` (required for {kind})",
                tool="cb_transaction_run",
            )

    try:
        cluster, _, collection = get_sdk_connection()
    except Exception as exc:
        return err(f"Couchbase connection failed: {exc}", tool="cb_transaction_run")

    # Build the transaction callable. Each op runs inside the SDK-managed
    # transaction context, and any exception triggers full rollback.
    def txn_body(ctx):
        for op in operations:
            _translate_txn_op(ctx, collection, op)

    # Build options if any txn-level args provided.
    try:
        from couchbase.durability import DurabilityLevel
        from couchbase.options import TransactionOptions
    except ImportError as exc:
        return err(
            f"Couchbase SDK transaction support missing: {exc}",
            tool="cb_transaction_run",
        )

    kw: dict = {}
    durability = args.get("durability")
    if durability and durability != "NONE":
        kw["durability_level"] = getattr(DurabilityLevel, durability, None)
        if kw["durability_level"] is None:
            return err(
                f"unknown durability level '{durability}'",
                tool="cb_transaction_run",
            )
    if args.get("timeout_seconds") is not None:
        from datetime import timedelta

        kw["timeout"] = timedelta(seconds=int(args["timeout_seconds"]))

    opts = TransactionOptions(**kw) if kw else None

    try:
        if opts:
            result = cluster.transactions.run(txn_body, opts)
        else:
            result = cluster.transactions.run(txn_body)
    except Exception as exc:
        return err(
            f"Transaction failed: {type(exc).__name__}: {exc}",
            tool="cb_transaction_run",
            operation_count=len(operations),
        )

    return ok(
        {
            "transaction_id": getattr(result, "transaction_id", None),
            "unstaging_complete": getattr(result, "unstaging_complete", None),
            "operation_count": len(operations),
            "status": "committed",
        }
    )


def _analytics(args: dict) -> list[TextContent]:
    """Run an Analytics service query."""
    statement = args["statement"]
    # Same DML blocking as cb_query — read-only mode rejects writes.
    blocked = block_dml_if_readonly(statement)
    if blocked:
        return err(blocked, tool="cb_analytics_query", statement=statement)

    try:
        cluster, _, _ = get_sdk_connection()
    except Exception as exc:
        return err(f"Couchbase connection failed: {exc}", tool="cb_analytics_query")

    from couchbase.options import AnalyticsOptions

    kw: dict = {}
    if args.get("params"):
        kw["named_parameters"] = args["params"]
    if args.get("timeout_seconds") is not None:
        from datetime import timedelta

        kw["timeout"] = timedelta(seconds=int(args["timeout_seconds"]))

    opts = AnalyticsOptions(**kw) if kw else AnalyticsOptions()

    result = cluster.analytics_query(statement, opts)
    rows = list(result)
    meta = result.metadata()
    return ok(
        {
            "rows": rows,
            "count": len(rows),
            "metrics": {
                "elapsed": str(meta.metrics().elapsed_time()),
                "execution": str(meta.metrics().execution_time()),
                "result_count": meta.metrics().result_count(),
            },
        }
    )
