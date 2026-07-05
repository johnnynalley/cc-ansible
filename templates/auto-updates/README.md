# Auto-Updates Templates

## Templates

- `50unattended-upgrades.j2`: Debian/Ubuntu security-only unattended-upgrades
  configuration.
- `auto-updates-arch.sh.j2`: Arch auto-update runner with notifications.
- `auto-updates-debian.sh.j2`: Debian/Ubuntu auto-update runner with
  notifications, reboot-required checks, and an optional Proxmox quorum guard.
- `unattended-upgrades-notify.sh.j2`: Post-upgrade notification helper.

## Consumers

- `playbooks/core/auto-updates.yml`
- `playbooks/core/unattended-upgrades.yml`

## Safety Notes

- These templates affect unattended package changes and reboot notifications.
- Proxmox automatic reboots must keep the quorum guard enabled and use
  non-overlapping per-host maintenance slots.
- Validate with full playbook check mode before changing schedule, reboot, or
  package-cleanup behavior.
