# UPS Templates

## Templates

- `apcupsd.conf.j2`: APC UPS daemon configuration.
- `apcupsd-event-notify.sh.j2`: APC UPS event notification helper.

## Consumers

- `playbooks/apcupsd.yml`

## Safety Notes

- UPS notifications should remain loud for power loss and battery events.
  Preserve master/slave role behavior when changing daemon config.
