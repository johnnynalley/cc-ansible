# MOTD Templates

## Templates

- `motd-header.sh.j2`: Login banner header.
- `motd-sysinfo.sh.j2`: System information MOTD section.
- `motd-updates.sh.j2`: Available updates MOTD section.
- `motd-reboot-required.sh.j2`: Reboot-required MOTD section.

## Consumers

- `playbooks/core/ssh-hardening.yml`

## Safety Notes

- These scripts run during interactive login. Keep them fast, bounded, and
  tolerant of unavailable package manager state.
