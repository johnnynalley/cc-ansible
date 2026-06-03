# Media Maintenance Scripts

## Scripts

- `nightly-media-maintenance`: Coordinates overnight media maintenance on the
  NAS host. Balance jobs own the overnight window; if no balance job is pending,
  it opens Profilarr's native Arr upgrade scheduler through the media-stack
  endpoint and closes it during restore.
  `balance defer set --until ...` or `balance defer set --for-days ...` delays
  pending balance jobs while still allowing Profilarr upgrade work during the
  overnight window.
- `plex-library-nightly-scan`: Refreshes Plex library sections through the
  local Plex API during the controlled overnight maintenance window.

## Safety Notes

- Mutates only through explicit subcommands and its configured state directory.
- Plex library refreshes should stay timer-owned; do not re-enable live
  filesystem-triggered scans without proving they cannot starve playback.
- Validate playbook changes with `playbooks/media/nightly-media-maintenance.yml`
  before changing deployed timers or command paths.
