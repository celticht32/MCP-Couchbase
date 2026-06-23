# server.py changes — per-tool OAuth scope enforcement

Three edits. Concise diffs, no file rewrite. Line numbers are from HEAD 5f37e5e.

## Edit 1 — import (after line 81, with the other `from mcp...` imports)

```python
from auth.scope_gate import check_scope, set_token_claims, clear_token_claims
```

## Edit 2 — enforce in call_tool

Insert immediately AFTER the `if name not in {t.name for t in _TOOLS}:` block
(after its closing `)` around line 218) and BEFORE the confirmation gate:

```python
    # Per-tool OAuth scope enforcement. No-op on stdio / when OAuth is not
    # configured (no token in context). On authenticated HTTP the token's
    # scopes must satisfy the tool's required scope (driven off annotations).
    tool_obj = next((t for t in _TOOLS if t.name == name), None)
    if tool_obj is not None:
        denial = check_scope(tool_obj)
        if denial:
            return err(denial, tool=name, hint="Token is missing the required scope.")
```

## Edit 3a — middleware (top-level, just above `async def _main_http`)

```python
class _ScopeAuthMiddleware:
    """ASGI middleware: validate Bearer token (if present) and stash claims in
    the scope-gate contextvar for the duration of the request.

    Enforcement is OPTIONAL by default. With OAUTH_ISSUER set and
    CB_MCP_HTTP_REQUIRE_AUTH=true, a missing/invalid token is rejected at the
    edge. Otherwise an invalid token is ignored (claims stay None) and per-tool
    scope checks no-op — preserving today's behavior unless you opt in.
    """

    def __init__(self, app):
        self.app = app
        self._require = os.environ.get(
            "CB_MCP_HTTP_REQUIRE_AUTH", "false"
        ).strip().lower() in ("1", "true", "yes")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        token = None
        for k, v in scope.get("headers", []):
            if k == b"authorization":
                val = v.decode("latin-1")
                if val.lower().startswith("bearer "):
                    token = val[7:].strip()
                break

        claims = None
        if token:
            try:
                from auth.oidc import validate_token
                claims = validate_token(token)
            except Exception as exc:  # invalid/expired/malformed
                if self._require:
                    await _send_401(send, f"Invalid token: {type(exc).__name__}")
                    return
                claims = None
        elif self._require:
            await _send_401(send, "Missing Bearer token")
            return

        set_token_claims(claims)
        try:
            await self.app(scope, receive, send)
        finally:
            clear_token_claims()


async def _send_401(send, detail: str) -> None:
    body = f'{{"error":"unauthorized","detail":"{detail}"}}'.encode()
    await send({
        "type": "http.response.start",
        "status": 401,
        "headers": [
            (b"content-type", b"application/json"),
            (b"www-authenticate", b"Bearer"),
        ],
    })
    await send({"type": "http.response.body", "body": body})
```

## Edit 3b — register middleware (change the existing Starlette block)

```python
        from starlette.applications import Starlette
        from starlette.routing import Mount
        from starlette.middleware import Middleware

        transport = StreamableHTTPServerTransport(mcp_session_id=None)
        starlette_app = Starlette(
            routes=[Mount("/mcp", app=transport.handle_request)],
            middleware=[Middleware(_ScopeAuthMiddleware)],
        )
```

## Env vars (all optional; defaults preserve current behavior)

| Var | Default | Effect |
|---|---|---|
| `CB_MCP_SCOPE_READ`  | `couchbase-mcp:read`  | scope required for read tools |
| `CB_MCP_SCOPE_WRITE` | `couchbase-mcp:write` | scope required for write tools |
| `CB_MCP_HTTP_REQUIRE_AUTH` | `false` | when true, missing/invalid Bearer -> 401 at the edge |

OIDC validation reuses your existing `auth/oidc.py` (`OAUTH_ISSUER`, JWKS, etc.).

## VERIFIED vs NOT-VERIFIED (read this)

Verified in an isolated venv against mcp 1.28.0:
- scope_gate logic: no-token no-op; read/write isolation; unannotated tools fail safe; `scp`-list shape.
- middleware: contextvar propagates to a same-task downstream handler; require-auth 401 paths; contextvar cleared after request.

NOT verified (needs your machine): that the contextvar set in the HTTP
middleware reaches `call_tool` across the streamable-HTTP transport's internal
asyncio task boundary (app.run runs under asyncio.gather alongside uvicorn). If
claims arrive as None inside call_tool on real HTTP traffic, switch the bare
contextvar for a per-session-id store keyed off the MCP session id.
