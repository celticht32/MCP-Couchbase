# Installing the Couchbase Claude skill suite

Three composable skills, designed to work together:

| Skill | What it's for | When it triggers |
|---|---|---|
| **`couchbase-mcp`** | Operating an existing cluster via celticht32/MCP-Couchbase (164 tools) | "list buckets", "create user", "rebalance", "XDCR", "explain this query", any tool-call task |
| **`couchbase-data-modeling`** | Designing what to put in Couchbase, before any tools are called | "how should I model X", "embed or reference", "scope vs collection", "schema design", "migrating from SQL/Mongo" |
| **`couchbase-sizing`** | Numerical capacity planning | "how much RAM", "how many nodes", "Capella tier", "scale up vs out", "will this fit" |

They cover three different conversation phases — design first (modeling), then capacity planning (sizing), then operation (mcp). Install all three for full coverage; install only the ones you need if your work is narrow.

## What's in this bundle

For each of the three skills, three distribution formats:

| File | Use case | Size |
|---|---|---|
| `*.skill` | Canonical Agent Skills format | 28-39 KB |
| `*.zip` | Identical content, `.zip` extension. **Use this for Claude.ai's web uploader** | 28-39 KB |
| `*-source.tar.gz` | Source layout. **Use this for Claude Code** (extract into `~/.claude/skills/`) or to track in git | 23-32 KB |

Plus this `INSTALL.md`.

## Prerequisites

Before installing:

1. **For the `couchbase-mcp` skill to be useful:** you need celticht32/MCP-Couchbase running and connected to your Claude client. See https://github.com/celticht32/MCP-Couchbase. The modeling and sizing skills don't require the MCP server — they're pure knowledge.
2. **For Claude.ai installs:** Code execution and File creation must be enabled in Settings → Capabilities.

## Install Path 1 — Claude.ai (web/mobile)

Use the `.zip` files.

**For Free, Pro, and Max plans:**

1. Go to https://claude.ai and sign in
2. Click your profile picture (bottom left) → **Settings**
3. **Capabilities** tab → verify Code execution and File creation is enabled
4. Left sidebar → **Customize** → **Skills**
5. Click **+ Upload skill** and select `couchbase-mcp.zip`
6. Repeat for `couchbase-data-modeling.zip` and `couchbase-sizing.zip`
7. Each upload takes a few seconds; Claude displays the skill name/description/license

**For Team plans:** Same per-user flow; an org owner can additionally provision all three org-wide via Settings → Skills.

**For Enterprise plans:** Org owner must first enable Skills in Organization settings → Skills (also requires Code execution and File creation enabled at the org level), then either provision org-wide or let members upload personally.

## Install Path 2 — Claude Code (terminal)

Use the source tarballs.

**User-level install — all 3 skills available in every project:**

```bash
mkdir -p ~/.claude/skills
tar xzf couchbase-mcp-source.tar.gz -C ~/.claude/skills/
tar xzf couchbase-data-modeling-source.tar.gz -C ~/.claude/skills/
tar xzf couchbase-sizing-source.tar.gz -C ~/.claude/skills/
```

Verify:

```bash
ls ~/.claude/skills/
# Expect three directories:
#   couchbase-mcp/  couchbase-data-modeling/  couchbase-sizing/
```

Restart any active Claude Code sessions.

**Project-level install — all 3 skills follow this repo:**

```bash
cd /path/to/your/project
mkdir -p .claude/skills
tar xzf /path/to/couchbase-mcp-source.tar.gz -C .claude/skills/
tar xzf /path/to/couchbase-data-modeling-source.tar.gz -C .claude/skills/
tar xzf /path/to/couchbase-sizing-source.tar.gz -C .claude/skills/

# Optionally commit so contributors get them automatically
git add .claude/skills/
git commit -m "Add Couchbase skill suite for Claude Code"
```

## Install Path 3 — Other clients

For clients that follow the Agent Skills open standard, the pattern matches Claude Code: extract the source tarballs into wherever the client looks for skills. Consult your client's docs for the exact path.

For API-direct embedding, see https://docs.claude.com — the wire format for passing skills varies by API version.

## How the three skills compose

These were designed as a suite. They trigger on **different vocabulary** so they don't conflict, and they explicitly hand off to each other:

- A conversation that starts with *"I'm building a new app on Couchbase"* triggers `couchbase-data-modeling` first (design phase). When the user pivots to *"how much will this cost on Capella"*, `couchbase-sizing` takes over. When they're ready to *"create the buckets and indexes"*, `couchbase-mcp` takes over.
- The skills reference each other by name where appropriate — e.g., `couchbase-sizing`'s SKILL.md explicitly tells Claude when to hand off to either of the others; `couchbase-mcp` references the modeling skill for design rationale.

