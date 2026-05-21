"""Unit tests for Phase 2 engineering fixes: retries, URL encoding, JSON body.

Mocks `urllib.request.urlopen` so no live cluster is required.

Run from the project root:
    python -m pytest tests/test_admin_request.py -v
"""

import json
import os
import sys
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_shared():
    """Import shared.py with required env vars set so module init doesn't fail."""
    os.environ.setdefault("CB_USERNAME", "Administrator")
    os.environ.setdefault("CB_PASSWORD", "password")
    sys.modules.pop("handlers.shared", None)
    sys.modules.pop("handlers", None)
    import handlers.shared as shared

    return shared


def _make_response(body: bytes, status: int = 200):
    """Build a mock response object compatible with urlopen context manager."""
    resp = MagicMock()
    resp.read.return_value = body
    resp.status = status
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda self, *a: None
    return resp


# ── Basic admin_request behavior ─────────────────────────────────────────────


def test_admin_request_returns_parsed_json():
    shared = _fresh_shared()
    payload = {"buckets": ["a", "b"]}
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value = _make_response(json.dumps(payload).encode())
        result = shared.admin_request("GET", "/pools/default/buckets")
    assert result == payload


def test_admin_request_returns_ok_on_empty_body():
    shared = _fresh_shared()
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value = _make_response(b"")
        result = shared.admin_request("POST", "/some/path")
    assert result == {"status": "ok"}


def test_admin_request_returns_text_for_non_json():
    shared = _fresh_shared()
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value = _make_response(b"plain text not json")
        result = shared.admin_request("GET", "/api/cfg")
    assert result["status"] == "ok"
    assert "plain text" in result["body"]


def test_admin_request_url_encodes_params():
    shared = _fresh_shared()
    captured = {}
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value = _make_response(b"{}")

        def capture(req, **kwargs):
            captured["url"] = req.full_url
            return _make_response(b"{}")

        mock_open.side_effect = capture
        shared.admin_request("GET", "/p", params={"a": "value with spaces", "b": "1"})
    assert "a=value+with+spaces" in captured["url"] or "a=value%20with%20spaces" in captured["url"]
    assert "b=1" in captured["url"]


def test_admin_request_sends_form_body_by_default():
    shared = _fresh_shared()
    captured = {}
    with patch("urllib.request.urlopen") as mock_open:
        def capture(req, **kwargs):
            captured["body"] = req.data
            captured["content_type"] = req.headers.get("Content-type")
            return _make_response(b"{}")

        mock_open.side_effect = capture
        shared.admin_request("POST", "/p", data={"name": "foo", "ram": "100"})
    assert captured["content_type"] == "application/x-www-form-urlencoded"
    assert b"name=foo" in captured["body"]
    assert b"ram=100" in captured["body"]


def test_admin_request_sends_json_body_when_requested():
    shared = _fresh_shared()
    captured = {}
    with patch("urllib.request.urlopen") as mock_open:
        def capture(req, **kwargs):
            captured["body"] = req.data
            captured["content_type"] = req.headers.get("Content-type")
            return _make_response(b"{}")

        mock_open.side_effect = capture
        shared.admin_request(
            "POST", "/p", data={"name": "foo"}, json_body=True
        )
    assert captured["content_type"] == "application/json"
    assert json.loads(captured["body"]) == {"name": "foo"}


def test_admin_request_sends_json_when_data_is_list():
    """List payloads (e.g. sample-bucket install) auto-serialize as JSON."""
    shared = _fresh_shared()
    captured = {}
    with patch("urllib.request.urlopen") as mock_open:
        def capture(req, **kwargs):
            captured["body"] = req.data
            captured["content_type"] = req.headers.get("Content-type")
            return _make_response(b"{}")

        mock_open.side_effect = capture
        shared.admin_request("POST", "/p", data=["travel-sample", "beer-sample"])
    assert captured["content_type"] == "application/json"
    assert json.loads(captured["body"]) == ["travel-sample", "beer-sample"]


def test_admin_request_filters_none_values_in_form():
    shared = _fresh_shared()
    captured = {}
    with patch("urllib.request.urlopen") as mock_open:
        def capture(req, **kwargs):
            captured["body"] = req.data
            return _make_response(b"{}")

        mock_open.side_effect = capture
        shared.admin_request("POST", "/p", data={"a": "1", "b": None, "c": "3"})
    body = captured["body"].decode()
    assert "a=1" in body
    assert "c=3" in body
    assert "b=" not in body


# ── Retries on transient failures ────────────────────────────────────────────


