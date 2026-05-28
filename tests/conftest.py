"""
tests/conftest.py — shared fixtures for couchbase-mcp-server tests.

Integration tests require a running Couchbase cluster. Set:
    CB_CONNECTION_STRING, CB_USERNAME, CB_PASSWORD, CB_BUCKET

Unit tests (tool registration, safety logic) run without a cluster.
"""

from __future__ import annotations

import os
import sys

import pytest

# ── Markers ──────────────────────────────────────────────────────────────────


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: mark test as requiring a live Couchbase cluster",
    )
    config.addinivalue_line(
        "markers",
        "unit: mark test as not requiring a live cluster",
    )


def pytest_collection_modifyitems(config, items):
    """Skip integration tests unless CB_CONNECTION_STRING is set."""
    if os.environ.get("CB_CONNECTION_STRING"):
        return
    skip = pytest.mark.skip(
        reason="CB_CONNECTION_STRING not set — skipping integration tests"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


# ── Module cache helpers ──────────────────────────────────────────────────────


def flush_modules(*prefixes: str) -> None:
    """Remove all cached modules whose names start with any of the given prefixes.
    Call before re-importing a module that reads env vars at import time.
    """
    for key in list(sys.modules.keys()):
        if any(key.startswith(p) for p in prefixes):
            del sys.modules[key]


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def clean_env(monkeypatch):
    """Ensure a predictable baseline environment for each unit test.
    Sets safe defaults so imports don't fail on missing required vars.
    """
    monkeypatch.setenv("CB_USERNAME", "testuser")
    monkeypatch.setenv("CB_PASSWORD", "testpass")
    monkeypatch.setenv("CB_CONNECTION_STRING", "couchbase://localhost")
    monkeypatch.setenv("CB_MCP_READ_ONLY_MODE", "true")
    flush_modules("handlers", "server")
    yield
    flush_modules("handlers", "server")


@pytest.fixture
def write_env(monkeypatch):
    """Function-scoped env with read-only mode OFF (for write-tool tests)."""
    monkeypatch.setenv("CB_MCP_READ_ONLY_MODE", "false")
    monkeypatch.setenv("CB_USERNAME", os.environ.get("CB_USERNAME", "Administrator"))
    monkeypatch.setenv("CB_PASSWORD", os.environ.get("CB_PASSWORD", "password"))
    monkeypatch.setenv(
        "CB_CONNECTION_STRING",
        os.environ.get("CB_CONNECTION_STRING", "couchbase://localhost"),
    )
    flush_modules("handlers", "server")
    yield
    flush_modules("handlers", "server")
