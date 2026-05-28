"""
gui_server.py - Flask backend for the Couchbase MCP GUI.

Imports the MCP handler modules directly and exposes them via a REST API
that the browser frontend can call. No MCP transport layer needed.

Security model (see also handlers/shared.py for the canonical server.py rules):

  * /api/config POST writes to os.environ but only for an allow-listed set
    of CB_* / CAPELLA_* keys; anything else is rejected.
  * /api/config GET redacts CB_PASSWORD / CAPELLA_API_KEY_SECRET / CB_CLIENT_*
    in the response (so the password is never visible on the wire).
  * /api/call enforces the same primitives server.py applies:
    - CB_MCP_READ_ONLY_MODE=true (default) blocks any write tool
    - CB_MCP_DISABLED_TOOLS is honored
    - destructiveHint=True tools require {"confirm": true} in arguments
  * CORS is restricted to localhost origins, not "*"
  * App binds to 127.0.0.1 by default (set GUI_HOST=0.0.0.0 to expose, with
    extreme caution; CB_GUI_ALLOW_REMOTE=1 must also be set as belt-and-braces)
  * debug=True is disabled by default (set FLASK_DEBUG=1 to opt in for dev)

Run:
    cd /path/to/couchbase-mcp-server
    python gui/gui_server.py
"""

import json
import os
import re
import sys

# Add the MCP server root to the path BEFORE importing handlers.
# Imports below intentionally come after sys.path mutation (E402 is
# inapplicable here; we suppress it on the affected import lines).
SERVER_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.abspath(SERVER_ROOT))

from flask import Flask, jsonify, request, send_from_directory  # noqa: E402
from flask_cors import CORS  # noqa: E402

# Import all 15 non-Capella handler modules (Capella v4 has its own separate GUI)
from handlers import (  # noqa: E402
    buckets,
    cluster,
    collections,
    data,
    diagnostics,
    eight_x,
    encryption,
    eventing,
    extended,
    indexes,
    mcp_status,
    search_admin,
    security,
    stats,
    synonyms,
    xdcr,
)
from handlers.shared import (  # noqa: E402
    _CUSTOM_CONFIRMATION_TOOLS,
    DISABLED_TOOLS,
    READ_ONLY_MODE,
    require_confirmation,
)

app = Flask(__name__, static_folder="static")

# CORS — restrict to localhost origins only.
# An overly-permissive CORS allows any web page the user visits to silently
# invoke MCP tools against their local cluster.
CORS(
    app,
    origins=[
        re.compile(r"^https?://localhost(:[0-9]+)?$"),
        re.compile(r"^https?://127\.0\.0\.1(:[0-9]+)?$"),
        re.compile(r"^https?://\[::1\](:[0-9]+)?$"),
    ],
)

# ── Tool registry (mirrors server.py, minus capella) ─────────────────────────
ALL_TOOLS = (
    data.TOOLS
    + buckets.TOOLS
    + collections.TOOLS
    + security.TOOLS
    + cluster.TOOLS
    + xdcr.TOOLS
    + indexes.TOOLS
    + search_admin.TOOLS
    + stats.TOOLS
    + diagnostics.TOOLS
    + eight_x.TOOLS
    + extended.TOOLS
    + eventing.TOOLS
    + synonyms.TOOLS
    + encryption.TOOLS
    + mcp_status.TOOLS
)

HANDLERS = {
    **{t.name: data for t in data.TOOLS},
    **{t.name: buckets for t in buckets.TOOLS},
    **{t.name: collections for t in collections.TOOLS},
    **{t.name: security for t in security.TOOLS},
    **{t.name: cluster for t in cluster.TOOLS},
    **{t.name: xdcr for t in xdcr.TOOLS},
    **{t.name: indexes for t in indexes.TOOLS},
    **{t.name: search_admin for t in search_admin.TOOLS},
    **{t.name: stats for t in stats.TOOLS},
    **{t.name: diagnostics for t in diagnostics.TOOLS},
    **{t.name: eight_x for t in eight_x.TOOLS},
    **{t.name: extended for t in extended.TOOLS},
    **{t.name: eventing for t in eventing.TOOLS},
    **{t.name: synonyms for t in synonyms.TOOLS},
    **{t.name: encryption for t in encryption.TOOLS},
    **{t.name: mcp_status for t in mcp_status.TOOLS},
}

