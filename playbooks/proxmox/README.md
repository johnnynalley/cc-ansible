# proxmox Playbooks

Owner area: Proxmox cluster, firewall, PBS, PDM, and VM hardware.

## Operating Notes

- Key vars: proxmox_*, pve_*, pbs_*, pdm_*.
- Template owners: templates/proxmox.
- Script owners: none by default.
- Keep playbook metadata headers and `playbooks/README.md` in sync when behavior changes.

## Playbooks

| Playbook | Hosts | Purpose | Validation |
| --- | --- | --- | --- |
| `pdm.yml` | `pdm_servers` | Configure Proxmox Datacenter Manager services. | `ansible-playbook playbooks/proxmox/pdm.yml --syntax-check` |
| `proxmox-backup-server.yml` | `pbs-lxc, proxmox_nodes` | Configure Proxmox Backup Server. | `ansible-playbook playbooks/proxmox/proxmox-backup-server.yml --syntax-check` |
| `proxmox-firewall.yml` | `proxmox_nodes` | Configure Proxmox firewall. | `ansible-playbook playbooks/proxmox/proxmox-firewall.yml --syntax-check` |
| `proxmox-ha.yml` | `proxmox_nodes` | Manage Proxmox HA service state. | `ansible-playbook playbooks/proxmox/proxmox-ha.yml --syntax-check` |
| `proxmox-notifications.yml` | `proxmox_nodes` | Configure Proxmox notification webhooks. | `ansible-playbook playbooks/proxmox/proxmox-notifications.yml --syntax-check` |
| `proxmox-pdm-vm.yml` | `pve-alto` | Provision the Proxmox Datacenter Manager VM. | `ansible-playbook playbooks/proxmox/proxmox-pdm-vm.yml --syntax-check` |
| `proxmox-router-firewall.yml` | `proxmox_nodes` | Configure router firewall rules on Proxmox nodes. | `ansible-playbook playbooks/proxmox/proxmox-router-firewall.yml --syntax-check` |
| `proxmox-vm-hardware.yml` | `proxmox_nodes, linux_hosts` | Configure Proxmox guest hardware settings. | `ansible-playbook playbooks/proxmox/proxmox-vm-hardware.yml --syntax-check` |
