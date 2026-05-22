"""handlers/data.py — CRUD, N1QL, FTS, ping, subdocument tools.

Changes from upstream:
- Phase 1: MCP tool annotations on every tool. cb_query blocks SQL++ DML when
  CB_MCP_READ_ONLY_MODE=true and forces the SDK's readonly flag in RO mode.
- Phase 2: Structured err() returns on SDK exceptions instead of raising.
- Phase 6a: Optional `durability` (and `expiry_seconds` / `cas` where appropriate)
  on the CRUD tools — strictly backwards-compatible, omitting them keeps the
  upstream behavior. Two new subdocument tools: cb_lookup_in and cb_mutate_in.
"""

from __future__ import annotations

from typing import Any

from mcp.types import Tool, TextContent, ToolAnnotations

from .shared import (
    READ_ONLY_MODE,
    block_dml_if_readonly,
    err,
    get_sdk_connection,
    ok,
)


# ── Durability handling ──────────────────────────────────────────────────────

_DURABILITY_VALUES = {"NONE", "MAJORITY", "MAJORITY_AND_PERSIST_TO_ACTIVE", "PERSIST_TO_MAJORITY"}


def _parse_durability(level: str | None):
    """Translate the env-style string to a SDK DurabilityLevel enum value.
    Returns None if level is None or 'NONE'."""
    if not level or level == "NONE":
        return None
    if level not in _DURABILITY_VALUES:
        raise ValueError(
            f"durability must be one of {sorted(_DURABILITY_VALUES)}; got '{level}'"
        )
    from couchbase.durability import DurabilityLevel  # type: ignore
    return getattr(DurabilityLevel, level)


def _kv_options(option_cls, durability: str | None,
                expiry_seconds: int | None = None,
                cas: str | None = None):
    """Build an Options object only if any field is set; else return None."""
    kw: dict = {}
    dl = _parse_durability(durability)
    if dl is not None:
        kw["durability_level"] = dl
    if expiry_seconds is not None:
        from datetime import timedelta
        kw["expiry"] = timedelta(seconds=int(expiry_seconds))
    if cas is not None:
        try:
            kw["cas"] = int(cas)
        except (TypeError, ValueError):
            raise ValueError(f"cas must be an integer string; got '{cas}'")
    if not kw:
        return None
    return option_cls(**kw)


# ── Subdoc spec translation ──────────────────────────────────────────────────


def _translate_lookup_spec(spec: dict):
    """Translate a lookup spec dict into an SDK LookupInSpec."""
    from couchbase import subdocument as SD  # type: ignore

    op = spec.get("op")
    path = spec.get("path", "")
    if op == "get":
        return SD.get(path)
    if op == "exists":
        return SD.exists(path)
    if op == "count":
        return SD.count(path)
    raise ValueError(f"unsupported lookup op '{op}'; expected get/exists/count")


def _translate_mutate_spec(spec: dict):
    """Translate a mutation spec dict into an SDK MutateInSpec."""
    from couchbase import subdocument as SD  # type: ignore

    op = spec.get("op")
    path = spec.get("path", "")
    value = spec.get("value")
    create_parents = bool(spec.get("create_parents", False))

    if op == "upsert":
        return SD.upsert(path, value, create_parents=create_parents)
    if op == "insert":
        return SD.insert(path, value, create_parents=create_parents)
    if op == "replace":
        return SD.replace(path, value)
    if op == "remove":
        return SD.remove(path)
    if op == "array_append":
        return SD.array_append(path, value, create_parents=create_parents)
    if op == "array_prepend":
        return SD.array_prepend(path, value, create_parents=create_parents)
    if op == "array_insert":
        return SD.array_insert(path, value)
    if op == "array_add_unique":
        return SD.array_addunique(path, value, create_parents=create_parents)
    if op == "counter":
        delta = spec.get("delta", 1)
        return SD.counter(path, int(delta), create_parents=create_parents)
    raise ValueError(
        f"unsupported mutate op '{op}'; expected one of: upsert, insert, "
        "replace, remove, array_append, array_prepend, array_insert, "
        "array_add_unique, counter"
    )


_STORE_SEMANTICS = {"replace", "upsert", "insert"}


