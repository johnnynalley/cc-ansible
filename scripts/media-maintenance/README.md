# Media Maintenance Scripts

## Scripts

- `nightly-media-maintenance`: Coordinates overnight media maintenance on the
  NAS host. Balance jobs own the overnight window; if no balance job is pending,
  it queues controlled Profilarr upgrade work through the media-stack endpoint.
  `balance defer set --until ...` or `balance defer set --for-days ...` delays
  pending balance jobs while still allowing Profilarr upgrade work during the
  overnight window.

## Safety Notes

- Mutates only through explicit subcommands and its configured state directory.
- Validate playbook changes with `playbooks/media/nightly-media-maintenance.yml`
  before changing deployed timers or command paths.
