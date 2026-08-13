# Docker Scripts

## Scripts

- `docker-stack-diff`: Compares running container image IDs against pulled image
  IDs before a compose stack is updated. Runs on Docker hosts and is deployed
  as `/usr/local/bin/docker-stack-diff`.
- `agent-docker-report.py`: Root-owned Docker Engine reader that emits only
  the allowlisted inventory schema documented in `docs/agent-docker-access.md`.
- `agent-docker-report-cat`: Forced-command SSH wrapper that returns only the
  generated report and rejects client-supplied commands.
- `test_agent_docker_report.py`: Regression coverage for schema redaction,
  bounded metadata, local image comparison, and report permissions.
- `agent-docker-update-broker.py`: Root-owned transaction broker that accepts
  only allowlisted target IDs, creates digest-bound plans, requires separate
  root approval, verifies health, and rolls back failed Compose updates.
- `test_agent_docker_update_broker.py`: Regression coverage for strict input,
  plan integrity, approval separation, redaction, drift rejection,
  one-use failure handling, stateless sandbox enforcement, trusted Compose
  inputs, and rollback.
- `test_agent_docker_playbooks.py`: Static regression coverage for locked
  forced-command accounts, exact CIDR parsing, pre-change rollback backups,
  stateless target policy, and complete disabled-state unit shutdown.

## Safety Notes

- Read-only by itself; it only inspects Docker image/container metadata.
- `--check-major` exits with code `2` when a confident major-version bump is
  detected so updater playbooks can block automatic recreation.
- Docker socket access is still root-equivalent. Only the root-owned reporter
  may receive it; agent runtimes receive the generated result and never the
  socket.
- The update request account may invoke only the broker's fixed `request`
  command. Root-only `approve` and `reject` commands remain outside Astra's
  trust boundary.
- Broker responses are restricted to bounded machine tokens. Legacy state is
  retained as an inert root-only archive, not imported as executable plans.
- Eligible broker targets are intentionally narrow: one stateless, non-root,
  read-only, capability-free, health-checked service with no mounts, devices,
  build context, secrets, configs, or shared host namespaces.
