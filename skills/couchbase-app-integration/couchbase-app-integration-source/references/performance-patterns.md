# Performance patterns

How to write client code that pushes throughput, minimizes latency, and uses the SDK's primitives well. The biggest wins come from a few patterns; everything else is incremental.

## The top 3 wins

1. **Async over sync** for any high-concurrency workload — frees the calling thread to do other work while waiting on cluster I/O
2. **Bulk ops over loops** — `cb_get_multi` is 100x faster than 100 individual `cb_get` calls
3. **Subdocument ops over full-doc reads/writes** — `cb_lookup_in` and `cb_mutate_in` move only the fields you need

If you do nothing else, do these three. Most performance complaints trace back to violating one of them.

## Async patterns

### When async wins

- Web servers handling many concurrent requests — each request does a few KV ops; threading per request wastes resources
- Pipelines that fan out many independent reads/writes
- Background workers processing parallel streams of data

### When async is overhead

- Batch scripts doing sequential work — sync is simpler and equivalent in throughput
- CLI tools — startup cost of an async runtime isn't worth it
- Simple ETL with no parallelism

### Async example — Python asyncio

```python
import asyncio
from acouchbase.cluster import AsyncCluster

async def fetch_user_with_orders(cluster, user_id):
    bucket = cluster.bucket("app_data")
    users = bucket.scope("_default").collection("users")
    orders = bucket.scope("_default").collection("orders")

    # Fetch user and their orders in parallel
    user_task = asyncio.create_task(users.get(f"user::{user_id}"))
    orders_task = asyncio.create_task(
        cluster.query(f"SELECT * FROM orders WHERE user_id = {user_id}")
    )

    user_result = await user_task
    orders_result = await orders_task

    return {
        "user": user_result.content_as[dict],
        "orders": [row async for row in orders_result.rows()]
    }
```

The two operations run concurrently; total latency = max(user_latency, orders_latency), not sum.

### Async example — Java reactive

```java
Mono<JsonObject> userMono = collection.reactive().get("user::" + userId)
    .map(result -> result.contentAsObject());

Flux<JsonObject> ordersFlux = cluster.reactive()
    .query("SELECT * FROM orders WHERE user_id = $1",
           QueryOptions.queryOptions().parameters(JsonArray.from(userId)))
    .flatMapMany(ReactiveQueryResult::rowsAsObject);

return Mono.zip(userMono, ordersFlux.collectList())
    .map(tuple -> /* combine */);
```

Same pattern — two operations run concurrently via Reactor.

## Bulk operations

### KV multi-get

```python
# Slow — sequential
for user_id in user_ids:
    user = collection.get(f"user::{user_id}")

# Fast — bulk
results = collection.get_multi([f"user::{uid}" for uid in user_ids])
```

`get_multi` (and the equivalents in other SDKs) pipelines requests over a single connection, reducing per-op overhead. 100x speedup is typical.

For SDKs that don't have a native multi-get (Go, for example): use async pattern with `gather` / `WaitGroup` to fire all the gets concurrently.

### Bulk insert / upsert

```python
# Slow — sequential
for doc in documents:
    collection.upsert(doc["id"], doc)

# Fast — concurrent
import asyncio
async def bulk_upsert(collection, documents, concurrency=50):
    semaphore = asyncio.Semaphore(concurrency)
    async def upsert_one(doc):
        async with semaphore:
            await collection.upsert(doc["id"], doc)
    await asyncio.gather(*[upsert_one(d) for d in documents])
```

The semaphore caps parallelism so you don't overwhelm the cluster. Typical concurrency: 50-200 for moderate clusters.

For very large loads (millions of docs), use the dedicated `cbimport` tool rather than client code — it handles batching, retries, and progress reporting.

### Bulk patterns for queries

Queries can't be "bulked" — each query is its own request. But:

- Use parameterized queries so the cluster can cache the plan
- Use scoped queries (`bucket.scope.collection`) for better routing
- Avoid `SELECT *` if you only need a few fields

```python
# Cached plan — fast on repeated calls
stmt = "SELECT name, email FROM users WHERE tier = $1"
for tier in tiers:
    result = cluster.query(stmt, QueryOptions(positional_parameters=[tier]))
```

## Subdocument ops — the underused win

When you only need one or two fields of a large document, `cb_lookup_in` and `cb_mutate_in` (and their SDK equivalents) move only those fields over the wire.

