# OpenClaw Runtime Security

## Current State

The live OpenClaw Gateway on `jn-t14s-lin` still runs as the human/controller
account `johnny`. That account has sudo, Docker, automation credentials, and
write access to active OpenClaw behavior. Model instructions, persona prompts,
and output filters do not make that a security boundary. Until the Gateway is
moved to a dedicated OS identity, prompt injection or a Gateway compromise can
become a controller and homelab compromise.

The first deterministic boundaries are implemented. Production cutover remains
disabled, while the attended Gateway canary is currently active only on
loopback and remains disabled at boot:

- `playbooks/agents/openclaw-health-receiver.yml` stages and migrates Apple
  Health ingestion to the no-login `openclaw-health` service account.
- `scripts/agents/health-receiver.py` accepts bounded authenticated JSON and
  stores raw records in an isolated SQLite database.
- `scripts/agents/health-summary.py` publishes only fixed daily aggregates.
- `playbooks/agents/openclaw-isolated-gateway.yml` stages a parallel system
  service under the no-login `openclaw` account without stopping production.
  A credential-less ephemeral build account resolves the current stable core
  plus the Codex, Discord, Lossless Claw, and Mem0 plugins inside a transient
  systemd sandbox with package lifecycle scripts disabled, sensitive paths
  inaccessible, and private/Tailscale network ranges denied. Root promotes the
  validated set into one versioned release and selects it through
  `/opt/openclaw-isolated/current`.
- `playbooks/agents/openclaw-state-rehearsal.yml` creates no Gateway and loads
  no channel or provider credential. It copies only the five active
  file-backed session trees and their exact structured workspace dependencies
  into a timestamped root-owned rehearsal generation, verifies path and hash
  parity, freezes the result read-only, and promotes only rehearsal selectors.
- `playbooks/agents/openclaw-doctor-rehearsal.yml` consumes that verified
  session generation, takes online SQLite backups of authoritative shared,
  per-agent, Lossless Claw, and Mem0 history stores, and scrubs copied provider
  auth. It disables channels and network access, retires all classified legacy
  plugin install records through the supported CLI, restores retained plugins
  from the immutable release, and requires two successful idempotent Doctor
  passes before promoting rehearsal-only selectors.
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
registry with zero diagnostics. The corrected bootstrap completed on
2026-08-10 with the stable `2026.7.1-2` core and `2026.7.1-1` Codex provider.
The temporary canary is active only on `127.0.0.1` and `::1` port `19789`, is
disabled at boot, and has no channels. The `johnny` production Gateway remains
unchanged on port `18789`; no production channel token is active in the
canary. Fresh device-code model authorization and the fixed model-response
proof remain pending. Inventory defaults to `disabled` outside attended
bootstrap, canary, and cutover work.

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
They are replaced or retired. Codex, Discord, Lossless Claw, and Mem0 are
retained capabilities but their service-writable npm installations are replaced
by root-managed current-channel artifacts. Brave, Nextcloud Talk, Perplexity,
and the former self-evolution gate are retired because they are disabled or no
longer configured as live channels. A persisted plugin install record is part
of the legacy runtime mechanism, not user data: the migration removes it through
the supported plugin CLI before rebuilding the registry from reviewed explicit
load paths. Plugin state, Lossless Claw history, and Mem0 history are separate
data and remain migration inputs. Stable-channel policy is retained, while each
resolved core/plugin set is recorded as one immutable deployment artifact for
rollback. Other agents, integrations, schedules, stores, and workspace
artifacts remain subject to the same classification before production cutover.

Stable `2026.7.1-2` is a hybrid runtime, not a completely database-first one.
The shared SQLite database is authoritative for cron, tasks, plugin state,
pairing, audit, and other control-plane records. Per-agent SQLite databases
currently hold auth and memory/index state, but the shipped schema has no
`sessions`, `session_entries`, or `transcript_events` tables. Active session
metadata still lives in per-agent `sessions.json`, and transcripts and
trajectories still live in JSONL files. The bundled
`refactor/database-first.md` describes an intended refactor state that is ahead
of the installed implementation and is not a migration contract by itself.

Doctor remains the supported owner for the legacy moves and repairs it actually
implements, including old root-level session layouts and cron JSON imports. Its
`migration_runs` and `migration_sources` ledger is not universal in this
release: the inspected production database has zero rows in both tables even
though all five active agents have valid, live file-backed session stores. The
target migration must therefore preserve each current store according to its
shipped owner, rewrite only deterministic state-root path references on a
protected copy, and reconcile file counts, hashes, metadata rows, sampled
history reads, and database rows independently.

