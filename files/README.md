# Static File Inventory

This directory contains static files copied or referenced by Ansible without
Jinja rendering. Use `templates/` when a file needs variable substitution.

## Files

| File | Owner area | Consumers | Notes |
| --- | --- | --- | --- |
| `qbit-release-stamper.py` | Media release stamping | Legacy/static source for qBittorrent post-download stamping | Prefer repo-managed script/template paths for new work. |
| `sab-release-stamper.py` | Media release stamping | Legacy/static source for SABnzbd post-download stamping | Prefer repo-managed script/template paths for new work. |
| `sonarr-transaction-monitor.py` | Media release monitoring | Legacy/static source for Sonarr transaction monitoring | Calls the repo-managed subtitle mismatch audit for new Sonarr imports when enabled. Prefer `scripts/media-release/` for new diagnostics. |
| `tailscale-policy.hujson` | Tailnet policy | `tasks/tailscale-policy.yml`, `playbooks/core/packages.yml` | Static policy source applied only when explicitly enabled. |

## Root Directory Notes

- `backup/`: legacy tracked backup material. Do not add new active source files
  here without also documenting the owner and migration path.
- `.agents/`, `.claude/`, `.codex/`: local/legacy agent directories are not
  tracked repo assets. Do not treat them as source of truth unless a future
  change explicitly adds tracked files and documentation.

## Operating Rules

- Do not add rendered configs here when a Jinja template is appropriate.
- If this directory grows, split files into domain folders such as
  `files/media/`, `files/proxmox/`, or `files/windows/` and update this catalog.
- Update playbooks, docs, and `scripts/repo/repo-audit` expectations when
  moving or retiring a static file.
