# Media Maintenance Templates

## Templates

- `nightly-media-maintenance.service.j2`: Main nightly maintenance service.
- `nightly-media-maintenance.timer.j2`: Main nightly maintenance timer.
- `nightly-media-maintenance-restore.service.j2`: Restore service after
  interrupted maintenance.
- `nightly-media-maintenance-restore.timer.j2`: Restore timer.
- `nightly-media-profilarr-client.sh.j2`: Profilarr SSH client used by the
  coordinator.

## Consumers

- `playbooks/nightly-media-maintenance.yml`

## Safety Notes

- Balance jobs own the overnight maintenance window. Validate timer and restore
  changes carefully so media services are not left paused.
