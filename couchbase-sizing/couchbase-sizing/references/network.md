# Network and XDCR bandwidth

Network is often invisible in sizing until something breaks. Couchbase clusters move a lot of bytes — replicas, indexing, rebalances, XDCR, query results — and under-provisioned network shows up as confusing latency spikes that are hard to diagnose.

## Network within the cluster

Couchbase nodes talk constantly:

- **Replication traffic**: every write propagates to replicas. Bandwidth = `write_rate × avg_doc_size × replica_count`
- **Rebalance traffic**: data movement during topology changes. Can spike to many GB/sec briefly
- **Query traffic**: query results streaming between Query and Data nodes
- **Index traffic**: index service pulls mutations from Data service
- **Eventing traffic**: similar — mutations push to Eventing
- **Cluster manager traffic**: heartbeats, stats, config sync. Minimal

For a typical production cluster, internal network should be:
- **10 Gbps** minimum (1 Gbps is workable for small clusters but limits rebalance speed)
- **25 Gbps+** for high-write workloads or large clusters

Cloud VMs: pick instance types with the higher network tiers. AWS for example has "Up to X Gbps" labels — the actual sustained throughput is often lower; benchmark for your workload.

### Worked example

Inputs:
- 50,000 writes/sec sustained
- Average doc size: 2 KB
- Replica count: 2 (so each write goes to 2 other nodes)

```
write_bandwidth_per_write = 2 KB × 2 replicas = 4 KB
total_replication_traffic = 50,000 × 4 KB = 200 MB/sec = 1.6 Gbps
```

This is the steady-state. During rebalance, multiply by 3-5x. 10 Gbps internal network handles this with room; 1 Gbps would be saturated.

## XDCR bandwidth

XDCR (cross-datacenter replication) sends data over WAN/inter-region links — typically slower and more expensive than intra-cluster network.

```
xdcr_bandwidth = source_write_rate × source_avg_doc_size × replication_factor
```

Where `replication_factor` is usually 1 (one target cluster) but can be higher with multiple target clusters.

### Worked example

Same inputs as above + an XDCR replication to a second cluster:

```
xdcr_traffic = 50,000 × 2 KB × 1 = 100 MB/sec = 800 Mbps
```

800 Mbps continuous WAN bandwidth. Whether this is feasible depends on your inter-region link:

| Link type | Practical bandwidth | XDCR feasibility |
|---|---|---|
| Cloud inter-region (same provider) | 5-40 Gbps | Easily handles most workloads |
| Cloud inter-region (cross-provider) | varies | Plan carefully |
| VPN over public internet | 100 Mbps - 1 Gbps | Limits XDCR to lower write rates |
| Dedicated leased line | 1-10 Gbps | Good for most workloads |
| Branch / edge sites | Often < 100 Mbps | XDCR may be infeasible |

XDCR has built-in throttling (configurable via `admin_xdcr_replication_update`) but if the source is writing faster than the link can replicate, lag accumulates indefinitely.

### XDCR initial sync

The first sync of an existing dataset replicates the entire dataset. For 1 TB of data over a 1 Gbps link, that's ~2.5 hours minimum (and you won't get full link speed). Plan accordingly:
- Start the XDCR setup during off-peak hours
- Monitor `admin_xdcr_replication_get` for progress
- Don't start production traffic relying on the target until initial sync completes

## Network for client traffic

In addition to internal traffic, the cluster receives client traffic (KV gets/puts, queries, etc.).

```
client_ingress = peak_client_qps × avg_request_size
client_egress = peak_client_qps × avg_response_size
```

For a typical web app with 50K QPS:
- Avg request: 200 bytes → 10 MB/sec (small)
- Avg response: 5 KB (small JSON doc) → 250 MB/sec = 2 Gbps

Egress dominates. For workloads returning large query results or full documents, plan egress as the constraint.

## Network during rebalance

Rebalances move data between nodes. The network impact:

- Cluster moves up to ~10% of total data per node per minute during active rebalance (varies with disk and CPU speed)
- For a node with 100 GB of data, that's ~1.7 GB/sec of moving data during rebalance
- This traffic is in addition to normal cluster traffic

Internal network needs headroom for this. If you provision exactly enough for steady-state, rebalances will be slow (good — backpressure throttles) but visibly impact normal operations.

## Multi-region / multi-cluster considerations

If you operate clusters in multiple regions:

- **Active-active XDCR**: bidirectional replication. Network bandwidth doubles (both directions). Conflict resolution becomes important — see `couchbase-mcp` skill's reference on XDCR conflict logging
- **Active-passive XDCR**: writes go to one cluster, replicate to the other read-only. Simpler, less network
- **Geo-distributed reads with regional writes**: route reads to the local cluster, writes to the regional master cluster, replicate via XDCR. Most common pattern

The further apart the clusters, the more important to monitor XDCR lag. Replication lag at 10 seconds is fine; at 10 minutes there's something to investigate.

## Application-level network optimizations

Things the user can do to reduce required network:

- **Use `cb_lookup_in` to fetch only specific fields** instead of full documents — drops bandwidth proportional to the fraction of fields not retrieved
- **Use `cb_get_multi` instead of N individual `cb_get` calls** — one round-trip instead of N
- **Avoid large response sets**: paginate. `cb_perf_large_response_sizes` (see the couchbase-mcp skill) finds offenders
- **Compress documents** at the SDK level — Couchbase doesn't compress automatically on the wire, but SDKs can

## Network monitoring signals

Symptoms of network bottlenecks:

- Replicas falling behind (visible in `admin_stats_overview` as replication queue length)
- XDCR lag growing (`admin_xdcr_replication_get` `changes_left` field)
- Increased query latency p99 with no obvious CPU or disk issue
- Rebalance taking much longer than estimated
- Client-side timeouts that don't correlate with cluster CPU/memory pressure

If you see these together, suspect network. Confirm with infrastructure-level monitoring (interface utilization, packet drops).

## Cloud-specific gotchas

- **Bandwidth credits / burst limits**: many cloud instance types advertise peak bandwidth that's only sustained for limited time. Sustained workloads need instance types with documented sustained bandwidth
- **Cross-AZ traffic costs money**: in AWS / Azure / GCP, traffic between AZs is billed. Multi-AZ clusters can have meaningful cross-AZ bandwidth bills. Plan for it
- **Egress to internet** (e.g., if clients are outside the cloud) is the most expensive cloud bandwidth. Co-locate clients with the cluster when possible
- **NAT gateway bandwidth limits**: traffic through a NAT can be limited; bypass NAT for cluster-internal traffic

## Quick decision tree

- **Calculating cluster-internal bandwidth?** `write_rate × avg_doc_size × replica_count` + headroom for rebalance
- **Calculating XDCR bandwidth?** `source_write_rate × source_avg_doc_size × target_count`
- **Initial XDCR sync time?** `total_dataset_size / link_bandwidth × 1.5` (real throughput is below theoretical)
- **Cluster-internal network spec?** 10 Gbps minimum for production; 25 Gbps+ for write-heavy or large clusters
- **Multi-AZ deployment in cloud?** Budget for cross-AZ traffic costs; they're often a surprise
- **WAN-bandwidth-constrained for XDCR?** Use compressed SDK + filter to only critical buckets; consider one-way active-passive instead of bidirectional
