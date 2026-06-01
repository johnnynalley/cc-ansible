# Plex Appliance Operations

Last updated: 2026-06-01

Use this doc for quick operator actions on the managed Plex TV appliances.

## Host Map

- Bedroom Plex: `jn-t14s-lin` / T14s HDMI appliance.
- Living room Plex: `mercury` / Raspberry Pi 5 appliance.

## Plex Server Storage

Plex runs on `media-vm` in the `/opt/media-stack` Docker Compose project. The
Plex config, metadata, thumbnails, intro/credits analysis, and cache live under
`/opt/media-stack/plex`, which is mounted from the dedicated `plex-data` ext4
disk (`LABEL=plex-data`) backed by TS440 ZFS storage `nas-zfs-vm`.

The media libraries are not stored there. Plex reads library media through
`/srv/plex` and `/srv/archive`, which are TS440 VirtioFS paths. Temporary
transcode scratch stays on the VM root disk at `/var/lib/plex-transcode` and is
mounted into the Plex container as `/transcode`.

## Bedroom HDMI Display Ownership

The T14s HDMI appliance uses mpv with direct DRM on VT8. When no real local
seat session is active, the HDMI watcher stops `sddm.service` before starting
playback and starts it again when HDMI appliance mode exits.

This prevents the SDDM Wayland greeter/KWin on VT1 from contending with mpv for
the same AMD DRM device. The failure signature that led to this rule was:

- TV shows the login screen or black video while HDMI audio continues.
- `sddm.service` repeatedly logs `Using VT 1`, `Jumping to VT 1`, or greeter
  restart messages.
- Kernel logs show AMDGPU/DMCUB DRM errors near the same timestamp.
- mpv logs show video configuration or AMDGPU initialization failures.

Do not treat a player restart or VT switch as the fix for this class of
incident. Preserve the logs and prove which process owned the display stack
before changing recovery behavior.

## Skip Current Bedroom Plex Episode

Run this on `jn-t14s-lin` from any shell. It stops the HDMI watcher and player,
backs up the shuffle state, marks the active item as played, and lets the
watcher start the next item.

```bash
set -euo pipefail

sudo -n systemctl stop plex-appliance-hdmi-vt-watcher.service plex-appliance-tv.service
trap 'sudo -n systemctl start plex-appliance-hdmi-vt-watcher.service' EXIT

ts="$(date +%Y%m%d-%H%M%S)"
state="/var/lib/plex-appliance/shuffle-state.json"
backup="/tmp/plex-appliance-shuffle-state.${ts}.json"
cp "$state" "$backup"

python3 - <<'PY'
import json
import pathlib
import time

path = pathlib.Path("/var/lib/plex-appliance/shuffle-state.json")
data = json.loads(path.read_text())
active = data.get("active") or {}
key = active.get("key")
title = active.get("title") or key
if not key:
    raise SystemExit("No active Plex appliance item to skip.")

played = data.setdefault("played", [])
if key not in played:
    played.append(key)
data["active"] = None
data["updated_at"] = int(time.time())
path.write_text(json.dumps(data, separators=(",", ":")) + "\n")
print(f"Skipped {title} ({key})")
PY

printf 'State backup: %s\n' "$backup"
```

Verify the player advanced:

```bash
systemctl status plex-appliance-tv.service --no-pager
python3 -c "import json; d=json.load(open('/var/lib/plex-appliance/shuffle-state.json')); print(d.get('active'))"
```

Rollback if the wrong item was skipped:

```bash
sudo -n systemctl stop plex-appliance-hdmi-vt-watcher.service plex-appliance-tv.service
cp /tmp/plex-appliance-shuffle-state.YYYYMMDD-HHMMSS.json /var/lib/plex-appliance/shuffle-state.json
sudo -n systemctl start plex-appliance-hdmi-vt-watcher.service
```

## Related Commands

Corruption alerts and heartbeat checks are documented in
`docs/openclaw-heartbeats.md`.