`scripts/agents/openclaw-session-relocate.py` enforces that file-backed
boundary. Its 2026-08-10 source manifest found five agents, 154 metadata
entries, 28,770 artifacts totaling 2.50 GB, and 1,391 absolute references in
five approved structured fields. Every reference exists and resolves inside
the source state/workspace roots. Relocation rewrites only those fields,
requires target references to resolve inside the dedicated roots, and verifies
that every non-index session artifact remains byte-identical.

The attended rehearsal generation `20260810T083108Z` passed this boundary and
was promoted only through rehearsal selectors. Its immutable verification
record reports five agents, 154 metadata entries, 28,770 artifacts, and 1,391
rewritten references. The promoted trees are owned by
`root:openclaw-migrate`, are not writable by the migration reader or other
users, and remain readable by the no-login migration identity. The production
user Gateway and its session sources were not stopped or modified. This passes
the active file-backed session relocation lane; it does not pass the separate
Doctor, database, behavior, integration, credential, or production-cutover
lanes.

Migration combines an OpenClaw `backup create --verify` archive for supported
SQLite-native snapshots with a separate stopped-state archive that preserves
all file-backed history and any artifacts the product backup intentionally
classifies as volatile. Run Doctor only against a protected writable rehearsal
copy with channels disabled because successful repairs can move, rewrite,
archive, or remove their source files. Keep production sources unchanged until
the rehearsal and stopped-state archive both pass.

In stable `2026.7.1-2`, `openclaw backup create --dry-run` is not a strictly
read-only probe. CLI initialization opens the state database, applies
best-effort permission hardening to the database paths, and may persist config
health observations before the backup planner returns its dry-run result. Run
it only inside the same backed-up, attended state-transition boundary as a real
backup. A read-only filesystem copy can be used for planning, but its expected
write failures must remain internal diagnostics rather than operator alerts.

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
explicit read-denial probes before it resolves `openclaw@latest` and the
reviewed managed plugin set from their `latest` channels with lifecycle scripts
disabled. The playbook verifies package and manifest identities, requires
matching core builds for official Codex and Discord releases, and stages the
complete set under
`/opt/openclaw-isolated/releases`, and atomically promotes it. Root ownership
prevents the Gateway from changing executable code. The old global-prefix
`bin` and `lib` layout and writable provider cache are removed after the
rollback artifact exists. If the stopped canary still has an OpenClaw-managed
Codex package, the playbook uses a service-owned temporary copy of the old
config and `plugins uninstall codex --force --keep-files` to remove only its
persisted install record. It then removes the old package tree, deploys the
root-managed config, runs `plugins registry --refresh`, and rejects a derived,
warning-bearing, duplicate, disabled, or dependency-incomplete provider
inventory. Because OpenClaw may report either the `current` symlink spelling or
its selected release target, validation compares canonical paths and separately
requires that target to be the exact promoted versioned release. The managed set
and retired set are fixed policy inputs; overlap, duplicates, exact-version
policy pins, or unreviewed plugin additions fail before package resolution.

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
mutation begins. `canary-bootstrap` validates the managed release set,
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

### Session-State Rehearsal

`openclaw_state_rehearsal_mode: disabled` is inert. An attended `sessions` run
also requires `openclaw_state_rehearsal_approved: true`. It does not stop,
restart, reconfigure, or authenticate the production Gateway.

The rehearsal is deliberately selective rather than a legacy workspace clone:

1. Manifest all five active `sessions.json` and JSONL trees before copying.
2. Copy those stores plus only workspace files/directories referenced by the
   approved structured session fields.
3. Manifest production again and require exact equality, proving the live
   source did not change during capture, then preserve the copied source
   indexes as immutable pre-transform evidence.
4. Rewrite only the approved state/workspace prefixes on the protected copy.
5. Verify against the immutable capture manifest and index snapshots rather
   than re-reading a moving live source. Require byte-identical non-index
   artifacts, semantic index equality, valid target references, and an
   `agents`-only target state root.
6. Keep config, credentials, plugin code/state, channels, and the unreferenced
   legacy workspace out of this generation.
7. Transfer the validated tree to root ownership with read-only access for the
   no-login `openclaw-migrate` group, then atomically update rehearsal-only
   `current` symlinks.

