"""handlers/search_admin.py – Full-Text Search index administration."""

from __future__ import annotations
import json
from mcp.types import Tool, TextContent
from .shared import admin_request, admin_request_json, ok

TOOLS: list[Tool] = [
    Tool(name="admin_fts_index_list",
         description="List all Full-Text Search indexes.",
         inputSchema={"type": "object", "properties": {}}),

    Tool(name="admin_fts_index_get",
         description="Get the definition of a specific FTS index.",
         inputSchema={"type": "object",
                      "properties": {"index_name": {"type": "string"}},
                      "required": ["index_name"]}),

    Tool(name="admin_fts_index_create",
         description=(
             "Create or update an FTS index. "
             "Pass the full index definition as a JSON object in 'definition'. "
             "Minimum required keys: name, type (fulltext-index), sourceName (bucket)."
         ),
         inputSchema={"type": "object",
                      "properties": {
                          "index_name": {"type": "string"},
                          "definition": {"type": "object",
                                         "description": "Full FTS index JSON definition"},
                      },
                      "required": ["index_name", "definition"]}),

    Tool(name="admin_fts_index_delete",
         description="Delete a Full-Text Search index.",
         inputSchema={"type": "object",
                      "properties": {"index_name": {"type": "string"}},
                      "required": ["index_name"]}),

    Tool(name="admin_fts_index_stats",
         description="Get statistics for a specific FTS index.",
         inputSchema={"type": "object",
                      "properties": {"index_name": {"type": "string"}},
                      "required": ["index_name"]}),

    Tool(name="admin_fts_index_doc_count",
         description="Get the document count for an FTS index.",
         inputSchema={"type": "object",
                      "properties": {"index_name": {"type": "string"}},
                      "required": ["index_name"]}),

    Tool(name="admin_fts_index_ingest_pause",
         description="Pause document ingestion for an FTS index.",
         inputSchema={"type": "object",
                      "properties": {"index_name": {"type": "string"}},
                      "required": ["index_name"]}),

    Tool(name="admin_fts_index_ingest_resume",
         description="Resume document ingestion for an FTS index.",
         inputSchema={"type": "object",
                      "properties": {"index_name": {"type": "string"}},
                      "required": ["index_name"]}),

    Tool(name="admin_fts_settings_get",
         description="Get global FTS (Search service) settings.",
         inputSchema={"type": "object", "properties": {}}),
]


def handle(name: str, args: dict) -> list[TextContent]:
    if name == "admin_fts_index_list":
        return ok(admin_request("GET", "/api/index"))

    if name == "admin_fts_index_get":
        return ok(admin_request("GET", f"/api/index/{args['index_name']}"))

    if name == "admin_fts_index_create":
        defn = args["definition"]
        defn.setdefault("name", args["index_name"])
        return ok(admin_request_json("PUT", f"/api/index/{args['index_name']}", payload=defn))

    if name == "admin_fts_index_delete":
        return ok(admin_request("DELETE", f"/api/index/{args['index_name']}"))

    if name == "admin_fts_index_stats":
        return ok(admin_request("GET", f"/api/index/{args['index_name']}/stats"))

    if name == "admin_fts_index_doc_count":
        return ok(admin_request("GET", f"/api/index/{args['index_name']}/count"))

    if name == "admin_fts_index_ingest_pause":
        return ok(admin_request("POST", f"/api/index/{args['index_name']}/ingestControl/pause"))

    if name == "admin_fts_index_ingest_resume":
        return ok(admin_request("POST", f"/api/index/{args['index_name']}/ingestControl/resume"))

    if name == "admin_fts_settings_get":
        return ok(admin_request("GET", "/api/cfg"))

    raise ValueError(f"Unknown FTS admin tool: {name}")
