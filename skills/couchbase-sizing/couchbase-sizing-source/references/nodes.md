# Nodes and replicas

How many nodes do you need, what replica count, and where should each service live? The answers come from three constraints: fault tolerance, load capacity, and ops simplicity.

## Replica count

Replica count is the number of additional copies of each piece of data, beyond the active copy.

| Replicas | Total copies | Total nodes data lives on | Survives | Use when |
|---|---|---|---|---|
| 0 | 1 | 1 | nothing | Dev / cache where data loss is OK |
| 1 | 2 | 2 | 1 node failure | Most production workloads |
| 2 | 3 | 3 | 2 node failures (rare) | Critical data, large clusters |
| 3 | 4 | 4 | 3 node failures (very rare) | Compliance / regulatory requirements |

The default is replica = 1. Replica = 2 is justified for:
- Compliance requiring N+2 durability
- Large clusters (>10 nodes) where simultaneous double-failures are statistically meaningful
- Data so critical that a single failure-during-rebalance can't be tolerated

Replica = 3 is rare; usually only seen in highly regulated environments.

**Cost of replicas:** each replica is a full copy of the data. RAM and disk multiply by `1 + replica_count`. Network traffic also scales (every write replicates).

## Minimum node count for replicas

Couchbase requires at least `1 + replica_count` data nodes to place all copies. Practical minimums (with one extra for failure tolerance):

| Replicas | Absolute min | Recommended min |
|---|---|---|
| 0 | 1 | 2 |
| 1 | 2 | **3** |
| 2 | 3 | **4** |
| 3 | 4 | **5** |

"Recommended" assumes you want to be able to LOSE one node and still have full replica placement.

3 data nodes with replica=1 is the most common starting production shape.

## The N-1 sizing rule

Always size for `N-1` nodes (one node missing). When a node fails:

- Its data load redistributes to remaining nodes
- Its replicas on other nodes are promoted to active
- The cluster needs to handle 100% of normal load with one less node

If your cluster runs at 80% capacity on N nodes, losing one means the remaining `N-1` nodes need to handle:
- 100% of the load (unchanged)
- Across N-1 nodes instead of N

So the per-node load goes from 80% to `80% × N / (N-1)`. For N=3: 120% — over capacity, you're degraded.

For sustainable failure tolerance, size for steady-state utilization no higher than `(N-1) / N × 80%`:

| Nodes | Steady-state max |
|---|---|
| 3 | ~53% |
| 4 | ~60% |
| 5 | ~64% |
| 6 | ~67% |
| 10 | ~72% |

This is why larger clusters can run "hotter" — losing one of 10 is less impactful than losing one of 3.

## Scale up vs scale out

Two ways to add capacity: bigger nodes (scale up) or more nodes (scale out).

| Dimension | Scale up favored | Scale out favored |
|---|---|---|
| Throughput-per-node | Yes | Lower per-node |
| Fault tolerance | Worse | Better |
| RAM utilization | Better at high tiers | More fragmentation |
| Rebalance time | Slower (more data per node) | Faster (less data per node) |
| Network blast radius on failure | Larger | Smaller |
| Per-node cost (cloud pricing) | Often cheaper / GB at top tiers | More instances |
| Operational complexity | Simpler (fewer machines) | More machines to monitor |

**Default progression:**
1. Start with smallest reasonable cluster (3 nodes typically)
2. Grow vertically (bigger nodes) until single-node failure becomes too impactful
3. Then grow horizontally (more nodes)
4. At very large scale (>20 nodes), consider whether multiple clusters with XDCR would simplify ops

**Hard limits:**
- Cluster can have up to ~1000 nodes in theory; practically <100 is sane
- Single nodes practically cap at ~256 GB RAM (above this, cluster overhead dominates)

## Service placement

Couchbase has multiple services that can run on any node combination. Choosing well materially affects cost and performance.

### Service list

