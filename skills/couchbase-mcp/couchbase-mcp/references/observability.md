# Observability — what to monitor and how

A reference for setting up monitoring, picking the right stats, and knowing what to alert on. The cluster exposes substantial telemetry; the trick is knowing which numbers matter and what their thresholds should be.

## The stats hierarchy

Couchbase exposes stats at several levels:

1. **Cluster-wide** — overall health, node count, services up
2. **Per-node** — CPU, RAM, disk, network for each node
3. **Per-service** — Data, Query, Index, FTS, Eventing, Analytics each have their own stats
4. **Per-bucket** — write/read ops, memory usage, item count, replicas
5. **Per-collection / per-scope** — more granular, useful for multi-tenant
6. **Per-query / per-index** — drilling into specific items

Always start broad (cluster) and drill down to the layer where the symptom appears.

## The right tools for the job

The MCP exposes a family of stats tools, each oriented around a service or surface:

| Tool | What it surfaces |
|---|---|
| `admin_stats_overview` | High-level cluster: utilization, op rates, alerts. **Start here for anything.** |
| `admin_stats_bucket` | Per-bucket: docs, memory, op rates, replication queue |
| `admin_stats_query` | Query service: request rate, error rate, slow query count |
| `admin_stats_index` | GSI: index sizes, scan rates, build progress |
| `admin_stats_fts` | FTS: search rate, index sizes, query latency |
| `admin_stats_search` | Search (8.x): vector + FTS combined view |
| `admin_stats_analytics` | Analytics service utilization and shadow-dataset lag |
| `admin_stats_eventing` | Per-function: invocations, failures, processing time |
| `admin_stats_xdcr` | XDCR: per-replication throughput, lag, conflicts |
| `admin_prometheus` | Raw Prometheus-format scrape endpoint for external monitoring |
| `admin_system_events` | Audit-style event log (failovers, config changes, etc.) |
| `admin_logs_get` | Recent cluster logs (errors, warnings) |

When debugging an issue: `admin_stats_overview` first, then the per-service stats tool for whichever service the problem touches, then `admin_logs_get` for the error context.

## Metrics that matter

Of the hundreds of metrics Couchbase exposes, these are the ones to actually watch.

### Data service (KV)

| Metric | What it tells you | Alert threshold |
|---|---|---|
| `cache_miss_ratio` | % of reads that had to fetch from disk | > 5% sustained = working set too big for RAM |
| `ep_resident_items_rate` | % of items in RAM (valueOnly eviction) | < 90% = consider more RAM or fullEviction |
| `ep_oom_errors` | Out-of-memory rejections | > 0 = immediate alert, writes are failing |
| `disk_write_queue` | Pending writes to disk | > 1M sustained = disk can't keep up |
| `ep_tmp_oom_errors` | Temporary OOM (transient) | > 0 sustained = memory pressure |
| `vb_active_resident_items_ratio` | Working set resident in RAM | < 85% = working set under-sized |
| `bytes_read` / `bytes_written` | Network throughput per bucket | Trend monitoring for capacity planning |

### Query service

| Metric | What it tells you | Alert threshold |
|---|---|---|
| `n1ql_requests` | Query rate | Baseline for capacity planning |
| `n1ql_errors` | Failed queries | > 1% of requests = investigate |
| `n1ql_slow_queries` | Queries over the slow-query threshold | Spike = something changed |
| `n1ql_active_requests` | Currently running | > query-service-thread-count sustained = thread pool exhausted |

### Index service

| Metric | What it tells you | Alert threshold |
|---|---|---|
| `index_resident_percent` | % of index in RAM | < 100% = index doesn't fit; slower scans |
| `index_data_size` | Total index bytes | Trend monitoring |
| `index_num_pending_requests` | Scan queue depth | > thread count sustained = scan throughput limited |
| `indexer_state` | Active / Paused / Recovery | anything other than Active = problem |

### XDCR

| Metric | What it tells you | Alert threshold |
|---|---|---|
| `changes_left` | Documents not yet replicated | Growing trend = replication falling behind |
| `bandwidth_usage` | Replication bandwidth | Useful for capacity planning |
| `docs_processed` | Replication throughput | Compare against write rate on source |
| `data_replicated_age` | Lag of replication (seconds) | > 60 seconds sustained = investigate |

### Eventing

| Metric | What it tells you | Alert threshold |
|---|---|---|
| `processing_status` | Function active or paused | Paused unexpectedly = alert |
| `success_count` / `failure_count` | Per-function execution outcomes | failure ratio > 1% = investigate |
| `on_update_latency` | How long function takes per invocation | Trending up = function slowing down |
| `dcp_backlog` | Backlog of mutations the function hasn't processed | Growing = function can't keep up |

