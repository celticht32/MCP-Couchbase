# Connection management

How your application connects to Couchbase determines a lot — performance, resilience, security, operability. This reference covers connection strings, the Cluster object lifecycle, TLS setup, mTLS, and connection pooling behavior.

## The Cluster → Bucket → Collection model

All modern Couchbase SDKs follow the same hierarchy:

```
Cluster (one per application typically — owns connections, auth)
 └── Bucket (logical container, named at runtime)
      └── Scope (default: "_default")
           └── Collection (default: "_default")
                └── KV / Query operations happen here
```

```python
# Python example
cluster = Cluster("couchbases://cb.example.com",
                  ClusterOptions(authenticator=PasswordAuthenticator("user", "pass")))
bucket = cluster.bucket("my-bucket")
scope = bucket.scope("orders")
collection = scope.collection("active")
result = collection.upsert("order::42", {"total": 142.10})
```

**Key insight:** Cluster is the expensive object. Create it once at app startup; reuse it for the application's lifetime. Bucket, Scope, Collection are cheap handles — create as needed.

**Anti-pattern:** creating a new Cluster per request. This is the most common Couchbase performance bug. Connections take seconds to establish (TLS, auth, cluster map fetch); creating a new one per request adds that latency to every request.

## Connection strings

Format: `<scheme>://<host1>[,<host2>,<host3>][?option=value&...]`

| Scheme | Use |
|---|---|
| `couchbase://` | Non-TLS — deprecated for production |
| `couchbases://` | TLS — required for Capella, recommended everywhere |

**Multiple hosts:** comma-separated. The SDK only needs ONE to be reachable; it fetches the full cluster map after connecting. Listing 2-3 is a good practice for first-connection resilience.

```
couchbases://cb-1.example.com,cb-2.example.com,cb-3.example.com
```

**Capella connection strings:** look like `couchbases://cb.<cluster-id>.cloud.couchbase.com`. Get it from `capella_cluster_get` or the Capella UI.

**Useful options** (URL parameters):

| Option | Example | Use |
|---|---|---|
| `timeout.kv` | `?timeout.kv=5s` | Override default KV timeout (default 2.5s) |
| `timeout.query` | `?timeout.query=75s` | Override default query timeout (default 75s) |
| `network` | `?network=external` | Use external network mapping (Capella + private link) |
| `enable_tls` | `?enable_tls=true` | Force TLS even with `couchbase://` scheme |

## Authentication

Modern SDKs use Password authentication (username + password) by default; some support certificate authentication (mTLS).

**Password auth:**

```java
// Java
Cluster cluster = Cluster.connect("couchbases://...",
    ClusterOptions.clusterOptions("username", "password"));
```

```python
# Python
auth = PasswordAuthenticator("username", "password")
cluster = Cluster("couchbases://...", ClusterOptions(authenticator=auth))
```

**Certificate auth (mTLS):**

```python
# Python
auth = CertificateAuthenticator(
    cert_path="/path/to/client.pem",
    key_path="/path/to/client.key"
)
cluster = Cluster("couchbases://...", ClusterOptions(authenticator=auth))
```

Password auth is the default; certificate auth is for highest-security environments where you don't want passwords in config.

## TLS setup

Production should always use TLS. The SDK needs to trust the cluster's certificate:

**Public CA-signed cert (e.g., Capella):** works out of the box. No client-side trust setup needed.

**Self-signed or internal-CA cert:** the SDK needs the CA cert path:

```python
options = ClusterOptions(
    authenticator=PasswordAuthenticator("user", "pass"),
    cert_path="/path/to/ca-cert.pem"
)
cluster = Cluster("couchbases://...", options)
```

**Specifying the CA cert** vs **disabling TLS verification:** never do the latter in production. Disabling verification means any man-in-the-middle can impersonate the cluster. If certs aren't working, fix the trust chain rather than disabling verification.

## Connection pooling

