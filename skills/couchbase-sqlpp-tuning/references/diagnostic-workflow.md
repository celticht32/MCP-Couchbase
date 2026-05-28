# Diagnostic workflow

How to use the MCP server's tools in this project to find, diagnose, and fix slow queries. This is the operational complement to the conceptual references.

The MCP server in this project (`celticht32/MCP-Couchbase`) exposes the tuning tools needed for the full workflow. All tools are read-only by default — they don't mutate the cluster.

## The five-step loop

```
1. FIND          →  cb_perf_*        — Top slow queries
2. UNDERSTAND    →  cb_explain_query — EXPLAIN + parsed findings
3. RECOMMEND     →  cb_index_advisor — ADVISE statement
4. CREATE        →  admin_index_create (writes, gated by confirm:true)
5. VERIFY        →  cb_explain_query + cb_query with profile
```

Read-only mode (default) blocks step 4. Disable it for the index-creation step only, then re-enable.

## Step 1 — Find the slow queries (Pareto)

80% of perf problems come from 20% of queries. Find that 20% first.

```
Tool: cb_perf_longest_running
Args: {"limit": 20}
```
Returns the top N queries by elapsed time, with statement, average duration, and count.

```
Tool: cb_perf_most_frequent
Args: {"limit": 20}
```
Returns the top N by invocation count. Tuning a 0.1s query that runs 100/sec saves more than tuning a 10s query that runs once/hour.

```
Tool: cb_perf_using_primary_index
```
Anything in this list is a high-priority fix — every entry is doing a full-keyspace scan.

```
Tool: cb_perf_not_using_covering_index
```
Queries doing IndexScan + Fetch — candidates for promotion to a covering index.

```
Tool: cb_perf_not_selective
```
Queries where the WHERE filter doesn't narrow the result set much. Often signals a wrong index or a missing predicate.

```
Tool: cb_perf_by_user           (Couchbase 8.x only)
```
Attributes slow queries to specific user accounts — useful for finding the "one team is running a bad query" case.

Sort the combined list by **(avg_duration × frequency)** to get the actual top-priority queries.

## Step 2 — Understand the plan

For each query from step 1:

```
Tool: cb_explain_query
Args: {"statement": "SELECT name FROM hotel WHERE state = 'CA'"}
```

Returns the EXPLAIN output plus a parsed findings block that flags common issues:
- `has_primary_scan: true` → ❌ uses PrimaryScan
- `has_intersect_scan: true` → ⚠ IntersectScan present
- `has_fetch: true` + `covers_count: 0` → ⚠ not covered
- `indexes_used: [...]` → which indexes the optimizer picked

Read the plan structure as described in `explain-plan.md`. The parsed findings give you a quick read; the full plan is for confirming hypotheses.

## Step 3 — Get an index recommendation

```
Tool: cb_index_advisor
Args: {"statement": "SELECT name FROM hotel WHERE state = 'CA'"}
```

This runs `ADVISE <statement>` against the cluster. Output includes:
- `recommended_indexes` — what to create
- `current_indexes` — what exists that could be used
- `recommended_covering_indexes` — if covering would help
- `recommended_partial_indexes` — if a low-cardinality predicate is present

ADVISE is conservative — it recommends the minimum index that would help. If you have multiple queries that could share a wider composite index, you might do better designing manually (see `index-design.md`).

If ADVISE doesn't recommend anything, the query is already optimal for the existing index set, OR the query has no usable index pattern (e.g., it's `SELECT * FROM keyspace` with no WHERE).

## Step 4 — Create the index

The MCP server has read-only mode ON by default. To create the index:

**Option A: temporarily disable read-only mode**

```bash
# Restart the MCP server with read-only mode off
CB_MCP_READ_ONLY_MODE=false uv run server.py
```

```
Tool: admin_index_create
Args: {
  "statement": "CREATE INDEX idx_state_name ON hotel(state, name)",
  "confirm": true
}
```

