# Repo Scripts

Repository-level checks live here. These scripts inspect layout, docs, and
cross-reference health rather than a single infrastructure service.

## Scripts

- `repo-audit`: Static repository organization audit. It checks for flat
  template/script/playbook drift, stale playbook/template/script references,
  skill-relative supporting-file references, missing source-of-truth doc
  pointers, divergent per-host agent npm prefixes, exhaustive Hermes Ansible
  path ownership, and plaintext secret exposure. It calls both
  `hermes-ansible-ownership-audit.py` and `secrets-scan` by default, so this
  remains the single required audit command.
- `test_repo_audit.py`: Focused regression coverage for repository and
  skill-relative reference resolution.
- `secrets-scan`: Built-in tracked-file secret scanner with optional Gitleaks
  integration. Local runs fall back to the built-in scanner when Gitleaks is not
  installed; CI uses `repo-audit --require-gitleaks` so the Gitleaks layer is
  mandatory there. It detects literal credentials in HTTP authorization/API-key
  headers in addition to assignments and known provider formats. Use `--root`
  to scan another Git worktree with the same rules. Run `secrets-scan
  --self-test` after changing scanner heuristics.

## Validation

```bash
# Normal local audit: includes built-in secret scanning and uses Gitleaks when installed.
scripts/repo/repo-audit

# CI/strict mode: fail if Gitleaks is unavailable.
scripts/repo/repo-audit --require-gitleaks

# Focused staged secret scan before committing.
scripts/repo/secrets-scan --staged

# Scan Astra's tracked workspace without printing unredacted values.
scripts/repo/secrets-scan --root ~/.openclaw/workspace --external off

# Scanner heuristic regression checks.
scripts/repo/secrets-scan --self-test

# Repository-audit reference regressions.
python3 scripts/repo/test_repo_audit.py
```
