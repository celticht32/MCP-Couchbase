# Memory and working set

Memory is the most consequential sizing dimension in Couchbase. Get this wrong and the cluster either over-provisions (wasted spend) or under-provisions (degraded performance, eviction storms). This reference walks through the math.

## What needs to fit in RAM

Couchbase nodes hold these things in RAM:

1. **Working set of documents** — the subset of documents actively being read/written. This is the dominant consumer
2. **Per-document metadata** — ~56 bytes per document, always in RAM regardless of working set (in `valueOnly` eviction mode) or paged with the document (in `fullEviction` mode)
3. **The bucket's RAM quota overhead** — small but non-zero
4. **GSI indexes** — if the Index service is on this node
5. **FTS / vector indexes** — if the Search service is on this node
6. **Query service workspace** — query execution uses RAM for sorts, aggregates, joins
7. **Eventing function memory** — if Eventing is on this node
8. **System overhead** — OS, monitoring, replication buffers

A reasonable starting allocation for a small all-services node:

- ~60% Data service (KV)
- ~20% Index service (if GSI is heavy)
- ~10% Query / Search / Eventing workspace
- ~10% system + headroom

For larger clusters with dedicated nodes, the allocation per service can be much more skewed.

## The fundamental memory equation for KV

For one bucket on one node:

```
RAM_needed = (working_set_size + metadata_overhead) × (1 + replica_count) / data_node_count
```

Where:
- `working_set_size` = `document_count × avg_doc_size × working_set_fraction`
- `metadata_overhead` = `document_count × 56 bytes` (per-doc Couchbase overhead, valueOnly eviction)
- The `(1 + replica_count)` factor accounts for replicas living on other nodes — each document exists on `1 + replica_count` nodes total

Then add headroom and per-service overhead.

### Worked example 1: small app

Inputs:
- 1M documents
- Avg doc size: 2 KB
- Working set: 100% (small enough to all fit)
- Replica count: 1
- 3 data nodes
- All-services nodes

Calculation:

```
working_set_size = 1,000,000 × 2 KB × 1.0 = 2 GB
metadata_overhead = 1,000,000 × 56 bytes ≈ 56 MB
RAM_for_KV = (2 GB + 56 MB) × 2 / 3 ≈ 1.4 GB per node
```

Plus ~20% for index/query/eventing, plus 20% headroom: each node needs roughly 2 GB for this bucket. With ~2 GB for the OS and other services, a 4 GB node would be tight; **8 GB nodes** are comfortable.

### Worked example 2: medium SaaS

Inputs:
- 100M documents
- Avg doc size: 1 KB
- Working set: 20% (most users are inactive at any moment)
- Replica count: 1
- 5 data nodes
- GSI on same nodes

Calculation:

```
working_set_size = 100M × 1 KB × 0.2 = 20 GB
metadata_overhead = 100M × 56 bytes ≈ 5.6 GB    ← significant! all 100M docs' metadata
RAM_for_KV = (20 GB + 5.6 GB) × 2 / 5 ≈ 10.2 GB per node
```

GSI (assume 5 indexes, ~500 MB each): +2.5 GB
Other services + headroom: +3 GB

**Per-node RAM: ~16 GB** for this bucket alone. So **32 GB nodes** with comfortable headroom.

Note how metadata overhead (5.6 GB) is meaningful at 100M docs. At 1B docs it dominates.

### Worked example 3: large with cold tail

Inputs:
- 1B documents
- Avg doc size: 500 bytes
- Working set: 5% (long tail of inactive)
- Replica count: 1
- 10 data nodes
- Dedicated data nodes (no index / FTS)

Calculation:

```
working_set_size = 1B × 500 bytes × 0.05 = 25 GB
metadata_overhead = 1B × 56 bytes = 56 GB    ← dominant
RAM_for_KV = (25 GB + 56 GB) × 2 / 10 ≈ 16.2 GB per node
```

For this scale, you'd switch to **fullEviction mode** to avoid the 56 GB metadata-in-RAM requirement.

In fullEviction:

```
RAM_for_KV ≈ working_set × (1 + replicas) / nodes + small_meta_overhead
           = 25 GB × 2 / 10 ≈ 5 GB per node
```

Massive reduction. fullEviction trades RAM efficiency for slight read latency increase on cold-data fetches.

## Eviction policy choice

| Policy | When to use | Tradeoff |
|---|---|---|
| `valueOnly` (default) | Document count < ~50M per node, OR latency-critical | Lower latency, but ALL doc metadata in RAM |
| `fullEviction` | Document count > 100M per node | Slight latency cost on cold fetches, but RAM scales with working set not total docs |

The break-even calculation: metadata overhead becomes problematic when `document_count × 56 bytes` exceeds ~20-30% of your RAM budget for that node.

## Working set assumptions

The working set fraction is the most uncertain input and the most consequential. Some heuristics:

| Workload type | Typical working set |
|---|---|
| Active session / cache layer | 80-100% |
| User profile / configuration | 30-60% |
| Transactional with hot recent data | 20-40% |
| Time-series with recent-window reads | 5-20% |
| Archive / cold storage | 1-5% |

**If you're not sure, model both 30% and 60% scenarios** and present the user with the resource requirement at each. They'll have a better sense of their actual access pattern.

## Bucket RAM quota — what it actually is

Each bucket has a `ram_quota_mb` setting. This is the RAM the bucket is ALLOWED to use across the cluster, NOT per node.

So a bucket with `ram_quota_mb = 30000` (30 GB) on a 3-node cluster uses up to 10 GB per node.

The cluster reserves this much regardless of whether the bucket actually has data — over-allocating bucket quota wastes RAM for no benefit.

## Multiple buckets

When you have multiple buckets on the same cluster, they share total RAM. The sum of bucket quotas across all buckets must fit within the cluster's RAM budget for the Data service.

Common allocation: split quotas roughly proportional to data size or write rate, leaving 20-30% of total RAM unallocated for the Data service to use as cache for whichever bucket is busiest at a given moment.

Each bucket also has fixed overhead (~50-100 MB per bucket on each node) for bookkeeping. Many small buckets waste this overhead; consolidate into scopes/collections when possible.

## Compaction and rebalance RAM

Both compaction (background) and rebalance (during topology changes) need additional RAM:
- **Compaction**: typically 10-20% extra RAM temporarily
- **Rebalance**: highly variable; can use 30%+ extra RAM during heavy data movement

The 20% headroom in our equations covers compaction but not heavy rebalance. If you're regularly adding/removing nodes, plan for more headroom or accept that rebalances will be slower because they're throttled by available RAM.

## Memory pressure symptoms

When the cluster doesn't have enough RAM:

- Cache miss ratio climbs (a healthy cluster has < 5% cache misses for the working set)
- Disk reads increase (the cluster is paging cold data in on every miss)
- Latency p99 spikes (paging is much slower than RAM access)
- Eviction events appear in logs (`admin_logs_get`)
- Stats show `mem_used` approaching the bucket quota (`admin_stats_overview`)

If you're seeing these in production, add RAM. The cluster is under-sized for its working set.

## Quick decision tree

- **Calculating from scratch?** Use the equation: `(working_set + metadata) × (1 + replicas) / nodes + headroom`
- **Don't know the working set?** Model 30% and 60% scenarios
- **> 100M docs per node?** Use fullEviction policy
- **Multiple buckets?** Allocate quotas proportional to data size; leave 20-30% unallocated for the Data service to manage
- **Seeing eviction in logs?** Add RAM, not nodes (unless you're also CPU-constrained)
- **Sizing for cluster growth?** Project 12-18 months out; doubling RAM is harder than doubling node count
