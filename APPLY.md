# Repo update — apply guide

This bundle contains everything changed across three pieces of work on the
MCP-Couchbase repo:

1. **Deep-scan code fixes** (OAuth token refresh, JWKS cache, GUI auth flow, callback guards)
2. **Documentation fixes** (GUI README safety note + OAuth docs, main README)
3. **Skill cleanup** (stale tool counts 164→167 / 148→151, removed duplicate skill dirs)

## Two ways to apply

### Option A — git patch (RECOMMENDED)

The patch reproduces everything: file edits, the rebuilt skill artifacts, AND
the **48 file deletions** (the stale `skills/couchbase_mcp/` duplicate and the
nested extraction debris). A plain file copy can NOT reproduce deletions, so
this is the reliable path.

```
cd C:\path\to\MCP-Couchbase
git checkout main
git pull

git apply --whitespace=nowarn all-changes.patch

git add -A
git commit -m "fix: deep-scan bug fixes + OAuth docs + skill count/dup cleanup"
git push origin main
```

If `git apply` reports any conflict (your working tree drifted), run:
```
git apply --3way all-changes.patch
```

### Option B — manual copy + manual deletes

The `changed-files/` folder holds every modified and rebuilt file at its real
repo path. Copy them over your repo, THEN delete the stale directories by hand:

```
# copy changed files (Windows)
xcopy /E /Y changed-files\* C:\path\to\MCP-Couchbase\

# then delete the stale duplicates (these are the 48 deletions)
rmdir /S /Q C:\path\to\MCP-Couchbase\skills\couchbase_mcp
rmdir /S /Q C:\path\to\MCP-Couchbase\skills\couchbase-mcp\couchbase-mcp
```

Then `git add -A`, commit, push.

## What changed (file list)

Modified / rebuilt:
- `README.md`
- `auth/oidc.py`
- `gui/README.md`
- `gui/gui_server.py`
- `gui/static/index.html`
- `skills/INSTALL.md`
- `skills/couchbase-mcp/couchbase-mcp-source/SKILL.md`
- `skills/couchbase-mcp/couchbase-mcp-source/references/tool-index.md`
- `skills/couchbase-mcp/compressed files/couchbase-mcp.zip`
- `skills/couchbase-mcp/compressed files/couchbase-mcp.skill`
- `skills/couchbase-mcp/compressed files/couchbase-mcp-source.tar.gz`

Deleted (48 files):
- `skills/couchbase_mcp/` — entire stale underscore duplicate
- `skills/couchbase-mcp/couchbase-mcp/` — nested extraction debris

Authoritative tool counts after this change: **167 total** (151 cluster + 16 Capella), 16 categories.

The 5 unrelated couchbase skills (app-integration, data-modeling,
migration-execution, sizing, sqlpp-tuning) were NOT touched.
