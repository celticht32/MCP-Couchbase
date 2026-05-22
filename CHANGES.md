# CHANGES — Phases 1–3 Hardening

This drop-in replaces upstream `celticht32/MCP-Couchbase` with the same tool
surface (every original tool name is preserved) plus safety, engineering, and
transport improvements. Existing Claude Desktop configurations continue to
work; the new behavior is opt-out for safety.

---

## Phase 1 — Safety (defense-in-depth)

### Read-only mode (default ON)
- New env var `CB_MCP_READ_ONLY_MODE` (default `true`).
- When on, write tools are **not loaded at all**. Listing `tools/list` returns
  only read-only tools. `cb_query` stays loaded but blocks DML internally and
  forces the SDK `read_only=true` flag.
- Set `CB_MCP_READ_ONLY_MODE=false` to expose writes.

### Disabled-tools list
- `CB_MCP_DISABLED_TOOLS` — comma-separated tool names, or a path to a file
  with one name per line. Listed tools are unloaded at startup.

### Confirmation gate on destructive tools
- Every tool whose annotation is `destructiveHint=true` (deletes, drops,
  failovers, rebalance start/stop, hard memory changes, internal settings
  writes) now requires an explicit `confirm: true` argument.
- Without `confirm: true`, the tool returns a structured error telling the
  caller to retry with confirmation.
- `CB_MCP_CONFIRMATION_REQUIRED_TOOLS` adds more tools to this list (same
  format as disabled list).
- The `confirm` key is stripped before reaching REST/SDK calls.

### MCP tool annotations everywhere
- Every tool now carries `ToolAnnotations(readOnlyHint, destructiveHint,
  idempotentHint)`. MCP clients that surface these (Claude Desktop, Inspector)
  will show appropriate badges.

### Hardcoded credentials removed
- Upstream silently defaulted to `Administrator` / `password` when env vars
  were unset. The hardened server now raises at startup if `CB_USERNAME` or
  `CB_PASSWORD` is missing **and** mTLS is not configured.

### Index DDL validation
- `admin_index_create`'s raw `statement` parameter previously accepted any
  SQL++. It now only accepts statements beginning with
  `CREATE INDEX`, `CREATE PRIMARY INDEX`, `CREATE [HYPERSCALE|COMPOSITE] VECTOR INDEX`,
  or `BUILD INDEX`. Other SQL++ is rejected with an actionable error.
- `admin_index_drop` similarly restricted to `DROP INDEX` / `DROP PRIMARY INDEX` /
  `DROP VECTOR INDEX`.
- All identifier interpolation (bucket / scope / collection / index name)
  now goes through a backtick-quoting helper that escapes embedded backticks.

### SQL++ DML detection
- `cb_query` parses the leading keyword (ignoring comments and whitespace).
  In read-only mode, `INSERT`, `UPSERT`, `UPDATE`, `DELETE`, `MERGE`, `CREATE`,
  `DROP`, `BUILD`, `ALTER`, `GRANT`, `REVOKE`, and `EXECUTE` are blocked.

---

## Phase 2 — Engineering fixes

### Retries with exponential backoff
- `admin_request` now retries on HTTP 408, 425, 429, 500, 502, 503, 504 and
  on transient `URLError`. Default 3 attempts, base 0.5s, doubling.
- Configurable via `CB_MCP_HTTP_RETRIES` and `CB_MCP_HTTP_TIMEOUT`.

### Unified admin client
- Upstream had `admin_sample_buckets_install` calling `urllib` directly with
  its own auth header — diverged from `admin_request`. It now routes through
  `admin_request_json`. Same for all FTS index and stats endpoints needing
  JSON bodies.
- `admin_request_json` is now a thin shim over `admin_request(json_body=True)`.

### URL encoding consolidation
- Query parameters are encoded inside `admin_request` only. Callers never
  encode again. XDCR replication IDs are encoded inside `xdcr.py`'s
  `_enc_rep_id` helper rather than expecting the caller to encode.

### Structured error responses
- Handlers no longer raise from inside `handle()`. They wrap in `try/except`
  and return `err(message, tool=..., args=...)`. The error JSON now includes
  the offending tool name and arguments for diagnosis.

### Cluster version detection
- Lazy first-call query to `/pools` caches `implementationVersion`.
- `is_8x()`, `is_7x()`, `is_version_at_least(major, minor)` helpers are
  available for future tools that need version gating (e.g. vector indexes,
  user lock/unlock, DARE/KMIP coming in Phase 5).

---

## Phase 3 — Auth & transport

