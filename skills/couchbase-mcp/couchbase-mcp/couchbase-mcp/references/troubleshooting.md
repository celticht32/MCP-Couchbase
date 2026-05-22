# Troubleshooting

When the MCP returns an error or a tool's result doesn't match what the user expects, work through these patterns. Each section starts with the symptom (what the user sees or what error the MCP returns), then gives the likely causes and the diagnostic tool to confirm.

## Connection failures

### Symptom: "could not connect to cluster" / "connection refused"

**Likely causes (in order of frequency):**

1. **Wrong connection string scheme.** `couchbase://` for non-TLS, `couchbases://` for TLS. Capella requires `couchbases://`. Mixing them up is the most common error.
2. **Wrong management port.** Default is 8091 for self-managed clusters, 18091 for Capella. The MCP env var `CB_MGMT_PORT` controls this.
3. **TLS cert not trusted.** Self-signed certs need `CB_CA_CERT_PATH` set; otherwise the SDK refuses the connection.
4. **Network firewall blocking** the data ports (11207 for TLS KV, 11210 for non-TLS KV). The cluster manager port (8091/18091) responds but actual data ops fail.
5. **Cluster is genuinely down.** Rare but happens — check `admin_cluster_status` if you can reach the manager at all.

**Diagnostic flow:**
- Call `cb_ping` first — this is the cheapest connectivity test
- If `cb_ping` fails: try `admin_cluster_status` (different code path; may succeed and reveal whether the issue is data-service-specific)
- If both fail: check the connection string and credentials; nothing else matters until basic connectivity works

### Symptom: connection works, then drops after a while

Almost always TCP keepalive issues. The SDK's idle connections get reaped by a NAT or load balancer. Set the SDK's keepalive interval shorter than the network's idle timeout. The MCP doesn't expose this directly — it's an SDK config the user must adjust in their environment.

## Authentication failures

### Symptom: "Unauthorized" / "401" / "user not found"

**Likely causes:**

1. **Wrong username or password.** Most common. Check `CB_USERNAME` / `CB_PASSWORD` env vars.
2. **User exists but doesn't have the role for this operation.** The error often says "Forbidden" rather than "Unauthorized" in this case. Diagnose with `admin_whoami` (shows the authenticated user's effective roles).
3. **User was locked** (8.x). Check with `admin_user_get` — look for `locked: true`. Unlock with `admin_user_unlock` if appropriate.
4. **Capella database user vs control-plane API key confusion.** Database users authenticate to `cb_*` / `admin_*` tools. API keys authenticate to `capella_*` tools. They're not interchangeable.

**Diagnostic flow:**
- `admin_whoami` to confirm who you're authenticated as and what roles you have
- If `admin_whoami` works but the target tool fails with Forbidden: the user lacks the role; check the role list in `cluster-admin.md`
- If `admin_whoami` itself fails: the credentials are wrong

### Symptom: Capella API call returns 403 Forbidden

The API key lacks the role for that endpoint. Many Capella read operations need only Project Viewer; some (`capella_api_keys_list`) need Organization Owner.

**Diagnostic flow:**
- Call `capella_organizations_list` first — if this works, the key is valid but may be project-scoped
- Check the key's scope in the Capella web UI
- Either widen the key's permissions or use a different key

## Query errors

### Symptom: "syntax error" in SQL++

Couchbase's SQL++ has a few syntactic differences from standard SQL:
- Identifiers with special characters or keywords need backticks: `` SELECT * FROM `my-bucket`.`scope`.`collection` ``
- Date literals: `STR_TO_MILLIS("2026-01-01")` or `MILLIS_TO_STR(...)` — no native DATE type
- ARRAY syntax for filtering arrays: `ANY x IN array SATISFIES x.field = "value" END`

Run `cb_explain_query` to confirm parse — it will surface syntax errors with line/column info.

### Symptom: query is correct but returns wrong results

Common cause: a stale or partial index. Indexes in Couchbase are eventually consistent by default. To force consistency:

```json
{
  "tool": "cb_query",
  "arguments": {
    "statement": "SELECT * FROM users WHERE tier = 'gold'",
    "scan_consistency": "request_plus"
  }
}
```

`request_plus` makes the query wait for the index to catch up to the current sequence number before returning. Slower but correct.

### Symptom: "no index available" / very slow query

The query is doing a primary scan or no scan at all. Run `cb_explain_query` — look for `PrimaryScan` in the plan. Then call `cb_index_advisor` with the same statement to get suggested index DDL.

## Index issues

### Symptom: "Index not found" when querying

