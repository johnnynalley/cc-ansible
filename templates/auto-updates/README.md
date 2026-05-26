# Auto-Updates Templates

## Templates

- `50unattended-upgrades.j2`: Debian/Ubuntu security-only unattended-upgrades
  configuration.
- `auto-updates-arch.sh.j2`: Arch auto-update runner with notifications.
- `auto-updates-debian.sh.j2`: Debian/Ubuntu auto-update runner with
  notifications and reboot-required checks.
- `unattended-upgrades-notify.sh.j2`: Post-upgrade notification helper.

## Consumers

- `playbooks/auto-updates.yml`
- `playbooks/unattended-upgrades.yml`

## Safety Notes

- These templates affect unattended package changes and reboot notifications.
- Validate with full playbook check mode before changing schedule, reboot, or
  package-cleanup behavior.