TOOL_INDEX = {t.name: t for t in ALL_TOOLS}


# ── Safety filtering — same primitives server.py applies ────────────────────


def _is_destructive(tool) -> bool:
    return bool(tool and tool.annotations and tool.annotations.destructiveHint)


def _is_read_only(tool) -> bool:
    return bool(tool and tool.annotations and tool.annotations.readOnlyHint)


def _visible_tools():
    """Same filter server.py applies at startup:
    - drop tools listed in CB_MCP_DISABLED_TOOLS
    - in read-only mode, drop write tools (except cb_query / cb_analytics_query
      which enforce DML blocking internally)
    """
    always_loaded_in_ro = {"cb_query", "cb_analytics_query"}
    out = []
    for t in ALL_TOOLS:
        if t.name in DISABLED_TOOLS:
            continue
        if (
            READ_ONLY_MODE
            and not _is_read_only(t)
            and t.name not in always_loaded_in_ro
        ):
            continue
        out.append(t)
    return out


# ── Config endpoint — env-var allow-list and password redaction ─────────────

# Only these env vars are settable through the GUI. Anything else in a POST
# body is silently dropped. Prevents an attacker from setting PATH,
# LD_PRELOAD, PYTHONPATH, etc., on the running server.
_CONFIG_ALLOWLIST = {
    "CB_CONNECTION_STRING",
    "CB_USERNAME",
    "CB_PASSWORD",
    "CB_BUCKET",
    "CB_SCOPE",
    "CB_COLLECTION",
    "CB_MGMT_PORT",
    "CB_CA_CERT_PATH",
    "CB_CLIENT_CERT_PATH",
    "CB_CLIENT_KEY_PATH",
    "CB_MCP_TLS_INSECURE",
    "CB_MCP_READ_ONLY_MODE",
    "CB_MCP_DISABLED_TOOLS",
    "CB_MCP_CONFIRMATION_REQUIRED_TOOLS",
    "CB_MCP_HTTP_RETRIES",
    "CB_MCP_HTTP_TIMEOUT",
    "CAPELLA_API_KEY_SECRET",
}

# Fields whose value must never leave the process unmasked.
_REDACTED_FIELDS = {
    "CB_PASSWORD",
    "CAPELLA_API_KEY_SECRET",
    "CB_CLIENT_KEY_PATH",  # not the value but path leakage is undesirable
}


def _redact(key: str, value: str) -> str:
    """Return either the value or a placeholder if it's a secret."""
    if not value:
        return ""
    if key in _REDACTED_FIELDS:
        return "********"
    return value


# ── API endpoints ────────────────────────────────────────────────────────────


@app.route("/api/tools", methods=["GET"])
def list_tools():
    """Return all tools currently exposed (after read-only / disabled filtering)."""
    result = []
    for tool in _visible_tools():
        result.append(
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.inputSchema,
                "readOnly": _is_read_only(tool),
                "destructive": _is_destructive(tool),
            }
        )
    return jsonify(result)


