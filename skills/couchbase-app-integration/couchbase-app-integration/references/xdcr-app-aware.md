# XDCR-aware application patterns

Cross-Datacenter Replication runs at the server level (configured via the `admin_xdcr_*` MCP tools), but its existence shapes how your application code should handle writes, conflicts, and reads. This reference covers the patterns your client code needs when XDCR is in play.

## The two XDCR shapes

**Active-passive:** writes go to one source cluster; replication flows one-way to one or more target clusters. Targets are read-only from the application's perspective.

**Active-active:** writes can go to either cluster; replication flows bidirectionally. Same document can be written in both clusters; conflict resolution decides which version wins.

The application code differs significantly between these two shapes.

## Active-passive patterns

The simple case. Your application has:

- A write cluster (source)
- One or more read clusters (replicas, in other regions)

### Pattern: regional reads, central writes

```python
class CouchbaseService:
    def __init__(self):
        self.write_cluster = Cluster("couchbases://write.example.com", ...)
        self.read_cluster = Cluster(f"couchbases://read-{my_region}.example.com", ...)

    def get_user(self, user_id):
        # Read from local cluster — fast
        return self.read_cluster.bucket("users").collection("users").get(f"user::{user_id}")

    def update_user(self, user_id, data):
        # Write to central cluster — replicated to local
        return self.write_cluster.bucket("users").collection("users").upsert(f"user::{user_id}", data)
```

**Tradeoff:** writes have higher latency (cross-region to write cluster). Reads are local. The right answer when read-heavy.

### Pattern: read-your-own-writes across regions

The challenge with the previous pattern: after writing to the write cluster, the local read cluster hasn't received the replication yet. Reading immediately may return the old value.

Three approaches:

**A. Read from write cluster for known-recent reads:**

```python
def update_and_get(self, user_id, data):
    self.write_cluster... .upsert(...)
    # Read back from write cluster so we see our own write
    return self.write_cluster... .get(...)
```

Simple but pays write-cluster latency for the read.

**B. Cache the write locally:**

```python
def update_user(self, user_id, data):
    self.write_cluster... .upsert(...)
    self.local_cache[user_id] = data

def get_user(self, user_id):
    if user_id in self.local_cache:
        return self.local_cache.pop(user_id)
    return self.read_cluster... .get(...)
```

Avoids the cross-region latency. Cache must be sized for write rate × replication lag.

**C. Use XDCR lag estimate and wait:**

```python
def update_and_get(self, user_id, data):
    self.write_cluster... .upsert(...)
    time.sleep(estimated_xdcr_lag_seconds)
    return self.read_cluster... .get(...)
```

Janky. Don't do this except for dev / debugging.

### Pattern: failover to alternate cluster

If your local read cluster becomes unreachable, fall back to another region:

```python
def get_user(self, user_id):
    try:
        return self.local_cluster... .get(f"user::{user_id}",
                                          GetOptions(timeout=timedelta(milliseconds=500)))
    except (TimeoutException, NetworkException):
        return self.fallback_cluster... .get(f"user::{user_id}")
```

The fallback adds latency but keeps you alive during regional outages.

## Active-active patterns

The harder case. Both clusters accept writes; conflicts are inevitable when the same document is updated in both within the replication window.

### Conflict resolution at the server

XDCR has built-in conflict resolution. By default, Couchbase uses "latest CAS wins" — the document with the higher CAS value survives. This means:
- If cluster A writes at time T1 and cluster B writes the same doc at time T2 > T1, B's version wins
- If A and B write at "the same time" (within the same CAS resolution), the winner is determined by deterministic tiebreaker

For most workloads, latest-wins is acceptable. But it means writes can be silently lost when conflicts occur.

### Application-side patterns for active-active

**Pattern: design for last-write-wins**

If your data semantics work with "latest wins":
- User profile updates (each update fully replaces — latest is correct)
- Settings / preferences
- Cache entries

No application-side code needed. The cluster's default resolution does the right thing.

**Pattern: idempotent operations with versioning**

For data where "merge" matters more than "overwrite":

```json
{
  "id": "user::42",
  "_v": 7,                      // version, incremented per logical update
  "_updated_regions": ["us", "eu"],  // regions that touched this version
  "data": {...}
}
```

Application code:
1. Read the doc with CAS
2. Check the version — if a newer version exists in your region, use it
3. Compose a merge — combine fields from both versions according to merge rules
4. Write back with incremented version

This is application-level conflict resolution. Heavier but lets you avoid losses.

**Pattern: append-only event sourcing**

Instead of mutating documents, append events:

```
event::user_42::01HXK7M8YQNT9N5J2VCABCDE  { type: "name_change", value: "Alice", ts: "..." }
event::user_42::01HXK7M8YQNT9N5J2WCFGHIJK  { type: "email_change", value: "alice@new", ts: "..." }
```

