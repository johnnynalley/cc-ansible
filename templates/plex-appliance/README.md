# Plex Appliance Templates

## Templates

- `plex-appliance.env.j2`: Plex appliance environment file.
- `plex-appliance-player.py.j2`: Player controller.
- `plex-appliance-corrupt-media-report.py.j2`: Corrupt-media report helper.
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

- These templates affect the living-room Plex appliance. Preserve visible
  session behavior and validate service/user context before applying changes.
