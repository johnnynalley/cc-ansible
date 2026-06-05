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

## Media Stack Check

Astra should run this from the current OpenClaw host:

```bash
ssh dbc@100.108.254.100 'sudo -n /usr/local/sbin/media-stack-health --status'
```

Healthy output:

```text
OK: cached media-stack health passed <age>s ago
```

Any nonzero exit or `CRITICAL:` output should alert Discord `#astra`.
If the command exits zero but includes a `WARNINGS:` section, Astra should not
send recurring heartbeat notifications. Those warnings are operator context for
manual review or digest-style summaries, not evidence that the media stack is
down. Current expected warning class: recent qBittorrent imports that were
copied instead of hardlinked because mergerfs placed the download and library
file on different backing branches.

This reads the cached result from the local `media-stack-health.timer` on `docker-vm`, which runs the full checks and alerts through Apprise/DBC. The cached heartbeat read avoids starting fresh NFS/mergerfs-touching probes from Astra. The timer covers the migrated Sonarr/Radarr/download automation on docker-vm while Plex stays on media-vm.

The media-stack check is alert-only. It must not pause Profilarr, stop searches,
or mutate queue/download state. Current storage/import guardrails include
thresholded alerts for repeated docker-vm NFS `fileid changed` kernel errors,
Arr media probe processes such as `ffprobe` stuck in `D` state, and
Sonarr/Radarr commands that are old and have stopped making command-message
progress past the no-progress threshold.

## Plex Appliance Verified Corruption Check

The Plex appliances do not scan media on a schedule. They only write playback
failure records after normal playback fails the same item repeatedly and an
automatic targeted `ffmpeg` decode check confirms the Plex stream could not be
decoded.

Astra should check the verified-corruption report from the current OpenClaw host:

```bash
# jn-t14s-lin / t14s: T14s HDMI Plex appliance on the OpenClaw host.
/usr/local/bin/plex-appliance-corrupt-media-report --since-hours 168

# mercury: living room Raspberry Pi 5 Plex appliance.
ssh dbc@100.81.29.94 '/usr/local/bin/plex-appliance-corrupt-media-report --since-hours 168'
```

Healthy output starts with `OK:`. Plex HTTP/storage-path failures, especially
`input/output error`, are suppressed by default because they can be transient
NAS, mergerfs, VirtioFS, or Plex stream-path failures even when the media file
later decodes cleanly from the backing mount. If the command reports suppressed
storage failures in the `OK:` line, do not page Johnny as corrupt media; rely on
the media mount and media-stack checks for storage-health paging, and inspect
manually with `--show-storage-failures` when needed.

Any output starting with `CRITICAL:` means the appliance found an actionable
file-corruption signature during attempted playback. Alert Johnny in Discord
`#astra` with the title, timestamp/position, reason, and file path so the
release can be replaced and the backing drive can be checked if patterns emerge.

De-duplicate by title, file path, and position in
`memory/plex-corrupt-media-alerts.json`; alert once per finding per 24 hours and
send a recovery/clear note only when the weekly window is clean after a prior
alert.

## Verify

Check the live heartbeat section:

```bash
ansible jn-t14s-lin -m command -a "grep -n 'Stream Relay And VOD Health' /home/johnny/.openclaw/workspace/HEARTBEAT.md"
ansible jn-t14s-lin -m command -a "grep -n 'Media Stack Health' /home/johnny/.openclaw/workspace/HEARTBEAT.md"
```

Check the exact media stack command Astra uses:

```bash
ansible jn-t14s-lin -m shell -a "ssh -o BatchMode=yes -o ConnectTimeout=8 dbc@100.108.254.100 'sudo -n /usr/local/sbin/media-stack-health --status'"
```

Check the exact stream relay command Astra uses:

```bash
ansible jn-t14s-lin -m shell -a "ssh -o BatchMode=yes -o ConnectTimeout=8 dbc@100.66.6.113 '/usr/local/sbin/stream-relay-health --no-alert'"
```

Check the exact Plex appliance corruption commands Astra uses:

```bash
ansible jn-t14s-lin -m command -a "/usr/local/bin/plex-appliance-corrupt-media-report --since-hours 168"
ansible jn-t14s-lin -m shell -a "ssh -o BatchMode=yes -o ConnectTimeout=8 dbc@100.81.29.94 '/usr/local/bin/plex-appliance-corrupt-media-report --since-hours 168'"
```
