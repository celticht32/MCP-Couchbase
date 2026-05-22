"""Unit tests for Phase 5 — 8.x-only tools.

These exercise version-gating, similarity validation, and statement-construction
helpers without requiring a Couchbase cluster.

Run from the project root:
    python -m pytest tests/test_eight_x.py -v
"""

import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_eight_x():
    os.environ.setdefault("CB_USERNAME", "u")
    os.environ.setdefault("CB_PASSWORD", "p")
    for m in ("handlers.shared", "handlers.eight_x", "handlers"):
        sys.modules.pop(m, None)
    import handlers.eight_x as e
    return e


# ── Version gate ─────────────────────────────────────────────────────────────


def test_require_8x_blocks_when_not_8x():
    e = _fresh_eight_x()
    with patch("handlers.eight_x.is_8x", return_value=False):
        result = e._require_8x("admin_user_lock")
    assert result is not None
    payload = json.loads(result[0].text)
    assert "Couchbase Server 8.0" in payload["error"]
    assert payload["tool"] == "admin_user_lock"


def test_require_8x_passes_when_8x():
    e = _fresh_eight_x()
    with patch("handlers.eight_x.is_8x", return_value=True):
        result = e._require_8x("admin_user_lock")
    assert result is None


def test_handler_rejects_on_7x_without_hitting_implementation():
    """If is_8x() is False, the handler should return an error before any
    SDK or REST call is attempted."""
    e = _fresh_eight_x()
    with patch("handlers.eight_x.is_8x", return_value=False):
        result = e.handle(
            "admin_vector_index_create_hyperscale",
            {
                "bucket_name": "b", "index_name": "i", "field_name": "f",
                "dimension": 1536, "similarity": "COSINE",
            },
        )
    payload = json.loads(result[0].text)
    assert "error" in payload
    assert "8.0" in payload["error"]


# ── Identifier and keyspace helpers ──────────────────────────────────────────


def test_safe_ident_basic_and_escape():
    e = _fresh_eight_x()
    assert e._safe_ident("foo") == "`foo`"
    assert e._safe_ident("bad`name") == "`bad``name`"
    assert e._safe_ident("travel-sample") == "`travel-sample`"


def test_keyspace_with_defaults():
    e = _fresh_eight_x()
    assert e._keyspace("b", None, None) == "`b`.`_default`.`_default`"


def test_keyspace_full():
    e = _fresh_eight_x()
    assert e._keyspace("b", "s", "c") == "`b`.`s`.`c`"


# ── Similarity validation ────────────────────────────────────────────────────


def test_similarity_accepts_documented_values():
    e = _fresh_eight_x()
    for sim in ("L2_SQUARED", "DOT_PRODUCT", "COSINE"):
        assert e._validate_similarity(sim, "test") is None


def test_similarity_rejects_unknown():
    e = _fresh_eight_x()
    result = e._validate_similarity("CHEBYSHEV", "test")
    assert result is not None
    payload = json.loads(result[0].text)
    assert "similarity" in payload["error"]


def test_similarity_rejects_lowercase():
    """The cluster requires uppercase; reject anything else to give a clearer
    error than the cluster's parse error."""
    e = _fresh_eight_x()
    result = e._validate_similarity("cosine", "test")
    assert result is not None


# ── WITH clause construction ─────────────────────────────────────────────────


def test_with_clause_minimal():
    e = _fresh_eight_x()
    w = e._with_clause(
        dimension=1536, similarity="DOT_PRODUCT",
        description=None, num_replica=None, defer_build=None,
    )
    assert '"dimension": 1536' in w
    assert '"similarity": "DOT_PRODUCT"' in w
    assert "num_replica" not in w
    assert "defer_build" not in w


def test_with_clause_includes_optional_fields():
    e = _fresh_eight_x()
    w = e._with_clause(
        dimension=768, similarity="COSINE",
        description="my notes",
        num_replica=2, defer_build=True,
    )
    assert '"description": "my notes"' in w
    assert '"num_replica": 2' in w
    assert '"defer_build": true' in w


