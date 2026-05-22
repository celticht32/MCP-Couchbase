# Index sizing — GSI, FTS, and vector

Indexes are often the second-largest RAM consumer after the working set. Vector indexes especially can dominate. This reference gives the math for each index type so you can plan dedicated index nodes correctly.

## GSI (secondary index) sizing

Global Secondary Indexes are RAM-resident for fast lookups. Each entry in an index uses:

- Bytes for the indexed value(s) — depends on field types
- Bytes for the document key reference — ~50 bytes typical
- Bytes for B-tree / skiplist overhead — ~24 bytes
- Replicas if configured (`with: {nodes: ["node1", "node2"]}`)

Simplified formula:

```
gsi_index_size = document_count × (avg_indexed_value_size + 80 bytes) × (1 + index_replica_count)
```

### Worked example

100M documents, index on a single field `user_id` (8-byte integer), no index replicas:

```
gsi_index_size = 100M × (8 + 80) = 8.8 GB
```

A composite index on `user_id, created_at, status`:

```
indexed_value_size = 8 (user_id) + 8 (timestamp) + 16 (status string) = 32 bytes
gsi_index_size = 100M × (32 + 80) = 11.2 GB
```

For a typical app with 5-10 indexes per collection, this adds up fast. 5 indexes × 10 GB each = 50 GB of index data — needs to fit in Index service RAM.

### When indexes hurt more than help

- Each index is updated on every write to the indexed collection. 5 indexes = 5x the write amplification on the Index service
- Unused indexes (created speculatively) are pure cost. Use `admin_index_get` to check `last_used`
- Wide composite indexes are big AND slow to update

Use `cb_index_advisor` to suggest the minimum useful index set rather than guessing.

## FTS index sizing

FTS indexes store an inverted text index plus stored fields.

```
fts_index_size = total_text_size × analyzer_expansion × storage_factor
```

Where:
- `analyzer_expansion`: ~1.5-2.5x depending on analyzer (tokenization + stemming + n-grams all increase size)
- `storage_factor`: ~1.0 if no fields are stored verbatim, up to ~2.0 if many fields are stored

### Worked example

10M documents, average 2 KB of text per document, standard English analyzer:

```
total_text_size = 10M × 2 KB = 20 GB
fts_index_size = 20 GB × 2.0 (analyzer) × 1.2 (some stored fields) ≈ 48 GB
```

For multi-language workloads or with synonyms, the analyzer expansion can be higher.

FTS indexes can be disk-resident with parts paged into RAM. Plan disk = 1.5x the calculated size for write-time buffering and compaction.

## Vector index sizing

Vector indexes are by far the largest. The math:

```
vector_index_size_raw = document_count × dimension × bytes_per_dimension
```

For float32 vectors (4 bytes/dim):

| Dimensions | 1M docs | 10M docs | 100M docs |
|---|---|---|---|
| 384 | 1.5 GB | 15 GB | 150 GB |
| 768 | 3 GB | 30 GB | 300 GB |
| 1024 | 4 GB | 40 GB | 400 GB |
| 1536 (OpenAI small) | 6 GB | 60 GB | 600 GB |
| 3072 (OpenAI large) | 12 GB | 120 GB | 1.2 TB |

This is the RAW vector storage. The actual index (graph for Composite, hierarchical for Hyperscale) adds overhead:

| Index type | Overhead factor | Notes |
|---|---|---|
| Composite | ~1.3-1.5x | Smaller, faster build, scales to ~10M vectors well |
| Hyperscale | ~1.8-2.5x | More overhead but scales further |

So a Composite index on 10M × 1536-dim vectors is roughly `10M × 1536 × 4 × 1.4 = 84 GB`.

### Vector indexes need RAM, not just disk

Unlike GSI, vector index search needs much of the index in RAM during a search to be fast. Plan:

- 100% of the vector index in RAM if you want sub-second search at scale
- 50-80% in RAM with slower (10-50 ms) search latency

This makes vector workloads RAM-intensive. A 100 GB vector index needs a Search node with ~100 GB of available RAM (more for headroom).

### Reducing vector index size

If size is a problem:

