# Diagnostics & query performance analysis

The `cb_perf_*` family and a handful of related tools answer "what's slow?" / "what's wrong?" questions. They don't change anything — all read-only — but they're the right starting point for any optimization or incident-response task.

## When to reach for diagnostics

- User says "queries are slow" / "the app is slow" / "Couchbase is slow"
- User asks "why is this query slow" (specific query) → use `cb_explain_query` (see `data-plane.md`) before `cb_perf_*`
- User asks "what should I index" → `cb_index_advisor` is the most direct answer
- User asks "what's in this collection" (exploratory) → `cb_get_schema_for_collection`
- User asks "who's hammering the database" → `cb_perf_by_user` (8.x only)

## The `cb_perf_*` family

Each tool returns the top N queries (default 10, configurable via `limit`) along the named dimension. The underlying data source is the system:completed_requests catalog — so it covers queries that the query service has logged. Long-running OR slow OR error queries are typically there; trivial subsecond queries may not be.

| Tool | Returns top N queries by… |
|---|---|
| `cb_perf_slowest_queries` | Maximum elapsed time |
| `cb_perf_longest_running` | (same as slowest, kept for clarity) |
| `cb_perf_most_frequent` | Execution count |
| `cb_perf_top_queries_by_count` | (alias for most_frequent) |
| `cb_perf_top_queries_by_elapsed` | Total elapsed time (count × avg) |
| `cb_perf_recent_query_failures` | Recently errored queries |
| `cb_perf_active_queries` | Currently executing queries |
| `cb_perf_large_response_sizes` | Result payload size in bytes |
| `cb_perf_large_result_count` | Number of result rows returned |
| `cb_perf_not_using_covering_index` | Queries that fetched docs from data service instead of being satisfied entirely by indexes |
| `cb_perf_using_primary_index` | Queries forced to scan the primary index (often a smell) |
| `cb_perf_not_selective` | Queries with low selectivity (returning a high fraction of scanned docs) |

For Couchbase 8.x clusters: `cb_perf_by_user` adds a per-user breakdown.

## Investigative workflow

A typical "find the worst offenders" walk:

1. **`cb_perf_top_queries_by_elapsed`** — gives the queries with the highest *total* time impact. A query that runs 10,000 times at 50ms is usually a bigger problem than one that runs once at 30 seconds.
2. **For each suspect, run `cb_explain_query`** — gets the plan, reveals whether it's using primary index, has covering-index gaps, etc.
3. **`cb_index_advisor`** with that query — gets the recommended index DDL.
4. **`admin_index_create`** with the recommended DDL, optionally `defer_build: true` if creating several at once.
5. **`admin_index_build`** at the end to actually build all deferred indexes in one pass.

## Index advisor

| Tool | What it does |
|---|---|
| `cb_index_advisor` | Returns suggested index DDL for a given SQL++ statement |

Pass a SQL++ statement; the advisor returns a list of `CREATE INDEX` recommendations sorted by estimated impact. The advisor considers:
- The WHERE clause predicates (which fields to index)
- The SELECT projection (whether the index can cover the query)
- Existing indexes (won't suggest duplicates)

It does NOT consider:
- Write throughput cost of the new index
- Disk space cost
- Whether the suggested index would compete with existing ones for the index service's memory budget

So treat the advisor's output as *candidates*, not commands. For each suggestion, ask:
- How often does this query actually run?
- How big is the collection (5K docs ≠ 50M docs)?
- Is there an existing index that's *almost* the right shape that could be extended instead?

## Schema inference

| Tool | What it does |
|---|---|
| `cb_get_schema_for_collection` | Samples documents from a collection and returns a flattened schema |

Output looks like:

```json
{
  "fields": [
    {"path": "id", "types": ["string"], "occurrence": 1.0},
    {"path": "user.name", "types": ["string"], "occurrence": 0.98},
    {"path": "user.age", "types": ["number"], "occurrence": 0.85},
    {"path": "addresses[]", "types": ["array"], "occurrence": 0.6}
  ],
  "sample_size": 100
}
```

`occurrence` is the fraction of sampled documents containing that field. Useful for:
- Understanding a new collection's shape before querying it
- Spotting schema drift (low-occurrence fields are usually accidental writes)
- Picking which fields to index

The default sample size is 100. Pass a larger `sample_size` for big collections where the shape varies widely.

## EXPLAIN

| Tool | What it does |
|---|---|
| `cb_explain_query` | Returns the query plan for a SQL++ statement (no execution) |

The plan is a tree of operators with cost estimates. The relevant pieces for diagnosis:

- **`#operator`**: the type of node (IndexScan, PrimaryScan, Fetch, Filter, Project, Order, etc.)
- **`index`** on an IndexScan: which index it's using. Missing → primary scan
- **`covers`**: array of field paths the index can serve without a Fetch. A query that doesn't need a Fetch is "covered"
- **`cardinality`** estimates: rows expected at each stage

**Red flags in plans:**
- A `PrimaryScan` near the root → no useful secondary index; advisor will suggest one
- A `Fetch` after `IndexScan` → index isn't covering; could extend it to cover
- A `Sort` not backed by an index → result set is being sorted in memory
- A `Nested Join` between large collections → likely missing a join key index

## "Active queries" — for real-time investigation

| Tool | What it does |
|---|---|
| `cb_perf_active_queries` | Currently running queries (snapshot) |

Useful during incidents to find specific runaway queries. If something is hammering the cluster *right now*, this returns the offenders mid-flight.

Output includes `requestId` — that's what `admin_query_settings` can target to cancel a specific query.

## Quick decision tree

- **"Queries are slow generally"** → `cb_perf_top_queries_by_elapsed` first, then drill into top offenders
- **"This specific query is slow"** → `cb_explain_query` then `cb_index_advisor`
- **"What indexes should I have?"** → `cb_index_advisor` on representative queries
- **"What's in this collection?"** → `cb_get_schema_for_collection`
- **"Who's running queries right now?"** → `cb_perf_active_queries`
- **"What queries failed recently?"** → `cb_perf_recent_query_failures`
- **"Why am I returning so much data?"** → `cb_perf_large_response_sizes` or `cb_perf_large_result_count`
- **"Why is this query doing a full scan?"** → `cb_perf_using_primary_index` (lists all candidates) or `cb_explain_query` (for one query)
- **"Per-user breakdown of query stats"** → `cb_perf_by_user` (8.x only)
