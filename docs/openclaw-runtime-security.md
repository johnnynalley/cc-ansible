# OpenClaw Runtime Security

## Current State

The live OpenClaw Gateway on `jn-t14s-lin` still runs as the human/controller
account `johnny`. That account has sudo, Docker, automation credentials, and
write access to active OpenClaw behavior. Model instructions, persona prompts,
and output filters do not make that a security boundary. Until the Gateway is
moved to a dedicated OS identity, prompt injection or a Gateway compromise can
become a controller and homelab compromise.

The first deterministic boundaries are implemented but deliberately disabled:

- `playbooks/agents/openclaw-health-receiver.yml` stages and migrates Apple
  Health ingestion to the no-login `openclaw-health` service account.
- `scripts/agents/health-receiver.py` accepts bounded authenticated JSON and
  stores raw records in an isolated SQLite database.
- `scripts/agents/health-summary.py` publishes only fixed daily aggregates.
- `playbooks/agents/openclaw-isolated-gateway.yml` stages a parallel system
  service under the no-login `openclaw` account without stopping production.
  A credential-less ephemeral build account resolves the current stable core
  and Codex provider inside a transient systemd sandbox with package lifecycle
  scripts disabled, sensitive paths inaccessible, and private/Tailscale network
  ranges denied. Root promotes the validated pair into a versioned release and
  selects it through `/opt/openclaw-isolated/current`.
- `templates/openclaw/openclaw-isolated.json.j2` starts from a blank config:
  one OpenAI model, an explicitly loaded root-managed Codex provider, a
  file-backed Gateway token, no channel, heartbeat, memory, delegation,
  filesystem, web, messaging, or execution surfaces. Provider prompt hooks,
  conversation access, computer use, plugin loading, and destructive actions
  are disabled.
- `templates/openclaw/openclaw-isolated-gateway.service.j2` makes the runtime,
  provider, primary config, and workspace root-owned/read-only. The SecretRef
  payload is service-owned mode `0400` because the current file provider
  requires the running UID to own it. Only data under
  `/var/lib/openclaw-isolated` and the exact service-owned `.last-good` config
  backup are writable inside the sandbox; the managed-plugin path inside that
  state tree is a root-owned read-only sentinel.
- The future `openclaw` Gateway identity will receive membership only in
  `openclaw-health-report`, which can read generated reports but cannot read the
  database, token, receiver configuration, or raw payloads.

Two initial attended canary attempts were rolled back automatically on
2026-08-10: the first exposed and fixed the current file-provider ownership
contract, and the second proved that the legacy OpenRouter fallback was
unfunded. A later infrastructure bootstrap passed with a dedicated account and
loopback-only, boot-disabled service. Subsequent modernization runs also failed
closed: one exposed excess builder read access to the controller checkout, and
the next reached provider inventory before detecting a stale SQLite install
record for the retired service-writable Codex tree. Both restored the exact
prior canary state. The builder now runs inside a transient path/network
sandbox. The registry failure was reproduced against a copied state database:
OpenClaw retained the legacy global install record after its package tree was
removed, so it reported a duplicate alongside the explicit root-managed
provider. The managed migration now retires that record through OpenClaw's
supported keep-files uninstall, discards the temporary writable config copy,
rebuilds the registry from the root-managed config, and requires a persisted
registry with zero diagnostics. The service is currently stopped, so the
`johnny` production Gateway is the only running Gateway. Production was not
stopped or modified. Inventory remains `disabled` outside attended bootstrap,
canary, and cutover work.

## Modernization Contract

Behavior and data parity do not require legacy mechanism parity. Every
discovered component must receive one explicit disposition:

- **replace** with a current supported mechanism and prove equivalent required
  behavior;
- **retain** because it remains current, intentional, and inside the new trust
  boundary;
- **archive** outside active discovery paths with a manifest and restore proof;
- **retire** because the capability is no longer wanted; or
- **discard** only after proving that the artifact is generated junk with no
  live references.

The runtime layer already applies that rule: human-home global npm state,
root-run package lifecycle scripts, service-writable provider code, copied
OAuth refresh material, and the unfunded OpenRouter fallback are not migrated.
They are replaced or retired. A persisted plugin install record is part of the
legacy runtime mechanism, not user data: the migration removes it through the
supported plugin CLI before rebuilding the registry from the reviewed explicit
load path. Stable-channel policy is retained, while each resolved core/provider
pair is recorded as an immutable deployment artifact for rollback. Other
agents, integrations, schedules, stores, and workspace artifacts remain subject
to the same classification before production cutover.

## Gateway Canary Design

The canary is intentionally not a copy of the current Gateway. Copying the
legacy config or `.env` would transfer Discord, GitHub, Home Assistant, Plex,
Sonarr, Radarr, iCloud, image, and other credentials into the new account and
would reproduce the current authority convergence.

