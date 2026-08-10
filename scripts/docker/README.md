# Docker Scripts

## Scripts

- `docker-stack-diff`: Compares running container image IDs against pulled image
  IDs before a compose stack is updated. Runs on Docker hosts and is deployed
  as `/usr/local/bin/docker-stack-diff`.
- `openclaw-docker-report.py`: Root-owned Docker Engine reader that emits only
  the allowlisted inventory schema documented in `docs/openclaw-docker-access.md`.
- `openclaw-docker-report-cat`: Forced-command SSH wrapper that returns only the
  generated report and rejects client-supplied commands.
- `test_openclaw_docker_report.py`: Regression coverage for schema redaction,
  local image comparison, and report permissions.

## Safety Notes

- Read-only by itself; it only inspects Docker image/container metadata.
- `--check-major` exits with code `2` when a confident major-version bump is
  detected so updater playbooks can block automatic recreation.
- Docker socket access is still root-equivalent. Only the root-owned reporter
  may receive it; OpenClaw receives the generated result and never the socket.