### mTLS
- New env vars `CB_CLIENT_CERT_PATH`, `CB_CLIENT_KEY_PATH`, `CB_CA_CERT_PATH`.
- When both client cert and key are set:
  - The Couchbase SDK uses `CertificateAuthenticator` (so the data plane is
    mTLS-authenticated).
  - The HTTP admin client builds an `ssl.SSLContext` with the client cert
    chain. **Basic auth header is omitted** when mTLS is active (auth happens
    at the TLS layer).
- `CB_CA_CERT_PATH` is honored even without client certs, for self-signed
  cluster certs.
- `CB_MCP_TLS_INSECURE=true` disables TLS verification (development only).

### Streamable HTTP transport
- New env var `CB_MCP_TRANSPORT` (default `stdio`). Set to `http` to expose
  the server over Streamable HTTP at `CB_MCP_HOST`:`CB_MCP_PORT`/mcp.
- HTTP mode requires `uvicorn` + `starlette` (optional in `requirements.txt`).
  If they aren't installed, the server prints a warning and falls back to
  stdio.
- **Warning**: HTTP mode has no built-in authorization. Deploy behind a
  reverse proxy or restrict to an authenticated network.

---

## Phase 4 — Official-MCP coverage gaps (schema, advisor, EXPLAIN, query perf)

Adds 10 tools that fill the gap between this MCP and the official `Couchbase-Ecosystem/mcp-server-couchbase`. All new tools live in `handlers/diagnostics.py`, are loaded in both read-only and read-write mode, and have `readOnlyHint=true` (none mutate the cluster).

### Schema discovery

- `cb_get_schema_for_collection` — samples N documents (default 100) from a collection, extracts every field via `OBJECT_PAIRS()`, returns a per-field type histogram and total occurrences. Equivalent to the official MCP's `get_schema_for_collection`.

### Index advisor

- `cb_index_advisor` — wraps the `ADVISOR()` SQL++ function. Pass an array of statements, get recommended indexes. Equivalent to `get_index_advisor_recommendations`.

### EXPLAIN with parsed findings

- `cb_explain_query` — runs EXPLAIN on a statement, then walks the plan tree to extract: operators used, indexes referenced, presence of `PrimaryScan`, presence of `Fetch` (non-covering signal), presence of `Filter` after a scan (pushdown failure). Returns both the raw plan and a human-readable findings list. Equivalent to `explain_sql_plus_plus_query`.

### Query performance analyzers

All six wrap `system:completed_requests` queries with the appropriate ordering/filtering:

- `cb_perf_longest_running` — by `elapsedTime` DESC. Equivalent to `get_longest_running_queries`.
- `cb_perf_most_frequent` — grouped by statement, by count DESC. Equivalent to `get_most_frequent_queries`.
- `cb_perf_largest_responses` — by `resultSize` DESC. Equivalent to `get_queries_with_largest_response_sizes`.
- `cb_perf_large_result_count` — `resultCount > threshold`. Equivalent to `get_queries_with_large_result_count`.
- `cb_perf_using_primary_index` — uses the `~phaseOperators` field when available; falls back to EXPLAIN-per-statement if that field is absent on this Couchbase version. Equivalent to `get_queries_using_primary_index`.
- `cb_perf_not_using_covering_index` — pulls recent SELECT queries, EXPLAINs each, flags any whose plan contains `Fetch`. Equivalent to `get_queries_not_using_covering_index`.
- `cb_perf_not_selective` — uses `~phaseCounts` to find queries where scan count >> result count (default `min_scan_count=1000`, `max_ratio=0.1`). Equivalent to `get_queries_not_selective`.

### Naming convention

The new tools use the `cb_` prefix (consistent with existing data-plane tools like `cb_query`, `cb_get`) plus a domain stem. The official-MCP equivalents are noted in each tool's description for easy migration. Mapping table:

| Official MCP | This MCP |
|---|---|
| `get_schema_for_collection` | `cb_get_schema_for_collection` |
| `get_index_advisor_recommendations` | `cb_index_advisor` |
| `explain_sql_plus_plus_query` | `cb_explain_query` |
| `get_longest_running_queries` | `cb_perf_longest_running` |
| `get_most_frequent_queries` | `cb_perf_most_frequent` |
| `get_queries_with_largest_response_sizes` | `cb_perf_largest_responses` |
| `get_queries_with_large_result_count` | `cb_perf_large_result_count` |
| `get_queries_using_primary_index` | `cb_perf_using_primary_index` |
| `get_queries_not_using_covering_index` | `cb_perf_not_using_covering_index` |
| `get_queries_not_selective` | `cb_perf_not_selective` |

### What this means for tool counts

