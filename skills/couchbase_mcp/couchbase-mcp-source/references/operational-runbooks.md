# Operational runbooks

Step-by-step procedures for high-stakes multi-step operations. Each runbook follows the same shape: preconditions, the sequence of tool calls, what to verify between steps, and what to do if it goes wrong.

When the user asks "how do I do X" where X is one of these, use the matching runbook. Don't improvise the order — the steps are sequenced to keep the cluster available and the data recoverable.

## Rolling upgrade

**When to use:** upgrading Couchbase Server from version N to N+1 across all nodes, without taking the cluster offline.

**Preconditions:**
- Cluster is healthy (`admin_cluster_status` returns `healthy: true`)
- Replicas ≥ 1 for every bucket (otherwise upgrading a node loses availability for any data only on that node)
- Backup is recent (`admin_backup_status` shows a successful run within the last 24h, or the user accepts the risk)

**Procedure:**

1. `admin_cluster_status` — record current node count, services per node, and replica counts. Save this somewhere outside the cluster
2. Pick the first node to upgrade (start with a non-orchestrator if possible — see `admin_node_self` to identify it)
3. Surface to user: "I'm about to remove node X from rotation, upgrade it, and add it back. The cluster stays online but throughput on the data services on this node drops to its replicas during the process. Continue?"
4. `admin_failover_graceful` for the node (drains active traffic to replicas first; gentler than hard-failover)
5. Verify failover completed: `admin_cluster_status` shows the node in `inactiveFailed` state
6. **Out-of-band step (not via MCP):** the user manually upgrades the Couchbase binary on that node and starts the service. The MCP can't do this — it's a shell/service operation on the node itself
7. `admin_recovery_set` with `recovery_type: delta` (faster — only re-syncs changed data) — or `recovery_type: full` if the node was offline longer than the typical replication window
8. `admin_rebalance_start` with `confirm: true` to integrate the upgraded node back into the cluster
9. Poll `admin_rebalance_status` until complete
10. Verify: `admin_cluster_status` shows the node `active` again, on the new version
11. Repeat steps 2-10 for each remaining node
12. After ALL nodes are upgraded, the cluster compatibility version updates automatically. Verify with `admin_cluster_status` (`cluster_compat_version` field)

**If it goes wrong:**
- During step 4-7 (node failed over but upgrade itself failed): user can downgrade the binary, then `admin_recovery_set` + `admin_rebalance_start` to bring the node back at the original version. The cluster never went offline; you just have one less node temporarily
- During step 8 (rebalance fails partway): `admin_rebalance_stop`, then investigate via `admin_logs_get`. The cluster is left in a partially-rebalanced state but data is safe. Don't proceed to the next node until the current one's rebalance completes successfully

## Adding a node to expand capacity

**When to use:** scaling up the cluster — adding a node to increase RAM, disk, or query throughput.

**Preconditions:**
- The new node has Couchbase Server installed at the same version as the existing cluster
- The new node can reach the cluster manager (port 8091/18091) network-wise
- An admin user exists on the cluster

**Procedure:**

1. `admin_cluster_status` — note current node count and per-node memory/storage
2. `admin_node_add` with the new node's hostname/IP, admin credentials, and the services to enable on it (`data`, `query`, `index`, `fts`, `eventing`, `analytics`, `backup`)
3. Verify: `admin_node_list` now shows the new node in `inactiveAdded` state (added but not serving traffic)
4. Surface to user: "Node added. To start serving traffic, I need to rebalance — this redistributes data across the new node set. Estimated time: depends on data volume, typically minutes to hours. Continue?"
5. `admin_rebalance_start` with `confirm: true`
6. Poll `admin_rebalance_status` until complete
7. Verify: `admin_cluster_status` shows the new node `active`

**If it goes wrong:**
- Step 2 fails ("node already in cluster" / "version mismatch"): the new node was either previously added (check `admin_node_list`) or is on a different version (upgrade it first)
- Step 5-6 (rebalance fails): `admin_rebalance_stop`, fix the root cause from logs, then resume by calling `admin_rebalance_start` again. The cluster is fine in the meantime — the new node just isn't yet serving traffic

## Removing a node to scale down or replace hardware

**When to use:** taking a node out of the cluster for hardware replacement or to reduce capacity.

**Preconditions:**
- Replicas ≥ 1 on all buckets (otherwise removing a node loses data)
- Remaining nodes have enough capacity to hold this node's data and traffic after redistribution

**Procedure:**

1. `admin_cluster_status` and `admin_node_list` — record current state, especially this node's data footprint
2. `admin_stats_overview` — check current cluster utilization. If you're already at 80%+ RAM, removing a node may push you over the edge
3. Surface to user with calculated impact: "removing this node will cause its ~X GB of data to be redistributed; expected RAM utilization after removal: Y%"
4. `admin_node_remove` with the target node hostname/IP
5. Verify: `admin_node_list` shows the node in `inactiveFailed` state
6. `admin_rebalance_start` with `confirm: true` — this is what actually redistributes the data
7. Poll `admin_rebalance_status` until complete
8. Verify: `admin_node_list` no longer shows the removed node
9. (User step, not via MCP): shut down Couchbase on the removed node, repurpose / decommission

**If it goes wrong:**
- Rebalance fails because remaining nodes are out of capacity: `admin_rebalance_stop`, then add a replacement node first via the "adding a node" runbook, then retry the removal

## Post-failover recovery

**When to use:** a node was auto-failed-over (by autofailover) or hard-failed-over (manually). You need to bring it back.

**Preconditions:**
- The reason for the failover is known and resolved (network was restored, disk was replaced, etc.)
- The failed node is reachable again

**Procedure:**

