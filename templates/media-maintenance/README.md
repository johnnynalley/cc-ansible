# Media Maintenance Templates

## Templates

- `nightly-media-maintenance.service.j2`: Main nightly maintenance service.
- `nightly-media-maintenance.timer.j2`: Main nightly maintenance timer.
- `nightly-media-maintenance-restore.service.j2`: Restore service after
  interrupted maintenance.
- `nightly-media-maintenance-restore.timer.j2`: Restore timer.
- `nightly-media-profilarr-client.sh.j2`: Profilarr SSH client used by the
  coordinator.
- `plex-library-nightly-scan.service.j2`: Runs the managed Plex library refresh
  helper on media-vm.
- `plex-library-nightly-scan.timer.j2`: Schedules Plex library refreshes during
  the overnight maintenance window.
- `plex-server-health.sh.j2`: Checks Plex identity, media-vm VirtioFS reads,
  ts440 host virtiofsd D-state, VM 100 state, and ZFS scrub-window violations.

## Consumers

- `playbooks/media/nightly-media-maintenance.yml`
- `playbooks/media/plex-server-health.yml`

## Safety Notes

- The normal overnight maintenance path opens Profilarr upgrades. Manually
  queued balance jobs are exceptional and own the window only while they are
  pending. Validate timer and restore changes carefully so media services are
  not left paused.