- **Lower-dimensional embeddings**: 1024-dim instead of 1536-dim is 33% smaller
- **Quantization**: some embedding pipelines support int8 quantization, dropping size 4x. Couchbase may or may not support quantized vectors directly depending on version; check current docs
- **Filter scope**: only index documents that will be searched. If half your corpus is archived, don't index it
- **Composite vs Hyperscale**: Composite is smaller for the same corpus

## Eventing memory

Each Eventing function has a memory footprint:

```
eventing_memory_per_function = base_overhead + workers × per_worker_memory
```

Where:
- `base_overhead`: ~100-200 MB per function
- `per_worker_memory`: ~200-500 MB depending on function complexity
- `workers`: configured at function deploy time, typical 4-8

So a function with 4 workers uses ~1-2 GB. 10 deployed functions = 10-20 GB.

Eventing nodes need enough RAM for:
- All deployed functions × their workers
- A buffer for function activity (the JavaScript runtime allocates and frees memory during execution)

Plan ~30% headroom beyond the function memory total.

## Analytics storage and memory

Analytics is its own beast — different storage engine, different sizing model.

- **Storage**: ~1.5x the source data size (shadow datasets + Analytics-specific index structures)
- **Memory**: depends on query complexity. A typical Analytics node needs 64-128 GB RAM for moderate workloads, 256+ GB for heavy joins/aggregations
- **CPU**: Analytics is CPU-heavy; pick high-vCPU instance types

Analytics is usually on dedicated nodes (Pattern C in `nodes.md`) because its workload is so different from OLTP.

## Putting it all together: a typical sizing exercise

For a moderate production deployment:

```
Workload:
  100M documents, 1 KB avg, 20% working set
  5 GSI indexes (avg 3 fields each)
  1 FTS index on a text-heavy field, 2 KB text avg
  1 vector index, 10M docs, 768-dim
  3 Eventing functions
  No Analytics

Per-service RAM budget:

  Data service:    (100M × 1 KB × 0.2 + 100M × 56 bytes) × 2 / 3 nodes ≈ 18 GB/node
  GSI:             ~5 indexes × 3 GB each = 15 GB total (Index service)
  FTS:             10M × 2 KB × 2.0 ≈ 40 GB
  Vector:          10M × 768 × 4 × 1.4 ≈ 42 GB
  Eventing:        3 functions × 2 GB ≈ 6 GB
  Other (Query, etc.): 4 GB

Service placement:
  3 data nodes: 18 GB Data + 5 GB other + 5 GB OS/headroom = 28 GB each → use 32 GB nodes
  2 index nodes: 15 GB GSI + 4 GB Query + 3 GB OS = 22 GB each → use 32 GB nodes
  2 search nodes: 40 GB FTS + 42 GB vector + 3 GB OS = 85 GB → use 128 GB nodes (vector is the driver)
  1 eventing node: 6 GB functions + 4 GB Query + 3 GB OS = 13 GB → use 16 GB node
```

That's 8 nodes total: 3 small data + 2 medium index + 2 large search + 1 small eventing.

Compare to the naive "all-services" approach: every node would need 100+ GB (sum of all services). Service separation saved meaningful cost.

## Common index-sizing mistakes

- **Ignoring vector index size** — vectors are by FAR the largest. A 1536-dim corpus over 10M docs is ~85 GB before overhead
- **Sizing GSI for current data, not projected** — index size grows linearly with documents
- **Forgetting index replicas** — if you set `with: {nodes: [..., ...]}` to get HA on the index, the index doubles
- **Building many indexes "just in case"** — each one costs RAM and write throughput. Use `cb_index_advisor`
- **Assuming FTS is small** — it's typically 1-2x the source text, which can be substantial for text-heavy collections

## Quick decision tree

- **Sizing GSI?** `docs × (indexed_size + 80) × (1 + replicas)`
- **Sizing FTS?** `text_size × 1.5-2.5 (analyzer) × 1.0-2.0 (storage factor)`
- **Sizing vector?** `docs × dim × 4 (float32) × 1.4 (Composite) or 2.5 (Hyperscale)`
- **Sizing Eventing?** `functions × workers × 200-500 MB + base overhead`
- **Many indexes, expensive RAM?** Drop unused ones (check `last_used`); use index advisor
- **Vector index too large?** Reduce dimension, quantize if supported, or filter what you index
- **Analytics?** Plan dedicated nodes with 64+ GB RAM each