Either the index doesn't exist (check `admin_index_list`) or it was created but never built. Indexes created with `defer_build: true` need a follow-up `admin_index_build` call.

### Symptom: index exists but query plan ignores it

The optimizer didn't pick it. Common reasons:
- The WHERE clause doesn't match the index keys (LEADING fields)
- The index is on a different scope/collection than the query thinks
- The index is in `errored` state — check with `admin_index_get`

Use `cb_explain_query` to see which index (if any) the optimizer chose, then compare against `admin_index_list`.

### Symptom: index stays in "building" status forever

For large collections, builds can legitimately take hours. But if it's been > 1 day and the cluster is otherwise idle, it may be stuck. Check `admin_stats_index` for build progress (`progress_percent` field). If progress is at 0%, drop and recreate the index — the build worker may have crashed.

## XDCR replication lag

### Symptom: source has writes that haven't appeared on target

**Diagnostic flow:**
1. `admin_xdcr_replication_get` for the replication — look at `current_throughput`, `changes_left`, `time_committing` fields
2. If `changes_left > 0` but `current_throughput` is low: bandwidth-limited. Either the network or the replication's throttle settings (configurable via `admin_xdcr_replication_update`)
3. If `current_throughput` is 0: the replication is paused or broken. Check `admin_xdcr_replication_get` for `paused: true`
4. If the conflict log (8.x, `admin_xdcr_conflict_log_query`) shows recent entries: conflicts are being resolved against your writes; that's not lag, that's loss

## Eventing function failures

### Symptom: "deploy failed" on `admin_eventing_deploy`

Most common causes:
- JavaScript syntax error in the function code — the error response usually includes the line number
- The function references a bucket/scope/collection that doesn't exist
- The function uses a binding alias that wasn't declared in the function settings

Get the full error via `admin_eventing_get` after the failed deploy — the `last_error` field has the details.

### Symptom: function deployed but isn't processing events

Check `admin_eventing_status` for the function. Look for:
- `deployment_status`: should be `deployed`
- `processing_status`: should be `running` (if `paused`, resume with `admin_eventing_resume`)
- `success_count` vs `failure_count`: ratio tells you if the function is running but failing

If `failure_count` is high: read the function's log bucket for error details. Eventing functions log to a `log_bucket` that's defined in the function settings.

## Backup / restore failures

### Symptom: backup completes but is missing data

Check `admin_backup_status` for the backup run. The status response includes per-bucket coverage. If a bucket is missing, the backup repository config didn't include it.

### Symptom: restore fails partway through

Restores are NOT transactional. A partial restore leaves the target in an inconsistent state — some docs from the backup are present, some are not, and any docs that existed before the restore started may or may not have been overwritten. Recovery options:
- Restore the rest manually (restart with `--resume` if `admin_backup_restore_run` supports it for your version)
- Restore from scratch to an empty bucket (`admin_bucket_flush` first, then restore)
- Restore to a different bucket and copy what you need

The safer pattern: always restore to a `<bucket>_restore` bucket first, validate, then swap. Documented in `operational-runbooks.md`.

## KMIP failures

### Symptom: `admin_kmip_test` returns success but `admin_encryption_set` with KMIP fails

`admin_kmip_test` only tests TCP connectivity and basic handshake. Enabling KMIP-backed encryption requires:
- The KMIP user has the right permissions (varies by KMIP server)
- The master key referenced in `admin_kmip_set` actually exists on the KMIP server
- The certificate paths are correct and the certs are not expired

Check the KMIP server's logs — the Couchbase-side error often doesn't tell you which check failed.

## Capella-specific errors

### Symptom: "Cluster not found" in `capella_cluster_get`

Either the `clusterId` is wrong, or it's in a different project than the `projectId` you passed. Walk the hierarchy again: `capella_projects_list` to see all projects you have access to, `capella_clusters_list` with each project's ID to find where this cluster actually lives.

### Symptom: rate-limited (429 errors) from Capella

The API key has hit the per-key request limit (~100/minute). The MCP retries with exponential backoff, but extended runs may still saturate. Either pace the calls, or split work across multiple API keys with the same role.

## Generic catch-all

### Symptom: tool returns an error you don't understand

The MCP's error responses include a `hint` field where possible. Read it before going further — it usually points to the specific check that failed. If the hint is empty or unhelpful, the underlying error often has more detail in the Couchbase logs (`admin_logs_get`).

If you've exhausted these and don't know what to do, surface the full error to the user verbatim and ask them to check the Couchbase admin console for additional context. The MCP doesn't see everything the cluster sees.
