# OpenClaw Templates

## Templates

- `openclaw-update-check.sh.j2`: OpenClaw npm update checker.
- `openclaw-safe-update.sh.j2`: guarded OpenClaw updater that checks the
  target package Node engine against the gateway service runtime before
  allowing a live package swap.

## Consumers

- `playbooks/agents/openclaw.yml`

## Safety Notes

- Keep OpenClaw runtime paths aligned with workspace guidance and heartbeat
  references when changing generated service support files.
- `jn-t14s-lin` enables `openclaw_wait_for_tailnet`, which deploys an
  update-safe user-systemd drop-in. It waits for Tailscale to enter `Running`
  before a `gateway.bind=tailnet` gateway starts, preventing a boot-time
  loopback fallback that would make the remote Caddy route return HTTP 502.
