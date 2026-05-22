# Capella v4 control plane — `capella_*` tools

These talk to Couchbase Capella's SaaS API at `cloudapi.cloud.couchbase.com` (or your region's endpoint). They are entirely separate from the cluster-level `cb_*` and `admin_*` tools and require different credentials.

## Setup

- **Endpoint:** `https://cloudapi.cloud.couchbase.com` (default; override with `CAPELLA_BASE_URL` for staging)
- **Auth:** Bearer token via `CAPELLA_API_KEY_SECRET`
- **How to get the secret:** In the Capella web UI: Settings → API Keys → Create API Key. The secret is shown **once** at creation — copy it then or it's lost forever
- **Required roles:** Most read tools work with Organization Owner or Project Viewer. Some (`capella_api_keys_list`) require Organization Owner specifically

If the user says "I don't have a Capella API key," walk them through getting one. There's no way around it for the `capella_*` tools.

## The resource hierarchy

Capella's data model is strictly hierarchical:

```
Organization (you have one per company)
├── Projects (named groupings of related clusters)
│   └── Clusters (operational Couchbase deployments)
│       ├── Database Users (per-cluster auth)
│       ├── Allowed CIDRs (IP allowlist)
│       └── App Services (Sync Gateway-equivalent, if enabled)
└── Organization-level resources
    ├── Organization Users (people with access to the org)
    └── API Keys (programmatic credentials)
```

Tools follow this hierarchy. You cannot list clusters globally — you must list projects first, pick a `projectId`, then list clusters under it.

## Tool catalogue (all read-only)

### Organization

| Tool | What it does |
|---|---|
| `capella_organizations_list` | All organizations the API key has access to. **Run this first** to verify connectivity |
| `capella_organization_get` | Detail for one organization |
| `capella_org_users_list` | List people with org-level access |
| `capella_org_user_get` | Detail for one org user |
| `capella_api_keys_list` | All API keys for the org (requires Organization Owner) |
| `capella_api_key_get` | Detail for one API key (still won't show the secret) |

### Projects

| Tool | What it does |
|---|---|
| `capella_projects_list` | All projects in an organization |
| `capella_project_get` | Detail for one project |

### Clusters

| Tool | What it does |
|---|---|
| `capella_clusters_list` | All clusters in a project |
| `capella_cluster_get` | Detail for one cluster (config, status, connection strings) |

### Per-cluster resources

| Tool | What it does |
|---|---|
| `capella_database_users_list` | Cluster-level Couchbase users (these are the credentials for `cb_*` tools) |
| `capella_database_user_get` | Detail for one database user |
| `capella_allowed_cidrs_list` | IP allowlist for the cluster |
| `capella_allowed_cidr_get` | Detail for one CIDR rule |
| `capella_app_services_list` | App Services attached to the cluster (mobile sync, if enabled) |
| `capella_app_service_get` | Detail for one App Service |

## Why no write operations?

Capella v4 supports write operations (cluster create, user invitation, allowlist edits, API key rotation, App Service deployment), but the celticht32 MCP server **deliberately doesn't expose them**.

The reasoning: an LLM running with broad Capella write access can spin up clusters, invite users to your organization, change allowlists to expose data to the internet, or rotate API keys with significant blast radius. Read-only is the safe default for a chat-driven interface. For Capella writes, point the user at:

- The Capella web UI (typical case)
- The Capella REST API via `curl` (advanced)
- A dedicated automation tool (Terraform, Pulumi) — the right answer for repeatable infra changes

If the user explicitly insists on a write tool, escalate: tell them this MCP doesn't have one, explain why, and ask if they want to proceed manually.

## Typical walkthrough

```
1. capella_organizations_list
   → gives you organizationId

2. capella_projects_list (orgId)
   → gives you projectIds; pick one

3. capella_clusters_list (orgId, projectId)
   → gives you clusterIds; pick one

4. capella_cluster_get (orgId, projectId, clusterId)
   → gives you the connection string, current state, services enabled

5. (Optional) capella_database_users_list, capella_allowed_cidrs_list,
   capella_app_services_list with the same orgId/projectId/clusterId for
   the per-cluster resources
```

Save the `organizationId` and `projectId` once you have them — they don't change and every subsequent call needs them.

## Capella vs. cluster — disambiguating

When the user says "Capella," figure out which they mean:

- **"my Capella org/projects/account"** → control plane → use `capella_*` tools
- **"a cluster hosted on Capella"** → data plane → use `cb_*` / `admin_*` tools, with `CB_CONNECTION_STRING=couchbases://<endpoint>` and `CB_MGMT_PORT=18091`

The credentials are different too: `capella_*` needs an API key secret; `cb_*` / `admin_*` need a database username/password (which you can find via `capella_database_users_list` if you have control-plane access).

Don't try to bridge them silently. If the user is in one mode and asks something that requires the other, surface the gap: "To do that, I need [API key secret / database user credentials] for the cluster — can you provide them or set the env var?"

## Common gotchas

**Rate limiting:** Capella v4 caps API key requests at ~100/minute. Rapid-fire calls (e.g., enumerating every cluster's app services in a loop) will eventually get 429 responses. The MCP retries with exponential backoff, but extended runs may still saturate the limit.

**Region-specific endpoints:** The default `cloudapi.cloud.couchbase.com` is global. Some enterprise deployments have region-specific endpoints (e.g., `eu-cloudapi.cloud.couchbase.com`). Override `CAPELLA_BASE_URL` if the user's Capella deployment uses one.

**API keys are scoped:** An API key created at the project level can only see resources under that project. If `capella_organizations_list` returns one item but you can't see expected projects, the key may be project-scoped. Check the Capella UI to see the key's scope.

**The secret is not echoed back:** Both the GUI's `/api/config` endpoint and the MCP's logs deliberately mask `CAPELLA_API_KEY_SECRET`. If the user asks "what's the current API key?" — you can't tell them, only whether one is set.

## Quick decision tree

- **"What clusters do I have?"** → `capella_organizations_list` → `capella_projects_list` → `capella_clusters_list`
- **"Show me the connection string for cluster X"** → `capella_cluster_get`
- **"Who has access to project Y?"** → `capella_org_users_list` (org-level access) or `capella_database_users_list` (cluster-level access)
- **"What IPs are allowed to connect?"** → `capella_allowed_cidrs_list`
- **"What API keys exist?"** → `capella_api_keys_list` (requires Org Owner)
- **"Create a new cluster"** → not supported by this MCP; use Capella UI or Terraform
- **"Verify my API key works"** → `capella_organizations_list` (returns 401 / 403 if the key is wrong)
