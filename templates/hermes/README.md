# Hermes Templates

## Templates

- `hermes-managed-config.yaml.j2`: per-profile root-owned managed scope. It
  pins manual approvals, deny-on-cron, review-gated memory/skills, quiet output,
  role-specific toolsets, and an air-gapped rootless Podman backend.
- `hermes-gateway.service.j2`: one hardened system service per OS identity. It
  fixes `HERMES_HOME`, managed scope, and Podman paths; requires a shadow-ready
  marker; and runs no dashboard or API listener.

## Consumer

- `playbooks/agents/hermes-shadow.yml`

## Safety Notes

- These templates contain no provider credentials, bot tokens, user/channel
  IDs, memories, sessions, or transcript data.
- Managed scope is not a sandbox. The OS identity, systemd boundary, and
  rootless Podman backend remain required.
- The shadow services are boot-disabled and cannot start until an attended
  playbook run creates the per-profile readiness marker.
