"""handlers/security.py – Users, groups, roles, RBAC, audit, certs, password policy."""

from __future__ import annotations
from mcp.types import Tool, TextContent
from .shared import admin_request, ok

TOOLS: list[Tool] = [
    # ── Users ────────────────────────────────────────────────────────────
    Tool(name="admin_user_list",
         description="List all local or external users.",
         inputSchema={"type": "object",
                      "properties": {
                          "domain": {"type": "string", "enum": ["local", "external"],
                                     "description": "Default: local"}
                      }}),

    Tool(name="admin_user_get",
         description="Get details for a specific user.",
         inputSchema={"type": "object",
                      "properties": {
                          "domain":   {"type": "string", "enum": ["local", "external"]},
                          "username": {"type": "string"},
                      },
                      "required": ["username"]}),

    Tool(name="admin_user_create",
         description=(
             "Create or update a local user. "
             "roles is a comma-separated string, e.g. 'admin' or 'bucket_admin[travel-sample]'."
         ),
         inputSchema={"type": "object",
                      "properties": {
                          "username": {"type": "string"},
                          "password": {"type": "string"},
                          "name":     {"type": "string", "description": "Display name"},
                          "roles":    {"type": "string",
                                       "description": "Comma-separated role list"},
                          "groups":   {"type": "string",
                                       "description": "Comma-separated group list"},
                      },
                      "required": ["username", "password", "roles"]}),

    Tool(name="admin_user_delete",
         description="Delete a local or external user.",
         inputSchema={"type": "object",
                      "properties": {
                          "domain":   {"type": "string", "enum": ["local", "external"]},
                          "username": {"type": "string"},
                      },
                      "required": ["username"]}),

    Tool(name="admin_user_change_password",
         description="Change the password for a local user.",
         inputSchema={"type": "object",
                      "properties": {
                          "username": {"type": "string"},
                          "password": {"type": "string"},
                      },
                      "required": ["username", "password"]}),

    # ── Groups ───────────────────────────────────────────────────────────
    Tool(name="admin_group_list",
         description="List all user groups.",
         inputSchema={"type": "object", "properties": {}}),

    Tool(name="admin_group_get",
         description="Get details for a specific user group.",
         inputSchema={"type": "object",
                      "properties": {"group_name": {"type": "string"}},
                      "required": ["group_name"]}),

    Tool(name="admin_group_create",
         description="Create or update a user group.",
         inputSchema={"type": "object",
                      "properties": {
                          "group_name":  {"type": "string"},
                          "description": {"type": "string"},
                          "roles":       {"type": "string"},
                          "ldap_group_ref": {"type": "string"},
                      },
                      "required": ["group_name", "roles"]}),

    Tool(name="admin_group_delete",
         description="Delete a user group.",
         inputSchema={"type": "object",
                      "properties": {"group_name": {"type": "string"}},
                      "required": ["group_name"]}),

    # ── Roles ────────────────────────────────────────────────────────────
    Tool(name="admin_role_list",
         description="List all available RBAC roles in the cluster.",
         inputSchema={"type": "object", "properties": {}}),

    # ── Who am I ─────────────────────────────────────────────────────────
    Tool(name="admin_whoami",
         description="Return the identity and roles of the currently authenticated user.",
         inputSchema={"type": "object", "properties": {}}),

    # ── Audit ────────────────────────────────────────────────────────────
    Tool(name="admin_audit_get",
         description="Retrieve current audit configuration.",
         inputSchema={"type": "object", "properties": {}}),

    Tool(name="admin_audit_set",
         description="Configure audit settings (enabled, log_path, rotate_interval, etc.).",
         inputSchema={"type": "object",
                      "properties": {
                          "auditdEnabled":    {"type": "boolean"},
                          "logPath":          {"type": "string"},
                          "rotateInterval":   {"type": "integer",
                                              "description": "Rotation interval in seconds"},
                          "rotateSize":       {"type": "integer",
                                              "description": "Max log size in bytes"},
                          "disabledUsers":    {"type": "array", "items": {"type": "string"}},
                      }}),

    # ── Password policy ───────────────────────────────────────────────────
    Tool(name="admin_password_policy_get",
         description="Retrieve the current password policy.",
         inputSchema={"type": "object", "properties": {}}),

    Tool(name="admin_password_policy_set",
         description="Set password policy (minLength, enforceUppercase, enforceLowercase, enforceDigits, enforceSpecialChars).",
         inputSchema={"type": "object",
                      "properties": {
                          "minLength":          {"type": "integer"},
                          "enforceUppercase":   {"type": "boolean"},
                          "enforceLowercase":   {"type": "boolean"},
                          "enforceDigits":      {"type": "boolean"},
                          "enforceSpecialChars":{"type": "boolean"},
                      }}),

    # ── Security settings ─────────────────────────────────────────────────
    Tool(name="admin_security_settings_get",
         description="Get global security / TLS settings.",
         inputSchema={"type": "object", "properties": {}}),

    Tool(name="admin_security_settings_set",
         description="Update global security settings (tlsMinVersion, honorCipherOrder, cipherSuites, etc.).",
         inputSchema={"type": "object",
                      "properties": {
                          "tlsMinVersion":    {"type": "string",
                                              "enum": ["tlsv1", "tlsv1.1", "tlsv1.2", "tlsv1.3"]},
                          "honorCipherOrder": {"type": "boolean"},
                          "cipherSuites":     {"type": "array", "items": {"type": "string"}},
                      }}),
]


