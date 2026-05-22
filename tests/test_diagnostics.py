"""Unit tests for Phase 4 diagnostics — plan walker, summarizer, findings.

These exercise pure-Python logic without needing a Couchbase cluster.

Run from the project root:
    python -m pytest tests/test_diagnostics.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_diagnostics():
    os.environ.setdefault("CB_USERNAME", "u")
    os.environ.setdefault("CB_PASSWORD", "p")
    for m in ("handlers.shared", "handlers.diagnostics", "handlers"):
        sys.modules.pop(m, None)
    import handlers.diagnostics as d
    return d


# ── Plan walker ──────────────────────────────────────────────────────────────


def test_walk_plan_yields_top_level_operator():
    d = _fresh_diagnostics()
    plan = {"#operator": "Sequence", "~children": []}
    ops = [n["#operator"] for n in d._walk_plan(plan)]
    assert ops == ["Sequence"]


def test_walk_plan_descends_into_children():
    d = _fresh_diagnostics()
    plan = {
        "#operator": "Sequence",
        "~children": [
            {"#operator": "IndexScan3", "index": "idx_a"},
            {"#operator": "Fetch"},
            {"#operator": "InitialProject"},
        ],
    }
    ops = [n["#operator"] for n in d._walk_plan(plan)]
    assert ops == ["Sequence", "IndexScan3", "Fetch", "InitialProject"]


def test_walk_plan_handles_deeply_nested():
    d = _fresh_diagnostics()
    plan = {
        "#operator": "Authorize",
        "~child": {
            "#operator": "Sequence",
            "~children": [
                {
                    "#operator": "Parallel",
                    "~child": {"#operator": "IndexScan3", "index": "deep_idx"},
                },
                {"#operator": "Fetch"},
            ],
        },
    }
    ops = [n["#operator"] for n in d._walk_plan(plan)]
    assert "IndexScan3" in ops
    assert "Authorize" in ops
    assert "Parallel" in ops


def test_walk_plan_handles_list_root():
    d = _fresh_diagnostics()
    plan = [{"#operator": "A"}, {"#operator": "B"}]
    ops = [n["#operator"] for n in d._walk_plan(plan)]
    assert ops == ["A", "B"]


def test_walk_plan_skips_non_operator_dicts():
    d = _fresh_diagnostics()
    plan = {
        "#operator": "X",
        "metadata": {"key": "value", "nested": {"foo": "bar"}},
        "~child": {"#operator": "Y"},
    }
    ops = [n["#operator"] for n in d._walk_plan(plan)]
    assert ops == ["X", "Y"]


# ── Plan summarizer ──────────────────────────────────────────────────────────


def test_summarize_detects_primary_scan():
    d = _fresh_diagnostics()
    plan = {
        "#operator": "Sequence",
        "~children": [
            {"#operator": "PrimaryScan3", "keyspace": "default"},
            {"#operator": "Fetch"},
        ],
    }
    s = d._summarize_plan(plan)
    assert s["has_primary_scan"] is True
    assert s["has_fetch"] is True
    assert s["indexes_used"] == []


def test_summarize_collects_index_names():
    d = _fresh_diagnostics()
    plan = {
        "~children": [
            {"#operator": "IndexScan3", "index": "idx_country"},
            {"#operator": "IndexScan", "index": "idx_legacy"},
        ],
    }
    s = d._summarize_plan(plan)
    assert "idx_country" in s["indexes_used"]
    assert "idx_legacy" in s["indexes_used"]
    assert s["has_primary_scan"] is False


def test_summarize_detects_covering_index():
    """No Fetch operator = covering index."""
    d = _fresh_diagnostics()
    plan = {
        "~children": [
            {"#operator": "IndexScan3", "index": "idx_covering"},
            {"#operator": "InitialProject"},
        ],
    }
    s = d._summarize_plan(plan)
    assert s["has_fetch"] is False


def test_summarize_detects_filter_after_scan():
    d = _fresh_diagnostics()
    plan = {
        "~children": [
            {"#operator": "IndexScan3", "index": "idx_x"},
            {"#operator": "Fetch"},
            {"#operator": "Filter", "condition": "country = 'France'"},
        ],
    }
    s = d._summarize_plan(plan)
    assert s["has_filter_after_scan"] is True


def test_summarize_filter_before_scan_not_flagged():
    """A Filter that appears before any scan operator shouldn't trigger the
    'predicate not pushed down' finding."""
    d = _fresh_diagnostics()
    plan = {
        "~children": [
            {"#operator": "Filter", "condition": "pre-scan"},  # very unusual
            {"#operator": "IndexScan3", "index": "idx_y"},
        ],
    }
    s = d._summarize_plan(plan)
    assert s["has_filter_after_scan"] is False


def test_summarize_empty_plan():
    d = _fresh_diagnostics()
    s = d._summarize_plan({})
    assert s["operators"] == []
    assert s["has_primary_scan"] is False
    assert s["has_fetch"] is False


# ── Findings ─────────────────────────────────────────────────────────────────


def test_findings_for_primary_scan():
    d = _fresh_diagnostics()
    findings = d._findings_for({
        "operators": ["PrimaryScan3"],
        "indexes_used": [],
        "has_primary_scan": True,
        "has_fetch": False,
        "has_filter_after_scan": False,
    })
    assert any("Primary key scan" in f for f in findings)
    assert any("secondary index" in f for f in findings)


def test_findings_for_covering_index():
    d = _fresh_diagnostics()
    findings = d._findings_for({
        "operators": ["IndexScan3"],
        "indexes_used": ["idx_x"],
        "has_primary_scan": False,
        "has_fetch": False,
        "has_filter_after_scan": False,
    })
    # Should mention the index used
    assert any("idx_x" in f for f in findings)
    # Should NOT mention Fetch
    assert not any("Fetch" in f for f in findings)
    # Should NOT mention primary
    assert not any("Primary key scan" in f for f in findings)


def test_findings_for_non_covering():
    d = _fresh_diagnostics()
    findings = d._findings_for({
        "operators": ["IndexScan3", "Fetch"],
        "indexes_used": ["idx_x"],
        "has_primary_scan": False,
        "has_fetch": True,
        "has_filter_after_scan": False,
    })
    assert any("not covering" in f for f in findings)


def test_findings_for_filter_pushdown_issue():
    d = _fresh_diagnostics()
    findings = d._findings_for({
        "operators": ["IndexScan3", "Filter"],
        "indexes_used": ["idx_x"],
        "has_primary_scan": False,
        "has_fetch": False,
        "has_filter_after_scan": True,
    })
    assert any("pushed down" in f for f in findings)


def test_findings_empty_plan_warning():
    d = _fresh_diagnostics()
    findings = d._findings_for({
        "operators": [],
        "indexes_used": [],
        "has_primary_scan": False,
        "has_fetch": False,
        "has_filter_after_scan": False,
    })
    assert any("Plan was empty" in f for f in findings)


# ── Keyspace and identifier formation ────────────────────────────────────────


def test_safe_ident_basic():
    d = _fresh_diagnostics()
    assert d._safe_ident("simple") == "`simple`"


def test_safe_ident_with_hyphen():
    d = _fresh_diagnostics()
    assert d._safe_ident("travel-sample") == "`travel-sample`"


def test_safe_ident_escapes_backticks():
    d = _fresh_diagnostics()
    assert d._safe_ident("bad`name") == "`bad``name`"


def test_keyspace_defaults():
    d = _fresh_diagnostics()
    assert d._keyspace("orders", None, None) == "`orders`.`_default`.`_default`"


def test_keyspace_full_path():
    d = _fresh_diagnostics()
    assert (
        d._keyspace("travel-sample", "inventory", "airport")
        == "`travel-sample`.`inventory`.`airport`"
    )


# ── Tool registration ────────────────────────────────────────────────────────


def test_diagnostics_exports_ten_tools():
    d = _fresh_diagnostics()
    assert len(d.TOOLS) == 10


def test_all_diagnostics_tools_are_read_only():
    """Every Phase 4 tool reads system catalogs or wraps EXPLAIN — none mutate."""
    d = _fresh_diagnostics()
    for t in d.TOOLS:
        assert t.annotations.readOnlyHint is True, f"{t.name} should be read-only"
        assert t.annotations.destructiveHint is False, f"{t.name} should not be destructive"


def test_diagnostics_tools_have_required_naming():
    """The official-MCP-equivalent tools follow the cb_ prefix convention."""
    d = _fresh_diagnostics()
    expected = {
        "cb_get_schema_for_collection",
        "cb_index_advisor",
        "cb_explain_query",
        "cb_perf_longest_running",
        "cb_perf_most_frequent",
        "cb_perf_largest_responses",
        "cb_perf_large_result_count",
        "cb_perf_using_primary_index",
        "cb_perf_not_using_covering_index",
        "cb_perf_not_selective",
    }
    actual = {t.name for t in d.TOOLS}
    assert actual == expected