Instead, the playbook creates a no-login `openclaw-build` account only for the
duration of the run. That account receives no service credentials and runs only
inside a transient systemd sandbox. The sandbox makes the human home, vault,
Docker socket, active workspace, canary config/state, controller paths, and bulk
data inaccessible; it denies loopback, private, link-local, and Tailscale CGNAT
ranges while allowing public package endpoints and the local DNS stub. Its
service exit is cgroup-scoped, so package-manager descendants must terminate
before staging cleanup or promotion can continue. The same sandbox must pass
explicit read-denial probes before it resolves
`openclaw@latest` and `@openclaw/codex@latest` with lifecycle scripts disabled.
The playbook then verifies the official package identities and build
compatibility, stages the complete pair under
`/opt/openclaw-isolated/releases`, and atomically promotes it. Root ownership
prevents the Gateway from changing executable code. The old global-prefix
`bin` and `lib` layout and writable provider cache are removed after the
rollback artifact exists. If the stopped canary still has an OpenClaw-managed
Codex package, the playbook uses a service-owned temporary copy of the old
config and `plugins uninstall codex --force --keep-files` to remove only its
persisted install record. It then removes the old package tree, deploys the
root-managed config, runs `plugins registry --refresh`, and rejects a derived,
warning-bearing, duplicate, disabled, or dependency-incomplete provider
inventory.

Only a dedicated Gateway token is generated in
`/etc/openclaw-isolated/secrets.json`. Nothing is imported from the legacy broad
environment. Production uses a current OpenAI OAuth profile whose refresh
material is intentionally nonportable, so the dedicated identity receives a
fresh device-code login rather than a copied token. The unfunded OpenRouter
fallback is not carried into the canary.

The system service adds the effective boundary:

- static no-login `openclaw` user with only its primary group;
- loopback-only port `19789`, disabled Control UI and HTTP compatibility APIs,
  disabled Tailscale/discovery/channels, and token authentication;
- minimal `session_status` tool profile plus explicit denial of runtime,
  filesystem, session, memory, web, UI, automation, messaging, node, agent,
  media, and plugin tools;
- `tools.exec.security=deny`, `ask=always`, elevated mode off, session scope
  `self`, and agent-to-agent delivery off;
- `ProtectHome`, `ProtectSystem=strict`, private devices/temp/IPC, no
  capabilities, no privilege gain, namespace restrictions, and explicit
  inaccessibility for the Docker socket, controller repo, human home, Ansible,
  Docker state, and bulk data mounts;
- pre-start assertions that the process can read but not write its primary
  config or secret, can write its data state and exact `.last-good` file,
  cannot write its release, provider, managed-plugin sentinel, or workspace,
  and cannot read the human home, Docker socket, vault password, or controller
  guidance.

Both live modes require `openclaw_isolated_gateway_canary_approved: true` and
take a root-only targeted backup of prior canary config, state, complete runtime
root, support files, and unit. The stopped-state archive preserves ownership,
ACLs, and extended attributes and must compare cleanly against its source before
mutation begins. `canary-bootstrap` validates the release pair,
explicit provider loading, config, token, listener, systemd properties,
account groups, authenticated health endpoint, and absence of provider
self-installation, then writes `.infrastructure-validated`. It leaves the
loopback-only, boot-disabled service available for a fresh OpenAI device-code
login. It does not claim model parity. After authentication, `canary` repeats
every infrastructure check, requires the fixed-response model probe, and only
then writes `.canary-validated`. Failure stops the canary and restores prior
canary state; the production Gateway is never touched. This playbook
deliberately has no production-cutover mode.

## Required Trust Boundaries

The final deployment must keep these principals separate:

| Principal | May access | Must not access |
| --- | --- | --- |
| `openclaw` | Root-deployed immutable runtime/provider/behavior, its own writable data state, aggregate Health and Docker reports, explicitly scoped tools | sudo, Docker socket/group, human home, Ansible vault/SSH/Git credentials, raw Health data, executable-code writes, active source writes |
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
- the core/provider pair was built without service credentials or lifecycle
  scripts, loads only from the selected root-managed release, and does not
  regenerate writable provider code;
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
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest scripts/agents/test_openclaw_isolated_secrets.py -v
black --check scripts/agents
ansible-playbook playbooks/agents/openclaw-health-receiver.yml --syntax-check
ansible-playbook playbooks/agents/openclaw-health-receiver.yml --check --diff
ansible-playbook playbooks/agents/openclaw-isolated-gateway.yml --syntax-check
ansible-playbook playbooks/agents/openclaw-isolated-gateway.yml --check --diff
ansible-playbook playbooks/agents/openclaw-isolated-gateway.yml --check --diff -e openclaw_isolated_gateway_mode=canary-bootstrap -e openclaw_isolated_gateway_canary_approved=true
scripts/repo/repo-audit
```

The default dry run must end after the disabled path with zero changes. Canary
and production are live-state operations and require the backup/approval
discipline above; do not test those modes casually through `site.yml`.
