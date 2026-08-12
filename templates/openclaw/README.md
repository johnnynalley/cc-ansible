# OpenClaw Templates

## Templates

- `openclaw-update-check.sh.j2`: OpenClaw npm update checker.
- `openclaw-safe-update.sh.j2`: guarded OpenClaw updater that checks the
  target package Node engine against the gateway service runtime before
  allowing a live package swap.
- `openclaw-isolated.json.j2`: minimal canary config with file-backed Gateway
  and Codex app-server capability tokens, one OpenAI model, the five production
  agent IDs for complete native session discovery, and an explicit
  root-managed Codex provider connected to the separate authenticated loopback
  executor. It has heartbeat `0m` with target `none`, no
  channels/bindings/cron, and no local filesystem or execution tools. Provider
  prompt hooks, conversation access, computer use, and plugin delegation are
  disabled. Model OAuth is enrolled separately under `openclaw-codex`.
- `openclaw-modern.json.j2`: production target config for the split dedicated
  Gateway/executor identities. It reconstructs the five active agents, Discord
  routing, native structured heartbeats, guarded Star delegation, current
  provider auth metadata, file-backed SecretRefs, workspace-only filesystem
  access, Guardian-reviewed remote Codex execution, pending-only Skill Workshop
  self-evolution, and a loopback-only Gateway. It contains no credentials or
  human-home paths.
  Lossless Claw and Mem0 remain explicit compatibility bridges pending their
  separate native-compaction and native-memory retirement gates. Its
  `behavior-canary` branch removes channels, bindings, cron, memory search, and
  broad tools; the normal baseline disables all heartbeats, while a controlled
  rehearsal variant enables only Rigel at a 24-hour cadence long enough to
  trigger and inspect one isolated native heartbeat. Its `security-canary`
  branch keeps channels, cron, and heartbeats absent while allowing only the
  remote Codex executor's workspace-confined hostile probe.
- `openclaw-isolated-gateway.service.j2`: system service for the parallel
  `openclaw` Gateway identity. Runtime, provider code, config, and workspace are
  read-only; Codex state/config, host-home, controller, Docker, Ansible, and bulk
  data are inaccessible. Only Gateway data and the exact `.last-good` config
  backup are writable.
- `openclaw-isolated-codex.service.j2`: authenticated loopback Codex app-server
  service under the separate `openclaw-codex` identity. It owns only Codex
  auth/state and mutable workspace data, consumes the reviewed Codex package
  through a read-only bind, and cannot read Gateway config/state/secrets,
  Docker, human-home, controller, Ansible, or bulk-data paths.

## Consumers

- `playbooks/agents/openclaw.yml`
- `playbooks/agents/openclaw-isolated-gateway.yml`
- `playbooks/agents/openclaw-behavior-rehearsal.yml`
- `playbooks/agents/openclaw-security-rehearsal.yml`
- Future attended production cutover playbook (the modern template is not
  consumed by normal convergence until that gate exists).

## Safety Notes

- Keep OpenClaw runtime paths aligned with workspace guidance and heartbeat
  references when changing generated service support files.
- `jn-t14s-lin` enables `openclaw_wait_for_tailnet`, which deploys an
  update-safe user-systemd drop-in. It waits for Tailscale to enter `Running`
  before a `gateway.bind=tailnet` gateway starts, preventing a boot-time
  loopback fallback that would make the remote Caddy route return HTTP 502.
