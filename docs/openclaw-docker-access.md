# OpenClaw Docker Access

## Current State

The implementation is intentionally disabled. The live OpenClaw Gateway still
runs as `johnny`, which is already a root-equivalent controller account. Giving
that process any additional Docker path would not create a meaningful security
boundary. Do not enable `openclaw_docker_report_enabled` until the dedicated
OpenClaw runtime identity and key are in place and the rollout is approved.

The Siri relay is retired. The authenticated Health receiver remains in use,
but it must move to its own no-exec service identity during the runtime
migration; it is not a Docker-management transport.

## Threat Model

Treat the OpenClaw Gateway, every agent response, fetched web content, Discord
content, attachments, skills, and tool output as potentially prompt-injected.
Compromise of that boundary must not grant any of the following:

- membership in the `docker` group or direct access to `docker.sock`;
- sudo, a human login shell, controller credentials, or Ansible vault access;
- arbitrary commands, Docker Engine API calls, compose edits, or container logs;
- environment variables, mounts, ports, networks, commands, or arbitrary labels;
- approval of an action proposed by the same compromised Gateway.

Docker socket access is root-equivalent. A read-only filesystem mount of the
socket does not make the Docker API read-only, so the socket must remain behind
a root-owned program that emits a strict result schema.

## Read-Only Reporter

`playbooks/docker/openclaw-docker-report.yml` installs two separate boundaries
on each opted-in Docker host:

1. A hardened root-owned oneshot service reads the local Unix socket and writes
   `/var/lib/openclaw-docker-report/data/report.json` every five minutes.
2. A dedicated `openclaw-report` SSH account can run only
   `/usr/local/bin/openclaw-docker-report-cat` from an allowlisted source CIDR.
   The reader rejects reports older than 15 minutes instead of silently serving
   stale container state.

The account has no Docker group, sudo rule, writable home, interactive command,
port forwarding, agent forwarding, PTY, or writable `authorized_keys`. The
reporter allows only these fields:

- Engine version, API version, OS, and architecture;
- container short ID, name, state, status text, and health state;
- exact Compose project and service labels;
- configured image reference, running and local tagged image IDs, repository
  digests, creation timestamp, and OCI version/revision labels.

It never serializes raw Docker responses. Regression tests inject secret
sentinels into environment variables, commands, health logs, mounts, ports,
networks, and private labels and require all of them to remain absent.

`updateState` compares the running image with the image currently resolved by
the same local tag. `pending-local` means a newer image is already present on
that host; it is not a remote-registry update guarantee. Registry checking
remains owned by the existing auto-update and Diun workflows.

## Update Boundary

The read-only reporter does not update containers. A future update broker must
be a separate root-owned service with all of these properties:

- Astra may create a proposal, but may not approve or alter the accepted plan.
- Approval occurs outside the Gateway trust boundary through a human/Codex or
  dedicated operator path.
- The broker accepts a short-lived, content-addressed plan for an allowlisted
  host, stack, and service; free-form compose arguments are rejected.
- It captures the relevant compose/config rollback artifact, applies the exact
  approved image change, runs service-specific health checks, and rolls back on
  failure.
- It returns a bounded result document and never returns secrets or raw logs.

Do not expose `/usr/local/sbin/docker-auto-update`, the Docker socket, Portainer,
or the existing broad `dbc` helpers directly to Astra as an update mechanism.

## Rollout Order

1. Create dedicated `openclaw` and `openclaw-health` service identities on the
   controller and move the Gateway and Health receiver without copying human
   SSH, Git, sudo, Docker, or vault credentials.
2. Generate a dedicated Ed25519 report-reader key under the `openclaw` identity.
3. Back up the affected host state, populate the public key and exact Tailscale
   source CIDR, enable the reporter, and canary one Docker host.
4. Verify the report schema, forced-command rejection, source restriction,
   timer health, and absence of every secret sentinel before estate rollout.
5. Design and separately approve the immutable update broker.

## Validation

```bash
python3 scripts/docker/test_openclaw_docker_report.py
shellcheck scripts/docker/openclaw-docker-report-cat
ansible-playbook playbooks/docker/openclaw-docker-report.yml --syntax-check
ansible-playbook playbooks/docker/openclaw-docker-report.yml --check --diff
```

The default check run must leave all hosts disabled and must not provision a
key, account, timer, report, or Docker access path.
