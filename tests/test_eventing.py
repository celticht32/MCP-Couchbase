"""Unit tests for Phase 6c — Eventing service tools.

Pure-Python tests verifying endpoint paths and tool registration. The actual
Eventing REST proxy path is unverified against a live cluster (see module
docstring on handlers/eventing.py); these tests verify the MCP calls THE PATH
IT INTENDS TO CALL, not that the cluster accepts it.

Run from the project root:
    python -m pytest tests/test_eventing.py -v
"""

import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_eventing():
    os.environ.setdefault("CB_USERNAME", "u")
    os.environ.setdefault("CB_PASSWORD", "p")
    for m in ("handlers.shared", "handlers.eventing", "handlers"):
        sys.modules.pop(m, None)
    import handlers.eventing as e

    return e


# ── Endpoint paths ──────────────────────────────────────────────────────────


def _capture_calls(monkey_module, attr_name="admin_request"):
    """Return a (calls list, side_effect callable) pair for patching."""
    calls: list[dict] = []

    def fake(method, path, **kwargs):
        calls.append({"method": method, "path": path, **kwargs})
        return {"status": "ok"}

    return calls, fake


def test_list_path():
    e = _fresh_eventing()
    calls, fake = _capture_calls(e)
    with patch("handlers.eventing.admin_request", side_effect=fake):
        e.handle("admin_eventing_list", {})
    assert calls[0]["method"] == "GET"
    assert calls[0]["path"] == "/_p/event/api/v1/list"


def test_get_path():
    e = _fresh_eventing()
    calls, fake = _capture_calls(e)
    with patch("handlers.eventing.admin_request", side_effect=fake):
        e.handle("admin_eventing_get", {"function_name": "myfunc"})
    assert calls[0]["method"] == "GET"
    assert calls[0]["path"] == "/_p/event/api/v1/functions/myfunc"


def test_delete_path():
    e = _fresh_eventing()
    calls, fake = _capture_calls(e)
    with patch("handlers.eventing.admin_request", side_effect=fake):
        e.handle("admin_eventing_delete", {"function_name": "myfunc", "confirm": True})
    assert calls[0]["method"] == "DELETE"
    assert calls[0]["path"] == "/_p/event/api/v1/functions/myfunc"


def test_deploy_undeploy_pause_resume_paths():
    e = _fresh_eventing()
    cases = [
        ("admin_eventing_deploy", "/deploy"),
        ("admin_eventing_undeploy", "/undeploy"),
        ("admin_eventing_pause", "/pause"),
        ("admin_eventing_resume", "/resume"),
    ]
    for tool_name, suffix in cases:
        calls, fake = _capture_calls(e)
        with patch("handlers.eventing.admin_request", side_effect=fake):
            e.handle(tool_name, {"function_name": "fn", "confirm": True})
        assert calls[0]["method"] == "POST"
        expected = f"/_p/event/api/v1/functions/fn{suffix}"
        assert calls[0]["path"] == expected, (
            f"{tool_name} wrong path: {calls[0]['path']}"
        )


def test_stats_path():
    e = _fresh_eventing()
    calls, fake = _capture_calls(e)
    with patch("handlers.eventing.admin_request", side_effect=fake):
        e.handle("admin_eventing_stats", {})
    assert calls[0]["path"] == "/_p/event/api/v1/stats"


def test_status_path():
    e = _fresh_eventing()
    calls, fake = _capture_calls(e)
    with patch("handlers.eventing.admin_request", side_effect=fake):
        e.handle("admin_eventing_status", {})
    assert calls[0]["path"] == "/_p/event/api/v1/status"


# ── Create / update uses JSON body ──────────────────────────────────────────


def test_create_or_update_uses_json_payload():
    e = _fresh_eventing()
    captured = {}

    def fake_json(method, path, payload=None):
        captured["method"] = method
        captured["path"] = path
        captured["payload"] = payload
        return {"status": "ok"}

    with patch("handlers.eventing.admin_request_json", side_effect=fake_json):
        e.handle(
            "admin_eventing_create_or_update",
            {
                "function_name": "myfn",
                "definition": {
                    "appname": "myfn",
                    "appcode": "function OnUpdate(doc, meta) { log(meta.id); }",
                    "depcfg": {"source_bucket": "src", "metadata_bucket": "meta"},
                    "settings": {
                        "deployment_status": False,
                        "processing_status": False,
                    },
                },
            },
        )
    assert captured["method"] == "POST"
    assert captured["path"] == "/_p/event/api/v1/functions/myfn"
    assert captured["payload"]["appname"] == "myfn"
    assert captured["payload"]["depcfg"]["source_bucket"] == "src"