- Total tools: **105 → 115** (10 new).
- Loaded in read-only mode: **46 → 56** (all 10 new tools are read-only).
- Confirmation-required tools: unchanged (still 21 in read-write mode).

### Version-portability notes

Field names in `system:completed_requests` evolve across Couchbase versions. Two tools handle this defensively:

- `cb_perf_using_primary_index` first tries `~phaseOperators`. If the query fails (field absent), it falls back to EXPLAIN-per-statement on recent queries and returns a `method: "explain_fallback"` flag with a note.
- `cb_perf_not_selective` requires `~phaseCounts`. If absent, it returns a structured error explaining the version mismatch rather than silently producing wrong results.

The `cb_perf_not_using_covering_index` tool always uses EXPLAIN-per-statement because that's the only reliable way to detect Fetch operators across versions. It runs EXPLAIN on `limit * 3` recent queries (so a typical `limit=20` triggers up to 60 EXPLAIN calls). On busy clusters, set `limit` low.

---

- **Tool names**: 100% preserved. Every upstream tool keeps the same name and
  same required arguments.
- **Optional `confirm` argument**: New on destructive tools. Existing tool
  invocations that omit it will return a structured error instead of executing.
  This is intentional — the safer default. Set
  `CB_MCP_READ_ONLY_MODE=false` and pass `confirm: true` to restore the
  upstream behavior on a per-call basis.
- **Tool descriptions**: Lightly clarified; behavior unchanged.
- **Environment variables**: All upstream vars work as before. New vars are
  additive and all have safe defaults.

---

---

## Phase 5 — Couchbase 8.x-specific first-class tools

Adds 7 tools that wrap 8.x-only Couchbase features. All live in a new module `handlers/eight_x.py` — easy to find, easy to disable (drop the import in `server.py`). Every tool calls `_require_8x()` at runtime and returns a structured error if invoked against a 7.x cluster.

### Vector index helpers (structured creation, no raw SQL++)

- `admin_vector_index_create_hyperscale` — structured wrapper around `CREATE HYPERSCALE VECTOR INDEX`. Required: `bucket_name`, `index_name`, `field_name`, `dimension`, `similarity` (must be one of `L2_SQUARED` / `DOT_PRODUCT` / `COSINE`, validated). Optional: `scope_name`, `collection_name`, `description`, `num_replica`, `defer_build`.
- `admin_vector_index_create_composite` — structured wrapper around `CREATE COMPOSITE VECTOR INDEX`. Same as hyperscale plus a required `scalar_fields` array (prefix keys, order significant) and an optional `where_clause` for partial indexes.

Both tools use backtick-quoting on every identifier (matches the Phase 1 hardening on `admin_index_create`). The `where_clause` is guarded against semicolons to block statement-chain injection; deeper safety is the cluster's SQL++ parser.

These are alternatives to the raw `statement` path on `admin_index_create` — both still work; the new ones are easier to call correctly. The Phase 1 regex on `admin_index_create` already accepts vector DDL, so existing code that builds the statement themselves continues to work.

### RBAC additions

- `admin_user_lock` — `POST /settings/rbac/users/local/{user}/lock`. Marked `destructiveHint=true` because it denies access; requires `confirm: true`.
- `admin_user_unlock` — `POST /settings/rbac/users/local/{user}/unlock`. Write, not destructive.
- `admin_user_create_temporary` — `PUT /settings/rbac/users/local/{user}` with `temporaryPassword=true`. The user must rotate the password on first authentication.

### XDCR conflict log readback

- `admin_xdcr_conflict_log_query` — reads from the bucket/scope/collection configured as the conflict logging target on a replication. The replication's `conflictLogging=true` and `conflictLoggingMapping` are set via `admin_xdcr_replication_create` extra fields (pass-through from Phase 2's unified admin client). This tool is the readback side.

### Per-user query stats

- `cb_perf_by_user` — groups `system:completed_requests` by the `users` field that 8.x adds. Returns query count, total/avg/max elapsed time per user. Complements the Phase 4 query-analytics tools.

### Explicitly deferred

Three things from the original 8.x feature list are not in this drop because they need live-cluster validation I can't perform:

- **Search synonyms** — the synonym source API surface varies across 8.x patch levels. The skills document defining synonyms inside FTS index params; that path works today.
- **DARE / KMIP configuration** — install-time / CLI work, not a clean runtime REST surface.
- **NL-to-SQL++** — the LLM does this directly; no MCP value-add.

### Numbers after Phase 5

