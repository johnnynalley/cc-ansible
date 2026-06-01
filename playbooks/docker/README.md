# docker Playbooks

Owner area: Docker Compose stacks and container maintenance.

## Operating Notes

- Key vars: docker_stacks, docker_daemon_config, docker_auto_update_*,
  gluetun_*, qbit_*.
- Template owners: templates/docker, templates/gluetun.
- Script owners: scripts/docker.
- Keep playbook metadata headers and `playbooks/README.md` in sync when behavior changes.

## Playbooks

| Playbook | Hosts | Purpose | Validation |
| --- | --- | --- | --- |
| `docker-auto-update.yml` | `docker_hosts` | Configure Docker container auto-updates. | `ansible-playbook playbooks/docker/docker-auto-update.yml --syntax-check` |
| `docker-stacks.yml` | `docker_hosts` | Deploy Docker Compose stacks. | `ansible-playbook playbooks/docker/docker-stacks.yml --syntax-check` |
| `gluetun-watchdog.yml` | `gluetun_hosts:media-vm` | Configure Gluetun VPN watchdog. | `ansible-playbook playbooks/docker/gluetun-watchdog.yml --syntax-check` |
