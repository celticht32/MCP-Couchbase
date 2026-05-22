# Cluster admin — `admin_*` tools

The `admin_*` family wraps Couchbase REST endpoints for managing the cluster itself: buckets, scopes, collections, users, indexes, XDCR replications, autofailover settings, etc. These operate against the cluster manager (port 8091 for self-managed, 18091 for Capella) and require `CB_USERNAME` / `CB_PASSWORD` with administrative roles.

## Buckets

| Tool | Read-only? | Notes |
|---|---|---|
| `admin_bucket_list` | ✓ | List all buckets |
| `admin_bucket_get` | ✓ | Detail for one bucket |
| `admin_bucket_create` | ✗ | New bucket; many config options |
| `admin_bucket_update` | ✗ | Modify quota, replicas, eviction policy |
| `admin_bucket_delete` | ✗ | **Destructive** — requires `confirm: true` |
| `admin_bucket_flush` | ✗ | **Destructive** — deletes all docs, requires `confirm: true` |
| `admin_bucket_settings_get` | ✓ | Read advanced settings |
| `admin_bucket_settings_set` | ✗ | Modify advanced settings |
| `admin_bucket_autoscale_get` | ✓ | Get auto-scaling config |
| `admin_bucket_autoscale_set` | ✗ | Set auto-scaling config |
| `admin_sample_buckets_list` | ✓ | List available sample datasets |
| `admin_sample_buckets_install` | ✗ | Install a sample (`travel-sample`, `beer-sample`, etc.) |

**Bucket types:** `couchbase` (typical), `memcached` (cache-only, deprecated), `ephemeral` (in-memory + replicated). Pick `couchbase` unless you specifically know you need ephemeral semantics.

**Eviction policy:** `valueOnly` (default — evict values only, keep metadata in memory) vs `fullEviction` (evict everything — better for large datasets). For working sets larger than RAM, `fullEviction` is correct.

## Scopes & collections

| Tool | Read-only? | Notes |
|---|---|---|
| `admin_scope_list` | ✓ | All scopes in a bucket |
| `admin_scope_create` | ✗ | Create scope |
| `admin_scope_drop` | ✗ | **Destructive** — also drops all collections in it |
| `admin_collection_list` | ✓ | Collections in a scope |
| `admin_collection_create` | ✗ | Create collection |
| `admin_collection_drop` | ✗ | **Destructive** — also drops indexes scoped to it |
| `admin_collection_settings_set` | ✗ | Modify TTL, history retention |

## Users, groups, roles (RBAC)

| Tool | Read-only? | Notes |
|---|---|---|
| `admin_user_list` | ✓ | List all users |
| `admin_user_get` | ✓ | Detail for one user |
| `admin_user_create` | ✗ | New local user |
| `admin_user_update` | ✗ | Modify roles / password |
| `admin_user_delete` | ✗ | **Destructive** |
| `admin_group_list`, `admin_group_create`, `admin_group_update`, `admin_group_delete` | mixed | Group-based role assignment |
| `admin_role_list` | ✓ | All available roles (built-in) |
| `admin_role_get` | ✓ | Role details (privileges) |
| `admin_whoami` | ✓ | Effective roles for the authenticated user |

For Couchbase 8.x user lock/unlock and temporary-user features, see `couchbase-8x.md`.

**Common roles you'll see:**
- `admin` — full cluster admin
- `cluster_admin` — admin minus security
- `bucket_admin[bucket]` — manage one bucket
- `data_reader[bucket]` — read documents
- `data_writer[bucket]` — write documents
- `query_select[bucket]` — run SELECT queries
- `query_manage_index[bucket]` — create/drop indexes

Roles are bucket-scoped where shown with `[bucket]`. Pass `*` for all buckets.

## Audit & security policy

| Tool | Read-only? |
|---|---|
| `admin_audit_get` / `admin_audit_set` | mixed |
| `admin_password_policy_get` / `admin_password_policy_set` | mixed |
| `admin_security_get` / `admin_security_set` | mixed |

These control what gets audited (event categories), password requirements (length, complexity, history), and cluster-wide security flags (TLS enforcement, encryption-in-transit, etc.). Modifying `admin_security_set` is high-impact — surface every changed setting to the user before applying.

## Cluster topology

| Tool | Read-only? | Notes |
|---|---|---|
| `admin_cluster_status` | ✓ | Overall health (replaces `get_cluster_health_and_services`) |
| `admin_node_list` | ✓ | All nodes + services |
| `admin_node_add` | ✗ | Add a node (provisioning step) |
| `admin_node_remove` | ✗ | **Destructive** — remove a node |
| `admin_rebalance_start` | ✗ | Begin a rebalance (long-running) |
| `admin_rebalance_status` | ✓ | Progress of running rebalance |
| `admin_rebalance_stop` | ✗ | Cancel rebalance |
| `admin_failover_node` | ✗ | **Destructive** — hard-failover a node |
| `admin_failover_graceful` | ✗ | Graceful failover (drains first) |
| `admin_recovery_set` | ✗ | Set recovery type after failover |
| `admin_autofailover_get` / `admin_autofailover_set` | mixed | Auto-failover config |
| `admin_autocompaction_get` / `admin_autocompaction_set` | mixed | Auto-compaction policy |
| `admin_logs_get` | ✓ | Recent cluster logs |
| `admin_alerts_get`, `admin_alerts_set` | mixed | Email-alert recipients |
| `admin_alerts_test_email` | ✓ | Send a test email — useful for verifying SMTP config |
| `admin_server_group_*` | mixed | Server group (rack/zone awareness) |

