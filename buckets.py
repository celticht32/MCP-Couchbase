"""handlers/buckets.py – Bucket & sample-bucket admin tools."""

from __future__ import annotations
from mcp.types import Tool, TextContent
from .shared import admin_request, ok, err

TOOLS: list[Tool] = [
    Tool(name="admin_bucket_list",
         description="List all buckets in the cluster.",
         inputSchema={"type": "object", "properties": {}}),

    Tool(name="admin_bucket_get",
         description="Get detailed information about a specific bucket.",
         inputSchema={"type": "object",
                      "properties": {"bucket_name": {"type": "string"}},
                      "required": ["bucket_name"]}),

    Tool(name="admin_bucket_create",
         description=(
             "Create a new bucket. Common params: name, bucketType (couchbase|ephemeral|memcached), "
             "ramQuota (MB), replicaNumber, flushEnabled (0|1), compressionMode, storageBackend (couchstore|magma)."
         ),
         inputSchema={
             "type": "object",
             "properties": {
                 "name":           {"type": "string"},
                 "bucketType":     {"type": "string", "enum": ["couchbase", "ephemeral", "memcached"]},
                 "ramQuota":       {"type": "integer", "description": "RAM quota in MB"},
                 "replicaNumber":  {"type": "integer"},
                 "flushEnabled":   {"type": "integer", "enum": [0, 1]},
                 "compressionMode":{"type": "string", "enum": ["off", "passive", "active"]},
                 "storageBackend": {"type": "string", "enum": ["couchstore", "magma"]},
             },
             "required": ["name", "ramQuota"],
         }),

    Tool(name="admin_bucket_update",
         description="Update settings on an existing bucket (ramQuota, replicaNumber, flushEnabled, etc.).",
         inputSchema={
             "type": "object",
             "properties": {
                 "bucket_name":    {"type": "string"},
                 "ramQuota":       {"type": "integer"},
                 "replicaNumber":  {"type": "integer"},
                 "flushEnabled":   {"type": "integer", "enum": [0, 1]},
                 "compressionMode":{"type": "string"},
             },
             "required": ["bucket_name"],
         }),

    Tool(name="admin_bucket_delete",
         description="Delete a bucket and all its data. IRREVERSIBLE.",
         inputSchema={"type": "object",
                      "properties": {"bucket_name": {"type": "string"}},
                      "required": ["bucket_name"]}),

    Tool(name="admin_bucket_flush",
         description="Flush (delete all documents from) a bucket. Requires flushEnabled=1.",
         inputSchema={"type": "object",
                      "properties": {"bucket_name": {"type": "string"}},
                      "required": ["bucket_name"]}),

    Tool(name="admin_bucket_compact",
         description="Trigger compaction on a bucket to reclaim disk space.",
         inputSchema={"type": "object",
                      "properties": {"bucket_name": {"type": "string"}},
                      "required": ["bucket_name"]}),

    Tool(name="admin_bucket_cancel_compaction",
         description="Cancel an in-progress compaction on a bucket.",
         inputSchema={"type": "object",
                      "properties": {"bucket_name": {"type": "string"}},
                      "required": ["bucket_name"]}),

    Tool(name="admin_sample_buckets_list",
         description="List available sample buckets (e.g. travel-sample, beer-sample).",
         inputSchema={"type": "object", "properties": {}}),

    Tool(name="admin_sample_buckets_install",
         description="Install one or more sample buckets by name.",
         inputSchema={"type": "object",
                      "properties": {
                          "buckets": {"type": "array", "items": {"type": "string"},
                                      "description": "e.g. [\"travel-sample\", \"beer-sample\"]"}
                      },
                      "required": ["buckets"]}),
]


def handle(name: str, args: dict) -> list[TextContent]:
    if name == "admin_bucket_list":
        return ok(admin_request("GET", "/pools/default/buckets"))

    if name == "admin_bucket_get":
        return ok(admin_request("GET", f"/pools/default/buckets/{args['bucket_name']}"))

    if name == "admin_bucket_create":
        data = {k: v for k, v in args.items() if v is not None}
        if "ramQuota" in data:
            data["ramQuotaMB"] = data.pop("ramQuota")
        return ok(admin_request("POST", "/pools/default/buckets", data=data))

    if name == "admin_bucket_update":
        bucket = args.pop("bucket_name")
        data   = {k: v for k, v in args.items() if v is not None}
        if "ramQuota" in data:
            data["ramQuotaMB"] = data.pop("ramQuota")
        return ok(admin_request("POST", f"/pools/default/buckets/{bucket}", data=data))

    if name == "admin_bucket_delete":
        return ok(admin_request("DELETE", f"/pools/default/buckets/{args['bucket_name']}"))

    if name == "admin_bucket_flush":
        b = args["bucket_name"]
        return ok(admin_request("POST", f"/pools/default/buckets/{b}/controller/doFlush"))

    if name == "admin_bucket_compact":
        b = args["bucket_name"]
        return ok(admin_request("POST", f"/pools/default/buckets/{b}/controller/compactBucket"))

    if name == "admin_bucket_cancel_compaction":
        b = args["bucket_name"]
        return ok(admin_request("POST", f"/pools/default/buckets/{b}/controller/cancelBucketCompaction"))

    if name == "admin_sample_buckets_list":
        return ok(admin_request("GET", "/sampleBuckets"))

    if name == "admin_sample_buckets_install":
        import json as _json
        # The endpoint expects a JSON array body
        import urllib.request, urllib.parse, urllib.error, base64
        from .shared import _admin_url, get_env
        url  = f"{_admin_url()}/sampleBuckets/install"
        cred = base64.b64encode(
            f"{get_env('CB_USERNAME','Administrator')}:{get_env('CB_PASSWORD','password')}".encode()
        ).decode()
        body = _json.dumps(args["buckets"]).encode()
        req  = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Authorization", f"Basic {cred}")
        req.add_header("Content-Type",  "application/json")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return ok(_json.loads(resp.read()))

    raise ValueError(f"Unknown bucket tool: {name}")
