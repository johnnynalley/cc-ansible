# agents Playbooks

Owner area: Codex, Claude archive sync, and OpenClaw services.

## Operating Notes

- Key vars: codex_*, claude_memory_sync_*, openclaw_*.
- Template owners: templates/openclaw.
- Script owners: templates/openclaw managed helper scripts.
- Isolated non-model services use repo-managed sources under `scripts/agents/`.
- Keep playbook metadata headers and `playbooks/README.md` in sync when behavior changes.
- OpenClaw intentionally tracks the npm `latest` channel. Do not add an exact package-version variable: native OpenClaw updates must survive later Ansible convergence instead of being downgraded.
- The isolated Gateway resolves the stable core plus the reviewed Codex,
  Discord, Lossless Claw, and Mem0 plugins under a credential-less ephemeral
  build account with lifecycle scripts disabled. It validates and atomically
  promotes one root-owned versioned release. Resolved versions are rollback
  records, not update-policy pins.

## Playbooks

| Playbook | Hosts | Purpose | Validation |
| --- | --- | --- | --- |
| `claude-memory-sync.yml` | `nas_server, orchestrator` | Configure Claude memory sync to NAS. | `ansible-playbook playbooks/agents/claude-memory-sync.yml --syntax-check` |
| `codex-cli.yml` | `orchestrator` | Configure Codex CLI. | `ansible-playbook playbooks/agents/codex-cli.yml --syntax-check` |
| `codex-memory-sync.yml` | `nas_server, orchestrator` | Configure Codex memory sync to NAS. | `ansible-playbook playbooks/agents/codex-memory-sync.yml --syntax-check` |
| `openclaw.yml` | `openclaw_hosts` | Deploy OpenClaw AI agent. | `ansible-playbook playbooks/agents/openclaw.yml --syntax-check` |
| `openclaw-health-receiver.yml` | `openclaw_hosts` | Stage or cut over the isolated Health receiver and aggregate-only publisher; disabled by default. | `ansible-playbook playbooks/agents/openclaw-health-receiver.yml --syntax-check` |
| `openclaw-isolated-gateway.yml` | `openclaw_hosts` | Stage a modernized two-phase Gateway canary with an immutable versioned core/plugin release, fresh OAuth enrollment, and a required model proof; disabled by default. | `ansible-playbook playbooks/agents/openclaw-isolated-gateway.yml --syntax-check` |
| `openclaw-state-rehearsal.yml` | `openclaw_hosts` | Rehearse deterministic relocation of active file-backed session stores and only their exact workspace dependencies; disabled by default. | `ansible-playbook playbooks/agents/openclaw-state-rehearsal.yml --syntax-check` |
