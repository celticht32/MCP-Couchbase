"""handlers/data.py – CRUD, N1QL, Full-Text Search, and ping tools."""

from __future__ import annotations
from typing import Any
from mcp.types import Tool, TextContent
from .shared import get_sdk_connection, ok, err


# ── Tool definitions ─────────────────────────────────────────────────────────
TOOLS: list[Tool] = [
    Tool(name="cb_ping",
         description="Ping the Couchbase cluster to verify SDK + service connectivity.",
         inputSchema={"type": "object", "properties": {}}),

    Tool(name="cb_get",
         description="Get a document by its key.",
         inputSchema={"type": "object",
                      "properties": {"key": {"type": "string"}},
                      "required": ["key"]}),

    Tool(name="cb_upsert",
         description="Insert or replace a document.",
         inputSchema={"type": "object",
                      "properties": {"key": {"type": "string"},
                                     "document": {"type": "object"}},
                      "required": ["key", "document"]}),

    Tool(name="cb_insert",
         description="Insert a new document (fails if key already exists).",
         inputSchema={"type": "object",
                      "properties": {"key": {"type": "string"},
                                     "document": {"type": "object"}},
                      "required": ["key", "document"]}),

    Tool(name="cb_replace",
         description="Replace an existing document (fails if key does not exist).",
         inputSchema={"type": "object",
                      "properties": {"key": {"type": "string"},
                                     "document": {"type": "object"}},
                      "required": ["key", "document"]}),

    Tool(name="cb_delete",
         description="Delete a document by key.",
         inputSchema={"type": "object",
                      "properties": {"key": {"type": "string"}},
                      "required": ["key"]}),

    Tool(name="cb_get_multi",
         description="Retrieve multiple documents by a list of keys.",
         inputSchema={"type": "object",
                      "properties": {"keys": {"type": "array",
                                              "items": {"type": "string"}}},
                      "required": ["keys"]}),

    Tool(name="cb_query",
         description="Run a N1QL / SQL++ query. Use $name style named parameters.",
         inputSchema={"type": "object",
                      "properties": {
                          "statement": {"type": "string"},
                          "params":    {"type": "object"},
                          "readonly":  {"type": "boolean"}},
                      "required": ["statement"]}),

    Tool(name="cb_fts_search",
         description="Run a full-text search query against a Couchbase FTS index.",
         inputSchema={"type": "object",
                      "properties": {
                          "index_name": {"type": "string"},
                          "query":      {"type": "string"},
                          "limit":      {"type": "integer"},
                          "fields":     {"type": "array", "items": {"type": "string"}},
                          "highlight":  {"type": "boolean"}},
                      "required": ["index_name", "query"]}),
]


# ── Handlers ─────────────────────────────────────────────────────────────────
def handle(name: str, args: dict) -> list[TextContent]:
    cluster, _, collection = get_sdk_connection()

    if name == "cb_ping":
        result   = cluster.ping()
        services = {}
        for svc, endpoints in result.endpoints.items():
            services[str(svc)] = [
                {"id": e.id, "state": str(e.state), "remote": e.remote}
                for e in endpoints
            ]
        return ok({"status": "ok", "services": services})

    if name == "cb_get":
        r = collection.get(args["key"])
        return ok({"key": args["key"], "content": r.content_as[dict]})

    if name == "cb_upsert":
        r = collection.upsert(args["key"], args["document"])
        return ok({"key": args["key"], "cas": str(r.cas), "operation": "upsert"})

    if name == "cb_insert":
        r = collection.insert(args["key"], args["document"])
        return ok({"key": args["key"], "cas": str(r.cas), "operation": "insert"})

    if name == "cb_replace":
        r = collection.replace(args["key"], args["document"])
        return ok({"key": args["key"], "cas": str(r.cas), "operation": "replace"})

    if name == "cb_delete":
        collection.remove(args["key"])
        return ok({"key": args["key"], "operation": "delete", "status": "ok"})

    if name == "cb_get_multi":
        results = collection.get_multi(args["keys"])
        docs    = {}
        for k, v in results.results.items():
            docs[k] = {"content": v.content_as[dict]} if v.success else {"error": str(v.exception)}
        return ok(docs)

    if name == "cb_query":
        from couchbase.options import QueryOptions
        params   = args.get("params") or {}
        readonly = args.get("readonly", False)
        result   = cluster.query(args["statement"],
                                 QueryOptions(named_parameters=params, read_only=readonly))
        rows = list(result)
        meta = result.metadata()
        return ok({
            "rows":    rows,
            "count":   len(rows),
            "metrics": {
                "elapsed":      str(meta.metrics().elapsed_time()),
                "execution":    str(meta.metrics().execution_time()),
                "result_count": meta.metrics().result_count(),
            },
        })

    if name == "cb_fts_search":
        from couchbase.search import SearchOptions, MatchQuery
        limit  = args.get("limit", 10)
        fields = args.get("fields", [])
        hl     = args.get("highlight", False)
        kw: dict[str, Any] = {"limit": limit}
        if fields:
            kw["fields"] = fields
        if hl:
            from couchbase.search import HighlightStyle
            kw["highlight_style"]  = HighlightStyle.Html
            kw["highlight_fields"] = fields or ["*"]
        result = cluster.search(args["index_name"], MatchQuery(args["query"]),
                                SearchOptions(**kw))
        hits = []
        for row in result:
            h: dict[str, Any] = {"id": row.id, "score": row.score}
            if row.fields:    h["fields"]    = row.fields
            if getattr(row, "fragments", None): h["fragments"] = row.fragments
            hits.append(h)
        meta = result.metadata()
        return ok({
            "hits":       hits,
            "total_hits": meta.metrics().total_rows(),
            "took_ms":    meta.metrics().took().total_seconds() * 1000,
        })

    raise ValueError(f"Unknown data tool: {name}")
