# FreePBX Templates

## Templates

- `freepbx-asterisk-logrotate.j2`: Asterisk logrotate policy for FreePBX.

## Consumers

- `playbooks/freepbx.yml`

## Safety Notes

- Keep log rotation changes conservative; broken rotation can either lose logs
  or let Asterisk logs grow without bounds.
