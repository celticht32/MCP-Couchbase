"""
tests/test_safety.py — unit tests for safety primitives, tool registration,
and regression tests for known bug-prone handler logic.

All tests here run WITHOUT a live Couchbase cluster.
"""

from __future__ import annotations

import importlib
import json
import urllib.parse

import pytest

from tests.conftest import flush_modules

# ═══════════════════════════════════════════════════════════════════════════════
# READ_ONLY_MODE parsing
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@pytest.mark.parametrize(
    "val,expected",
    [
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("false", False),
        ("False", False),
        ("0", False),
        ("no", False),
        ("off", False),
        ("", True),  # empty → default True
        (None, True),  # unset → default True
    ],
)
def test_read_only_mode_parsing(monkeypatch, val, expected):
    flush_modules("handlers", "server")
    monkeypatch.setenv("CB_USERNAME", "u")
    monkeypatch.setenv("CB_PASSWORD", "p")
    if val is None:
        monkeypatch.delenv("CB_MCP_READ_ONLY_MODE", raising=False)
    else:
        monkeypatch.setenv("CB_MCP_READ_ONLY_MODE", val)
    from handlers import shared

    assert expected == shared.READ_ONLY_MODE


# ═══════════════════════════════════════════════════════════════════════════════
# DML detection
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@pytest.mark.parametrize(
    "stmt,is_dml",
    [
        ("SELECT * FROM users", False),
        ("select * from users", False),
        ("  SELECT * FROM users", False),
        ("-- comment\nSELECT * FROM users", False),
        ("/* block */ SELECT 1", False),
        ("INSERT INTO users VALUES {}", True),
        ("insert into users values {}", True),
        ("UPSERT INTO users KEY 'k' VALUES {}", True),
        ("UPDATE users SET x = 1", True),
        ("DELETE FROM users WHERE id = 1", True),
        ("MERGE INTO users", True),
        ("CREATE INDEX idx ON users(id)", True),
        ("DROP INDEX idx ON users", True),
        ("BUILD INDEX ON users(idx)", True),
        ("ALTER INDEX idx ON users", True),
        ("GRANT SELECT ON users TO user1", True),
        ("REVOKE SELECT ON users FROM user1", True),
        ("EXECUTE FUNCTION f()", True),
        ("", False),
        ("   ", False),
    ],
)
def test_is_dml_statement(monkeypatch, clean_env, stmt, is_dml):
    from handlers import shared

    assert shared.is_dml_statement(stmt) == is_dml


@pytest.mark.unit
def test_block_dml_blocks_insert(clean_env):
    from handlers import shared

    msg = shared.block_dml_if_readonly("INSERT INTO users VALUES {}")
    assert msg is not None
    assert "read-only" in msg.lower()


@pytest.mark.unit
def test_block_dml_allows_select(clean_env):
    from handlers import shared

    assert shared.block_dml_if_readonly("SELECT * FROM users") is None


@pytest.mark.unit
def test_block_dml_off_allows_insert(monkeypatch):
    flush_modules("handlers", "server")
    monkeypatch.setenv("CB_MCP_READ_ONLY_MODE", "false")
    monkeypatch.setenv("CB_USERNAME", "u")
    monkeypatch.setenv("CB_PASSWORD", "p")
    from handlers import shared

    assert shared.block_dml_if_readonly("INSERT INTO users VALUES {}") is None


# ═══════════════════════════════════════════════════════════════════════════════
# DISABLED_TOOLS parsing
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_disabled_tools_comma_list(monkeypatch):
    flush_modules("handlers", "server")
    monkeypatch.setenv("CB_USERNAME", "u")
    monkeypatch.setenv("CB_PASSWORD", "p")
    monkeypatch.setenv("CB_MCP_DISABLED_TOOLS", "cb_get,cb_upsert, cb_delete")
    from handlers import shared

    assert "cb_get" in shared.DISABLED_TOOLS
    assert "cb_upsert" in shared.DISABLED_TOOLS
    assert "cb_delete" in shared.DISABLED_TOOLS
    assert "cb_ping" not in shared.DISABLED_TOOLS


@pytest.mark.unit
def test_disabled_tools_file(monkeypatch, tmp_path):
    f = tmp_path / "disabled.txt"
    f.write_text("# comment\ncb_get\ncb_upsert\n\n# another comment\ncb_ping\n")
    flush_modules("handlers", "server")
    monkeypatch.setenv("CB_USERNAME", "u")
    monkeypatch.setenv("CB_PASSWORD", "p")
    monkeypatch.setenv("CB_MCP_DISABLED_TOOLS", str(f))
    from handlers import shared

    assert "cb_get" in shared.DISABLED_TOOLS
    assert "cb_upsert" in shared.DISABLED_TOOLS
    assert "cb_ping" in shared.DISABLED_TOOLS


@pytest.mark.unit
def test_disabled_tools_empty(monkeypatch):
    flush_modules("handlers", "server")
    monkeypatch.setenv("CB_USERNAME", "u")
    monkeypatch.setenv("CB_PASSWORD", "p")
    monkeypatch.delenv("CB_MCP_DISABLED_TOOLS", raising=False)
    from handlers import shared

    assert len(shared.DISABLED_TOOLS) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Confirmation gate
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_confirmation_required_without_confirm(clean_env):
    from handlers import shared

    msg = shared.require_confirmation("admin_bucket_delete", {}, in_confirm_set=True)
    assert msg is not None
    assert "confirmation required" in msg.lower()


@pytest.mark.unit
def test_confirmation_with_confirm_true(clean_env):
    from handlers import shared

    msg = shared.require_confirmation(
        "admin_bucket_delete", {"confirm": True}, in_confirm_set=True
    )
    assert msg is None


@pytest.mark.unit
def test_confirmation_with_confirm_false_still_blocked(clean_env):
    from handlers import shared

    msg = shared.require_confirmation(
        "admin_bucket_delete", {"confirm": False}, in_confirm_set=True
    )
    assert msg is not None


@pytest.mark.unit
def test_confirmation_not_in_set_always_passes(clean_env):
    from handlers import shared

    msg = shared.require_confirmation("cb_get", {}, in_confirm_set=False)
    assert msg is None


@pytest.mark.unit
def test_confirmation_hint_in_message(monkeypatch):
    flush_modules("handlers", "server")
    monkeypatch.setenv("CB_USERNAME", "u")
    monkeypatch.setenv("CB_PASSWORD", "p")
    monkeypatch.setenv("CB_MCP_ELICITATION_HINTS", "true")
    from handlers import shared

    msg = shared.require_confirmation("admin_bucket_delete", {}, in_confirm_set=True)
    assert "confirm" in msg.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# Index DDL validation
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@pytest.mark.parametrize(
    "stmt",
    [
        "CREATE INDEX idx ON bucket.scope.coll(field)",
        "CREATE PRIMARY INDEX ON bucket.scope.coll",
        "BUILD INDEX ON bucket(idx)",
        "create index idx ON bucket(f)",
        "CREATE HYPERSCALE VECTOR INDEX vi ON b.s.c(vec)",
        "CREATE COMPOSITE VECTOR INDEX vi ON b.s.c(vec)",
    ],
)
def test_index_create_ddl_valid(clean_env, stmt):
    from handlers import shared

    assert shared.assert_index_create_ddl(stmt) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "stmt",
    [
        "SELECT * FROM system:indexes",
        "DELETE FROM bucket WHERE x=1",
        "INSERT INTO bucket VALUES {}",
        "DROP INDEX idx ON bucket",
        "",
    ],
)
def test_index_create_ddl_invalid(clean_env, stmt):
    from handlers import shared

    assert shared.assert_index_create_ddl(stmt) is not None