### Cluster-wide

| Metric | What it tells you | Alert threshold |
|---|---|---|
| `rebalance_running` | Whether a rebalance is active | True for hours = stuck rebalance |
| `node_status` (per node) | Up / Warmup / Failed | Anything not "Up" = investigate |
| `autofailover_count` | Autofailovers triggered recently | > 0 = at least one node failed |
| `disk_used_percent` (per node) | Disk fill | > 80% = scale soon; > 90% = scale now |

## Prometheus integration

The simplest external-monitoring integration uses `admin_prometheus`, which returns Prometheus-format text from the cluster. Configure your Prometheus server to scrape it:

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'couchbase'
    metrics_path: /metrics
    static_configs:
      - targets: ['cb-node-1:8091', 'cb-node-2:8091', 'cb-node-3:8091']
    basic_auth:
      username: 'monitor_user'
      password: '<password>'
```

Once scraped, Couchbase metrics flow into your existing Prometheus + Grafana stack alongside everything else. Dedicated Couchbase dashboards exist on Grafana Labs' dashboard registry — search "Couchbase" there for community-maintained ones.

## Recommended alerts

A starter alert set for production:

**Critical (page someone):**
- `node_status != Up` for any node, sustained > 2 minutes
- `ep_oom_errors > 0` on any bucket (writes failing)
- `disk_used_percent > 90` on any node
- `autofailover_count` increased in the last 5 minutes
- `rebalance_running == true` for > 4 hours (likely stuck)

**Warning (notify on-call channel):**
- `cache_miss_ratio > 10%` sustained 10+ minutes
- `disk_used_percent > 80` on any node
- XDCR `changes_left` growing over 30+ minutes
- `n1ql_errors / n1ql_requests > 1%` sustained 5+ minutes
- Any Eventing function with `failure_count / success_count > 5%`
- Any index in `errored` or `paused` state

**Informational (log only):**
- Slow query count increasing
- Index size growing (capacity planning)
- Per-bucket op rate trending up (capacity planning)

## Logs

`admin_logs_get` returns the cluster manager's recent log entries. Useful when stats show a symptom and you need to know what happened.

For long-term log retention, ship Couchbase logs to your central log aggregation:
- File location: `/opt/couchbase/var/lib/couchbase/logs/` (self-managed)
- Capella: log access via the Capella UI; programmatic access requires support tickets currently

Audit logs (when enabled via `admin_audit_set`) are separate and go to their own file. Ship these to a security log aggregator with appropriate access controls.

## System events vs logs

The two surfaces overlap but differ:

- **`admin_logs_get`**: error and warning messages from the cluster manager. Free-text, intended for human reading
- **`admin_system_events`**: structured event log of state changes (failovers, config updates, user actions). Intended for machine consumption

For "what's broken right now" → logs. For "what changed in the cluster yesterday" → system events.

## Per-collection observability (8.x)

Couchbase 8.x exposes per-collection stats — useful when one collection's behavior matters separately from the rest of the bucket:

```
admin_stats_bucket with scope_name and collection_name args returns
per-collection metrics: item count, ops/sec, data size
```

For multi-tenant deployments using scope-per-tenant, this lets you see per-tenant load without exposing per-tenant queries.

## What to put on a dashboard

A useful 6-panel dashboard:

1. **Cluster health** — node count + status, current alerts, autofailover history
2. **Throughput** — KV ops/sec + N1QL queries/sec + FTS searches/sec, stacked
3. **Latency** — KV p99 + N1QL p99 + FTS p99 (separate lines)
4. **Memory** — per-bucket memory used vs quota; cache miss ratio
5. **Disk** — per-node disk fill %; disk write queue depth
6. **XDCR** — per-replication lag (changes_left); replication throughput

Build this once and it'll answer 80% of "is the cluster OK" questions at a glance.

## Quick decision tree

- **"Is the cluster healthy?"** → `admin_stats_overview` + check for any node not Up
- **"Why is a query slow?"** → `cb_explain_query` first; if pattern, `cb_perf_slowest_queries` from the diagnostics reference
- **"Why is the cluster slow generally?"** → `admin_stats_overview`, look for cache miss ratio, disk queue, OOM errors
- **"What changed recently?"** → `admin_system_events` for state changes; `admin_logs_get` for error context
- **"Setting up external monitoring"** → `admin_prometheus` endpoint; scrape from existing Prometheus
- **"Per-function eventing health"** → `admin_stats_eventing`, look at failure ratio and DCP backlog
- **"XDCR keeping up?"** → `admin_stats_xdcr`, watch `changes_left` and `data_replicated_age`
