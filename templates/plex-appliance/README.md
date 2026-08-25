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
- `plex-appliance-hdmi-vt-watcher.py.j2`: Root HDMI controller. In hybrid mode
  it selects the logged-in graphical player or the no-login direct-DRM VT path
  and includes a focused `--self-test` for session classification.
- `plex-appliance-hdmi-autostart.sh.j2`: HDMI autostart helper.
- `plex-appliance.service.j2`: Main appliance service.
- `plex-appliance-hdmi.service.j2`: KScreen watcher service on legacy backends,
  or the graphical-session appliance player in hybrid mode.
- `plex-appliance-hdmi-vt-watcher.service.j2`: HDMI VT watcher service.
- `plex-appliance-tv.service.j2`: TV-mode service.
- `plex-appliance-hdmi.desktop.j2`: Desktop autostart entry.

## Consumers

- `playbooks/media/plex-appliance.yml`

## Safety Notes

- These templates affect both Plex appliances. Preserve visible session
  behavior and validate service/user context before applying changes.
- Hybrid mode must keep the graphical player and direct-DRM player mutually
  exclusive. Do not stop SDDM or claim DRM ownership while a user seat is
  active, and do not require KScreen inspection for the configured HDMI path.
- Missing Plex metadata IDs must trigger collection reconciliation. Never mark
  a stale ID watched or corrupt; rebind only on one unique identity/title match,
  otherwise leave current replacements eligible in the refreshed queue.
