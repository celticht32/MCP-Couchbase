# Disk and storage

Memory gets the headlines, but disk sizing matters too — and it's where many sizing exercises trip up because the math is non-obvious. Couchbase stores everything to disk eventually, and the disk footprint can be 2-5x the working memory size.

## What lives on disk

Per node:

1. **Active data** — the partition of documents this node is responsible for
2. **Replica data** — copies of data from other nodes
3. **Compaction overhead** — temporary space during compaction (can briefly equal the bucket size)
4. **GSI / FTS / vector index files** — if those services are on this node
5. **Append-only files** for KV (compacted periodically)
6. **System / logs / configs** — small but non-zero

## The storage equation

For data only (KV):

```
disk_for_data = total_doc_count × avg_doc_size × (1 + replica_count) × compaction_headroom × growth_buffer
              / data_node_count
```

Where:
- `compaction_headroom` ≈ 1.4-2.0 (Couchbase uses append-only writes; old document versions persist until compacted, taking ~40-100% extra)
- `growth_buffer` ≈ 1.5-2.0 (12-18 months of growth)

### Worked example

Inputs:
- 100M documents, 1 KB average
- Replica count: 1
- 5 data nodes
- 18 months projected growth: 3x today
- Default compaction settings

```
total_data_today = 100M × 1 KB × 2 (replicas) = 200 GB
total_data_at_growth = 200 GB × 3 = 600 GB
with_compaction = 600 GB × 1.6 = 960 GB
per_node = 960 GB / 5 = 192 GB
```

Plus index storage, plus logs, plus OS: provision **~300 GB per node** disk.

If the budget allows, round up — running out of disk is operationally painful, and the cost of larger SSDs is small.

## Compaction explained

Couchbase uses append-only writes. When a document is updated, the new version is appended; the old version stays until compaction removes it.

Compaction:
- Runs in the background
- Triggered when fragmentation exceeds a threshold (default 30%)
- Rewrites the data file to remove old versions
- Briefly doubles disk usage during the rewrite

If compaction can't keep up (very write-heavy workloads), disk fragmentation grows and you need more headroom. Tune via `admin_autocompaction_set` — lower fragmentation threshold for tighter disk use, higher threshold for less compaction CPU.

## Storage type: SSD vs HDD vs cloud volumes

- **NVMe SSD** — required for production. Couchbase is I/O-intensive; spinning disk is unusable
- **SATA SSD** — OK for non-latency-critical workloads
- **HDD** — only acceptable for backup repositories, never for active data
- **Cloud block storage** (EBS gp3, GCP pd-ssd, Azure Premium SSD) — works but IOPS matter; provision at least 3000 IOPS per node, more for write-heavy
- **Local instance storage** (NVMe attached to the VM) — fastest but ephemeral; only use if your replication strategy can rebuild a lost node fast

For Capella: storage type is included in tier selection.

## Couchbase 8.x: Magma storage engine

Couchbase 8.x introduces Magma, an LSM-tree storage engine optimized for large datasets per node.

| Storage engine | Best for | Documents per node |
|---|---|---|
| Couchstore (default pre-8.x) | Most workloads | < 100M docs / node |
| Magma | Large datasets, high write rate | > 100M docs / node |

Magma is the better choice when:
- You have more than ~100M documents per node
- You're using fullEviction (it pairs well with Magma's design)
- Write rate is high and steady

Set the storage engine when creating the bucket. Migration between engines requires a rebuild.

8.x adds "Magma 128 vBuckets" — a tuning that further improves performance for high-vBucket-count workloads.

## Index storage

GSI indexes also live on disk:

- An index typically uses 1-3x the size of the indexed fields
- A composite index on 3 fields × 100M docs × 40 bytes per indexed value × 1.5 = ~18 GB per index
- Vector indexes are much larger — see `indexes.md`

Plan index storage as a separate budget. If you're running Index service on the same nodes as Data, allocate disk for both.

## FTS / Search storage

FTS indexes:
- Typically 30-100% the size of the indexed text
- Vector indexes (8.x) much larger — `indexes.md`

Same pattern: allocate explicit disk budget for the Search service if it's on this node.

## Analytics storage

Analytics maintains shadow datasets — copies of the source data optimized for analytical queries. Storage = total source data size (roughly). On dedicated Analytics nodes, plan disk = total cluster data × 1.5.

## Logs and system

- Couchbase logs grow with activity. Default rotation keeps recent ones; configure via `admin_logs_get` if growth is a problem
- Audit logs (when enabled) can grow fast — plan separate disk if audit is high-volume
- Don't put data and logs on the same disk; log writes can compete with data I/O

## Backup storage

Backups go to a separate location — typically:
- Local backup repository on a backup node's disk
- Network-attached storage (NFS)
- Object storage (S3, GCS, Azure Blob)

Backup storage = (total data × number of backups retained). For weekly fulls + daily incrementals retained for 30 days, plan ~4-5x total data size for backup storage.

This is on top of the cluster's own storage.

## Disk IOPS

IOPS matters as much as capacity for write-heavy workloads:

| Workload type | IOPS per data node |
|---|---|
| Read-heavy (90/10) | 1000-3000 |
| Balanced (60/40) | 3000-5000 |
| Write-heavy (10/90) | 5000-10000+ |
| Vector workloads | 5000-10000+ (index updates are expensive) |

For cloud volumes, provision IOPS explicitly. Default volumes often have IOPS limits that hurt write-heavy workloads.

## Growth strategies

Disk has friendlier scaling than RAM in most ways:

- **Grow vertically:** swap volumes to larger ones, or extend cloud volumes online. No data movement needed
- **Grow horizontally:** adding a node spreads the data wider, reducing per-node disk pressure

In Capella with compute-storage separation, disk and compute scale independently — easier than self-managed.

## Common mistakes

- **Sizing for just the data, ignoring compaction headroom** — disk fills up sooner than expected
- **Putting Couchbase data and logs on the same volume** — log writes interfere with data I/O
- **Using HDD for active data** — unusable performance
- **Provisioning minimum IOPS in cloud** — write throughput hits a wall, no clear error
- **Forgetting backup storage** — typically several times the cluster's own storage
- **Sizing for today, not 18 months from now** — disk migration is annoying enough that planning ahead pays off

## Quick decision tree

- **Calculating from scratch?** Use `total_docs × avg_size × (1 + replicas) × 1.6 × growth_factor / nodes`
- **> 100M docs per node?** Use Magma storage engine (8.x)
- **High write rate?** Provision more IOPS (5000+ on cloud volumes)
- **Mixed services on one node?** Add up the storage for each service's needs
- **Backup planning?** ~4-5x total data size for typical retention
- **Production?** Always NVMe SSD or top-tier cloud SSD; never HDD for active data
