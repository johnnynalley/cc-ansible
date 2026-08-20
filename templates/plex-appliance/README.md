# Plex Appliance Templates

## Templates

- `plex-appliance.env.j2`: Plex appliance environment file.
- `plex-appliance-player.py.j2`: Player controller. Saved checkpoints include
  stable media identity so a Plex rating-key replacement triggers an immediate
  collection refresh and safe active-item rebind instead of an endless `404`
  retry loop.
- `plex-appliance-corrupt-media-report.py.j2`: Corrupt-media report helper.
- `plex-appliance-tailscale-keepalive.sh.j2`: Warms and verifies the Plex
  server Tailscale path used by the appliance.
- `plex-appliance-tailscale-keepalive.service.j2`: One-shot keepalive service.
- `plex-appliance-tailscale-keepalive.timer.j2`: Periodic keepalive timer.
- `plex-appliance-hdmi-watcher.py.j2`: HDMI watcher.
- `plex-appliance-hdmi-vt-watcher.py.j2`: HDMI VT watcher.
- `plex-appliance-hdmi-autostart.sh.j2`: HDMI autostart helper.
- `plex-appliance.service.j2`: Main appliance service.
- `plex-appliance-hdmi.service.j2`: HDMI service.
- `plex-appliance-hdmi-vt-watcher.service.j2`: HDMI VT watcher service.
- `plex-appliance-tv.service.j2`: TV-mode service.
- `plex-appliance-hdmi.desktop.j2`: Desktop autostart entry.

## Consumers

- `playbooks/media/plex-appliance.yml`

## Safety Notes

- These templates affect both Plex appliances. Preserve visible session
  behavior and validate service/user context before applying changes.
- Missing Plex metadata IDs must trigger collection reconciliation. Never mark
  a stale ID watched or corrupt; rebind only on one unique identity/title match,
  otherwise leave current replacements eligible in the refreshed queue.
