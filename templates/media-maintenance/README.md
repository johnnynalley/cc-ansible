# Media Maintenance Templates

## Templates

- `nightly-media-maintenance.service.j2`: Main nightly maintenance service.
- `nightly-media-maintenance.timer.j2`: Main nightly maintenance timer.
- `nightly-media-maintenance-restore.service.j2`: Restore service after
  interrupted maintenance.
- `nightly-media-maintenance-restore.timer.j2`: Restore timer.
- `nightly-media-profilarr-client.sh.j2`: Profilarr SSH client used by the
  coordinator.
- `sonarr-large-series-upgrade.service.j2`: Runs one guarded, season-scoped
  Sonarr search for series excluded from Profilarr's full-series threshold.
- `sonarr-large-series-upgrade.timer.j2`: Checks hourly at `:30` during the
  configured overnight window; the helper skips when Profilarr, RSS, or another
  Sonarr search is active.
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
- A Profilarr-only restore closes its upgrade window without touching the media
  stack. The restore path starts the media stack only when that window was
  actually owned by a balance job.