@app.route("/api/call", methods=["POST"])
def call_tool():
    """Execute a tool and return the result, enforcing the same safety gates
    that server.py applies."""
    body = request.get_json(force=True)
    tool_name = body.get("tool")
    arguments = body.get("arguments", {}) or {}

    if not tool_name:
        return jsonify({"error": "Missing 'tool' field"}), 400

    # Read-only filter
    if tool_name in DISABLED_TOOLS:
        return jsonify(
            {"error": f"Tool '{tool_name}' is disabled by configuration"}
        ), 403

    tool = TOOL_INDEX.get(tool_name)
    if tool is None:
        return jsonify({"error": f"Unknown tool: {tool_name}"}), 404

    if (
        READ_ONLY_MODE
        and not _is_read_only(tool)
        and tool_name not in ("cb_query", "cb_analytics_query")
    ):
        return (
            jsonify(
                {
                    "error": (
                        f"Tool '{tool_name}' is a write operation and "
                        "CB_MCP_READ_ONLY_MODE=true. Set false to enable."
                    )
                }
            ),
            403,
        )

    # Confirmation gate — same as server.py
    in_confirm_set = _is_destructive(tool) or tool_name in _CUSTOM_CONFIRMATION_TOOLS
    confirm_err = require_confirmation(tool_name, arguments, in_confirm_set)
    if confirm_err is not None:
        return jsonify({"ok": False, "error": confirm_err}), 403
    # Strip confirm before passing to handler (matches server.py behavior)
    arguments = {k: v for k, v in arguments.items() if k != "confirm"}

    handler = HANDLERS.get(tool_name)
    if handler is None:
        return jsonify({"error": f"No handler for tool: {tool_name}"}), 500

    try:
        result = handler.handle(tool_name, arguments)
        text = result[0].text if result else "{}"
        parsed = json.loads(text)
        return jsonify({"ok": True, "result": parsed})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 200


@app.route("/api/config", methods=["GET", "POST"])
def config():
    """Get or set environment-level connection config.

    POST: writes accepted ONLY for keys in _CONFIG_ALLOWLIST.
    GET:  returns current values with passwords / API secrets redacted.
    """
    if request.method == "POST":
        body = request.get_json(force=True) or {}
        rejected = []
        applied = []
        for key, val in body.items():
            if key not in _CONFIG_ALLOWLIST:
                rejected.append(key)
                continue
            if val is None or val == "":
                # Allow explicit clear by passing empty string
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(val)
            applied.append(key)

        # Reset SDK connection so next call re-connects
        import handlers.shared as sh

        sh._cluster = sh._bucket = sh._collection = None

        return jsonify({"ok": True, "applied": applied, "rejected": rejected})
    else:
        return jsonify(
            {
                k: _redact(k, os.environ.get(k, default))
                for k, default in {
                    "CB_CONNECTION_STRING": "couchbase://localhost",
                    "CB_USERNAME": "Administrator",
                    "CB_PASSWORD": "",
                    "CB_BUCKET": "default",
                    "CB_SCOPE": "_default",
                    "CB_COLLECTION": "_default",
                    "CB_MGMT_PORT": "8091",
                }.items()
            }
        )


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    """Serve the React SPA."""
    if path and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("GUI_PORT", "5173"))
    host = os.environ.get("GUI_HOST", "127.0.0.1")
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes", "on")

    # Belt-and-braces — refuse to bind to all interfaces unless the operator
    # explicitly opts in via a second env var. Prevents an unintended exposure
    # of the GUI on a developer laptop or a poorly-configured container.
    if host == "0.0.0.0" and os.environ.get("CB_GUI_ALLOW_REMOTE", "").lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        print(
            "[gui] Refusing to bind to 0.0.0.0 without CB_GUI_ALLOW_REMOTE=1. "
            "Set CB_GUI_ALLOW_REMOTE=1 if this is intentional.",
            file=sys.stderr,
        )
        host = "127.0.0.1"

    if debug:
        print(
            "[gui] WARNING: FLASK_DEBUG=1 enables the Werkzeug debugger. "
            "Never use this on a network-exposed host (RCE risk).",
            file=sys.stderr,
        )

    print(f"\n  Couchbase MCP GUI -> http://{host}:{port}\n")
    app.run(host=host, port=port, debug=debug)
