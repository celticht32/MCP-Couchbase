# Workload shapes — sizing by access pattern

Different workload shapes have different sizing characteristics. The same total data size can need very different cluster shapes depending on whether it's read-heavy, write-heavy, vector-search-driven, or time-series-shaped. This reference walks through the common workload shapes and the sizing characteristics of each.

## Read-heavy (>90% reads)

Examples: content delivery, catalog browsing, user profile lookups.

**Characteristics:**
- Working set can be relatively small if cold tail is large
- KV reads dominate; very latency-sensitive
- Indexes are read but rarely written
- Replicas help with throughput (each replica can serve reads)

**Sizing priorities:**
1. **RAM** — fit the working set comfortably
2. **Network egress** — many small reads = high response bandwidth
3. **CPU for query** if there's a query-heavy component (e.g., search-style reads)
4. **Replicas at 2** to enable load distribution across more nodes

**Service mix:**
- 3-5 data nodes for low-latency KV
- 2 query/index nodes if query is meaningful
- Eventing usually not needed

**Common mistake:** over-sizing for storage when most of it is cold. Use working set fraction of 20-40%, not 100%.

## Write-heavy (>50% writes)

Examples: event ingestion, IoT telemetry, audit logs.

**Characteristics:**
- High disk write throughput
- Replicas amplify write cost
- Indexes are expensive (every write updates every index)
- Compaction runs constantly

**Sizing priorities:**
1. **Disk IOPS** — provision aggressively (5000+ per node)
2. **CPU for compaction** — keeps up with write rate
3. **Network for replication** — replica count × write rate
4. **Fewer indexes** — each one adds write amplification

