# Agent Docker Access

## Current State

Hermes Astra has two live, separate Docker capabilities. Neither grants the
Hermes service a Docker socket, Docker group membership, sudo, a general SSH
shell, Compose paths, image selection, or arbitrary command arguments.

- `docker_inventory` reads a generated schema-v2 report from `docker-vm`,
  `media-vm`, `nextcloud-vm`, or `jn-t14s-lin`.
- `docker_update` reads updater status or starts the existing
  Ansible-managed `docker-auto-update.service` on `docker-vm`, `media-vm`,
  `nextcloud-vm`, or all three.

`jn-t14s-lin` remains inventory-only because its managed Docker auto-update
policy is disabled. Dubble and the logical Rigel role receive neither tool nor
credential. The retired Siri relay is unrelated and remains retired. The
independent Health receiver remains active.

## Trust Boundaries

The reporter and updater use different Ed25519 keys, remote accounts, forced
commands, sudo rules, state directories, and systemd credentials. Both SSH
keys are restricted to the exact `192.168.1.31/32` source and pinned Ed25519
host keys. Client commands, forwarding, PTYs, agents, and user rc files are
disabled.

The remote accounts are password-locked and have no supplementary groups.
The report account uses `nologin`. The update account uses `/bin/sh` because
OpenSSH executes an `authorized_keys` forced command through the account
shell; `nologin` blocks the forced command before it can run. This does not
create an interactive path because the sole authorized key has
`restrict,command=...`, password authentication is locked, and the sudo rule
matches one exact root-owned command.

The Hermes unit receives each private key as a read-only systemd credential.
The keys are not present in profile state, prompts, plugin source, Git, or
normal logs. Only the Astra Gateway unit receives them.

## Inventory Boundary

`playbooks/docker/agent-docker-report.yml` installs:

1. a root-owned collector that reads Docker locally and writes an atomic
   result file every five minutes; and
2. a forced-command reader that returns only that result.

The report contains the host and Engine versions plus bounded per-container
identity, state, health, restart/exit status, Compose project/service, image
reference and IDs, repository digests, image version/revision labels, and a
local update comparison.

The schema deliberately excludes environment variables, mounts, ports,
commands, labels other than the allowlisted version fields, logs, networks,
secrets, configs, events, volumes, file contents, and Docker object inspection
payloads. `pending-local` means a newer image is already present under the same
local tag; it is not registry freshness evidence.

The Hermes plugin independently validates the complete response shape, host,
field character sets, list bounds, and size before returning it to the model.

## Update Boundary

`playbooks/docker/agent-docker-update-trigger.yml` exposes one operation: start
the already-managed `docker-auto-update.service`. The request schema is exactly:

```json
{"schemaVersion":1,"action":"status"}
```

or:

```json
{"schemaVersion":1,"action":"run"}
```

The trigger accepts no target, service, image, tag, digest, path, command,
environment value, or Compose option. It verifies that the managed timer is
active, serializes requests under a root-owned lock, and enforces a one-hour
cooldown. Responses are bounded status tokens only.

The existing Ansible Docker policy remains authoritative for what updates:

- only stacks or services selected by `docker_stacks` auto-update fields;
- existing required-path, lock, health, and service-specific handling remains
  in the managed updater;
- confident major-version changes remain blocked by the existing major guard;
- Docker-socket proxy images are excluded from blind auto-updates and require
  attended Ansible convergence because compromise of that image can reach the
  host Docker daemon;
- Hermes cannot modify that policy or bypass it through this tool.

Scheduled systemd timer runs remain automatic. An unscheduled
`docker_update(action=run)` call is intercepted by Hermes's native
`pre_tool_call` approval path. The approval key includes the current turn ID,
so choosing session or permanent approval cannot authorize a later turn. Cron
contexts deny the call; they use the external systemd timer instead. Status
queries require no approval.

This is intentionally not a custom transaction broker. The rejected broker
would have duplicated Compose orchestration, introduced interrupted-plan and
rollback state, and risked applying unrelated Compose drift. Triggering the
already-operated native updater keeps one update implementation and gives
Hermes the unattended behavior the owner requested.

No production update was triggered during deployment. Status and boundary
probes passed; the next naturally scheduled run exercises the unchanged
updater, while the trigger's `run` branch is covered by isolated tests.

## Prompt-Injection Impact

A successful prompt injection into Astra can read the same redacted inventory
Astra can read, but an immediate updater run stops at a fresh native approval.
If the owner approves it, the one-hour per-host cooldown still applies. The
agent cannot choose what updates, cross a major-version block, obtain a shell,
inspect container secrets, or reach the Docker socket through these boundaries.

That is containment, not a claim that prompt injection is harmless. An
unwanted update can still cause the ordinary availability or upstream
supply-chain risk of the pre-authorized auto-update policy. Keep the target
allowlist narrow, retain backups and health checks, review upstream policy, and
revoke the dedicated update key or forced-command file to disable the path.

## Rollout And Revocation

The source-of-truth playbooks are:

- `playbooks/docker/agent-docker-report.yml`
- `playbooks/docker/agent-docker-update-trigger.yml`
- `playbooks/agents/hermes-docker-inventory.yml`

Each live rollout takes a targeted backup before replacing existing artifacts.
To revoke a remote boundary, set its `*_enabled` value false and converge the
owning Docker playbook. To revoke Astra, stop the Gateway and remove its
systemd credential bindings through the Hermes playbook. Do not manually add
Hermes to `docker`, expose `/var/run/docker.sock`, or grant broad updater sudo.

## Validation

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/docker/test_agent_docker_report.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/docker/test_agent_docker_update_trigger.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/docker/test_agent_docker_playbooks.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/agents/test_hermes_agent_docker_inventory.py
shellcheck scripts/docker/agent-docker-report-cat
ansible-playbook playbooks/docker/agent-docker-report.yml --syntax-check
ansible-playbook playbooks/docker/agent-docker-update-trigger.yml --syntax-check
ansible-playbook playbooks/agents/hermes-docker-inventory.yml --syntax-check
```
