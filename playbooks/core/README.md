# core Playbooks

Owner area: Base OS and controller hygiene.

## Operating Notes

- Key vars: packages_*, bootstrap_*, auto_updates_*, unattended_upgrades_*, swap_*, sysctl_*, logging_*, smartd_*, apcupsd_*.
- Template owners: templates/auto-updates, templates/logging, templates/motd, templates/smartmontools, templates/ups.
- Script owners: scripts/repo/repo-audit for repo checks; otherwise none by default.
- Keep playbook metadata headers and `playbooks/README.md` in sync when behavior changes.

## Playbooks

| Playbook | Hosts | Purpose | Validation |
| --- | --- | --- | --- |
| `apcupsd.yml` | `proxmox_nodes` | Configure apcupsd UPS monitoring. | `ansible-playbook playbooks/core/apcupsd.yml --syntax-check` |
| `auto-updates.yml` | `linux_hosts` | Configure automatic updates. | `ansible-playbook playbooks/core/auto-updates.yml --syntax-check` |
| `bootstrap.yml` | `bootstrap_hosts` | Bootstrap new managed hosts. | `ansible-playbook playbooks/core/bootstrap.yml --syntax-check` |
| `logging.yml` | `linux_hosts, macos_hosts` | Configure centralized logging (Loki + Alloy). | `ansible-playbook playbooks/core/logging.yml --syntax-check` |
| `packages.yml` | `localhost, linux_hosts, macos_hosts` | Install baseline packages. | `ansible-playbook playbooks/core/packages.yml --syntax-check` |
| `power-management.yml` | `linux_hosts` | Configure power management. | `ansible-playbook playbooks/core/power-management.yml --syntax-check` |
| `smartmontools.yml` | `linux_hosts` | Configure SMART disk monitoring. | `ansible-playbook playbooks/core/smartmontools.yml --syntax-check` |
| `ssh-hardening.yml` | `linux_hosts` | Configure SSH hardening. | `ansible-playbook playbooks/core/ssh-hardening.yml --syntax-check` |
| `swap.yml` | `linux_hosts` | Configure swap files. | `ansible-playbook playbooks/core/swap.yml --syntax-check` |
| `sysctl.yml` | `proxmox_nodes, linux_hosts` | Configure kernel sysctl settings. | `ansible-playbook playbooks/core/sysctl.yml --syntax-check` |
| `unattended-upgrades.yml` | `debian_hosts` | Configure unattended-upgrades (security patches). | `ansible-playbook playbooks/core/unattended-upgrades.yml --syntax-check` |
| `user-separation.yml` | `linux_hosts, orchestrator, media-vm, docker-vm` | Configure separated automation and operational users. | `ansible-playbook playbooks/core/user-separation.yml --syntax-check` |
