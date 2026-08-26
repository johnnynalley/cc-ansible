# Agent Docker Access

## Current State

Hermes Astra has three live, separate Docker capabilities. None grants the
Hermes service a Docker socket, Docker group membership, sudo, a general SSH
shell, arbitrary host paths, or arbitrary command arguments.

- `docker_inventory` reads a generated schema-v2 report from every current
  member of the Ansible `docker_hosts` group. Each report is generated from
  the live Docker Engine inventory, so containers added outside Ansible appear
  automatically on the next five-minute collection cycle.
- `docker_update` reads updater status or starts the existing
  Ansible-managed `docker-auto-update.service` on current `docker_hosts` whose
  inventory policy enables that updater.
- `compose_hosts` and `compose_request` expose a typed, rollback-backed
  transaction boundary on every current `docker_hosts` member. Astra can list
  managed stacks, validate a proposed declarative spec, and, after exact fresh
  approval, apply/update or remove an Astra-managed stack.

At this writing, `jn-t14s-lin` remains inventory-only because its managed
Docker auto-update policy is disabled. Dubble and Rigel receive neither tool nor
credential. The retired Siri relay is unrelated and remains retired. The
independent Health receiver remains active.

## Trust Boundaries

The reporter, updater, and Compose target use different Ed25519 keys, remote
accounts, forced commands, sudo rules, state directories, and systemd
credentials. All SSH
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

Ansible renders a root-owned endpoint manifest and pinned `known_hosts` file
from the current `docker_hosts` membership, each host's primary inventory
address, and its live Ed25519 SSH host key. The plugin reloads and validates
that manifest on every tool call. Adding a Docker host therefore requires an
inventory declaration plus convergence of the reporter, updater policy, and
Astra access playbooks, but no plugin source edit or hardcoded hostname. A host
cannot add itself to Astra's authority merely by appearing on the network.

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
The endpoint manifest controls which hosts may answer; it does not enumerate
containers. Container discovery remains live and complete within the bounded
report schema.

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

No production update was triggered during deployment. Status and boundary
probes passed; the next naturally scheduled run exercises the unchanged
updater, while the trigger's `run` branch is covered by isolated tests.

## Compose Transaction Boundary

`playbooks/agents/hermes-compose-admin.yml` enrolls every current Docker host
through a dedicated `agent-compose` forced-command account. That account has
no supplementary groups. Its only sudo rule invokes one root-owned executable
with no command-line arguments; the complete typed request arrives on stdin.

The transaction schema permits dynamic stack, service, and image names without
hardcoding current containers. It allows production-versioned public images,
non-secret environment values, project-scoped named volumes, bounded tmpfs,
loopback or exact discovered-LAN ports, restart policy, read-only root
filesystems, and bounded CPU, memory, and PID limits.

It rejects `latest` or unversioned images, inline secret-like environment
keys, host bind mounts, the Docker socket, privileged mode, host namespaces or
networking, devices, added capabilities, arbitrary Compose keys, shell input,
and volume deletion. Compose files and transaction journals are root-owned
under `/opt/hermes-managed-stacks`; prior specs are archived under
`/var/backups/agent-compose`. Audit records contain only host, action, stack,
outcome, timestamp, and desired digest.

`status` and `plan` are read-only. Planning writes only an ephemeral file under
`/run` and runs `docker compose config --quiet`; it does not pull an image or
create a stack. `apply` and `remove` require approval keyed to the current turn
and SHA-256 digest of the exact request. Apply validates, pulls, atomically
promotes, waits for health, and restores the prior stack on failure. Remove
backs up and stops the project but deliberately preserves named volumes.
Interrupted transactions are journaled and recovered before another mutation.

This boundary manages only stacks created through it. It does not adopt or
rewrite repository/Ansible-owned Compose projects. Existing stacks remain
visible through dynamic inventory and update through existing managed policy.

## Prompt-Injection Impact

A successful prompt injection into Astra can read the same redacted inventory
Astra can read and validate a non-secret Compose plan, but updater and Compose
mutations stop at fresh native approval. Compose approval is bound to the exact
request digest; changing an image, port, service, or stack requires another
approval. The agent cannot obtain a shell, inspect container secrets, mount host
state, delete named volumes, or reach the Docker socket through these boundaries.

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
- `playbooks/agents/hermes-compose-admin.yml`

Each live rollout takes a targeted backup before replacing existing artifacts.
To revoke a remote boundary, set its `*_enabled` value false and converge the
owning Docker playbook. To revoke Astra, stop the Gateway and remove its
systemd credential bindings through the Hermes playbook. Do not manually add
Hermes to `docker`, expose `/var/run/docker.sock`, or grant broad updater sudo.

To add a Docker host, place it in `docker_hosts`, configure its normal Docker
and updater policy, converge the two Docker-side playbooks, and then converge
`hermes-docker-inventory.yml`. To add a container on an existing host, no Astra
configuration change is needed; the next collector run publishes it.

Compose revocation is independent: remove the Astra credential/plugin and the
target forced key/sudo rule through the owning playbook. Existing containers
and named volumes are not deleted by revocation.

## Validation

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/docker/test_agent_docker_report.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/docker/test_agent_docker_update_trigger.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/docker/test_agent_docker_playbooks.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/agents/test_hermes_agent_docker_inventory.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/docker/test_agent_compose_transaction.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/agents/test_hermes_compose_admin.py
shellcheck scripts/docker/agent-docker-report-cat
ansible-playbook playbooks/docker/agent-docker-report.yml --syntax-check
ansible-playbook playbooks/docker/agent-docker-update-trigger.yml --syntax-check
ansible-playbook playbooks/agents/hermes-docker-inventory.yml --syntax-check
ansible-playbook playbooks/agents/hermes-compose-admin.yml --syntax-check
```
