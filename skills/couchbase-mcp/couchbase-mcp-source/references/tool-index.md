# Tool index — alphabetical reference

A flat listing of all 167 tools across both servers, grouped by family for fast lookup. When you know what you want to do and just need the exact tool name, this is the page.

## Cluster server (151 tools) — `cb_*` and `admin_*`

### `cb_*` — data plane (43)

**KV operations**
- `cb_ping` — connectivity check
- `cb_get`, `cb_get_multi` — read
- `cb_upsert`, `cb_insert`, `cb_replace`, `cb_delete` — write
- `cb_lookup_in`, `cb_mutate_in` — subdocument

**Query**
- `cb_query` — SQL++ execution
- `cb_explain_query` — plan only
- `cb_get_schema_for_collection` — schema inference
- `cb_fts_search` — full-text search
- `cb_fts_synonym_upsert`, `cb_fts_synonym_list`, `cb_fts_synonym_delete` — synonyms (8.x)
- `cb_analytics_query` — Analytics service
- `cb_transaction_run` — multi-doc ACID

**Index advisor**
- `cb_index_advisor` — suggest indexes for a query

**Performance analysis** — `cb_perf_*`
- `cb_perf_slowest_queries`, `cb_perf_longest_running`
- `cb_perf_most_frequent`, `cb_perf_top_queries_by_count`, `cb_perf_top_queries_by_elapsed`
- `cb_perf_recent_query_failures`, `cb_perf_active_queries`
- `cb_perf_large_response_sizes`, `cb_perf_large_result_count`
- `cb_perf_not_using_covering_index`, `cb_perf_using_primary_index`, `cb_perf_not_selective`
- `cb_perf_by_user` (8.x)

### `admin_*` — cluster admin (105)

**Buckets** (~10)
- `admin_bucket_list`, `admin_bucket_get`
- `admin_bucket_create`, `admin_bucket_update`, `admin_bucket_delete`, `admin_bucket_flush`
- `admin_bucket_settings_get`, `admin_bucket_settings_set`
- `admin_bucket_autoscale_get`, `admin_bucket_autoscale_set`
- `admin_sample_buckets_list`, `admin_sample_buckets_install`

**Scopes & collections**
- `admin_scope_list`, `admin_scope_create`, `admin_scope_drop`
- `admin_collection_list`, `admin_collection_create`, `admin_collection_drop`, `admin_collection_settings_set`

**Users / RBAC** (~20)
- `admin_user_list`, `admin_user_get`, `admin_user_create`, `admin_user_update`, `admin_user_delete`
- `admin_user_lock`, `admin_user_unlock`, `admin_user_create_temporary` (8.x)
- `admin_group_list`, `admin_group_get`, `admin_group_create`, `admin_group_update`, `admin_group_delete`
- `admin_role_list`, `admin_role_get`
- `admin_whoami`
- `admin_audit_get`, `admin_audit_set`
- `admin_password_policy_get`, `admin_password_policy_set`
- `admin_security_get`, `admin_security_set`

**Cluster** (~30)
- `admin_cluster_status`
- `admin_node_list`, `admin_node_add`, `admin_node_remove`, `admin_node_self`
- `admin_rebalance_start`, `admin_rebalance_status`, `admin_rebalance_stop`
- `admin_failover_node`, `admin_failover_graceful`
- `admin_recovery_set`
- `admin_autofailover_get`, `admin_autofailover_set`, `admin_autofailover_reset`
- `admin_autocompaction_get`, `admin_autocompaction_set`
- `admin_logs_get`
- `admin_alerts_get`, `admin_alerts_set`, `admin_alerts_test_email`
- `admin_server_group_list`, `admin_server_group_create`, `admin_server_group_update`, `admin_server_group_delete`

**XDCR** (~11)
- `admin_xdcr_remotes_list`, `admin_xdcr_remote_get`
- `admin_xdcr_remote_add`, `admin_xdcr_remote_update`, `admin_xdcr_remote_delete`
- `admin_xdcr_replications_list`, `admin_xdcr_replication_get`
- `admin_xdcr_replication_create`, `admin_xdcr_replication_update`, `admin_xdcr_replication_delete`
- `admin_xdcr_replication_pause`, `admin_xdcr_replication_resume`
- `admin_xdcr_conflict_log_query` (8.x)

**Indexes** (GSI + vector)
- `admin_index_list`, `admin_index_get`
- `admin_index_create`, `admin_index_create_primary`
- `admin_index_drop`, `admin_index_build`, `admin_index_alter`
- `admin_vector_index_create_hyperscale`, `admin_vector_index_create_composite` (8.x)

