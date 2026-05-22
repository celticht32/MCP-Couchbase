"""
Couchbase MCP Server (Extended, hardened)
=========================================

Exposes the full Couchbase data-plane AND admin REST API as MCP tools, with
defense-in-depth safety primitives modeled after the official Couchbase MCP.

Tool categories (all upstream names preserved)
──────────────────────────────────────────────
  Data       - CRUD, N1QL, FTS search, ping     (cb_*)
  Buckets    - create/update/delete/flush       (admin_bucket_*)
  Collections- scopes and collections           (admin_scope_*, admin_collection_*)
  Security   - users, groups, RBAC, audit       (admin_user_*, admin_group_*, admin_*)
  Cluster    - nodes, rebalance, failover       (admin_cluster_*, admin_node_*, admin_*)
  XDCR       - references and replications      (admin_xdcr_*)
  Indexes    - GSI create/drop/build, settings  (admin_index_*)
  FTS Admin  - FTS index CRUD + stats           (admin_fts_*)
  Stats      - metrics, events, internal        (admin_stats_*, admin_*)
  Diagnostics- schema, advisor, EXPLAIN, perf   (cb_get_schema_for_collection,
                                                  cb_index_advisor, cb_explain_query,
                                                  cb_perf_*)
  8.x-only   - vector indexes, lock, conflicts  (admin_vector_index_create_*,
                                                  admin_user_lock/unlock/create_temporary,
                                                  admin_xdcr_conflict_log_query,
                                                  cb_perf_by_user)
  Extended   - transactions, Analytics, Backup  (cb_transaction_run,
                                                  cb_analytics_query, admin_backup_*)
  Eventing   - function lifecycle, deploy, stats (admin_eventing_*)
  Synonyms   - FTS synonym set documents (8.x)   (cb_fts_synonym_*)
  Encryption - DARE + KMIP                       (admin_encryption_*, admin_kmip_*)
  Capella v4 - SaaS control plane (read-only)    (capella_*)

Environment variables
─────────────────────

CONNECTION
  CB_CONNECTION_STRING         couchbase://localhost (use couchbases:// for TLS)
  CB_USERNAME                  (required unless using mTLS)
  CB_PASSWORD                  (required unless using mTLS)
  CB_BUCKET                    default
  CB_SCOPE                     _default
  CB_COLLECTION                _default
  CB_MGMT_PORT                 8091 (or 18091 for TLS; Capella self-managed admin)

mTLS / TLS  (Phase 3)
  CB_CLIENT_CERT_PATH          path to client cert PEM (presence enables mTLS)
  CB_CLIENT_KEY_PATH           path to client key PEM
  CB_CA_CERT_PATH              path to CA cert for self-signed self-managed clusters
  CB_MCP_TLS_INSECURE          false   set true to skip TLS verification (dev only)

SAFETY  (Phase 1)
  CB_MCP_READ_ONLY_MODE        true    when true, write tools are NOT loaded
  CB_MCP_DISABLED_TOOLS                comma list, or path to file with one name per line
  CB_MCP_CONFIRMATION_REQUIRED_TOOLS   additional tools that require confirm:true
  CB_MCP_ELICITATION_HINTS     true    include hint text in confirmation errors

NETWORK  (Phase 2)
  CB_MCP_HTTP_RETRIES          3       max attempts for admin HTTP calls
  CB_MCP_HTTP_TIMEOUT          30      per-request timeout in seconds

TRANSPORT  (Phase 3)
  CB_MCP_TRANSPORT             stdio   one of: stdio, http
  CB_MCP_HOST                  127.0.0.1  for http transport
  CB_MCP_PORT                  8000       for http transport

Compatibility
─────────────
All tool names from the upstream celticht32 server are preserved. New tools
may be added in future; new optional `confirm` arguments are introduced on
destructive tools but do not change existing tool semantics.
"""

from __future__ import annotations

import asyncio
import os
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from handlers import (
    buckets,
    capella,
    cluster,
    collections,
    data,
    diagnostics,
    eight_x,
    encryption,
    eventing,
    extended,
    indexes,
    search_admin,
    security,
    stats,
    synonyms,
    xdcr,
)
from handlers.shared import (
    DISABLED_TOOLS,
    READ_ONLY_MODE,
    err,
    get_confirmation_required,
    require_confirmation,
)


# ── Aggregate tool registry ──────────────────────────────────────────────────

_RAW_TOOLS: list[Tool] = (
    data.TOOLS
    + buckets.TOOLS
    + collections.TOOLS
    + security.TOOLS
    + cluster.TOOLS
    + xdcr.TOOLS
    + indexes.TOOLS
    + search_admin.TOOLS
    + stats.TOOLS
    + diagnostics.TOOLS
    + eight_x.TOOLS
    + extended.TOOLS
    + eventing.TOOLS
    + synonyms.TOOLS
    + encryption.TOOLS
    + capella.TOOLS
)

_HANDLERS = {
    **{t.name: data for t in data.TOOLS},
    **{t.name: buckets for t in buckets.TOOLS},
    **{t.name: collections for t in collections.TOOLS},
    **{t.name: security for t in security.TOOLS},
    **{t.name: cluster for t in cluster.TOOLS},
    **{t.name: xdcr for t in xdcr.TOOLS},
    **{t.name: indexes for t in indexes.TOOLS},
    **{t.name: search_admin for t in search_admin.TOOLS},
    **{t.name: stats for t in stats.TOOLS},
    **{t.name: diagnostics for t in diagnostics.TOOLS},
    **{t.name: eight_x for t in eight_x.TOOLS},
    **{t.name: extended for t in extended.TOOLS},
    **{t.name: eventing for t in eventing.TOOLS},
    **{t.name: synonyms for t in synonyms.TOOLS},
    **{t.name: encryption for t in encryption.TOOLS},
    **{t.name: capella for t in capella.TOOLS},
}

