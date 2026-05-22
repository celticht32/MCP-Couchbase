# Security best practices

This reference is for *designing* security, not just calling the tools that change it. When the user is creating users, granting roles, configuring audit, deciding on encryption, or hardening a cluster, walk them through these patterns before reaching for `admin_user_create` or `admin_security_set`.

## RBAC design — groups before direct grants

The fastest way to get RBAC wrong is to grant roles directly to users one by one. After about five users, you have no idea who has what, and revocation becomes a manual audit.

**Pattern: define roles by function, not person.**

```
group: data_engineers
  roles: query_select[*], query_manage_index[*], data_writer[ingestion]

group: app_readers
  roles: data_reader[app_data], query_select[app_data]

group: oncall_admins
  roles: cluster_admin, bucket_admin[*]
```

Then assign users to groups via `admin_user_update` (each user gets a `groups` array). The user's effective permissions are the union of all their groups' roles plus any direct roles. Direct roles are an escape hatch for one-off exceptions, not the default mechanism.

**When direct grants are correct:**
- One-time access for a specific incident (use `admin_user_create_temporary` if 8.x)
- Service accounts where the role is unique to that service (e.g., a backup tool needing `data_backup[*]` on its own)

**When groups are correct:** everything else.

## The principle of least privilege, applied

Couchbase has ~40 distinct roles. The wrong default is to grant `admin` to everyone who "needs access." The right default is to grant the narrowest role that lets the user do their job.

| Use case | Right role(s) |
|---|---|
| App reading its own data | `data_reader[<bucket>]`, `query_select[<bucket>]` |
| App writing its own data | Above + `data_writer[<bucket>]` |
| Backend doing both reads and writes | `data_reader[<bucket>]`, `data_writer[<bucket>]`, `query_select[<bucket>]`, `query_update[<bucket>]`, `query_insert[<bucket>]`, `query_delete[<bucket>]` |
| Analyst running ad-hoc queries | `query_select[<bucket>]`, optionally `analytics_select[<bucket>]` |
| On-call engineer (read-only diagnosis) | `data_reader[*]`, `query_select[*]`, `cluster_settings_read`, `security_read` |
| On-call engineer (incident response) | Above + `cluster_admin` — but consider `admin_user_create_temporary` instead |
| Index management | `query_manage_index[<bucket>]` |
| FTS index management | `fts_admin[<bucket>]` |
| Full cluster admin | `admin` — reserve for break-glass and the security team |

**Common mistake:** granting `data_writer[<bucket>]` to "the app" when the app only needs to write one collection. The collection-scoped variant (`data_writer[<bucket>:<scope>:<collection>]`) limits blast radius substantially.

## External identity providers — LDAP, SAML, AD: NOT exposed by this MCP

Couchbase Server fully supports LDAP (for both authentication and group-based authorization), SAML 2.0 SSO (for the web UI in 7.6+), and SASL/PLAIN authentication via saslauthd. **This MCP does NOT expose tools for configuring any of them.** The 17-tool security surface covers local users, groups, roles, audit, password policy, encryption, and KMIP — but not the external-identity REST endpoints (`/settings/ldap`, `/settings/saslauthd`, `/settings/security/saml`).

If the user asks "how do I configure LDAP / SAML / Active Directory in Couchbase":

**Don't try to find an MCP tool for it.** There isn't one. Recommend the right access path instead:

| Scenario | Right tool |
|---|---|
| Configuring LDAP for the first time | Web UI → Security → LDAP. Friendliest; full feature coverage including group-mapping rules and bind-DN templates |
| Scripting LDAP config in CI/CD | `couchbase-cli setting-ldap` |
| Configuring SAML 2.0 SSO (web UI, 7.6+) | Web UI → Security → SAML. Tightly coupled to IdP metadata (Okta, Auth0, Azure AD etc.); needs interactive setup |
| Configuring saslauthd (PAM, etc.) | Web UI → Security → External Users, or `couchbase-cli setting-saslauthd-auth` |
| Infrastructure-as-code | Couchbase Ansible role, Terraform provider, or direct REST calls to `/settings/ldap` |
| Testing an existing LDAP config | Web UI → Security → LDAP → "Test Configuration" button, or REST POST to `/settings/ldap/validate` |

**Why these aren't in the MCP:**

- **Blast radius:** a misconfigured LDAP server blocks all federated logins. The web UI's interactive validation (group-mapping preview, bind test, test-user authentication) makes this safer than calling REST endpoints from a chat
- **Lifecycle mismatch:** LDAP/SAML configuration is set once at install and rarely changed; it belongs in IaC, not chat-driven ops
- **Live-server dependency:** validating LDAP config requires a reachable LDAP server with realistic test users — not something the MCP fork could verify during development

**What the MCP DOES cover for federated users:**

Once LDAP/SAML is configured externally, Couchbase treats external users similarly to local users for most RBAC operations. So:

- `admin_user_list` shows both local AND external users (with a `domain` field distinguishing them: `local` vs `external`)
- `admin_user_get` retrieves an external user's role assignments
- `admin_user_update` can grant/revoke roles for an external user (the user record exists in Couchbase even though authentication is delegated externally)
- `admin_user_delete` removes the Couchbase-side record (does NOT touch the LDAP directory)
- `admin_group_*` tools manage groups that BOTH local and external users can belong to
- `admin_audit_*` captures authentication events from external users the same way as local users

So you can think of it as: external identity provider sets up WHO can log in; the MCP manages WHAT THEY CAN DO once logged in (via groups and role assignments).

**If LDAP/SAML support in the MCP would be valuable for your workflow:** open a feature request at https://github.com/celticht32/MCP-Couchbase. The relevant REST endpoints are well-documented; the fork has historically been responsive to expanding the security surface when there's a clear use case.