def handle(name: str, args: dict) -> list[TextContent]:
    domain = args.get("domain", "local")

    if name == "admin_user_list":
        return ok(admin_request("GET", f"/settings/rbac/users/{domain}"))

    if name == "admin_user_get":
        u = args["username"]
        return ok(admin_request("GET", f"/settings/rbac/users/{domain}/{u}"))

    if name == "admin_user_create":
        u    = args["username"]
        data = {
            "password": args["password"],
            "roles":    args["roles"],
        }
        if args.get("name"):   data["name"]   = args["name"]
        if args.get("groups"): data["groups"] = args["groups"]
        return ok(admin_request("PUT", f"/settings/rbac/users/local/{u}", data=data))

    if name == "admin_user_delete":
        u = args["username"]
        return ok(admin_request("DELETE", f"/settings/rbac/users/{domain}/{u}"))

    if name == "admin_user_change_password":
        u = args["username"]
        return ok(admin_request("PUT", f"/settings/rbac/users/local/{u}",
                                data={"password": args["password"]}))

    if name == "admin_group_list":
        return ok(admin_request("GET", "/settings/rbac/groups"))

    if name == "admin_group_get":
        return ok(admin_request("GET", f"/settings/rbac/groups/{args['group_name']}"))

    if name == "admin_group_create":
        g    = args["group_name"]
        data = {"roles": args["roles"]}
        if args.get("description"):   data["description"]   = args["description"]
        if args.get("ldap_group_ref"): data["ldap_group_ref"] = args["ldap_group_ref"]
        return ok(admin_request("PUT", f"/settings/rbac/groups/{g}", data=data))

    if name == "admin_group_delete":
        return ok(admin_request("DELETE", f"/settings/rbac/groups/{args['group_name']}"))

    if name == "admin_role_list":
        return ok(admin_request("GET", "/settings/rbac/roles"))

    if name == "admin_whoami":
        return ok(admin_request("GET", "/whoami"))

    if name == "admin_audit_get":
        return ok(admin_request("GET", "/settings/audit"))

    if name == "admin_audit_set":
        data = {k: str(v) for k, v in args.items() if v is not None}
        return ok(admin_request("POST", "/settings/audit", data=data))

    if name == "admin_password_policy_get":
        return ok(admin_request("GET", "/settings/passwordPolicy"))

    if name == "admin_password_policy_set":
        data = {k: str(v) for k, v in args.items() if v is not None}
        return ok(admin_request("POST", "/settings/passwordPolicy", data=data))

    if name == "admin_security_settings_get":
        return ok(admin_request("GET", "/settings/security"))

    if name == "admin_security_settings_set":
        data = {k: str(v) for k, v in args.items() if v is not None}
        return ok(admin_request("POST", "/settings/security", data=data))

    raise ValueError(f"Unknown security tool: {name}")
