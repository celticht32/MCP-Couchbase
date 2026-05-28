"""
gui_server.py - Flask backend for the Couchbase MCP GUI.

Imports the MCP handler modules directly and exposes them via a REST API
that the browser frontend can call. No MCP transport layer needed.

Run:
    cd /path/to/couchbase-mcp-server
    python gui/gui_server.py
"""

import json
import os
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
    search_admin,
    security,
    stats,
    synonyms,
    xdcr,
)

app = Flask(__name__, static_folder="static")
CORS(app)
app = Flask(__name__, static_folder="static")
CORS(app)

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
}

TOOL_INDEX = {t.name: t for t in ALL_TOOLS}


# ── API endpoints ─────────────────────────────────────────────────────────────


@app.route("/api/tools", methods=["GET"])
def list_tools():
    """Return all tools with their schemas."""
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
    """Execute a tool and return the result."""
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
    """Get or set environment-level connection config."""
    if request.method == "POST":
        body = request.get_json(force=True)
        for key, val in body.items():
            if val:
                os.environ[key] = val
        # Reset SDK connection so next call re-connects
        import handlers.shared as sh

        sh._cluster = sh._bucket = sh._collection = None
        return jsonify({"ok": True})
    else:
        return jsonify(
            {
                "CB_CONNECTION_STRING": os.environ.get(
                    "CB_CONNECTION_STRING", "couchbase://localhost"
                ),
                "CB_USERNAME": os.environ.get("CB_USERNAME", "Administrator"),
                "CB_PASSWORD": os.environ.get("CB_PASSWORD", ""),
                "CB_BUCKET": os.environ.get("CB_BUCKET", "default"),
                "CB_SCOPE": os.environ.get("CB_SCOPE", "_default"),
                "CB_COLLECTION": os.environ.get("CB_COLLECTION", "_default"),
                "CB_MGMT_PORT": os.environ.get("CB_MGMT_PORT", "8091"),
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
    print(f"\n  Couchbase MCP GUI → http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=True)
