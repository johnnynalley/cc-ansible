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

The account has no password login, Docker group, sudo rule, writable home,
interactive command, port forwarding, agent forwarding, PTY, or writable
`authorized_keys`. Source restrictions are parsed as canonical IPv4/IPv6 CIDRs
before OpenSSH configuration is written. The reporter allows only these fields:

- Engine version, API version, OS, and architecture;
- container short ID, name, state, status text, and health state;
- exact Compose project and service labels;
- configured image reference, running and local tagged image IDs, repository
  digests, creation timestamp, and OCI version/revision labels.

It never serializes raw Docker responses. Regression tests inject secret
sentinels into environment variables, commands, health logs, mounts, ports,
networks, and private labels and require all of them to remain absent. OCI
version and revision values must also be bounded single tokens; prose-shaped
labels are dropped instead of being carried into an agent prompt. The reporter
fails closed above 2,048 containers or a 16 MiB encoded report.

`updateState` compares the running image with the image currently resolved by
the same local tag. `pending-local` means a newer image is already present on
that host; it is not a remote-registry update guarantee. Registry checking
remains owned by the existing auto-update and Diun workflows.

## Update Boundary

The read-only reporter does not update containers. The separately managed
`playbooks/docker/openclaw-docker-update-broker.yml` implementation is also
disabled by default. It gives the isolated Gateway only a forced-command SSH
request interface; it does not give the Gateway Docker, sudo, shell, or Compose
access.

The broker enforces these properties:

- Astra may create a proposal, but may not approve or alter the accepted plan.
- Approval occurs outside the Gateway trust boundary through a human/Codex or
  dedicated operator path.
- The broker accepts only strict JSON with `propose`, `status`, or `execute`
  plus one opaque target or plan ID. Paths, image references, service names,
  Compose arguments, health checks, and backup files cannot come from Astra.
- A root-owned inventory manifest maps an opaque target ID to one Compose
  service transaction. Unknown fields, path traversal, multiple services or
  replicas, missing image digests, stale plans, runtime drift, configuration
  drift, and candidate-tag drift are rejected. The complete Compose project
  tree must be root-owned, contain no symlinks or special files, and be
  non-writable by group or other so implicit `.env`, include, and extends
  inputs cannot bypass the allowlist.
- Proposal creation pulls the allowlisted service image into the local cache,
  but cannot recreate a container. It records the current and candidate image
  IDs/digests in a short-lived content-addressed plan.
- Only a local root/operator command can approve that exact plan. Approval is
  short-lived, stored outside the request account's access, and consumed before
  the first transactional side effect. A preparation failure records a
  terminal `failed` result and cannot reuse the approval. The root-only
  approval record and audit log name the sudo operator when available. Astra
  cannot call the approve or reject paths.
- The initial broker supports only `stateless-image` targets. It rejects an
  image that declares volumes; any running-container mount or device access;
  and Compose services with volumes, secrets, configs, builds, added
  capabilities, shared namespaces, or privileged mode. Eligible services must
  run as a numeric non-root UID, use a read-only root filesystem, drop all
  capabilities, set `no-new-privileges`, and expose a Docker health check.
  Stateful or broadly privileged containers remain visible in the report but
  are not eligible for Astra-driven updates.
- Docker CLI subprocesses use an isolated root-only `DOCKER_CONFIG` directory,
  not root's normal credential store. Candidate version and revision fields
  use the same bounded-token rule as the reporter.
- It captures the relevant compose/config rollback artifact, applies the exact
  approved digest through a generated Compose override, runs fixed
  service-specific health checks, and recreates the previous locally tagged
  image on failure.
- Plans are one-use. A process interruption after execution starts leaves the
  transaction in `executing` for operator recovery rather than replaying it.
- It returns a bounded result document and never returns secrets or raw logs.

Image-and-config rollback is not application-data rollback. A stateful service
may be added only after its target has a separately reviewed, application-native
backup and restore transaction with a proved recovery test. Merely retaining the
old image or copying Compose files is not sufficient for a database migration.

The operator flow, after a broker proposal is independently reviewed, is:

```bash
sudo openclaw-docker-update-broker show PLAN_ID
sudo openclaw-docker-update-broker approve PLAN_ID
# Astra may now send the one-use execute request before approval expires.
sudo openclaw-docker-update-broker reject PLAN_ID
```

Approval must compare the exact target, current image, candidate digest,
version/revision evidence, and expected downtime. A registry image remains
untrusted code: digest pinning prevents tag movement between approval and
execution, but it cannot make a compromised upstream image safe.

Do not expose `/usr/local/sbin/docker-auto-update`, the Docker socket, Portainer,
or the existing broad `dbc` helpers directly to Astra as an update mechanism.

## Rollout Order

1. Create dedicated `openclaw` and `openclaw-health` service identities on the
   controller and move the Gateway and Health receiver without copying human
   SSH, Git, sudo, Docker, or vault credentials.
2. Generate a dedicated Ed25519 report-reader key under the `openclaw` identity.
3. Back up the affected host state, populate the public key and exact Tailscale
   source CIDR, enable the reporter, and canary one Docker host. The enabled
   playbook backs up any pre-existing managed artifacts to
   `/srv/live-rollbacks` before replacing them; a clean first install has no
   prior artifact to copy.
4. Verify the report schema, forced-command rejection, source restriction,
   timer health, and absence of every secret sentinel before estate rollout.
5. Populate one reviewed, health-checked, stateless service target and a
   separate update-request key, then canary the broker only after a distinct
   owner approval. Its enabled playbook applies the same pre-existing-artifact
   backup gate.
6. Verify proposal redaction, approval separation, digest/config drift
   rejection, health failure rollback, replay rejection, and root-only audit
   artifacts before adding another target or host.

## Validation

```bash
python3 scripts/docker/test_openclaw_docker_report.py
python3 scripts/docker/test_openclaw_docker_update_broker.py
python3 scripts/docker/test_openclaw_docker_playbooks.py
shellcheck scripts/docker/openclaw-docker-report-cat
ansible-playbook playbooks/docker/openclaw-docker-report.yml --syntax-check
ansible-playbook playbooks/docker/openclaw-docker-report.yml --check --diff
ansible-playbook playbooks/docker/openclaw-docker-update-broker.yml --syntax-check
ansible-playbook playbooks/docker/openclaw-docker-update-broker.yml --check --diff
```

The default check runs must leave all hosts disabled and must not provision a
key, account, timer, report, broker target, proposal, credential, or Docker
access path.
