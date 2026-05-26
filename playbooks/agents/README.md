# agents Playbooks

Owner area: Codex, Claude archive sync, and OpenClaw services.

## Operating Notes

- Key vars: codex_*, claude_memory_sync_*, openclaw_*.
- Template owners: templates/openclaw.
- Script owners: none by default.
- Keep playbook metadata headers and `playbooks/README.md` in sync when behavior changes.

## Playbooks

| Playbook | Hosts | Purpose | Validation |
| --- | --- | --- | --- |
| `claude-memory-sync.yml` | `nas_server, orchestrator` | Configure Claude memory sync to NAS. | `ansible-playbook playbooks/agents/claude-memory-sync.yml --syntax-check` |
| `codex-cli.yml` | `orchestrator` | Configure Codex CLI. | `ansible-playbook playbooks/agents/codex-cli.yml --syntax-check` |
| `codex-memory-sync.yml` | `nas_server, orchestrator` | Configure Codex memory sync to NAS. | `ansible-playbook playbooks/agents/codex-memory-sync.yml --syntax-check` |
| `openclaw.yml` | `openclaw_hosts` | Deploy OpenClaw AI agent. | `ansible-playbook playbooks/agents/openclaw.yml --syntax-check` |