## Audit — what to capture without drowning

The default audit configuration in Couchbase is "off" — you must enable it explicitly via `admin_audit_set`. The next mistake is enabling *everything*, which drowns the audit log in noise.

**Categories worth always enabling:**
- Authentication events (every login, success and failure)
- User/role modifications (any RBAC change)
- Bucket lifecycle (create, delete, flush)
- Index lifecycle (create, drop)
- Security setting changes
- XDCR config changes

**Categories worth enabling for production data:**
- Document modifications above a threshold (set the threshold via the `sample_rate` option, not 100% — that's expensive)
- N1QL queries (DDL specifically; full DML logging is usually too much)

**Categories that are usually noise:**
- Internal RPC chatter
- Successful KV reads (high-volume; log only failures)
- Stats endpoint hits (the monitoring stack hits these constantly)

If the user is enabling audit for compliance (SOC 2, HIPAA, PCI), they typically need everything except the stats noise. Document the audit policy somewhere outside Couchbase too — auditors want to see "this is what we audit and why."

Check current state with `admin_audit_get` before changing anything. Modifying audit settings is itself an audited event in most policies.

## Password policy

The defaults are lenient. For anything resembling production, raise them via `admin_password_policy_set`:

**Recommended minimums:**
- `min_length`: 12 (NIST 800-63B; 14 if you can get it)
- `min_uppercase`: 1
- `min_lowercase`: 1
- `min_digits`: 1
- `min_special`: 1 (some sources argue against this — service-account passwords often can't include special chars due to escaping)
- `forbid_reuse`: 5 (last 5 passwords)
- `expiry_days`: 90 for human users; **0 (never) for service accounts** — rotation is via API key rotation, not password expiry

The policy applies to local users only (not LDAP / SAML-federated users — those follow the IdP's policy).

## When KMIP is warranted

Couchbase 8.x supports DARE (Data-at-Rest Encryption) standalone OR with KMIP (Key Management Interoperability Protocol) integrating an external key manager.

**Use plain DARE (no KMIP) when:**
- You need encryption-at-rest for compliance but don't have an external KMS
- You're OK with Couchbase managing its own data encryption keys
- Your threat model is "stolen disk / decommissioned hardware"

**Use DARE + KMIP when:**
- You already run a KMS (Vault, AWS KMS, HashiCorp, Thales, etc.) and corporate policy requires it
- Your threat model includes "a Couchbase admin going rogue" — KMIP separates the key store from the database admin role
- Compliance (FIPS 140-2 Level 3, etc.) requires hardware-backed key storage

**Don't use KMIP when:**
- You don't already have a KMS — standing one up just for Couchbase is more risk than it removes
- Your operational team isn't trained on KMIP — a KMIP outage takes the cluster down

Test KMIP connectivity with `admin_kmip_test` before enabling — a bad KMIP config blocks new data encryption operations.

## Network isolation

**Allowed CIDRs** (Capella only — `capella_allowed_cidrs_list`): default to a deny-all posture. Add specific CIDR blocks for your application VPCs and your developers' egress IPs. Avoid `0.0.0.0/0` even temporarily — once it's there, you'll forget to remove it.

**TLS enforcement** (self-managed via `admin_security_set`): set `require_tls` to true once all clients are on TLS-capable SDKs. Test in staging first — non-TLS clients fail closed when this flips.

**Connection-string convention:**
- `couchbase://` — non-TLS (deprecated for production)
- `couchbases://` — TLS (required for Capella, recommended everywhere)

If you see `couchbase://` in production config, that's a finding. Migrate to `couchbases://` and roll out via blue-green rather than in-place — the cert chain validation can fail on first connect.

## How to phase a security tightening without locking yourself out

Three classic ways to lock yourself out of a Couchbase cluster:

1. **Enable TLS without distributing the CA cert to clients** — clients can't verify the cert, refuse to connect
2. **Tighten allowed CIDRs** without including your current admin IP — the next call fails
3. **Drop the only `admin` user** — no one can perform admin tasks

**The right order for a security tightening project:**

1. Verify there are at least two `admin` users from different teams (`admin_user_list` + filter by role)
2. Make sure the CA cert is distributed to all clients
3. Test the new config in staging end-to-end
4. Schedule the production change with a rollback ready
5. Apply the change
6. Verify with the smallest possible test (a single connection from a known-good client)
7. Wider rollout

For Capella allowlist changes: add the new CIDR ranges first, verify those work, then remove the old ones.

## Quick decision tree

- **"Granting access to a new team"** → create a group with the right roles via `admin_group_create`, assign users to it via `admin_user_update`
- **"Setting up LDAP / SAML / Active Directory"** → not via this MCP. Use the Couchbase web UI (Security → LDAP / SAML), `couchbase-cli setting-ldap`, or the REST API. Once configured, manage role grants for external users via the normal `admin_user_*` / `admin_group_*` tools
- **"Setting up audit for compliance"** → enable the categories above via `admin_audit_set`, then test `admin_alerts_test_email` for alert delivery
- **"Production deserves real password policy"** → `admin_password_policy_set` with the recommended minimums
- **"Should we enable KMIP?"** → only if you already run a KMS; otherwise plain DARE
- **"Locking down network access in Capella"** → `capella_allowed_cidrs_list` first to see current state, then update via Capella UI (write tools deliberately not in this MCP)
- **"Suspect a compromised account"** → `admin_user_lock` (8.x) to freeze it without losing the audit trail, investigate, then either unlock or delete
- **"Need someone admin for an hour"** → `admin_user_create_temporary` (8.x) with `expires_at`, don't grant `admin` directly
