# Error handling — retries, timeouts, transient vs durable

The SDK handles a lot of retry logic for you. The hard part is recognizing what's left for your code to handle, which errors are transient vs durable, and how to set timeouts that match your application's SLA.

## The two categories of errors

**Transient errors** — the SDK retries them automatically, within the operation's timeout budget:
- `TemporaryFailureException` — the server is overloaded; back off and retry
- `RequestCanceledException` (in some scenarios) — request canceled mid-flight, may have succeeded or not
- Network blips — TCP-level disconnects
- Node failovers — the routing target failed, the SDK retries against another node

**Durable errors** — your code must handle them:
- `DocumentNotFoundException` — the doc doesn't exist (your business logic must decide what to do)
- `DocumentExistsException` — INSERT failed because doc already exists
- `CasMismatchException` — optimistic-concurrency conflict (you read with CAS X, doc was updated by someone else, write with CAS X failed)
- `AuthenticationException` — credentials wrong
- `BucketNotFoundException` / `CollectionNotFoundException` — config error
- `IndexNotFoundException` — query references an index that doesn't exist
- `TimeoutException` — operation didn't complete within budget (could be transient root cause; your code decides whether to retry)

## SDK-level vs application-level retries

The SDK retries transient errors automatically. **Don't add application-level retries on top.** This double-retries: SDK already tries N times within the timeout, your wrapper tries M times on top, total tries = N×M with M×timeout total latency.

**When application-level retries ARE appropriate:**

1. **Idempotent operations across timeout boundaries.** If the SDK times out, you don't know if the write succeeded. For idempotent operations (upsert), retrying is safe. For non-idempotent (incrementing a counter), retrying may double-count
2. **CAS mismatches in optimistic-concurrency loops.** Read, modify in memory, write with CAS; on mismatch, re-read and try again. The retry loop is YOUR responsibility, not the SDK's
3. **Circuit-breaker-style backoff for an entire cluster outage.** SDK retries individual operations; your circuit breaker decides "stop hitting the cluster for 30 seconds" if everything is failing

## Setting timeouts

Timeout defaults vary by operation type:

| Operation type | Default timeout | When to override |
|---|---|---|
| KV (get/upsert/etc.) | 2.5 seconds | Lower (e.g., 500ms) for latency-critical paths; higher for warmup scenarios |
| Query (N1QL) | 75 seconds | Set per-query based on expected runtime |
| Analytics | 75 seconds | Set per-query; analytics often takes longer |
| Search (FTS) | 75 seconds | Per-query |
| Management ops | varies, often 75s | Bumps for slow management ops |

**Setting at the cluster level** (default for all ops):

```python
options = ClusterOptions(
    authenticator=auth,
    timeout_options=TimeoutOptions(
        kv_timeout=timedelta(seconds=1),
        query_timeout=timedelta(seconds=30)
    )
)
```

**Setting at the operation level** (overrides cluster default):

```python
result = collection.get("user::42", GetOptions(timeout=timedelta(milliseconds=500)))
```

**Rule of thumb:** set the operation timeout to be roughly the slowest-acceptable response from that operation. Setting it equal to your overall request SLA is fine for KV in a request-response handler; for parallel ops, divide proportionally.

## Timeout vs durability tradeoff

Higher durability levels (waiting for replication/persistence) increase op latency. If you set durability `Majority` AND timeout 500ms AND replicas are catching up after a node failover, your writes may time out.

**Recommendation:** when using high durability, set a slightly more generous timeout (e.g., 2-3 seconds instead of 500ms). The SDK's default 2.5s assumes Majority durability.

## Retry patterns by use case

### Pattern: idempotent write with retry

```python
def upsert_with_retry(coll, key, value, max_attempts=3):
    for attempt in range(max_attempts):
        try:
            return coll.upsert(key, value, UpsertOptions(timeout=timedelta(seconds=2)))
        except (TimeoutException, TemporaryFailureException) as e:
            if attempt + 1 == max_attempts:
                raise
            time.sleep(0.1 * (2 ** attempt))  # exponential backoff
```

**Use when:** the operation is idempotent (upsert, delete-if-exists). Safe to retry on transient errors after the SDK has already retried within timeout.

### Pattern: CAS-based optimistic concurrency