- Total tools: **115 → 122** (7 new).
- Loaded in read-only mode: **56 → 58** (`admin_xdcr_conflict_log_query` and `cb_perf_by_user` are read-only; the other 5 are writes).
- Confirmation-required: **21 → 22** (`admin_user_lock` added).
- Unit tests: **90 → 115** (25 new for version gating, similarity validation, WHERE-clause guard, statement construction, endpoint paths, tool registration).
- All 115 tests pass. All Python files compile clean.

### Behavior on 7.x clusters

Every Phase 5 tool calls `_require_8x()` at the top of its handler. On a 7.x cluster, the tool returns:

```json
{
  "error": "This tool requires Couchbase Server 8.0 or newer. Run admin_cluster_info and check `implementationVersion` to confirm your cluster version. For 7.x clusters use the equivalent 7.x tools or the documented SQL++ workarounds.",
  "tool": "<the tool name>",
  "hint": "Use admin_cluster_info to verify the cluster version."
}
```

Version detection uses the Phase 2 cached `get_cluster_version()` — one `/pools` call per server lifetime.

---

---

## Phase 6a — KV durability and subdocument operations

Two related additions to the data plane: durability-level support on the existing CRUD tools (strictly additive — old callers see no change), and a pair of new subdocument tools that read and modify fields inside a document without fetching the whole thing.

### Durability on the CRUD tools

`cb_upsert`, `cb_insert`, `cb_replace`, and `cb_delete` accept an optional `durability` argument with one of:

- `NONE` — default; matches upstream behavior.
- `MAJORITY` — wait for replication to a majority of replicas.
- `MAJORITY_AND_PERSIST_TO_ACTIVE` — same as MAJORITY plus disk on the active.
- `PERSIST_TO_MAJORITY` — wait for disk on a majority of replicas.

The schema enum is validated against the SDK's `DurabilityLevel` enum at module import time — a unit test verifies the two sets stay in sync, so if Couchbase adds a level we'll notice.

`cb_upsert` / `cb_insert` / `cb_replace` also accept an optional `expiry_seconds` (document TTL). `cb_replace` and `cb_delete` accept an optional `cas` string (from a prior `cb_get` or `cb_upsert` response) for optimistic concurrency control.

**Backwards compatibility**: all four tools' `required` field lists are unchanged. Existing calls without the new fields produce exactly the same behavior as upstream. The optional fields are added to the input schema without modifying or replacing any prior behavior.

### `cb_get` returns CAS

