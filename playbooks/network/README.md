# network Playbooks

Owner area: Network recovery, adapter tuning, and DNS endpoint automation.

## Operating Notes

- Key vars: network_recovery_*, netplan_*, wifi_*, e1000e_*,
  cloudflare_ddns_*, tailscale_peer_relay_endpoint_*, tailscale_peer_relay_*.
- Template owners: templates/network.
- Script owners: none by default.
- Keep playbook metadata headers and `playbooks/README.md` in sync when behavior changes.

## Playbooks

| Playbook | Hosts | Purpose | Validation |
| --- | --- | --- | --- |
| `cloudflare-ddns.yml` | `cloudflare_ddns_hosts` | Configure DNS-only Cloudflare DDNS updater timers. | `ansible-playbook playbooks/network/cloudflare-ddns.yml --syntax-check` |
| `e1000e-tuning.yml` | `proxmox_nodes` | Tune e1000e NICs (disable EEE/TSO). | `ansible-playbook playbooks/network/e1000e-tuning.yml --syntax-check` |
| `network-recovery.yml` | `linux_hosts:!workstations` | Configure network recovery. | `ansible-playbook playbooks/network/network-recovery.yml --syntax-check` |
| `tailscale-peer-relay-endpoint.yml` | `tailscale_peer_relay_endpoint_hosts` | Keep peer-relay static endpoints synced to current WAN IPs. | `ansible-playbook playbooks/network/tailscale-peer-relay-endpoint.yml --syntax-check` |
| `wifi.yml` | `linux_hosts` | Configure WiFi power management. | `ansible-playbook playbooks/network/wifi.yml --syntax-check` |
