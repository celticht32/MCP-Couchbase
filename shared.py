"""
shared.py – connection pool, HTTP admin client, and response helpers.
All handler modules import from here.
"""

from __future__ import annotations

import json
import os
from typing import Any
import urllib.request
import urllib.parse
import urllib.error
import base64

from mcp.types import TextContent

# ── SDK connection (lazy) ────────────────────────────────────────────────────
_cluster    = None
_bucket     = None
_collection = None


def get_env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def get_sdk_connection():
    """Return (cluster, bucket, collection) – lazily initialised."""
    global _cluster, _bucket, _collection
    if _cluster is not None:
        return _cluster, _bucket, _collection

    try:
        from couchbase.cluster import Cluster
        from couchbase.options import ClusterOptions
        from couchbase.auth import PasswordAuthenticator
        from datetime import timedelta
    except ImportError as exc:
        raise RuntimeError("pip install couchbase") from exc

    auth = PasswordAuthenticator(
        get_env("CB_USERNAME", "Administrator"),
        get_env("CB_PASSWORD", "password"),
    )
    opts = ClusterOptions(auth)
    opts.apply_profile("wan_development")

    _cluster = Cluster(get_env("CB_CONNECTION_STRING", "couchbase://localhost"), opts)
    _cluster.wait_until_ready(__import__("datetime").timedelta(seconds=10))

    _bucket     = _cluster.bucket(get_env("CB_BUCKET", "default"))
    _collection = _bucket.scope(get_env("CB_SCOPE", "_default")).collection(
        get_env("CB_COLLECTION", "_default")
    )
    return _cluster, _bucket, _collection


# ── HTTP admin client ────────────────────────────────────────────────────────
def _admin_url() -> str:
    """Derive the HTTP management URL from CB_CONNECTION_STRING."""
    raw = get_env("CB_CONNECTION_STRING", "couchbase://localhost")
    host = raw.replace("couchbases://", "").replace("couchbase://", "").split(":")[0]
    port = get_env("CB_MGMT_PORT", "8091")
    scheme = "https" if "couchbases://" in raw else "http"
    return f"{scheme}://{host}:{port}"


def admin_request(
    method: str,
    path: str,
    data: dict | None = None,
    params: dict | None = None,
) -> Any:
    """
    Execute a Couchbase Management REST API call.
    Returns parsed JSON or raises on HTTP error.
    """
    base  = _admin_url()
    url   = f"{base}{path}"

    if params:
        url += "?" + urllib.parse.urlencode(params)

    credentials = base64.b64encode(
        f"{get_env('CB_USERNAME','Administrator')}:{get_env('CB_PASSWORD','password')}".encode()
    ).decode()

    body: bytes | None = None
    content_type = "application/x-www-form-urlencoded"
    if data is not None:
        body = urllib.parse.urlencode(data).encode()

    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Basic {credentials}")
    req.add_header("Content-Type", content_type)
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            if raw:
                return json.loads(raw)
            return {"status": "ok"}
    except urllib.error.HTTPError as exc:
        body_bytes = exc.read()
        try:
            detail = json.loads(body_bytes)
        except Exception:
            detail = body_bytes.decode(errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def admin_request_json(method: str, path: str, payload: dict | None = None) -> Any:
    """Like admin_request but sends JSON body (for endpoints that require it)."""
    import urllib.request, urllib.parse, urllib.error, base64, json
    base  = _admin_url()
    url   = f"{base}{path}"

    credentials = base64.b64encode(
        f"{get_env('CB_USERNAME','Administrator')}:{get_env('CB_PASSWORD','password')}".encode()
    ).decode()

    body = json.dumps(payload).encode() if payload else None
    req  = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Basic {credentials}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept",       "application/json")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {"status": "ok"}
    except urllib.error.HTTPError as exc:
        body_bytes = exc.read()
        try:
            detail = json.loads(body_bytes)
        except Exception:
            detail = body_bytes.decode(errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


# ── Response helpers ─────────────────────────────────────────────────────────
def ok(data: Any) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def err(msg: str) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps({"error": msg}, indent=2))]
