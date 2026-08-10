# OpenClaw Templates

## Templates

- `openclaw-update-check.sh.j2`: OpenClaw npm update checker.
- `openclaw-safe-update.sh.j2`: guarded OpenClaw updater that checks the
  target package Node engine against the gateway service runtime before
  allowing a live package swap.
- `openclaw-isolated.json.j2`: minimal canary config with file-backed secrets,
  one model, no channels, no heartbeats, no delegation, and a minimal tool
  profile.
- `openclaw-isolated-gateway.service.j2`: system service for the parallel
  `openclaw` identity with host-home, controller, Docker, and write boundaries.

## Consumers

- `playbooks/agents/openclaw.yml`
- `playbooks/agents/openclaw-isolated-gateway.yml`

## Safety Notes

- Keep OpenClaw runtime paths aligned with workspace guidance and heartbeat
  references when changing generated service support files.
- `jn-t14s-lin` enables `openclaw_wait_for_tailnet`, which deploys an
  update-safe user-systemd drop-in. It waits for Tailscale to enter `Running`
  before a `gateway.bind=tailnet` gateway starts, preventing a boot-time
  loopback fallback that would make the remote Caddy route return HTTP 502.