Failed generations are never promoted. Timestamped manifests, verification
reports, rollback metadata, and the modernization disposition are kept under
`/var/backups/openclaw-migration-rehearsal`. This proves file-store relocation;
it does not classify or activate the remaining behavior, database, plugin,
integration, or credential lanes.

### Doctor Modernization Rehearsal

`openclaw_doctor_rehearsal_mode: disabled` is inert. An attended `doctor` run
also requires `openclaw_doctor_rehearsal_approved: true`. It creates no Gateway,
loads no provider or channel credential, and cannot read the production state
as its no-login migration identity.

The run is a modernization gate rather than a legacy clone:

1. Consume only the promoted session/workspace rehearsal and current immutable
   OpenClaw/plugin release.
2. Take consistent online SQLite backups of the shared database, each active
   per-agent database, Lossless Claw, and Mem0 history. Delete copied per-agent
   auth rows while retaining memory and index state.
3. Transform a copied config to dedicated roots, redact secret values, disable
   channels and updates, and reject surviving production path references.
4. Require the exact eight classified legacy plugin install records, retire
   each through `plugins uninstall --keep-files --force`, then regenerate the
   sanitized config and refresh the registry from four root-managed immutable
   plugin paths.
5. Run Doctor twice inside a transient `PrivateNetwork` systemd sandbox with
   the human home, Docker socket, and controller checkout inaccessible.
6. Compare data-free filesystem manifests and stable SQLite table digests.
   Only a reviewed list of known volatile shared control-plane tables is
   excluded from the stable comparison; an unknown exclusion fails closed.
7. Promote root-owned rehearsal selectors only after both passes and
   error-level lint succeed, then prove the production config checksum and user
   Gateway state are unchanged.

Root-only evidence and the rollback artifact live under
`/var/backups/openclaw-doctor-rehearsal/<timestamp>`. A successful result proves
the supported database/plugin modernization lane only. It does not authorize
fresh OAuth, Discord/channel activation, behavior parity, or production
cutover.

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
- the core/plugin set was built without service credentials or lifecycle
  scripts, loads only from the selected root-managed release, and does not
  regenerate writable plugin code;
- writable memory/project facts cannot promote themselves into behavior;
- session visibility and agent-to-agent delivery are scoped;
- Discord routes have explicit sender authorization;
- idle Rigel heartbeats remain silent without output-token filters;
- aggregate Health reports remain readable while the raw database and token do
  not;
- a copy-only Doctor rehearsal validates each migration it actually owns, while
  the separately manifested per-agent file-backed session stores relocate with
  count/hash parity and readable sampled history.

The current `dbc` account is not a replacement for this boundary. Its arbitrary
Ansible dry-run arguments, writable Compose/Caddy inputs, and broad sudo rules
require separate removal or redesign.

## Validation

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/agents -p 'test_health_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest scripts/agents/test_openclaw_isolated_secrets.py -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest scripts/agents/test_openclaw_session_relocate.py -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest scripts/agents/test_openclaw_doctor_rehearsal.py -v
black --check scripts/agents
ansible-playbook playbooks/agents/openclaw-health-receiver.yml --syntax-check
ansible-playbook playbooks/agents/openclaw-health-receiver.yml --check --diff
ansible-playbook playbooks/agents/openclaw-isolated-gateway.yml --syntax-check
ansible-playbook playbooks/agents/openclaw-isolated-gateway.yml --check --diff
ansible-playbook playbooks/agents/openclaw-isolated-gateway.yml --check --diff -e openclaw_isolated_gateway_mode=canary-bootstrap -e openclaw_isolated_gateway_canary_approved=true
ansible-playbook playbooks/agents/openclaw-state-rehearsal.yml --syntax-check
ansible-playbook playbooks/agents/openclaw-state-rehearsal.yml --check --diff
ansible-playbook playbooks/agents/openclaw-state-rehearsal.yml --check --diff -e openclaw_state_rehearsal_mode=sessions -e openclaw_state_rehearsal_approved=true
ansible-playbook playbooks/agents/openclaw-doctor-rehearsal.yml --syntax-check
ansible-playbook playbooks/agents/openclaw-doctor-rehearsal.yml --check --diff
ansible-playbook playbooks/agents/openclaw-doctor-rehearsal.yml --check --diff -e openclaw_doctor_rehearsal_mode=doctor -e openclaw_doctor_rehearsal_approved=true
scripts/repo/repo-audit
```

The default dry run must end after the disabled path with zero changes. Canary
and production are live-state operations and require the backup/approval
discipline above; do not test those modes casually through `site.yml`.
