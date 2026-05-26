# Repo Scripts

Repository-level checks live here. These scripts inspect layout, docs, and
cross-reference health rather than a single infrastructure service.

## Scripts

- `repo-audit`: Static repository organization audit. It checks for flat
  template/script/playbook drift, stale playbook/template/script references,
  missing source-of-truth doc pointers, and plaintext secret exposure. It calls
  `secrets-scan` by default, so this remains the single required audit command.
- `secrets-scan`: Built-in tracked-file secret scanner with optional Gitleaks
  integration. Local runs fall back to the built-in scanner when Gitleaks is not
  installed; CI uses `repo-audit --require-gitleaks` so the Gitleaks layer is
  mandatory there.

## Validation

```bash
# Normal local audit: includes built-in secret scanning and uses Gitleaks when installed.
scripts/repo/repo-audit

# CI/strict mode: fail if Gitleaks is unavailable.
scripts/repo/repo-audit --require-gitleaks

# Focused staged secret scan before committing.
scripts/repo/secrets-scan --staged
```
