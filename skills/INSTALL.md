# Installing the Couchbase Claude skill suite

Five composable skills, designed to work together across the application lifecycle:

| Skill | What it's for | When it triggers |
|---|---|---|
| **`couchbase-data-modeling`** | Designing what to put in Couchbase | "how should I model X", "embed or reference", "scope vs collection", "schema design" |
| **`couchbase-sizing`** | Numerical capacity planning | "how much RAM", "how many nodes", "Capella tier", "scale up vs out" |
| **`couchbase-migration-execution`** | Moving data INTO Couchbase from another system | "migrate from MongoDB / Postgres / DynamoDB", "dual-write", "CDC", "cbimport", "cutover", "rollback" |
| **`couchbase-app-integration`** | Writing application code that talks to Couchbase | "Python/Java/Node SDK", "connection pool", "retry strategy", "durability", "bulk insert" |
| **`couchbase-mcp`** | Operating an existing cluster via celticht32/MCP-Couchbase (164 tools) | "list buckets", "create user", "rebalance", "XDCR", "explain query", "monitoring", "Prometheus" |

They cover five conversation phases — design → plan capacity → move data in → write app code → operate. Each triggers on **different vocabulary** so they don't conflict; they explicitly hand off to each other by name. Install all five for full coverage; install only the ones you need.

## What's in this bundle

For each of the five skills, three distribution formats:

| File | Use case | Size |
|---|---|---|
| `*.skill` | Canonical Agent Skills format | 28-43 KB |
| `*.zip` | Identical content, `.zip` extension. **Use this for Claude.ai's web uploader** | 28-43 KB |
| `*-source.tar.gz` | Source layout. **Use this for Claude Code** (extract into `~/.claude/skills/`) or to track in git | 23-35 KB |

Plus this `INSTALL.md`.

## Prerequisites

Before installing:

1. **For the `couchbase-mcp` skill to be useful:** you need celticht32/MCP-Couchbase running and connected to your Claude client. See https://github.com/celticht32/MCP-Couchbase. The other four skills don't require the MCP server — they're pure knowledge.
2. **For Claude.ai installs:** Code execution and File creation must be enabled in Settings → Capabilities.

## Install Path 1 — Claude.ai (web/mobile)

Use the `.zip` files.

**For Free, Pro, and Max plans:**

1. Go to https://claude.ai and sign in
2. Click your profile picture (bottom left) → **Settings**
3. **Capabilities** tab → verify Code execution and File creation is enabled
4. Left sidebar → **Customize** → **Skills**
5. Click **+ Upload skill**, select `couchbase-data-modeling.zip`
6. Repeat for `couchbase-sizing.zip`, `couchbase-migration-execution.zip`, `couchbase-app-integration.zip`, `couchbase-mcp.zip`
7. Each upload takes a few seconds; Claude displays each skill's name/description/license

**For Team plans:** Same per-user flow; an org owner can additionally provision all five org-wide via Settings → Skills.

**For Enterprise plans:** Org owner must first enable Skills in Organization settings → Skills (also requires Code execution and File creation enabled at the org level), then either provision org-wide or let members upload personally.

## Install Path 2 — Claude Code (terminal)

Use the source tarballs.

**User-level install — all 5 skills available in every project:**

```bash
mkdir -p ~/.claude/skills
tar xzf couchbase-data-modeling-source.tar.gz -C ~/.claude/skills/
tar xzf couchbase-sizing-source.tar.gz -C ~/.claude/skills/
tar xzf couchbase-migration-execution-source.tar.gz -C ~/.claude/skills/
tar xzf couchbase-app-integration-source.tar.gz -C ~/.claude/skills/
tar xzf couchbase-mcp-source.tar.gz -C ~/.claude/skills/
```

Verify:

```bash
ls ~/.claude/skills/
# Expect five directories:
#   couchbase-data-modeling/  couchbase-sizing/  couchbase-migration-execution/
#   couchbase-app-integration/  couchbase-mcp/
```

Restart any active Claude Code sessions.

**Project-level install — all 5 skills follow this repo:**

```bash
cd /path/to/your/project
mkdir -p .claude/skills
for skill in couchbase-data-modeling couchbase-sizing couchbase-migration-execution couchbase-app-integration couchbase-mcp; do
    tar xzf /path/to/$skill-source.tar.gz -C .claude/skills/
done

# Optionally commit so contributors get them automatically
git add .claude/skills/
git commit -m "Add Couchbase skill suite for Claude Code"
```