The `confirm: true` is required for write tools. The handler validates that the statement is actual index DDL — it rejects arbitrary SQL++.

**Option B: run it directly through the SDK or workbench**

Some operators prefer to do index creation outside the MCP server entirely, keeping the MCP server read-only at all times. Both are valid.

## Step 5 — Verify

Re-run cb_explain_query to confirm the new index is picked:

```
Tool: cb_explain_query
Args: {"statement": "SELECT name FROM hotel WHERE state = 'CA' AND name = 'Hilton'"}
```

Look for:
- The new index name in `indexes_used`
- `has_primary_scan: false`
- `has_intersect_scan: false`
- `has_fetch: false` if you built a covering index

Then run the query with profile to confirm real-world improvement:

```
Tool: cb_query
Args: {
  "statement": "SELECT name FROM hotel WHERE state = 'CA' AND name = 'Hilton'",
  "profile": "timings"
}
```

Returns results plus a profile section with `kernTime`, `servTime`, `execTime` per operator. Compare against the baseline you captured in step 1.

## A worked example

User reports: "The hotel-search page is slow."

```
1. cb_perf_longest_running {limit: 10}
   → Top result: "SELECT name, country FROM hotel WHERE state = $1 AND city = $2"
                 avg 1.8s, runs 240/min

2. cb_explain_query
   → Plan: PrimaryScan3 (hotel_primary), Fetch, Filter, InitialProject
   → Findings: has_primary_scan: true, covers_count: 0

3. cb_index_advisor
   → Recommended: CREATE INDEX adv_state_city
                    ON hotel(state, city)
   → Recommended covering: CREATE INDEX adv_state_city_cover
                             ON hotel(state, city, name, country)

4. Choose the covering variant (the query is hot enough to justify it)
   → admin_index_create with the covering DDL, confirm: true

5. cb_explain_query (re-run on same statement)
   → Plan: IndexScan3 (adv_state_city_cover) with covers=[state, city, name, country]
   → Findings: has_primary_scan: false, covers_count: 4, has_fetch: false

   cb_query with profile=timings
   → New runtime: 12ms (was 1800ms). servTime on scan now dominant, no Fetch.
```

Done. Move to the next query in the Pareto list.

## When to look at system:completed_requests directly

The `cb_perf_*` tools are pre-canned views. Sometimes you need to ask a custom question, like "find queries that hit `idx_old_thing` so I can drop it":

```sql
SELECT statement, COUNT(*) AS hits
FROM system:completed_requests
WHERE preparedText LIKE '%idx_old_thing%'
   OR ANY plan IN ARRAY plans WITHIN ~child SATISFIES plan = 'idx_old_thing' END
GROUP BY statement
ORDER BY hits DESC;
```

The MCP server's `cb_query` tool can run this directly (read-only mode allows SELECT against system catalogs).

## Schema inference

Before designing an index, you need to know the document shape. The schema isn't enforced — it's discovered.

```
Tool: cb_get_schema_for_collection
Args: {
  "bucket_name": "travel-sample",
  "scope_name": "inventory",
  "collection_name": "hotel",
  "sample_size": 1000
}
```

Returns a unioned schema: every field that appears in the sampled docs, with its type and a sample value. Use it to confirm field names before writing the CREATE INDEX statement (typos in field names produce silently-empty indexes).

## Continuous monitoring

For ongoing operations, run a weekly review:

1. `cb_perf_longest_running` — has anything new slipped in?
2. `cb_perf_using_primary_index` — should always be empty in prod
3. `cb_perf_not_using_covering_index` — review the top entries; promote to covering if they're hot
4. Drop indexes that don't appear in any plan over the past month — they're costing memory and write throughput for nothing

A simple cron + the MCP server can capture this and email a digest.

## What to do next

- Don't know what plan you're looking at → `explain-plan.md`
- Don't know what index to recommend → `index-design.md`
- Don't know what's wrong with the query → `query-patterns.md`
- CBO-specific question → `cost-based-optimizer.md`
- Pagination-specific question → `pagination.md`
