# agents Playbooks

Owner area: Codex, Claude archive sync, OpenClaw, and Hermes services.

## Operating Notes

- Key vars: codex_*, claude_memory_sync_*, openclaw_*, hermes_shadow_*,
  hermes_profile_memory_*, hermes_profile_skills_*.
- Template owners: templates/openclaw and templates/hermes.
- Script owners: templates/openclaw managed helper scripts.
- Isolated non-model services use repo-managed sources under `scripts/agents/`.
- The modern production behavior bundle is rooted at
  `files/openclaw/workspace/`; it is reconstructed and audited source, not a
  legacy workspace clone. Mutable memories and project data remain separate.
- Keep playbook metadata headers and `playbooks/README.md` in sync when behavior changes.
- OpenClaw intentionally tracks the npm `latest` channel. Do not add an exact package-version variable: native OpenClaw updates must survive later Ansible convergence instead of being downgraded.
- The isolated runtime resolves the stable core plus the reviewed Codex,
  Discord, Lossless Claw, and Mem0 plugins under a credential-less ephemeral
  build account with lifecycle scripts disabled. It validates and atomically
  promotes one root-owned versioned release, then separates the `openclaw`
  Gateway from the `openclaw-codex` model executor. Resolved versions are
  rollback records, not update-policy pins.

## Playbooks

| Playbook | Hosts | Purpose | Validation |
| --- | --- | --- | --- |
| `claude-memory-sync.yml` | `nas_server, orchestrator` | Configure Claude memory sync to NAS. | `ansible-playbook playbooks/agents/claude-memory-sync.yml --syntax-check` |
| `codex-cli.yml` | `orchestrator` | Configure Codex CLI. | `ansible-playbook playbooks/agents/codex-cli.yml --syntax-check` |
| `codex-memory-sync.yml` | `nas_server, orchestrator` | Configure Codex memory sync to NAS. | `ansible-playbook playbooks/agents/codex-memory-sync.yml --syntax-check` |
| `hermes-shadow.yml` | `hermes_hosts` | Stage the isolated, boot-disabled Hermes runtime with three OS identities, root-owned identity/operating/Discord/automation contracts, service-identity native config validation, Astra's validated hook-only Star privacy boundary, approval-gated learning, root-writable profile-scoped managed environments, and no production delivery or schedules; disabled by default. | `ansible-playbook playbooks/agents/hermes-shadow.yml --syntax-check` |
| `hermes-openclaw-dry-run.yml` | `hermes_hosts` | Run the pinned official importer against an ephemeral shape-only, no-secret, read-only source and target; retain only root-private structural evidence and leave all services unchanged; disabled by default. | `ansible-playbook playbooks/agents/hermes-openclaw-dry-run.yml --syntax-check` |
| `hermes-profile-memory.yml` | `hermes_hosts` | Transactionally stage four vault-encrypted, compact native memory seeds for Astra and Rigel while keeping Dubble empty and every Gateway stopped; disabled by default. | `ansible-playbook playbooks/agents/hermes-profile-memory.yml --syntax-check` |
| `hermes-profile-skills.yml` | `hermes_hosts` | Transactionally stage five reviewed declarative native skills under root-owned per-profile sources, prove exact hashes and Hermes-native discovery through read-only service bindings, and leave every Gateway stopped; disabled by default. | `ansible-playbook playbooks/agents/hermes-profile-skills.yml --syntax-check` |
| `hermes-profile-data.yml` | `hermes_hosts` | Transactionally copy only reviewed project data and operator references into isolated per-profile writable/read-only roots, prove source and manifest stability plus runtime bind modes, and leave every Gateway stopped; disabled by default. | `ansible-playbook playbooks/agents/hermes-profile-data.yml --syntax-check` |
| `hermes-profile-transforms.yml` | `hermes_hosts` | Transactionally normalize six reviewed legacy state sources into isolated canonical per-profile roots, prove source/output stability and runtime bind modes, and leave every Gateway stopped; disabled by default. | `ansible-playbook playbooks/agents/hermes-profile-transforms.yml --syntax-check` |
| `openclaw.yml` | `openclaw_hosts` | Deploy OpenClaw AI agent. | `ansible-playbook playbooks/agents/openclaw.yml --syntax-check` |
| `openclaw-health-receiver.yml` | `openclaw_hosts` | Stage or cut over the isolated Health receiver and aggregate-only publisher; disabled by default. | `ansible-playbook playbooks/agents/openclaw-health-receiver.yml --syntax-check` |
| `openclaw-isolated-gateway.yml` | `openclaw_hosts` | Stage a modernized split Gateway/Codex canary with immutable runtime/plugin code, separate no-login identities and secrets, fresh executor OAuth, and a required model proof; disabled by default. | `ansible-playbook playbooks/agents/openclaw-isolated-gateway.yml --syntax-check` |
| `openclaw-state-rehearsal.yml` | `openclaw_hosts` | Rehearse deterministic relocation of active file-backed session stores, quarantine copied delivery-recovery intent, and retain only the selected plus immediate rollback generations; disabled by default. | `ansible-playbook playbooks/agents/openclaw-state-rehearsal.yml --syntax-check` |
| `openclaw-doctor-rehearsal.yml` | `openclaw_hosts` | Rehearse credential-free supported state migrations and plugin modernization on protected copies with bounded upstream/Doctor generation retention; disabled by default. | `ansible-playbook playbooks/agents/openclaw-doctor-rehearsal.yml --syntax-check` |
| `openclaw-canary-data-rehearsal.yml` | `openclaw_hosts` | Transactionally hand the classified modern workspace and verified file-backed sessions to the loopback-only, channel/cron/heartbeat-suppressed five-agent canary, then plan or apply native session archival with rollback; disabled by default. | `ansible-playbook playbooks/agents/openclaw-canary-data-rehearsal.yml --syntax-check` |
| `openclaw-behavior-rehearsal.yml` | `openclaw_hosts` | Prove Dubble response discipline, native Vega/Antares Star lineage, and idle-silent Rigel heartbeat behavior in the channel-less loopback canary, then archive only the synthetic probe sessions; disabled by default. | `ansible-playbook playbooks/agents/openclaw-behavior-rehearsal.yml --syntax-check` |
| `openclaw-security-rehearsal.yml` | `openclaw_hosts` | Run one channel-less hostile-prompt probe against the split Gateway/executor and prove sudo, Gateway-secret, Docker, and outside-workspace denial from trajectory and filesystem evidence; disabled by default. | `ansible-playbook playbooks/agents/openclaw-security-rehearsal.yml --syntax-check` |
