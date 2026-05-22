# Migrating from MongoDB

MongoDB-to-Couchbase is the most common document-database migration to Couchbase. Both are JSON document stores, so the shape translates relatively directly — but there are real differences in modeling, query language, indexing, and operational primitives that need handling.

## Concept mapping

| MongoDB | Couchbase | Notes |
|---|---|---|
| Cluster | Cluster | Roughly equivalent |
| Database | Bucket | MongoDB databases are namespaces; buckets are heavier (own memory budget) |
| Collection | Collection (in `_default` scope) | OR a Couchbase scope+collection for finer organization |
| Document | Document | JSON in both |
| `_id` field | Document key | MongoDB auto-generates ObjectId; Couchbase uses any string |
| Index | GSI index | Different syntax (N1QL CREATE INDEX vs MongoDB createIndex) |
| Replica Set | Cluster with replicas | Couchbase replicates via vBuckets, not replica sets per se |
| Sharding | Built-in (vBuckets) | No manual shard key needed; vBuckets auto-distribute |
| Change Streams | Eventing functions | Server-side reactions to mutations |
| `find()` | KV `get` or N1QL `SELECT` | Pick KV when filtering by `_id`; N1QL otherwise |
| Aggregation pipeline | N1QL with subqueries / Analytics service | N1QL covers most aggregation needs |
| `$lookup` (joins) | N1QL JOIN, or denormalization | N1QL JOINs are real but slower than denormalized reads |
| `gridFS` (binary blobs) | Not directly supported | Store binaries in object storage; references in Couchbase |
| Transactions | `cb_transaction_run` | Couchbase transactions are stronger (ACID across docs) |

## Schema differences worth flagging

**MongoDB's `_id` is an `ObjectId` by default.** Couchbase document keys are strings. The mapping options:

1. **Use `_id.toString()` as the Couchbase key** — straightforward, opaque
2. **Use a more meaningful key derived from the document** — e.g., `user::<email>` instead of `user::507f1f77bcf86cd799439011`. Better for debugging

For migrations preserving identity (existing references in other systems), use option 1. For new applications building on top of the migration, option 2 is more operable.

**MongoDB's flexible-schema reality:** the same collection can have wildly varying document shapes if discipline wasn't enforced. Before migrating, run a schema audit:

```javascript
// In MongoDB
db.users.aggregate([{ $sample: { size: 1000 } }, { $project: { keys: { $objectToArray: "$$ROOT" }}}, {$unwind: "$keys"}, {$group: { _id: "$keys.k", count: { $sum: 1 }}}])
```

The output is "for a 1000-doc sample, here's how often each field appears." Fields with low occurrence are usually accidental — decide whether to keep or drop.

For Couchbase, run `cb_get_schema_for_collection` (via the `couchbase-mcp` skill) post-migration to verify the actual schema matches expectations.

## Tooling for MongoDB → Couchbase

### One-shot migration: `mongoexport` + cbimport

```bash
# Step 1: Export from MongoDB
mongoexport \
    --uri="mongodb://source-host:27017/mydb" \
    --collection=users \
    --out=users.jsonl

# Step 2: (Optional) transform — adjust field names, key format, etc.
# E.g., a quick Python script that reads users.jsonl and writes transformed.jsonl

# Step 3: Import to Couchbase
cbimport json \
    --cluster couchbases://cb.example.com \
    --username Administrator \
    --password "..." \
    --bucket app_data \
    --scope-collection-exp _default.users \
    --format lines \
    --dataset file://transformed.jsonl \
    --generate-key "user::%_id%" \
    --threads 8
```

mongoexport writes JSON lines (one doc per line); cbimport reads them directly with `--format lines`.

**Key generation:** `%_id%` substitutes the document's `_id` field into the Couchbase key. If the document has `_id: ObjectId("...")`, the resulting key is `user::ObjectId("...")` — usually you want to convert this to a string first in the transform step.

### Ongoing sync: Debezium MongoDB connector

