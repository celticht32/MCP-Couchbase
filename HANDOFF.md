# HANDOFF — Couchbase MCP Server (celticht32 / Celtic Heart Steamworks)

## Project at a glance

A Python MCP server that wraps the Couchbase Python SDK and Management REST API,
exposing 167 tools across 17 handler modules. The current state is the result
of merging the maintainer's `MCP-Couchbase` repo with the safety primitives
and contribution conventions from the official `Couchbase-Ecosystem/mcp-server-couchbase`.

Goal: contribute this back to `Couchbase-Ecosystem/mcp-server-couchbase` as a
single PR after an open GitHub issue settles the scope.

## Layout

```
server.py                   # MCP entry point — aggregates 17 handler modules,
                            # applies read-only / disabled-tools filters,
                            # enforces confirmation gate
handlers/
  shared.py                 # Connection pool, HTTP admin client,
                            # safety primitives, URL/form helpers
  data.py                   # CRUD, N1QL, FTS search, sub-document     (11 tools)
  buckets.py                # Bucket lifecycle                          (10)
  collections.py            # Scopes and collections                    (5)
  security.py               # Users, groups, RBAC, audit                (17)
  cluster.py                # Nodes, rebalance, failover                (29)
  xdcr.py                   # Cross-datacenter replication              (10)
  indexes.py                # GSI index management                      (6)
  search_admin.py           # FTS index administration                  (9)
  stats.py                  # Metrics and monitoring                    (10)
  diagnostics.py            # Schema, index advisor, EXPLAIN, perf      (10)
  eight_x.py                # Couchbase 8.x-only features               (7)
  extended.py               # Transactions, Analytics, Backup           (7)
  eventing.py               # Eventing function lifecycle               (10)
  synonyms.py               # FTS synonym set documents                 (3)
  encryption.py             # DARE encryption + KMIP                    (4)
  capella.py                # Capella v4 control plane (read-only)      (16)
  mcp_status.py             # Server introspection                      (3)
tests/
  conftest.py               # Shared fixtures, integration skip markers
  test_safety.py            # 134 unit tests, no cluster required
skills/
  couchbase-sqlpp-tuning/   # LLM skill — diagnose and fix slow SQL++ queries
    SKILL.md                # Router with core principles
    references/             # 6 deep references (explain plan, index design,
                            # query patterns, CBO, diagnostic workflow,
                            # pagination, joins)
pyproject.toml              # hatchling build, uv lock, ruff/pytest config
.pre-commit-config.yaml     # Matches official Couchbase MCP repo
Dockerfile                  # Multi-stage Python 3.12-slim, non-root
docker-compose.yml          # Couchbase Server + MCP server stack
smithery.yaml               # Smithery.ai managed hosting config
.github/
  workflows/ci.yml          # GH Actions — ruff + pytest on 3.10/3.11/3.12, build
  ISSUE_TEMPLATE/           # Bug report and feature request templates
  PULL_REQUEST_TEMPLATE.md  # PR checklist (safety review + verification)
LICENSE                     # MIT
.env.example                # Template for all CB_* env vars
.dockerignore
.gitignore
requirements.txt            # Runtime deps (mcp, couchbase)
README.md                   # Full reference: tools, config, deploy options
```

## Safety model (matches official server)

| Knob | Env var | Default |
|---|---|---|
| Read-only mode | `CB_MCP_READ_ONLY_MODE` | `true` |
| Tool exclusion | `CB_MCP_DISABLED_TOOLS` | unset |
| Extra confirm-required tools | `CB_MCP_CONFIRMATION_REQUIRED_TOOLS` | unset |
| Elicitation hints in error responses | `CB_MCP_ELICITATION_HINTS` | `true` |
| HTTP retries | `CB_MCP_HTTP_RETRIES` | `3` |
| HTTP timeout (sec) | `CB_MCP_HTTP_TIMEOUT` | `30` |
| Transport | `CB_MCP_TRANSPORT` | `stdio` |

Defense-in-depth measures wired through `handlers/shared.py`:

