# Smartmontools Templates

## Templates

- `smartd.conf.j2`: SMART monitoring configuration.
- `smartd-notify.sh.j2`: SMART alert notification helper.

## Consumers

- `playbooks/core/smartmontools.yml`

## Safety Notes

- Keep notification routing and device matching conservative so disk alerts
  remain loud and reliable.
