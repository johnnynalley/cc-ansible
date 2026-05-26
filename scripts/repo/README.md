# Repo Scripts

Repository-level checks live here. These scripts inspect layout, docs, and
cross-reference health rather than a single infrastructure service.

## Scripts

- `repo-audit`: Static repository organization audit. It checks for flat
  template/script drift, stale playbook/template/script references, and missing
  source-of-truth doc pointers.

## Validation

```bash
scripts/repo/repo-audit
```
