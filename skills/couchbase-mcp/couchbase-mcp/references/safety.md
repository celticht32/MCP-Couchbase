# Safety — destructive operations and how to approach them

The MCP server enforces two safety mechanisms; this reference explains them and lists the operations they cover.

## Mechanism 1: read-only mode

`CB_MCP_READ_ONLY_MODE=true` (set in the MCP server's environment) filters destructive tools out of the tool listing entirely. They become invisible — calling them returns an "unknown tool" error.

**You can't override this from the client side.** Don't try. If a tool you need isn't available because the server is in read-only mode, surface that to the user: "the MCP is running in read-only mode; either temporarily unset CB_MCP_READ_ONLY_MODE in its environment and restart, or do this through the Couchbase web console."

The default for `CB_MCP_READ_ONLY_MODE` in the celticht32 fork is **opt-in** (defaults to false). This is a deliberate difference from the official MCP server (which defaults read-only to true) — the celticht32 is intended as an operator tool. Operators usually want the writes; AI assistants usually want the reads. If you're an AI assistant operating the MCP for an LLM-driven flow, recommend the user set read-only mode in their MCP config.

## Mechanism 2: confirmation gate

Destructive tools require `confirm: true` in their arguments. Without it, the tool returns a structured error like:

```json
{
  "ok": false,
  "error": "Destructive operation requires confirm:true",
  "would_do": {
    "operation": "admin_bucket_delete",
    "target": "my-bucket",
    "impact": "Deletes the bucket and all its data. No recovery without a backup.",
    "reversible": false
  }
}
```

The `would_do` field is what you should surface to the user before re-calling with `confirm: true`. Always show the impact, get explicit user confirmation, then resubmit with the confirmation flag.

## How to handle a destructive request

The right flow for any destructive operation:

1. **Identify the impact** — what data / config will change, is it reversible, what's the blast radius?
2. **State it to the user clearly** — "this will delete bucket X, which contains 4.7M documents and ~2 GB. There's no automatic recovery; rollback requires restoring from backup."
3. **Ask for explicit confirmation** — not "should I proceed?" but "type 'yes, delete X' to confirm" or equivalent. Don't accept ambiguous answers.
4. **Call with `confirm: true`** only after step 3.
5. **Surface the result** — if the operation succeeded, say so. If it failed, surface the error verbatim.

Don't skip step 2-3 even if the user said "delete it" earlier in the conversation. Ambiguity is one of the most common causes of "I lost my data" incidents.

## Full taxonomy of destructive operations

### Hard-destructive (data loss, irreversible without backup)

- `cb_delete` — Delete one document by ID
- `admin_bucket_delete` — Delete an entire bucket and all its data
- `admin_bucket_flush` — Delete all documents in a bucket but keep the bucket
- `admin_scope_drop` — Delete a scope and all its collections (recursive)
- `admin_collection_drop` — Delete a collection and all its documents
- `admin_xdcr_replication_delete` — Stop replication (the source data is intact, but the target is no longer kept in sync)

### Soft-destructive (reversible but requires effort)

- `admin_index_drop` — Drop a secondary index. Recoverable by recreating, but rebuilding can take hours on large collections
- `admin_fts_index_delete` — Delete an FTS index. Same: recreate + rebuild
- `admin_user_delete` — Delete a user. Recoverable if you remember the role assignments

### Topology changes (high impact, hard to undo)

- `admin_node_remove` — Remove a node from the cluster. Always followed by `admin_rebalance_start`
- `admin_failover_node` — Hard-failover a node. Irreversible — the node is marked failed and must be added back as a new node
- `admin_failover_graceful` — Graceful failover. Same effect as hard-failover but the failed node drains first
- `admin_rebalance_start` — Begins data redistribution. Long-running (minutes to hours). Can be stopped mid-flight but leaves the cluster in an inconsistent state until a successful rebalance completes

### Security changes (audit-worthy)

- `admin_user_lock` (8.x) — Locks a user account
- `admin_security_set` — Modifies cluster-wide security settings (TLS, encryption-in-transit, etc.). Surface every changed setting to the user
- `admin_audit_set` — Modifies what's audited. If this is being turned off, that's noteworthy
- `admin_password_policy_set` — Modifies password requirements

### Encryption (multi-stage impact)

- `admin_encryption_set` — Enable or disable DARE. Enabling on existing data triggers a background re-encryption pass — cluster stays online but I/O is heavier
- `admin_encryption_rotate` — Rotate the data encryption key. Background re-encryption
- `admin_kmip_rotate` — Rotate the master KMIP key. Depends on KMIP server's behavior

### Backup / restore

- `admin_backup_restore_run` — **Hard-destructive.** Overwrites current data with backup contents. The user almost always wants to confirm the target bucket and the backup snapshot ID. A wrong choice here can erase production data with a stale backup

### Eventing

- `admin_eventing_delete` — Delete a function definition (soft-destructive — function code is gone, but its actions on data so far remain)
- `admin_eventing_undeploy` — Stop running a function (non-destructive — preserves the function definition, just stops execution)

### Capella (write operations)

There aren't any. `capella_*` is entirely read-only by design. If the user asks to do a Capella write, point them at the Capella web UI.

## What's NOT destructive but feels like it might be

These are safe to call without confirmation:

- All `admin_*_list` / `admin_*_get` / `capella_*_list` / `capella_*_get` — pure reads
- `cb_get`, `cb_get_multi`, `cb_query` (SELECT only), `cb_explain_query`, `cb_get_schema_for_collection`, `cb_lookup_in`
- `cb_perf_*` — all read-only
- `admin_cluster_status`, `admin_node_list`, `admin_logs_get`, `admin_stats_*`
- `admin_rebalance_status`, `admin_xdcr_replication_get`, `admin_fts_index_status`
- `admin_alerts_test_email` — sends one test email, doesn't change anything persistent
- `admin_index_advisor` — returns suggestions only, doesn't create anything
- `admin_kmip_test` — tests connectivity, doesn't change config

## Concrete dialog patterns

**Pattern: deleting a bucket**

User: "Delete the staging-old bucket"
You: "Before I delete `staging-old`, I want to confirm: this will permanently delete the bucket and all documents in it. There's no automatic recovery — rollback requires a backup. The current bucket has [X] documents and [Y] GB of data (per `admin_bucket_get`). To proceed, type 'yes, delete staging-old'."
User: "yes, delete staging-old"
You: [calls `admin_bucket_delete` with `bucket_name: "staging-old"`, `confirm: true`]
You: "Deleted. Bucket `staging-old` is gone."

**Pattern: rebalancing**

User: "Rebalance the cluster"
You: "Confirm: starting a rebalance will redistribute data across the current node set. The cluster stays online but performance may be degraded for the duration of the rebalance. Estimated time depends on data volume — could be minutes to hours. Proceed?"
User: "yes"
You: [calls `admin_rebalance_start` with `confirm: true`]
You: "Rebalance started. I'll poll `admin_rebalance_status` and let you know when it completes."

**Pattern: restoring from backup (especially high-stakes)**

User: "Restore the prod backup from yesterday"
You: "Restoring will OVERWRITE the current `prod` bucket with the backup snapshot. Any writes since the backup will be lost. Before I proceed, let me confirm two things: (1) the backup snapshot ID — `admin_backup_repository_list` shows [list snapshots] — which one do you want? (2) the target bucket — restoring to `prod` will affect live data; do you want to restore to a different bucket like `prod_restore` for verification first?"
[wait for unambiguous answer to both]
[then call `admin_backup_restore_run` with `confirm: true`]
