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
  test_safety.py            # 141 unit tests, no cluster required
skills/
  couchbase-sqlpp-tuning/   # LLM skill — diagnose and fix slow SQL++ queries
    SKILL.md                # Router with core principles
    references/             # 7 deep references (explain plan, index design,
                            # query patterns, CBO, diagnostic workflow,
                            # pagination, joins)
gui/
  gui_server.py             # Flask backend for the cluster GUI (151 tools)
  static/                   # React SPA (not in this repo's tree)
gui-capella/
  gui_server.py             # Flask backend for the Capella v4 GUI (16 tools)
  static/                   # Capella-themed React SPA
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

## Bug history (29 bugs fixed across iterative scan passes)

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
22. `server.py` `_main_http` — used `asyncio.TaskGroup` (3.11+) but `pyproject.toml` declares `requires-python>=3.10`. CI failed on the Python 3.10 matrix job. Replaced with `asyncio.gather` for the two-task case (equivalent semantics: first failure cancels the other and propagates).
23. `tests/test_safety.py` `test_pyproject_entry_point_points_at_sync_main` — used `import tomllib` (stdlib only on 3.11+). Same CI failure. Added a 3.10-safe fallback to `tomli` (added to `dev` extras with a `python_version<'3.11'` marker) and a new regression test `test_no_python_311_only_stdlib_in_runtime_code` that scans all runtime code for `asyncio.TaskGroup`, `ExceptionGroup`, `tomllib` imports, `except*`, and `typing.Self` — so this class of CI failure can't recur silently.
24. `gui/gui_server.py` — duplicated `app = Flask(...)` + `CORS(app)` on consecutive lines from a botched earlier patch. The second one silently shadowed the first; Flask still worked but the `CORS(app)` call was applied twice. Cleaned up to a single instance.
25. `gui/gui_server.py` and `gui-capella/gui_server.py` — `CORS(app)` with no args allowed every origin. Restricted to localhost/127.0.0.1/::1 origins so a malicious page can't fire calls at a local MCP GUI.
26. `gui/gui_server.py` `/api/config` POST accepted ARBITRARY `os.environ` writes from the request body. An attacker (LAN-reachable or via CORS exploit) could set `PATH`, `LD_PRELOAD`, `PYTHONPATH`, etc., on the running server. Added a `_CONFIG_ALLOWLIST` of permitted `CB_*` / `CAPELLA_*` keys; everything else is rejected. Same fix applied to `gui-capella/gui_server.py`.
27. `gui/gui_server.py` `/api/config` GET returned `CB_PASSWORD` in cleartext to anyone who hit the endpoint. Added `_REDACTED_FIELDS` and a `_redact()` helper that returns `"********"` for password / API-key fields.
28. `gui/gui_server.py` `/api/call` bypassed every safety primitive — no `READ_ONLY_MODE` filter, no `DISABLED_TOOLS`, no confirmation gate. Any destructive admin tool could be invoked through the GUI even with `CB_MCP_READ_ONLY_MODE=true` set. Now imports the same primitives from `handlers.shared` and applies them in `/api/call`, with parity to `server.py`'s tool-call gate.
29. Both GUIs had `app.run(host="0.0.0.0", port=port, debug=True)` — bound to every interface AND enabled the Werkzeug debugger (full RCE on any reachable client). Now: bind defaults to `127.0.0.1`, `0.0.0.0` requires an explicit `CB_GUI_ALLOW_REMOTE=1`, and `debug` defaults to `False` and reads from `FLASK_DEBUG`.

## Shared helpers introduced

Three helpers in `handlers/shared.py` were added during the bug-fix sweep and now factor out the patterns where bugs kept recurring:

- `quote_path(segment)` — URL-encode a single user-supplied URL path segment. Used in 11 handlers.
- `form_data(args, exclude=("confirm",))` — Build form-data dict with boolean-aware encoding (`True` → `"true"`, not Python's `"True"`). Used in 6 handlers.
- `form_value(v)` — Single-value boolean-aware form encoding.

Any new handler accepting user-supplied identifiers in URL paths or boolean form fields **must** use these.

## Tests

```bash
# Unit tests only (no cluster) — 141 tests, all passing
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

# 2. All unit tests pass (141 tests, no cluster needed)
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
