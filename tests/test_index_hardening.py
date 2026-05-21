"""Unit tests for the critical Phase 1 hardening: admin_index_create and
admin_index_drop must reject arbitrary SQL++ passed via the `statement` param.

These tests verify that the validation triggers BEFORE any SDK call, so they
don't require a live cluster.

Run from the project root:
    python -m pytest tests/test_index_hardening.py -v
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_indexes():
    os.environ.setdefault("CB_USERNAME", "Administrator")
    os.environ.setdefault("CB_PASSWORD", "password")
    for m in ("handlers.shared", "handlers.indexes", "handlers"):
        sys.modules.pop(m, None)
    import handlers.indexes as indexes

    return indexes


# ── admin_index_create rejects non-DDL ────────────────────────────────────────


def test_index_create_rejects_select():
    indexes = _fresh_indexes()
    result = indexes.handle("admin_index_create", {"statement": "SELECT * FROM t"})
    payload = json.loads(result[0].text)
    assert "error" in payload
    assert "admin_index_create" in payload["error"]


def test_index_create_rejects_delete():
    indexes = _fresh_indexes()
    result = indexes.handle("admin_index_create", {"statement": "DELETE FROM t"})
    payload = json.loads(result[0].text)
    assert "error" in payload


def test_index_create_rejects_drop():
    """DROP belongs to admin_index_drop; reject it here."""
    indexes = _fresh_indexes()
    result = indexes.handle(
        "admin_index_create", {"statement": "DROP INDEX foo ON t"}
    )
    payload = json.loads(result[0].text)
    assert "error" in payload


def test_index_create_rejects_grant_revoke():
    indexes = _fresh_indexes()
    for stmt in (
        "GRANT data_reader ON `t` TO u",
        "REVOKE data_reader FROM u",
    ):
        result = indexes.handle("admin_index_create", {"statement": stmt})
        payload = json.loads(result[0].text)
        assert "error" in payload


# ── admin_index_drop rejects non-drop DDL ────────────────────────────────────


def test_index_drop_rejects_create():
    indexes = _fresh_indexes()
    result = indexes.handle(
        "admin_index_drop", {"statement": "CREATE INDEX foo ON t(a)"}
    )
    payload = json.loads(result[0].text)
    assert "error" in payload


def test_index_drop_rejects_select():
    indexes = _fresh_indexes()
    result = indexes.handle("admin_index_drop", {"statement": "SELECT * FROM t"})
    payload = json.loads(result[0].text)
    assert "error" in payload


# ── Identifier quoting ────────────────────────────────────────────────────────


def test_safe_ident_quotes_simple_name():
    indexes = _fresh_indexes()
    assert indexes._safe_ident("travel-sample") == "`travel-sample`"


def test_safe_ident_escapes_backticks():
    """A name containing a backtick must have it doubled to prevent breakout."""
    indexes = _fresh_indexes()
    quoted = indexes._safe_ident("evil`name")
    assert quoted == "`evil``name`"


def test_safe_ident_handles_empty():
    indexes = _fresh_indexes()
    assert indexes._safe_ident("") == "``"


# ── Required-field validation ─────────────────────────────────────────────────


def test_index_create_requires_bucket_when_no_statement():
    indexes = _fresh_indexes()
    result = indexes.handle("admin_index_create", {"index_name": "foo"})
    payload = json.loads(result[0].text)
    assert "error" in payload
    assert "bucket_name" in payload["error"]


def test_index_create_requires_index_name_for_non_primary():
    indexes = _fresh_indexes()
    result = indexes.handle(
        "admin_index_create",
        {"bucket_name": "t", "fields": ["a"]},
    )
    payload = json.loads(result[0].text)
    assert "error" in payload
    assert "index_name" in payload["error"]


def test_index_create_requires_fields_for_non_primary():
    indexes = _fresh_indexes()
    result = indexes.handle(
        "admin_index_create",
        {"bucket_name": "t", "index_name": "idx1"},
    )
    payload = json.loads(result[0].text)
    assert "error" in payload
    assert "fields" in payload["error"]


def test_index_drop_requires_bucket_when_no_statement():
    indexes = _fresh_indexes()
    result = indexes.handle("admin_index_drop", {"index_name": "foo"})
    payload = json.loads(result[0].text)
    assert "error" in payload
    assert "bucket_name" in payload["error"]
