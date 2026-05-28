# Couchbase MCP Server (Extended)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

A Python [Model Context Protocol](https://modelcontextprotocol.io/) server that exposes the **full Couchbase data-plane and admin REST API** as tools for AI assistants like Claude.

This project extends the [official Couchbase MCP server](https://github.com/Couchbase-Ecosystem/mcp-server-couchbase) with comprehensive cluster administration coverage — bucket lifecycle, security/RBAC, nodes, rebalance, XDCR, FTS admin, Eventing, Analytics, Backup, Encryption, and Capella v4 control-plane tooling — while preserving all safety primitives from the official server.

---

## Features

**167 tools across 17 categories:**

| Category | Tools | Prefix | Covers |
|---|---|---|---|
| Data plane | 11 | `cb_` | CRUD, N1QL, FTS search, sub-document, multi-get, transactions, Analytics |
| Bucket admin | 10 | `admin_bucket_` | Create/update/delete/flush/compact/sample |
| Scopes & Collections | 5 | `admin_scope_` / `admin_collection_` | Full lifecycle |
| Security & RBAC | 17 | `admin_user_` / `admin_group_` / `admin_*` | Users, groups, roles, audit, TLS, password policy |
| Cluster & Nodes | 29 | `admin_cluster_` / `admin_node_` / `admin_*` | Nodes, rebalance, failover, server groups, alerts, logs |
| XDCR | 10 | `admin_xdcr_` | References, replications, settings |
| GSI Indexes | 6 | `admin_index_` | Create/drop/build/settings |
| FTS Admin | 9 | `admin_fts_` | FTS index CRUD, stats, ingestion control |
| Stats & Monitoring | 10 | `admin_stats_` / `admin_*` | Prometheus targets, events, diagnostics, service settings |
| Diagnostics | 10 | `cb_*` | Schema, index advisor, EXPLAIN plan, 7 query-performance tools |
| Couchbase 8.x | 7 | `admin_vector_index_*` / `admin_user_*` / `admin_xdcr_*` / `cb_perf_*` | Vector indexes, user lock/unlock, XDCR conflict log |
| Extended | 7 | `cb_*` / `admin_backup_*` | Transactions, Analytics query, Backup |
| Eventing | 10 | `admin_eventing_` | Function lifecycle, deploy, pause, stats |
| FTS Synonyms | 3 | `cb_fts_synonym_` | Synonym set documents (8.x) |
| Encryption (DARE/KMIP) | 4 | `admin_encryption_` / `admin_kmip_` | At-rest encryption, KMIP settings |
| Capella v4 | 16 | `capella_` | Organizations, projects, clusters, users, CIDRs, app services (read-only) |
| MCP introspection | 3 | `cb_mcp_` | Server config status, tool listing, tool schema lookup |

---

## Safety

Safety defaults are modeled after the official Couchbase MCP server:

| Feature | Default | Env variable |
|---|---|---|
| Read-only mode | **ON** | `CB_MCP_READ_ONLY_MODE=true` |
| Disabled tools | none | `CB_MCP_DISABLED_TOOLS` |
| Destructive-op confirmation | ON (all `destructiveHint` tools) | `CB_MCP_CONFIRMATION_REQUIRED_TOOLS` |
| DML blocking in SQL++ | ON when read-only | _(automatic)_ |
| Elicitation hints | ON | `CB_MCP_ELICITATION_HINTS=true` |

When `CB_MCP_READ_ONLY_MODE=true` (the default), all tools annotated as write operations are **not loaded** — they don't appear in tool discovery and cannot be called. Destructive tools that survive the filter require `confirm: true` in their arguments before execution.

> **RBAC is your primary security control.** Tool-level restrictions are a defense-in-depth layer. Always configure appropriate Couchbase user permissions.

---

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A running Couchbase Server cluster or [Capella](https://cloud.couchbase.com/) instance

---

## Installation

### Option A — Smithery.ai (managed hosting)

Install from the [Smithery registry](https://smithery.ai/) — no local Python or Docker required. Smithery will host the server, prompt you for the configuration values defined in `smithery.yaml`, and connect your MCP client.

### Option B — Docker

Build and run as a single container:

```bash
docker build -t celtic/couchbase-mcp:0.9.0 .

docker run -i --rm \
  -e CB_CONNECTION_STRING="couchbases://cluster.example" \
  -e CB_USERNAME="user" -e CB_PASSWORD="pass" \
  -e CB_BUCKET="travel-sample" \
  celtic/couchbase-mcp:0.9.0
```

Or use Docker Compose to bring up Couchbase Server + the MCP server together for local development:

```bash
docker compose up -d
# Couchbase UI at http://localhost:8091
# MCP server (HTTP transport) at http://localhost:8000/mcp
```

### Option C — From source

```bash
git clone https://github.com/celticht32/MCP-Couchbase.git
cd MCP-Couchbase
uv sync
uv run server.py
```

### Option D — From PyPI (once published)

```bash
pip install couchbase-mcp-server
couchbase-mcp-server
```

---

## Configuration

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `CB_CONNECTION_STRING` | `couchbase://localhost` | Use `couchbases://` for TLS / Capella |
| `CB_USERNAME` | _(required)_ | Username — unless using mTLS |
| `CB_PASSWORD` | _(required)_ | Password — unless using mTLS |
| `CB_BUCKET` | `default` | Default bucket for data-plane tools |
| `CB_SCOPE` | `_default` | Default scope |
| `CB_COLLECTION` | `_default` | Default collection |
| `CB_MGMT_PORT` | `8091` | Override for non-standard management port |
| `CB_CLIENT_CERT_PATH` | — | Path to client cert PEM (enables mTLS) |
| `CB_CLIENT_KEY_PATH` | — | Path to client key PEM |
| `CB_CA_CERT_PATH` | — | CA cert for self-signed / self-managed clusters |
| `CB_MCP_TLS_INSECURE` | `false` | Skip TLS verification (dev only) |
| `CB_MCP_READ_ONLY_MODE` | `true` | Disable all write tools when `true` |
| `CB_MCP_DISABLED_TOOLS` | — | Comma list or file path of tools to exclude |
| `CB_MCP_CONFIRMATION_REQUIRED_TOOLS` | — | Extra tools requiring `confirm: true` |
| `CB_MCP_ELICITATION_HINTS` | `true` | Include hint text in confirmation errors |
| `CB_MCP_HTTP_RETRIES` | `3` | Max retries for admin HTTP calls |
| `CB_MCP_HTTP_TIMEOUT` | `30` | Per-request timeout (seconds) |
| `CB_MCP_TRANSPORT` | `stdio` | `stdio` or `http` |
| `CB_MCP_HOST` | `127.0.0.1` | Host for HTTP transport |
| `CB_MCP_PORT` | `8000` | Port for HTTP transport |

### Claude Desktop

```json
{
  "mcpServers": {
    "couchbase": {
      "command": "uv",
      "args": ["--directory", "/path/to/MCP-Couchbase", "run", "server.py"],
      "env": {
        "CB_CONNECTION_STRING": "couchbases://your-cluster",
        "CB_USERNAME": "username",
        "CB_PASSWORD": "password",
        "CB_BUCKET": "travel-sample"
      }
    }
  }
}
```

### Capella

```json
{
  "env": {
    "CB_CONNECTION_STRING": "couchbases://cb.xxxx.cloud.couchbase.com",
    "CB_USERNAME": "username",
    "CB_PASSWORD": "password",
    "CB_MGMT_PORT": "18091"
  }
}
```

### mTLS

```json
{
  "env": {
    "CB_CONNECTION_STRING": "couchbases://your-cluster",
    "CB_CLIENT_CERT_PATH": "/path/to/client.pem",
    "CB_CLIENT_KEY_PATH": "/path/to/client.key"
  }
}
```

### Disabling tools

```bash
# Comma-separated
CB_MCP_DISABLED_TOOLS="admin_bucket_delete,admin_node_failover_hard"

# File (one name per line, # comments supported)
CB_MCP_DISABLED_TOOLS="/path/to/disabled_tools.txt"
```

---

## Tool reference

### Data plane (`cb_`)

| Tool | Description |
|---|---|
| `cb_ping` | Ping the cluster to verify SDK + service connectivity |
| `cb_get` | Get a document by key |
| `cb_upsert` | Insert or replace a document _(write — disabled in read-only mode)_ |
| `cb_insert` | Insert a new document (fails if key exists) _(write)_ |
| `cb_replace` | Replace an existing document (fails if key missing) _(write)_ |
| `cb_delete` | Delete a document by key _(write)_ |
| `cb_get_multi` | Retrieve multiple documents by key list |
| `cb_query` | Run a N1QL / SQL++ query (DML blocked in read-only mode) |
| `cb_fts_search` | Run a Full-Text Search query against an FTS index |
| `cb_lookup_in` | Sub-document get path(s) |
| `cb_mutate_in` | Sub-document mutation _(write)_ |

### Bucket administration (`admin_bucket_`)

| Tool | Description |
|---|---|
| `admin_bucket_list` | List all buckets with settings |
| `admin_bucket_get` | Get settings for a specific bucket |
| `admin_bucket_create` | Create a bucket _(write — confirmation required)_ |
| `admin_bucket_update` | Update bucket settings _(write)_ |
| `admin_bucket_delete` | Delete a bucket _(write — confirmation required)_ |
| `admin_bucket_flush` | Flush all documents from a bucket _(write — confirmation required)_ |
| `admin_bucket_compact` | Trigger bucket compaction |
| `admin_bucket_cancel_compaction` | Cancel an in-progress compaction |
| `admin_sample_buckets_list` | List available sample buckets |
| `admin_sample_buckets_install` | Install a sample bucket _(write)_ |

### Scopes & Collections

| Tool | Description |
|---|---|
| `admin_scope_list` | List all scopes in a bucket |
| `admin_scope_create` | Create a scope _(write)_ |
| `admin_scope_delete` | Delete a scope _(write — confirmation required)_ |
| `admin_collection_create` | Create a collection _(write)_ |
| `admin_collection_delete` | Delete a collection _(write — confirmation required)_ |

### Security & RBAC (`admin_user_` / `admin_group_`)

| Tool | Description |
|---|---|
| `admin_user_list` | List all database users |
| `admin_user_get` | Get a specific user |
| `admin_user_create` | Create a user _(write)_ |
| `admin_user_delete` | Delete a user _(write — confirmation required)_ |
| `admin_user_change_password` | Change a user's password _(write)_ |
| `admin_group_list` | List all user groups |
| `admin_group_get` | Get a specific group |
| `admin_group_create` | Create or update a group _(write)_ |
| `admin_group_delete` | Delete a group _(write — confirmation required)_ |
| `admin_role_list` | List all available RBAC roles |
| `admin_whoami` | Show current user and assigned roles |
| `admin_audit_get` | Get audit settings |
| `admin_audit_set` | Update audit settings _(write)_ |
| `admin_password_policy_get` | Get password policy |
| `admin_password_policy_set` | Set password policy _(write)_ |
| `admin_security_settings_get` | Get security settings |
| `admin_security_settings_set` | Update security settings _(write)_ |

### Cluster & Nodes

| Tool | Description |
|---|---|
| `admin_cluster_info` | Get cluster overview |
| `admin_cluster_details` | Get detailed cluster pools/default info |
| `admin_cluster_tasks` | List active cluster tasks |
| `admin_cluster_name_set` | Rename the cluster _(write)_ |
| `admin_cluster_memory_set` | Set cluster memory quotas _(write)_ |
| `admin_node_list` | List all nodes |
| `admin_node_services_list` | List services per node |
| `admin_node_add` | Add a node to the cluster _(write — confirmation required)_ |
| `admin_node_remove` | Remove a node _(write — confirmation required)_ |
| `admin_rebalance_start` | Start a rebalance _(write)_ |
| `admin_rebalance_progress` | Get rebalance progress |
| `admin_rebalance_stop` | Stop an in-progress rebalance _(write — confirmation required)_ |
| `admin_failover_hard` | Hard failover a node _(write — confirmation required)_ |
| `admin_failover_graceful` | Graceful failover a node _(write)_ |
| `admin_recovery_type_set` | Set node recovery type _(write)_ |
| `admin_autofailover_get` | Get auto-failover settings |
| `admin_autofailover_set` | Set auto-failover settings _(write)_ |
| `admin_autofailover_reset` | Reset auto-failover error count _(write)_ |
| `admin_server_groups_get` | List server groups |
| `admin_server_group_create` | Create a server group _(write)_ |
| `admin_server_group_delete` | Delete a server group _(write — confirmation required)_ |
| `admin_server_group_rename` | Rename a server group _(write)_ |
| `admin_logs_collect_start` | Start log collection _(write)_ |
| `admin_logs_collect_cancel` | Cancel log collection _(write)_ |
| `admin_autocompaction_get` | Get auto-compaction settings |
| `admin_autocompaction_set` | Set auto-compaction settings _(write)_ |
| `admin_alerts_get` | Get alert settings |
| `admin_alerts_set` | Set alert settings _(write)_ |
| `admin_alerts_test_email` | Test alert email configuration |

### XDCR (`admin_xdcr_`)

| Tool | Description |
|---|---|
| `admin_xdcr_references_list` | List remote cluster references |
| `admin_xdcr_reference_create` | Create a remote cluster reference _(write)_ |
| `admin_xdcr_reference_delete` | Delete a remote cluster reference _(write — confirmation required)_ |
| `admin_xdcr_replications_list` | List XDCR replications |
| `admin_xdcr_replication_create` | Create a replication _(write)_ — supports `replicationType`, `type` (xmem/capi), `compressionType`, `filterExpression`, and CB 8.x `conflictLogging` + `conflictLoggingMapping` |
| `admin_xdcr_replication_pause` | Pause a replication _(write)_ |
| `admin_xdcr_replication_resume` | Resume a paused replication _(write)_ |
| `admin_xdcr_replication_delete` | Delete a replication _(write — confirmation required)_ |
| `admin_xdcr_settings_get` | Get global XDCR settings |
| `admin_xdcr_settings_set` | Set global XDCR settings _(write)_ |

### GSI Indexes (`admin_index_`)

| Tool | Description |
|---|---|
| `admin_index_list` | List all GSI indexes |
| `admin_index_create` | Create a GSI index (DDL only) _(write)_ |
| `admin_index_drop` | Drop a GSI index _(write — confirmation required)_ |
| `admin_index_build` | Build deferred indexes _(write)_ |
| `admin_index_settings_get` | Get index service settings |
| `admin_index_settings_set` | Set index service settings _(write)_ |

### FTS Administration (`admin_fts_`)

| Tool | Description |
|---|---|
| `admin_fts_index_list` | List all FTS indexes |
| `admin_fts_index_get` | Get an FTS index definition |
| `admin_fts_index_create` | Create an FTS index _(write)_ |
| `admin_fts_index_delete` | Delete an FTS index _(write — confirmation required)_ |
| `admin_fts_index_stats` | Get FTS index stats |
| `admin_fts_index_doc_count` | Get document count for an FTS index |
| `admin_fts_index_ingest_pause` | Pause FTS index ingestion _(write)_ |
| `admin_fts_index_ingest_resume` | Resume FTS index ingestion _(write)_ |
| `admin_fts_settings_get` | Get FTS service settings |

### Diagnostics (`cb_`)

| Tool | Description |
|---|---|
| `cb_get_schema_for_collection` | Infer collection schema from sample documents |
| `cb_index_advisor` | Get index recommendations for a SQL++ query |
| `cb_explain_query` | Get and evaluate the EXPLAIN plan for a SQL++ query |
| `cb_perf_longest_running` | Get longest-running queries by average service time |
| `cb_perf_most_frequent` | Get most frequently executed queries |
| `cb_perf_largest_responses` | Get queries with the largest response sizes |
| `cb_perf_large_result_count` | Get queries with the largest result counts |
| `cb_perf_using_primary_index` | Get queries using a primary index (performance concern) |
| `cb_perf_not_using_covering_index` | Get queries not using a covering index |
| `cb_perf_not_selective` | Get non-selective queries |

### Stats & Monitoring

| Tool | Description |
|---|---|
| `admin_stats_bucket` | Get per-bucket stats |
| `admin_stats_single` | Get a single named stat |
| `admin_stats_multi` | Get multiple named stats |
| `admin_system_events` | List recent cluster system events |
| `admin_node_self_info` | Get info for the current node |
| `admin_internal_settings_get` | Get cluster internal settings |
| `admin_internal_settings_set` | Set cluster internal settings _(write)_ |
| `admin_query_settings_get` | Get query service settings |
| `admin_query_settings_set` | Set query service settings _(write)_ |
| `admin_prometheus_targets` | List Prometheus scrape targets |

### MCP introspection (`cb_mcp_`)

These tools report on the MCP server itself (not the Couchbase cluster). They have no cluster dependency — useful for verifying configuration and debugging missing-tool issues.

| Tool | Description |
|---|---|
| `cb_mcp_status` | Server config summary: safety mode, transport, auth method, tool counts, cluster version (if probed) |
| `cb_mcp_list_tools` | List currently exposed tools (after read-only and disabled-tools filtering), optionally filtered by category (`read` / `write` / `destructive` / `all`) |
| `cb_mcp_get_tool_info` | Get input schema and annotations for a single tool; reports `currently_loaded` and `currently_disabled` |

### Extended, Eventing, 8.x, Encryption, Capella

See [server.py](server.py) for full handler module imports and the [handlers/](handlers/) directory for per-category tool definitions.

---

## Development

### Setup

```bash
git clone https://github.com/celticht32/MCP-Couchbase.git
cd MCP-Couchbase
uv sync --extra dev
pre-commit install
```

### Linting and formatting

```bash
# Check
ruff check .
# Auto-fix + format
ruff check . --fix && ruff format .
```

Pre-commit runs `ruff` automatically on every `git commit`.

### Tests

```bash
# Unit tests only (no cluster required)
pytest tests/ -m unit -v

# All tests (requires CB_CONNECTION_STRING, CB_USERNAME, CB_PASSWORD, CB_BUCKET)
CB_CONNECTION_STRING=couchbase://localhost \
CB_USERNAME=Administrator \
CB_PASSWORD=password \
CB_BUCKET=travel-sample \
pytest tests/ -v
```

---

## Architecture

```
server.py                   # MCP entry point — aggregates handlers, applies
                            # read-only / disabled-tool filters, confirmation gate
handlers/
  shared.py                 # SDK connection pool, HTTP admin client,
                            # safety primitives (READ_ONLY_MODE, DML blocking,
                            # disabled tools, confirmation gate, mTLS)
  data.py                   # CRUD, N1QL, FTS search, sub-document
  buckets.py                # Bucket lifecycle
  collections.py            # Scopes and collections
  security.py               # Users, groups, RBAC, audit
  cluster.py                # Nodes, rebalance, failover, server groups
  xdcr.py                   # Cross-datacenter replication
  indexes.py                # GSI index management
  search_admin.py           # FTS index administration
  stats.py                  # Metrics and monitoring
  diagnostics.py            # Schema, index advisor, EXPLAIN, query performance
  eight_x.py                # Couchbase 8.x-only features
  extended.py               # Transactions, Analytics, Backup
  eventing.py               # Eventing function lifecycle
  synonyms.py               # FTS synonym set documents
  encryption.py             # DARE encryption + KMIP
  capella.py                # Capella v4 control-plane (read-only)
  mcp_status.py             # Server introspection (config, tool listing)
tests/
  conftest.py               # Shared fixtures, integration skip markers
  test_safety.py            # Unit tests for safety primitives (no cluster needed)
skills/
  couchbase-sqlpp-tuning/   # LLM skill: read EXPLAIN, design indexes,
                            # fix slow queries — wires into cb_explain_query,
                            # cb_index_advisor, cb_perf_*
```

### Adding a new tool category

1. Create `handlers/my_category.py` with a `TOOLS: list[Tool]` and `handle(name, args)` function
2. Import and register it in `server.py` (two lines)

### Helpers in `handlers/shared.py`

When writing a handler, reach for these helpers — they prevent the bug classes that have been fixed over multiple review passes:

| Helper | Use it for |
|---|---|
| `quote_path(segment)` | Every user-supplied URL path segment. URL-encodes `/`, spaces, `@`, etc. so identifiers like `ns_1@host.example` or `my cluster/DR` can't break the URL. |
| `form_data(args, exclude=("confirm",))` | Building the form-data dict for an admin POST. Drops `None`, drops `confirm` (already stripped at server layer, but defensive), converts booleans to lowercase `"true"` / `"false"` (Couchbase REST rejects Python's `"True"`). |
| `form_value(v)` | Single-value version of the boolean-aware encoding. |
| `_safe_ident(s)` (in `indexes.py`/`eight_x.py`) | Backtick-quote a N1QL/SQL++ identifier. Doubles embedded backticks. Always use for bucket/scope/collection/index names in raw SQL++. |
| `_keyspace(bucket, scope, coll)` | Build `` `bucket`.`scope`.`coll` `` in one call. |
| `block_dml_if_readonly(stmt)` | At the top of any tool that accepts a raw SQL++ statement. Returns an error message if read-only mode is on and the statement is DML/DDL. |
| `assert_index_create_ddl(stmt)` / `assert_index_drop_ddl(stmt)` | When a tool accepts a raw `statement` for index DDL. Locks the input to actual index DDL — rejects everything else. |
| `admin_request(method, path, data=None, params=None, json_body=False)` | The unified REST admin client. Handles auth, retries, TLS, JSON vs form body. Caller is responsible for URL-encoding path segments (use `quote_path`). |
| `ok(data)` / `err(msg, **context)` | Always return through these. `err()` accepts arbitrary keyword diagnostics (`tool`, `args`, `hint`) that help the LLM recover. |

---

## Relationship to the official Couchbase MCP server

This project contributes to and extends [Couchbase-Ecosystem/mcp-server-couchbase](https://github.com/Couchbase-Ecosystem/mcp-server-couchbase). The safety model (`CB_MCP_READ_ONLY_MODE`, `CB_MCP_DISABLED_TOOLS`, mTLS, DML blocking) is fully compatible with the official server's design. See the open contribution issue for the merge proposal.

---

## Bundled skills

The project ships an LLM skill at [`skills/couchbase-sqlpp-tuning/`](skills/couchbase-sqlpp-tuning/) for diagnosing and fixing slow SQL++ / N1QL queries. It pairs with the MCP server's diagnostic tools (`cb_explain_query`, `cb_index_advisor`, `cb_perf_*`, `cb_get_schema_for_collection`) and covers:

- Reading EXPLAIN plans (operators, signs of bad plans, profile timings)
- Index design (covering, partial, array, composite, functional, vector)
- Common anti-patterns (PrimaryScan, IntersectScan, EVERY without ANY, deep pagination)
- The 7.6+ cost-based optimizer and its hints
- The five-step diagnostic workflow using the MCP server tools
- Pagination patterns (LIMIT/OFFSET vs KeySet)
- Tuning joins between keyspaces

Drop the `skills/couchbase-sqlpp-tuning/` directory into Claude's skills path to make it available in conversations.

---

## Support

This project is community-maintained. Open a GitHub issue for bug reports, feature requests, or questions.

---

## License

MIT © 2026 Chris Ahrendt. See [LICENSE](LICENSE) for the full text.
