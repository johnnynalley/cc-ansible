# OpenClaw Runtime Security

## Current State

The live OpenClaw Gateway on `jn-t14s-lin` still runs as the human/controller
account `johnny`. That account has sudo, Docker, automation credentials, and
write access to active OpenClaw behavior. Model instructions, persona prompts,
and output filters do not make that a security boundary. Until the Gateway is
moved to a dedicated OS identity, prompt injection or a Gateway compromise can
become a controller and homelab compromise.

The first deterministic boundary is implemented but deliberately disabled:

- `playbooks/agents/openclaw-health-receiver.yml` stages and migrates Apple
  Health ingestion to the no-login `openclaw-health` service account.
- `scripts/agents/health-receiver.py` accepts bounded authenticated JSON and
  stores raw records in an isolated SQLite database.
- `scripts/agents/health-summary.py` publishes only fixed daily aggregates.
- The future `openclaw` Gateway identity will receive membership only in
  `openclaw-health-report`, which can read generated reports but cannot read the
  database, token, receiver configuration, or raw payloads.

No live service, user, listener, credential, or database has been changed by
this implementation. The inventory mode remains `disabled` until an attended
canary and cutover are approved.

## Required Trust Boundaries

The final deployment must keep these principals separate:

| Principal | May access | Must not access |
| --- | --- | --- |
| `openclaw` | Root-deployed behavior, its own writable runtime state, aggregate Health and Docker reports, explicitly scoped tools | sudo, Docker socket/group, human home, Ansible vault/SSH/Git credentials, raw Health data, active source writes |
| `openclaw-health` | Health token, receiver configuration, raw Health SQLite database, aggregate report output | OpenClaw sessions/tools, Docker, sudo, controller credentials, network destinations other than its listener |
| `openclaw-health-report` | Generated `yesterday.json` and `yesterday.md` only | Token, database, row-level records, source-device names, write access |
| Docker reporter accounts | One fresh, redacted report through a forced SSH command | Docker socket, arbitrary SSH commands, environment/mount/log data, updates |
| Docker update broker | One immutable approved plan at a time | Free-form Compose paths, image names, arguments, or self-approval by Astra |

An output or prompt rule is defense in depth. The OS identity, filesystem
ownership, fixed command schema, and independent approval path are the actual
controls.

## Health Receiver Design

The receiver is not an OpenClaw tool and never delivers text to a model. It
enforces:

- a token of at least 32 bytes, loaded only from a protected file;
- one `/health` path and `application/json` request bodies;
- literal source-IP allowlisting, body and rate limits, and no chunked input;
- bounded JSON depth, node count, collection size, and string size;
- object/array and finite-number validation before one atomic SQLite
  transaction;
- duplicate row hashes with `INSERT OR IGNORE`;
- generic client errors and no request-body logging.

The summary publisher opens SQLite in read-only/query-only mode. Its output
contains aggregate metrics, duplicate factors, workouts, sleep totals, and
sanity warnings. It excludes `raw_json`, row-level values, source/device names,
database paths, and credentials. Reports are atomically replaced at mode
`0640` under the aggregate-reader group.

## Migration Modes

`inventory/host_vars/jn-t14s-lin/openclaw.yml` keeps the migration mode and
cutover gates.

### Disabled

`openclaw_health_receiver_mode: disabled` is the normal current state. A full
site run does not create the new users, copy the token/database, or touch the
legacy user service. If a previously deployed isolated unit exists, disabled
mode stops it without modifying the legacy receiver.

### Canary

An owner-approved canary temporarily uses:

- loopback `127.0.0.1:19791`;
- a protected byte-for-byte copy of the current token;
- a consistent SQLite `.backup` of the current database;
- the hardened system service and aggregate summary publisher.

The playbook requires existing mode-`0600` token input and a nonempty legacy
database. It validates the canary with a helper that reads the token from disk,
so the secret never enters arguments, Ansible output, or the service
environment. Canary mode leaves the current production listener untouched and
does not enable the new receiver at boot.

### Production Cutover

First production activation requires all three settings in the attended run:

```yaml
openclaw_health_receiver_mode: production
openclaw_health_receiver_cutover_requested: true
openclaw_health_receiver_cutover_approved: true
```

The playbook then:

1. Creates a root-only timestamped backup of the legacy unit, nonsecret
   environment, token, and a consistent SQLite database copy.
2. Stops both receiver processes before the final SQLite backup.
3. Atomically promotes the final database under `openclaw-health` ownership.
4. Starts the production system service on `100.73.46.86:18791`.
5. Performs an authenticated result-only check and requires retained metrics.
6. Disables the old user unit and writes a root-owned completion marker.

If any cutover task or validation fails, the isolated service is stopped and
the legacy user service is restarted. After success, set both one-time cutover
booleans back to `false`; subsequent `production` runs require the completion
marker and converge the stable service normally.

The iPhone Health Auto Export client still needs the current rotated token and
a real post-rotation export. Server health alone does not prove that client
path is restored.

## Gateway Migration Gate

Do not deploy the Docker reporter or claim the security work complete until a
parallel Gateway canary proves all of the following:

- the service runs as `openclaw` with no supplementary privilege groups;
- `/home/johnny`, Docker sockets, controller SSH keys, vault password, Git
  credentials, and human environment files are inaccessible;
- generic host execution is denied by default;
- active instructions, skills, plugins, hooks, and collectors are root-owned
  and read-only to the Gateway;
- writable memory/project facts cannot promote themselves into behavior;
- session visibility and agent-to-agent delivery are scoped;
- Discord routes have explicit sender authorization;
- idle Rigel heartbeats remain silent without output-token filters;
- aggregate Health reports remain readable while the raw database and token do
  not.

The current `dbc` account is not a replacement for this boundary. Its arbitrary
Ansible dry-run arguments, writable Compose/Caddy inputs, and broad sudo rules
require separate removal or redesign.

## Validation

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/agents -p 'test_health_*.py' -v
black --check scripts/agents
ansible-playbook playbooks/agents/openclaw-health-receiver.yml --syntax-check
ansible-playbook playbooks/agents/openclaw-health-receiver.yml --check --diff
scripts/repo/repo-audit
```

The default dry run must end after the disabled path with zero changes. Canary
and production are live-state operations and require the backup/approval
discipline above; do not test those modes casually through `site.yml`.
