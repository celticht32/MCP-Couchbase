"""Unit tests for Phase 5 deferred items (synonyms, DARE/KMIP) and Phase 7
(Capella v4 read-only).

Run from the project root:
    python -m pytest tests/test_phase5_phase7.py -v
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh(modname: str):
    """Reload a handlers.* module with a clean env."""
    os.environ.setdefault("CB_USERNAME", "u")
    os.environ.setdefault("CB_PASSWORD", "p")
    for m in ("handlers.shared", "handlers.eight_x", f"handlers.{modname}",
              "handlers"):
        sys.modules.pop(m, None)
    return __import__(f"handlers.{modname}", fromlist=[modname])


# ────────────────────────────────────────────────────────────────────────────
# Synonyms
# ────────────────────────────────────────────────────────────────────────────


def test_synonyms_exports_three_tools():
    s = _fresh("synonyms")
    assert len(s.TOOLS) == 3


def test_synonyms_validate_accepts_valid_doc():
    s = _fresh("synonyms")
    result = s._validate_synonym_doc(
        {"input": ["js"], "synonyms": ["js", "javascript"]}, "test"
    )
    assert result is None


def test_synonyms_validate_rejects_empty_input():
    s = _fresh("synonyms")
    result = s._validate_synonym_doc(
        {"input": [], "synonyms": ["x"]}, "test"
    )
    assert result is not None
    payload = json.loads(result[0].text)
    assert "input" in payload["error"]


def test_synonyms_validate_rejects_non_string_in_input():
    s = _fresh("synonyms")
    result = s._validate_synonym_doc(
        {"input": ["js", 42], "synonyms": ["js"]}, "test"
    )
    assert result is not None
    payload = json.loads(result[0].text)
    assert "strings" in payload["error"]


def test_synonyms_validate_rejects_missing_synonyms_field():
    s = _fresh("synonyms")
    result = s._validate_synonym_doc(
        {"input": ["js"]}, "test"
    )
    assert result is not None


def test_synonyms_validate_rejects_non_dict():
    s = _fresh("synonyms")
    result = s._validate_synonym_doc(["not", "a", "dict"], "test")
    assert result is not None
    payload = json.loads(result[0].text)
    assert "object" in payload["error"]


def test_synonyms_upsert_gates_on_8x():
    """When is_8x() is False, the tool should error before touching the SDK."""
    s = _fresh("synonyms")
    with patch("handlers.eight_x.is_8x", return_value=False):
        result = s.handle("cb_fts_synonym_upsert", {
            "bucket_name": "b", "key": "k",
            "input": ["js"], "synonyms": ["js", "javascript"],
        })
    payload = json.loads(result[0].text)
    assert "8.0" in payload["error"]


def test_synonyms_upsert_passes_through_to_sdk_when_8x():
    s = _fresh("synonyms")
    mock_collection = MagicMock()
    mock_collection.upsert.return_value = MagicMock(cas=12345)
    mock_bucket = MagicMock()
    mock_bucket.scope.return_value.collection.return_value = mock_collection
    mock_cluster = MagicMock()
    mock_cluster.bucket.return_value = mock_bucket

    with patch("handlers.eight_x.is_8x", return_value=True), \
         patch("handlers.synonyms.get_sdk_connection",
               return_value=(mock_cluster, None, None)):
        result = s.handle("cb_fts_synonym_upsert", {
            "bucket_name": "myb",
            "scope_name": "myscope",
            "collection_name": "synonyms",
            "key": "k1",
            "input": ["js", "javascript"],
            "synonyms": ["js", "javascript", "ecmascript"],
        })

    mock_cluster.bucket.assert_called_once_with("myb")
    mock_bucket.scope.assert_called_once_with("myscope")
    mock_bucket.scope.return_value.collection.assert_called_once_with("synonyms")
    upsert_args = mock_collection.upsert.call_args
    assert upsert_args[0][0] == "k1"
    assert upsert_args[0][1] == {
        "input": ["js", "javascript"],
        "synonyms": ["js", "javascript", "ecmascript"],
    }
    payload = json.loads(result[0].text)
    assert payload["schema"] == "synonym"


def test_synonyms_annotations():
    s = _fresh("synonyms")
    upsert = next(t for t in s.TOOLS if t.name == "cb_fts_synonym_upsert")
    lst = next(t for t in s.TOOLS if t.name == "cb_fts_synonym_list")
    dele = next(t for t in s.TOOLS if t.name == "cb_fts_synonym_delete")
    assert upsert.annotations.readOnlyHint is False
    assert upsert.annotations.destructiveHint is False
    assert lst.annotations.readOnlyHint is True
    assert dele.annotations.destructiveHint is True


# ────────────────────────────────────────────────────────────────────────────
# Encryption (DARE + KMIP)
# ────────────────────────────────────────────────────────────────────────────


def test_encryption_exports_four_tools():
    e = _fresh("encryption")
    assert len(e.TOOLS) == 4


def test_encryption_get_path():
    e = _fresh("encryption")
    captured = {}

    def fake(method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        return {"enabled": False}

    with patch("handlers.encryption.admin_request", side_effect=fake):
        e.handle("admin_encryption_get", {})

    assert captured["method"] == "GET"
    assert captured["path"] == "/settings/security/encryptionAtRest"


def test_encryption_set_filters_confirm():
    """The confirm argument should not be forwarded to the REST endpoint."""
    e = _fresh("encryption")
    captured = {}

    def fake(method, path, **kwargs):
        captured["data"] = kwargs.get("data")
        return {"status": "ok"}

    with patch("handlers.encryption.admin_request", side_effect=fake):
        e.handle("admin_encryption_set", {
            "encryptionEnabled": True,
            "rotateInterval": 86400,
            "confirm": True,
        })

    assert "confirm" not in captured["data"]
    assert captured["data"]["encryptionEnabled"] == "true"
    assert captured["data"]["rotateInterval"] == "86400"


def test_encryption_set_passes_additional_fields():
    """Pass-through for fields not in the explicit schema."""
    e = _fresh("encryption")
    captured = {}

    def fake(method, path, **kwargs):
        captured["data"] = kwargs.get("data")
        return {"status": "ok"}

    with patch("handlers.encryption.admin_request", side_effect=fake):
        e.handle("admin_encryption_set", {
            "encryptionEnabled": True,
            "additional_fields": {"experimental_flag": "x", "other": 42},
            "confirm": True,
        })

    assert captured["data"]["experimental_flag"] == "x"
    assert captured["data"]["other"] == "42"
    assert "additional_fields" not in captured["data"]


def test_kmip_get_path():
    e = _fresh("encryption")
    captured = {}

    def fake(method, path, **kwargs):
        captured["path"] = path
        return {}

    with patch("handlers.encryption.admin_request", side_effect=fake):
        e.handle("admin_kmip_get", {})

    assert captured["path"] == "/settings/security/kmip"


def test_encryption_404_includes_path_hint():
    e = _fresh("encryption")

    def fake(method, path, **kwargs):
        raise RuntimeError("HTTP 404 on GET /settings/security/encryptionAtRest: Not Found")

    with patch("handlers.encryption.admin_request", side_effect=fake):
        result = e.handle("admin_encryption_get", {})

    payload = json.loads(result[0].text)
    assert "hint" in payload
    assert "encryption" in payload["hint"].lower() or "404" in payload["hint"]


def test_encryption_destructive_writes():
    e = _fresh("encryption")
    for name in ("admin_encryption_set", "admin_kmip_set"):
        t = next(tt for tt in e.TOOLS if tt.name == name)
        assert t.annotations.destructiveHint is True, f"{name} should be destructive"


# ────────────────────────────────────────────────────────────────────────────
# Capella v4 (read-only)
# ────────────────────────────────────────────────────────────────────────────


def test_capella_exports_sixteen_tools():
    os.environ["CAPELLA_API_KEY_SECRET"] = "fake"
    c = _fresh("capella")
    assert len(c.TOOLS) == 16


def test_capella_all_read_only():
    """Every Capella v4 tool in this phase is a read; no writes."""
    os.environ["CAPELLA_API_KEY_SECRET"] = "fake"
    c = _fresh("capella")
    for t in c.TOOLS:
        assert t.annotations.readOnlyHint is True, f"{t.name} should be read-only"
        assert t.annotations.destructiveHint is False, f"{t.name} should not be destructive"


def test_capella_requires_api_key_secret():
    """Module init shouldn't fail, but the first request should raise about
    the missing env var."""
    # Clear the env var
    os.environ.pop("CAPELLA_API_KEY_SECRET", None)
    c = _fresh("capella")

    # The handler calls _capella_secret() which reads the env via get_env.
    # That should raise RuntimeError if unset.
    result = c.handle("capella_organizations_list", {})
    payload = json.loads(result[0].text)
    assert "CAPELLA_API_KEY_SECRET" in payload["error"]


def test_capella_base_url_default():
    os.environ["CAPELLA_API_KEY_SECRET"] = "fake"
    os.environ.pop("CAPELLA_BASE_URL", None)
    c = _fresh("capella")
    assert c._capella_base_url() == "https://cloudapi.cloud.couchbase.com"


def test_capella_base_url_override():
    os.environ["CAPELLA_API_KEY_SECRET"] = "fake"
    os.environ["CAPELLA_BASE_URL"] = "https://staging.cloudapi.couchbase.com/"
    c = _fresh("capella")
    # Trailing slash stripped
    assert c._capella_base_url() == "https://staging.cloudapi.couchbase.com"
    os.environ.pop("CAPELLA_BASE_URL", None)


def test_capella_path_encoding():
    """Path segments should be URL-encoded (UUIDs are safe; special chars get encoded)."""
    os.environ["CAPELLA_API_KEY_SECRET"] = "fake"
    c = _fresh("capella")
    # Normal UUID
    assert c._path("organizations", "abc-123") == "/v4/organizations/abc-123"
    # Special characters get encoded
    assert "%2F" in c._path("organizations", "a/b") or c._path(
        "organizations", "a/b"
    ).endswith("a%2Fb")


def test_capella_request_uses_bearer_token():
    """Verify the Authorization header is built correctly."""
    os.environ["CAPELLA_API_KEY_SECRET"] = "my-secret-key"
    c = _fresh("capella")
    captured = {}

    class FakeResp:
        def read(self):
            return b'{"data": []}'
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def fake_urlopen(req, **kwargs):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        return FakeResp()

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        c._capella_request("GET", "/v4/organizations")

    # Header name is normalized (capitalized first letter) by urllib
    auth_header = captured["headers"].get("Authorization") or captured["headers"].get("authorization")
    assert auth_header == "Bearer my-secret-key"
    assert captured["url"].startswith("https://cloudapi.cloud.couchbase.com/v4/organizations")


def test_capella_request_retries_on_503():
    """Transient 5xx should retry."""
    os.environ["CAPELLA_API_KEY_SECRET"] = "fake"
    c = _fresh("capella")
    from io import BytesIO
    from urllib.error import HTTPError

    class FakeResp:
        def read(self):
            return b'{"ok": true}'
        def __enter__(self): return self
        def __exit__(self, *a): pass

    calls = []

    def fake_urlopen(req, **kwargs):
        calls.append(req.full_url)
        if len(calls) < 3:
            raise HTTPError("http://x", 503, "busy", {}, BytesIO(b""))
        return FakeResp()

    with patch("urllib.request.urlopen", side_effect=fake_urlopen), \
         patch("time.sleep"):
        result = c._capella_request("GET", "/v4/organizations")

    assert result == {"ok": True}
    assert len(calls) == 3


def test_capella_request_does_not_retry_on_403():
    """403 (auth failure) should not retry."""
    os.environ["CAPELLA_API_KEY_SECRET"] = "fake"
    c = _fresh("capella")
    from io import BytesIO
    from urllib.error import HTTPError

    calls = []

    def fake_urlopen(req, **kwargs):
        calls.append(req.full_url)
        raise HTTPError("http://x", 403, "forbidden", {}, BytesIO(b'{"code": 1002}'))

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        with pytest.raises(RuntimeError, match="403"):
            c._capella_request("GET", "/v4/organizations")

    assert len(calls) == 1


def test_capella_clusters_list_constructs_correct_path():
    os.environ["CAPELLA_API_KEY_SECRET"] = "fake"
    c = _fresh("capella")
    captured = {}

    def fake(method, path, params=None):
        captured["path"] = path
        return {"data": []}

    with patch("handlers.capella._capella_request", side_effect=fake):
        c.handle("capella_clusters_list", {
            "organization_id": "org-uuid",
            "project_id": "proj-uuid",
        })

    assert captured["path"] == "/v4/organizations/org-uuid/projects/proj-uuid/clusters"


def test_capella_cluster_get_with_full_hierarchy():
    os.environ["CAPELLA_API_KEY_SECRET"] = "fake"
    c = _fresh("capella")
    captured = {}

    def fake(method, path, params=None):
        captured["path"] = path
        return {}

    with patch("handlers.capella._capella_request", side_effect=fake):
        c.handle("capella_cluster_get", {
            "organization_id": "o", "project_id": "p", "cluster_id": "c",
        })

    assert captured["path"] == "/v4/organizations/o/projects/p/clusters/c"


def test_capella_expected_tool_names():
    os.environ["CAPELLA_API_KEY_SECRET"] = "fake"
    c = _fresh("capella")
    expected = {
        "capella_organizations_list",
        "capella_organization_get",
        "capella_projects_list",
        "capella_project_get",
        "capella_clusters_list",
        "capella_cluster_get",
        "capella_database_users_list",
        "capella_database_user_get",
        "capella_allowed_cidrs_list",
        "capella_allowed_cidr_get",
        "capella_org_users_list",
        "capella_org_user_get",
        "capella_api_keys_list",
        "capella_api_key_get",
        "capella_app_services_list",
        "capella_app_service_get",
    }
    actual = {t.name for t in c.TOOLS}
    assert actual == expected
