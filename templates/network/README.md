# Network Templates

## Templates

- `network-watchdog.sh.j2`: Network and Tailscale recovery watchdog.

## Consumers

- `playbooks/network-recovery.yml`

## Safety Notes

- Workstations intentionally opt out of automated recovery. Preserve host/group
  opt-ins before changing watchdog behavior.