def _store_semantics(name: str | None):
    """Translate store_semantics string to the SDK enum, or None if default."""
    if not name:
        return None
    if name not in _STORE_SEMANTICS:
        raise ValueError(
            f"store_semantics must be one of {sorted(_STORE_SEMANTICS)}; got '{name}'"
        )
    from couchbase.subdocument import StoreSemantics  # type: ignore
    return getattr(StoreSemantics, name.upper())


# ── Tool definitions ─────────────────────────────────────────────────────────

# Reused schema fragments
_DURABILITY_SCHEMA = {
    "type": "string",
    "enum": ["NONE", "MAJORITY", "MAJORITY_AND_PERSIST_TO_ACTIVE", "PERSIST_TO_MAJORITY"],
    "description": (
        "Optional durability level. Default NONE matches upstream behavior. "
        "MAJORITY waits for replication to majority of replicas; "
        "MAJORITY_AND_PERSIST_TO_ACTIVE also waits for disk on active; "
        "PERSIST_TO_MAJORITY waits for disk on majority. Cluster must have "
        "enough replicas configured to satisfy the level."
    ),
}

_EXPIRY_SCHEMA = {
    "type": "integer",
    "description": "Optional document expiry in seconds (0 = no expiry).",
}

_CAS_SCHEMA = {
    "type": "string",
    "description": (
        "Optional Compare-And-Swap value (from a prior cb_get/cb_upsert result). "
        "If set, the operation fails if the document has been modified since."
    ),
}


TOOLS: list[Tool] = [
    Tool(
        name="cb_ping",
        description="Ping the Couchbase cluster to verify SDK + service connectivity.",
        inputSchema={"type": "object", "properties": {}},
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True,
        ),
    ),
    Tool(
        name="cb_get",
        description="Get a document by its key.",
        inputSchema={
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True,
        ),
    ),
    Tool(
        name="cb_upsert",
        description=(
            "Insert or replace a document. Optional `durability` and "
            "`expiry_seconds` (Phase 6a additions, backwards-compatible)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "document": {"type": "object"},
                "durability": _DURABILITY_SCHEMA,
                "expiry_seconds": _EXPIRY_SCHEMA,
            },
            "required": ["key", "document"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=True,
        ),
    ),
    Tool(
        name="cb_insert",
        description=(
            "Insert a new document (fails if key already exists). Optional "
            "`durability` and `expiry_seconds`."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "document": {"type": "object"},
                "durability": _DURABILITY_SCHEMA,
                "expiry_seconds": _EXPIRY_SCHEMA,
            },
            "required": ["key", "document"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False,
        ),
    ),
    Tool(
        name="cb_replace",
        description=(
            "Replace an existing document (fails if key does not exist). "
            "Optional `durability`, `expiry_seconds`, and `cas` for "
            "optimistic concurrency."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "document": {"type": "object"},
                "durability": _DURABILITY_SCHEMA,
                "expiry_seconds": _EXPIRY_SCHEMA,
                "cas": _CAS_SCHEMA,
            },
            "required": ["key", "document"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=True,
        ),
    ),
    Tool(
        name="cb_delete",
        description=(
            "Delete a document by key. Optional `durability` and `cas`."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "durability": _DURABILITY_SCHEMA,
                "cas": _CAS_SCHEMA,
                "confirm": {"type": "boolean"},
            },
            "required": ["key"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=True,
        ),
    ),
    Tool(
        name="cb_get_multi",
        description="Retrieve multiple documents by a list of keys.",
        inputSchema={
            "type": "object",
            "properties": {
                "keys": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["keys"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True,
        ),
    ),
    Tool(
        name="cb_query",
        description=(
            "Run a N1QL / SQL++ query. Use $name style named parameters. "
            "When CB_MCP_READ_ONLY_MODE=true (default), all DML/DDL statements "
            "are blocked and the SDK readonly flag is forced on."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "statement": {"type": "string"},
                "params": {"type": "object"},
                "readonly": {"type": "boolean"},
            },
            "required": ["statement"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=False,
        ),
    ),
    Tool(
        name="cb_fts_search",
        description="Run a full-text search query against a Couchbase FTS index.",
        inputSchema={
            "type": "object",
            "properties": {
                "index_name": {"type": "string"},
                "query": {"type": "string"},
                "limit": {"type": "integer"},
                "fields": {"type": "array", "items": {"type": "string"}},
                "highlight": {"type": "boolean"},
            },
            "required": ["index_name", "query"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True,
        ),
    ),
    # ── Phase 6a: subdocument operations ─────────────────────────────────
    Tool(
        name="cb_lookup_in",
        description=(
            "Read one or more paths inside a document without fetching the "
            "whole document. Each spec is an object with `op` (get|exists|count) "
            "and `path` (e.g. 'user.name', 'addresses[0].city'). Returns a "
            "results array aligned with the input specs."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "specs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {"type": "string", "enum": ["get", "exists", "count"]},
                            "path": {"type": "string"},
                        },
                        "required": ["op", "path"],
                    },
                    "minItems": 1,
                },
            },
            "required": ["key", "specs"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True,
        ),
    ),
    Tool(
        name="cb_mutate_in",
        description=(
            "Mutate one or more paths inside a document atomically. Each op is "
            "an object with `op` (upsert|insert|replace|remove|array_append|"
            "array_prepend|array_insert|array_add_unique|counter), `path`, and "
            "either `value` or `delta` (counter only). Optional `create_parents` "
            "auto-creates intermediate path segments. Optional `store_semantics` "
            "(replace|upsert|insert) controls behavior when the parent document "
            "does not exist. Optional `durability` and `cas`."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "ops": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {
                                "type": "string",
                                "enum": [
                                    "upsert", "insert", "replace", "remove",
                                    "array_append", "array_prepend",
                                    "array_insert", "array_add_unique",
                                    "counter",
                                ],
                            },
                            "path": {"type": "string"},
                            "value": {
                                "description": "Value for the op (not used by remove or counter)",
                            },
                            "delta": {
                                "type": "integer",
                                "description": "Increment for counter op (default 1)",
                            },
                            "create_parents": {"type": "boolean"},
                        },
                        "required": ["op", "path"],
                    },
                    "minItems": 1,
                },
                "store_semantics": {
                    "type": "string",
                    "enum": ["replace", "upsert", "insert"],
                    "description": (
                        "How to behave when the parent document doesn't exist. "
                        "Default: replace (fail). upsert creates the doc; "
                        "insert creates only if absent."
                    ),
                },
                "durability": _DURABILITY_SCHEMA,
                "cas": _CAS_SCHEMA,
            },
            "required": ["key", "ops"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False,
        ),
    ),
]


