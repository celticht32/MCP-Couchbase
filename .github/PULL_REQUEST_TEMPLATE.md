## Summary

<!-- One or two sentences on what this PR does and why -->

## Changes

<!-- Bulleted list of the actual code changes. Be specific. -->

- 
- 
- 

## Tool inventory impact

<!-- Did this PR add, remove, or rename tools? -->

- Tools added: 
- Tools removed: 
- Tools renamed: 
- Tools changed (schema or behavior): 

## Safety review

- [ ] All new write tools have `ToolAnnotations.destructiveHint=True` AND a `confirm` field in their schema
- [ ] All new tools have unique names with the right prefix (`cb_*` / `admin_*` / `capella_*`)
- [ ] User-supplied URL path segments use `quote_path()` from `handlers/shared.py`
- [ ] User-supplied boolean form fields use `form_data()` / `form_value()` from `handlers/shared.py`
- [ ] Any raw SQL++ statement input is validated (DML blocked when read-only, DDL is locked to its category)
- [ ] No regression — existing tests still pass

## Verification

```
ruff check . && ruff format --check .
pytest tests/ -m unit -v
```

Output:
```

```

## Documentation

- [ ] Tool added to the appropriate table in `README.md`
- [ ] If a new bug class was found and fixed, added to `HANDOFF.md`
- [ ] If a new helper was introduced in `shared.py`, documented in the README's "Helpers" table

## Linked issues

<!-- Closes #N -->
