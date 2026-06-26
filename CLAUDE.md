# CLAUDE.md

> **STATUS:** Frozen. Codex is the primary agent on this repo; Claude Code is a
> secondary, on-demand assistant. This file is intentionally NOT a source of
> truth and is no longer maintained. Its prior contents were stale and caused
> real errors (acting on old host/service locations). Do not reintroduce them.

## Operating rule for Claude Code

Do **not** rely on this file, on prior Claude memory snapshots, or on README.md
for current infrastructure state. They are frozen and likely stale.

Before acting on any claim about the infrastructure, verify against the sources
of truth below — and confirm with **live host state** first.

## Sources of truth (priority order)

1. **Live host state** — always verify before acting:
   `ansible <host> -m shell -a "<cmd>" --become`
2. **`AGENTS.md`** (repo root) — primary repo/workflow rules, architecture, runbooks.
3. **`inventory/`** — host_vars, group_vars, hosts.ini for declared config
   (cross-reference with live state; declared config can also drift).
4. **`~/.codex/MEMORY.md`**, **`~/.codex/memory_summary.md`**,
   **`~/.codex/raw_memories.md`** — Codex's persistent state.
5. **`~/.codex/skills/`** — operational skills.
6. **`~/.codex/rollout_summaries/`** — past session context.
7. **`.codex/work-plans/active/`** (gitignored) — in-flight plans.
8. **`docs/`** — subsystem runbooks.

## What NOT to do

- Do not trust historical specifics (which host runs which service, ports,
  paths, IPs) from this file or from old Claude memory. Container/service
  locations have already moved at least once.
- Do not run ad-hoc changes that bypass Ansible — Infrastructure as Code first.
  See `AGENTS.md` for the IaC policy and workflow.