# ── Handlers ─────────────────────────────────────────────────────────────────


def handle(name: str, args: dict) -> list[TextContent]:
    try:
        cluster, _, collection = get_sdk_connection()
    except Exception as exc:
        return err(f"Couchbase connection failed: {exc}", tool=name)

    try:
        if name == "cb_ping":
            result = cluster.ping()
            services = {}
            for svc, endpoints in result.endpoints.items():
                services[str(svc)] = [
                    {"id": e.id, "state": str(e.state), "remote": e.remote}
                    for e in endpoints
                ]
            return ok({"status": "ok", "services": services})

        if name == "cb_get":
            r = collection.get(args["key"])
            return ok({
                "key": args["key"],
                "content": r.content_as[dict],
                "cas": str(r.cas),
            })

        if name == "cb_upsert":
            from couchbase.options import UpsertOptions
            opts = _kv_options(
                UpsertOptions, args.get("durability"), args.get("expiry_seconds"),
            )
            r = collection.upsert(args["key"], args["document"], opts) if opts \
                else collection.upsert(args["key"], args["document"])
            return ok({"key": args["key"], "cas": str(r.cas), "operation": "upsert"})

        if name == "cb_insert":
            from couchbase.options import InsertOptions
            opts = _kv_options(
                InsertOptions, args.get("durability"), args.get("expiry_seconds"),
            )
            r = collection.insert(args["key"], args["document"], opts) if opts \
                else collection.insert(args["key"], args["document"])
            return ok({"key": args["key"], "cas": str(r.cas), "operation": "insert"})

        if name == "cb_replace":
            from couchbase.options import ReplaceOptions
            opts = _kv_options(
                ReplaceOptions, args.get("durability"),
                args.get("expiry_seconds"), args.get("cas"),
            )
            r = collection.replace(args["key"], args["document"], opts) if opts \
                else collection.replace(args["key"], args["document"])
            return ok({"key": args["key"], "cas": str(r.cas), "operation": "replace"})

        if name == "cb_delete":
            from couchbase.options import RemoveOptions
            opts = _kv_options(
                RemoveOptions, args.get("durability"), None, args.get("cas"),
            )
            if opts:
                collection.remove(args["key"], opts)
            else:
                collection.remove(args["key"])
            return ok({"key": args["key"], "operation": "delete", "status": "ok"})

        if name == "cb_get_multi":
            results = collection.get_multi(args["keys"])
            docs = {}
            for k, v in results.results.items():
                if v.success:
                    docs[k] = {"content": v.content_as[dict], "cas": str(v.cas)}
                else:
                    docs[k] = {"error": str(v.exception)}
            return ok(docs)

        if name == "cb_query":
            from couchbase.options import QueryOptions

            statement = args["statement"]
            blocked = block_dml_if_readonly(statement)
            if blocked:
                return err(blocked, tool=name, statement=statement)

            params = args.get("params") or {}
            readonly = True if READ_ONLY_MODE else bool(args.get("readonly", False))

            result = cluster.query(
                statement,
                QueryOptions(named_parameters=params, read_only=readonly),
            )
            rows = list(result)
            meta = result.metadata()
            return ok({
                "rows": rows,
                "count": len(rows),
                "read_only": readonly,
                "metrics": {
                    "elapsed": str(meta.metrics().elapsed_time()),
                    "execution": str(meta.metrics().execution_time()),
                    "result_count": meta.metrics().result_count(),
                },
            })

        if name == "cb_fts_search":
            from couchbase.search import SearchOptions, MatchQuery

            limit = args.get("limit", 10)
            fields = args.get("fields", [])
            hl = args.get("highlight", False)
            kw: dict[str, Any] = {"limit": limit}
            if fields:
                kw["fields"] = fields
            if hl:
                from couchbase.search import HighlightStyle

                kw["highlight_style"] = HighlightStyle.Html
                kw["highlight_fields"] = fields or ["*"]
            result = cluster.search(
                args["index_name"], MatchQuery(args["query"]), SearchOptions(**kw)
            )
            hits = []
            for row in result:
                h: dict[str, Any] = {"id": row.id, "score": row.score}
                if row.fields:
                    h["fields"] = row.fields
                if getattr(row, "fragments", None):
                    h["fragments"] = row.fragments
                hits.append(h)
            meta = result.metadata()
            return ok({
                "hits": hits,
                "total_hits": meta.metrics().total_rows(),
                "took_ms": meta.metrics().took().total_seconds() * 1000,
            })

        if name == "cb_lookup_in":
            specs_in = args["specs"]
            if not isinstance(specs_in, list) or not specs_in:
                return err("specs must be a non-empty array", tool=name)
            sdk_specs = [_translate_lookup_spec(s) for s in specs_in]
            result = collection.lookup_in(args["key"], sdk_specs)
            out = []
            for i, spec_in in enumerate(specs_in):
                op = spec_in.get("op")
                entry: dict = {"op": op, "path": spec_in.get("path")}
                try:
                    if op == "get":
                        entry["value"] = result.content_as[object](i)
                    elif op == "exists":
                        entry["exists"] = bool(result.exists(i))
                    elif op == "count":
                        entry["count"] = result.content_as[int](i)
                except Exception as ex:
                    entry["error"] = str(ex)
                out.append(entry)
            return ok({
                "key": args["key"],
                "cas": str(result.cas),
                "results": out,
            })

        if name == "cb_mutate_in":
            from couchbase.options import MutateInOptions

            ops_in = args["ops"]
            if not isinstance(ops_in, list) or not ops_in:
                return err("ops must be a non-empty array", tool=name)
            sdk_ops = [_translate_mutate_spec(o) for o in ops_in]

            kw: dict = {}
            dl = _parse_durability(args.get("durability"))
            if dl is not None:
                kw["durability_level"] = dl
            ss = _store_semantics(args.get("store_semantics"))
            if ss is not None:
                kw["store_semantics"] = ss
            if args.get("cas") is not None:
                try:
                    kw["cas"] = int(args["cas"])
                except (TypeError, ValueError):
                    return err(
                        f"cas must be an integer string; got '{args['cas']}'",
                        tool=name,
                    )

            opts = MutateInOptions(**kw) if kw else None
            result = collection.mutate_in(args["key"], sdk_ops, opts) if opts \
                else collection.mutate_in(args["key"], sdk_ops)

            return ok({
                "key": args["key"],
                "cas": str(result.cas),
                "operation_count": len(sdk_ops),
            })

        return err(f"Unknown data tool: {name}", tool=name)

    except Exception as exc:
        return err(f"{type(exc).__name__}: {exc}", tool=name, args=args)
