"""
gui_server.py - Flask backend for the Couchbase Capella v4 Control-Plane GUI.

Separate from the main cluster GUI under ../gui/. This server only exposes
Capella v4 read-only inspection tools (orgs/projects/clusters/users/CIDRs/
API keys/app services). It does NOT need a per-cluster connection - it
authenticates against cloudapi.cloud.couchbase.com with a Bearer API-key
secret.

Run:
    cd /path/to/couchbase-mcp-server
    export CAPELLA_API_KEY_SECRET=<paste-from-Capella-UI-Settings-API-Keys>
    python gui-capella/gui_server.py
    # -> http://localhost:5174
"""

import json
import os
import sys

# Add the MCP server root to the path BEFORE importing handlers.
SERVER_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.abspath(SERVER_ROOT))

from flask import Flask, jsonify, request, send_from_directory  # noqa: E402
from flask_cors import CORS  # noqa: E402

# Capella v4 is the ONLY handler this GUI exposes.
from handlers import capella  # noqa: E402

app = Flask(__name__, static_folder="static")
CORS(app)

# ── Tool registry (Capella v4 only — all 16 read-only) ───────────────────────
ALL_TOOLS = list(capella.TOOLS)
HANDLERS = {t.name: capella for t in capella.TOOLS}


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
    """Execute a Capella tool and return the result."""
    body = request.get_json(force=True)
    tool_name = body.get("tool")
    arguments = body.get("arguments", {})

    if not tool_name:
        return jsonify({"error": "Missing 'tool' field"}), 400

    handler = HANDLERS.get(tool_name)
    if handler is None:
        return jsonify({"error": f"Unknown tool: {tool_name}"}), 404

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

    Different from the main GUI's /api/config: this one only handles the
    CAPELLA_* env vars (the rest of the MCP's CB_* vars aren't used here).
    """
    if request.method == "POST":
        body = request.get_json(force=True)
        for key, val in body.items():
            if key.startswith("CAPELLA_") and val:
                os.environ[key] = val
        return jsonify({"ok": True})
    else:
        # Don't echo the secret back — return whether it's set, not the value
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
    print(f"\n  Couchbase Capella v4 Console → http://localhost:{port}")
    print(
        f"  ({'CAPELLA_API_KEY_SECRET is set' if os.environ.get('CAPELLA_API_KEY_SECRET') else 'WARNING: CAPELLA_API_KEY_SECRET not set — set via UI or env'})\n"
    )
    app.run(host="0.0.0.0", port=port, debug=True)
