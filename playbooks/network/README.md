# network Playbooks

Owner area: Network recovery and adapter tuning.

## Operating Notes

- Key vars: network_recovery_*, netplan_*, wifi_*, e1000e_*.
- Template owners: templates/network.
- Script owners: none by default.
- Keep playbook metadata headers and `playbooks/README.md` in sync when behavior changes.

## Playbooks

| Playbook | Hosts | Purpose | Validation |
| --- | --- | --- | --- |
| `e1000e-tuning.yml` | `proxmox_nodes` | Tune e1000e NICs (disable EEE/TSO). | `ansible-playbook playbooks/network/e1000e-tuning.yml --syntax-check` |
| `network-recovery.yml` | `linux_hosts:!workstations` | Configure network recovery. | `ansible-playbook playbooks/network/network-recovery.yml --syntax-check` |
| `wifi.yml` | `linux_hosts` | Configure WiFi power management. | `ansible-playbook playbooks/network/wifi.yml --syntax-check` |
