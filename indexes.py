"""handlers/indexes.py – Query Service index management via N1QL system catalog + Index REST API."""

from __future__ import annotations
from mcp.types import Tool, TextContent
from .shared import get_sdk_connection, admin_request, ok

TOOLS: list[Tool] = [
    Tool(name="admin_index_list",
         description="List all GSI indexes (optionally filtered by bucket/scope/collection).",
         inputSchema={"type": "object",
                      "properties": {
                          "bucket_name":     {"type": "string"},
                          "scope_name":      {"type": "string"},
                          "collection_name": {"type": "string"},
                      }}),

    Tool(name="admin_index_create",
         description=(
             "Create a GSI index using N1QL CREATE INDEX. "
             "Provide the full CREATE INDEX statement, or use the helper fields."
         ),
         inputSchema={"type": "object",
                      "properties": {
                          "statement": {
                              "type": "string",
                              "description": "Full CREATE INDEX N1QL statement (preferred)"
                          },
                          "index_name":      {"type": "string"},
                          "bucket_name":     {"type": "string"},
                          "scope_name":      {"type": "string"},
                          "collection_name": {"type": "string"},
                          "fields":          {"type": "array", "items": {"type": "string"},
                                             "description": "Fields to index"},
                          "is_primary":      {"type": "boolean"},
                          "num_replica":     {"type": "integer"},
                          "defer_build":     {"type": "boolean"},
                      }}),

    Tool(name="admin_index_drop",
         description="Drop a GSI index.",
         inputSchema={"type": "object",
                      "properties": {
                          "statement":       {"type": "string",
                                             "description": "Full DROP INDEX statement (preferred)"},
                          "index_name":      {"type": "string"},
                          "bucket_name":     {"type": "string"},
                          "scope_name":      {"type": "string"},
                          "collection_name": {"type": "string"},
                          "is_primary":      {"type": "boolean"},
                      }}),

    Tool(name="admin_index_build",
         description="Build deferred indexes on a bucket.",
         inputSchema={"type": "object",
                      "properties": {
                          "bucket_name":  {"type": "string"},
                          "index_names":  {"type": "array", "items": {"type": "string"},
                                          "description": "List of deferred index names to build"},
                      },
                      "required": ["bucket_name", "index_names"]}),

    Tool(name="admin_index_settings_get",
         description="Get Index Service settings (memory, threads, log level, etc.).",
         inputSchema={"type": "object", "properties": {}}),

    Tool(name="admin_index_settings_set",
         description=(
             "Update Index Service settings. Common keys: indexerThreads, memorySnapshotInterval, "
             "stableSnapshotInterval, maxRollbackPoints, logLevel."
         ),
         inputSchema={"type": "object",
                      "properties": {
                          "indexerThreads":          {"type": "integer"},
                          "memorySnapshotInterval":  {"type": "integer"},
                          "stableSnapshotInterval":  {"type": "integer"},
                          "maxRollbackPoints":       {"type": "integer"},
                          "logLevel":                {"type": "string",
                                                     "enum": ["silent","fatal","error",
                                                              "warn","info","verbose","timing","debug","trace"]},
                      }}),
]


def _run_n1ql(statement: str) -> list[TextContent]:
    from couchbase.options import QueryOptions
    cluster, _, _ = get_sdk_connection()
    result = cluster.query(statement, QueryOptions())
    rows   = list(result)
    return ok({"rows": rows, "count": len(rows)})


def handle(name: str, args: dict) -> list[TextContent]:
    if name == "admin_index_list":
        parts  = ["SELECT * FROM system:indexes"]
        wheres = []
        if args.get("bucket_name"):
            wheres.append(f"bucket_id = '{args['bucket_name']}'")
        if args.get("scope_name"):
            wheres.append(f"scope_id = '{args['scope_name']}'")
        if args.get("collection_name"):
            wheres.append(f"keyspace_id = '{args['collection_name']}'")
        if wheres:
            parts.append("WHERE " + " AND ".join(wheres))
        return _run_n1ql(" ".join(parts))

    if name == "admin_index_create":
        if args.get("statement"):
            return _run_n1ql(args["statement"])
        # Build statement from helper fields
        if args.get("is_primary"):
            bucket = args["bucket_name"]
            scope  = args.get("scope_name", "_default")
            coll   = args.get("collection_name", "_default")
            idx    = args.get("index_name", "#primary")
            stmt   = f"CREATE PRIMARY INDEX `{idx}` ON `{bucket}`.`{scope}`.`{coll}`"
        else:
            bucket = args["bucket_name"]
            scope  = args.get("scope_name", "_default")
            coll   = args.get("collection_name", "_default")
            fields = ", ".join(f"`{f}`" for f in args.get("fields", []))
            idx    = args["index_name"]
            stmt   = f"CREATE INDEX `{idx}` ON `{bucket}`.`{scope}`.`{coll}` ({fields})"
        withs = []
        if args.get("num_replica"):  withs.append(f'"num_replica": {args["num_replica"]}')
        if args.get("defer_build"):  withs.append('"defer_build": true')
        if withs:
            stmt += " WITH {" + ", ".join(withs) + "}"
        return _run_n1ql(stmt)

    if name == "admin_index_drop":
        if args.get("statement"):
            return _run_n1ql(args["statement"])
        bucket = args["bucket_name"]
        scope  = args.get("scope_name", "_default")
        coll   = args.get("collection_name", "_default")
        if args.get("is_primary"):
            stmt = f"DROP PRIMARY INDEX ON `{bucket}`.`{scope}`.`{coll}`"
        else:
            idx  = args["index_name"]
            stmt = f"DROP INDEX `{idx}` ON `{bucket}`.`{scope}`.`{coll}`"
        return _run_n1ql(stmt)

    if name == "admin_index_build":
        bucket  = args["bucket_name"]
        indexes = ", ".join(f"`{i}`" for i in args["index_names"])
        stmt    = f"BUILD INDEX ON `{bucket}` ({indexes})"
        return _run_n1ql(stmt)

    if name == "admin_index_settings_get":
        return ok(admin_request("GET", "/settings/indexes"))

    if name == "admin_index_settings_set":
        data = {k: str(v) for k, v in args.items() if v is not None}
        return ok(admin_request("POST", "/settings/indexes", data=data))

    raise ValueError(f"Unknown index tool: {name}")
