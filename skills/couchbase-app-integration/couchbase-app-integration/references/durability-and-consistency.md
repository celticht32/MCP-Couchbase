# Durability and consistency

The two knobs that trade off speed against guarantees. Picking them right is per-operation; the wrong default for both wastes throughput, the wrong default for either creates correctness bugs.

## Write durability levels

Couchbase writes have four durability levels. They differ in how many nodes/replicas have committed the write before the SDK returns success.

| Level | Acknowledged after | Survives | Latency cost |
|---|---|---|---|
| `None` (default in some SDKs) | Active node's memory | Nothing — even active node restart | ~1ms (fastest) |
| `Majority` | Replicated in memory to majority of replicas | A node failure | ~3-5ms |
| `MajorityAndPersistActive` | Majority in memory + persisted to disk on active | Cluster restart with active surviving | ~5-15ms |
| `PersistToMajority` | Persisted to disk on majority of replicas | Cluster restart, multiple failures | ~10-50ms |

The "majority of replicas" calculation: with replica_count=1 there are 2 copies total (active + 1 replica); majority means both. With replica_count=2 there are 3 copies; majority means 2 (active + 1 replica).

### Picking durability — the question to ask

**"What happens if this write is lost?"**

| Loss tolerance | Use |
|---|---|
| Total loss is fine (cache, session, ephemeral state) | `None` |
| Single-node failure shouldn't lose it | `Majority` |
| Cluster restart shouldn't lose it (with active surviving) | `MajorityAndPersistActive` |
| Multi-failure shouldn't lose it (financial, audit, compliance) | `PersistToMajority` |

### Per-operation durability

You pick durability per write, not per app:

```python
# Cache update — low durability OK
collection.upsert("cache::user_42", data,
                  UpsertOptions(durability=DurabilityLevel.NONE))

# Financial write — strong durability
collection.insert("payment::abc123", payment_data,
                  InsertOptions(durability=DurabilityLevel.PERSIST_TO_MAJORITY))

# Normal user data — Majority is the right default for most apps
collection.upsert("user::42", user_data,
                  UpsertOptions(durability=DurabilityLevel.MAJORITY))
```

### Default — what to use when in doubt

**Use `Majority` as your default.** It's a meaningful guarantee (survives single-node failure), it's fast enough for most workloads, and it's the most-commonly-correct choice.

`None` is appropriate only for genuinely-disposable data. `PersistToMajority` is for genuinely-irreplaceable data. Most things are in between → `Majority`.

### What about replica reads?

Couchbase supports reading from replicas (not just active) via `getAllReplicas` / `getAnyReplica`. Replica reads:
- Return stale data if the replica hasn't caught up
- Are useful for "best effort, must respond quickly" scenarios (e.g., during a failover)
- Are NOT useful for normal read patterns — read from active for current data

Skip this unless you have a specific reason to consider replicas.

## Query consistency levels

Queries (N1QL / SQL++) hit indexes, which are eventually consistent with KV writes. Three scan consistency levels:

| Level | What it does | Latency cost |
|---|---|---|
| `NotBounded` (default) | Don't wait — return whatever's currently in the index | Fastest |
| `RequestPlus` | Wait until the index has caught up to the current sequence number | Slower — may wait seconds during heavy writes |
| `AtPlus` | Wait until the index has caught up to a specific sequence number (advanced) | Slowest, most precise |

### When each is correct

**`NotBounded`** — appropriate for:
- Dashboards / reports where slight staleness is fine
- High-throughput read paths where ~100ms of staleness doesn't matter
- Most analytical / aggregation queries

**`RequestPlus`** — appropriate for:
- Read-your-own-writes patterns (user updates a record, then immediately re-queries)
- Workflows that depend on the current state being indexed (e.g., "after creating this, find all related records")
- Reconciliation logic

**`AtPlus`** — appropriate for:
- Distributed transactions where you've captured the mutation token from a write and need to wait for the index to catch up to that exact point
- Rare; usually `RequestPlus` is sufficient

### Per-query consistency

```python
# Dashboard query — don't care about freshness
result = cluster.query("SELECT count(*) FROM orders",
                       QueryOptions(scan_consistency=QueryScanConsistency.NOT_BOUNDED))

# Read-your-own-writes after an insert
collection.insert("order::ORD-00837", order)
result = cluster.query("SELECT * FROM orders WHERE customer_id = 42",
                       QueryOptions(scan_consistency=QueryScanConsistency.REQUEST_PLUS))
```

### Default — what to use when in doubt

**Use `NotBounded` as default; opt into `RequestPlus` for specific cases.** Most application reads can tolerate < 100ms of staleness, and `NotBounded` is much faster under load.

The trap: defaulting to `RequestPlus` for everything. This makes queries wait on index catchup, which under heavy write load can mean multi-second waits — destroying throughput.

## Combining durability + consistency in workflows

### Pattern: write, then read your own write

```python
# Write with Majority so it's replicated
result = collection.upsert("user::42", user_data,
                            UpsertOptions(durability=DurabilityLevel.MAJORITY))

# Read with RequestPlus to ensure index sees the write
query_result = cluster.query("SELECT * FROM users WHERE tier = 'gold'",
                              QueryOptions(scan_consistency=QueryScanConsistency.REQUEST_PLUS))
```

Without RequestPlus, the query may return results from before the upsert.

### Pattern: high-throughput ingestion + analytical reads

```python
# Bulk ingest with no durability — speed matters, can re-ingest on loss
for doc in batch:
    collection.upsert(doc["id"], doc,
                       UpsertOptions(durability=DurabilityLevel.NONE))

# Analytics queries with NotBounded — slight staleness fine
result = cluster.analytics_query("SELECT count(*) FROM events GROUP BY type",
                                  AnalyticsOptions(scan_consistency=AnalyticsScanConsistency.NOT_BOUNDED))
```

Both choices favor throughput; appropriate when neither write durability nor read freshness is critical.

### Pattern: financial / audit writes

```python
# PersistToMajority + insert (not upsert) for unique-key safety
collection.insert(f"payment::{payment_id}", payment_data,
                   InsertOptions(durability=DurabilityLevel.PERSIST_TO_MAJORITY))
```

Pair with idempotency at the application level: use a unique payment ID generated client-side so retries don't create duplicates.

## DurabilityImpossibleException

If you request `Majority` on a cluster that doesn't have enough healthy replicas (e.g., during a failover with replica_count=1), the SDK raises `DurabilityImpossibleException`.

Options:
- **Catch and downgrade:** retry with `None` and accept the reduced guarantee
- **Catch and surface:** tell the user the write couldn't be made durable; the cluster is in a degraded state
- **Catch and queue for later:** retry when the cluster reports healthy again

Production apps typically need a deliberate policy here — don't just let the exception propagate as a 500 error.

## When to skip both

For ephemeral cache-style writes where neither durability nor consistency matters at all:

```python
collection.upsert(key, value,
                  UpsertOptions(durability=DurabilityLevel.NONE,
                                timeout=timedelta(milliseconds=100)))
```

This is the fastest possible write. Pair with the Ephemeral bucket type for the corresponding fast read path.

## Quick decision tree

- **Default for writes?** `Majority` — meaningful guarantee, manageable latency
- **Cache / session / ephemeral?** `None`
- **Financial / audit / compliance?** `PersistToMajority`
- **Default for reads (queries)?** `NotBounded` — much faster under load
- **Read-your-own-writes?** `RequestPlus` on the query
- **Cluster degraded, durability impossible?** Catch and decide: downgrade, surface, or queue
- **High-throughput bulk ingest?** `None` + bulk ops; if loss matters, design idempotent ingestion
