# Network Templates

## Templates

- `cloudflare-ddns-update.sh.j2`: Cloudflare DNS-only A-record updater for
  fixed external endpoints with dynamic WAN addresses.
- `netplan-static.yaml.j2`: Opt-in static netplan config for fixed LAN service
  addresses.
- `network-watchdog.sh.j2`: Network and Tailscale recovery watchdog.
- `tailscale-peer-relay-endpoint-sync.sh.j2`: Tailscale peer-relay static
  endpoint updater for dynamic WAN IPs.

## Consumers

- `playbooks/network/cloudflare-ddns.yml`
- `playbooks/network/network-recovery.yml`
- `playbooks/network/tailscale-peer-relay-endpoint.yml`

## Safety Notes

- Workstations intentionally opt out of automated recovery. Preserve host/group
  opt-ins before changing watchdog behavior.