Both clusters can write events independently — no conflict possible because the keys are unique (ULID).
Read-side computes current state by replaying events.

Application code is more complex but conflicts go away entirely.

**Pattern: per-region key prefixes**

Each region writes to its own key namespace; aggregation happens at read time:

```
user::42::region:us    { fields written from US cluster }
user::42::region:eu    { fields written from EU cluster }
```

Writes never conflict. Reads fetch both regional docs and merge.

Use when fields are clearly region-owned (e.g., user's US-shipping-address vs EU-shipping-address).

### Mutation tokens for read-your-own-writes

Couchbase SDKs return a `mutation_token` from writes. You can pass this token to subsequent queries to ensure they see your write:

```python
result = collection.upsert("user::42", data)
token = result.mutation_token

# Query that's guaranteed to see this write
query_result = cluster.query("SELECT * FROM users WHERE tier = $1",
                              QueryOptions(
                                  positional_parameters=["gold"],
                                  consistent_with=MutationState.from_tokens(token)
                              ))
```

This is the same idea as `RequestPlus` but more precise — it waits only for THIS write to be indexed, not "everything pending."

In XDCR context: the mutation token tells you "your write reached this cluster," but it doesn't tell you about other clusters. For cross-cluster read-your-own-writes, you still need one of the patterns above.

## Conflict logging (Couchbase 8.x)

When XDCR resolves a conflict against your write, the losing version can be persisted to a conflict log bucket. From the application side:

- Application code typically doesn't read the conflict log directly — it's an audit / debugging surface
- Read via `admin_xdcr_conflict_log_query` (couchbase-mcp skill)
- Useful for understanding the magnitude of conflicts in production

If your application is hitting many conflicts (visible in the log), reconsider whether active-active is the right shape. Active-passive may give you what you actually want with much less complexity.

## Idempotency keys

For active-active or any retried workflow, idempotency keys are essential:

```python
def create_order(user_id, items, idempotency_key):
    # Check if this idempotency key was already used
    try:
        existing = collection.get(f"idemp::{idempotency_key}")
        return existing.content_as[dict]["order_id"]
    except DocumentNotFoundException:
        pass

    order_id = generate_order_id()
    collection.insert(f"order::{order_id}", order_data)
    collection.insert(f"idemp::{idempotency_key}",
                       {"order_id": order_id},
                       InsertOptions(expiry=timedelta(days=30)))
    return order_id
```

The idempotency document acts as a guard against double-creation when the client retries or replicates.

## When NOT to use active-active

The honest answer: active-active is hard, and you should avoid it unless you have a specific reason:

**Avoid active-active when:**
- The data is naturally regional (US users access US data, EU users access EU data) — partition the data instead
- Reads-from-anywhere is the goal — active-passive with read replicas gives you this with less complexity
- Conflicts would be expensive — financial systems, inventory, counters

**Use active-active when:**
- Users actually travel between regions and write from wherever they are
- The data is genuinely shared globally and writes can come from anywhere
- You've accepted the conflict-resolution model (and verified it's correct for your data)
- You've measured the conflict rate and it's low enough to tolerate

## Reading replicated data — what to expect

Even in active-passive, the target cluster's view of a write lags behind the source. Application code reading from the target should:

- Tolerate "the data isn't there yet" for short windows (seconds typically)
- Not assume that two writes in the source appear in the target in the same order (XDCR doesn't strictly preserve order across documents)
- Handle the case where a delete on the source hasn't reached the target yet

## Monitoring application-relevant XDCR metrics

Your app should be aware of XDCR health, even if it doesn't manage XDCR directly:

- **`changes_left`** (from `admin_stats_xdcr`) — pending replication; growing trend = problem
- **`data_replicated_age`** — how stale the target is; alert if > expected lag
- **Conflict log entries** (8.x) — if you're using active-active, watch the conflict rate

Wire these into your application's observability so you can correlate "users seeing stale data" with "XDCR is behind."

## Quick decision tree

- **Single-region writes + multi-region reads?** → Active-passive, read locally, write to central; cache local-writes briefly if needed
- **Need writes-from-anywhere?** → Active-active, but pick a conflict-resolution model first
- **Data is naturally regional?** → Partition by region; don't do active-active
- **Need atomicity across clusters?** → You don't get it. Design around it (eventual consistency, idempotency)
- **Read-your-own-writes within one cluster?** → Mutation token + `consistent_with` on the query
- **Read-your-own-writes across clusters?** → Read from the cluster you wrote to, or cache locally
- **Conflicts hurting you?** → Reconsider whether active-active is the right shape; maybe active-passive + region partitioning is correct
