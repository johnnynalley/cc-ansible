# Docker Scripts

## Scripts

- `docker-stack-diff`: Compares running container image IDs against pulled image
  IDs before a compose stack is updated. Runs on Docker hosts and is deployed
  as `/usr/local/bin/docker-stack-diff`.

## Safety Notes

- Read-only by itself; it only inspects Docker image/container metadata.
- `--check-major` exits with code `2` when a confident major-version bump is
  detected so updater playbooks can block automatic recreation.
