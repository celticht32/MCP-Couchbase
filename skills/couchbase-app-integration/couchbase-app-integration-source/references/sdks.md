# SDKs — choosing, installing, version awareness

Couchbase ships official SDKs in multiple languages. They share the same underlying protocol but differ in idioms, maturity, and feature coverage. This reference helps pick the right one and avoid common version traps.

## The SDK list

Currently officially-supported SDKs (verify current support status at https://docs.couchbase.com):

| Language | Package | Maturity | Notes |
|---|---|---|---|
| Java | `com.couchbase.client:java-client` | Reference SDK — most mature, fullest coverage | Reactive (Reactor-based) by default |
| .NET | `CouchbaseNetClient` | Mature | C# / F#; async/await throughout |
| Node.js | `couchbase` (npm) | Mature | TypeScript types included |
| Python | `couchbase` (pypi) | Mature | Sync and async (asyncio + Twisted) variants |
| Go | `github.com/couchbase/gocb/v2` | Mature | Idiomatic Go; channels not used (context-based) |
| C | `libcouchbase` | Mature, low-level | Foundation for some other SDKs |
| Ruby | `couchbase` gem | Less actively developed; verify status before relying on it |
| PHP | `couchbase` pecl | Less actively developed; verify status |
| Scala | `com.couchbase.client::scala-client` | Mature; wraps the Java SDK |
| Kotlin | `com.couchbase.client:kotlin-client` | Mature | Coroutine-based |
| Swift | Couchbase Lite (different product) | Mobile only — not the server SDK |

**For brand-new projects:** Java or .NET if your stack supports them — they get features first. Python and Node are excellent and current. Go for systems work. Scala/Kotlin wrap Java with their own idioms.

## Major version awareness

The SDKs have had significant version transitions:

| SDK | Modern version | Older patterns to avoid |
|---|---|---|
| Java | 3.x | Java 2.x used different APIs (cluster.openBucket → cluster.bucket) |
| .NET | 3.x | 2.x used different connection patterns and DI conventions |
| Node | 4.x | 3.x used callbacks; 4.x is promise-based |
| Python | 4.x | 3.x was a major rewrite from 2.x; 2.x docs are misleading for current users |
| Go | gocb/v2 | gocb v1 had different APIs entirely |

**If the user cites a code snippet that doesn't match current docs:** ask which SDK version they're on. Tutorials older than ~2-3 years often show patterns that don't work anymore.

## Install commands by language

**Java (Maven):**
```xml
<dependency>
  <groupId>com.couchbase.client</groupId>
  <artifactId>java-client</artifactId>
  <version>3.x.y</version>
</dependency>
```

**Java (Gradle):**
```gradle
implementation 'com.couchbase.client:java-client:3.x.y'
```

**.NET (NuGet):**
```bash
dotnet add package CouchbaseNetClient --version 3.x.y
```

**Node.js:**
```bash
npm install couchbase
```

**Python:**
```bash
pip install couchbase
```

**Go:**
```bash
go get github.com/couchbase/gocb/v2
```

**Scala (sbt):**
```scala
libraryDependencies += "com.couchbase.client" %% "scala-client" % "1.x.y"
```

**Kotlin (Gradle):**
```gradle
implementation 'com.couchbase.client:kotlin-client:1.x.y'
```

Always check the SDK's docs page for current minor version — these change frequently for bug fixes.

## SDK feature parity considerations

Most data operations (KV, query, FTS) are available in all official SDKs. Some newer features land in some SDKs before others:

- **Couchbase 8.x vector search**: Java, .NET, Python, Node, Go support it; Ruby and PHP lag
- **Distributed transactions library**: Java has the richest API; .NET / Node / Python / Go all support transactions but with some API differences
- **Eventing function management**: covered by the MCP / REST API, not typically SDK-side
- **Capella v4 control plane**: not an SDK feature — use the Capella REST API or the celticht32 MCP

When the user asks "can my SDK do X?" and X is a newer feature: check the SDK's specific release notes rather than assuming feature parity.

## Sync vs async clients

Several SDKs offer both sync and async APIs:

**Java:** Three flavors — blocking, reactive (Project Reactor), async (CompletableFuture). Pick reactive for high-throughput servers, blocking for batch jobs.

**.NET:** Async throughout; no truly sync API in modern versions. Use `Task` / `async`/`await`.

**Node.js:** Promise-based throughout; works with async/await.

**Python:** Three flavors — sync (default), asyncio (`acouchbase`), Twisted (`txcouchbase`). Pick asyncio for modern Python servers, sync for scripts and batch jobs.

**Go:** Single API with context for cancellation — no separate sync/async APIs.

**Recommendation:** match your application's existing pattern. A FastAPI Python service should use `acouchbase`; a Click CLI tool can use sync `couchbase`. Mixing within one component is awkward; mixing across components is fine.

## Compatibility matrix

| Server version | Minimum SDK version (typical) |
|---|---|
| 7.x | SDK 3.x+ (Java/Net/Node/Python) |
| 8.x | SDK 3.4+ for vector search; 3.x sufficient for basics |
| Capella (latest) | Latest SDK strongly recommended |

The SDK auto-negotiates protocol features with the server, so a recent SDK against a slightly older server is generally fine. Old SDK against new server is more likely to miss features.

## Couchbase Mobile vs server SDKs

Don't confuse these:

- **Server SDKs** (this reference): connect application servers to a Couchbase cluster
- **Couchbase Mobile / Lite / App Services**: a separate product for mobile apps with offline-first sync

If the user mentions "Couchbase Lite," "Sync Gateway," "App Services," or mobile/offline patterns — that's the mobile product line, not what this skill covers. Refer them to https://docs.couchbase.com/couchbase-lite/current/.

## Where to find the docs

- **All SDK docs:** https://docs.couchbase.com → click your SDK in the sidebar
- **API reference:** typically `https://docs.couchbase.com/sdk-api/<language>-<version>/`
- **GitHub repos:** searchable; useful for examples and issue tracker
- **Release notes:** announce new features and behavioral changes; worth scanning when upgrading

## Quick decision tree

- **Java / Spring / enterprise?** → Java SDK (reactive flavor for servers, blocking for batch)
- **.NET / ASP.NET?** → .NET SDK
- **Node.js?** → Node SDK (always async)
- **Python web service?** → asyncio variant (`acouchbase`)
- **Python script / batch?** → sync `couchbase`
- **Go?** → gocb v2
- **Scala?** → Scala SDK (wraps Java; Scala idioms)
- **Kotlin?** → Kotlin SDK (coroutines)
- **Mobile or offline-first?** → Couchbase Lite (different product line)
- **Code snippet looks wrong?** → check the SDK version; old tutorials are out of date
