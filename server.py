"""
Couchbase MCP Server
Exposes Couchbase operations (CRUD, N1QL queries, Full-Text Search) as MCP tools.
"""

import json
import os
import asyncio
from typing import Any
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# ---------------------------------------------------------------------------
# Lazy Couchbase connection
# ---------------------------------------------------------------------------
_cluster = None
_bucket = None
_collection = None


def _get_connection():
    """Return (cluster, bucket, default_collection) – connect on first call."""
    global _cluster, _bucket, _collection

    if _cluster is not None:
        return _cluster, _bucket, _collection

    try:
        from couchbase.cluster import Cluster
        from couchbase.options import ClusterOptions
        from couchbase.auth import PasswordAuthenticator
        from datetime import timedelta
    except ImportError as exc:
        raise RuntimeError(
            "couchbase package not installed. Run: pip install couchbase"
        ) from exc

    conn_str   = os.environ.get("CB_CONNECTION_STRING", "couchbase://localhost")
    username   = os.environ.get("CB_USERNAME", "Administrator")
    password   = os.environ.get("CB_PASSWORD", "password")
    bucket_name = os.environ.get("CB_BUCKET", "default")
    scope_name  = os.environ.get("CB_SCOPE", "_default")
    coll_name   = os.environ.get("CB_COLLECTION", "_default")

    auth = PasswordAuthenticator(username, password)
    opts = ClusterOptions(auth)
    opts.apply_profile("wan_development")

    _cluster = Cluster(conn_str, opts)
    _cluster.wait_until_ready(timedelta(seconds=10))

    _bucket = _cluster.bucket(bucket_name)
    _collection = _bucket.scope(scope_name).collection(coll_name)

    return _cluster, _bucket, _collection


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------
app = Server("couchbase-mcp")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        # ── CRUD ──────────────────────────────────────────────────────────
        Tool(
            name="cb_get",
            description="Get a document by its key from Couchbase.",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Document key / ID"},
                },
                "required": ["key"],
            },
        ),
        Tool(
            name="cb_upsert",
            description="Insert or replace a document in Couchbase.",
            inputSchema={
                "type": "object",
                "properties": {
                    "key":      {"type": "string", "description": "Document key / ID"},
                    "document": {"type": "object", "description": "JSON document to store"},
                },
                "required": ["key", "document"],
            },
        ),
        Tool(
            name="cb_insert",
            description="Insert a new document (fails if key already exists).",
            inputSchema={
                "type": "object",
                "properties": {
                    "key":      {"type": "string"},
                    "document": {"type": "object"},
                },
                "required": ["key", "document"],
            },
        ),
        Tool(
            name="cb_replace",
            description="Replace an existing document (fails if key doesn't exist).",
            inputSchema={
                "type": "object",
                "properties": {
                    "key":      {"type": "string"},
                    "document": {"type": "object"},
                },
                "required": ["key", "document"],
            },
        ),
        Tool(
            name="cb_delete",
            description="Delete a document by key from Couchbase.",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Document key / ID"},
                },
                "required": ["key"],
            },
        ),
        Tool(
            name="cb_get_multi",
            description="Retrieve multiple documents by a list of keys.",
            inputSchema={
                "type": "object",
                "properties": {
                    "keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of document keys",
                    }
                },
                "required": ["keys"],
            },
        ),
        # ── N1QL / SQL++ ──────────────────────────────────────────────────
        Tool(
            name="cb_query",
            description=(
                "Run a N1QL / SQL++ query against Couchbase. "
                "Use named parameters like $name in the statement and supply them in params."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "statement": {
                        "type": "string",
                        "description": "N1QL statement, e.g. SELECT * FROM `travel-sample` LIMIT 5",
                    },
                    "params": {
                        "type": "object",
                        "description": "Optional named parameters (key → value)",
                    },
                    "readonly": {
                        "type": "boolean",
                        "description": "Set true to hint read-only (default false)",
                    },
                },
                "required": ["statement"],
            },
        ),
        # ── Full-Text Search ───────────────────────────────────────────────
        Tool(
            name="cb_fts_search",
            description="Run a full-text search query against a Couchbase Search index.",
            inputSchema={
                "type": "object",
                "properties": {
                    "index_name": {
                        "type": "string",
                        "description": "Name of the FTS index to search",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query string",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default 10)",
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to include in results",
                    },
                    "highlight": {
                        "type": "boolean",
                        "description": "Include highlighted snippets (default false)",
                    },
                },
                "required": ["index_name", "query"],
            },
        ),
        # ── Utility ───────────────────────────────────────────────────────
        Tool(
            name="cb_ping",
            description="Ping the Couchbase cluster to verify connectivity.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def _ok(data: Any) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _err(msg: str) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps({"error": msg}, indent=2))]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_call_tool, name, arguments)


def _sync_call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        _, _, collection = _get_connection()
        cluster, _, _    = _get_connection()
    except Exception as exc:
        return _err(f"Connection error: {exc}")

    # ── cb_ping ──────────────────────────────────────────────────────────
    if name == "cb_ping":
        try:
            result = cluster.ping()
            services = {}
            for svc, endpoints in result.endpoints.items():
                services[str(svc)] = [
                    {"id": e.id, "state": str(e.state), "remote": e.remote}
                    for e in endpoints
                ]
            return _ok({"status": "ok", "services": services})
        except Exception as exc:
            return _err(str(exc))

    # ── cb_get ───────────────────────────────────────────────────────────
    if name == "cb_get":
        try:
            result = collection.get(arguments["key"])
            return _ok({"key": arguments["key"], "content": result.content_as[dict]})
        except Exception as exc:
            return _err(str(exc))

    # ── cb_upsert ────────────────────────────────────────────────────────
    if name == "cb_upsert":
        try:
            result = collection.upsert(arguments["key"], arguments["document"])
            return _ok({"key": arguments["key"], "cas": str(result.cas), "operation": "upsert"})
        except Exception as exc:
            return _err(str(exc))

    # ── cb_insert ────────────────────────────────────────────────────────
    if name == "cb_insert":
        try:
            result = collection.insert(arguments["key"], arguments["document"])
            return _ok({"key": arguments["key"], "cas": str(result.cas), "operation": "insert"})
        except Exception as exc:
            return _err(str(exc))

    # ── cb_replace ───────────────────────────────────────────────────────
    if name == "cb_replace":
        try:
            result = collection.replace(arguments["key"], arguments["document"])
            return _ok({"key": arguments["key"], "cas": str(result.cas), "operation": "replace"})
        except Exception as exc:
            return _err(str(exc))

    # ── cb_delete ────────────────────────────────────────────────────────
    if name == "cb_delete":
        try:
            collection.remove(arguments["key"])
            return _ok({"key": arguments["key"], "operation": "delete", "status": "ok"})
        except Exception as exc:
            return _err(str(exc))

    # ── cb_get_multi ─────────────────────────────────────────────────────
    if name == "cb_get_multi":
        try:
            results = collection.get_multi(arguments["keys"])
            docs = {}
            for k, v in results.results.items():
                if v.success:
                    docs[k] = {"content": v.content_as[dict]}
                else:
                    docs[k] = {"error": str(v.exception)}
            return _ok(docs)
        except Exception as exc:
            return _err(str(exc))

    # ── cb_query ─────────────────────────────────────────────────────────
    if name == "cb_query":
        try:
            from couchbase.options import QueryOptions

            params   = arguments.get("params") or {}
            readonly = arguments.get("readonly", False)
            opts     = QueryOptions(named_parameters=params, read_only=readonly)
            result   = cluster.query(arguments["statement"], opts)
            rows     = [row for row in result]
            meta     = result.metadata()
            return _ok({
                "rows":     rows,
                "count":    len(rows),
                "metrics": {
                    "elapsed":   str(meta.metrics().elapsed_time()),
                    "execution": str(meta.metrics().execution_time()),
                    "result_count": meta.metrics().result_count(),
                },
            })
        except Exception as exc:
            return _err(str(exc))

    # ── cb_fts_search ────────────────────────────────────────────────────
    if name == "cb_fts_search":
        try:
            from couchbase.search import SearchQuery, SearchOptions, TermQuery, MatchQuery
            from couchbase.vector_search import VectorQuery, VectorSearch

            index   = arguments["index_name"]
            q_str   = arguments["query"]
            limit   = arguments.get("limit", 10)
            fields  = arguments.get("fields", [])
            hl      = arguments.get("highlight", False)

            search_query = MatchQuery(q_str)

            opts_kwargs: dict[str, Any] = {"limit": limit}
            if fields:
                opts_kwargs["fields"] = fields
            if hl:
                from couchbase.search import HighlightStyle
                opts_kwargs["highlight_style"] = HighlightStyle.Html
                opts_kwargs["highlight_fields"] = fields or ["*"]

            opts   = SearchOptions(**opts_kwargs)
            result = cluster.search(index, search_query, opts)
            hits   = []
            for row in result:
                hit: dict[str, Any] = {"id": row.id, "score": row.score}
                if row.fields:
                    hit["fields"] = row.fields
                if hasattr(row, "locations") and row.locations:
                    hit["locations"] = str(row.locations)
                if hasattr(row, "fragments") and row.fragments:
                    hit["fragments"] = row.fragments
                hits.append(hit)

            meta = result.metadata()
            return _ok({
                "hits":       hits,
                "total_hits": meta.metrics().total_rows(),
                "took_ms":    meta.metrics().took().total_seconds() * 1000,
            })
        except Exception as exc:
            return _err(str(exc))

    return _err(f"Unknown tool: {name}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
