# FreePBX Templates

## Templates

- `interfaces.j2`: Static primary interface config for FreePBX.
- `freepbx-asterisk-logrotate.j2`: Asterisk logrotate policy for FreePBX.

## Consumers

- `playbooks/apps/freepbx.yml`

## Safety Notes

- Keep log rotation changes conservative; broken rotation can either lose logs
  or let Asterisk logs grow without bounds.