**FTS admin**
- `admin_fts_index_list`, `admin_fts_index_get`
- `admin_fts_index_create`, `admin_fts_index_update`, `admin_fts_index_delete`
- `admin_fts_index_status`, `admin_fts_index_pause`, `admin_fts_index_resume`
- `admin_fts_alias_create`, `admin_fts_alias_update`, `admin_fts_alias_delete`

**Eventing** (10)
- `admin_eventing_list`, `admin_eventing_get`
- `admin_eventing_create`, `admin_eventing_update`, `admin_eventing_delete`
- `admin_eventing_deploy`, `admin_eventing_undeploy`
- `admin_eventing_pause`, `admin_eventing_resume`
- `admin_eventing_status`

**Backup**
- `admin_backup_repository_list`, `admin_backup_repository_get`
- `admin_backup_run`, `admin_backup_restore_run`
- `admin_backup_status`

**Encryption / KMIP** (8.x)
- `admin_encryption_get`, `admin_encryption_set`, `admin_encryption_rotate`, `admin_encryption_status`
- `admin_kmip_get`, `admin_kmip_set`, `admin_kmip_test`, `admin_kmip_rotate`

**Stats / observability**
- `admin_stats_overview`, `admin_stats_bucket`, `admin_stats_query`, `admin_stats_index`, `admin_stats_fts`, `admin_stats_analytics`, `admin_stats_eventing`, `admin_stats_xdcr`, `admin_stats_search`
- `admin_system_events`
- `admin_internal`, `admin_query_settings`, `admin_prometheus`

## Capella server (16 tools) — `capella_*`

Run separately from the cluster server. Different auth (Bearer via `CAPELLA_API_KEY_SECRET`), different endpoint (`cloudapi.cloud.couchbase.com`).

**Organization**
- `capella_organizations_list`, `capella_organization_get`
- `capella_org_users_list`, `capella_org_user_get`
- `capella_api_keys_list`, `capella_api_key_get`

**Projects**
- `capella_projects_list`, `capella_project_get`

**Clusters**
- `capella_clusters_list`, `capella_cluster_get`

**Cluster sub-resources** (each requires orgId + projectId + clusterId)
- `capella_database_users_list`, `capella_database_user_get`
- `capella_allowed_cidrs_list`, `capella_allowed_cidr_get`
- `capella_app_services_list`, `capella_app_service_get`

## Task → tool mapping

A reverse index — when you know what you want to do but not the exact name:

| Task | Tool |
|---|---|
| Check connectivity | `cb_ping` |
| Read a document | `cb_get` |
| Read many documents | `cb_get_multi` |
| Read a field inside a document | `cb_lookup_in` |
| Write a document | `cb_upsert` (or `cb_insert`/`cb_replace` for stricter semantics) |
| Modify a field inside a document | `cb_mutate_in` |
| Delete a document | `cb_delete` (requires `confirm:true`) |
| Run SQL++ | `cb_query` |
| See query plan | `cb_explain_query` |
| Explore schema | `cb_get_schema_for_collection` |
| Full-text search | `cb_fts_search` |
| Suggest indexes for a query | `cb_index_advisor` |
| Find slow queries | `cb_perf_slowest_queries` / `cb_perf_top_queries_by_elapsed` |
| Find frequent queries | `cb_perf_most_frequent` |
| Find queries doing full scans | `cb_perf_using_primary_index` |
| List buckets | `admin_bucket_list` |
| Create a bucket | `admin_bucket_create` |
| Install travel-sample | `admin_sample_buckets_install` |
| Create a scope/collection | `admin_scope_create` / `admin_collection_create` |
| List users | `admin_user_list` |
| Create a user | `admin_user_create` |
| Lock a user (8.x) | `admin_user_lock` |
| Get cluster health | `admin_cluster_status` |
| Start rebalance | `admin_rebalance_start` |
| Set up XDCR | `admin_xdcr_remote_add` then `admin_xdcr_replication_create` |
| Create a vector index (8.x) | `admin_vector_index_create_composite` |
| Define FTS synonyms (8.x) | `cb_fts_synonym_upsert` |
| Deploy an Eventing function | `admin_eventing_create` then `admin_eventing_deploy` |
| Run a backup | `admin_backup_run` |
| Restore from backup | `admin_backup_restore_run` (requires `confirm:true`) |
| Enable encryption at rest (8.x) | `admin_encryption_set` |
| List Capella organizations | `capella_organizations_list` |
| List Capella clusters | `capella_clusters_list` |
| See Capella allowlist | `capella_allowed_cidrs_list` |
