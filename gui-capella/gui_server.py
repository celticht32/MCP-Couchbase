"""
gui_server.py - Flask backend for the Couchbase Capella v4 Control-Plane GUI.

Separate from the main cluster GUI under ../gui/. This server only exposes
Capella v4 read-only inspection tools (orgs/projects/clusters/users/CIDRs/
API keys/app services). It does NOT need a per-cluster connection - it
authenticates against cloudapi.cloud.couchbase.com with a Bearer API-key
secret.

Security model (parallel to ../gui/gui_server.py):

  * /api/config POST writes to os.environ ONLY for an allow-listed set of
    CAPELLA_* keys.
  * /api/config GET reports whether CAPELLA_API_KEY_SECRET is set, never
    the value.
  * CORS is restricted to localhost origins.
  * App binds to 127.0.0.1 by default. Setting GUI_HOST=0.0.0.0 requires
    CB_GUI_ALLOW_REMOTE=1 as an explicit opt-in.
  * debug=True is gated behind FLASK_DEBUG=1.

Run:
    cd /path/to/couchbase-mcp-server
    export CAPELLA_API_KEY_SECRET=<paste-from-Capella-UI-Settings-API-Keys>
    python gui-capella/gui_server.py
    # -> http://localhost:5174
"""

import json
import os
import re
import sys

# Add the MCP server root to the path BEFORE importing handlers.
SERVER_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.abspath(SERVER_ROOT))

from flask import Flask, jsonify, request, send_from_directory  # noqa: E402
from flask_cors import CORS  # noqa: E402

# Capella v4 is the ONLY handler this GUI exposes.
from handlers import capella  # noqa: E402

app = Flask(__name__, static_folder="static")

# CORS — restrict to localhost origins only.
CORS(
    app,
    origins=[
        re.compile(r"^https?://localhost(:[0-9]+)?$"),
        re.compile(r"^https?://127\.0\.0\.1(:[0-9]+)?$"),
        re.compile(r"^https?://\[::1\](:[0-9]+)?$"),
    ],
)

# ── Tool registry (Capella v4 only — all 16 read-only) ───────────────────────
ALL_TOOLS = list(capella.TOOLS)
HANDLERS = {t.name: capella for t in capella.TOOLS}
TOOL_INDEX = {t.name: t for t in ALL_TOOLS}

# Capella-specific env-var allow-list. Only these can be set via the GUI.
_CONFIG_ALLOWLIST = {
    "CAPELLA_API_KEY_SECRET",
    "CAPELLA_BASE_URL",
    "CAPELLA_HTTP_TIMEOUT",
    "CAPELLA_HTTP_RETRIES",
}


# ── API endpoints ────────────────────────────────────────────────────────────


@app.route("/api/tools", methods=["GET"])
def list_tools():
    """Return all Capella v4 tools with their schemas."""
    result = []
    for tool in ALL_TOOLS:
        result.append(
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.inputSchema,
            }
        )
    return jsonify(result)


@app.route("/api/call", methods=["POST"])
def call_tool():
    """Execute a Capella tool and return the result.

    Capella v4 tools are all read-only — the handler module declines anything
    destructive. We still validate the requested tool exists.
    """
    body = request.get_json(force=True)
    tool_name = body.get("tool")
    arguments = body.get("arguments", {}) or {}

    if not tool_name:
        return jsonify({"error": "Missing 'tool' field"}), 400

    if tool_name not in TOOL_INDEX:
        return jsonify({"error": f"Unknown tool: {tool_name}"}), 404

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
    """Get or set Capella-specific environment variables.

    POST: writes accepted ONLY for keys in _CONFIG_ALLOWLIST.
    GET:  reports whether CAPELLA_API_KEY_SECRET is set, never the value.
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
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(val)
            applied.append(key)
        return jsonify({"ok": True, "applied": applied, "rejected": rejected})
    else:
        secret_set = bool(os.environ.get("CAPELLA_API_KEY_SECRET"))
        return jsonify(
            {
                "CAPELLA_API_KEY_SECRET": "(set)" if secret_set else "",
                "CAPELLA_BASE_URL": os.environ.get(
                    "CAPELLA_BASE_URL", "https://cloudapi.cloud.couchbase.com"
                ),
                "CAPELLA_HTTP_TIMEOUT": os.environ.get("CAPELLA_HTTP_TIMEOUT", "30"),
                "CAPELLA_HTTP_RETRIES": os.environ.get("CAPELLA_HTTP_RETRIES", "3"),
            }
        )


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    """Serve the Capella-themed React SPA."""
    if path and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("GUI_PORT", "5174"))
    host = os.environ.get("GUI_HOST", "127.0.0.1")
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes", "on")

    if host == "0.0.0.0" and os.environ.get("CB_GUI_ALLOW_REMOTE", "").lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        print(
            "[gui-capella] Refusing to bind to 0.0.0.0 without CB_GUI_ALLOW_REMOTE=1. "
            "Set CB_GUI_ALLOW_REMOTE=1 if this is intentional.",
            file=sys.stderr,
        )
        host = "127.0.0.1"

    if debug:
        print(
            "[gui-capella] WARNING: FLASK_DEBUG=1 enables the Werkzeug debugger. "
            "Never use this on a network-exposed host (RCE risk).",
            file=sys.stderr,
        )

    print(f"\n  Couchbase Capella v4 Console -> http://{host}:{port}")
    secret_state = (
        "CAPELLA_API_KEY_SECRET is set"
        if os.environ.get("CAPELLA_API_KEY_SECRET")
        else "WARNING: CAPELLA_API_KEY_SECRET not set - set via UI or env"
    )
    print(f"  ({secret_state})\n")

    app.run(host=host, port=port, debug=debug)