For zero-downtime migrations, Debezium's MongoDB source connector reads from the MongoDB oplog (or change streams) and emits to Kafka. A Couchbase sink consumes Kafka and writes to the target.

**Setup outline:**

```
[MongoDB] --[oplog]--> [Debezium MongoDB connector] --> [Kafka topic]
                                                            |
                                                            v
                                            [Couchbase Kafka Connector]
                                                            |
                                                            v
                                                       [Couchbase]
```

Connector configs are JSON; the Debezium docs at https://debezium.io/documentation/ have current schema. Plan a week minimum to get this stable.

### MongoDB to Couchbase using MongoDB Sync Connector

Some commercial tools (Striim, others) offer direct MongoDB-to-Couchbase sync without the Kafka intermediate. Less ops surface but commercial cost.

## Modeling considerations

The temptation: "MongoDB documents are JSON, Couchbase documents are JSON, just dump them across." This works as a starting point but often misses Couchbase-specific optimization opportunities.

**Things to consider during migration (cross-reference `couchbase-data-modeling` skill):**

1. **Embedded vs referenced** — MongoDB conventions may have over-embedded (huge user docs with all their activity) or over-referenced (small docs requiring many JOINs). The migration is a chance to fix this
2. **Key design** — MongoDB ObjectIds are opaque. Better keys (`user::<email>` or ULIDs with type prefixes) help operability
3. **Scopes & collections** — if MongoDB's "database" was being used as a tenant boundary, consider mapping to Couchbase scopes
4. **TTL on ephemeral docs** — Couchbase has per-document and per-collection TTL; MongoDB has document-level expiration. Translates directly but worth confirming the TTL logic
5. **Indexes** — every MongoDB index doesn't necessarily need a Couchbase index. Use `cb_index_advisor` (via `couchbase-mcp` skill) on representative queries to find what's needed

## Query translation

MongoDB queries don't translate 1:1 to N1QL. Common patterns:

### Find by ID

```
// MongoDB
db.users.findOne({_id: ObjectId("...")})
```

```sql
-- Couchbase via KV (preferred — single round-trip, very fast)
-- Just call cb_get with the key "user::<id>"

-- Couchbase via N1QL (works but slower)
SELECT * FROM users WHERE META().id = "user::<id>"
```

### Filter by field

```
// MongoDB
db.users.find({tier: "gold"})
```

```sql
-- Couchbase
SELECT * FROM users WHERE tier = "gold"
```

Requires a GSI index on `tier` (`CREATE INDEX ix_users_tier ON users(tier)`).

### Aggregation

```
// MongoDB
db.orders.aggregate([
  { $match: { status: "complete" }},
  { $group: { _id: "$customer_id", total: { $sum: "$amount" }}},
  { $sort: { total: -1 }},
  { $limit: 10 }
])
```

```sql
-- Couchbase N1QL
SELECT customer_id, SUM(amount) AS total
FROM orders
WHERE status = "complete"
GROUP BY customer_id
ORDER BY total DESC
LIMIT 10
```

Cleaner in N1QL since it's SQL-like.

### Joins (MongoDB `$lookup`)

```
// MongoDB
db.orders.aggregate([
  { $lookup: {
      from: "users",
      localField: "user_id",
      foreignField: "_id",
      as: "user"
  }}
])
```

```sql
-- Couchbase N1QL
SELECT o.*, u.name AS user_name
FROM orders o
JOIN users u ON o.user_id = META(u).id
```

JOINs work in Couchbase but consider denormalization if this is a hot path — see `couchbase-data-modeling` skill.

### Text search

```
// MongoDB (with text index)
db.products.find({$text: {$search: "wireless mouse"}})
```

```
// Couchbase (with FTS index)
// Via cb_fts_search tool — see couchbase-mcp skill's data-plane.md
```

FTS is more flexible than MongoDB text search (better fuzzy matching, language support, custom analyzers, vector + text hybrid in 8.x).

### Change Streams

```
// MongoDB
const changeStream = db.users.watch();
changeStream.on('change', (change) => { ... });
```

