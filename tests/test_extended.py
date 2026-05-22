"""Unit tests for Phase 6b — transactions, Analytics, Backup/Restore.

Pure-Python tests for input validation, op translation, and tool registration.
SDK-level transaction execution and analytics queries require a real cluster
and are not covered here.

Run from the project root:
    python -m pytest tests/test_extended.py -v
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_extended():
    os.environ.setdefault("CB_USERNAME", "u")
    os.environ.setdefault("CB_PASSWORD", "p")
    for m in ("handlers.shared", "handlers.extended", "handlers"):
        sys.modules.pop(m, None)
    import handlers.extended as e
    return e


# ── Transaction input validation (no SDK reached) ────────────────────────────


def test_transaction_rejects_missing_operations():
    e = _fresh_extended()
    result = e._transaction({})
    payload = json.loads(result[0].text)
    assert "operations" in payload["error"]


def test_transaction_rejects_empty_operations():
    e = _fresh_extended()
    result = e._transaction({"operations": []})
    payload = json.loads(result[0].text)
    assert "non-empty" in payload["error"]


def test_transaction_rejects_unknown_op():
    e = _fresh_extended()
    result = e._transaction({"operations": [
        {"op": "merge", "key": "doc1", "document": {}},
    ]})
    payload = json.loads(result[0].text)
    assert "unsupported op" in payload["error"]
    assert "merge" in payload["error"]


def test_transaction_rejects_missing_key():
    e = _fresh_extended()
    result = e._transaction({"operations": [
        {"op": "upsert", "document": {"x": 1}},
    ]})
    payload = json.loads(result[0].text)
    assert "key" in payload["error"]


def test_transaction_rejects_missing_document_for_write():
    e = _fresh_extended()
    for kind in ("insert", "upsert", "replace"):
        result = e._transaction({"operations": [
            {"op": kind, "key": "doc1"},
        ]})
        payload = json.loads(result[0].text)
        assert "document" in payload["error"], f"{kind} did not require document"


def test_transaction_remove_does_not_require_document():
    """Remove only needs a key; the SDK does an implicit get for the docref.
    The validation should accept this — actual SDK call would happen next."""
    e = _fresh_extended()
    # Patch the connection so we don't actually call the cluster.
    with patch("handlers.extended.get_sdk_connection") as mock_conn:
        mock_conn.side_effect = RuntimeError("would-have-connected")
        result = e._transaction({"operations": [{"op": "remove", "key": "doc1"}]})
        payload = json.loads(result[0].text)
        # The error should be the connection failure, not a validation error
        assert "would-have-connected" in payload["error"]
        assert "document" not in payload["error"]


def test_transaction_rejects_unknown_durability():
    e = _fresh_extended()
    with patch("handlers.extended.get_sdk_connection") as mock_conn:
        mock_conn.return_value = (MagicMock(), MagicMock(), MagicMock())
        result = e._transaction({
            "operations": [{"op": "upsert", "key": "x", "document": {}}],
            "durability": "MAJORITY_PLUS",
        })
    payload = json.loads(result[0].text)
    assert "durability" in payload["error"]


# ── Transaction op translation ───────────────────────────────────────────────


def test_translate_txn_insert():
    """insert calls ctx.insert(collection, key, document) directly."""
    e = _fresh_extended()
    ctx = MagicMock()
    coll = MagicMock(name="collection")
    e._translate_txn_op(ctx, coll, {"op": "insert", "key": "k", "document": {"x": 1}})
    ctx.insert.assert_called_once_with(coll, "k", {"x": 1})
    ctx.get.assert_not_called()


def test_translate_txn_upsert():
    """upsert calls ctx.upsert(collection, key, document) directly."""
    e = _fresh_extended()
    ctx = MagicMock()
    coll = MagicMock()
    e._translate_txn_op(ctx, coll, {"op": "upsert", "key": "k", "document": {"x": 1}})
    ctx.upsert.assert_called_once_with(coll, "k", {"x": 1})
    ctx.get.assert_not_called()


def test_translate_txn_replace_does_implicit_get():
    """replace requires a TransactionGetResult, so the MCP does the get."""
    e = _fresh_extended()
    ctx = MagicMock()
    coll = MagicMock()
    got = MagicMock(name="get_result")
    ctx.get.return_value = got
    e._translate_txn_op(ctx, coll, {"op": "replace", "key": "k", "document": {"x": 2}})
    ctx.get.assert_called_once_with(coll, "k")
    ctx.replace.assert_called_once_with(got, {"x": 2})


def test_translate_txn_remove_does_implicit_get():
    """remove also requires a TransactionGetResult."""
    e = _fresh_extended()
    ctx = MagicMock()
    coll = MagicMock()
    got = MagicMock(name="get_result")
    ctx.get.return_value = got
    e._translate_txn_op(ctx, coll, {"op": "remove", "key": "k"})
    ctx.get.assert_called_once_with(coll, "k")
    ctx.remove.assert_called_once_with(got)


def test_translate_txn_rejects_unknown():
    e = _fresh_extended()
    ctx = MagicMock()
    coll = MagicMock()
    with pytest.raises(ValueError, match="unsupported transaction op"):
        e._translate_txn_op(ctx, coll, {"op": "merge", "key": "k"})


# ── Analytics DML blocking ───────────────────────────────────────────────────


def test_analytics_blocks_dml_in_read_only_mode():
    """cb_analytics_query should reject DML when CB_MCP_READ_ONLY_MODE=true,
    same as cb_query."""
    os.environ["CB_MCP_READ_ONLY_MODE"] = "true"
    e = _fresh_extended()
    result = e._analytics({"statement": "INSERT INTO ds VALUES ('k', {})"})
    payload = json.loads(result[0].text)
    assert "Read-only mode" in payload["error"]


def test_analytics_allows_select_in_read_only_mode():
    """SELECT should make it past the DML check (then fail at the SDK because
    we don't have a real cluster, but past the gate)."""
    os.environ["CB_MCP_READ_ONLY_MODE"] = "true"
    e = _fresh_extended()
    with patch("handlers.extended.get_sdk_connection") as mock_conn:
        mock_conn.side_effect = RuntimeError("would-have-connected")
        result = e._analytics({"statement": "SELECT * FROM ds LIMIT 10"})
    payload = json.loads(result[0].text)
    # Got past the DML gate, hit the (mocked) connection failure
    assert "would-have-connected" in payload["error"]
    assert "Read-only mode" not in payload["error"]


def test_analytics_blocks_create_dataset_in_read_only_mode():
    """CREATE is in the DML regex — should be blocked, even though Analytics
    has its own DDL surface."""
    os.environ["CB_MCP_READ_ONLY_MODE"] = "true"
    e = _fresh_extended()
    result = e._analytics({"statement": "CREATE DATASET ds ON `bucket`"})
    payload = json.loads(result[0].text)
    assert "Read-only mode" in payload["error"]


# ── Backup tool endpoint paths ───────────────────────────────────────────────


def test_backup_list_repos_path():
    e = _fresh_extended()
    captured = {}

    def fake_request(method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        return {"repos": []}

    with patch("handlers.extended.admin_request", side_effect=fake_request):
        e.handle("admin_backup_repository_list", {})

    assert captured["method"] == "GET"
    assert captured["path"] == "/_p/backup/api/v1/cluster/self/repository"


def test_backup_repository_get_path():
    e = _fresh_extended()
    captured = {}

    def fake_request(method, path, **kwargs):
        captured["path"] = path
        return {}

    with patch("handlers.extended.admin_request", side_effect=fake_request):
        e.handle("admin_backup_repository_get", {"repository_id": "daily"})

    assert captured["path"] == "/_p/backup/api/v1/cluster/self/repository/daily"


def test_backup_run_posts_with_payload():
    e = _fresh_extended()
    captured = {}

    def fake_request(method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["data"] = kwargs.get("data")
        captured["json_body"] = kwargs.get("json_body")
        return {"task_id": "t1"}

    with patch("handlers.extended.admin_request", side_effect=fake_request):
        e.handle("admin_backup_run", {"repository_id": "daily", "full_backup": True})

    assert captured["method"] == "POST"
    assert captured["path"] == "/_p/backup/api/v1/cluster/self/repository/daily/backup"
    assert captured["data"] == {"full_backup": True}
    assert captured["json_body"] is True


def test_backup_restore_posts_target():
    e = _fresh_extended()
    captured = {}

    def fake_request(method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["data"] = kwargs.get("data")
        return {}

    with patch("handlers.extended.admin_request", side_effect=fake_request):
        e.handle("admin_backup_restore_run", {
            "repository_id": "daily",
            "target": {"filter_keys": ["user::*"]},
        })

    assert captured["method"] == "POST"
    assert "/restore" in captured["path"]
    assert captured["data"] == {"filter_keys": ["user::*"]}


# ── Tool registration and classification ─────────────────────────────────────


def test_extended_exports_seven_tools():
    e = _fresh_extended()
    assert len(e.TOOLS) == 7


def test_transaction_is_destructive():
    e = _fresh_extended()
    t = next(tt for tt in e.TOOLS if tt.name == "cb_transaction_run")
    assert t.annotations.destructiveHint is True


def test_analytics_marked_destructive_but_not_truly_blocked():
    """cb_analytics_query mirrors cb_query: destructiveHint=true so clients
    show the right badge, but stays loaded in read-only mode via the
    _ALWAYS_LOADED_IN_READ_ONLY set in server.py."""
    e = _fresh_extended()
    t = next(tt for tt in e.TOOLS if tt.name == "cb_analytics_query")
    assert t.annotations.destructiveHint is True
    assert t.annotations.readOnlyHint is False


def test_backup_reads_are_read_only():
    e = _fresh_extended()
    for name in ("admin_backup_repository_list", "admin_backup_repository_get",
                 "admin_backup_list"):
        t = next(tt for tt in e.TOOLS if tt.name == name)
        assert t.annotations.readOnlyHint is True, f"{name} should be read-only"


def test_backup_restore_is_destructive():
    e = _fresh_extended()
    t = next(tt for tt in e.TOOLS if tt.name == "admin_backup_restore_run")
    assert t.annotations.destructiveHint is True


def test_backup_run_is_write_not_destructive():
    """A backup READS from the cluster and WRITES to the backup repository.
    From the cluster's perspective it's read-only; from the repository's it's
    a write but not destructive (creates new backup, doesn't overwrite)."""
    e = _fresh_extended()
    t = next(tt for tt in e.TOOLS if tt.name == "admin_backup_run")
    assert t.annotations.readOnlyHint is False
    assert t.annotations.destructiveHint is False


def test_extended_expected_names():
    e = _fresh_extended()
    expected = {
        "cb_transaction_run",
        "cb_analytics_query",
        "admin_backup_repository_list",
        "admin_backup_repository_get",
        "admin_backup_list",
        "admin_backup_run",
        "admin_backup_restore_run",
    }
    actual = {t.name for t in e.TOOLS}
    assert actual == expected
