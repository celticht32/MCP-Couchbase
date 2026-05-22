# Couchbase 8.x specific features

These tools only work against Couchbase Server 8.0 or later. They fail loudly with a clear error message if invoked against a 7.x cluster — but it's better to check the server version first via `admin_cluster_status` if the user hasn't said which version they're on.

## Vector indexes (search-driven similarity)

Two flavors, both for indexing high-dimensional vector embeddings:

| Tool | When to pick it |
|---|---|
| `admin_vector_index_create_composite` | The default. Combines vector field with other scalar fields in one index. Cheaper, fits most workloads under ~10M vectors |
| `admin_vector_index_create_hyperscale` | For very large vector corpora (10M+ vectors) or when search latency on huge indexes is the bottleneck. More expensive in storage and index-build time, but scales further |

Both take the same core arguments:

```json
{
  "tool": "admin_vector_index_create_composite",
  "arguments": {
    "bucket_name": "my-bucket",
    "scope_name": "_default",
    "collection_name": "_default",
    "index_name": "idx_embeddings",
    "field_name": "embedding",
    "dimension": 1536,
    "similarity": "COSINE",
    "defer_build": false
  }
}
```

**Picking `similarity`:**
- `COSINE` — measures angle, ignores magnitude. Default for most semantic-search use cases with OpenAI / Voyage / Cohere embeddings
- `DOT_PRODUCT` — assumes vectors are already normalized; faster than COSINE if so
- `L2_SQUARED` — Euclidean distance squared. For embeddings where magnitude carries meaning (rare)

If unsure, use `COSINE` — it's what the popular embedding providers expect.

**Picking `dimension`:**
- OpenAI `text-embedding-3-small`: 1536
- OpenAI `text-embedding-3-large`: 3072 (or 1024 with `dimensions` param)
- Voyage `voyage-3`: 1024
- Cohere `embed-english-v3.0`: 1024

Get the dimension wrong and inserts fail at write time, not index-create time — so triple-check.

## Synonyms (FTS)

Couchbase 8.x adds the ability to define synonym groups that map terms together for full-text search (e.g., "automobile" / "car" / "vehicle" all match the same docs).

| Tool | What it does |
|---|---|
| `cb_fts_synonym_upsert` | Create or replace a synonym set document |
| `cb_fts_synonym_list` | List all synonym sets in a collection |
| `cb_fts_synonym_delete` | Delete a synonym set |

**Two-step setup:**

1. Create the synonym set document in a collection via `cb_fts_synonym_upsert`:

```json
{
  "tool": "cb_fts_synonym_upsert",
  "arguments": {
    "id": "vehicle_synonyms",
    "synonyms": ["car", "automobile", "vehicle", "auto"],
    "bucket": "search-data",
    "scope": "_default",
    "collection": "synonyms"
  }
}
```

2. Edit the FTS index definition to reference the synonym set via `admin_fts_index_update`. The synonym source is declared inside the index's `params.mapping.analysis.synonym_sources` map. See `cluster-admin.md` for the FTS index tools.

The synonym set documents live in your own collections — they're regular Couchbase documents. The FTS index references them by location.

## User lock / unlock and temporary users

Couchbase 8.x adds an account-state field to users, so admins can lock accounts without deleting them (e.g., for incident response).

| Tool | What it does |
|---|---|
| `admin_user_lock` | Lock a user — they can't authenticate until unlocked. **Requires `confirm: true`** |
| `admin_user_unlock` | Unlock a previously locked user |
| `admin_user_create_temporary` | Create a temporary user that auto-expires at a given timestamp |

**Temporary users:**

```json
{
  "tool": "admin_user_create_temporary",
  "arguments": {
    "username": "incident_responder_2026_05_21",
    "password": "<strong-password>",
    "roles": ["bucket_admin[*]"],
    "expires_at": "2026-05-22T00:00:00Z"
  }
}
```

The user is automatically deleted at `expires_at`. Useful for granting temporary debugging access during an incident without remembering to clean up.

## XDCR conflict log readback

Couchbase 8.x adds XDCR conflict logging — when a doc is updated in both clusters concurrently and the resolver picks one over the other, the loser can be persisted to a conflict log bucket for later review.

| Tool | What it does |
|---|---|
| `admin_xdcr_conflict_log_query` | Read the conflict log from the replication's conflict-log target |

This is read-only. The actual writing of conflict log entries is done by the XDCR machinery; this tool just lets you query the log to understand what was lost.

## DARE + KMIP (encryption at rest)

Couchbase 8.x supports Data-at-Rest Encryption (DARE) with optional KMIP integration for external key management.

| Tool | What it does | Read-only? |
|---|---|---|
| `admin_encryption_get` | Get current encryption settings | ✓ |
| `admin_encryption_set` | Enable / disable DARE for the cluster | ✗ |
| `admin_encryption_rotate` | Rotate the data encryption key | ✗ |
| `admin_encryption_status` | Per-bucket encryption state | ✓ |
| `admin_kmip_get` | Get KMIP server config | ✓ |
| `admin_kmip_set` | Configure KMIP integration | ✗ |
| `admin_kmip_test` | Test KMIP connectivity | ✓ |
| `admin_kmip_rotate` | Rotate the master KMIP key | ✗ |

**Enabling DARE is non-reversible at-scale:** Once a bucket is encrypted, decrypting requires a full rewrite. Surface this to the user before calling `admin_encryption_set`.

## Per-user query stats

| Tool | What it does |
|---|---|
| `cb_perf_by_user` | Get aggregate query stats broken down by authenticating user |

8.x exposes per-user query metrics that earlier versions did not. Useful for "who's running the slow queries?" — the response groups call counts, total CPU, and total elapsed time by user.

## How these tools handle being called against a 7.x cluster

All of the above call into 8.x-specific REST endpoints. If the cluster is running 7.x, the underlying request returns 404 and the tool surfaces this with a message like:

```json
{
  "ok": false,
  "error": "This tool requires Couchbase Server 8.0 or later; the connected cluster reports version 7.6.2",
  "hint": "Upgrade the cluster or use the 7.x-compatible workflow"
}
```

This is intentional — it's better to fail clearly than to silently produce wrong results. If you see this error, check `admin_cluster_status` to confirm the version, then either tell the user to upgrade or use a different approach.

## Quick decision tree

- **"Create a vector index"** → `admin_vector_index_create_composite` (or Hyperscale for huge corpora)
- **"Set up synonyms for FTS"** → `cb_fts_synonym_upsert` then `admin_fts_index_update`
- **"Lock a user account (incident response)"** → `admin_user_lock`
- **"Create a temp account for a contractor"** → `admin_user_create_temporary`
- **"Read XDCR conflict log"** → `admin_xdcr_conflict_log_query`
- **"Enable encryption at rest"** → `admin_encryption_set` (after explaining the impact)
- **"Set up external KMIP"** → `admin_kmip_set` then `admin_kmip_test`
- **"Rotate encryption keys"** → `admin_encryption_rotate` or `admin_kmip_rotate`
- **"Find which user is running the slow queries"** → `cb_perf_by_user`
