# Capella tier selection

Couchbase Capella's pricing model is per-node-tier × node-count. Picking the right tier is mostly about matching the tier's spec to your workload, then choosing node count for fault tolerance and capacity.

This reference covers the selection logic. Specific tier names, prices, and specs change over time — verify current details at https://www.couchbase.com/products/capella/.

## How Capella sizing differs from self-managed

- **Tier = bundled compute + RAM + storage + network**, picked together rather than separately
- **Storage is included** in some tiers and separable in others (compute-storage separation)
- **Replicas and high availability** are managed by Capella; you choose the count, Capella places them
- **Network and bandwidth are managed** — no need to size NICs
- **Backup, monitoring, alerts** are included
- **Upgrades** are managed (no rolling-upgrade runbook needed — Capella handles it)

You DO still need to size:
- Tier (per-node specs)
- Node count
- Replica count
- Service mix (in tiers that support per-service nodes)
- Storage if separately provisioned
- Number of clusters if you need multi-region or workload isolation

## The selection logic

### Step 1: estimate workload size

Use the calculations from `memory.md` and `disk.md` to get:
- Total RAM needed across the cluster (sum of all services)
- Total storage needed
- Peak QPS for sizing CPU

### Step 2: pick the smallest tier that fits

Capella tiers come in sizes from "developer / free" up through large compute-heavy nodes. Match the tier so that:

```
needed_RAM_per_node ≤ tier_RAM × 0.7
```

The 0.7 is headroom — running at 70% of capacity leaves room for spikes and headroom for OS / monitoring.

Don't over-pick — a tier 2 sizes too big means paying for unused capacity.

### Step 3: pick node count

Apply the node-count rules from `nodes.md`:
- At least 3 for replica=1 production
- At least 4 if you want N-1 fault tolerance with replica=2
- Higher counts for higher fault tolerance or throughput

### Step 4: validate with the N-1 rule

After picking the tier and node count, recompute: can the cluster handle the workload with one node missing?

If not, either:
- Pick a larger tier
- Add more nodes of the same tier

### Step 5: pick services per node (if applicable)

In tiers that support per-service deployment, separate the workload:
- Data nodes: tier optimized for RAM and disk
- Query/Index nodes: tier optimized for RAM
- Search nodes (especially vector-heavy): largest RAM tier
- Eventing: smallest tier sufficient for function memory
- Analytics: dedicated tier (CPU + storage)

## Workload-to-tier matching

Rough guidance:

| Workload | Cluster size | Tier suggestion |
|---|---|---|
| Dev / staging | 1-3 nodes | Free or smallest paid tier |
| Small production (< 10M docs) | 3 nodes | Small tier, all services |
| Medium production (10-100M docs) | 4-6 nodes | Medium tier, split data/query nodes |
| Large production (100M-1B docs) | 6-12 nodes | Large tier, dedicated service nodes |
| Vector / FTS heavy | 4+ nodes for Search | Large RAM tier for Search nodes |
| Analytics workload | 3+ nodes for Analytics | Dedicated Analytics tier |
| Multi-region / multi-cluster | Multiple clusters | Tier per cluster sized to that cluster's role |

## Compute-storage separation

Newer Capella tiers separate compute and storage. With this:

- Compute scales independently (more vCPU/RAM without paying for more disk)
- Storage scales independently (larger disk without paying for more vCPU/RAM)
- Useful for workloads where one dimension dominates

**When this helps:**
- Large datasets with modest CPU: storage-heavy, compute-light (use it)
- Compute-heavy, small dataset: opposite (use it)
- Balanced workload: standard tiers are usually fine

## Multi-cluster patterns

For multi-region or workload-isolation, deploy multiple Capella clusters:

**Pattern: regional with XDCR**
- One cluster per region
- XDCR replicates writes (typically active-passive: primary region accepts writes, others replicate read-only)
- Cost: pay for each region's cluster + WAN bandwidth for XDCR

**Pattern: workload isolation**
- One cluster for OLTP (Data + Query)
- One cluster for Analytics
- One cluster for development / staging
- XDCR between them as needed
- Cost: 3 clusters, but each is sized exactly for its workload

**Pattern: customer isolation (B2B SaaS)**
- One cluster per customer or per customer tier
- Highest isolation but most expensive
- Justified only when one customer's workload can impact others, or compliance requires isolation

## Cost optimization

A few patterns that materially reduce Capella cost:

**Right-size aggressively.** It's tempting to over-size "just in case." Capella supports online scaling — you can increase the tier later. Start at 60-70% projected utilization on the chosen tier; scale up when you actually need it.

**Use compute-storage separation for data-heavy workloads.** Saves 30-50% vs paying for the same storage on standard tiers.

**Pause non-production clusters.** Dev and staging clusters can be paused outside of work hours. Capella charges less (or nothing for some tiers) for paused clusters.

**Drop unused indexes.** Each index uses RAM, which determines tier sizing. `cb_index_advisor` and `admin_index_get` `last_used` help find them.

**Tune working set assumption.** If you've been sizing for 50% working set but actual measurement shows 20%, downsize the tier or node count.

**Consider archiving cold data.** Move data older than X months out of the active cluster. Either delete (if not needed) or backup-then-delete (if needed for compliance, restore on demand).

## Quick decision tree

- **Sizing for the first time?** Use `memory.md` math, pick the smallest Capella tier that fits with 30% headroom
- **Production?** Minimum 3 nodes, replica=1; validate N-1 fault tolerance
- **Vector workload?** Pick the largest RAM tier; vector indexes dominate sizing
- **Multi-region?** Multiple clusters with XDCR; budget for inter-region bandwidth
- **Cost-conscious?** Compute-storage separation; pause non-prod; drop unused indexes
- **Workload changing?** Capella supports online scaling — don't over-size at start