Phase 6a also adds the `cas` value to the `cb_get` response (and `cb_get_multi`'s per-key entries). This is the only existing-response change in the whole engagement so far — necessary to give callers something to feed into `cb_replace { cas }`. Existing callers that ignored extra response fields are unaffected.

### New: `cb_lookup_in`

Read one or more paths inside a document:

```
cb_lookup_in {
  key: "user::42",
  specs: [
    { op: "get", path: "profile.name" },
    { op: "exists", path: "profile.email" },
    { op: "count", path: "tags" }
  ]
}
```

Returns a `results` array aligned with the input specs, plus the document's `cas`. Each result includes the original `op` and `path` so the caller can match them up. Failed specs (e.g. a `get` on a missing path) include an `error` field instead of a value; other specs in the same call still execute.

`cb_lookup_in` is `readOnlyHint=true` and loads in read-only mode.

### New: `cb_mutate_in`

Modify one or more paths in a document atomically. Supports nine operation types:

- `upsert` — create-or-replace the path
- `insert` — create only if absent (fails if path exists)
- `replace` — replace only if present (fails if path missing)
- `remove` — delete the path
- `array_append` — push to the end of an array
- `array_prepend` — push to the start of an array
- `array_insert` — insert at a specific index (path ends in `[N]`)
- `array_add_unique` — append only if value not already present
- `counter` — atomic increment/decrement by an integer `delta` (default 1)

Optional `create_parents: true` on each op auto-creates intermediate path segments. Optional top-level `store_semantics` (`replace`/`upsert`/`insert`) controls behavior when the parent document does not exist. Optional `durability` and `cas` at the top level.

Example: append a tag, bump a counter, and conditionally set a preference in one atomic call:

```
cb_mutate_in {
  key: "user::42",
  ops: [
    { op: "array_append", path: "tags", value: "vip" },
    { op: "counter", path: "login_count", delta: 1 },
    { op: "upsert", path: "preferences.theme", value: "dark", create_parents: true }
  ],
  durability: "MAJORITY"
}
```

`cb_mutate_in` is `readOnlyHint=false, destructiveHint=false`. It does write data including potentially destructive `remove` ops, but is in the same category as `cb_upsert` — it's a routine write. Callers who want extra friction can add it to `CB_MCP_CONFIRMATION_REQUIRED_TOOLS`.

### Numbers after Phase 6a

- Total tools: **122 → 124** (2 new).
- Loaded in read-only mode: **58 → 59** (`cb_lookup_in` is a read; `cb_mutate_in` is a write).
- Confirmation-required: unchanged (22).
- Unit tests: **115 → 152** (37 new — durability parsing, KV options, lookup/mutate spec translation, store semantics, schema validation, enum-SDK alignment, backwards-compatibility verification).
- All 152 tests pass; all Python files compile clean.

### What's still missing from Phase 6 (deferred — Phase 6b)

- Multi-document transactions (`cluster.transactions.run(...)`) — requires a different shape (the SDK expects a callable, not a serialized op list). Doable but non-trivial.
- Analytics service tools — separate SQL++ for Analytics dialect, different endpoints.
- Eventing service tools — function deployment, debugger, statistics. Whole separate model.
- Sync Gateway tools — Sync Gateway is a separate product with its own REST API.
- Backup/Restore — REST endpoints exist; service is `backup` running on at least one node.

These were originally bundled into "Phase 6". The split into 6a (this drop) and 6b (later) keeps each chunk reviewable.

---

---

## Phase 6b — Transactions, Analytics, Backup/Restore

Three service surfaces added in one drop, all wrapped in a new `handlers/extended.py` module.

### Multi-document transactions

- `cb_transaction_run` — wraps `cluster.transactions.run`. Accepts a serialized operations list (insert/upsert/replace/remove) on documents in the configured `CB_BUCKET/CB_SCOPE/CB_COLLECTION`. The MCP builds the transaction callable that the SDK requires. All ops succeed or all roll back; the failure path is a single structured error with the SDK exception class name and the operation count.

```
cb_transaction_run {
  operations: [
    { op: "upsert", key: "account::a", document: {balance: 90} },
    { op: "upsert", key: "account::b", document: {balance: 210} }
  ],
  durability: "MAJORITY",
  timeout_seconds: 30,
  confirm: true
}
```

For `replace` and `remove`, the SDK's transaction API requires a `TransactionGetResult` (the API is built around fetched-doc references, not raw keys). The MCP does the implicit `ctx.get(collection, key)` inside the transaction body — if the doc is missing, the transaction fails fast and rolls back.

`cb_transaction_run` is `destructiveHint=true`, so it's unloaded in read-only mode and requires `confirm: true` in read-write mode.

**Currently scoped to write-only ops.** Read-then-conditional-write patterns (e.g. "get account balance, if > $100 then deduct $100") would require the LLM to be inside the transaction, which isn't viable with an MCP turn boundary. The 80% case — batched writes that need to all-succeed-or-all-fail — is what this drop covers. Read-modify-write atomicity over a single doc still works through `cb_replace { cas }`.

### Analytics service

- `cb_analytics_query` — wraps `cluster.analytics_query`. Same shape as `cb_query` but goes through the Analytics service instead of the Query service. Different SQL++ dialect (Analytics SQL++ has DDL like `CREATE DATASET`, `CREATE SHADOW DATASET`, etc.). Same DML blocking via `block_dml_if_readonly()` in read-only mode.

```
cb_analytics_query {
  statement: "SELECT region, COUNT(*) AS n FROM ds_orders GROUP BY region",
  params: {},
  timeout_seconds: 60
}
```

Treated like `cb_query`: `destructiveHint=true` in the spec, but always loaded in read-only mode (special case in `server.py`'s `_ALWAYS_LOADED_IN_READ_ONLY`), and excluded from the confirmation set because internal DML gating is sufficient.

The Analytics service must be running on at least one node — if it isn't, the tool returns the underlying SDK error verbatim.

### Backup / Restore

Five tools wrapping the backup service REST API at `/_p/backup/api/v1/...` on the cluster manager (mounted via Couchbase's REST proxy — uses the same `:8091`/`:18091` port as the rest of admin).

| Tool | HTTP | Path |
|---|---|---|
| `admin_backup_repository_list` | GET | `/cluster/self/repository` |
| `admin_backup_repository_get` | GET | `/cluster/self/repository/{id}` |
| `admin_backup_list` | GET | `/cluster/self/repository/{id}/backups` |
| `admin_backup_run` | POST | `/cluster/self/repository/{id}/backup` |
| `admin_backup_restore_run` | POST | `/cluster/self/repository/{id}/restore` |

Reads are `readOnlyHint=true`. `admin_backup_run` is a write but not destructive (creates new backup; doesn't overwrite cluster data). `admin_backup_restore_run` is `destructiveHint=true` because it can overwrite cluster data with backup contents — requires `confirm: true`.

The backup service must be installed and running on at least one node. If it isn't, `admin_request` returns the cluster manager's 404 error verbatim.

### Numbers after Phase 6b

- Total tools: **124 → 131** (7 new).
- Loaded in read-only mode: **59 → 63** (`cb_analytics_query` special-case-loaded + 3 read backup tools = 4 new; `cb_transaction_run`, `admin_backup_run`, `admin_backup_restore_run` are writes/destructive and filtered out).
- Confirmation-required: **22 → 24** (`cb_transaction_run` and `admin_backup_restore_run` added).
- Unit tests: **152 → 178** (26 new).
- All 178 tests pass; all Python files compile clean.

### Still deferred

- Eventing service tools (function deployment, debugger, statistics) — Eventing is a programming model with its own lifecycle and metadata structure. Deserves a dedicated turn.
- Sync Gateway tools — Sync Gateway is a separate product with a separate REST API at `:4985` (admin) / `:4984` (public). Different auth, different scope. Deserves a dedicated turn.

Both are tagged for a hypothetical "Phase 6c" if you want them.

---

---

## Phase 6c — Eventing service

Adds 10 tools wrapping the Couchbase Eventing service in a new `handlers/eventing.py` module. Eventing runs JavaScript functions that react to KV mutations (or timers); these tools cover the function lifecycle.

### Tools added

| Tool | Class | Notes |
|---|---|---|
| `admin_eventing_list` | R | List all functions with metadata |
| `admin_eventing_get` | R | Full definition + status of one function |
| `admin_eventing_create_or_update` | W | Takes a full JSON definition (appname, appcode, depcfg, settings) |
| `admin_eventing_delete` | D | Requires confirm; function must be undeployed first |
| `admin_eventing_deploy` | W | Start processing mutations |
| `admin_eventing_undeploy` | D | Stop processing; checkpoint discarded; requires confirm |
| `admin_eventing_pause` | W | Halt processing but preserve checkpoint |
| `admin_eventing_resume` | W | Continue from saved checkpoint |
| `admin_eventing_stats` | R | Per-function rates, failures, latency, DCP backlog |
| `admin_eventing_status` | R | Composite state of every function |

`admin_eventing_delete` and `admin_eventing_undeploy` are marked destructive: deletion is irreversible (function source is gone), and undeploy discards the processing checkpoint (resuming later requires reprocessing from the source). Pause/resume is non-destructive because the checkpoint persists.

### REST proxy path — caveat

The tools target `/_p/event/api/v1/...` on the cluster manager, mirroring the Backup tools' `/_p/backup/...` pattern. This is **unverified against a live cluster**. Some Couchbase deployments expose Eventing at the service's own port (8096 / 18096) without a cluster-manager proxy.

If a tool returns 404, the error response includes an explicit `hint` field pointing at this assumption:

```json
{
  "error": "RuntimeError: HTTP 404 on GET /_p/event/api/v1/list: Not Found",
  "tool": "admin_eventing_list",
  "hint": "404 from the Eventing endpoint may indicate the REST proxy path is different on this cluster. See handlers/eventing.py module docstring for adjustments."
}
```

The path prefix lives in a single module-level constant `_EVT_BASE` and a helper `_evt_path()` — change in one place if your cluster uses a different proxy path. A unit test (`test_evt_path_centralized_for_easy_override`) asserts the constant is exactly `/_p/event/api/v1`, so accidental drift is caught.

### Numbers after Phase 6c

- Total tools: **131 → 141** (10 new).
- Loaded in read-only mode: **63 → 67** (4 of the 10 Eventing tools are reads).
- Confirmation-required: **24 → 26** (`admin_eventing_delete` and `admin_eventing_undeploy` added).
- Unit tests: **178 → 195** (17 new — endpoint paths, JSON payload routing for create/update, 404 hint behavior, path-prefix override safety, annotation classification).
- All 195 tests pass; all Python files compile clean.

### What's still missing

- **Sync Gateway** — a separate product with its own REST API at `:4985` (admin) and `:4984` (public), separate authentication, and its own data model (databases, channels, users, replications). Wrapping it requires new env vars (`SG_HOST`, `SG_ADMIN_PORT`, `SG_USERNAME`, `SG_PASSWORD`) and a separate request helper. Deferred to a hypothetical Phase 6d if you want it; it's a meaningful chunk of work because Sync Gateway is essentially a second product wedged into this MCP.

---

---

## Phase 5 deferred items — completed

Three items deferred from Phase 5 because they "needed live-cluster validation I couldn't perform." Per the user's directive ("complete Phase 5 deferred items"), implemented two and documented the third as permanently out-of-scope.

### FTS synonym set documents (8.x) — new module `handlers/synonyms.py`

Couchbase 8.x synonyms are configured differently than I originally assumed:
- The synonym **source** is declared inside an FTS index's `params.mapping.analysis.synonym_sources` block — created via the existing `admin_fts_index_create` tool (no new admin endpoint needed).
- The synonym **set documents** live in a regular Couchbase collection. Each document has the shape `{"input": [...], "synonyms": [...]}`.

This module provides three KV convenience tools that validate the synonym schema client-side, so the LLM gets a clear error if it writes a malformed doc instead of silently inserting something the FTS analyzer can't parse:

- `cb_fts_synonym_upsert` — schema-validated upsert (input must be non-empty array of strings, synonyms same; both required).
- `cb_fts_synonym_list` — query the source collection for documents matching the synonym schema.
- `cb_fts_synonym_delete` — destructive (requires confirm).

All three are 8.x-only — they import `_require_8x()` from `handlers/eight_x.py` and gate at handler entry.

### DARE / KMIP — new module `handlers/encryption.py`

Four tools wrapping the Couchbase admin REST endpoints for Data-at-Rest Encryption configuration:

- `admin_encryption_get` — `GET /settings/security/encryptionAtRest` (read).
- `admin_encryption_set` — `POST /settings/security/encryptionAtRest` (destructive — misconfiguration can render data unreadable).
- `admin_kmip_get` — `GET /settings/security/kmip` (read).
- `admin_kmip_set` — `POST /settings/security/kmip` (destructive — misconfiguration can prevent cluster startup).

Both `set` tools accept explicit fields (`encryptionEnabled`, `keySource`, `rotateInterval`, `algorithm` for encryption; `kmipHost`, `kmipPort`, `clientCertPath`, etc. for KMIP) **and** an `additional_fields` pass-through dict for keys this MCP doesn't list explicitly. That way, when Couchbase adds new settings in a future version, callers can use them immediately without an MCP code change.

A 404 from either endpoint triggers the same path-hint pattern Eventing uses — the error response includes a `hint` field flagging that the path may differ on your specific cluster version.

### NL-to-SQL++ — permanently out of scope

The Couchbase 8.x natural-language-to-SQL++ feature does exist, but it's gated to specific Capella editions and the REST/SDK surface for it is not a documented stable public API. Per your direction ("Skip — document as permanent out-of-scope"), this is recorded as a known limitation rather than implemented.

If you want NL-to-SQL++ through Claude later, the right path is to call the Capella AI Services API directly from your application code rather than wrapping it in this MCP — the auth model and rate-limiting are different from cluster-management calls.

### Phase 5 deferred — Numbers

- Total tools: **141 → 148** (3 synonyms + 4 encryption).
- Loaded in read-only mode: **67 → 70** (cb_fts_synonym_list + admin_encryption_get + admin_kmip_get).
- Confirmation-required: **26 → 29** (cb_fts_synonym_delete + admin_encryption_set + admin_kmip_set).
- Unit tests: **+15** (synonym schema validation, version gating, encryption path correctness, additional_fields pass-through, 404 hint).

---

## Phase 7 — Capella v4 control plane (read-only)

A new module `handlers/capella.py` wrapping the Couchbase Capella SaaS control-plane API at `cloudapi.cloud.couchbase.com`. This is fundamentally different from every other module in this MCP — it talks to Couchbase's SaaS layer, not to a per-cluster manager.

### Scope: read-only inspection (per directive)

16 read-only tools covering the full resource hierarchy: organizations, projects, clusters, database users, allowed CIDRs, org users, API keys, and app services. All are `readOnlyHint=true`. Per your direction, no write operations are exposed in this drop — Capella writes (cluster creation, user invitations, API-key rotation) are explicitly out of scope because the cost of a runaway LLM-driven write to a production Capella org outweighs the convenience.

### What's different from the cluster-management tools

This module has its **own request helper** `_capella_request()` because:

- **Different base URL** — `https://cloudapi.cloud.couchbase.com` (overridable via `CAPELLA_BASE_URL` for staging endpoints), not derived from `CB_CONNECTION_STRING`.
- **Different auth** — Bearer token (`Authorization: Bearer <secret>`), not Basic. The secret comes from the API key created in the Capella UI under Settings → API Keys.
- **Different TLS** — Capella uses a publicly-trusted certificate, so the standard system CA bundle works. No `CB_CA_CERT_PATH` plumbing, no mTLS.

The helper has its own retry logic (same exponential-backoff pattern as `admin_request`, with `CAPELLA_HTTP_RETRIES` env override) and its own timeout (`CAPELLA_HTTP_TIMEOUT`).

### Tools (16, all read-only)

Organization scope:
- `capella_organizations_list` — also serves as the connectivity check after setting `CAPELLA_API_KEY_SECRET`.
- `capella_organization_get`
- `capella_org_users_list`, `capella_org_user_get` — Capella UI/API users (distinct from per-cluster database users).
- `capella_api_keys_list`, `capella_api_key_get` — metadata only; the secret part of each key is not retrievable post-creation.

Project scope:
- `capella_projects_list`, `capella_project_get`
- `capella_app_services_list`, `capella_app_service_get` — App Services (Couchbase Mobile / managed Sync Gateway endpoints) attached to projects.

Cluster scope (operational Capella clusters):
- `capella_clusters_list`, `capella_cluster_get`
- `capella_database_users_list`, `capella_database_user_get` — per-cluster database credentials.
- `capella_allowed_cidrs_list`, `capella_allowed_cidr_get` — IP allowlist; Capella only accepts client connections from allowed CIDRs.

### New env vars

| Var | Required | Default | Purpose |
|---|---|---|---|
| `CAPELLA_API_KEY_SECRET` | Yes (if you use Capella tools) | — | The secret part of a Capella API key |
| `CAPELLA_BASE_URL` | No | `https://cloudapi.cloud.couchbase.com` | Override for staging endpoints |
| `CAPELLA_HTTP_TIMEOUT` | No | `30` | Per-request timeout in seconds |
| `CAPELLA_HTTP_RETRIES` | No | `3` | Max attempts on transient failures |

The Capella tools fail loudly if `CAPELLA_API_KEY_SECRET` is unset — they don't silently no-op. If you don't use Capella, you don't need to set it; the rest of the MCP still works.

### Phase 7 — Numbers

- Total tools: **148 → 164** (16 Capella tools).
- Loaded in read-only mode: **70 → 86** (all 16 Capella tools are reads).
- Confirmation-required: unchanged (29 — no Capella writes).
- Unit tests: **+13** (Bearer-token header construction, base URL handling, path encoding for hierarchical resources, retry-on-503, no-retry-on-403, env-var failure mode).

### Final test count

**223 unit tests, all passing.** Phase coverage:

| Phase | Test file | Tests |
|---|---|---|
| 1 (safety) + 3 (transport) | `test_safety.py` | 34 |
| 2 (admin client) | `test_admin_request.py` | 19 |
| 1 (index DDL) | `test_index_hardening.py` | 13 |
| 4 (diagnostics) | `test_diagnostics.py` | 24 |
| 5 (8.x core) | `test_eight_x.py` | 25 |
| 6a (subdoc) | `test_subdoc.py` | 37 |
| 6b (extended) | `test_extended.py` | 26 |
| 6c (eventing) | `test_eventing.py` | 17 |
| 5-deferred + 7 | `test_phase5_phase7.py` | 28 |

---

## Required env vars (no silent defaults)

The hardened server raises at startup if these are unset and mTLS is not
configured:

- `CB_USERNAME`
- `CB_PASSWORD`

If mTLS is configured (both `CB_CLIENT_CERT_PATH` and `CB_CLIENT_KEY_PATH`
set), `CB_USERNAME` / `CB_PASSWORD` are not required.

`CB_CONNECTION_STRING`, `CB_BUCKET`, `CB_SCOPE`, `CB_COLLECTION` continue to
default to `couchbase://localhost`, `default`, `_default`, `_default`.

---

## What's NOT in this drop (intentional limits)

- **NL-to-SQL++**: documented as permanently out-of-scope (see Phase 5 deferred
  items section). The feature exists but its API surface isn't a stable
  documented public contract; call Capella AI Services directly from your app
  instead of through this MCP.
- **Phase 6b deferred**: read-then-conditional-write transactions. The
  LLM-in-the-loop boundary makes these awkward; the write-batch pattern in
  `cb_transaction_run` covers 80% of multi-doc atomicity needs.
- **Phase 6d** (deferred per directive — to be built later as a separate MCP
  server): Sync Gateway tools. Separate product with its own REST API at
  `:4985`/`:4984`, separate auth, separate data model.
- **Phase 7 writes**: Capella v4 wraps reads only. Writes (cluster create/
  delete, user management, API-key rotation, allowlist changes) are
  out-of-scope by directive — the blast radius of an LLM-driven write to a
  production Capella org outweighs the convenience.
- **Skill refresh**: the `couchbase-7x` and `couchbase-8x` skill packs need
  an update to reference all the new tools from Phases 4 onward. The packs
  still work — they reference workarounds for tools that now have first-class
  versions — but a refresh would let the LLM prefer the better tools by
  default.
