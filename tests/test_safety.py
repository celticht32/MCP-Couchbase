"""Unit tests for Phase 1 safety primitives.

These tests do NOT require a running Couchbase cluster. They exercise the
pure-Python safety logic in shared.py.

Run from the project root:
    python -m pytest tests/test_safety.py -v
"""

import importlib
import os
import sys
import tempfile

import pytest

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _reload_shared(env: dict) -> object:
    """Reload handlers.shared with the given env vars set, return the module."""
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    # Force re-import so module-level constants pick up new env
    sys.modules.pop("handlers.shared", None)
    sys.modules.pop("handlers", None)
    import handlers.shared as shared  # noqa: WPS433
    importlib.reload(shared)
    return shared


# ── Env parsing ──────────────────────────────────────────────────────────────


def test_get_env_bool_truthy_values():
    shared = _reload_shared({"FOO_BOOL": "true"})
    assert shared.get_env_bool("FOO_BOOL", False) is True
    os.environ["FOO_BOOL"] = "1"
    assert shared.get_env_bool("FOO_BOOL", False) is True
    os.environ["FOO_BOOL"] = "YES"
    assert shared.get_env_bool("FOO_BOOL", False) is True


def test_get_env_bool_falsy_values():
    shared = _reload_shared({"FOO_BOOL": "false"})
    assert shared.get_env_bool("FOO_BOOL", True) is False
    os.environ["FOO_BOOL"] = "0"
    assert shared.get_env_bool("FOO_BOOL", True) is False


def test_get_env_bool_default_when_unset():
    shared = _reload_shared({"NOT_SET_VAR": None})
    assert shared.get_env_bool("NOT_SET_VAR", True) is True
    assert shared.get_env_bool("NOT_SET_VAR", False) is False


def test_required_env_raises_when_unset():
    shared = _reload_shared({"REQUIRED_KEY": None})
    with pytest.raises(RuntimeError, match="REQUIRED_KEY"):
        shared.get_env("REQUIRED_KEY")


def test_required_env_returns_value_when_set():
    shared = _reload_shared({"REQUIRED_KEY": "hello"})
    assert shared.get_env("REQUIRED_KEY") == "hello"


# ── Tool-list parsing ────────────────────────────────────────────────────────


def test_parse_tool_list_comma_separated():
    shared = _reload_shared({})
    assert shared._parse_tool_list("a,b,c") == {"a", "b", "c"}
    assert shared._parse_tool_list("a, b , c ") == {"a", "b", "c"}


def test_parse_tool_list_empty():
    shared = _reload_shared({})
    assert shared._parse_tool_list("") == set()
    assert shared._parse_tool_list(None) == set()


def test_parse_tool_list_from_file():
    shared = _reload_shared({})
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("# this is a comment\n")
        f.write("admin_bucket_delete\n")
        f.write("\n")  # blank line
        f.write("cb_delete\n")
        path = f.name
    try:
        assert shared._parse_tool_list(path) == {"admin_bucket_delete", "cb_delete"}
    finally:
        os.unlink(path)


# ── Read-only mode ───────────────────────────────────────────────────────────


def test_read_only_mode_defaults_on():
    shared = _reload_shared({"CB_MCP_READ_ONLY_MODE": None})
    assert shared.READ_ONLY_MODE is True


def test_read_only_mode_off_when_set_false():
    shared = _reload_shared({"CB_MCP_READ_ONLY_MODE": "false"})
    assert shared.READ_ONLY_MODE is False


# ── DML detection ────────────────────────────────────────────────────────────


def test_is_dml_detects_insert():
    shared = _reload_shared({})
    assert shared.is_dml_statement("INSERT INTO t (KEY, VALUE) VALUES ('k', {})") is True


def test_is_dml_detects_upsert():
    shared = _reload_shared({})
    assert shared.is_dml_statement("UPSERT INTO t VALUES ('k', {})") is True


def test_is_dml_detects_update_delete_merge():
    shared = _reload_shared({})
    assert shared.is_dml_statement("UPDATE t SET x=1") is True
    assert shared.is_dml_statement("DELETE FROM t WHERE x=1") is True
    assert shared.is_dml_statement("MERGE INTO t USING s ON t.k = s.k") is True


def test_is_dml_detects_ddl_dcl():
    shared = _reload_shared({})
    assert shared.is_dml_statement("CREATE INDEX foo ON t(a)") is True
    assert shared.is_dml_statement("DROP INDEX foo ON t") is True
    assert shared.is_dml_statement("GRANT SELECT ON t TO u") is True


def test_is_dml_accepts_select():
    shared = _reload_shared({})
    assert shared.is_dml_statement("SELECT * FROM t") is False
    assert shared.is_dml_statement("  SELECT 1") is False


def test_is_dml_skips_comments():
    shared = _reload_shared({})
    assert shared.is_dml_statement("-- a comment\nINSERT INTO t VALUES ('k', {})") is True
    assert shared.is_dml_statement("/* block */\nDELETE FROM t") is True
    # SELECT after comments stays read
    assert shared.is_dml_statement("-- comment\nSELECT * FROM t") is False


