# scope-enforcement fix — celticht32/MCP-Couchbase

Fixes the incomplete commit at HEAD 5f9dddd:
  1. The committed auth/scope_gate.py was the buggy version (read/write
     classification disagreed with server.py's read-only filter -> cb_query /
     cb_analytics_query would be visible-but-uninvokable for read-scoped tokens).
  2. Nothing in server.py called scope_gate -> the gate was inert dead code.

## What's in this archive
- auth/scope_gate.py   — corrected module (classification reuses the server's
                         own read-only predicate via configure(); 0 mismatches
                         across all 167 tools).
- server.py            — fully patched: import, configure() wiring, per-tool
                         scope check in call_tool (ordered scope -> confirm ->
                         dispatch), _ScopeAuthMiddleware, middleware registration,
                         refreshed _main_http docstring, fail-open startup warning.
- server.py.diff       — unified diff vs committed server.py (review before commit).
- scope_gate.py.diff   — unified diff vs committed scope_gate.py.

## Install (Windows / PowerShell)
Extract, then copy the two files over the committed ones. Confirm your repo root
path first — adjust C:\path\to\MCP-Couchbase below.

    copy /Y auth\scope_gate.py C:\path\to\MCP-Couchbase\auth\scope_gate.py
    copy /Y server.py          C:\path\to\MCP-Couchbase\server.py

## Env vars (all optional; defaults preserve current behavior)
- CB_MCP_SCOPE_READ          default couchbase-mcp:read
- CB_MCP_SCOPE_WRITE         default couchbase-mcp:write
- CB_MCP_HTTP_REQUIRE_AUTH   default false; true = reject missing/invalid Bearer with 401

OIDC validation reuses auth/oidc.py (OAUTH_ISSUER, JWKS, etc.).

## Verified in this session (mcp 1.28.0, isolated venv)
- read/write split matches server.py read-only filter for ALL 167 tools (0 mismatches)
- read token reaches every read-side tool, denied on every write-side; write token reverse
- stdio (no token) allows all; require=true 401 paths; contextvar cleared in finally
- no token logging; 401 detail = exception type name only; exact-match scope compare

## NOT verified (needs your machine)
That the contextvar set in _ScopeAuthMiddleware reaches call_tool across the
streamable-HTTP transport's asyncio task boundary (app.run runs under
asyncio.gather alongside uvicorn). Test: run HTTP with CB_MCP_HTTP_REQUIRE_AUTH=true
and a read-only token; if a write tool still executes (claims arriving as None in
call_tool), switch the bare contextvar for a per-MCP-session-id store.

## mcp version note
Verified against mcp 1.28.0. Repo pins mcp>=1.0.0 (a floor). The only library
surface touched is tool.annotations.readOnlyHint, which handlers already use, so
risk below 1.28.0 is low but untested there.

License: MIT — Copyright (c) 2026 Chris Ahrendt
