# Couchbase MCP Server

Full Couchbase data-plane **and** cluster-admin REST API exposed as MCP tools.
An independent, ground-up Python server (not a fork of the official
`Couchbase-Ecosystem/mcp-server-couchbase`) that reaches CRUD/data-plane parity
with the official server and adds a complete administrative surface.

- **167 tools** across 17 categories
- **Default-safe**: `CB_MCP_READ_ONLY_MODE=true` by default — writes are blocked
  until you opt in
- **Per-tool OAuth scope enforcement** on the HTTP transport
- **Confirmation gate** on destructive operations
- Two bundled web GUIs (standard + Capella), each with optional OIDC login
- 274 tests

License: MIT — Copyright (c) 2026 Chris Ahrendt
GitHub: https://github.com/celticht32/MCP-Couchbase

---

## Requirements

- Python `>=3.10,<3.15` (standard CPython; the free-threaded `3.13t` build is
  not supported — some compiled dependencies have no `cp313t` wheels)
- A reachable Couchbase cluster (Server or Capella)

## Install

From the repo root. On Windows, invoke a specific interpreter with `py -3.13`
(or your chosen 3.10–3.14) so you don't accidentally use a free-threaded build:

```powershell
py -3.13 -m pip install -e .
```

Optional extras:

| Extra   | Pulls in                                | Needed for                |
|---------|-----------------------------------------|---------------------------|
| `http`  | `uvicorn`, `starlette`                  | HTTP (Streamable) transport |
| `gui`   | `flask`, `flask-cors`                   | bundled web GUIs          |
| `oauth` | `PyJWT[crypto]`, `cryptography`, `requests`, `flask`, `flask-cors` | OIDC login + token validation |

```powershell
py -3.13 -m pip install -e ".[http,gui,oauth]"
```

## Run

Transport is selected by `CB_MCP_TRANSPORT` (default `stdio`).

**stdio** (default — local single-client):

```powershell
py -3.13 server.py
```

**HTTP** (Streamable HTTP; requires the `http` extra):

```powershell
$env:CB_MCP_TRANSPORT = "http"
py -3.13 server.py
```

On a successful HTTP start you'll see, on stderr:

```
[couchbase-mcp] tools loaded: N of M (read_only=True, disabled=0, confirmation_required=0)
[couchbase-mcp] HTTP transport listening on http://127.0.0.1:8000/mcp
```

If you instead see a fallback message about a missing `mcp` library or missing
`uvicorn`/`starlette`, the HTTP extra isn't installed and the server reverted to
stdio.

## Connection

| Variable                | Purpose                                          | Default               |
|-------------------------|--------------------------------------------------|-----------------------|
| `CB_CONNECTION_STRING`  | e.g. `couchbase://localhost` / `couchbases://...`| `couchbase://localhost` |
| `CB_USERNAME`           | cluster user                                     | —                     |
| `CB_PASSWORD`           | cluster password                                 | —                     |
| `CB_CLIENT_CERT_PATH` / `CB_CLIENT_KEY_PATH` | mTLS via `CertificateAuthenticator` | —      |
| `CB_CA_CERT_PATH`       | CA cert for TLS verification                     | —                     |
| `CB_BUCKET` / `CB_SCOPE` / `CB_COLLECTION` | default keyspace                  | `default` / `_default` / `_default` |
| `CAPELLA_API_KEY_SECRET`| Bearer token for Capella v4 control-plane tools  | —                     |

## Safety

Safety defaults are modeled after the official Couchbase MCP server.

| Control                       | Default | Variable                            |
|-------------------------------|---------|-------------------------------------|
| Read-only mode                | **on**  | `CB_MCP_READ_ONLY_MODE`             |
| Disabled tools                | none    | `CB_MCP_DISABLED_TOOLS`             |
| Destructive-op confirmation   | on      | `CB_MCP_CONFIRMATION_REQUIRED_TOOLS`|
| Elicitation hints             | on      | `CB_MCP_ELICITATION_HINTS`          |

In read-only mode the server loads only read-side tools (those annotated
`readOnlyHint=true`), plus `cb_query` and `cb_analytics_query`, which declare
`destructiveHint=true` but block DML internally.

## OAuth scope enforcement (HTTP transport)

Per-tool scope enforcement is implemented in `auth/scope_gate.py` and wired into
the `call_tool` dispatch. It is a **no-op on stdio** and when no token is
present; it activates only on the HTTP transport with a validated Bearer token.

The read/write classification reuses the server's own read-only filter, so a
read-scoped token can invoke exactly the tools the server loads under
`CB_MCP_READ_ONLY_MODE`.

| Variable                   | Default               | Effect                                         |
|----------------------------|-----------------------|------------------------------------------------|
| `CB_MCP_SCOPE_READ`        | `couchbase-mcp:read`  | scope required for read-side tools             |
| `CB_MCP_SCOPE_WRITE`       | `couchbase-mcp:write` | scope required for write-side tools            |
| `CB_MCP_HTTP_REQUIRE_AUTH` | `false`               | when `true`, missing/invalid Bearer → 401      |

Token validation reuses `auth/oidc.py` (`OAUTH_ISSUER`, JWKS discovery,
`OAUTH_AUDIENCE`, `OAUTH_ALGORITHMS`). With `OAUTH_ISSUER` set but
`CB_MCP_HTTP_REQUIRE_AUTH` left false, the server prints a startup warning —
invalid tokens are ignored in that mode rather than rejected.

> Note: the HTTP transport binds to `CB_MCP_HOST` (default `127.0.0.1`). When
> `CB_MCP_HTTP_REQUIRE_AUTH` is false there is no request authentication; deploy
> behind a reverse proxy or trusted network, or set it true.

## Tool categories

| Category      | Module                  | Tools |
|---------------|-------------------------|-------|
| Cluster ops   | `handlers/cluster`      | 29    |
| Security      | `handlers/security`     | 17    |
| Capella v4    | `handlers/capella`      | 16    |
| KV / data     | `handlers/data`         | 11    |
| Buckets       | `handlers/buckets`      | 10    |
| XDCR          | `handlers/xdcr`         | 10    |
| Diagnostics   | `handlers/diagnostics`  | 10    |
| Stats         | `handlers/stats`        | 10    |
| Eventing      | `handlers/eventing`     | 10    |
| FTS admin     | `handlers/search_admin` | 9     |
| 8.x features  | `handlers/eight_x`      | 7     |
| Extended      | `handlers/extended`     | 7     |
| Indexes       | `handlers/indexes`      | 6     |
| Collections   | `handlers/collections`  | 5     |
| Encryption    | `handlers/encryption`   | 4     |
| Synonyms      | `handlers/synonyms`     | 3     |
| MCP status    | `handlers/mcp_status`   | 3     |
| **Total**     |                         | **167** |

## Development

```powershell
py -3.13 -m pip install -e ".[dev]"
py -3.13 -m pytest
```

Pinned dev tooling (see `pyproject.toml`): `ruff==0.12.5`, `pytest==9.0.3`,
`pytest-asyncio==1.3.0`, `pre-commit==4.2.0`.