- **Data (KV)** — required; the heart of Couchbase
- **Query (N1QL)** — required if you want SQL++ queries
- **Index (GSI)** — required if you want secondary indexes
- **Search (FTS / vector)** — full-text and vector search
- **Eventing** — server-side JS functions on data mutations
- **Analytics** — separate massively parallel query service for OLAP-style workloads
- **Backup** — coordinator for backup/restore operations

### Three deployment patterns

**Pattern A: all services on every node**

Simplest. All N nodes run Data, Query, Index, Search, Eventing.

Good for: small clusters (≤ 5 nodes), dev/staging, low total scale.

Bad for: production at scale — services compete for RAM and CPU; one heavy query can starve KV operations.

**Pattern B: Data nodes + Query/Index nodes**

Separate the data plane from the query plane. Typical: 3 data nodes + 2 query/index nodes.

Data nodes do KV only — low-latency, RAM-budgeted for working set.
Query/Index nodes run Query, Index, and possibly Search.

Good for: medium scale (5-15 nodes), production.

Most common production shape.

**Pattern C: dedicated nodes per service**

Each service has its own node pool. Data nodes are storage-optimized. Index nodes are RAM-optimized. Analytics nodes are storage + CPU optimized (often a completely different instance type).

Good for: large scale (>15 nodes), workload isolation requirements.

The expensive option but the cleanest.

### Service-specific sizing notes

**Data service:** dominant RAM consumer (see `memory.md`). Storage = total data × (1 + replicas).

**Query service:** RAM for query workspace (sorts, joins, aggregates). Stateless — just CPU and RAM. Scale horizontally to add throughput.

**Index service:** RAM for indexes (see `indexes.md`). Stateful — losing an index node means re-syncing on recovery. Plan for at least 2 index nodes for fault tolerance.

**Search (FTS / vector):** RAM-heavy when vector indexes are involved (`indexes.md` has the math). Disk for the index data. Stateful like Index.

**Eventing:** RAM for function workspace (~512 MB per active function instance, scales with worker count). CPU for function execution. Often co-located with Data because functions react to mutations.

**Analytics:** completely separate workload. Storage-heavy (shadow datasets). Often on its own node pool. Doesn't impact OLTP.

**Backup:** lightweight coordinator. Can run on any node; minimal resource needs.

## Server groups (rack awareness)

For multi-rack / multi-AZ deployments, server groups tell Couchbase to place replicas across groups. So if rack 1 fails, rack 2 has the replicas.

Configuration via `admin_server_group_*` tools.

Without server groups, Couchbase distributes replicas without rack awareness — a rack failure could lose multiple replica copies of the same data.

**Use server groups when:**
- AWS / GCP / Azure deployments across AZs
- On-prem with multiple racks/data centers
- Any deployment where node failures are correlated (entire rack power, network switch)

The rule: at least `1 + replica_count` server groups so replicas can be distributed.

## Capella node count

For Capella, you pick a tier (which determines per-node specs) and a node count separately. Same math applies — start with at least 3 nodes for replica=1, more for headroom.

Capella also offers compute-storage separation in some tiers, where storage scales independently of compute. For data-heavy / read-light workloads, this is more efficient than pure-compute scaling.

## Quick decision tree

- **Replica count?** → 1 unless you have compliance or you're at very large scale (>10 nodes), then 2
- **Minimum nodes?** → 3 for replica=1, 4 for replica=2, 5 for replica=3
- **Steady-state load target?** → never above `(N-1)/N × 80%` so a single node failure is absorbable
- **Scale up vs out?** → scale up while N is small; scale out when single-node failure becomes too impactful
- **Service mix?** → all-services on small clusters; data + query/index split at medium scale; dedicated per-service at large scale
- **Multi-AZ / multi-rack?** → configure server groups so replicas distribute correctly
- **Analytics needed?** → run it on its own node pool to avoid impacting OLTP
