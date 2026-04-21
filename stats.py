"""handlers/stats.py – Statistics, diagnostics, events, and system info tools."""

from __future__ import annotations
from mcp.types import Tool, TextContent
from .shared import admin_request, admin_request_json, ok

TOOLS: list[Tool] = [
    Tool(name="admin_stats_bucket",
         description="Get statistics for a specific bucket.",
         inputSchema={"type": "object",
                      "properties": {"bucket_name": {"type": "string"}},
                      "required": ["bucket_name"]}),

    Tool(name="admin_stats_single",
         description=(
             "Get a single Prometheus-style metric. "
             "metric_name examples: kv_num_items, index_ram_percent, n1ql_requests."
         ),
         inputSchema={"type": "object",
                      "properties": {
                          "metric_name": {"type": "string"},
                          "bucket":      {"type": "string",
                                         "description": "Optional bucket label filter"},
                          "start":       {"type": "integer",
                                         "description": "Unix timestamp start (optional)"},
                          "end":         {"type": "integer",
                                         "description": "Unix timestamp end (optional)"},
                          "step":        {"type": "integer",
                                         "description": "Step/resolution in seconds (optional)"},
                      },
                      "required": ["metric_name"]}),

    Tool(name="admin_stats_multi",
         description="Get multiple statistics in one call by posting a list of metric requests.",
         inputSchema={"type": "object",
                      "properties": {
                          "metrics": {
                              "type": "array",
                              "description": "List of metric request objects",
                              "items": {
                                  "type": "object",
                                  "properties": {
                                      "metric": {"type": "array",
                                                  "items": {"type": "object"}},
                                      "step":   {"type": "integer"},
                                      "start":  {"type": "integer"},
                                      "end":    {"type": "integer"},
                                  },
                              },
                          }
                      },
                      "required": ["metrics"]}),

    Tool(name="admin_system_events",
         description="Get recent system events from the cluster event log.",
         inputSchema={"type": "object",
                      "properties": {
                          "limit": {"type": "integer",
                                    "description": "Max events to return (default 50)"},
                      }}),

    Tool(name="admin_node_self_info",
         description="Get detailed information about the current node (storage, services, etc.).",
         inputSchema={"type": "object", "properties": {}}),

    Tool(name="admin_internal_settings_get",
         description="Get internal cluster settings (advanced tuning parameters).",
         inputSchema={"type": "object", "properties": {}}),

    Tool(name="admin_internal_settings_set",
         description="Update internal cluster settings. Use with caution.",
         inputSchema={"type": "object",
                      "properties": {
                          "indexAwareRebalanceDisabled": {"type": "boolean"},
                          "rebalanceIgnoreViewCompactions": {"type": "boolean"},
                          "rebalanceIndexWaitingDisabled": {"type": "boolean"},
                          "maxParallelIndexers":           {"type": "integer"},
                          "maxParallelReplicaIndexers":    {"type": "integer"},
                      }}),

    Tool(name="admin_query_settings_get",
         description="Get Query Service (N1QL) settings.",
         inputSchema={"type": "object", "properties": {}}),

    Tool(name="admin_query_settings_set",
         description=(
             "Update Query Service settings. Common keys: "
             "queryTmpSpaceDir, queryTmpSpaceSize, queryPipelineBatch, queryPipelineCap, "
             "queryScanCap, queryTimeout, queryPreparedLimit, queryCompletedLimit, "
             "queryLogLevel, queryMaxParallelism, queryN1qlFeatCtrl."
         ),
         inputSchema={"type": "object",
                      "properties": {
                          "queryTmpSpaceDir":     {"type": "string"},
                          "queryTmpSpaceSize":    {"type": "integer"},
                          "queryPipelineBatch":   {"type": "integer"},
                          "queryTimeout":         {"type": "integer",
                                                  "description": "Timeout in nanoseconds"},
                          "queryLogLevel":        {"type": "string"},
                          "queryMaxParallelism":  {"type": "integer"},
                      }}),

    Tool(name="admin_prometheus_targets",
         description="Get Prometheus scrape target discovery config for the cluster.",
         inputSchema={"type": "object", "properties": {}}),
]


def handle(name: str, args: dict) -> list[TextContent]:
    if name == "admin_stats_bucket":
        b = args["bucket_name"]
        return ok(admin_request("GET", f"/pools/default/buckets/{b}/stats"))

    if name == "admin_stats_single":
        m    = args["metric_name"]
        params: dict = {}
        for k in ("start", "end", "step"):
            if args.get(k) is not None:
                params[k] = args[k]
        return ok(admin_request("GET",
                                f"/pools/default/stats/range/{m}",
                                params=params if params else None))

    if name == "admin_stats_multi":
        return ok(admin_request_json("POST", "/pools/default/stats/range",
                                    payload=args["metrics"]))

    if name == "admin_system_events":
        limit  = args.get("limit", 50)
        result = admin_request("GET", "/events")
        if isinstance(result, list):
            result = result[:limit]
        return ok(result)

    if name == "admin_node_self_info":
        return ok(admin_request("GET", "/nodes/self"))

    if name == "admin_internal_settings_get":
        return ok(admin_request("GET", "/internalSettings"))

    if name == "admin_internal_settings_set":
        data = {k: str(v) for k, v in args.items() if v is not None}
        return ok(admin_request("POST", "/internalSettings", data=data))

    if name == "admin_query_settings_get":
        return ok(admin_request("GET", "/settings/querySettings"))

    if name == "admin_query_settings_set":
        data = {k: str(v) for k, v in args.items() if v is not None}
        return ok(admin_request("POST", "/settings/querySettings", data=data))

    if name == "admin_prometheus_targets":
        return ok(admin_request("GET", "/prometheus_sd_config"))

    raise ValueError(f"Unknown stats tool: {name}")