1. `admin_cluster_status` — confirm the node is `inactiveFailed`
2. Check `admin_logs_get` — understand what caused the original failover so you know whether to use delta or full recovery
3. `admin_recovery_set`:
   - `recovery_type: delta` if the node was offline less than the bucket's metadata retention window (faster, only re-syncs changes)
   - `recovery_type: full` if it was offline longer, or if the disk was replaced
4. `admin_rebalance_start` with `confirm: true`
5. Poll `admin_rebalance_status` until complete
6. Verify: `admin_node_list` shows the node `active`

**If it goes wrong:**
- Delta recovery fails ("changes too large"): switch to `full` recovery and retry
- The node simply can't be recovered (disk corruption, etc.): treat it as a permanent loss — remove it from the cluster and add a fresh node

## Restoring from backup (safely)

**When to use:** recovering from data loss or rolling back a bad change.

**Preconditions:**
- A valid backup exists (`admin_backup_repository_list` shows the snapshot)
- You have a clear answer to "restore to where?" — typically NOT directly over production

**Procedure — the safe way:**

1. `admin_backup_repository_list` — find the snapshot. Note its ID and timestamp
2. Surface to user: "Restoring directly over the current bucket is risky — any writes since the backup will be lost. I recommend restoring to a temporary bucket first, validating, then deciding whether to swap. Proceed with the safe pattern?"
3. `admin_bucket_create` for a new bucket named `<original>_restore_<date>` with the same settings as the original (`admin_bucket_get` on the original gives you the config)
4. `admin_backup_restore_run` with `confirm: true`, targeting the new bucket
5. Wait for completion via `admin_backup_status`
6. User validates the restored data
7. If valid: the user decides whether to keep the original (this is a recovery copy for reference) or swap. Swapping is application-specific — usually it means redirecting client config to the new bucket, then deleting the old one days/weeks later
8. If invalid: `admin_bucket_delete` the restore bucket; the original is untouched

**Procedure — the unsafe way (when the user insists on restoring over production):**

1. `admin_backup_repository_list` — find the snapshot. Note its ID
2. Surface to user EXPLICITLY: "This will OVERWRITE the current `<bucket>` bucket. Any writes since the backup timestamp `<timestamp>` will be permanently lost. There is no automatic rollback. Confirm with 'yes, overwrite <bucket>'"
3. Wait for unambiguous confirmation
4. `admin_backup_restore_run` with `confirm: true`, targeting the production bucket
5. Wait for completion via `admin_backup_status`
6. Validate via `cb_query` on representative data

**If it goes wrong:**
- The restore failed partway: the target bucket is in an inconsistent state (some docs from the backup, possibly some pre-existing docs). Either `admin_bucket_flush` (if no recovery is needed) then restart the restore, or attempt incremental recovery by re-restoring (depends on backup tool version)

## Enabling DARE on existing data

**When to use:** turning on Data-at-Rest Encryption for a cluster that already has data.

**Preconditions:**
- KMIP server is configured if using KMIP (`admin_kmip_test` returns success)
- The cluster has spare I/O — re-encryption is I/O-intensive

**Procedure:**

1. `admin_encryption_get` — confirm current state is "disabled"
2. Surface to user: "Enabling DARE triggers a background re-encryption pass on existing data. The cluster stays online but I/O is heavier for the duration. Estimated time scales with total data size — typically hours for production-scale buckets. Continue?"
3. `admin_encryption_set` with the encryption config and `confirm: true`
4. Poll `admin_encryption_status` — shows per-bucket re-encryption progress
5. Verify: `admin_encryption_get` returns the new state once re-encryption completes

**If it goes wrong:**
- Re-encryption stalls (`admin_encryption_status` shows no progress): check `admin_stats_overview` for I/O saturation; throttle other work, or accept slower progress
- KMIP becomes unreachable mid-encryption: the cluster stops accepting new writes until KMIP is restored. Fix KMIP connectivity first

## Rotating credentials

**When to use:** credential rotation (suspected compromise, regular schedule, employee departure).

### Rotating a database user's password

1. `admin_user_get` — confirm the user exists and note their current roles
2. Generate a new strong password
3. `admin_user_update` with the new password (`confirm: true` if required for password changes in your config)
4. Distribute the new password to all systems using this credential
5. Validate connectivity from those systems
6. Done — the old password is now invalid

### Rotating a Capella API key

The MCP doesn't expose Capella write operations (see `capella-v4.md`). The procedure must be done via the Capella web UI:

1. In Capella UI, create a new API key with the same roles as the old one
2. Update systems that use the old key to use the new key
3. Validate (call `capella_organizations_list` with the new key via the MCP — should succeed)
4. In Capella UI, revoke the old key

### Rotating the DARE master key

1. `admin_encryption_get` — confirm current state and key ID
2. Surface to user: "Key rotation triggers a re-encryption pass with the new master key. Cluster stays online but I/O is heavier. Continue?"
3. `admin_encryption_rotate` with `confirm: true`
4. Poll `admin_encryption_status` for re-encryption progress
5. Verify: `admin_encryption_get` returns the new key ID

For KMIP-managed keys: `admin_kmip_rotate` instead. The KMIP server generates the new key; Couchbase initiates re-encryption with the new key reference.

## A general pattern for any "I want to do X" runbook the user invents

If the user asks for a procedure not listed here, follow this shape:

1. **Preconditions** — what must be true before starting (replica count, recent backup, version, etc.)
2. **Step-by-step** — concrete tool calls, with what to verify between them
3. **Rollback** — what to do if any step fails
4. **Confirmation gates** — destructive steps get explicit user confirmation before `confirm: true` is passed

Don't skip the rollback step. Real operational pain comes from being mid-procedure when something fails and not knowing what state the system is in.