**Rebalance flow** (most common destructive operation):

1. Confirm with user: "this will redistribute data across N nodes and may take hours; cluster will be online but degraded"
2. Call `admin_rebalance_start`
3. Poll `admin_rebalance_status` until `running: false`
4. If user cancels, call `admin_rebalance_stop` — but warn that partial rebalances leave the cluster in an inconsistent state until a successful rebalance completes

## XDCR (cross-datacenter replication)

| Tool | Read-only? |
|---|---|
| `admin_xdcr_remotes_list`, `admin_xdcr_remote_get` | ✓ |
| `admin_xdcr_remote_add`, `admin_xdcr_remote_update` | ✗ |
| `admin_xdcr_remote_delete` | ✗ |
| `admin_xdcr_replications_list`, `admin_xdcr_replication_get` | ✓ |
| `admin_xdcr_replication_create`, `admin_xdcr_replication_update` | ✗ |
| `admin_xdcr_replication_delete` | ✗ |
| `admin_xdcr_replication_pause`, `admin_xdcr_replication_resume` | ✗ |

For 8.x conflict logging (`admin_xdcr_conflict_log_query`), see `couchbase-8x.md`.

**Two-step setup:** XDCR needs a *remote cluster reference* first, then a *replication* on top of it. Use `admin_xdcr_remote_add` to register the target, then `admin_xdcr_replication_create` to actually start replicating a bucket.

## Indexes (GSI)

| Tool | Read-only? |
|---|---|
| `admin_index_list` | ✓ |
| `admin_index_get` | ✓ |
| `admin_index_create` | ✗ |
| `admin_index_create_primary` | ✗ |
| `admin_index_drop` | ✗ |
| `admin_index_build` | ✗ — kick off deferred build |
| `admin_index_alter` | ✗ — change replica count, partition |

**Defer index builds during bulk loads:** When creating multiple indexes on the same collection, use `with: {"defer_build": true}` on each, then call `admin_index_build` once at the end with all of them. This batches the actual building into a single scan pass.

**Primary indexes are expensive:** Use `admin_index_create_primary` only when the user explicitly wants one. Standard practice is to create secondary indexes covering the actual query patterns; the optimizer can stitch them together.

For vector indexes (8.x Hyperscale / Composite), see `couchbase-8x.md`.

## FTS admin

| Tool | Read-only? |
|---|---|
| `admin_fts_index_list` | ✓ |
| `admin_fts_index_get` | ✓ |
| `admin_fts_index_create` | ✗ |
| `admin_fts_index_update` | ✗ |
| `admin_fts_index_delete` | ✗ |
| `admin_fts_index_status` | ✓ |
| `admin_fts_index_pause` / `admin_fts_index_resume` | ✗ |
| `admin_fts_alias_create` / `admin_fts_alias_update` / `admin_fts_alias_delete` | ✗ |

For synonyms (8.x), see `couchbase-8x.md`.

## Stats & observability

| Tool | Read-only? |
|---|---|
| `admin_stats_*` | ✓ — many tools for various stat surfaces |
| `admin_system_events` | ✓ — system event log |
| `admin_node_self` | ✓ — info about the node serving this connection |
| `admin_internal` | ✓ — internal settings (advanced) |
| `admin_query_settings` | ✓ — query service settings |
| `admin_prometheus` | ✓ — Prometheus scrape endpoint (raw text) |

When the user asks for "current stats" or "cluster metrics," start with `admin_stats_overview` and drill down from there.

## Quick decision tree

- **"Create a new bucket / scope / collection"** → `admin_bucket_create` / `admin_scope_create` / `admin_collection_create`
- **"Who has access?"** → `admin_user_list` + filter by role; for "who am I?" use `admin_whoami`
- **"Add / remove a node"** → `admin_node_add` then `admin_rebalance_start`; for removal, `admin_node_remove` then `admin_rebalance_start`
- **"Rebalance is stuck"** → `admin_rebalance_status` to see progress; `admin_rebalance_stop` to cancel (but understand the risk)
- **"Set up XDCR"** → `admin_xdcr_remote_add` then `admin_xdcr_replication_create`
- **"Create / drop an index"** → `admin_index_create` / `admin_index_drop`
- **"Get cluster health"** → `admin_cluster_status`
- **"What's getting audited?"** → `admin_audit_get`
- **"Test email alerts"** → `admin_alerts_test_email`
