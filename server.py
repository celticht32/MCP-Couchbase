"""
Couchbase MCP Server (Extended)
================================
Exposes the full Couchbase data-plane AND admin REST API as MCP tools.

Tool categories
───────────────
  Data        - CRUD, N1QL, FTS search, ping          (prefix: cb_)
  Buckets     - create/update/delete/flush/compact     (prefix: admin_bucket_)
  Collections - scopes and collections                 (prefix: admin_scope_ / admin_collection_)
  Security    - users, groups, RBAC, audit, certs      (prefix: admin_user_ / admin_group_ / admin_*)
  Cluster     - nodes, rebalance, failover, groups     (prefix: admin_cluster_ / admin_node_ / admin_*)
  XDCR        - references and replications            (prefix: admin_xdcr_)
  Indexes     - GSI create/drop/build, settings        (prefix: admin_index_)
  FTS Admin   - FTS index CRUD + stats                 (prefix: admin_fts_index_ / admin_fts_*)
  Stats       - metrics, events, internal settings     (prefix: admin_stats_ / admin_*)

Environment variables
─────────────────────
  CB_CONNECTION_STRING   couchbase://localhost
  CB_USERNAME            Administrator
  CB_PASSWORD            password
  CB_BUCKET              default
  CB_SCOPE               _default
  CB_COLLECTION          _default
  CB_MGMT_PORT           8091   (override for non-standard HTTP management port)
"""

import asyncio
from mcp.server       import Server
from mcp.server.stdio import stdio_server
from mcp.types        import Tool, TextContent

# Import all handler modules
from handlers import (
    data,
    buckets,
    collections,
    security,
    cluster,
    xdcr,
    indexes,
    search_admin,
    stats,
)

# Aggregate tool registry
_ALL_TOOLS: list[Tool] = (
    data.TOOLS
    + buckets.TOOLS
    + collections.TOOLS
    + security.TOOLS
    + cluster.TOOLS
    + xdcr.TOOLS
    + indexes.TOOLS
    + search_admin.TOOLS
    + stats.TOOLS
)

# Map tool name -> handler module
_HANDLERS = {
    **{t.name: data         for t in data.TOOLS},
    **{t.name: buckets      for t in buckets.TOOLS},
    **{t.name: collections  for t in collections.TOOLS},
    **{t.name: security     for t in security.TOOLS},
    **{t.name: cluster      for t in cluster.TOOLS},
    **{t.name: xdcr         for t in xdcr.TOOLS},
    **{t.name: indexes      for t in indexes.TOOLS},
    **{t.name: search_admin for t in search_admin.TOOLS},
    **{t.name: stats        for t in stats.TOOLS},
}

# MCP server
app = Server("couchbase-mcp")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return _ALL_TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    handler = _HANDLERS.get(name)
    if handler is None:
        from handlers.shared import err
        return err(f"Unknown tool: {name}")

    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, handler.handle, name, arguments)
    except Exception as exc:
        from handlers.shared import err
        return err(str(exc))


# Entry point
async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