```
// Couchbase
// Use Eventing functions (server-side JS) instead — see couchbase-mcp skill
// Functions react to mutations and can write to other collections, call HTTP endpoints, etc.
```

Couchbase Eventing is more powerful than change streams (can transform, filter, fan out) but server-side. If your app needs to react to changes in app code, use the DCP protocol via the SDK (advanced).

## Transactions

MongoDB has multi-document transactions in replica sets and sharded clusters (4.0+).
Couchbase has distributed ACID transactions via `cb_transaction_run` and the SDK transactions library.

Both work similarly: begin → operations → commit/abort. Code patterns translate; specific API differs by SDK. See `couchbase-app-integration` skill's `transactions-app-side.md` for the Couchbase patterns.

## Operational differences

| Concern | MongoDB | Couchbase |
|---|---|---|
| Connection from app | mongoose / native driver | Couchbase SDK (see `couchbase-app-integration`) |
| User management | createUser / grantRolesToUser | `admin_user_*` tools (see `couchbase-mcp`) |
| Backup | mongodump / Atlas backups | `admin_backup_*` tools |
| Monitoring | Atlas / Cloud Manager | `admin_stats_*` + Prometheus (see `couchbase-mcp`'s `observability.md`) |
| Sharding | Manual shard key | Automatic via vBuckets |
| Replication | Replica sets | Built-in (1-3 replicas per bucket) |

## Common MongoDB-to-Couchbase migration pitfalls

- **Treating ObjectId as a magic key:** Couchbase keys are just strings. Define a key naming convention; don't carry ObjectId opacity forward unless you have to
- **Keeping MongoDB's `_id` field in the document body:** redundant. Couchbase key IS the access path. You can store it in the body for queries via `META().id`, but don't keep the MongoDB-style `_id` field by reflex
- **Translating every MongoDB index to a Couchbase index:** MongoDB collections often have many indexes that aren't used. Profile queries on the new system; build only what's needed
- **Using N1QL for everything:** if your access pattern is "get by ID," `cb_get` (KV) is much faster than N1QL. Use N1QL when filtering / aggregating
- **Ignoring scopes and collections:** Couchbase 7+ has scopes and collections that let you organize data within a bucket. MongoDB doesn't have an equivalent of scopes; consider using them during migration

## A typical MongoDB migration timeline

For a moderate MongoDB-to-Couchbase migration (10-100 GB):

| Phase | Duration | Activities |
|---|---|---|
| Planning | 1-2 weeks | Schema audit, modeling decisions, sizing, approach |
| Tooling setup | 3-5 days | Test mongoexport + cbimport on sample data |
| Dry run | 1 week | Migrate 10% sample to staging; validate; iterate |
| Schema iteration | 1-2 weeks | Adjust target model based on findings |
| Staging migration | 1 week | Full migration to staging; full validation |
| Dual-write or CDC setup | 1-2 weeks | If zero-downtime; Debezium + Kafka path |
| Soak period | 2-4 weeks | Both DBs in sync; validate continuously |
| Cutover | 1 day | Switch app traffic |
| Soak post-cutover | 2-4 weeks | MongoDB still running, read-only |
| Decommission | 1 day | Retire MongoDB |

Total: 8-16 weeks for production-grade migrations.

## Quick decision tree

- **One-shot migration with downtime?** → mongoexport + transform + cbimport
- **Zero-downtime migration?** → Debezium MongoDB connector + Couchbase Kafka sink
- **Want to preserve ObjectId keys?** → use `%_id%` template in cbimport, but consider whether you really want opaque keys
- **MongoDB Atlas?** → Same migration path; use Atlas's mongoexport equivalent or set up CDC against Atlas's change streams
- **Need to keep both running for a while?** → dual-write at the app layer + Debezium for backfill; or just Debezium for ongoing sync without app changes
- **Schema audit reveals chaos?** → migration is a great time to clean it up; use a transform step
- **Lots of $lookup joins in current app?** → consider denormalization during migration; reads will be much faster