def test_block_dml_if_readonly_blocks_writes():
    shared = _reload_shared({"CB_MCP_READ_ONLY_MODE": "true"})
    msg = shared.block_dml_if_readonly("INSERT INTO t VALUES ('k', {})")
    assert msg is not None
    assert "Read-only mode" in msg


def test_block_dml_if_readonly_allows_reads():
    shared = _reload_shared({"CB_MCP_READ_ONLY_MODE": "true"})
    assert shared.block_dml_if_readonly("SELECT * FROM t") is None


def test_block_dml_off_when_readonly_disabled():
    shared = _reload_shared({"CB_MCP_READ_ONLY_MODE": "false"})
    assert shared.block_dml_if_readonly("INSERT INTO t VALUES ('k', {})") is None


# ── Index DDL validation ─────────────────────────────────────────────────────


def test_assert_index_create_accepts_create_index():
    shared = _reload_shared({})
    assert shared.assert_index_create_ddl("CREATE INDEX foo ON t(a, b)") is None
    assert shared.assert_index_create_ddl("  create  primary  index ON t") is None


def test_assert_index_create_accepts_vector_indexes():
    shared = _reload_shared({})
    assert shared.assert_index_create_ddl(
        "CREATE HYPERSCALE VECTOR INDEX foo ON t(emb)"
    ) is None
    assert shared.assert_index_create_ddl(
        "CREATE COMPOSITE VECTOR INDEX bar ON t(emb VECTOR)"
    ) is None


def test_assert_index_create_accepts_build():
    shared = _reload_shared({})
    assert shared.assert_index_create_ddl("BUILD INDEX ON t(a, b)") is None


def test_assert_index_create_rejects_delete():
    shared = _reload_shared({})
    msg = shared.assert_index_create_ddl("DELETE FROM t WHERE 1=1")
    assert msg is not None
    assert "admin_index_create" in msg


def test_assert_index_create_rejects_select():
    shared = _reload_shared({})
    assert shared.assert_index_create_ddl("SELECT * FROM t") is not None


def test_assert_index_create_rejects_drop_index():
    shared = _reload_shared({})
    # DROP belongs to admin_index_drop, not create
    assert shared.assert_index_create_ddl("DROP INDEX foo ON t") is not None


def test_assert_index_drop_accepts_drop_index():
    shared = _reload_shared({})
    assert shared.assert_index_drop_ddl("DROP INDEX foo ON t") is None
    assert shared.assert_index_drop_ddl("DROP PRIMARY INDEX ON t") is None
    assert shared.assert_index_drop_ddl("DROP VECTOR INDEX foo ON t") is None


def test_assert_index_drop_rejects_create_or_other():
    shared = _reload_shared({})
    assert shared.assert_index_drop_ddl("CREATE INDEX foo ON t(a)") is not None
    assert shared.assert_index_drop_ddl("SELECT 1") is not None


# ── Confirmation gate ────────────────────────────────────────────────────────


def test_require_confirmation_passes_when_not_in_set():
    shared = _reload_shared({})
    assert shared.require_confirmation("cb_get", {"key": "k"}, in_confirm_set=False) is None


def test_require_confirmation_blocks_without_confirm():
    shared = _reload_shared({})
    msg = shared.require_confirmation("admin_bucket_delete", {"bucket_name": "b"}, in_confirm_set=True)
    assert msg is not None
    assert "admin_bucket_delete" in msg


def test_require_confirmation_passes_when_confirm_true():
    shared = _reload_shared({})
    msg = shared.require_confirmation(
        "admin_bucket_delete",
        {"bucket_name": "b", "confirm": True},
        in_confirm_set=True,
    )
    assert msg is None


def test_require_confirmation_rejects_truthy_but_not_true():
    """`confirm: "true"` (string) should NOT bypass the gate — only boolean True."""
    shared = _reload_shared({})
    msg = shared.require_confirmation(
        "admin_bucket_delete",
        {"bucket_name": "b", "confirm": "true"},
        in_confirm_set=True,
    )
    assert msg is not None


def test_get_confirmation_required_merges_defaults_and_custom():
    shared = _reload_shared(
        {"CB_MCP_CONFIRMATION_REQUIRED_TOOLS": "cb_query,cb_upsert"}
    )
    eff = shared.get_confirmation_required(["admin_bucket_delete", "cb_delete"])
    assert "admin_bucket_delete" in eff
    assert "cb_delete" in eff
    assert "cb_query" in eff
    assert "cb_upsert" in eff


# ── Response helpers ─────────────────────────────────────────────────────────


def test_err_includes_context():
    shared = _reload_shared({})
    result = shared.err("oops", tool="my_tool", args={"k": "v"})
    assert len(result) == 1
    import json

    payload = json.loads(result[0].text)
    assert payload["error"] == "oops"
    assert payload["tool"] == "my_tool"
    assert payload["args"] == {"k": "v"}


def test_ok_serializes_complex_types():
    shared = _reload_shared({})
    from datetime import datetime

    result = shared.ok({"when": datetime(2025, 1, 1)})
    import json

    payload = json.loads(result[0].text)
    assert "when" in payload
