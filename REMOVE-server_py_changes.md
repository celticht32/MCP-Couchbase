# Remove server_py_changes.md from the repo

`server_py_changes.md` was patch-application scaffolding for the scope-enforcement
work. It is pinned to transient commit `5f37e5e`, describes "three edits" (the
final wiring was five), and refers to the gate as not-yet-wired. All of it is now
committed and live at `b11b1df`, so the file is stale and misleading.

Remove it:

```powershell
git rm server_py_changes.md
git commit -m "docs: remove stale scope-enforcement patch notes; add project README"
```

The root `README.md` was also the fix-package changelog (first appeared at
`b11b1df`, no prior project README in history). Replace it with the project
README in this archive:

```powershell
copy /Y README.md C:\path\to\MCP-Couchbase\README.md
```

Confirm your repo path before running the copy — adjust `C:\path\to\MCP-Couchbase`.