SDKs manage connection pooling internally. You don't typically need to configure this, but for high-throughput servers a few knobs help:

| Setting | Default | When to tune |
|---|---|---|
| `kv_endpoints` per node | 1 (Java) / varies | Increase to 2-4 for very high QPS workloads |
| `query_endpoints` per node | 1 | Increase if running many concurrent queries |
| `idle_http_connection_timeout` | 4500ms | Match to your network's NAT/firewall idle timeout |

```java
// Java example — bump KV endpoints
Cluster cluster = Cluster.connect("couchbases://...",
    ClusterOptions.clusterOptions(authenticator)
        .ioConfig(IoConfig.numKvConnections(2)));
```

The default is fine for 95% of applications. Only tune if profiling shows connection contention.

## Cluster object lifecycle

**At startup:** create Cluster, call `cluster.wait_until_ready(timeout)` to verify connectivity before serving traffic. Otherwise the first request takes the full connection-setup time.

**During runtime:** reuse the Cluster object. Bucket, Scope, Collection handles can be cached or re-obtained — both are cheap.

**At shutdown:** call `cluster.disconnect()` (or `cluster.close()` depending on SDK) to cleanly close connections. Important for graceful shutdown; less important for crash recovery.

**Sample structure:**

```python
# Module-level singleton
_cluster: Optional[Cluster] = None

def get_cluster():
    global _cluster
    if _cluster is None:
        _cluster = Cluster("couchbases://...",
                            ClusterOptions(authenticator=PasswordAuthenticator(...)))
        _cluster.wait_until_ready(timedelta(seconds=10))
    return _cluster

def shutdown():
    if _cluster:
        _cluster.disconnect()
```

For DI-based frameworks (Spring, ASP.NET Core), register Cluster as a singleton.

## Failover behavior — what the SDK does automatically

When a node fails:

1. SDK detects it via heartbeat / failed request
2. Retries the failed request against another node hosting the data (within the SDK's retry budget — typically the operation's timeout)
3. Caller sees either success (if retry worked) or timeout/failure (if cluster genuinely can't serve)

Cluster topology changes (failover, rebalance, node add) are propagated to the SDK via the config endpoint. The SDK updates its routing tables transparently. **You don't write code to handle node failures** — the SDK handles it. Your code only sees the outcome.

## Network setups — public, private link, VPC peering

**Public access** (default Capella): `couchbases://cb.<id>.cloud.couchbase.com`. Allowed CIDRs in Capella must include your app's egress IP.

**Private endpoint / private link:** add `?network=external` to the connection string. The cluster has separate internal and external addresses; this option tells the SDK which to use.

**VPC peering (cloud):** treat as a private network — same connection string format as public but lower latency and no internet egress cost.

For all setups: the network path matters more than the connection string. A misconfigured firewall causes the same symptom as a wrong connection string (connection refused). Verify network reachability before debugging client config.

## Connection string anti-patterns

- **Hardcoded credentials in connection strings:** put credentials in env vars / secrets manager, not in code
- **Passing the cluster object across processes** (forking after connection): the connections aren't shared across the fork; the child gets broken sockets. Connect AFTER fork
- **One Cluster per database operation:** see "Cluster object lifecycle" above — Cluster is meant to live for the app's lifetime
- **Hardcoding bucket / scope / collection in connection string:** the connection string is the cluster address; specify bucket/scope/collection separately

## Quick decision tree

- **Cluster object — when to create?** Once at app startup; reuse for app lifetime
- **TLS — when to use?** Always in production; mandatory for Capella (always use `couchbases://`)
- **Self-signed cert?** Pass `cert_path` to the cluster options; don't disable TLS verification
- **Capella?** Use `couchbases://`; get connection string from `capella_cluster_get`; ensure allowed CIDR includes your app
- **Auth method?** Password (default); mTLS if your security posture requires it
- **Connection pooling?** SDK handles automatically; only tune for very high QPS
- **Node failed?** SDK handles routing; your code does nothing special