You can install one, two, or all three. They function independently but compose better than they stand alone.

## Validation tests

After installing, run these in a new chat to confirm each skill triggers correctly.

**Test 1 — `couchbase-mcp`:**
> *"I want to set up XDCR between two Couchbase clusters. Walk me through it."*

Expected: Claude references the actual tools `admin_xdcr_remote_add` then `admin_xdcr_replication_create`, mentions the two-step setup, asks about admin credentials and network reachability.

**Test 2 — `couchbase-data-modeling`:**
> *"I'm migrating a Postgres database to Couchbase. The schema has users, addresses, orders, and order_items. How should I model this?"*

Expected: Claude walks through the read-vs-write pattern question, suggests embedding addresses (1:1 with user), references for orders (1:many unbounded), explicitly mentions the modeling skill's `document-shape.md` and `migration-from-relational.md`.

**Test 3 — `couchbase-sizing`:**
> *"I have 50 million user documents, average 2 KB each, with 80% writes. What Capella tier should I pick?"*

Expected: Claude asks for missing inputs (working set %, replica count, growth projection), walks through the memory equation, suggests tier ranges, references the sizing skill's `memory.md` and `capella.md`.

If a skill doesn't trigger, see Troubleshooting below.

## Troubleshooting

### Skill uploaded but doesn't trigger

Most common: needs a fresh conversation. Skills loaded after a chat started don't auto-attach to that chat.

If new chats still don't trigger:
1. Settings → Skills (Claude.ai) or `/skills` (Claude Code) — is the skill listed?
2. Is it toggled on?
3. The user's message may not have hit enough trigger keywords. Try a more explicit prompt: *"Using the couchbase-data-modeling skill, help me design a schema for..."*

### Two skills triggering for the same prompt

Possible but rare given the deliberate vocabulary separation. If it happens:
- Modeling + sizing on questions like *"design a model and tell me how much RAM it needs"* — correct behavior; both skills apply
- MCP + modeling on questions like *"create a collection for users"* — Claude should default to mcp (the action) but may load modeling for context. Also correct
- If you want only one, prefix the prompt explicitly: *"Just the MCP tool calls, no design discussion"*

### "Invalid SKILL.md" during upload

All three skills validate clean (via skill-creator's quick_validate.py). If you see this:
1. Re-download the file — the upload may be corrupt
2. Check the SKILL.md inside the zip — `name` field must be lowercase letters/digits/hyphens only (they are: `couchbase-mcp`, `couchbase-data-modeling`, `couchbase-sizing`)

### `couchbase-mcp` triggers but Claude says "I don't have those tools"

The MCP server itself isn't connected. The skill teaches Claude *how* to use the tools, but the tools come from a running celticht32/MCP-Couchbase. Check:
- **Claude.ai:** Settings → Connectors → is your celticht32 MCP server listed and connected?
- **Claude Code:** `claude mcp list` should show the server
- **Claude Desktop:** edit `claude_desktop_config.json`

The modeling and sizing skills don't have this dependency — they're pure knowledge and work without any MCP server.

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
rm -rf ~/.claude/skills/couchbase-mcp
rm -rf ~/.claude/skills/couchbase-data-modeling
rm -rf ~/.claude/skills/couchbase-sizing
```

## Sizing summary of the skills themselves

For transparency about what gets loaded into Claude's context:

| Skill | SKILL.md (always loaded when triggered) | References (lazy-loaded) | Total content |
|---|---|---|---|
| `couchbase-mcp` | 149 lines | 10 files, ~1572 lines | 1721 lines |
| `couchbase-data-modeling` | 85 lines | 7 files, ~1427 lines | 1512 lines |
| `couchbase-sizing` | 133 lines | 7 files, ~1232 lines | 1365 lines |

Only the SKILL.md is always in context when a skill triggers; references load individually on demand. Even if all three trigger simultaneously, that's only ~367 lines always-loaded (vs ~4600 if everything loaded).

## Where to get help

- **About the skills themselves (content, additions):** open an issue on https://github.com/celticht32/MCP-Couchbase
- **About installing skills in Claude.ai generally:** https://support.claude.com/en/articles/12512180-use-skills-in-claude
- **About building skills in Claude Code:** https://code.claude.com/docs/en/skills
- **About the celticht32/MCP-Couchbase server itself:** https://github.com/celticht32/MCP-Couchbase