def test_with_clause_escapes_description():
    """Description is user input — must survive embedded quotes."""
    e = _fresh_eight_x()
    w = e._with_clause(
        dimension=1536, similarity="DOT_PRODUCT",
        description='hello "world"',
        num_replica=None, defer_build=None,
    )
    # json.dumps gives \" escapes
    assert '"hello \\"world\\""' in w


# ── Composite vector WHERE clause guard ──────────────────────────────────────


def test_composite_rejects_where_with_semicolon():
    e = _fresh_eight_x()
    with patch("handlers.eight_x.is_8x", return_value=True):
        result = e._vec_composite({
            "bucket_name": "b", "index_name": "i",
            "scalar_fields": ["a"], "vector_field": "emb",
            "dimension": 768, "similarity": "COSINE",
            "where_clause": "1=1; DROP INDEX foo ON `b`",
        })
    payload = json.loads(result[0].text)
    assert "error" in payload
    assert "semicolon" in payload["error"]


def test_composite_rejects_empty_scalar_fields():
    e = _fresh_eight_x()
    with patch("handlers.eight_x.is_8x", return_value=True):
        result = e._vec_composite({
            "bucket_name": "b", "index_name": "i",
            "scalar_fields": [], "vector_field": "emb",
            "dimension": 768, "similarity": "COSINE",
        })
    payload = json.loads(result[0].text)
    assert "error" in payload
    assert "scalar_fields" in payload["error"]


# ── Vector index DDL construction (SDK call mocked) ──────────────────────────


def test_hyperscale_constructs_correct_statement():
    """Capture the SQL++ statement that would be sent to the cluster."""
    e = _fresh_eight_x()
    captured = {}

    def fake_run(stmt):
        captured["statement"] = stmt
        # Return a fake ok() response
        from mcp.types import TextContent
        return [TextContent(type="text", text=json.dumps({"ok": True}))]

    with patch("handlers.eight_x.is_8x", return_value=True), \
         patch("handlers.eight_x._run_n1ql", side_effect=fake_run):
        e.handle("admin_vector_index_create_hyperscale", {
            "bucket_name": "travel-sample",
            "scope_name": "inventory",
            "collection_name": "airport",
            "index_name": "idx_emb",
            "field_name": "embedding",
            "dimension": 1536,
            "similarity": "DOT_PRODUCT",
            "defer_build": True,
        })

    stmt = captured["statement"]
    assert "CREATE HYPERSCALE VECTOR INDEX" in stmt
    assert "`idx_emb`" in stmt
    assert "`travel-sample`.`inventory`.`airport`" in stmt
    assert "`embedding` VECTOR" in stmt
    assert '"dimension": 1536' in stmt
    assert '"similarity": "DOT_PRODUCT"' in stmt
    assert '"defer_build": true' in stmt


def test_composite_constructs_correct_statement():
    e = _fresh_eight_x()
    captured = {}

    def fake_run(stmt):
        captured["statement"] = stmt
        from mcp.types import TextContent
        return [TextContent(type="text", text=json.dumps({"ok": True}))]

    with patch("handlers.eight_x.is_8x", return_value=True), \
         patch("handlers.eight_x._run_n1ql", side_effect=fake_run):
        e.handle("admin_vector_index_create_composite", {
            "bucket_name": "b",
            "scope_name": "s",
            "collection_name": "c",
            "index_name": "idx_filt",
            "scalar_fields": ["tenant_id", "status"],
            "vector_field": "embedding",
            "where_clause": "deleted = false",
            "dimension": 768,
            "similarity": "COSINE",
        })

    stmt = captured["statement"]
    assert "CREATE COMPOSITE VECTOR INDEX" in stmt
    assert "`b`.`s`.`c`" in stmt
    # Scalar prefix order preserved
    assert stmt.index("`tenant_id`") < stmt.index("`status`")
    assert stmt.index("`status`") < stmt.index("`embedding` VECTOR")
    assert "WHERE deleted = false" in stmt
    assert '"dimension": 768' in stmt


