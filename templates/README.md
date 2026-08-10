# Template Inventory

This directory contains Ansible-managed source templates for rendered configs,
service units, scripts, Docker Compose files, and host-side helper files.

## Operating Rules

- Do not add new reusable templates directly under `templates/` as flat files.
- Put templates in a domain directory and document them in that directory's
  `README.md`.
- When moving, renaming, deleting, or replacing a template, update playbooks,
  tasks, inventory variables, operator docs, and `README.md` references in the
  same change.
- Keep rendered live paths unchanged unless the change is explicitly a runtime
  migration with cleanup and rollback notes.

## Directories

- `auto-updates/`: System auto-update and unattended-upgrades templates.
- `docker/`: Docker Compose, Caddy, Diun, and Docker maintenance templates.
- `freepbx/`: FreePBX support templates.
- `gluetun/`: Gluetun and qBittorrent port-sync templates.
- `logging/`: Alloy/Loki centralized logging templates.
- `media-inbox/`: Headless Immich semantic-vision service, Astra wrapper, and cloud-worker unit templates.
- `media-maintenance/`: Nightly media maintenance units and clients.
- `motd/`: Custom Linux MOTD templates.
- `network/`: Network recovery watchdog templates.
- `openclaw/`: OpenClaw service support templates.
- `plex-appliance/`: Plex appliance services, scripts, and env templates.
- `proxmox/`: Proxmox firewall, VirtioFS, PBS, and hookscript templates.
- `samba/`: Samba and Time Machine advertisement templates.
- `smartmontools/`: SMART monitoring templates.
- `storage/`: NFS, ZFS, Sanoid, and MergerFS templates.
- `streaming/`: Stream relay, MediaMTX, and VOD mover templates.
- `ups/`: APC UPS daemon and notification templates.
- `windows/`: Windows gaming, performance, and SignalRGB templates.

Start with the relevant directory README before adding or changing a template.
