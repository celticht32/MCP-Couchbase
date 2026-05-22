# Couchbase Capella v4 Console — Separate GUI

A web-based interface for the Couchbase Capella v4 **control plane** — the SaaS API at `cloudapi.cloud.couchbase.com` that manages organizations, projects, clusters, users, allowlists, API keys, and App Services.

This is a **separate** GUI from `../gui/`. It:

- Runs on a different port (default **5174**, vs `gui/`'s **5173**) so both can run side-by-side
- Uses different authentication (Bearer token via `CAPELLA_API_KEY_SECRET`, not username/password)
- Talks to a different host (`cloudapi.cloud.couchbase.com`, not your cluster)
- Exposes a different set of tools (16 Capella v4 read-only inspection tools)

## Why two separate GUIs?

Capella v4 is fundamentally different from the cluster-management surface:

| | Main GUI (`../gui/`) | Capella GUI (this) |
|---|---|---|
| Talks to | A specific Couchbase cluster | The Couchbase Capella SaaS API |
| Endpoint | `<host>:8091` or `<host>:18091` | `cloudapi.cloud.couchbase.com` |
| Auth | Basic (username + password) or mTLS | Bearer (API key secret) |
| Tools | 148 (CRUD, admin, diagnostics, etc.) | 16 (org / project / cluster / user listings) |
| Scope | Per-cluster operations | Multi-cluster / org-wide |
| Writes | Yes, with confirmation gates in the MCP | No — read-only |

Mixing them in one GUI confuses the model and risks credential leakage (the Capella secret is more sensitive than per-cluster creds; it can spin up infrastructure).

## Quick Start

```bash
# From the couchbase-mcp-server directory:
pip install flask flask-cors

# Set your Capella API key secret (or configure via the GUI on first launch):
export CAPELLA_API_KEY_SECRET=<paste-from-Capella-UI-Settings-API-Keys>

# Run the Capella GUI server:
python gui-capella/gui_server.py
# → http://localhost:5174
```

The API key is created in the Couchbase Capella web UI under **Settings → API Keys → Create API Key**. You'll be shown the secret **once** — copy it then. Store it in your password manager.

## File Structure

```
gui-capella/
├── gui_server.py      # Flask backend — exposes the capella handler module
├── static/
│   └── index.html     # React SPA, cyan-themed for visual distinction from the main GUI
└── README.md
```

## Tool catalogue (16 read-only)

| Category | Tools |
|---|---|
| Organization | `capella_organizations_list`, `capella_organization_get`, `capella_org_users_list`, `capella_org_user_get`, `capella_api_keys_list`, `capella_api_key_get` |
| Projects | `capella_projects_list`, `capella_project_get` |
| Clusters | `capella_clusters_list`, `capella_cluster_get` |
| Database Users | `capella_database_users_list`, `capella_database_user_get` |
| Allowed CIDRs | `capella_allowed_cidrs_list`, `capella_allowed_cidr_get` |
| App Services | `capella_app_services_list`, `capella_app_service_get` |

**This GUI is read-only.** No cluster creation, no user invitations, no API-key rotation, no allowlist changes. Use the Capella web UI or a dedicated automation tool for writes — the LLM blast radius on a runaway write is too large to expose through a chat-driven interface.

## API Endpoints

| Method | Path         | Description |
|--------|-------------|-------------|
| GET    | `/api/tools` | List all 16 Capella tools with their schemas |
| POST   | `/api/call`  | Execute a tool: `{ "tool": "capella_organizations_list", "arguments": {} }` |
| GET    | `/api/config`| Get current Capella config (shows whether secret is set, never echoes the value) |
| POST   | `/api/config`| Update Capella config |
| GET    | `/`          | Serve the Capella-themed React SPA |

## Configuration

| Variable | Default | Description |
|---|---|---|
| `CAPELLA_API_KEY_SECRET` | (required) | API key secret from Capella UI |
| `CAPELLA_BASE_URL` | `https://cloudapi.cloud.couchbase.com` | Override only for non-production environments |
| `CAPELLA_HTTP_TIMEOUT` | `30` | Per-request timeout in seconds |
| `CAPELLA_HTTP_RETRIES` | `3` | Max attempts on transient (5xx) failures |
| `GUI_PORT` | `5174` | Flask listen port. Set to differ from the main GUI |

## How to use the GUI

1. Open `http://localhost:5174`.
2. Click the gear icon (top-right) and paste your `CAPELLA_API_KEY_SECRET` into the modal.
3. Call `capella_organizations_list` first — this is the connectivity check. If it returns an org UUID, your secret is working.
4. Walk the hierarchy: copy the `organizationId` from the list, paste into `capella_organization_get` to see details, then `capella_projects_list` with the same orgId, etc.

The form widgets are auto-generated from each tool's JSON schema (same engine as the main GUI). Required fields are marked; UUIDs are plain text inputs.

## Notes

- The API key secret is never echoed back from `/api/config` — only whether it's set. This protects against shoulder-surfing if you're sharing your screen.
- Capella v4 has rate limits (typically 100 req/min per key). The GUI doesn't rate-limit itself; rapid-clicking through resources may hit the cap and get 429 responses.
- For staging or non-production Capella environments, override `CAPELLA_BASE_URL`.