```python
def increment_counter_safely(coll, key, max_attempts=5):
    for attempt in range(max_attempts):
        try:
            result = coll.get(key)
            new_value = result.content_as[dict]
            new_value["count"] += 1
            coll.replace(key, new_value, ReplaceOptions(cas=result.cas))
            return new_value["count"]
        except CasMismatchException:
            continue  # someone else updated; retry
    raise Exception("Couldn't acquire CAS lock after max attempts")
```

**Use when:** atomic read-modify-write on a single document. For high contention, see `cb_mutate_in` with the `increment` op as an alternative — it's atomic without CAS loops.

### Pattern: circuit breaker

For when an entire cluster is unreachable:

```python
class CouchbaseCircuitBreaker:
    def __init__(self, failure_threshold=10, reset_timeout=30):
        self.failures = 0
        self.opened_at = None
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout

    def call(self, fn, *args, **kwargs):
        if self.opened_at and time.time() - self.opened_at < self.reset_timeout:
            raise CircuitOpenError("Circuit is open")
        try:
            result = fn(*args, **kwargs)
            self.failures = 0
            self.opened_at = None
            return result
        except (TimeoutException, RequestCanceledException) as e:
            self.failures += 1
            if self.failures >= self.failure_threshold:
                self.opened_at = time.time()
            raise
```

**Use when:** the cost of waiting on timeouts during a full cluster outage is hurting your service. The circuit breaker fails fast after a threshold of consecutive failures, then probes to see if the cluster recovered.

## What an `RequestCanceledException` actually means

This is the most confusing Couchbase error. It means: the SDK gave up on this specific request before getting a response. Two scenarios:

1. **Timeout exceeded** — the operation took longer than the budget
2. **SDK shutdown / cluster recovery interrupted the request** — happens during topology changes

For both: **the write may or may not have succeeded on the server.** The SDK doesn't know. Your code must:
- For idempotent ops (upsert, delete): retry is safe
- For non-idempotent ops (insert, counter increment): you have a recoverability problem — either accept it, design the operation idempotently, or use transactions

## Specific exceptions and what to do

| Exception | What it means | Action |
|---|---|---|
| `DocumentNotFoundException` | Doc doesn't exist | Business logic decides — 404? Create? |
| `DocumentExistsException` | INSERT failed | Either expected (idempotent insert workflow) or a race condition |
| `CasMismatchException` | Optimistic concurrency conflict | Re-read, retry the modification |
| `DurabilityImpossibleException` | Requested durability can't be met (e.g., not enough replicas) | Lower durability or fix the cluster |
| `BucketNotFoundException` | Config error | Fix the bucket name in your config |
| `AuthenticationException` | Credentials wrong | Fix the password/cert |
| `TemporaryFailureException` | Server overloaded | SDK retries; if it surfaces to you, the cluster is genuinely stressed |
| `RequestCanceledException` | Request gave up before response | Idempotent → retry; non-idempotent → unknown state |
| `TimeoutException` | Operation didn't complete in budget | Same handling as RequestCanceledException, but often indicates the budget itself was too short |

## Logging and metrics

Recommended client-side instrumentation:

- Log every error with: operation name, key/query, timeout, exception class, traceback
- Metric: error rate by exception type (separate counters for transient vs durable)
- Metric: operation latency p50/p95/p99 by operation type
- Trace span per Couchbase operation (OpenTelemetry support is built into modern SDKs)

The SDKs emit telemetry; configure your APM (Datadog, New Relic, etc.) to capture it.

## Quick decision tree

- **Error from the SDK?** First check: is it transient or durable? (Transient → SDK has already retried; usually means cluster is stressed)
- **Setting a timeout?** Match it to the operation's expected latency + headroom; don't make it the same as your overall request SLA without thought
- **Need to retry across timeouts?** Only for idempotent operations; otherwise the retry is double-spending
- **Optimistic concurrency on one doc?** CAS loop with `replace` — see pattern above
- **Atomic counter / increment?** Use `cb_mutate_in` with `increment` op, not a CAS loop
- **Cluster intermittently unavailable?** Circuit breaker on top of the SDK
- **Got `RequestCanceledException`?** Idempotent op → retry; non-idempotent → accept unknown state or redesign with transactions
