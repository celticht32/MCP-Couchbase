# Couchbase MCP Console — Main GUI

A web-based interface for the Couchbase MCP Server. Browse and execute all 151 cluster-management tools from your browser.

> **Capella v4 control-plane tools** (16 read-only tools that talk to `cloudapi.cloud.couchbase.com`) live in a **separate** GUI under `../gui-capella/`. They run on a different port, with different credentials, against a different API surface. See `../gui-capella/README.md`.

## Features

- 🗂 **Sidebar navigation** — 151 tools organized into 16 categories (Data, Buckets, Collections, Security, Cluster, XDCR, Indexes, FTS Admin, Stats, **Diagnostics**, **Vector Indexes**, **Encryption**, **Transactions**, **Eventing**, **Backup**, **Synonyms**)
- 🔍 **Live search** — filter tools instantly by name or description
- 📋 **Auto-generated forms** — input fields are generated from each tool's JSON schema, with type-aware widgets
- ✅ **Syntax-highlighted JSON output** — color-coded responses with table view for arrays
- ⏱ **Execution timing** — ms elapsed per call
- 🕘 **History strip** — last 10 calls one click away
- ⚙️ **Connection settings modal** — change `CB_CONNECTION_STRING`, credentials, bucket, etc. at runtime

## Quick Start

```bash
# From the couchbase-mcp-server directory:
pip install flask flask-cors

# For OAuth login (optional), also install:
pip install "PyJWT[crypto]" cryptography requests

# Set your connection details (optional — also configurable in the GUI):
export CB_CONNECTION_STRING=couchbase://localhost
export CB_USERNAME=Administrator
export CB_PASSWORD=password
export CB_BUCKET=travel-sample

# Run the GUI server:
python gui/gui_server.py
# → http://localhost:5173
```

## File Structure

```
gui/
├── gui_server.py      # Flask backend — wraps MCP handlers as REST endpoints
├── static/
│   └── index.html     # Complete React SPA (single file, no build step)
└── README.md
```

## API Endpoints

| Method | Path         | Description |
|--------|-------------|-------------|
| GET    | `/api/tools` | List all 151 tools with their schemas |
| POST   | `/api/call`  | Execute a tool: `{ "tool": "cb_ping", "arguments": {} }` |
| GET    | `/api/config`| Get current connection environment variables |
| POST   | `/api/config`| Update connection variables and reset SDK connection |
| GET    | `/`          | Serve the React SPA |

When `OAUTH_ENABLED=true`, these additional routes are active (always public — no auth required to reach them):

| Method | Path             | Description |
|--------|------------------|-------------|
| GET    | `/auth/status`   | Whether OAuth is enabled and the caller is authenticated |
| GET    | `/auth/login`    | Begin Authorization Code + PKCE login (`?next=<relative-path>`) |
| GET    | `/auth/callback` | IdP redirect target — exchanges the code, creates the session |
| GET    | `/auth/logout`   | Clear the session (and trigger IdP logout if supported) |
| POST   | `/auth/token`    | Client Credentials token for M2M callers |
| GET    | `/auth/me`       | Identity of the current user |

## Configuration

| Variable | Default | Description |
|---|---|---|
| `CB_CONNECTION_STRING` | `couchbase://localhost` | Use `couchbases://` for TLS |
| `CB_USERNAME` | `Administrator` | |
| `CB_PASSWORD` | `password` | |
| `CB_BUCKET` | `default` | Default bucket for data ops |
| `CB_SCOPE` | `_default` | |
| `CB_COLLECTION` | `_default` | |
| `CB_MGMT_PORT` | `8091` | |
| `GUI_PORT` | `5173` | Port the Flask server listens on |

## Safety

The GUI **enforces the same safety gates as the MCP server**:

- **Read-only mode** (`CB_MCP_READ_ONLY_MODE=true`) — write tools are filtered out of `/api/tools` and rejected by `/api/call` (except `cb_query` / `cb_analytics_query`, which carry their own read-only handling).
- **Disabled tools** (`CB_MCP_DISABLED_TOOLS`) — listed tools are hidden and refused.
- **Confirmation gate** — destructive tools (and any in `CB_MCP_CONFIRMATION_REQUIRED_TOOLS`) require an explicit `confirm: true` argument; the API returns `403` otherwise.

The frontend marks read-only and destructive tools so you can see at a glance which operations mutate state.

## Authentication (OAuth 2.0 / OIDC)

Authentication is **off by default** (`OAUTH_ENABLED=false`) — the GUI is reachable only from localhost with no login, matching the original behaviour.

Set `OAUTH_ENABLED=true` to require login. The GUI then supports:

- **Authorization Code + PKCE** — browser users are redirected to your identity provider (Okta, Microsoft Entra ID, Keycloak, Auth0, etc.), and a signed `HttpOnly` session cookie tracks the session afterward. Tokens are stored server-side; the browser never sees them.
- **Client Credentials** — external machine-to-machine callers can `POST /auth/token` to obtain a short-lived Bearer token and supply it as `Authorization: Bearer <token>` on `/api/*` requests. (The browser GUI itself authenticates via its session cookie, not this flow.)

When OAuth is enabled, all `/api/*` routes return `401` to unauthenticated requests. See the root `.env.example` for the full list of `OAUTH_*` variables. Minimum required:

```bash
OAUTH_ENABLED=true
OAUTH_ISSUER=https://your-idp.example.com
OAUTH_CLIENT_ID=...
OAUTH_CLIENT_SECRET=...
OAUTH_REDIRECT_URI=http://localhost:5173/auth/callback
OAUTH_SESSION_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
```

## What's new since the original GUI release

The original GUI covered 105 tools across 9 categories. This update covers **all 151 cluster-management tools** added through Phase 7, organized into **16 categories**:

| New category | Phase | Tool examples |
|---|---|---|
| Diagnostics | 4 | `cb_explain_query`, `cb_index_advisor`, `cb_perf_slowest_queries` |
| Vector Indexes | 5 (8.x) | `admin_vector_index_create_hyperscale/composite` |
| Transactions | 6b | `cb_transaction_run`, `cb_analytics_query` |
| Eventing | 6c | `admin_eventing_deploy/undeploy/list/...` |
| Backup | 6b | `admin_backup_repository_list`, `admin_backup_run/restore_run` |
| Synonyms | 5 deferred | `cb_fts_synonym_upsert/list/delete` |
| Encryption | 5 deferred | `admin_encryption_*`, `admin_kmip_*` |

The Data and Cluster categories also gained tools through Phase 6a (subdoc: `cb_lookup_in`, `cb_mutate_in`) and Phase 5 (8.x user lock/unlock, conflict log readback, per-user query stats).

## Notes

- The GUI server imports the MCP handler modules directly — no separate MCP process needed.
- The frontend is a single HTML file with no build step: React and fonts load from CDN.
- For Couchbase Capella **data plane** (per-cluster ops against your Capella deployment): `CB_CONNECTION_STRING=couchbases://...` and `CB_MGMT_PORT=18091`.
- For Couchbase Capella **control plane** (org/project/cluster management): use `../gui-capella/`.
