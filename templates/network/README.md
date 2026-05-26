# Network Templates

## Templates

- `netplan-static.yaml.j2`: Opt-in static netplan config for fixed LAN service
  addresses.
- `network-watchdog.sh.j2`: Network and Tailscale recovery watchdog.

## Consumers

- `playbooks/network/network-recovery.yml`

## Safety Notes

- Workstations intentionally opt out of automated recovery. Preserve host/group
  opt-ins before changing watchdog behavior.
