# Hermes Templates

## Templates

- `hermes-managed-config.yaml.j2`: per-profile root-owned managed scope. It
  pins manual approvals, deny-on-cron, review-gated memory/skills, quiet output,
  suppressed background-learning chat notices, role-specific toolsets, and an
  air-gapped rootless Podman backend. Delegation is flat, capped at two
  concurrent children and 12 iterations, with child orchestration disabled.
  Discord fails closed with no shadow allowlists, silent unknown DMs, no bot
  input, no history or missed-message backfill, per-user sessions, explicit
  thread mentions, bounded attachments, and no slash registration. It carries
  the reviewed Hermes config schema version.
- `hermes-gateway.service.j2`: one hardened system service per OS identity. It
  fixes `HERMES_HOME`, root-writable profile-scoped managed credentials, and
  Podman paths; requires a root-owned shadow-ready marker; runs the shadow,
  Discord, and automation/Health contract audits before startup; rejects any
  managed config or environment checksum drift before Hermes's fail-open
  managed-scope parser can run; and exposes no dashboard or API listener.

## Consumer

- `playbooks/agents/hermes-shadow.yml`

## Safety Notes

- These templates contain no provider credentials, bot tokens, user/channel
  IDs, memories, sessions, or transcript data.
- Managed scope is not a sandbox. The OS identity, systemd boundary, and
  rootless Podman backend remain required.
- The shadow services are boot-disabled and cannot start until an attended
  playbook run creates the per-profile root-owned readiness marker.