- `block_dml_if_readonly()` rejects DML/DDL in `cb_query` and `cb_analytics_query` when read-only mode is on
- `assert_index_create_ddl()` / `assert_index_drop_ddl()` lock the raw-`statement` paths to index DDL only
- `require_confirmation()` enforces the `confirm: true` two-step pattern on every `destructiveHint=True` tool
- `quote_path()` URL-encodes every user-supplied URL segment (applied across all handlers)
- `form_data()` boolean-aware form encoding (`True` → `"true"`, not Python's `"True"`)
- Domain values in security endpoints validated against the `local`/`external` allow-list
- All N1QL identifier interpolation goes through `_safe_ident()` / `_keyspace()`
- mTLS via `CertificateAuthenticator` when both `CB_CLIENT_CERT_PATH` and `CB_CLIENT_KEY_PATH` are set

## Architecture decision — Option B

The merge uses the **handler module pattern** rather than `@mcp.tool()` decorators:

- Each tool category is a self-contained module exporting `TOOLS: list[Tool]` and `handle(name, args)`
- `server.py` aggregates them, applies filters, routes calls
- Adding a new category is two lines in `server.py`
- The shared connection pool and HTTP admin client are exposed via `handlers.shared` for reuse

The PR proposal in the GitHub issue formalizes this pattern and asks for maintainer alignment before opening the PR.

## Bug history (21 bugs fixed across iterative scan passes)

1. `security.py` `admin_user_change_password` — was using `PUT` with only password, wiped user roles. Fixed to use `POST /controller/changePassword`.
2. `collections.py` `maxTTL` — was string, must be int.
3. `xdcr.py` `cluster_name` — wasn't URL-encoded.
4. `indexes.py` `admin_index_build` — pre-7.0 syntax; added scope/collection support.
5. `stats.py` `admin_query_settings_set` — didn't strip `confirm`.
6. `tests/conftest.py` — used nonexistent `monkeypatch_session` fixture.
7. `cluster.py` `admin_autocompaction_set` — didn't strip `confirm`.
8-11. `security.py` (audit/password/security) + `stats.py` (internal) — `str(True)` produced `"True"`; Couchbase REST requires `"true"`. Fixed via new `form_data()` helper in `shared.py`.
12. `eventing.py` — function names weren't URL-encoded.
13. URL path identifiers across buckets/collections/security/eight_x/cluster/search_admin/stats/extended — none were URL-encoded. Fixed via new `quote_path()` helper applied uniformly.
14. `security.py` `domain` field — not validated against allow-list (could traverse via URL). Now rejects anything but `local`/`external`.
15. `xdcr.py` `replicationType` schema — conflated `replicationType` (always "continuous") and `type` (xmem/capi protocol). Split into two fields per Couchbase docs, added `compressionType`.
16. `collections.py` — `data={"name": s}` was using URL-encoded value as the actual form-data name. Fixed.
17. `xdcr.py` `admin_xdcr_replication_create` — was missing `conflictLogging` / `conflictLoggingMapping` fields that the 8.x conflict-log-query tool's docstring references. Couldn't actually configure conflict logging through the MCP.
18. `server.py` + `pyproject.toml` — entry-point script `couchbase-mcp-server = "server:main"` pointed at an `async def main`. Pip-installed users would hit "coroutine was never awaited". Added sync `main()` wrapper around `_async_main()`.
19. `Dockerfile` `HEALTHCHECK` — always probed HTTP even in stdio mode, marking the container unhealthy forever. Now exits 0 (skip) unless `CB_MCP_TRANSPORT=http`.
20. `data.py` `_kv_options` — `raise ValueError(...)` without `from exc` (B904), masking the original `TypeError` / `ValueError`. Fixed with `from exc`.
21. `.gitignore` — no patterns for `*.pem` / `*.key` / `*.crt` / `*.p12`. Easy to accidentally commit a Couchbase TLS cert. Added secret-material patterns plus `secrets/`, `credentials.json`.

## Shared helpers introduced

Three helpers in `handlers/shared.py` were added during the bug-fix sweep and now factor out the patterns where bugs kept recurring:

- `quote_path(segment)` — URL-encode a single user-supplied URL path segment. Used in 11 handlers.
- `form_data(args, exclude=("confirm",))` — Build form-data dict with boolean-aware encoding (`True` → `"true"`, not Python's `"True"`). Used in 6 handlers.
- `form_value(v)` — Single-value boolean-aware form encoding.

Any new handler accepting user-supplied identifiers in URL paths or boolean form fields **must** use these.

## Tests

```bash
# Unit tests only (no cluster) — 134 tests, all passing
pytest tests/ -m unit -v

# Integration tests (requires live cluster)
CB_CONNECTION_STRING=couchbase://localhost \
CB_USERNAME=Administrator \
CB_PASSWORD=password \
CB_BUCKET=travel-sample \
pytest tests/ -v
```

## Deployment paths

| Path | Status |
|---|---|
| PyPI (`couchbase-mcp-server`) | Ready to publish — `pyproject.toml` configured with hatchling |
| Docker | Dockerfile + docker-compose.yml present, non-root user, read-only mode default |
| Smithery.ai | `smithery.yaml` with stdio + Docker build path |
| Source | `git clone && uv sync && uv run server.py` |

## Pending — open contribution issue

The GitHub issue draft (in the prior conversation summary) describes scope, architecture rationale, and questions for the maintainers. After the maintainers respond, the PR opens from a fork into `Couchbase-Ecosystem/mcp-server-couchbase`.

## Quick verification after handoff

```bash
# 1. Lint and format clean
ruff check . && ruff format --check .

# 2. All unit tests pass (134 tests, no cluster needed)
pytest tests/ -m unit

# 3. Server starts (kills immediately — just to verify imports)
CB_USERNAME=u CB_PASSWORD=p timeout 2 python server.py || true

# 4. Entry-point script is callable (verifies the pip-install path)
python -c "from server import main; import inspect; \
  assert callable(main) and not inspect.iscoroutinefunction(main); \
  print('entry-point OK')"

# 5. cb_mcp_status responds without a live cluster
CB_USERNAME=u CB_PASSWORD=p python -c "
import server
from handlers import mcp_status
import json
out = mcp_status.handle('cb_mcp_status', {})
print(json.loads(out[0].text)['safety'])
"
```