# ── 404 hint behavior ───────────────────────────────────────────────────────


def test_404_adds_path_hint():
    """When the cluster returns 404, the err() response should include a hint
    pointing at the path-assumption caveat in the module docstring."""
    e = _fresh_eventing()

    def fake(method, path, **kwargs):
        raise RuntimeError("HTTP 404 on GET /_p/event/api/v1/list: Not Found")

    with patch("handlers.eventing.admin_request", side_effect=fake):
        result = e.handle("admin_eventing_list", {})

    payload = json.loads(result[0].text)
    assert "error" in payload
    assert "404" in payload["error"]
    assert "hint" in payload
    assert "REST proxy path" in payload["hint"]


def test_non_404_error_no_hint():
    """For non-404 errors, no path hint — the issue is elsewhere."""
    e = _fresh_eventing()

    def fake(method, path, **kwargs):
        raise RuntimeError("HTTP 500: Internal Server Error")

    with patch("handlers.eventing.admin_request", side_effect=fake):
        result = e.handle("admin_eventing_list", {})

    payload = json.loads(result[0].text)
    assert "error" in payload
    assert "500" in payload["error"]
    assert "hint" not in payload  # No path hint for non-404 errors


# ── Path-building helper ─────────────────────────────────────────────────────


def test_evt_path_normalizes_leading_slash():
    e = _fresh_eventing()
    # Both forms should produce the same result
    assert e._evt_path("/list") == "/_p/event/api/v1/list"
    assert e._evt_path("list") == "/_p/event/api/v1/list"


def test_evt_path_centralized_for_easy_override():
    """The path prefix lives in one place so changing it (if a cluster uses
    a different proxy path) is a single edit."""
    e = _fresh_eventing()
    assert e._EVT_BASE == "/_p/event/api/v1"


# ── Tool registration ──────────────────────────────────────────────────────


def test_eventing_exports_ten_tools():
    e = _fresh_eventing()
    assert len(e.TOOLS) == 10


def test_eventing_expected_names():
    e = _fresh_eventing()
    expected = {
        "admin_eventing_list",
        "admin_eventing_get",
        "admin_eventing_create_or_update",
        "admin_eventing_delete",
        "admin_eventing_deploy",
        "admin_eventing_undeploy",
        "admin_eventing_pause",
        "admin_eventing_resume",
        "admin_eventing_stats",
        "admin_eventing_status",
    }
    actual = {t.name for t in e.TOOLS}
    assert actual == expected


def test_eventing_reads_are_read_only():
    e = _fresh_eventing()
    read_tools = (
        "admin_eventing_list",
        "admin_eventing_get",
        "admin_eventing_stats",
        "admin_eventing_status",
    )
    for name in read_tools:
        t = next(tt for tt in e.TOOLS if tt.name == name)
        assert t.annotations.readOnlyHint is True, f"{name} should be read-only"


def test_eventing_delete_and_undeploy_are_destructive():
    e = _fresh_eventing()
    for name in ("admin_eventing_delete", "admin_eventing_undeploy"):
        t = next(tt for tt in e.TOOLS if tt.name == name)
        assert t.annotations.destructiveHint is True, f"{name} should be destructive"


def test_eventing_pause_not_destructive():
    """Pause preserves checkpoint — it's reversible, so not destructive."""
    e = _fresh_eventing()
    t = next(tt for tt in e.TOOLS if tt.name == "admin_eventing_pause")
    assert t.annotations.destructiveHint is False


def test_eventing_deploy_not_destructive():
    """Deploy starts processing; doesn't destroy anything."""
    e = _fresh_eventing()
    t = next(tt for tt in e.TOOLS if tt.name == "admin_eventing_deploy")
    assert t.annotations.destructiveHint is False