# Tools that stay loaded in read-only mode despite destructiveHint=true,
# because they enforce read-only behavior internally (e.g. cb_query rejects DML).
_ALWAYS_LOADED_IN_READ_ONLY: set[str] = {"cb_query", "cb_analytics_query"}


def _is_read_only(t: Tool) -> bool:
    """A tool is read-only if its annotation says so."""
    return bool(t.annotations and t.annotations.readOnlyHint)


def _filter_tools(raw_tools: list[Tool]) -> list[Tool]:
    """Apply read-only mode and disabled-tools filters."""
    filtered: list[Tool] = []
    for t in raw_tools:
        if t.name in DISABLED_TOOLS:
            continue
        if READ_ONLY_MODE:
            if not _is_read_only(t) and t.name not in _ALWAYS_LOADED_IN_READ_ONLY:
                continue
        filtered.append(t)
    return filtered


_TOOLS: list[Tool] = _filter_tools(_RAW_TOOLS)

# Default confirmation set: every destructive tool that survived the filter.
_DEFAULT_CONFIRMATION = {
    t.name for t in _TOOLS if t.annotations and t.annotations.destructiveHint
}
_CONFIRMATION_REQUIRED: set[str] = get_confirmation_required(_DEFAULT_CONFIRMATION)
# cb_query and cb_analytics_query are "destructive in spec" but have internal
# DML blocking; don't double-gate.
_CONFIRMATION_REQUIRED.discard("cb_query")
_CONFIRMATION_REQUIRED.discard("cb_analytics_query")


# ── MCP server ───────────────────────────────────────────────────────────────

app = Server("couchbase-mcp")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return _TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    arguments = dict(arguments or {})

    handler = _HANDLERS.get(name)
    if handler is None:
        return err(f"Unknown tool: {name}", tool=name, hint="Tool may be disabled or unloaded.")

    # Tool must also be in the currently exposed list.
    if name not in {t.name for t in _TOOLS}:
        return err(
            f"Tool {name} is not enabled in this server configuration.",
            tool=name,
            hint=(
                "It may be unloaded because CB_MCP_READ_ONLY_MODE=true or it "
                "appears in CB_MCP_DISABLED_TOOLS."
            ),
        )

    # Confirmation gate for destructive tools.
    in_confirm_set = name in _CONFIRMATION_REQUIRED
    msg = require_confirmation(name, arguments, in_confirm_set)
    if msg:
        return err(msg, tool=name, args=arguments, requires_confirmation=True)

    # Strip the confirm key so it never reaches REST/SDK calls as a stray field.
    arguments.pop("confirm", None)

    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, handler.handle, name, arguments)
    except Exception as exc:
        return err(f"{type(exc).__name__}: {exc}", tool=name, args=arguments)


# ── Startup banner ───────────────────────────────────────────────────────────


def _startup_banner() -> None:
    msg = (
        f"[couchbase-mcp] tools loaded: {len(_TOOLS)} of {len(_RAW_TOOLS)} "
        f"(read_only={READ_ONLY_MODE}, disabled={len(DISABLED_TOOLS)}, "
        f"confirmation_required={len(_CONFIRMATION_REQUIRED)})"
    )
    # Banner goes to stderr so it does not pollute stdio MCP framing.
    print(msg, file=sys.stderr, flush=True)


# ── Transport selection ──────────────────────────────────────────────────────


async def _main_stdio() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


async def _main_http() -> None:
    """Streamable HTTP transport. Note: this mode does not include authorization;
    deploy behind a reverse proxy or authenticated network."""
    try:
        from mcp.server.streamable_http import StreamableHTTPServerTransport
    except ImportError:
        print(
            "[couchbase-mcp] Streamable HTTP transport requires a newer mcp library. "
            "Falling back to stdio.",
            file=sys.stderr,
        )
        await _main_stdio()
        return

    host = os.environ.get("CB_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("CB_MCP_PORT", "8000"))
    print(
        f"[couchbase-mcp] HTTP transport listening on http://{host}:{port}/mcp",
        file=sys.stderr,
        flush=True,
    )
    # The exact instantiation API for StreamableHTTPServerTransport varies
    # across mcp library versions. We delegate to a thin runner so the user
    # can adapt this in their environment if the API has shifted.
    try:
        import uvicorn  # type: ignore
        from starlette.applications import Starlette
        from starlette.routing import Mount

        transport = StreamableHTTPServerTransport(mcp_session_id=None)
        starlette_app = Starlette(routes=[Mount("/mcp", app=transport.handle_request)])
        config = uvicorn.Config(starlette_app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)

        async def run_server():
            async with transport.connect() as (rs, ws):
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(server.serve())
                    tg.create_task(app.run(rs, ws, app.create_initialization_options()))

        await run_server()
    except ImportError as exc:
        print(
            f"[couchbase-mcp] HTTP transport requires uvicorn and starlette: {exc}. "
            "Install: pip install uvicorn starlette. Falling back to stdio.",
            file=sys.stderr,
        )
        await _main_stdio()


async def main() -> None:
    _startup_banner()
    transport = os.environ.get("CB_MCP_TRANSPORT", "stdio").lower()
    if transport in ("http", "streamable_http", "streamablehttp"):
        await _main_http()
    else:
        await _main_stdio()


if __name__ == "__main__":
    asyncio.run(main())
