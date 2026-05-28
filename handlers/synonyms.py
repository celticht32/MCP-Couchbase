"""handlers/synonyms.py — Phase 5 deferred: Couchbase 8.x FTS synonym documents.

In Couchbase 8.x, FTS synonyms are configured by:
1. A synonym source declared inside the FTS index's `params.mapping.analysis.
   synonym_sources` block (managed via admin_fts_index_create — Phase 1 tool).
2. Synonym set documents stored in a regular Couchbase collection. Each
   document has the shape:
       {"input": ["js", "javascript"], "synonyms": ["js", "javascript", "ecmascript"]}

This module provides convenience tools for managing the synonym set documents
in the source collection. The schema is validated client-side so the LLM gets
a clear error if it gets the shape wrong, rather than silently inserting a doc
that the FTS analyzer can't parse.

The FTS index itself (with the synonym source declared in its analysis config)
is still managed through admin_fts_index_create.

All tools are 8.x-only (synonym sources are a Couchbase 8.0+ feature) — they
call _require_8x() at the top of their handlers.
"""

from __future__ import annotations

from mcp.types import TextContent, Tool, ToolAnnotations

from .eight_x import _require_8x
from .shared import err, get_sdk_connection, ok

# ── Schema validation ────────────────────────────────────────────────────────


def _validate_synonym_doc(doc: dict, tool: str) -> list[TextContent] | None:
    """Verify the document matches the FTS synonym schema. Returns None if OK,
    else an error response."""
    if not isinstance(doc, dict):
        return err("synonym document must be an object", tool=tool)

    inp = doc.get("input")
    syns = doc.get("synonyms")

    if not isinstance(inp, list) or not inp:
        return err(
            "synonym document must include `input` as a non-empty array of strings",
            tool=tool,
        )
    if not all(isinstance(x, str) for x in inp):
        return err("`input` must contain only strings", tool=tool)

    if not isinstance(syns, list) or not syns:
        return err(
            "synonym document must include `synonyms` as a non-empty array of strings",
            tool=tool,
        )
    if not all(isinstance(x, str) for x in syns):
        return err("`synonyms` must contain only strings", tool=tool)

    # Document may contain extra fields (e.g. for explicit equivalence vs
    # transformation semantics), but those two are required.
    return None


TOOLS: list[Tool] = [
    Tool(
        name="cb_fts_synonym_upsert",
        description=(
            "Insert or update a synonym set document in the configured "
            "synonym source collection. Schema is validated: requires `input` "
            "(non-empty array of strings) and `synonyms` (non-empty array of "
            "strings). The FTS index referencing this source collection picks "
            "up the synonyms on its next refresh. Requires Couchbase 8.0+."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "bucket_name": {
                    "type": "string",
                    "description": "Bucket containing the synonym source collection",
                },
                "scope_name": {"type": "string", "description": "default: _default"},
                "collection_name": {
                    "type": "string",
                    "description": "default: _default",
                },
                "key": {
                    "type": "string",
                    "description": "Document key (any string; often a hash of input terms)",
                },
                "input": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Source terms — words that should map to the synonyms",
                },
                "synonyms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Synonym terms produced when an input matches",
                },
            },
            "required": ["bucket_name", "key", "input", "synonyms"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
        ),
    ),
    Tool(
        name="cb_fts_synonym_list",
        description=(
            "List all synonym set documents in a synonym source collection. "
            "Returns up to `limit` documents (default 50). Requires Couchbase 8.0+."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "bucket_name": {"type": "string"},
                "scope_name": {"type": "string"},
                "collection_name": {"type": "string"},
                "limit": {"type": "integer", "description": "default 50"},
            },
            "required": ["bucket_name"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        ),
    ),
    Tool(
        name="cb_fts_synonym_delete",
        description=(
            "Delete a synonym set document by key. Requires confirm:true. "
            "Requires Couchbase 8.0+."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "bucket_name": {"type": "string"},
                "scope_name": {"type": "string"},
                "collection_name": {"type": "string"},
                "key": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["bucket_name", "key"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
        ),
    ),
]


def _safe_ident(s: str) -> str:
    return "`" + (s or "").replace("`", "``") + "`"


def _resolve_collection(cluster, bucket: str, scope: str | None, coll: str | None):
    """Resolve a (bucket, scope, collection) tuple to an SDK Collection ref."""
    b = cluster.bucket(bucket)
    return b.scope(scope or "_default").collection(coll or "_default")


def handle(name: str, args: dict) -> list[TextContent]:
    gate = _require_8x(name)
    if gate is not None:
        return gate

    try:
        cluster, _, _ = get_sdk_connection()
    except Exception as exc:
        return err(f"Couchbase connection failed: {exc}", tool=name)

    try:
        if name == "cb_fts_synonym_upsert":
            doc = {"input": args["input"], "synonyms": args["synonyms"]}
            bad = _validate_synonym_doc(doc, name)
            if bad:
                return bad
            coll = _resolve_collection(
                cluster,
                args["bucket_name"],
                args.get("scope_name"),
                args.get("collection_name"),
            )
            r = coll.upsert(args["key"], doc)
            return ok(
                {
                    "key": args["key"],
                    "cas": str(r.cas),
                    "operation": "upsert",
                    "schema": "synonym",
                }
            )

        if name == "cb_fts_synonym_list":
            from couchbase.options import QueryOptions

            bucket = _safe_ident(args["bucket_name"])
            scope = _safe_ident(args.get("scope_name") or "_default")
            coll = _safe_ident(args.get("collection_name") or "_default")
            limit = int(args.get("limit", 50))
            stmt = (
                f"SELECT META().id AS key, d.input, d.synonyms "
                f"FROM {bucket}.{scope}.{coll} d "
                f"WHERE d.input IS NOT MISSING AND d.synonyms IS NOT MISSING "
                f"LIMIT $lim"
            )
            result = cluster.query(stmt, QueryOptions(named_parameters={"lim": limit}))
            rows = list(result)
            return ok({"synonyms": rows, "count": len(rows)})

        if name == "cb_fts_synonym_delete":
            coll = _resolve_collection(
                cluster,
                args["bucket_name"],
                args.get("scope_name"),
                args.get("collection_name"),
            )
            coll.remove(args["key"])
            return ok({"key": args["key"], "operation": "delete", "status": "ok"})

        return err(f"Unknown synonym tool: {name}", tool=name)

    except Exception as exc:
        return err(f"{type(exc).__name__}: {exc}", tool=name, args=args)
