# Couchbase MCP Server

A Python MCP (Model Context Protocol) server exposing the **full Couchbase data-plane and admin REST API** as tools for AI assistants like Claude.

---

## Tool Summary (75+ tools across 9 categories)

| Category | Prefix | Count | Covers |
|---|---|---|---|
| Data plane | `cb_` | 9 | CRUD, N1QL, FTS, ping |
| Buckets | `admin_bucket_` | 10 | Create/update/delete/flush/compact/sample |
| Scopes & Collections | `admin_scope_` / `admin_collection_` | 5 | Full lifecycle |
| Security & RBAC | `admin_user_` / `admin_group_` / `admin_*` | 17 | Users, groups, roles, audit, TLS, passwords |
| Cluster & Nodes | `admin_cluster_` / `admin_node_` / `admin_*` | 29 | Nodes, rebalance, failover, server groups, logs, alerts |
| XDCR | `admin_xdcr_` | 10 | References, replications, settings |
| GSI Indexes | `admin_index_` | 6 | Create/drop/build/settings via N1QL |
| FTS Admin | `admin_fts_` | 9 | FTS index CRUD, stats, ingestion control |
| Stats & Monitoring | `admin_stats_` / `admin_*` | 10 | Prometheus metrics, events, query/index settings |

---

## Project Structure

```
couchbase-mcp-server/
├── server.py               # MCP entry point — composes all handlers
├── requirements.txt
├── claude_desktop_config.json
├── README.md
└── handlers/
    ├── __init__.py
    ├── shared.py           # SDK connection, HTTP admin client, ok/err helpers
    ├── data.py             # CRUD, N1QL, FTS search, ping
    ├── buckets.py          # Bucket management + sample buckets
    ├── collections.py      # Scopes and collections
    ├── security.py         # Users, groups, RBAC, audit, password policy, TLS
    ├── cluster.py          # Cluster info, nodes, rebalance, failover, server groups, alerts
    ├── xdcr.py             # Cross-datacenter replication
    ├── indexes.py          # GSI index management
    ├── search_admin.py     # FTS index administration
    └── stats.py            # Metrics, events, diagnostics, query/index service settings
```

---

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment variables

| Variable | Default | Description |
|---|---|---|
| `CB_CONNECTION_STRING` | `couchbase://localhost` | Use `couchbases://` for TLS |
| `CB_USERNAME` | `Administrator` | |
| `CB_PASSWORD` | `password` | |
| `CB_BUCKET` | `default` | Default bucket for data ops |
| `CB_SCOPE` | `_default` | |
| `CB_COLLECTION` | `_default` | |
| `CB_MGMT_PORT` | `8091` | Capella: use `18091` |

### 3. Register with Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "couchbase": {
      "command": "python",
      "args": ["/absolute/path/to/couchbase-mcp-server/server.py"],
      "env": {
        "CB_CONNECTION_STRING": "couchbase://localhost",
        "CB_USERNAME": "Administrator",
        "CB_PASSWORD": "password",
        "CB_BUCKET": "travel-sample"
      }
    }
  }
}
```

Restart Claude Desktop — all 75+ tools appear automatically.

---

## Example Prompts

```
List all buckets and show memory usage for each.
Create a bucket called "sessions" with 256MB RAM, ephemeral type.
Add a user "app_reader" with read-only access to travel-sample.
Show me which nodes are in the cluster and their service assignments.
Create a GSI index on the `email` field of users._default._default.
Set up XDCR replication from travel-sample to my DR cluster at 10.1.0.5.
Show current rebalance progress.
List all FTS indexes and their document counts.
Get the last 20 system events from the cluster log.
```

---
## Support Policy
I truly appreciate your interest in this project! This project is community-maintained. However, I actively monitor and maintain this repo and will try to resolve issues on a best-effort basis.

All inquiries should be through GitHub.

    Bug reports: Open a GitHub issue
    Feature requests: Open a GitHub issue with the "enhancement" label
    Questions: Open a GitHub issue

Your collaboration helps me move forward together - thank you! Pull requests and contributions from the community are welcome and encouraged.

---
## Requirements
Python version
Python 3.10 or higher is required. The binding constraint is the mcp package itself — it declares requires_python >= 3.10. The code also uses list[Tool] and dict as generic type hints directly (PEP 585), but every handler file includes from __future__ import annotations which backports that syntax to 3.8+. Without that annotation import the syntax would require 3.9+. In practice 3.10 is the floor.

pip packages
MCP server (requirements.txt):
PackageVersionWhymcp>=1.0.0MCP server framework — Server, stdio_server, Tool, TextContentcouchbase>=4.2.0Couchbase Python SDK — used for CRUD, N1QL, FTS data-plane tools
GUI server (install separately):
PackageVersionWhyflaskany recentREST bridge between browser and MCP handlersflask-corsany recentCORS headers so the SPA can call the API
bashpip install mcp>=1.0.0 couchbase>=4.2.0          # MCP server
pip install flask flask-cors                       # GUI only

Standard library only (no extra install needed)
The admin REST API tools use only Python built-ins — urllib.request, urllib.parse, urllib.error, base64, json, os, asyncio, typing — so the HTTP side has zero extra dependencies beyond what ships with Python.

Couchbase server compatibility
The couchbase SDK >=4.2.0 targets Couchbase Server 7.0+ and Couchbase Capella. The apply_profile("wan_development") call in shared.py relaxes timeouts for remote/cloud connections and was added in SDK 4.1, so 4.2+ covers it cleanly

## Notes

- **Admin tools** call the Couchbase Management REST API (port 8091) via HTTP — no extra SDK needed beyond the Python SDK already installed.
- **Data tools** use the Couchbase Python SDK with lazy connection initialization.
- For **Couchbase Capella**, set `CB_CONNECTION_STRING=couchbases://...` and `CB_MGMT_PORT=18091`.
- Destructive operations (delete bucket, flush, hard failover) are explicit tools — Claude will ask for confirmation in context before acting.
