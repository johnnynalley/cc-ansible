# docker Playbooks

Owner area: Docker Compose stacks and container maintenance.

## Operating Notes

- Key vars: docker_stacks, docker_daemon_config, docker_auto_update_*,
  agent_docker_report_*, agent_docker_update_broker_*, gluetun_*, qbit_*.
- Template owners: templates/docker, templates/gluetun.
- Script owners: scripts/docker.
- Keep playbook metadata headers and `playbooks/README.md` in sync when behavior changes.

## Playbooks

| Playbook | Hosts | Purpose | Validation |
| --- | --- | --- | --- |
| `docker-auto-update.yml` | `docker_hosts` | Configure Docker container auto-updates. | `ansible-playbook playbooks/docker/docker-auto-update.yml --syntax-check` |
| `agent-docker-report.yml` | `docker_hosts` | Publish a strict redacted inventory through a forced-command account; disabled by default. | `ansible-playbook playbooks/docker/agent-docker-report.yml --syntax-check` |
| `agent-docker-update-broker.yml` | `docker_hosts` | Install a strict, separately approved, digest-bound service update broker; disabled by default. | `ansible-playbook playbooks/docker/agent-docker-update-broker.yml --syntax-check` |
| `docker-stacks.yml` | `docker_hosts` | Deploy Docker Compose stacks. | `ansible-playbook playbooks/docker/docker-stacks.yml --syntax-check` |
| `gluetun-watchdog.yml` | `gluetun_hosts:media-vm` | Configure Gluetun VPN watchdog. | `ansible-playbook playbooks/docker/gluetun-watchdog.yml --syntax-check` |
