# Agent Runtime Scripts

## Health Receiver

- `health-receiver.py` is the bounded, authenticated Health Auto Export
  receiver. It writes only to the dedicated Health SQLite database and does not
  call OpenClaw or any model session.
- `health-summary.py` reads the database in SQLite query-only mode and publishes
  fixed aggregate JSON and Markdown reports. It never emits raw payloads,
  source-device names, database paths, or row-level values.
- `health-receiver-check.py` performs the authenticated cutover/canary probe by
  reading the token from a protected file; the token never enters command-line
  arguments, Ansible output, or the process environment.
- `test_health_receiver.py` covers authentication, path/body/rate controls,
  payload bounds, malformed record rejection, and duplicate prevention.
- `test_health_summary.py` covers duplicate collapse, aggregate-only output,
  atomic report permissions, and generic missing-database errors.

The repo is the source of truth for both scripts. The legacy copies under the
OpenClaw workspace are migration inputs only and must be retired after the
dedicated `openclaw-health` system service passes cutover validation.

## Isolated Gateway

- `openclaw-isolated-secrets.py` preserves or generates the canary Gateway
  token and atomically writes one service-owned, owner-read-only SecretRef
  payload inside a root-owned directory. It imports no legacy provider or
  application credentials. This satisfies the current OpenClaw file-provider
  contract while the systemd sandbox keeps the path read-only to the service.
  It rejects symlinks and unsafe output directories, and its output contains
  only status and change state.
- `test_openclaw_isolated_secrets.py` covers atomic permissions, idempotency,
  unexpected-field removal, parent ownership, and Gateway-token preservation.
- `openclaw-session-relocate.py` inventories the shipped file-backed session
  stores, rewrites only approved absolute state/workspace path fields on a
  copied target, and verifies JSONL byte parity plus semantic metadata parity.
  It rejects missing paths, symlink escapes, unknown path-bearing fields, and
  any target session artifact that differs from its source.
- `test_openclaw_session_relocate.py` covers deterministic relocation,
  idempotency, byte preservation, unknown-field rejection, path-boundary
  enforcement, and target drift detection.
- `openclaw-doctor-rehearsal.py` creates credential-free structured config
  copies, replaces retained external plugin paths with reviewed immutable
  artifacts, retires explicit legacy plugin ids, performs online SQLite backups,
  scrubs only per-agent auth tables, and emits data-free manifests and database
  summaries for Doctor idempotency checks.
- `test_openclaw_doctor_rehearsal.py` covers config path and secret handling,
  plugin modernization boundaries, auth-only database scrubbing, SQLite
  summaries, and immutable tree manifest comparison.

## Validation

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/agents -p 'test_*.py' -v
black --check scripts/agents
```