## Install Path 3 — Other clients

For clients that follow the Agent Skills open standard, the pattern matches Claude Code: extract the source tarballs into wherever the client looks for skills. Consult your client's docs for the exact path.

## How the five skills compose

These were designed as a suite. They trigger on **different vocabulary** so they don't conflict, and they reference each other by name where appropriate.

A typical greenfield project flows through them in order:

1. *"I'm building a new app on Couchbase. Should I use one bucket or several?"* → **modeling** loads `boundaries.md`
2. *"With 100M docs and 80% writes, how much will this cost on Capella?"* → **sizing** loads `memory.md` and `capella.md`
3. *"In Python, what's the right SDK pattern for async writes with durability?"* → **app-integration** loads `durability-and-consistency.md`
4. *"Now create the buckets and indexes"* → **mcp** loads `cluster-admin.md`
5. *"How do I know if the cluster is healthy?"* → **mcp** loads `observability.md`

A migration project starts differently:

1. *"I have a MongoDB / Postgres / DynamoDB I want to migrate to Couchbase"* → **migration-execution** loads strategy and source-specific references
2. *"How should I model the data once it's in Couchbase?"* → **modeling** for the target schema
3. *"How much capacity will I need?"* → **sizing**
4. *"Write the dual-write code"* → **app-integration**
5. *"Run the cutover and monitor it"* → **mcp** (observability + safety/runbooks)

Each skill knows when it doesn't apply and points to the right sibling.

## Validation tests

After installing, run these in a new chat to confirm each skill triggers correctly.

**Test 1 — `couchbase-data-modeling`:**
> *"I'm migrating a Postgres database to Couchbase. The schema has users, addresses, orders, and order_items. How should I model this?"*

Expected: Claude walks through the read-vs-write pattern question, suggests embedding addresses (1:1), references for orders (1:many unbounded), explicitly mentions `document-shape.md` and `migration-from-relational.md`.

**Test 2 — `couchbase-sizing`:**
> *"I have 50 million user documents, average 2 KB each, with 80% writes. What Capella tier should I pick?"*

Expected: Claude asks for missing inputs (working set %, replica count, growth projection), walks through the memory equation, suggests tier ranges, references `memory.md` and `capella.md`.

**Test 3 — `couchbase-migration-execution`:**
> *"I need to migrate 200 GB of data from MongoDB to Couchbase with zero downtime. What's my approach?"*

Expected: Claude walks through the five-question pre-migration checklist, recommends dual-write or Debezium-based CDC, references `strategies.md` and `from-mongodb.md`, mentions backfill ordering and the soak period.

**Test 4 — `couchbase-app-integration`:**
> *"In Python, what's the best way to bulk-insert 10 million documents into Couchbase?"*

Expected: Claude recommends async SDK with bounded parallelism via semaphore, mentions durability tradeoff (None for max speed), references `performance-patterns.md`. May also mention `cbimport` as an alternative.

**Test 5 — `couchbase-mcp`:**
> *"I want to set up XDCR between two Couchbase clusters. Walk me through it."*

Expected: Claude references the actual tools `admin_xdcr_remote_add` then `admin_xdcr_replication_create`, mentions the two-step setup, asks about admin credentials and network reachability.

**Test 6 — `couchbase-mcp` observability:**
> *"What metrics should I monitor in Couchbase, and what should I alert on?"*

Expected: Claude references the `admin_stats_*` tools, mentions `cache_miss_ratio`, `disk_used_percent`, XDCR `changes_left`, Prometheus integration via `admin_prometheus`, and points to `observability.md`.

If a skill doesn't trigger, see Troubleshooting below.

## Troubleshooting

### Skill uploaded but doesn't trigger

Most common: needs a fresh conversation. Skills loaded after a chat started don't auto-attach to that chat.

If new chats still don't trigger:
1. Settings → Skills (Claude.ai) or `/skills` (Claude Code) — is the skill listed?
2. Is it toggled on?
3. The user's message may not have hit enough trigger keywords. Try a more explicit prompt: *"Using the couchbase-migration-execution skill, help me plan a dual-write..."*

### Two or three skills triggering for the same prompt

