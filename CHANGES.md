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

## Backwards compatibility

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

## What's NOT in this drop (intentional, for later phases)

- Phase 4: Coverage gaps vs the official Couchbase MCP — schema discovery
  helpers, query performance analyzers (longest-running, large-result-count,
  not-using-covering-index, etc.), index advisor.
- Phase 5: Couchbase 8.x-specific tools — hyperscale/composite vector indexes,
  DARE/KMIP, XDCR conflict logging, query workload repo, user lock/unlock,
  temporary passwords, search synonyms.
- Phase 6: Missing 7.x surfaces — KV durability levels, subdocument ops,
  multi-document transactions, Analytics service, Eventing, Sync Gateway,
  Backup/Restore.
- Phase 7: Capella v4 control-plane API (separate API at
  `cloudapi.cloud.couchbase.com` with API-key auth — not the per-cluster
  management API this server already supports).