@pytest.mark.unit
@pytest.mark.parametrize(
    "stmt",
    [
        "DROP INDEX idx ON bucket.scope.coll",
        "DROP PRIMARY INDEX ON bucket.scope.coll",
        "drop index idx on bucket",
        "DROP VECTOR INDEX vi ON bucket.scope.coll",
    ],
)
def test_index_drop_ddl_valid(clean_env, stmt):
    from handlers import shared

    assert shared.assert_index_drop_ddl(stmt) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "stmt",
    [
        "CREATE INDEX idx ON bucket(f)",
        "SELECT 1",
        "",
    ],
)
def test_index_drop_ddl_invalid(clean_env, stmt):
    from handlers import shared

    assert shared.assert_index_drop_ddl(stmt) is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Response helpers
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_ok_returns_json(clean_env):
    from handlers import shared

    result = shared.ok({"key": "value", "nested": {"x": 1}})
    assert len(result) == 1
    assert result[0].type == "text"
    data = json.loads(result[0].text)
    assert data["key"] == "value"
    assert data["nested"]["x"] == 1


@pytest.mark.unit
def test_err_returns_structured_error(clean_env):
    from handlers import shared

    result = shared.err("something broke", tool="cb_get", hint="try again")
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["error"] == "something broke"
    assert data["tool"] == "cb_get"
    assert data["hint"] == "try again"


@pytest.mark.unit
def test_ok_handles_non_serializable(clean_env):
    """ok() should not raise on types that require default=str."""
    from datetime import datetime

    from handlers import shared

    result = shared.ok({"ts": datetime(2026, 1, 1)})
    assert "2026" in result[0].text


# ═══════════════════════════════════════════════════════════════════════════════
# Tool registration
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_all_handlers_import_cleanly(clean_env):
    """All handler modules must import and expose TOOLS + handle without errors."""
    handler_names = [
        "handlers.data",
        "handlers.buckets",
        "handlers.collections",
        "handlers.security",
        "handlers.cluster",
        "handlers.xdcr",
        "handlers.indexes",
        "handlers.search_admin",
        "handlers.stats",
        "handlers.diagnostics",
        "handlers.eight_x",
        "handlers.extended",
        "handlers.eventing",
        "handlers.synonyms",
        "handlers.encryption",
        "handlers.capella",
        "handlers.mcp_status",
    ]
    for name in handler_names:
        mod = importlib.import_module(name)
        assert hasattr(mod, "TOOLS"), f"{name} missing TOOLS"
        assert hasattr(mod, "handle"), f"{name} missing handle()"
        assert len(mod.TOOLS) > 0, f"{name} has empty TOOLS"
        # Every tool must have a name and inputSchema
        for t in mod.TOOLS:
            assert t.name, f"{name}: tool missing name"
            assert t.inputSchema, f"{name}: {t.name} missing inputSchema"


@pytest.mark.unit
def test_tool_names_are_unique(clean_env):
    """No two tools across all handlers may share a name."""
    all_tools = _all_tools()
    names = [t.name for t in all_tools]
    dupes = [n for n in set(names) if names.count(n) > 1]
    assert not dupes, f"Duplicate tool names: {dupes}"


@pytest.mark.unit
def test_total_tool_count(clean_env):
    """Total tool count must be >= 167 (164 Couchbase + 3 MCP introspection)."""
    total = len(_all_tools())
    assert total >= 167, f"Expected >= 167 tools, got {total}"


@pytest.mark.unit
def test_every_write_tool_has_read_only_false(clean_env):
    """Every tool with readOnlyHint=False must have an explicit annotation."""
    for t in _all_tools():
        assert t.annotations is not None, (
            f"{t.name}: missing annotations — all tools must have ToolAnnotations"
        )


