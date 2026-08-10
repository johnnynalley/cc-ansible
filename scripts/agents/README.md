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

- `openclaw-isolated-secrets.py` reads one exact credential from the protected
  legacy dotenv file, preserves or generates the canary Gateway token, and
  atomically writes one root-managed SecretRef payload. It rejects symlinks,
  loose source permissions, duplicate keys, unexpected bytes, and unsafe
  output directories. Its output contains only status and change state.
- `test_openclaw_isolated_secrets.py` covers exact-key parsing, duplicate and
  whitespace rejection, source permissions, atomic permissions, idempotency,
  provider-key replacement, and Gateway-token preservation.

## Validation

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/agents -p 'test_*.py' -v
black --check scripts/agents
```
