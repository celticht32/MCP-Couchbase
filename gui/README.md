# Couchbase MCP Console — Main GUI

A web-based interface for the Couchbase MCP Server. Browse and execute all 148 cluster-management tools from your browser.

> **Capella v4 control-plane tools** (16 read-only tools that talk to `cloudapi.cloud.couchbase.com`) live in a **separate** GUI under `../gui-capella/`. They run on a different port, with different credentials, against a different API surface. See `../gui-capella/README.md`.

## Features

- 🗂 **Sidebar navigation** — 148 tools organized into 16 categories (Data, Buckets, Collections, Security, Cluster, XDCR, Indexes, FTS Admin, Stats, **Diagnostics**, **Vector Indexes**, **Encryption**, **Transactions**, **Eventing**, **Backup**, **Synonyms**)
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
| GET    | `/api/tools` | List all 148 tools with their schemas |
| POST   | `/api/call`  | Execute a tool: `{ "tool": "cb_ping", "arguments": {} }` |
| GET    | `/api/config`| Get current connection environment variables |
| POST   | `/api/config`| Update connection variables and reset SDK connection |
| GET    | `/`          | Serve the React SPA |

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

## Safety note

**This GUI does not enforce read-only mode or the confirmation gate.** The MCP server's `server.py` enforces both (`CB_MCP_READ_ONLY_MODE` filters destructive tools out of the tool list; the confirmation gate requires `confirm:true` for destructive operations). The GUI calls the handler modules directly, bypassing those gates — it is a **power-user tool**.

If you want safety in the GUI, the addition is small but not done in this build:
- Filter `ALL_TOOLS` against `READ_ONLY_MODE` and the destructive annotation
- Require an explicit `confirm` arg in the form for destructive tools

## What's new since the original GUI release

The original GUI covered 105 tools across 9 categories. This update covers **all 148 cluster-management tools** added through Phase 7, organized into **15 categories**:

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