def test_composite_handles_no_where():
    e = _fresh_eight_x()
    captured = {}

    def fake_run(stmt):
        captured["statement"] = stmt
        from mcp.types import TextContent
        return [TextContent(type="text", text=json.dumps({"ok": True}))]

    with patch("handlers.eight_x.is_8x", return_value=True), \
         patch("handlers.eight_x._run_n1ql", side_effect=fake_run):
        e.handle("admin_vector_index_create_composite", {
            "bucket_name": "b", "index_name": "i",
            "scalar_fields": ["a"], "vector_field": "v",
            "dimension": 128, "similarity": "L2_SQUARED",
        })

    assert "WHERE" not in captured["statement"]


# ── User lock / unlock construct correct REST paths ─────────────────────────


def test_user_lock_calls_correct_endpoint():
    e = _fresh_eight_x()
    captured = {}

    def fake_admin_request(method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        return {"status": "ok"}

    with patch("handlers.eight_x.is_8x", return_value=True), \
         patch("handlers.eight_x.admin_request", side_effect=fake_admin_request):
        e.handle("admin_user_lock", {"username": "alice", "confirm": True})

    assert captured["method"] == "POST"
    assert captured["path"] == "/settings/rbac/users/local/alice/lock"


def test_user_unlock_calls_correct_endpoint():
    e = _fresh_eight_x()
    captured = {}

    def fake_admin_request(method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        return {"status": "ok"}

    with patch("handlers.eight_x.is_8x", return_value=True), \
         patch("handlers.eight_x.admin_request", side_effect=fake_admin_request):
        e.handle("admin_user_unlock", {"username": "alice"})

    assert captured["method"] == "POST"
    assert captured["path"] == "/settings/rbac/users/local/alice/unlock"


def test_user_temp_sets_temporary_password_flag():
    e = _fresh_eight_x()
    captured = {}

    def fake_admin_request(method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["data"] = kwargs.get("data")
        return {"status": "ok"}

    with patch("handlers.eight_x.is_8x", return_value=True), \
         patch("handlers.eight_x.admin_request", side_effect=fake_admin_request):
        e.handle("admin_user_create_temporary", {
            "username": "bob",
            "password": "Temp123!",
            "roles": "data_reader[bucket:*:*]",
            "name": "Bob",
        })

    assert captured["method"] == "PUT"
    assert captured["path"] == "/settings/rbac/users/local/bob"
    assert captured["data"]["temporaryPassword"] == "true"
    assert captured["data"]["password"] == "Temp123!"
    assert captured["data"]["roles"] == "data_reader[bucket:*:*]"
    assert captured["data"]["name"] == "Bob"


# ── Tool registration ────────────────────────────────────────────────────────


def test_eight_x_exports_seven_tools():
    e = _fresh_eight_x()
    assert len(e.TOOLS) == 7


def test_eight_x_user_lock_is_destructive():
    e = _fresh_eight_x()
    lock = next(t for t in e.TOOLS if t.name == "admin_user_lock")
    assert lock.annotations.destructiveHint is True


def test_eight_x_unlock_not_destructive():
    e = _fresh_eight_x()
    unlock = next(t for t in e.TOOLS if t.name == "admin_user_unlock")
    assert unlock.annotations.destructiveHint is False


def test_eight_x_read_tools_marked_read_only():
    e = _fresh_eight_x()
    read_tools = ("admin_xdcr_conflict_log_query", "cb_perf_by_user")
    for name in read_tools:
        t = next(tt for tt in e.TOOLS if tt.name == name)
        assert t.annotations.readOnlyHint is True, f"{name} should be read-only"


def test_eight_x_expected_names():
    e = _fresh_eight_x()
    expected = {
        "admin_vector_index_create_hyperscale",
        "admin_vector_index_create_composite",
        "admin_user_lock",
        "admin_user_unlock",
        "admin_user_create_temporary",
        "admin_xdcr_conflict_log_query",
        "cb_perf_by_user",
    }
    actual = {t.name for t in e.TOOLS}
    assert actual == expected
