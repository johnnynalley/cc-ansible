# media Playbooks

Owner area: Plex, streaming, media maintenance, release-policy automation.

## Operating Notes

- Key vars: nightly_media_*, media_release_stamper_*, media_stack_health_*, immich_media_inbox_*, stream_relay_*, plex_appliance_*.
- Template owners: templates/media-inbox, templates/media-maintenance, templates/streaming, templates/plex-appliance, templates/docker.
- Script owners: scripts/media-inbox, scripts/media-maintenance, scripts/media-release, scripts/streaming.
- Keep playbook metadata headers and `playbooks/README.md` in sync when behavior changes.

## Playbooks

| Playbook | Hosts | Purpose | Validation |
| --- | --- | --- | --- |
| `immich-media-inbox.yml` | `docker_hosts` (opt-in) | Deploy Astra's headless Immich screenshot semantic-analysis queue. | `ansible-playbook playbooks/media/immich-media-inbox.yml --syntax-check` |
| `media-release-stamper.yml` | `gluetun_hosts` | Configure media release metadata stamping plus exact-target import and terminal qBittorrent reconciliation; use `--tags media-release-reconciler` to deploy/reload only the reconciler boundary. | `ansible-playbook playbooks/media/media-release-stamper.yml --syntax-check` |
| `media-stack-health.yml` | `docker-vm` | Configure media health monitoring and classified NFS/container-bind recovery. | `ansible-playbook playbooks/media/media-stack-health.yml --syntax-check` |
| `plex-server-health.yml` | `media-vm, nas_server` | Configure Plex server, VirtioFS, and scrub-window health monitor. | `ansible-playbook playbooks/media/plex-server-health.yml --syntax-check` |
| `nightly-media-maintenance.yml` | `nas_server, media-vm:docker-vm` | Configure nightly media maintenance. | `ansible-playbook playbooks/media/nightly-media-maintenance.yml --syntax-check` |
| `plex-appliance.yml` | `plex_appliances` | Configure Plex appliance. | `ansible-playbook playbooks/media/plex-appliance.yml --syntax-check` |
| `sonarr-transaction-monitor.yml` | `gluetun_hosts:media-vm` | Configure Sonarr transaction monitor. | `ansible-playbook playbooks/media/sonarr-transaction-monitor.yml --syntax-check` |
| `stream-relay.yml` | `media-vm` | Configure stream relay. | `ansible-playbook playbooks/media/stream-relay.yml --syntax-check` |