**Service mix:**
- 5+ data nodes spread the write load
- Index nodes separate from data (so index updates don't compete with KV writes)
- Eventing if you need to react to writes

**Common mistake:** treating it like a read-heavy workload. Write-heavy clusters need fewer-but-leaner indexes, more nodes for write parallelism, and aggressive disk IOPS.

## Mixed transactional (40-60% reads/writes)

Examples: e-commerce, SaaS apps, social platforms.

**Characteristics:**
- Most common shape
- Indexes get both heavy reads (queries) and heavy updates (writes)
- Working set is moderate (active users + hot data)

**Sizing priorities:**
- Balanced across RAM, disk, CPU
- More indexes than write-heavy, fewer than read-heavy
- Service separation (data vs query/index) helps with isolation

**Service mix:**
- Pattern B from `nodes.md`: data nodes + query/index nodes
- 3 data + 2 query/index is a typical starter shape

## Burst-prone (Black Friday, viral events)

Examples: e-commerce sale, viral content, sports event traffic.

**Characteristics:**
- 3-10x normal load for hours or days, then back to baseline
- Cluster can't be scaled in real time (rebalances take too long)
- Need to pre-provision for peak

**Sizing priorities:**
1. **Size for peak, not average** — and add 20% headroom on top
2. **CPU and network are usually the binding constraints** (everything else, you can paper over with RAM)
3. **Consider read replicas** to scale reads horizontally
4. **Cache layer in front** to absorb the burst

**Pre-burst checklist:**
- Validate the cluster handles peak via load test
- Confirm autofailover settings (`admin_autofailover_get`) won't trigger spuriously under load
- Have a rollback plan if something goes wrong

**Common mistake:** sizing for average. The cluster runs fine for 51 weeks, then collapses on the one week that matters.

## Time-series (mostly appends with retention)

Examples: metrics, IoT, audit logs, event streams.

**Characteristics:**
- Write rate steady or growing, read rate moderate
- Mostly append; rarely updates
- Retention-bounded; data ages out
- Often time-range queries

**Sizing priorities:**
1. **Disk IOPS for sustained writes** — IOPS dominates
2. **Storage** — grows linearly until retention kicks in
3. **Compaction** — works hard against the steady write load
4. **Working set is tiny** (typically just the recent time window)

**Service mix:**
- Data-heavy nodes (lots of disk, moderate RAM)
- Magma storage engine (8.x) if document count per node > 100M
- Collection rotation for retention (see `couchbase-data-modeling` skill's time-series reference)

**Sizing tip:** the steady-state size is bounded by retention. If you write 1 GB/day and keep 90 days, max size is 90 GB. Plan for retention-stable size, not unlimited growth.

## Vector search workloads

Examples: semantic search, RAG, recommendation systems, image similarity.

**Characteristics:**
- Vector indexes dominate RAM (see `indexes.md`)
- Read-heavy on the vector side
- Often combined with scalar filtering (hybrid search)
- Document size larger due to embedding storage

**Sizing priorities:**
1. **RAM for the vector index** — typically the largest line item
2. **Large RAM tier nodes** for Search service
3. **Storage for embeddings** — 6 KB per doc for 1536-dim float32 vectors adds up
4. **CPU for vector similarity computation** — search is CPU-intensive

**Service mix:**
- Dedicated Search nodes with large RAM (vector index needs to be RAM-resident)
- Separate Data nodes for the source documents
- Query nodes if hybrid search is used (vector + N1QL filter)

**Typical shape for 10M docs, 1536-dim:**
- 3 data nodes, moderate RAM (sized for working set of source docs)
- 2 Search nodes with 64+ GB RAM each (sized for ~85 GB vector index split across them)
- 2 query/index nodes
- = 7 nodes total

**Common mistake:** putting vector indexes on the same nodes as data and underestimating RAM. The vector index is often 5-10x the working set in size.

## Multi-tenant SaaS

Examples: B2B SaaS products with many customer tenants.

**Characteristics:**
- Per-tenant access control (scope-per-tenant pattern, see `couchbase-data-modeling`)
- Wildly varying tenant sizes (one tenant 100x bigger than another)
- Queries scoped per-tenant
- Background jobs across all tenants

**Sizing priorities:**
1. **Capacity for the LARGEST tenant** scaled appropriately
2. **Per-tenant working set** sums across tenants
3. **Index per scope** if access patterns differ per tenant
4. **Resource isolation** for any noisy-neighbor concerns

**Service mix:**
- Similar to mixed transactional
- Consider separate clusters for very large tenants vs the long tail of small ones (cost: extra cluster overhead; benefit: noisy-neighbor isolation)

**Sizing math:** sum the per-tenant working sets, plus 50% buffer for the largest tenant growing.

## Analytical (OLAP) workloads

Examples: business intelligence, ad-hoc reporting, data exploration.

**Characteristics:**
- Few, expensive queries (vs many cheap queries)
- Large scans and aggregations
- Latency tolerance is higher (seconds OK)
- Doesn't impact OLTP if isolated

**Sizing priorities:**
1. **Use the Analytics service** (separate from Query)
2. **Storage and CPU heavy** — different node sizing than OLTP
3. **Dedicated nodes** so OLAP doesn't disrupt OLTP

**Service mix:**
- Dedicated Analytics node pool (Pattern C from `nodes.md`)
- Typical: 3 Analytics nodes with high CPU and storage
- Co-located with the rest of the cluster, but service-separated

## Cache-like workload

Examples: session store, computed-result cache, page cache.

**Characteristics:**
- High write rate (cache populates and evicts constantly)
- High read rate (every cached read is a hit)
- TTL-heavy (entries expire)
- Data loss acceptable (it's a cache; re-compute is possible)

**Sizing priorities:**
1. **RAM** — the entire cache should fit
2. **Replica = 0 or 1** — losing the cache isn't catastrophic
3. **Ephemeral bucket type** — lower overhead than couchbase bucket
4. **fullEviction** — when item count is high

**Service mix:**
- Data only, often a single-bucket use case
- Light Query usage if any

## Summary table

| Workload | Replicas | Indexes | RAM/node priority | Disk/node priority | Special |
|---|---|---|---|---|---|
| Read-heavy | 1-2 | Many (covering) | High | Medium | Replica = 2 for read distribution |
| Write-heavy | 1 | Few | Medium | High IOPS | Separate index nodes |
| Mixed | 1 | Moderate | High | Medium | Data + query/index split |
| Burst | 1-2 | As needed | Sized for peak | Sized for peak | Pre-provision for peak |
| Time-series | 1 | Minimal | Low (small WS) | High capacity | Magma + collection rotation |
| Vector | 1-2 | Vector indexes | Very high (large vector index) | High | Dedicated Search nodes |
| Multi-tenant | 1 | Per-tenant | Sum of tenants | Sum of tenants | Scope-per-tenant |
| Analytics | n/a for OLAP | None for OLAP | High for Analytics | Very high | Dedicated Analytics nodes |
| Cache | 0-1 | None | Very high | Low | Ephemeral bucket, fullEviction |

## Quick decision tree

- **Workload is mostly reads?** → more replicas, larger working set, more indexes
- **Workload is mostly writes?** → high IOPS, fewer indexes, separate index nodes
- **Burst-prone?** → size for peak + 20% headroom; pre-provision before the burst
- **Time-series?** → collection rotation; Magma engine; low working set
- **Vector search?** → dedicated Search nodes with large RAM; vector index dominates
- **Multi-tenant?** → scope-per-tenant; size for sum of tenants + largest-tenant headroom
- **Analytics?** → dedicated Analytics node pool; doesn't impact OLTP
- **Cache?** → ephemeral bucket, fullEviction, replica=0 if loss tolerable
