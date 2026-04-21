"""handlers/xdcr.py – Cross Datacenter Replication (XDCR) admin tools."""

from __future__ import annotations
from mcp.types import Tool, TextContent
from .shared import admin_request, ok

TOOLS: list[Tool] = [
    Tool(name="admin_xdcr_references_list",
         description="List all registered remote cluster references.",
         inputSchema={"type": "object", "properties": {}}),

    Tool(name="admin_xdcr_reference_create",
         description="Register a remote cluster reference for XDCR.",
         inputSchema={"type": "object",
                      "properties": {
                          "name":        {"type": "string",
                                          "description": "Friendly name for the remote cluster"},
                          "hostname":    {"type": "string",
                                          "description": "IP/hostname of the remote cluster node"},
                          "username":    {"type": "string"},
                          "password":    {"type": "string"},
                          "demandEncryption": {"type": "integer", "enum": [0, 1],
                                               "description": "0=none, 1=TLS"},
                      },
                      "required": ["name", "hostname", "username", "password"]}),

    Tool(name="admin_xdcr_reference_delete",
         description="Delete a remote cluster reference by name.",
         inputSchema={"type": "object",
                      "properties": {"cluster_name": {"type": "string"}},
                      "required": ["cluster_name"]}),

    Tool(name="admin_xdcr_replications_list",
         description="List all XDCR replication settings / replications.",
         inputSchema={"type": "object", "properties": {}}),

    Tool(name="admin_xdcr_replication_create",
         description="Create an XDCR replication from a source bucket to a target bucket.",
         inputSchema={"type": "object",
                      "properties": {
                          "fromBucket":  {"type": "string"},
                          "toCluster":   {"type": "string",
                                          "description": "Remote cluster reference name"},
                          "toBucket":    {"type": "string"},
                          "replicationType": {"type": "string",
                                              "enum": ["continuous", "xmem"],
                                              "description": "Default: continuous"},
                          "filterExpression": {"type": "string",
                                               "description": "Optional N1QL-style filter"},
                      },
                      "required": ["fromBucket", "toCluster", "toBucket"]}),

    Tool(name="admin_xdcr_replication_pause",
         description="Pause an XDCR replication.",
         inputSchema={"type": "object",
                      "properties": {"replication_id": {"type": "string",
                                                         "description": "URL-encoded replication ID"}},
                      "required": ["replication_id"]}),

    Tool(name="admin_xdcr_replication_resume",
         description="Resume a paused XDCR replication.",
         inputSchema={"type": "object",
                      "properties": {"replication_id": {"type": "string"}},
                      "required": ["replication_id"]}),

    Tool(name="admin_xdcr_replication_delete",
         description="Delete an XDCR replication.",
         inputSchema={"type": "object",
                      "properties": {"replication_id": {"type": "string"}},
                      "required": ["replication_id"]}),

    Tool(name="admin_xdcr_settings_get",
         description="Get global XDCR advanced settings.",
         inputSchema={"type": "object", "properties": {}}),

    Tool(name="admin_xdcr_settings_set",
         description="Update global or per-replication XDCR settings.",
         inputSchema={"type": "object",
                      "properties": {
                          "replication_id":  {"type": "string",
                                             "description": "Leave empty for global settings"},
                          "workerBatchSize": {"type": "integer"},
                          "docBatchSizeKb":  {"type": "integer"},
                          "failureRestartInterval": {"type": "integer"},
                          "optimisticReplicationThreshold": {"type": "integer"},
                          "statsInterval":  {"type": "integer"},
                          "compressionType":{"type": "string", "enum": ["None", "Snappy", "Auto"]},
                      }}),
]


def handle(name: str, args: dict) -> list[TextContent]:
    if name == "admin_xdcr_references_list":
        return ok(admin_request("GET", "/pools/default/remoteClusters"))

    if name == "admin_xdcr_reference_create":
        data = {
            "name":     args["name"],
            "hostname": args["hostname"],
            "username": args["username"],
            "password": args["password"],
        }
        if args.get("demandEncryption") is not None:
            data["demandEncryption"] = str(args["demandEncryption"])
        return ok(admin_request("POST", "/pools/default/remoteClusters", data=data))

    if name == "admin_xdcr_reference_delete":
        return ok(admin_request("DELETE",
                                f"/pools/default/remoteClusters/{args['cluster_name']}"))

    if name == "admin_xdcr_replications_list":
        return ok(admin_request("GET", "/settings/replications/"))

    if name == "admin_xdcr_replication_create":
        data = {
            "fromBucket":      args["fromBucket"],
            "toCluster":       args["toCluster"],
            "toBucket":        args["toBucket"],
            "replicationType": args.get("replicationType", "continuous"),
        }
        if args.get("filterExpression"):
            data["filterExpression"] = args["filterExpression"]
        return ok(admin_request("POST", "/controller/createReplication", data=data))

    if name == "admin_xdcr_replication_pause":
        rid = args["replication_id"]
        return ok(admin_request("POST", f"/settings/replications/{rid}",
                                data={"pauseRequested": "true"}))

    if name == "admin_xdcr_replication_resume":
        rid = args["replication_id"]
        return ok(admin_request("POST", f"/settings/replications/{rid}",
                                data={"pauseRequested": "false"}))

    if name == "admin_xdcr_replication_delete":
        import urllib.parse
        rid = urllib.parse.quote(args["replication_id"], safe="")
        return ok(admin_request("DELETE", f"/controller/cancelXDCR/{rid}"))

    if name == "admin_xdcr_settings_get":
        return ok(admin_request("GET", "/settings/replications/"))

    if name == "admin_xdcr_settings_set":
        rid  = args.pop("replication_id", None)
        data = {k: str(v) for k, v in args.items() if v is not None}
        path = f"/settings/replications/{rid}" if rid else "/settings/replications/"
        return ok(admin_request("POST", path, data=data))

    raise ValueError(f"Unknown XDCR tool: {name}")
