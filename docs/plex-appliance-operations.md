# Plex Appliance Operations

Last updated: 2026-05-27

Use this doc for quick operator actions on the managed Plex TV appliances.

## Host Map

- Bedroom Plex: `jn-t14s-lin` / T14s HDMI appliance.
- Living room Plex: `mercury` / Raspberry Pi 5 appliance.

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
