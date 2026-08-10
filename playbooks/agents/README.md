# agents Playbooks

Owner area: Codex, Claude archive sync, and OpenClaw services.

## Operating Notes

- Key vars: codex_*, claude_memory_sync_*, openclaw_*.
- Template owners: templates/openclaw.
- Script owners: templates/openclaw managed helper scripts.
- Isolated non-model services use repo-managed sources under `scripts/agents/`.
- Keep playbook metadata headers and `playbooks/README.md` in sync when behavior changes.
- OpenClaw intentionally tracks the npm `latest` channel. Do not add an exact package-version variable: native OpenClaw updates must survive later Ansible convergence instead of being downgraded.

## Playbooks

| Playbook | Hosts | Purpose | Validation |
| --- | --- | --- | --- |
| `claude-memory-sync.yml` | `nas_server, orchestrator` | Configure Claude memory sync to NAS. | `ansible-playbook playbooks/agents/claude-memory-sync.yml --syntax-check` |
| `codex-cli.yml` | `orchestrator` | Configure Codex CLI. | `ansible-playbook playbooks/agents/codex-cli.yml --syntax-check` |
| `codex-memory-sync.yml` | `nas_server, orchestrator` | Configure Codex memory sync to NAS. | `ansible-playbook playbooks/agents/codex-memory-sync.yml --syntax-check` |
| `openclaw.yml` | `openclaw_hosts` | Deploy OpenClaw AI agent. | `ansible-playbook playbooks/agents/openclaw.yml --syntax-check` |
| `openclaw-health-receiver.yml` | `openclaw_hosts` | Stage or cut over the isolated Health receiver and aggregate-only publisher; disabled by default. | `ansible-playbook playbooks/agents/openclaw-health-receiver.yml --syntax-check` |
| `openclaw-isolated-gateway.yml` | `openclaw_hosts` | Stage a parallel deny-by-default Gateway canary under the `openclaw` account; disabled by default. | `ansible-playbook playbooks/agents/openclaw-isolated-gateway.yml --syntax-check` |
