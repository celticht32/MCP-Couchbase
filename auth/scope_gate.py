"""
auth/scope_gate.py — Per-tool OAuth scope enforcement for the MCP call path.

KISS design:
  * When no validated token is in context (stdio transport, or HTTP with OAuth
    not configured), enforcement is a no-op. Same code path serves both modes.
  * When a token IS in context, each tool call is checked against the scopes the
    token carries. Destructive/write tools need the WRITE scope; everything else
    needs the READ scope. Read and write are independent: a write-only token
    cannot reach read tools, and vice versa.

The decision is driven off each tool's existing ToolAnnotations
(destructiveHint / readOnlyHint), so there is no separate write-list to keep in
sync across the tool catalog.

Environment
───────────
  CB_MCP_SCOPE_READ    scope required for read tools   (default: couchbase-mcp:read)
  CB_MCP_SCOPE_WRITE   scope required for write tools  (default: couchbase-mcp:write)

License: MIT — Copyright (c) 2026 Chris Ahrendt
"""

from __future__ import annotations

import contextvars
import os
from typing import Any

# Request-scoped token claims. Set by the HTTP layer after validate_token();
# left as None on stdio or when OAuth is not configured.
_token_claims: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "cb_mcp_token_claims", default=None
)


def set_token_claims(claims: dict[str, Any] | None) -> None:
    """Store validated JWT claims for the current request context."""
    _token_claims.set(claims)


def clear_token_claims() -> None:
    """Reset context after a request (defensive; contextvars are per-task)."""
    _token_claims.set(None)


def _scope_read() -> str:
    return os.environ.get("CB_MCP_SCOPE_READ", "couchbase-mcp:read").strip()


def _scope_write() -> str:
    return os.environ.get("CB_MCP_SCOPE_WRITE", "couchbase-mcp:write").strip()


def _claims_scopes(claims: dict[str, Any]) -> set[str]:
    """
    Extract granted scopes from token claims.

    Handles the common shapes:
      * RFC 8693 'scope' as a space-delimited string
      * 'scope'/'scopes' already a list
      * Entra-style 'scp' (string or list)
    """
    raw: Any = claims.get("scope")
    if raw is None:
        raw = claims.get("scp")
    if raw is None:
        raw = claims.get("scopes")

    if raw is None:
        return set()
    if isinstance(raw, str):
        return {s for s in raw.split() if s}
    if isinstance(raw, (list, tuple, set)):
        return {str(s) for s in raw}
    return set()


def _required_scope_for(tool: Any) -> str:
    """
    Return the scope a tool requires, from its annotations.

    Rule (fail-safe): a tool needs the WRITE scope if it is destructive OR not
    explicitly marked read-only OR carries no annotations at all. Only tools
    explicitly flagged readOnlyHint=True (and not destructive) need just READ.
    """
    ann = getattr(tool, "annotations", None)
    if ann is None:
        return _scope_write()  # unknown intent -> require the stronger scope
    if getattr(ann, "destructiveHint", False):
        return _scope_write()
    if getattr(ann, "readOnlyHint", False):
        return _scope_read()
    return _scope_write()  # not explicitly read-only -> treat as write


def check_scope(tool: Any) -> str | None:
    """
    Authorize the current request to invoke `tool`.

    Returns None when allowed (including the no-token no-op case), or a
    human-readable denial message when the token lacks the required scope.
    """
    claims = _token_claims.get()
    if claims is None:
        return None  # no token in context -> enforcement disabled, allowed

    required = _required_scope_for(tool)
    granted = _claims_scopes(claims)
    if required in granted:
        return None

    return (
        f"Access denied: tool '{getattr(tool, 'name', '?')}' requires scope "
        f"'{required}', which the presented token does not hold."
    )
