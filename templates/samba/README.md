# Samba Templates

## Templates

- `smb.conf.j2`: Samba server configuration.
- `avahi-timemachine.service.j2`: Time Machine mDNS advertisement.

## Consumers

- `tasks/samba.yml`

## Safety Notes

- Time Machine visibility depends on Samba, Avahi, and firewall behavior
  staying aligned.