Common with cross-cutting prompts. Examples:
- *"design a model and tell me how much RAM it needs"* → modeling + sizing (correct)
- *"migrate from MongoDB and figure out the target schema"* → migration-execution + modeling (correct)
- *"write the bulk-insert code for my migration"* → migration-execution + app-integration (correct)
- *"how do I monitor my Python app's Couchbase usage"* → app-integration + mcp observability (correct)

If you want only one, prefix the prompt explicitly: *"Just the SDK code, no migration discussion."*

### "Invalid SKILL.md" during upload

All five skills validate clean (via skill-creator's quick_validate.py). If you see this:
1. Re-download the file — the upload may be corrupt
2. Check the SKILL.md inside the zip — `name` field must be lowercase letters/digits/hyphens only

### `couchbase-mcp` triggers but Claude says "I don't have those tools"

The MCP server itself isn't connected. The skill teaches Claude *how* to use the tools, but the tools come from a running celticht32/MCP-Couchbase. Check:
- **Claude.ai:** Settings → Connectors → is your celticht32 MCP server listed and connected?
- **Claude Code:** `claude mcp list` should show the server
- **Claude Desktop:** edit `claude_desktop_config.json`

The other four skills don't have this dependency — they're pure knowledge.

### App-integration suggestions don't match my SDK version

Couchbase SDKs have had significant version transitions (e.g., Python SDK 2.x → 3.x → 4.x). If Claude's suggestions use APIs you don't recognize, ask explicitly: *"I'm on Python SDK 3.x — show me that pattern in 3.x."* The references cover patterns; the skill defers to the SDK's current docs for exact syntax.

### Migration skill seems to suggest more work than expected

That's intentional. Real migrations take 8-16 weeks for moderate scale. If Claude is laying out a multi-week timeline and the user wants something faster, push back: a "fast" migration usually means skipping validation or rollback, which is where production incidents come from.

## Upgrading later

**Claude.ai:** Settings → Customize → Skills → find the skill → `...` → **Delete**, then re-upload the new `.zip`.

**Claude Code:**
```bash
rm -rf ~/.claude/skills/<skill-name>
tar xzf <skill-name>-source.tar.gz -C ~/.claude/skills/
```

## Uninstalling

**Claude.ai:** Settings → Customize → Skills → `...` → **Delete** for each skill.

**Claude Code:**
```bash
for skill in couchbase-mcp couchbase-data-modeling couchbase-sizing \
             couchbase-app-integration couchbase-migration-execution; do
    rm -rf ~/.claude/skills/$skill
done
```

## Sizing summary of the skills themselves

For transparency about what gets loaded into Claude's context:

| Skill | SKILL.md (always loaded when triggered) | References (lazy-loaded) | Total content |
|---|---|---|---|
| `couchbase-mcp` | 150 lines | 11 files, ~1765 lines | 1915 lines |
| `couchbase-data-modeling` | 85 lines | 7 files, ~1427 lines | 1512 lines |
| `couchbase-sizing` | 133 lines | 7 files, ~1232 lines | 1365 lines |
| `couchbase-app-integration` | 90 lines | 7 files, ~1418 lines | 1508 lines |
| `couchbase-migration-execution` | 129 lines | 7 files, ~2083 lines | 2212 lines |

Only the SKILL.md is always in context when a skill triggers; references load individually on demand. Even if all five trigger simultaneously, that's only ~587 lines of always-loaded context (vs ~8500 if every reference loaded eagerly). Progressive disclosure as designed.

The migration-execution skill has the longest references because migration is genuinely multi-faceted — strategy + tooling + source-specific patterns + dual-write + CDC + validation all need their own coverage. The four longest references include navigation TOCs to help readers (and Claude) jump to the relevant section.

## Where to get help

- **About the skills themselves (content, additions):** open an issue on https://github.com/celticht32/MCP-Couchbase
- **About installing skills in Claude.ai generally:** https://support.claude.com/en/articles/12512180-use-skills-in-claude
- **About building skills in Claude Code:** https://code.claude.com/docs/en/skills
- **About the celticht32/MCP-Couchbase server itself:** https://github.com/celticht32/MCP-Couchbase
- **Couchbase SDK docs (for app-integration follow-up):** https://docs.couchbase.com → pick your SDK in the sidebar
- **Migration tooling (for migration-execution follow-up):** Debezium docs at https://debezium.io/documentation/, AWS DMS docs, or the Couchbase Kafka Connector docs
