# OpenClaw Heartbeats

OpenClaw's Astra heartbeat is file-driven. The active prompt is:

```text
/home/johnny/.openclaw/workspace/HEARTBEAT.md
```

on the current OpenClaw host (`jn-t14s-lin` / T14s as of 2026-05-24).

Do not model this as an OpenClaw cron unless exact timing or isolated delivery is the requirement. Batched recurring health checks belong in `HEARTBEAT.md`.

## Management Model

`HEARTBEAT.md` is live OpenClaw workspace content, not an Ansible template. Astra may edit it during normal operation, so do not use Ansible markers or managed blocks for heartbeat checklist entries.

When adding a heartbeat check:

1. Edit `/home/johnny/.openclaw/workspace/HEARTBEAT.md` on the OpenClaw host.
2. Verify the exact command in that file works from the OpenClaw host.
3. Document the operational expectation in this repo.

## Stream Relay Check

Astra should run this from the current OpenClaw host:

```bash
ssh dbc@100.66.6.113 '/usr/local/sbin/stream-relay-health --no-alert'
```

Healthy output:

```text
OK: stream relay health checks passed
```

Any nonzero exit or `CRITICAL:` output should alert Discord `#astra`.

This is separate from the local `stream-relay-health.timer` on `media-vm`, which also runs the same checks and alerts through Apprise/DBC.

Current VOD recording covers the landscape relay only. Vertical/mobile recording is not included until a separate recording path is explicitly added.

## Verify

Check the live heartbeat section:

```bash
ansible jn-t14s-lin -m command -a "grep -n 'Stream Relay And VOD Health' /home/johnny/.openclaw/workspace/HEARTBEAT.md"
```

Check the exact command Astra uses:

```bash
ansible jn-t14s-lin -m shell -a "ssh -o BatchMode=yes -o ConnectTimeout=8 dbc@100.66.6.113 '/usr/local/sbin/stream-relay-health --no-alert'"
```