```python
# Slow — fetches full document just to read 'email'
user = collection.get("user::42").content_as[dict]
email = user["email"]

# Fast — fetches only the email field
result = collection.lookup_in("user::42", [SD.get("email")])
email = result.content_as[str](0)
```

For documents > 10 KB or for high-throughput paths, the difference is meaningful.

`mutate_in` for updates is similarly valuable — modifying one field of a 100 KB doc without `mutate_in` means reading + rewriting all 100 KB.

```python
# Slow
user = collection.get("user::42").content_as[dict]
user["last_login"] = now
collection.replace("user::42", user)  # rewrites whole doc

# Fast
collection.mutate_in("user::42", [SD.upsert("last_login", now)])
```

## Connection settings for throughput

By default, the SDK uses a single KV connection per node. For very high-throughput workloads (10K+ ops/sec), bump this:

```python
options = ClusterOptions(
    authenticator=auth,
    timeout_options=TimeoutOptions(kv_timeout=timedelta(seconds=2))
)
# Adjust per-SDK; this is illustrative
```

Java example:

```java
Cluster cluster = Cluster.connect(connStr,
    ClusterOptions.clusterOptions(auth)
        .ioConfig(IoConfig.numKvConnections(4)));
```

Only tune if you've profiled and seen connection contention. Most apps don't need this.

## Latency optimization

For latency-critical paths (request handlers needing sub-10ms p99):

1. **KV reads only** — queries have higher overhead than KV
2. **`get` on active node only** — don't use `getAllReplicas`
3. **Subdocument ops** if only specific fields needed
4. **Cluster.wait_until_ready at startup** so the first request doesn't pay setup cost
5. **Lower operation timeouts** so the SDK doesn't spend long retrying — fail fast and let the request handler decide what to do

## Throughput optimization

For batch/ingest paths needing high total ops/sec:

1. **Async + parallelism** — many concurrent ops
2. **Bulk ops** where available
3. **No durability** if data loss is acceptable
4. **Reuse connections** — one Cluster for the entire batch job
5. **Batch sized to memory** — async with no limit can run out of memory; semaphore-cap to a reasonable parallelism

For multi-million document ingestion, also consider:
- `cbimport` for one-shot loads (better than client code)
- Eventing functions for transform-during-write
- Multi-node ingestion (each worker writes to its assigned partition)

## Caching considerations

Couchbase is fast enough that adding a cache layer in front of it (Redis, application memory) is often unnecessary. Before adding a cache, profile:

- Couchbase KV reads at ~1ms median, scaling linearly with cluster
- Application-memory cache at ~10μs
- The difference is meaningful only if 1ms is actually a bottleneck

When caching DOES make sense:
- Cross-request shared data accessed many times per request — cache in-memory per worker
- Heavy aggregation results — cache the aggregated form, not raw data
- Capella egress costs are a concern — cache to reduce queries

Often the right answer is: just hit Couchbase. The simplicity wins.

## Profiling

When something is slow:

1. **Use SDK tracing** — modern SDKs emit OpenTelemetry spans. Configure your APM to capture them
2. **Check the cluster** — use `cb_perf_*` tools (couchbase-mcp skill) to see if slow queries are happening
3. **Time things** — put timing around the suspected slow op, log p50/p95/p99
4. **`cb_explain_query`** — for queries that are slow, get the plan

Don't optimize without measurement. The intuitions about "this is probably slow" are often wrong.

## Anti-patterns

- **N+1 query pattern** — fetching a list of IDs, then KV-getting each one in a loop. Use `get_multi` instead
- **Creating Cluster per request** — see `connection-management.md`
- **Full document reads when subdoc would do** — wastes bandwidth and memory
- **Sync ops in async handlers** — blocks the event loop, kills throughput
- **No connection reuse** — every request paying connection-setup cost
- **Optimistic concurrency loops without backoff** — under contention, busy-loop hammers the cluster

## Quick decision tree

- **High concurrency / web handler?** → async SDK + per-op timeouts + connection pooling
- **Batch / ETL?** → sync SDK or async with bounded parallelism (semaphore)
- **Reading many docs by ID?** → `get_multi`
- **Reading specific fields of a doc?** → `lookup_in`
- **Updating specific fields of a doc?** → `mutate_in`
- **Counter increment under contention?** → `mutate_in` with `increment` op, not CAS loop
- **Throughput too low?** → async, bulk, parallelism. In that order
- **Latency too high?** → KV only (not queries), no replicas, lower timeouts
- **Adding cache layer?** → profile first; Couchbase is often fast enough that a cache adds complexity without value
