# Gluetun Templates

## Templates

- `gluetun-watchdog.sh.j2`: Gluetun crash-loop and VPN health watchdog.
- `qbit-port-sync.sh.j2`: qBittorrent forwarded-port sync helper.

## Consumers

- `playbooks/docker/gluetun-watchdog.yml`

## Safety Notes

- These templates affect VPN-protected download behavior. Avoid changes that
  can expose qBittorrent outside the intended Gluetun network path.
