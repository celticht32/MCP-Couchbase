# Data plane — `cb_*` tools

The `cb_*` family operates on documents, query results, and search indexes. All of these require `CB_CONNECTION_STRING`, `CB_USERNAME`, and `CB_PASSWORD` to be set, and most respect `CB_BUCKET` / `CB_SCOPE` / `CB_COLLECTION` as defaults.

## KV (key-value) operations

The simplest and fastest way to read/write a document.

| Tool | What it does | Read-only? |
|---|---|---|
| `cb_ping` | Verify SDK + service connectivity. Run this first when troubleshooting | ✓ |
| `cb_get` | Get a single document by ID. Returns the full document or an error | ✓ |
| `cb_get_multi` | Batch get — pass a list of IDs, get back a map of ID → document | ✓ |
| `cb_upsert` | Insert or replace a document by ID. Idempotent | ✗ |
| `cb_insert` | Insert a new document. Fails if the ID already exists | ✗ |
| `cb_replace` | Replace an existing document. Fails if the ID doesn't exist | ✗ |
| `cb_delete` | Delete a document by ID. **Destructive.** Requires `confirm: true` | ✗ |

**When to use upsert vs insert vs replace:** Use `cb_upsert` for "write this regardless of current state." Use `cb_insert` when you want to fail loudly on accidental overwrites (e.g., new-user registration where uniqueness matters). Use `cb_replace` when you want to fail if the record doesn't exist (e.g., update flow where you've already confirmed existence).

**Typical call:**

```json
{
  "tool": "cb_upsert",
  "arguments": {
    "id": "user_42",
    "value": {"name": "Alice", "tier": "gold"},
    "bucket": "users",
    "scope": "_default",
    "collection": "_default"
  }
}
```

If `bucket` / `scope` / `collection` are omitted, the env-var defaults apply.

## Subdocument operations

For modifying a single field inside a large document without serializing/deserializing the whole thing. Much cheaper than `cb_get` + `cb_replace` for field-level changes.

| Tool | What it does |
|---|---|
| `cb_lookup_in` | Read specific paths inside a document (e.g., just `user.address.zip`) |
| `cb_mutate_in` | Modify specific paths inside a document (set, remove, increment, array_append, etc.) |

**`cb_lookup_in` example:**

```json
{
  "tool": "cb_lookup_in",
  "arguments": {
    "id": "user_42",
    "specs": [
      {"op": "get", "path": "name"},
      {"op": "exists", "path": "tier"},
      {"op": "count", "path": "addresses"}
    ]
  }
}
```

**`cb_mutate_in` example:**

```json
{
  "tool": "cb_mutate_in",
  "arguments": {
    "id": "user_42",
    "specs": [
      {"op": "upsert", "path": "lastLogin", "value": "2026-05-21T10:00:00Z"},
      {"op": "increment", "path": "loginCount", "value": 1},
      {"op": "array_append", "path": "history", "value": "2026-05-21"}
    ]
  }
}
```

Supported `mutate_in` ops: `upsert`, `insert`, `replace`, `remove`, `array_append`, `array_prepend`, `array_insert`, `array_add_unique`, `increment`, `decrement`. Maximum 16 specs per call.

## SQL++ (N1QL) queries

For anything that isn't a single-doc-by-ID lookup.

| Tool | What it does | Read-only? |
|---|---|---|
| `cb_query` | Run a SQL++ statement against the cluster | Depends on statement |
| `cb_explain_query` | Get the query plan for a SQL++ statement. Use BEFORE optimizing a slow query | ✓ |
| `cb_get_schema_for_collection` | Infer the schema (field paths + types) of a collection from a sample of documents | ✓ |

**Read-only mode and queries:** If `CB_MCP_READ_ONLY_MODE=true` is set, `cb_query` blocks any statement that modifies data (UPDATE / INSERT / DELETE / UPSERT). SELECTs and EXPLAINs still work.

**EXPLAIN before optimizing:** When asked "why is this query slow?", run `cb_explain_query` first. The plan reveals primary-index scans (typically the slowness culprit), missing covering indexes, and unusual join shapes. Then use `cb_index_advisor` (see `diagnostics.md`) to get suggested index DDL.

**Schema inference for unknown data:** `cb_get_schema_for_collection` is the right tool when the user asks "what's in this collection?" — it samples documents and returns a flattened schema. Much more concise than running `SELECT * LIMIT 5` and asking the user to interpret it.

## Full-text search

| Tool | What it does | Read-only? |
|---|---|---|
| `cb_fts_search` | Run a full-text search query against an FTS index. Returns ranked results with scores | ✓ |

For administrative operations on FTS indexes (create, delete, edit definition), use the `admin_fts_*` tools — see `cluster-admin.md`.

For synonyms (8.x feature), see `couchbase-8x.md`.

## Analytics queries

| Tool | What it does | Read-only? |
|---|---|---|
| `cb_analytics_query` | Run a query against the Analytics service (separate from N1QL/Query service) | ✓ |

The Analytics service is a separate cluster service designed for ad-hoc analytical workloads. It uses the same SQL++ dialect but runs against shadow datasets — so it doesn't compete with the operational Query service for resources. Use it for long-running aggregations and joins that would impact OLTP performance.

## Transactions (multi-document ACID)

| Tool | What it does |
|---|---|
| `cb_transaction_run` | Execute a multi-step transaction atomically. Either all operations commit or all roll back |

**Call shape:**

```json
{
  "tool": "cb_transaction_run",
  "arguments": {
    "operations": [
      {"op": "get", "id": "account_a"},
      {"op": "get", "id": "account_b"},
      {"op": "replace", "id": "account_a", "value": {...}},
      {"op": "replace", "id": "account_b", "value": {...}}
    ]
  }
}
```

The handler resolves dependencies and commits atomically. If any operation fails, the entire transaction rolls back and returns an error explaining which step caused the failure.

Transactions are slower than equivalent KV operations (about 3-5x for typical loads) because they involve two-phase commit. Use them only when atomicity actually matters.

## Quick decision tree

- **"I need to read one document by ID"** → `cb_get`
- **"I need to read many documents by ID"** → `cb_get_multi`
- **"I need to read certain fields of a document"** → `cb_lookup_in`
- **"I need to update a field inside a doc"** → `cb_mutate_in`
- **"I need to write a whole document"** → `cb_upsert` / `cb_insert` / `cb_replace`
- **"I need to query across documents"** → `cb_query` (SQL++)
- **"I need a search-engine-style query"** → `cb_fts_search`
- **"I need an analytical query that doesn't impact OLTP"** → `cb_analytics_query`
- **"I need atomicity across multiple docs"** → `cb_transaction_run`
- **"I want to understand the schema"** → `cb_get_schema_for_collection`
- **"I want to see why a query is slow"** → `cb_explain_query`, then read `diagnostics.md`
