"""handlers/collections.py — Scopes and Collections admin tools.

Changes from upstream:
- Phase 1: ToolAnnotations. Scope/collection deletes marked destructive.
- Phase 2: Structured err() returns.
"""

from __future__ import annotations

from mcp.types import Tool, TextContent, ToolAnnotations

from .shared import admin_request, err, ok


TOOLS: list[Tool] = [
    Tool(
        name="admin_scope_list",
        description="List all scopes (and their collections) in a bucket.",
        inputSchema={
            "type": "object",
            "properties": {"bucket_name": {"type": "string"}},
            "required": ["bucket_name"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True,
        ),
    ),
    Tool(
        name="admin_scope_create",
        description="Create a new scope in a bucket.",
        inputSchema={
            "type": "object",
            "properties": {
                "bucket_name": {"type": "string"},
                "scope_name": {"type": "string"},
            },
            "required": ["bucket_name", "scope_name"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False,
        ),
    ),
    Tool(
        name="admin_scope_delete",
        description="Delete a scope and all its collections. IRREVERSIBLE. Requires confirm:true.",
        inputSchema={
            "type": "object",
            "properties": {
                "bucket_name": {"type": "string"},
                "scope_name": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["bucket_name", "scope_name"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=True,
        ),
    ),
    Tool(
        name="admin_collection_create",
        description="Create a new collection inside a scope.",
        inputSchema={
            "type": "object",
            "properties": {
                "bucket_name": {"type": "string"},
                "scope_name": {"type": "string"},
                "collection_name": {"type": "string"},
                "maxTTL": {
                    "type": "integer",
                    "description": "Max document TTL in seconds (0 = inherit)",
                },
            },
            "required": ["bucket_name", "scope_name", "collection_name"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False,
        ),
    ),
    Tool(
        name="admin_collection_delete",
        description="Delete a collection from a scope. IRREVERSIBLE. Requires confirm:true.",
        inputSchema={
            "type": "object",
            "properties": {
                "bucket_name": {"type": "string"},
                "scope_name": {"type": "string"},
                "collection_name": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["bucket_name", "scope_name", "collection_name"],
        },
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=True,
        ),
    ),
]


def handle(name: str, args: dict) -> list[TextContent]:
    try:
        b = args.get("bucket_name", "")
        s = args.get("scope_name", "")
        c = args.get("collection_name", "")

        if name == "admin_scope_list":
            return ok(admin_request("GET", f"/pools/default/buckets/{b}/scopes/"))

        if name == "admin_scope_create":
            return ok(
                admin_request(
                    "POST", f"/pools/default/buckets/{b}/scopes", data={"name": s}
                )
            )

        if name == "admin_scope_delete":
            return ok(admin_request("DELETE", f"/pools/default/buckets/{b}/scopes/{s}"))

        if name == "admin_collection_create":
            data = {"name": c}
            if args.get("maxTTL") is not None:
                data["maxTTL"] = str(args["maxTTL"])
            return ok(
                admin_request(
                    "POST",
                    f"/pools/default/buckets/{b}/scopes/{s}/collections",
                    data=data,
                )
            )

        if name == "admin_collection_delete":
            return ok(
                admin_request(
                    "DELETE", f"/pools/default/buckets/{b}/scopes/{s}/collections/{c}"
                )
            )

        return err(f"Unknown collection tool: {name}", tool=name)

    except Exception as exc:
        return err(f"{type(exc).__name__}: {exc}", tool=name, args=args)
