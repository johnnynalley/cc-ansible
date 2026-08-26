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
- `agent-docker-update-trigger.py`: Root-owned fixed-schema trigger for the
  existing Ansible-managed `docker-auto-update.service`; it accepts only status
  or run and cannot select a target, image, path, command, or Compose option.
- `test_agent_docker_update_trigger.py`: Regression coverage for strict input,
  updater availability, serialization, cooldown, bounded output, and the fixed
  systemd action.
- `test_agent_docker_playbooks.py`: Static regression coverage for locked
  forced-command accounts, exact CIDR parsing, pre-change rollback backups,
  group isolation, the fixed update target, and bytecode-free validation.
- `agent-compose-transaction.py`: Root-owned, stdin-only typed Compose target
  for Astra-managed stacks. It validates a strict declarative schema, journals
  mutations, takes per-stack backups, waits for health, and restores prior
  state on failed or interrupted applies without exposing the Docker socket.
- `test_agent_compose_transaction.py`: Regression coverage for schema
  hardening, root-owned state authority, read-only planning, exact request
  shapes, interrupted transaction recovery, and volume-preserving removal.

## Safety Notes

- Read-only by itself; it only inspects Docker image/container metadata.
- `--check-major` exits with code `2` when a confident major-version bump is
  detected so updater playbooks can block automatic recreation.
- Docker socket access is still root-equivalent. Only the root-owned reporter
  may receive it; agent runtimes receive the generated result and never the
  socket.
- The update request account may invoke only one exact root-owned trigger
  command. It can start the existing updater but cannot change its Ansible
  target selection or major-version policy.
- Trigger responses are restricted to bounded machine tokens and a one-hour
  per-host cooldown limits repeated requests.
- Compose apply/remove is available only through a separate forced account and
  exact per-request approval. It supports named volumes but denies host binds,
  secrets, privileged options, and volume deletion.