def test_admin_request_retries_on_503_then_succeeds():
    shared = _fresh_shared()
    # First two calls 503, third succeeds
    bad = HTTPError("http://x", 503, "busy", {}, BytesIO(b'{"e":"busy"}'))
    good = _make_response(b'{"ok":true}')
    with patch("urllib.request.urlopen") as mock_open, \
         patch("time.sleep") as mock_sleep:
        mock_open.side_effect = [bad, bad, good]
        result = shared.admin_request("GET", "/p")
    assert result == {"ok": True}
    # Backoff: 0.5s after attempt 1, 1.0s after attempt 2
    assert mock_sleep.call_count == 2


def test_admin_request_does_not_retry_on_400():
    shared = _fresh_shared()
    bad = HTTPError("http://x", 400, "bad req", {}, BytesIO(b'{"e":"bad"}'))
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.side_effect = [bad]
        with pytest.raises(RuntimeError, match="HTTP 400"):
            shared.admin_request("GET", "/p")
        assert mock_open.call_count == 1


def test_admin_request_does_not_retry_on_404():
    shared = _fresh_shared()
    bad = HTTPError("http://x", 404, "not found", {}, BytesIO(b""))
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.side_effect = [bad]
        with pytest.raises(RuntimeError, match="HTTP 404"):
            shared.admin_request("GET", "/p")


def test_admin_request_retries_on_url_error_then_succeeds():
    shared = _fresh_shared()
    fail = URLError("connection refused")
    good = _make_response(b'{"ok":1}')
    with patch("urllib.request.urlopen") as mock_open, \
         patch("time.sleep"):
        mock_open.side_effect = [fail, good]
        result = shared.admin_request("GET", "/p")
    assert result == {"ok": 1}


def test_admin_request_gives_up_after_max_attempts():
    shared = _fresh_shared()
    bad = HTTPError("http://x", 503, "busy", {}, BytesIO(b""))
    with patch("urllib.request.urlopen") as mock_open, \
         patch("time.sleep"):
        mock_open.side_effect = [bad] * 10
        with pytest.raises(RuntimeError):
            shared.admin_request("GET", "/p")
        # Default 3 attempts
        assert mock_open.call_count == 3


def test_admin_request_error_includes_method_and_path():
    shared = _fresh_shared()
    bad = HTTPError("http://x", 500, "err", {}, BytesIO(b'{"d":"e"}'))
    with patch("urllib.request.urlopen") as mock_open, \
         patch("time.sleep"):
        mock_open.side_effect = [bad, bad, bad]
        try:
            shared.admin_request("DELETE", "/some/path")
            pytest.fail("should have raised")
        except RuntimeError as e:
            assert "DELETE" in str(e)
            assert "/some/path" in str(e)


# ── Auth header behavior ─────────────────────────────────────────────────────


def test_auth_header_basic_by_default():
    shared = _fresh_shared()
    # Make sure mTLS env vars are not set for this test
    os.environ.pop("CB_CLIENT_CERT_PATH", None)
    os.environ.pop("CB_CLIENT_KEY_PATH", None)
    headers = shared._auth_header()
    assert "Authorization" in headers
    assert headers["Authorization"].startswith("Basic ")


def test_auth_header_omitted_when_mtls_active():
    shared = _fresh_shared()
    os.environ["CB_CLIENT_CERT_PATH"] = "/tmp/fake.crt"
    os.environ["CB_CLIENT_KEY_PATH"] = "/tmp/fake.key"
    try:
        headers = shared._auth_header()
        assert "Authorization" not in headers
    finally:
        os.environ.pop("CB_CLIENT_CERT_PATH", None)
        os.environ.pop("CB_CLIENT_KEY_PATH", None)


# ── _admin_url derivation ─────────────────────────────────────────────────────


def test_admin_url_http_for_couchbase_scheme():
    os.environ["CB_CONNECTION_STRING"] = "couchbase://host.example:11210"
    os.environ.pop("CB_MGMT_PORT", None)
    shared = _fresh_shared()
    url = shared._admin_url()
    assert url == "http://host.example:8091"


def test_admin_url_https_for_couchbases_scheme():
    os.environ["CB_CONNECTION_STRING"] = "couchbases://host.example:11207"
    os.environ.pop("CB_MGMT_PORT", None)
    shared = _fresh_shared()
    url = shared._admin_url()
    assert url == "https://host.example:18091"


def test_admin_url_respects_mgmt_port_override():
    os.environ["CB_CONNECTION_STRING"] = "couchbases://host.example"
    os.environ["CB_MGMT_PORT"] = "19999"
    shared = _fresh_shared()
    url = shared._admin_url()
    assert url == "https://host.example:19999"
    os.environ.pop("CB_MGMT_PORT", None)