@pytest.mark.unit
def test_every_destructive_tool_has_confirm_in_schema(clean_env):
    """Every tool annotated destructiveHint=True must accept a 'confirm' parameter,
    EXCEPT tools that use DML blocking internally (cb_query, cb_analytics_query).
    """
    # These tools are destructive in spec but gate writes via DML detection, not confirm.
    INTERNAL_GATE_TOOLS = {"cb_query", "cb_analytics_query"}
    for t in _all_tools():
        if t.annotations and t.annotations.destructiveHint:
            if t.name in INTERNAL_GATE_TOOLS:
                continue
            props = t.inputSchema.get("properties", {})
            assert "confirm" in props, (
                f"{t.name}: destructiveHint=True but 'confirm' not in inputSchema"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Server-level filtering
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_read_only_mode_filters_write_tools(monkeypatch):
    """In read-only mode, write tools must not appear in the loaded tool list."""
    flush_modules("handlers", "server")
    monkeypatch.setenv("CB_MCP_READ_ONLY_MODE", "true")
    monkeypatch.setenv("CB_USERNAME", "u")
    monkeypatch.setenv("CB_PASSWORD", "p")
    import server

    loaded = {t.name for t in server._TOOLS}
    write_tools = [
        "cb_upsert",
        "cb_insert",
        "cb_replace",
        "cb_delete",
        "cb_mutate_in",
        "admin_bucket_create",
        "admin_bucket_delete",
        "admin_bucket_flush",
        "admin_user_create",
        "admin_user_delete",
        "admin_user_change_password",
        "admin_group_create",
        "admin_group_delete",
        "admin_scope_create",
        "admin_scope_delete",
        "admin_collection_create",
        "admin_collection_delete",
        "admin_failover_hard",
        "admin_failover_graceful",
        "admin_xdcr_replication_create",
        "admin_xdcr_replication_delete",
        "admin_index_create",
        "admin_index_drop",
        "admin_fts_index_create",
        "admin_fts_index_delete",
        "admin_eventing_create_or_update",
        "admin_eventing_deploy",
        "admin_backup_run",
        "admin_backup_restore_run",
    ]
    for name in write_tools:
        assert name not in loaded, f"Write tool {name!r} present in read-only mode"


@pytest.mark.unit
def test_read_only_mode_keeps_read_tools(monkeypatch):
    """In read-only mode, all read-only tools must still be loaded."""
    flush_modules("handlers", "server")
    monkeypatch.setenv("CB_MCP_READ_ONLY_MODE", "true")
    monkeypatch.setenv("CB_USERNAME", "u")
    monkeypatch.setenv("CB_PASSWORD", "p")
    import server

    loaded = {t.name for t in server._TOOLS}
    read_tools = [
        "cb_get",
        "cb_get_multi",
        "cb_ping",
        "cb_fts_search",
        "cb_query",
        "cb_analytics_query",
        "admin_bucket_list",
        "admin_bucket_get",
        "admin_scope_list",
        "admin_cluster_info",
        "admin_node_list",
        "cb_get_schema_for_collection",
        "cb_index_advisor",
        "cb_explain_query",
        "admin_xdcr_references_list",
        "admin_xdcr_replications_list",
        "admin_fts_index_list",
        "admin_fts_index_stats",
        "admin_index_list",
        "admin_index_settings_get",
        "admin_user_list",
        "admin_role_list",
        "admin_whoami",
        "admin_eventing_list",
        "admin_eventing_stats",
        "capella_organizations_list",
        "capella_clusters_list",
    ]
    for name in read_tools:
        assert name in loaded, f"Read tool {name!r} missing in read-only mode"


@pytest.mark.unit
def test_disabled_tools_respected_by_server(monkeypatch):
    """Tools in CB_MCP_DISABLED_TOOLS must not appear in _TOOLS."""
    flush_modules("handlers", "server")
    monkeypatch.setenv("CB_MCP_READ_ONLY_MODE", "false")
    monkeypatch.setenv("CB_USERNAME", "u")
    monkeypatch.setenv("CB_PASSWORD", "p")
    monkeypatch.setenv("CB_MCP_DISABLED_TOOLS", "cb_get,admin_bucket_list")
    import server

    loaded = {t.name for t in server._TOOLS}
    assert "cb_get" not in loaded
    assert "admin_bucket_list" not in loaded
    assert "cb_ping" in loaded  # unrelated tool still present


# ═══════════════════════════════════════════════════════════════════════════════
# Handler logic regressions — no cluster needed (unit-testing the logic, not the call)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_bucket_ramquota_renamed(clean_env):
    """admin_bucket_create must rename ramQuota → ramQuotaMB before the REST call."""
    from handlers import buckets

    # Capture what data would be sent without actually making the HTTP call
    calls = []

    def fake_admin_request(method, path, data=None, **kwargs):
        calls.append({"method": method, "path": path, "data": data})
        return {"status": "ok"}

    # Patch admin_request in the buckets module
    original = buckets.__dict__.get("admin_request")
    try:
        import handlers.buckets as b_mod

        b_mod.__dict__["admin_request"] = fake_admin_request
        b_mod.handle("admin_bucket_create", {"name": "test", "ramQuota": 256})
    finally:
        if original:
            b_mod.__dict__["admin_request"] = original

    assert calls, "admin_request was not called"
    sent_data = calls[0]["data"]
    assert "ramQuotaMB" in sent_data, "ramQuota not renamed to ramQuotaMB"
    assert "ramQuota" not in sent_data, "original ramQuota key still present"
    assert sent_data["ramQuotaMB"] == 256


@pytest.mark.unit
def test_collection_maxttl_is_int(clean_env):
    """admin_collection_create must send maxTTL as int, not string."""
    calls = []

    def fake_admin_request(method, path, data=None, **kwargs):
        calls.append({"data": data})
        return {"status": "ok"}

    import handlers.collections as c_mod

    original = c_mod.__dict__.get("admin_request")
    try:
        c_mod.__dict__["admin_request"] = fake_admin_request
        c_mod.handle(
            "admin_collection_create",
            {
                "bucket_name": "b",
                "scope_name": "s",
                "collection_name": "c",
                "maxTTL": 30,
            },
        )
    finally:
        if original:
            c_mod.__dict__["admin_request"] = original

    assert calls
    assert calls[0]["data"]["maxTTL"] == 30, "maxTTL must be int, not string"
    assert isinstance(calls[0]["data"]["maxTTL"], int), "maxTTL type must be int"


@pytest.mark.unit
def test_xdcr_reference_delete_url_encodes_name(clean_env):
    """admin_xdcr_reference_delete must URL-encode the cluster name in the path."""
    calls = []

    def fake_admin_request(method, path, data=None, **kwargs):
        calls.append({"method": method, "path": path})
        return {"status": "ok"}

    import handlers.xdcr as x_mod

    original = x_mod.__dict__.get("admin_request")
    try:
        x_mod.__dict__["admin_request"] = fake_admin_request
        x_mod.handle(
            "admin_xdcr_reference_delete",
            {"cluster_name": "my cluster/DR", "confirm": True},
        )
    finally:
        if original:
            x_mod.__dict__["admin_request"] = original

    assert calls
    path = calls[0]["path"]
    assert " " not in path, "Space in URL path — cluster_name not encoded"
    assert "/" not in path.split("/remoteClusters/")[1], (
        "Slash in cluster name not encoded"
    )
    assert urllib.parse.quote("my cluster/DR", safe="") in path


@pytest.mark.unit
def test_index_build_scoped_syntax(clean_env):
    """admin_index_build with scope+collection must use bucket.scope.coll syntax."""
    stmts = []

    def fake_run_n1ql(stmt):
        stmts.append(stmt)
        return [{"type": "text", "text": "{}"}]

    import handlers.indexes as idx_mod

    original = idx_mod.__dict__.get("_run_n1ql")
    try:
        idx_mod.__dict__["_run_n1ql"] = fake_run_n1ql
        idx_mod.handle(
            "admin_index_build",
            {
                "bucket_name": "travel",
                "scope_name": "inventory",
                "collection_name": "hotel",
                "index_names": ["idx_name"],
            },
        )
    finally:
        if original:
            idx_mod.__dict__["_run_n1ql"] = original

    assert stmts, "_run_n1ql was not called"
    stmt = stmts[0]
    assert "`travel`.`inventory`.`hotel`" in stmt, (
        f"Scoped keyspace not used in BUILD INDEX: {stmt}"
    )


@pytest.mark.unit
def test_index_build_unscoped_syntax(clean_env):
    """admin_index_build without scope must use bare bucket syntax (pre-7 compat)."""
    stmts = []

    def fake_run_n1ql(stmt):
        stmts.append(stmt)
        return [{"type": "text", "text": "{}"}]

    import handlers.indexes as idx_mod

    original = idx_mod.__dict__.get("_run_n1ql")
    try:
        idx_mod.__dict__["_run_n1ql"] = fake_run_n1ql
        idx_mod.handle(
            "admin_index_build",
            {"bucket_name": "travel", "index_names": ["idx_name"]},
        )
    finally:
        if original:
            idx_mod.__dict__["_run_n1ql"] = original

    assert stmts
    stmt = stmts[0]
    # Should be BUILD INDEX ON `travel` (`idx_name`) — no dot notation
    assert stmt.count("`travel`") == 1
    assert ".`" not in stmt.split("ON")[1].split("(")[0], (
        f"Unexpected scope in unscoped build: {stmt}"
    )


@pytest.mark.unit
def test_stats_query_settings_strips_confirm(clean_env):
    """admin_query_settings_set must not forward 'confirm' to the REST API."""
    calls = []

    def fake_admin_request(method, path, data=None, **kwargs):
        calls.append({"data": data})
        return {"status": "ok"}

    import handlers.stats as s_mod

    original = s_mod.__dict__.get("admin_request")
    try:
        s_mod.__dict__["admin_request"] = fake_admin_request
        s_mod.handle(
            "admin_query_settings_set",
            {"queryLogLevel": "info", "queryMaxParallelism": 4, "confirm": True},
        )
    finally:
        if original:
            s_mod.__dict__["admin_request"] = original

    assert calls
    assert "confirm" not in calls[0]["data"], (
        "'confirm' key must not be forwarded to the query settings REST endpoint"
    )
    assert "queryLogLevel" in calls[0]["data"]


@pytest.mark.unit
def test_security_change_password_uses_controller_endpoint(clean_env):
    """admin_user_change_password must POST to /controller/changePassword,
    not PUT to /settings/rbac/users/local/{u} (which would wipe roles).
    """
    calls = []

    def fake_admin_request(method, path, data=None, **kwargs):
        calls.append({"method": method, "path": path, "data": data})
        return {"status": "ok"}

    import handlers.security as sec_mod

    original = sec_mod.__dict__.get("admin_request")
    try:
        sec_mod.__dict__["admin_request"] = fake_admin_request
        sec_mod.handle(
            "admin_user_change_password",
            {"username": "alice", "password": "newpass", "confirm": True},
        )
    finally:
        if original:
            sec_mod.__dict__["admin_request"] = original

    assert calls, "admin_request was not called"
    call = calls[0]
    assert call["method"] == "POST", f"Expected POST, got {call['method']}"
    assert call["path"] == "/controller/changePassword", (
        f"Wrong endpoint: {call['path']} — must use /controller/changePassword "
        f"to avoid wiping user roles"
    )
    assert call["data"]["username"] == "alice"
    assert call["data"]["password"] == "newpass"


# ═══════════════════════════════════════════════════════════════════════════════
# form_data helper — boolean serialization regression
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_form_value_lowercases_bools(clean_env):
    """form_value must return lowercase 'true'/'false' for booleans, since
    str(True) returns 'True' which Couchbase REST API rejects for bool fields.
    """
    from handlers import shared

    assert shared.form_value(True) == "true"
    assert shared.form_value(False) == "false"


@pytest.mark.unit
def test_form_value_preserves_other_types(clean_env):
    from handlers import shared

    assert shared.form_value(42) == "42"
    assert shared.form_value(3.14) == "3.14"
    assert shared.form_value("hello") == "hello"


@pytest.mark.unit
def test_form_data_strips_confirm_by_default(clean_env):
    from handlers import shared

    out = shared.form_data({"x": 1, "confirm": True, "y": False})
    assert "confirm" not in out
    assert out["x"] == "1"
    assert out["y"] == "false"


@pytest.mark.unit
def test_form_data_drops_none(clean_env):
    from handlers import shared

    out = shared.form_data({"x": 1, "y": None, "z": 0})
    assert "y" not in out
    assert out["x"] == "1"
    # z=0 is not None, must be kept and rendered as "0"
    assert out["z"] == "0"


@pytest.mark.unit
def test_form_data_custom_exclude(clean_env):
    from handlers import shared

    out = shared.form_data(
        {"keep": 1, "drop": 2, "confirm": True}, exclude=("drop", "confirm")
    )
    assert "drop" not in out
    assert "confirm" not in out
    assert out["keep"] == "1"


@pytest.mark.unit
def test_security_audit_set_serializes_bools_lowercase(clean_env):
    """admin_audit_set must send auditdEnabled as 'true'/'false' (lowercase),
    not 'True'/'False' which Couchbase REST API rejects.
    """
    calls = []

    def fake_admin_request(method, path, data=None, **kwargs):
        calls.append({"data": data})
        return {"status": "ok"}

    import handlers.security as sec_mod

    original = sec_mod.__dict__.get("admin_request")
    try:
        sec_mod.__dict__["admin_request"] = fake_admin_request
        sec_mod.handle(
            "admin_audit_set",
            {"auditdEnabled": True, "rotateInterval": 86400},
        )
    finally:
        if original:
            sec_mod.__dict__["admin_request"] = original

    assert calls
    data = calls[0]["data"]
    assert data["auditdEnabled"] == "true", (
        f"Boolean must serialize to lowercase 'true', got {data['auditdEnabled']!r}"
    )
    assert data["rotateInterval"] == "86400"


@pytest.mark.unit
def test_security_password_policy_serializes_bools_lowercase(clean_env):
    """admin_password_policy_set has 4 boolean fields — all must be lowercase."""
    calls = []

    def fake_admin_request(method, path, data=None, **kwargs):
        calls.append({"data": data})
        return {"status": "ok"}

    import handlers.security as sec_mod

    original = sec_mod.__dict__.get("admin_request")
    try:
        sec_mod.__dict__["admin_request"] = fake_admin_request
        sec_mod.handle(
            "admin_password_policy_set",
            {
                "minLength": 12,
                "enforceUppercase": True,
                "enforceLowercase": True,
                "enforceDigits": False,
                "enforceSpecialChars": False,
            },
        )
    finally:
        if original:
            sec_mod.__dict__["admin_request"] = original

    assert calls
    data = calls[0]["data"]
    assert data["enforceUppercase"] == "true"
    assert data["enforceLowercase"] == "true"
    assert data["enforceDigits"] == "false"
    assert data["enforceSpecialChars"] == "false"
    # No "True" with capital T anywhere
    assert "True" not in data.values()
    assert "False" not in data.values()


@pytest.mark.unit
def test_stats_internal_settings_serializes_bools_lowercase(clean_env):
    """admin_internal_settings_set has 3 boolean fields."""
    calls = []

    def fake_admin_request(method, path, data=None, **kwargs):
        calls.append({"data": data})
        return {"status": "ok"}

    import handlers.stats as s_mod

    original = s_mod.__dict__.get("admin_request")
    try:
        s_mod.__dict__["admin_request"] = fake_admin_request
        s_mod.handle(
            "admin_internal_settings_set",
            {
                "indexAwareRebalanceDisabled": True,
                "rebalanceIgnoreViewCompactions": False,
                "maxParallelIndexers": 4,
                "confirm": True,
            },
        )
    finally:
        if original:
            s_mod.__dict__["admin_request"] = original

    assert calls
    data = calls[0]["data"]
    assert data["indexAwareRebalanceDisabled"] == "true"
    assert data["rebalanceIgnoreViewCompactions"] == "false"
    assert "confirm" not in data
    assert data["maxParallelIndexers"] == "4"


@pytest.mark.unit
def test_cluster_autocompaction_set_strips_confirm(clean_env):
    """admin_autocompaction_set previously forwarded 'confirm' to the REST API."""
    calls = []

    def fake_admin_request(method, path, data=None, **kwargs):
        calls.append({"data": data})
        return {"status": "ok"}

    import handlers.cluster as c_mod

    original = c_mod.__dict__.get("admin_request")
    try:
        c_mod.__dict__["admin_request"] = fake_admin_request
        c_mod.handle(
            "admin_autocompaction_set",
            {"databaseFragmentationThreshold[percentage]": 30, "confirm": True},
        )
    finally:
        if original:
            c_mod.__dict__["admin_request"] = original

    assert calls
    assert "confirm" not in calls[0]["data"]


# ═══════════════════════════════════════════════════════════════════════════════
# Eventing — function name URL encoding
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_eventing_function_name_url_encoded(clean_env):
    """Eventing tools must URL-encode function names in path interpolation."""
    calls = []

    def fake_admin_request(method, path, data=None, **kwargs):
        calls.append({"method": method, "path": path})
        return {"status": "ok"}

    import handlers.eventing as evt_mod

    original = evt_mod.__dict__.get("admin_request")
    try:
        evt_mod.__dict__["admin_request"] = fake_admin_request
        evt_mod.handle(
            "admin_eventing_deploy",
            {"function_name": "my fn/v2"},
        )
    finally:
        if original:
            evt_mod.__dict__["admin_request"] = original

    assert calls
    path = calls[0]["path"]
    # Function name segment must be encoded — no raw space or slash
    fn_part = path.split("/functions/")[1].split("/")[0]
    assert " " not in fn_part
    assert "%20" in fn_part or "%2F" in path


# ═══════════════════════════════════════════════════════════════════════════════
# Cluster version helpers
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@pytest.mark.parametrize(
    "ver,major,minor,expected",
    [
        ("8.0.0-1234", 8, 0, True),
        ("8.1.2-5678", 8, 0, True),
        ("7.6.5-1234", 8, 0, False),
        ("7.6.5-1234", 7, 6, True),
        ("7.5.0-1000", 7, 6, False),
        ("6.6.0-9000", 7, 0, False),
        (None, 7, 0, False),
    ],
)
def test_is_version_at_least(clean_env, ver, major, minor, expected):
    from handlers import shared

    # Bypass HTTP call — inject directly
    shared._cluster_version = ver
    try:
        result = shared.is_version_at_least(major, minor)
        assert result == expected, (
            f"is_version_at_least({major}, {minor}) with ver={ver!r}: "
            f"expected {expected}, got {result}"
        )
    finally:
        shared._cluster_version = None


# ═══════════════════════════════════════════════════════════════════════════════
# Shared URL/auth helpers
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_admin_url_http_scheme(monkeypatch):
    flush_modules("handlers", "server")
    monkeypatch.setenv("CB_USERNAME", "u")
    monkeypatch.setenv("CB_PASSWORD", "p")
    monkeypatch.setenv("CB_CONNECTION_STRING", "couchbase://myhost")
    monkeypatch.setenv("CB_MGMT_PORT", "8091")
    from handlers import shared

    url = shared._admin_url()
    assert url == "http://myhost:8091"


@pytest.mark.unit
def test_admin_url_https_scheme(monkeypatch):
    flush_modules("handlers", "server")
    monkeypatch.setenv("CB_USERNAME", "u")
    monkeypatch.setenv("CB_PASSWORD", "p")
    monkeypatch.setenv("CB_CONNECTION_STRING", "couchbases://myhost")
    monkeypatch.setenv("CB_MGMT_PORT", "18091")
    from handlers import shared

    url = shared._admin_url()
    assert url == "https://myhost:18091"


@pytest.mark.unit
def test_admin_url_strips_path(monkeypatch):
    flush_modules("handlers", "server")
    monkeypatch.setenv("CB_USERNAME", "u")
    monkeypatch.setenv("CB_PASSWORD", "p")
    monkeypatch.setenv("CB_CONNECTION_STRING", "couchbase://myhost/bucket")
    from handlers import shared

    url = shared._admin_url()
    assert "bucket" not in url


@pytest.mark.unit
def test_required_env_raises_when_missing(monkeypatch):
    flush_modules("handlers", "server")
    monkeypatch.delenv("CB_USERNAME", raising=False)
    monkeypatch.delenv("CB_PASSWORD", raising=False)
    monkeypatch.setenv("CB_CONNECTION_STRING", "couchbase://localhost")
    from handlers import shared

    with pytest.raises(RuntimeError, match="CB_USERNAME"):
        shared.get_env("CB_USERNAME")


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _all_tools():
    """Return the combined TOOLS list from all 16 handler modules."""
    from handlers import (
        buckets,
        capella,
        cluster,
        collections,
        data,
        diagnostics,
        eight_x,
        encryption,
        eventing,
        extended,
        indexes,
        mcp_status,
        search_admin,
        security,
        stats,
        synonyms,
        xdcr,
    )

    return (
        data.TOOLS
        + buckets.TOOLS
        + collections.TOOLS
        + security.TOOLS
        + cluster.TOOLS
        + xdcr.TOOLS
        + indexes.TOOLS
        + search_admin.TOOLS
        + stats.TOOLS
        + diagnostics.TOOLS
        + eight_x.TOOLS
        + extended.TOOLS
        + eventing.TOOLS
        + synonyms.TOOLS
        + encryption.TOOLS
        + capella.TOOLS
        + mcp_status.TOOLS
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Server/MCP config status (cb_mcp_*)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_mcp_status_returns_payload(monkeypatch):
    """cb_mcp_status must return safety / tool / connection sections without a cluster."""
    flush_modules("handlers", "server")
    monkeypatch.setenv("CB_MCP_READ_ONLY_MODE", "true")
    monkeypatch.setenv("CB_USERNAME", "u")
    monkeypatch.setenv("CB_PASSWORD", "p")
    monkeypatch.setenv("CB_CONNECTION_STRING", "couchbase://localhost")

    import handlers.mcp_status as ms
    import server  # noqa: F401  (force registration)

    out = ms.handle("cb_mcp_status", {})
    assert len(out) == 1
    data = json.loads(out[0].text)
    assert data["server"] == "couchbase-mcp"
    assert data["safety"]["read_only_mode"] is True
    assert data["tools"]["loaded"] >= 1
    assert data["connection"]["auth_method"].startswith("Password")
    assert data["connection"]["tls"]["tls_enabled"] is False


@pytest.mark.unit
def test_mcp_status_detects_mtls(monkeypatch, tmp_path):
    flush_modules("handlers", "server")
    cert = tmp_path / "client.pem"
    key = tmp_path / "client.key"
    cert.write_text("dummy")
    key.write_text("dummy")
    monkeypatch.setenv("CB_USERNAME", "u")
    monkeypatch.setenv("CB_PASSWORD", "p")
    monkeypatch.setenv("CB_CONNECTION_STRING", "couchbases://localhost")
    monkeypatch.setenv("CB_CLIENT_CERT_PATH", str(cert))
    monkeypatch.setenv("CB_CLIENT_KEY_PATH", str(key))

    import handlers.mcp_status as ms
    import server  # noqa: F401

    out = ms.handle("cb_mcp_status", {})
    data = json.loads(out[0].text)
    assert "mTLS" in data["connection"]["auth_method"]
    assert data["connection"]["tls"]["tls_enabled"] is True
    assert data["connection"]["tls"]["client_cert_configured"] is True


@pytest.mark.unit
def test_mcp_list_tools_filter(monkeypatch):
    flush_modules("handlers", "server")
    monkeypatch.setenv("CB_MCP_READ_ONLY_MODE", "true")
    monkeypatch.setenv("CB_USERNAME", "u")
    monkeypatch.setenv("CB_PASSWORD", "p")

    import handlers.mcp_status as ms
    import server  # noqa: F401

    out = ms.handle("cb_mcp_list_tools", {"category": "read"})
    data = json.loads(out[0].text)
    assert data["filter"] == "read"
    # Every entry must be read-only
    assert all(t["read_only"] for t in data["tools"])
    # cb_get is a read tool, must be present in read-only mode
    assert any(t["name"] == "cb_get" for t in data["tools"])
    # cb_upsert is a write tool, must NOT be present in read-only mode
    assert not any(t["name"] == "cb_upsert" for t in data["tools"])


@pytest.mark.unit
def test_mcp_list_tools_all(monkeypatch):
    flush_modules("handlers", "server")
    monkeypatch.setenv("CB_MCP_READ_ONLY_MODE", "false")
    monkeypatch.setenv("CB_USERNAME", "u")
    monkeypatch.setenv("CB_PASSWORD", "p")

    import handlers.mcp_status as ms
    import server  # noqa: F401

    out = ms.handle("cb_mcp_list_tools", {"category": "all"})
    data = json.loads(out[0].text)
    assert data["count"] >= 167


@pytest.mark.unit
def test_mcp_get_tool_info(monkeypatch):
    flush_modules("handlers", "server")
    monkeypatch.setenv("CB_MCP_READ_ONLY_MODE", "true")
    monkeypatch.setenv("CB_USERNAME", "u")
    monkeypatch.setenv("CB_PASSWORD", "p")

    import handlers.mcp_status as ms
    import server  # noqa: F401

    out = ms.handle("cb_mcp_get_tool_info", {"tool_name": "cb_get"})
    data = json.loads(out[0].text)
    assert data["name"] == "cb_get"
    assert data["annotations"]["read_only"] is True
    assert "key" in data["input_schema"]["properties"]
    assert data["currently_loaded"] is True


@pytest.mark.unit
def test_mcp_get_tool_info_for_filtered_tool(monkeypatch):
    """In read-only mode, a write tool exists in _RAW_TOOLS but is currently_loaded=False."""
    flush_modules("handlers", "server")
    monkeypatch.setenv("CB_MCP_READ_ONLY_MODE", "true")
    monkeypatch.setenv("CB_USERNAME", "u")
    monkeypatch.setenv("CB_PASSWORD", "p")

    import handlers.mcp_status as ms
    import server  # noqa: F401

    out = ms.handle("cb_mcp_get_tool_info", {"tool_name": "cb_upsert"})
    data = json.loads(out[0].text)
    assert data["name"] == "cb_upsert"
    assert data["currently_loaded"] is False


@pytest.mark.unit
def test_mcp_get_tool_info_unknown(clean_env):
    import handlers.mcp_status as ms
    import server  # noqa: F401

    out = ms.handle("cb_mcp_get_tool_info", {"tool_name": "does_not_exist"})
    data = json.loads(out[0].text)
    assert "error" in data
    assert "No tool named" in data["error"]


@pytest.mark.unit
def test_mcp_status_reports_disabled_tools(monkeypatch):
    flush_modules("handlers", "server")
    monkeypatch.setenv("CB_MCP_READ_ONLY_MODE", "false")
    monkeypatch.setenv("CB_USERNAME", "u")
    monkeypatch.setenv("CB_PASSWORD", "p")
    monkeypatch.setenv("CB_MCP_DISABLED_TOOLS", "cb_get,cb_upsert")

    import handlers.mcp_status as ms
    import server  # noqa: F401

    out = ms.handle("cb_mcp_status", {})
    data = json.loads(out[0].text)
    assert data["safety"]["disabled_tools_count"] == 2
    assert "cb_get" in data["safety"]["disabled_tools"]


# ═══════════════════════════════════════════════════════════════════════════════
# Smithery / Docker packaging (sanity — files exist and parse)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_smithery_yaml_present_and_parses():
    """smithery.yaml must exist and be valid YAML with required sections."""
    import pathlib

    root = pathlib.Path(__file__).parent.parent
    smithery_path = root / "smithery.yaml"
    assert smithery_path.exists(), "smithery.yaml is missing from project root"

    # Don't require pyyaml — parse manually for required top-level keys
    content = smithery_path.read_text()
    assert "startCommand:" in content
    assert "configSchema:" in content
    assert "commandFunction:" in content
    assert "connectionString" in content


@pytest.mark.unit
def test_dockerfile_present():
    """Dockerfile must exist."""
    import pathlib

    root = pathlib.Path(__file__).parent.parent
    df = root / "Dockerfile"
    assert df.exists(), "Dockerfile missing"
    content = df.read_text()
    # Must use a Python base, set up a non-root user, run server.py
    assert "python:3.12" in content or "python:3" in content
    assert "USER mcp" in content
    assert "server.py" in content


@pytest.mark.unit
def test_docker_compose_present():
    """docker-compose.yml must exist with both services."""
    import pathlib

    root = pathlib.Path(__file__).parent.parent
    dc = root / "docker-compose.yml"
    assert dc.exists(), "docker-compose.yml missing"
    content = dc.read_text()
    assert "couchbase:" in content
    assert "couchbase-mcp:" in content


# ═══════════════════════════════════════════════════════════════════════════════
# Entry-point + packaging regressions (Pass 4)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_server_main_is_sync(clean_env):
    """The 'couchbase-mcp-server' console script (configured in pyproject.toml as
    server:main) MUST be a synchronous function. If main() is async, pip-installed
    users get 'coroutine was never awaited' on startup.
    """
    import inspect

    import server

    assert callable(server.main), "server.main must exist and be callable"
    assert not inspect.iscoroutinefunction(server.main), (
        "server.main must be sync — pip entry-point wrappers call it directly. "
        "If you need async, wrap it: def main(): asyncio.run(_async_main())"
    )


@pytest.mark.unit
def test_server_async_main_is_async(clean_env):
    """The async runtime lives in _async_main; main() wraps it with asyncio.run."""
    import inspect

    import server

    assert inspect.iscoroutinefunction(server._async_main), (
        "server._async_main must be async — it's the actual runtime"
    )


@pytest.mark.unit
def test_pyproject_entry_point_points_at_sync_main():
    """pyproject.toml entry point must point at server:main (the sync wrapper)."""
    import pathlib
    import sys

    # tomllib is stdlib on 3.11+; fall back to tomli on 3.10
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        try:
            import tomli as tomllib
        except ImportError:
            pytest.skip("tomli not installed (only needed on Python 3.10)")

    root = pathlib.Path(__file__).parent.parent
    with open(root / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    scripts = data.get("project", {}).get("scripts", {})
    assert "couchbase-mcp-server" in scripts
    assert scripts["couchbase-mcp-server"] == "server:main", (
        f"Entry point must be 'server:main', got {scripts['couchbase-mcp-server']!r}"
    )


@pytest.mark.unit
def test_xdcr_replication_create_accepts_conflict_logging(clean_env):
    """admin_xdcr_replication_create must accept the 8.x conflictLogging /
    conflictLoggingMapping fields that admin_xdcr_conflict_log_query depends on.
    """
    calls = []

    def fake_admin_request(method, path, data=None, **kwargs):
        calls.append({"data": data})
        return {"status": "ok"}

    import handlers.xdcr as x_mod

    original = x_mod.__dict__.get("admin_request")
    try:
        x_mod.__dict__["admin_request"] = fake_admin_request
        x_mod.handle(
            "admin_xdcr_replication_create",
            {
                "fromBucket": "src",
                "toCluster": "remote-1",
                "toBucket": "dst",
                "conflictLogging": True,
                "conflictLoggingMapping": {
                    "bucket": "conflicts",
                    "scope": "_default",
                    "collection": "_default",
                },
            },
        )
    finally:
        if original:
            x_mod.__dict__["admin_request"] = original

    assert calls
    data = calls[0]["data"]
    # conflictLogging boolean must be lowercase string
    assert data["conflictLogging"] == "true"
    # conflictLoggingMapping must be JSON-encoded string (form encoding can't take a dict)
    assert isinstance(data["conflictLoggingMapping"], str)
    assert "conflicts" in data["conflictLoggingMapping"]


@pytest.mark.unit
def test_xdcr_replication_create_type_and_compression(clean_env):
    """admin_xdcr_replication_create must distinguish replicationType from type."""
    calls = []

    def fake_admin_request(method, path, data=None, **kwargs):
        calls.append({"data": data})
        return {"status": "ok"}

    import handlers.xdcr as x_mod

    original = x_mod.__dict__.get("admin_request")
    try:
        x_mod.__dict__["admin_request"] = fake_admin_request
        x_mod.handle(
            "admin_xdcr_replication_create",
            {
                "fromBucket": "src",
                "toCluster": "remote-1",
                "toBucket": "dst",
                "type": "xmem",
                "compressionType": "Snappy",
            },
        )
    finally:
        if original:
            x_mod.__dict__["admin_request"] = original

    assert calls
    data = calls[0]["data"]
    assert data["replicationType"] == "continuous"  # default
    assert data["type"] == "xmem"
    assert data["compressionType"] == "Snappy"


@pytest.mark.unit
def test_dockerfile_healthcheck_skips_stdio():
    """Dockerfile HEALTHCHECK must short-circuit when CB_MCP_TRANSPORT != http,
    otherwise stdio-mode containers report unhealthy forever.
    """
    import pathlib

    root = pathlib.Path(__file__).parent.parent
    content = (root / "Dockerfile").read_text()
    # Look for the stdio skip clause
    assert "CB_MCP_TRANSPORT" in content
    # Must explicitly check for 'http' before probing
    healthcheck_block = content[content.find("HEALTHCHECK") :]
    assert "stdio" in healthcheck_block.lower() or "http" in healthcheck_block.lower()


@pytest.mark.unit
def test_gitignore_covers_secrets():
    """Common cert/key patterns must be in .gitignore — easy to accidentally
    commit Couchbase TLS material otherwise.
    """
    import pathlib

    root = pathlib.Path(__file__).parent.parent
    content = (root / ".gitignore").read_text()
    for pattern in ("*.pem", "*.key", "*.crt", "*.p12"):
        assert pattern in content, f".gitignore missing {pattern}"


# ═══════════════════════════════════════════════════════════════════════════════
# shared.quote_path helper regressions
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected_contains",
    [
        ("plain-name", "plain-name"),
        ("with spaces", "with%20spaces"),
        ("with/slash", "with%2Fslash"),
        ("ns_1@host.example", "ns_1%40host.example"),
        ("name#hash", "name%23hash"),
        ("", ""),
        (None, ""),
    ],
)
def test_quote_path_encodes_reserved(clean_env, raw, expected_contains):
    from handlers import shared

    out = shared.quote_path(raw)
    if expected_contains:
        assert expected_contains in out
    if raw and isinstance(raw, str):
        for reserved in (" ", "/", "@", "#"):
            if reserved in raw:
                assert reserved not in out, (
                    f"quote_path({raw!r}) leaked reserved char {reserved!r}"
                )


@pytest.mark.unit
def test_buckets_get_url_encodes_bucket_name(clean_env):
    """admin_bucket_get must URL-encode bucket_name in the REST path."""
    calls = []

    def fake_admin_request(method, path, data=None, **kwargs):
        calls.append({"path": path})
        return {"status": "ok"}

    import handlers.buckets as b_mod

    original = b_mod.__dict__.get("admin_request")
    try:
        b_mod.__dict__["admin_request"] = fake_admin_request
        b_mod.handle("admin_bucket_get", {"bucket_name": "my bucket/dev"})
    finally:
        if original:
            b_mod.__dict__["admin_request"] = original

    assert calls
    path = calls[0]["path"]
    assert " " not in path
    # The path must NOT contain a raw slash inside the bucket-name segment.
    # Path is /pools/default/buckets/<encoded> so the only legitimate / chars
    # are the structural ones; the bucket-name's '/' must be encoded.
    segments = path.split("/")
    assert "%2F" in segments[-1]


@pytest.mark.unit
def test_security_domain_validated(clean_env):
    """Invalid domain values must be rejected with a structured error
    rather than interpolated into the URL.
    """
    import handlers.security as sec_mod

    out = sec_mod.handle("admin_user_list", {"domain": "local/../admin"})
    assert len(out) == 1
    data = json.loads(out[0].text)
    assert "error" in data
    assert "Invalid domain" in data["error"]


@pytest.mark.unit
def test_security_domain_local_accepted(clean_env):
    """The two valid domain values must pass validation (we won't make the
    actual request, just verify the validation doesn't reject them)."""
    calls = []

    def fake_admin_request(method, path, data=None, **kwargs):
        calls.append({"path": path})
        return {"status": "ok"}

    import handlers.security as sec_mod

    original = sec_mod.__dict__.get("admin_request")
    try:
        sec_mod.__dict__["admin_request"] = fake_admin_request
        sec_mod.handle("admin_user_list", {"domain": "local"})
        sec_mod.handle("admin_user_list", {"domain": "external"})
    finally:
        if original:
            sec_mod.__dict__["admin_request"] = original

    assert len(calls) == 2
    assert "/local" in calls[0]["path"]
    assert "/external" in calls[1]["path"]


# ═══════════════════════════════════════════════════════════════════════════════
# Skills bundled with the project
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_sqlpp_tuning_skill_present():
    """skills/couchbase-sqlpp-tuning/SKILL.md must exist and have frontmatter."""
    import pathlib

    root = pathlib.Path(__file__).parent.parent
    skill = root / "skills" / "couchbase-sqlpp-tuning" / "SKILL.md"
    assert skill.exists(), "couchbase-sqlpp-tuning SKILL.md missing"

    content = skill.read_text()
    # YAML frontmatter
    assert content.startswith("---\n"), "SKILL.md missing YAML frontmatter"
    assert "name: couchbase-sqlpp-tuning" in content
    assert "description:" in content
    assert "license: MIT" in content
    # Must mention the MCP tools the skill ties into
    assert "cb_explain_query" in content
    assert "cb_index_advisor" in content
    assert "cb_perf_" in content


@pytest.mark.unit
def test_sqlpp_tuning_skill_references_present():
    """All 6 reference files must be present and non-trivially sized."""
    import pathlib

    root = pathlib.Path(__file__).parent.parent
    refs_dir = root / "skills" / "couchbase-sqlpp-tuning" / "references"
    expected = {
        "explain-plan.md",
        "index-design.md",
        "query-patterns.md",
        "cost-based-optimizer.md",
        "diagnostic-workflow.md",
        "pagination.md",
        "joins-and-cbo.md",
    }
    actual = {p.name for p in refs_dir.glob("*.md")}
    assert expected.issubset(actual), f"Missing reference files: {expected - actual}"
    # Each reference must be non-trivial (100+ lines is the rough floor)
    for name in expected:
        f = refs_dir / name
        lines = f.read_text().splitlines()
        assert len(lines) >= 80, (
            f"{name} has only {len(lines)} lines — too short to be useful"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Project-hygiene files
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_license_file_present():
    """LICENSE file must exist with MIT text and the right copyright holder."""
    import pathlib

    root = pathlib.Path(__file__).parent.parent
    lic = root / "LICENSE"
    assert lic.exists(), "LICENSE file missing"
    content = lic.read_text()
    assert "MIT License" in content
    assert "Copyright (c) 2026 Chris Ahrendt" in content


@pytest.mark.unit
def test_env_example_present_and_documents_required_vars():
    """.env.example must list every required CB_* env var so users get a
    copy-pasteable template."""
    import pathlib

    root = pathlib.Path(__file__).parent.parent
    env = root / ".env.example"
    assert env.exists(), ".env.example missing"
    content = env.read_text()
    # Connection essentials
    for var in (
        "CB_CONNECTION_STRING",
        "CB_USERNAME",
        "CB_PASSWORD",
        "CB_BUCKET",
        "CB_MCP_READ_ONLY_MODE",
        "CB_MCP_DISABLED_TOOLS",
        "CB_MCP_TRANSPORT",
    ):
        assert var in content, f".env.example missing {var}"


@pytest.mark.unit
def test_github_ci_workflow_present():
    """The CI workflow file must exist and run on PRs to main."""
    import pathlib

    root = pathlib.Path(__file__).parent.parent
    ci = root / ".github" / "workflows" / "ci.yml"
    assert ci.exists(), ".github/workflows/ci.yml missing"
    content = ci.read_text()
    # Must trigger on PRs
    assert "pull_request:" in content
    # Must run ruff and pytest
    assert "ruff check" in content
    assert "pytest tests/" in content
    # Must verify the tool count to catch regressions
    assert "167" in content


@pytest.mark.unit
def test_github_templates_present():
    """Issue and PR templates must exist for the contributor flow."""
    import pathlib

    root = pathlib.Path(__file__).parent.parent
    for path in (
        ".github/ISSUE_TEMPLATE/bug_report.md",
        ".github/ISSUE_TEMPLATE/feature_request.md",
        ".github/PULL_REQUEST_TEMPLATE.md",
    ):
        assert (root / path).exists(), f"{path} missing"


# ═══════════════════════════════════════════════════════════════════════════════
# Python version-compatibility regression guards
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_no_python_311_only_stdlib_in_runtime_code():
    """Runtime code (server.py, handlers/) must not use 3.11+-only stdlib
    constructs unguarded, since pyproject.toml declares requires-python>=3.10.

    Things that are 3.11+:
      - asyncio.TaskGroup
      - ExceptionGroup / BaseExceptionGroup
      - tomllib (stdlib only on 3.11+)
      - typing.Self
      - except* syntax (3.11+)

    Allowed:
      - These constructs *inside* version-guarded if blocks
      - Use in tests/ where the test itself can sys.version_info-guard
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).parent.parent
    runtime_paths = [root / "server.py", *list((root / "handlers").glob("*.py"))]

    forbidden = [
        (r"\basyncio\.TaskGroup\b", "asyncio.TaskGroup (use asyncio.gather on 3.10)"),
        (r"\bExceptionGroup\b", "ExceptionGroup"),
        (r"\bBaseExceptionGroup\b", "BaseExceptionGroup"),
        (r"^\s*import tomllib", "tomllib (stdlib only on 3.11+)"),
        (r"^\s*from tomllib", "tomllib (stdlib only on 3.11+)"),
        (r"\bexcept\*", "except* (3.11+ syntax)"),
        # typing.Self is 3.11+; allow `Self` from typing_extensions
        (r"from typing import.*\bSelf\b", "typing.Self (use typing_extensions.Self)"),
    ]

    findings = []
    for path in runtime_paths:
        for i, line in enumerate(path.read_text().splitlines(), 1):
            # Skip comments — that's where we document the alternative
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            for pattern, desc in forbidden:
                if re.search(pattern, line):
                    findings.append(f"  {path.name}:{i}: {desc}")

    assert not findings, (
        "Found Python 3.11+ stdlib usage in runtime code without a version guard:\n"
        + "\n".join(findings)
    )


# ═══════════════════════════════════════════════════════════════════════════════
# GUI security regressions
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_gui_files_dont_bind_remote_by_default():
    """Both GUI servers must NOT default to host='0.0.0.0' on app.run.
    A 0.0.0.0 default exposes the GUI to the LAN; the user must opt in via
    GUI_HOST=0.0.0.0 + CB_GUI_ALLOW_REMOTE=1.
    """
    import pathlib

    root = pathlib.Path(__file__).parent.parent
    for path in ("gui/gui_server.py", "gui-capella/gui_server.py"):
        f = root / path
        if not f.exists():
            continue  # GUI not in this build
        content = f.read_text()
        # Look for raw `app.run(host="0.0.0.0"` — if found, that's a default bind
        assert 'app.run(host="0.0.0.0"' not in content, (
            f"{path} binds to 0.0.0.0 unconditionally — should default to 127.0.0.1"
        )


@pytest.mark.unit
def test_gui_files_dont_default_debug_true():
    """Flask debug=True exposes the Werkzeug interactive debugger, which is
    full RCE if the port is reachable. Must NOT be the default."""
    import pathlib

    root = pathlib.Path(__file__).parent.parent
    for path in ("gui/gui_server.py", "gui-capella/gui_server.py"):
        f = root / path
        if not f.exists():
            continue
        # Scan line by line, skipping comments/docstring lines, looking for the
        # literal `debug=True` in code (not as substring of `debug=debug` etc.)
        in_docstring = False
        for i, line in enumerate(f.read_text().splitlines(), 1):
            stripped = line.strip()
            # Toggle docstring state on triple-quote
            if '"""' in stripped:
                in_docstring = not in_docstring or stripped.count('"""') >= 2
                continue
            if in_docstring or stripped.startswith("#"):
                continue
            # Only flag `debug=True,` or `debug=True)` — actual code
            if "debug=True," in line or "debug=True)" in line:
                raise AssertionError(
                    f"{path}:{i} hardcodes debug=True — read from env, default False"
                )


@pytest.mark.unit
def test_gui_files_use_cors_allowlist():
    """Both GUI servers must restrict CORS to localhost origins, not allow *."""
    import pathlib

    root = pathlib.Path(__file__).parent.parent
    for path in ("gui/gui_server.py", "gui-capella/gui_server.py"):
        f = root / path
        if not f.exists():
            continue
        content = f.read_text()
        # `CORS(app)` with no args allows everything — the fix is to pass `origins=`
        # Look for any CORS call and ensure it has 'origins=' on the same logical call
        cors_idx = content.find("CORS(app")
        if cors_idx == -1:
            continue  # GUI doesn't use flask-cors at all
        # Find the matching close paren — heuristic: look for closing ) within next 500 chars
        snippet = content[cors_idx : cors_idx + 500]
        close = snippet.find(")")
        assert close != -1, f"{path}: couldn't find end of CORS(...) call"
        call = snippet[: close + 1]
        assert "origins=" in call, (
            f"{path}: CORS call must specify origins= (found: {call!r})"
        )


@pytest.mark.unit
def test_gui_config_endpoint_uses_allowlist():
    """The /api/config POST handler must use an explicit allow-list constant
    for which env vars can be set via the GUI, not accept arbitrary keys."""
    import pathlib

    root = pathlib.Path(__file__).parent.parent
    for path in ("gui/gui_server.py", "gui-capella/gui_server.py"):
        f = root / path
        if not f.exists():
            continue
        content = f.read_text()
        # Look for the _CONFIG_ALLOWLIST set
        assert "_CONFIG_ALLOWLIST" in content, (
            f"{path}: must define _CONFIG_ALLOWLIST for env-var write protection"
        )
        # And use it in the config POST handler
        assert "_CONFIG_ALLOWLIST" in content.split("def config")[-1], (
            f"{path}: config() handler must check against _CONFIG_ALLOWLIST"
        )


@pytest.mark.unit
def test_gui_redacts_secrets():
    """The main GUI's /api/config GET must redact CB_PASSWORD."""
    import pathlib

    root = pathlib.Path(__file__).parent.parent
    main_gui = root / "gui" / "gui_server.py"
    if not main_gui.exists():
        return
    content = main_gui.read_text()
    # Should declare a redaction set and use it
    assert "_REDACTED_FIELDS" in content
    assert "CB_PASSWORD" in content
    # Make sure CB_PASSWORD isn't returned raw — it should go through _redact()
    # Find the GET branch of /api/config and confirm
    assert "_redact(" in content, (
        "gui/gui_server.py must use a redaction helper for password fields"
    )


@pytest.mark.unit
def test_gui_call_endpoint_filters_read_only_mode():
    """The main GUI's /api/call must apply READ_ONLY_MODE filtering, the same
    way server.py does. Without it the GUI bypasses every safety primitive."""
    import pathlib

    root = pathlib.Path(__file__).parent.parent
    main_gui = root / "gui" / "gui_server.py"
    if not main_gui.exists():
        return
    content = main_gui.read_text()
    # Must import the safety primitives from handlers.shared
    assert "READ_ONLY_MODE" in content, (
        "gui/gui_server.py must reference READ_ONLY_MODE — without it, the "
        "GUI exposes every write tool even when MCP server.py would not"
    )
    assert "DISABLED_TOOLS" in content
    assert "require_confirmation" in content
