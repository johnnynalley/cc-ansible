# Agent Runtime Scripts

## Hermes Replacement

- `hermes-shadow-target-audit.py` validates the structured, credential-free
  Gate 3 target declaration. It fails closed on unknown top-level schema,
  production delivery/scheduling/listeners, pre-gate VM selection, Docker
  group/socket access, local-terminal fallback, host mounts, forwarded secrets,
  unsafe approvals, cross-profile identity reuse, broad Dubble/Rigel authority,
  broker self-approval, or missing backup/rollback controls.
- `test_hermes_shadow_target_audit.py` covers the real policy plus negative
  regressions for those privilege and cutover boundaries.
- `test_hermes_shadow_playbook.py` renders every managed profile config and
  service unit, then rejects host execution, production authority, unreviewed
  installer input, unsafe startup, or a weakened Podman boundary.
- `hermes-rigel-schedule.py` is Rigel's deterministic, script-only academic
  alert evaluator. Expected idle, missing, or malformed source state produces
  no stdout; exact source-backed alerts are deduplicated in profile-local state.
- `test_hermes_rigel_schedule.py` covers empty/missing semesters, source-backed
  alerts, duplicates, malformed state, and restart persistence.
- `hermes-openclaw-migration-audit.py` validates the hashed path-level
  workspace policy and the top-level OpenClaw state contract, then inventories
  only entry names and filesystem kinds. It fails closed on unknown or
  ambiguous categories, kind drift, symlinks, source mutation authority,
  secret copying, active legacy jobs, delivery-queue replay, or an unsafe
  database backup method.
- `test_hermes_openclaw_migration_audit.py` covers policy-hash drift, every
  workspace disposition, Health's external ownership, secret re-enrollment,
  disabled cron reconstruction, queue draining, stopped SQLite backup, unknown
  entries, kind drift, and symlink rejection.
- `hermes-openclaw-dry-run.py` creates an ephemeral shape-only OpenClaw source
  and disposable Hermes target, runs the pinned official importer as the
  no-login migration account with no network and read-only trees, strips all
  item details from retained evidence, and removes the view. Legacy skill
  symlinks are represented only by an anonymous count and are never followed.
  Raw source text, prompts, credentials, sessions, code, and opaque identities
  never enter it.
- `test_hermes_openclaw_dry_run.py` covers contract immutability, source
  placeholders, secret/prompt/code exclusion, ordinary-source symlink
  rejection, anonymous skill-link handling, structural report stripping,
  disabled deployment, and systemd confinement.
- `hermes-profile-import-audit.py` pins the workspace and state contracts,
  validates three distinct profile roots and behavior sources, and requires
  every retained or curated source to have exactly one profile, namespace,
  owner class, import mode, and non-raw exposure. Dubble/Rigel data cannot cross
  profile roots; reviewer memory remains private evidence; ordinary memory
  remains an approval-gated proposal source.
- `test_hermes_profile_import_audit.py` covers complete mapping, duplicate
  targets, owner drift, cross-profile assignment, private reviewer evidence,
  approved memory curation, raw-prompt denial, inert safety controls, state
  mapping completeness, source hash drift, and behavior-source symlinks.
- `hermes-memory-seed-validate.py` validates one root-staged curated memory
  seed with the pinned Hermes parser and native threat scanner. It enforces
  UTF-8, regular non-executable files, clean entry round trips, and Hermes's
  documented compact character limits without printing seed content.
- `test_hermes_profile_memory.py` covers the encrypted curated-source
  contract, profile isolation, intentionally empty Dubble store, compact
  config limits, transactional rollback, exact checksum verification, and
  absence of Gateway activation.
- `hermes-profile-skills-validate.py` validates reviewed declarative profile
  skills with Hermes's pinned native frontmatter parser and threat scanner,
  exact source and installed hashes, exclusive root-owned inventories, and the
  native skill index inside the service's read-only bind namespace.
- `test_hermes_profile_skills.py` covers replacement of legacy phrase-triggered
  skills, semantic descriptions, capability-field exclusions, profile
  isolation, transactional rollback, native service bindings, and absence of
  Gateway activation.
- `hermes-profile-data-stage.py` selects only the reviewed `data-stage` and
  `operator-reference` mappings from pinned source contracts, takes a stable
  no-link snapshot, copies bytes into isolated writable/root-managed profile
  roots, normalizes modes, writes a root-private content manifest, and verifies
  exact managed inventory, safe writable drift, and runtime bind identity plus
  read/write mount flags. It never mounts or mutates the OpenClaw source.
- `test_hermes_profile_data_stage.py` covers selection boundaries, source-pin
  and source-race rejection, executable-bit removal, manifest and root-shape
  drift, managed immutability, bounded writable drift, runtime identity and
  mount modes, transaction cleanup, rollback, and absence of Gateway starts.
- `test_hermes_behavior_contract.py` validates semantic routing without phrase
  triggers, one concise user-facing answer, native background review with
  staged memory/skill approval, owner-only policy changes, complete sanitized
  promotion cases, non-symlink profile policies, and control-token exclusion.
- `test_hermes_star_contract.py` validates two independent parallel leaf
  reviewers, distinct corroboration/challenge roles, bounded inherited
  authority, no exact model pin, complete-review requirements, one normal
  private synthesis, MoA's documented role-prompt gap, and six sanitized
  promotion cases.
- `hermes-discord-cutover-audit.py` validates the credential-free Discord
  handoff contract. It pins the source shadow, migration, and delivery-audit
  assets; requires three distinct profile/application/token references; keeps
  unknown DMs, bot input, backfill, replay, and allow-all access disabled; and
  enforces stopped-source-before-target and stopped-target-before-rollback
  ordering while the Health receiver remains online.
- `test_hermes_discord_cutover_audit.py` covers authority drift, shared
  identities or homes, pairing and bot loops, replay/backfill, source ordering,
  Health continuity, rollback ordering, source-hash drift, redacted output,
  and all 12 sanitized Discord promotion cases.
- `hermes-automation-contract-audit.py` validates all 28 current cron jobs and
  three heartbeat lanes against their agent-backed, external, or no-agent
  owners. With `--source-inventory`, it fails on new jobs, recurring-job
  absence, schedule drift, or unsafe one-shot state while allowing already
  expired delete-after-run reminders to remain absent.
- `test_hermes_automation_contract_audit.py` covers schedule-set and authority
  drift, command/Gateway separation, no direct scheduled Discord delivery,
  fresh source reconciliation, one-shot expiry, Health/Siri boundaries, and
  aggregate-only audit output.

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

- `openclaw-access-check` is the argument-only filesystem access predicate used
  by isolated service preflights and host-namespace security gates. It accepts
  only `[!] -r|-w|-x PATH` and uses Bash's effective supplementary-group
  semantics; the host's uutils `/usr/bin/test` can otherwise return false
  denials for paths granted through `openclaw-workspace`.
- `openclaw-bootstrap-audit.py` validates the repo-owned modern Astra/Fleet
  bootstrap bundle without importing or initializing OpenClaw. It requires the
  exact role layout, native structured heartbeat outcomes, semantic routing and
  review invariants, and bounded per-role/aggregate prompt sizes. It rejects
  legacy human-home paths, opaque platform IDs, control tokens, generic starter
  files, hardcoded session routes, transcript polling, symlinks, hardlinks,
  executable prompt files, and unknown additions.
- `test_openclaw_bootstrap_audit.py` runs the real bundle plus negative
  regressions for legacy paths, opaque IDs, heartbeat token leakage, Dubble
  polling, missing native heartbeat outcomes, and unknown links.
- `openclaw-control-plane-inventory.py` reads the live SQLite control plane in
  query-only mode and emits a migration inventory for cron ownership, schedule,
  one-shot timing, delete-after-run state, execution class, and delivery shape.
  It fingerprints job IDs and omits prompts, raw arguments,
  recipient/account IDs, and error text.
- `test_openclaw_control_plane_inventory.py` proves secret-like arguments,
  recipient/account IDs, raw job IDs, and one-shot payload text cannot enter
  the inventory output; it also verifies lifecycle metadata and unknown-schema
  rejection.
- `openclaw-config-inventory.py` inventories agent, heartbeat, binding,
  Discord-account, plugin-slot, hook, model-runtime, global/per-agent subagent
  routing, and Gateway policy shape without emitting credentials, identity
  text, sender/guild/channel IDs, peer IDs, or trusted-proxy addresses. Unknown
  policy keys are surfaced by name so every legacy surface can be classified
  before cutover. Reporting subagent policy separately is required because a
  global spawn-model override can silently defeat a target agent's own model.
- `test_openclaw_config_inventory.py` proves plaintext and SecretRef values,
  identity text, and opaque Discord IDs remain absent, and malformed or
  symlinked source configurations fail closed.
- `openclaw-modern-config-audit.py` validates a rendered production target
  without importing OpenClaw. It rejects retired providers/plugins and
  human-home paths, plaintext credentials, stale bindings, a global subagent
  model override, broad Rigel authority, noisy or bounded-hours Rigel
  heartbeats, non-loopback Gateway exposure, legacy/full exec policy, mutable
  runtime controls, and unsupported Mem0/Lossless provider drift.
- `openclaw-provider-auth-boundary-audit.py` proves OpenAI authentication is
  absent from Gateway config and per-agent state while the separate Codex
  executor owns one nonempty mode-0600 auth file. It reports only metadata and
  row counts, never credential values.
- `test_openclaw_modern_config_audit.py` renders the real Jinja template with
  synthetic identifiers and covers the promotion contract plus negative
  regressions for credentials, routing, model ownership, heartbeat isolation,
  exec policy, compatibility providers, and binding precedence.
- `openclaw-workspace-inventory.py` applies the reviewed modernization policy
  to a legacy workspace without reading file contents or following symlinks.
  It fails on unknown paths, special files, ambiguous rules, retained
  credential-like paths without an explicit sensitivity classification, and
  retained targets with conflicting ownership classes.
- `test_openclaw_workspace_inventory.py` covers specific-rule precedence,
  unknown-path rejection, sensitive retained data, authorization-policy
  exceptions, non-followed symlinks, and invalid target declarations.
- `openclaw-workspace-stage.py` builds a fresh workspace generation from only
  policy-classified retained data plus the repo-owned modern behavior overlay.
  It rejects retained symlinks/special files, ambiguous glob remaps, nonempty
  targets, file/parent collisions, and source drift; hashes copied bytes and
  normalizes files to non-executable executor-writable or operator-read-only
  ownership classes. The workspace root and behavior remain root-owned;
  mutable project-data subtrees are owned by the no-login `openclaw` runtime
  UID. A dedicated
  `openclaw-workspace` group gives both services read/traverse access without
  exposing either service's private config, credentials, or state.
- `test_openclaw_workspace_stage.py` covers retained/remapped data, modern
  overlay replacement, byte manifests, normalized modes, collision rejection,
  retained-symlink rejection, nonempty-target rejection, and ambiguous glob
  mapping rejection.
- `openclaw-workspace-manifest-parity.py` compares two protected workspace
  manifests without emitting retained paths. It permits content and byte drift
  only for files already classified as retained executor-writable data, while
  rejecting path-set, source mapping, owner-class, modern-overlay,
  operator-read-only, structural-summary, and archive-contract drift.
- `test_openclaw_workspace_manifest_parity.py` covers exact parity, approved
  mutable data drift, immutable overlay rejection, path-set rejection,
  malformed summaries, and symlink rejection.
- `openclaw-star-gateway-rehearsal.py` starts the Star canary through the
  persistent Gateway RPC with one-shot Codex cleanup disabled, requires the
  initial turn to end only through `sessions_yield`, then waits for the pushed
  requester follow-up and writes exactly one private final payload only after
  all canary runs are idle. This exercises the same multi-turn completion
  topology as a channel request instead of mistaking a yielded CLI turn for a
  finished answer.
- `test_openclaw_star_gateway_rehearsal.py` rejects premature visible output,
  incomplete session inventories, multiple final answers, and missing pushed
  follow-ups while proving the persistent cleanup boundary.

- `openclaw-isolated-secrets.py` preserves or generates the canary Gateway and
  Codex app-server capability tokens, then atomically writes owner-read-only
  copies in separate root-owned Gateway and executor configuration directories.
  The Gateway JSON contains only both required tokens; the executor sees only
  its matching capability-token file. Missing copies are reconstructed, token
  disagreement fails closed, and no legacy provider or application credential
  is imported. It rejects symlinks and unsafe output directories, and its
  output contains only status and change state.
- `test_openclaw_isolated_secrets.py` covers atomic permissions, idempotency,
  unexpected-field removal, parent ownership, Gateway-token preservation, and
  the required helper CLI contract across every managed playbook consumer.
- `test_openclaw_doctor_rehearsal.py` rejects the retired embedded-plugin
  release layout and requires Doctor to source exact package and manifest
  identities from the frozen native OpenClaw plugin store.
- `test_openclaw_isolated_gateway_playbook.py` enforces immutable release
  ownership convergence, non-following recursive permission changes, targeted
  local rollback before package work, native integrity-bearing plugin installs
  without config path injection, post-start runtime trust, a service-identity
  CLI probe, native static/deep security-audit ordering, the silent five-agent
  session topology, and a real canary restart rather than an
  already-running-process check.
- `openclaw-session-relocate.py` inventories the shipped file-backed session
  stores, classifies approved absolute references by exact schema role,
  rewrites state paths and spawned workspace directories on a copied target,
  and can discard derived prompt/skill snapshots for native rebuilding from the
  modern bootstrap. Its active-state modernization follows OpenClaw's native
  provenance boundary: automatic model/auth fallback state and generated prompt
  state are cleared, explicit user model and display preferences are retained,
  and user auth or session execution authority blocks migration for review.
  An explicit rehearsal-only delivery quarantine removes pending-final and
  restart-recovery intent from active copied rows, records each removed field,
  and leaves immutable source indexes untouched so a canary cannot replay a
  production response.
  Verification requires JSONL byte parity and models only those approved index
  transformations. It rejects missing paths, symlink escapes, unknown
  path-bearing fields, and unapproved target drift.
- `test_openclaw_session_relocate.py` covers deterministic relocation,
  idempotency, byte preservation, schema-role enforcement, derived-cache
  modernization, delivery-recovery quarantine, unknown-field rejection,
  path-boundary enforcement, and target drift detection.
- `openclaw-delivery-cutover-audit.py` is the stopped-state, metadata-only
  single-Gateway cutover gate. It requires the current delivery-queue schema,
  treats only failed rows as non-replayable history, blocks pending database
  rows and active session recovery fields, rejects unknown statuses, and never
  emits message, target, account, channel, session-key, or entry content.
- `test_openclaw_delivery_cutover_audit.py` covers clean failed history,
  pending database and session blockers, unknown schema/status rejection,
  symlink rejection, redaction, private report permissions, and gate exit
  behavior.
- `openclaw-session-transition.py` consumes a complete native `sessions.list`
  response, keeps durable main/channel routes and native
  `agent:<agent>:main:heartbeat` sessions, plans archive actions only for
  structurally identified synthetic or completed execution rows, retains
  dormant statusless runtime sessions with a real session identity, and fails
  on active work, unknown agents, malformed shapes, pagination, or duplicate
  keys.
  Exact session keys are written only to its mode-0600 plan; normal output is
  aggregate-only.
- `test_openclaw_session_transition.py` covers durable-route retention,
  synthetic archival, active/unknown fail-closed behavior, complete-list
  enforcement, clean post-transition verification, redaction, and plan modes.
- `openclaw-native-session-transition.py` calls `sessions.list` and
  `sessions.patch` through the running loopback canary as its no-login service
  identity. It never passes a Gateway token or password in arguments. Exact
  session keys are persisted only in fresh mode-`0600` evidence and supplied
  transiently to the local native RPC CLI for `sessions.patch`; normal output
  and logs remain aggregate-only. It archives only actions approved by
  `openclaw-session-transition.py`, can explicitly restore only exact configured
  `agent:<agent>:main:heartbeat` keys, and re-lists to prove convergence after
  restore/apply modes. An optional exact required-archive-key set makes
  synthetic cleanup fail before patching if any expected key is missing or any
  unexpected session would be archived.
- `test_openclaw_native_session_transition.py` covers read-only planning,
  private evidence, exact native-heartbeat restoration, native archive
  convergence, active-work rejection, and evidence-directory reuse rejection.
- `test_openclaw_canary_data_rehearsal.py` enforces candidate-before-stop
  ordering, targeted rollback before promotion, hash-verified relocation,
  delivery-recovery quarantine, native service-identity transition, silent
  canary controls, capacity accounting, and rescue restoration without any
  production Gateway service action.
- `openclaw-behavior-audit.py` validates private canary evidence for all five
  agents. It requires exact Dubble output, one Vega and one Antares child with
  native parent/depth/model provenance, verbatim Vega evidence passed to
  Antares, one concise user-facing Star answer, and a new Rigel heartbeat whose
  transcript and structured event prove either native `ok-token` with
  `notify=false` or native `ok-empty`, with no visible text, tool error, or
  delivery target. Provider-facing tool checks account for Codex-native
  filesystem access that is not projected as OpenClaw `read`; non-Codex
  reviewers must still expose the configured OpenClaw read tool. Normal output
  is aggregate-only, and failures emit fixed non-content reason codes.
- `openclaw-heartbeat-event-check.py` waits through the immutable native CLI for
  one fresh scheduled `ok-token` or `ok-empty` event. It rejects delivery routes,
  visible control/reasoning/error previews, failed/sent outcomes, malformed
  timing, and non-scheduled events before returning the private event JSON. The
  live start must be a plausible Unix-millisecond value; timeout output contains
  only query count and the last event's timestamp/status/reason, never preview
  text or route metadata.
- `test_openclaw_heartbeat_event_check.py` covers both native idle-success
  branches, stale/skipped waits, route and status rejection, preview rejection,
  and immutable executable selection.
- `test_openclaw_behavior_audit.py` covers the complete success path plus
  missing reviewer evidence, wrong lineage, internal narration, dangerous tool
  exposure, noisy heartbeat outcomes, visible control tokens, and transcript
  path escapes.
- `test_openclaw_behavior_rehearsal.py` enforces the applied-data prerequisite,
  inert plan boundary, backup-before-model ordering, channel/cron/boot
  suppression, native Star/Rigel evidence gates, baseline restoration,
  synthetic-session archival, delivery parity, production-listener parity,
  and rescue restoration.
- `openclaw-session-relocate.py verify-artifacts` performs the post-archive
  preservation gate. It permits OpenClaw-owned session-index updates
  while requiring the complete non-index transcript and trajectory artifact
  set, byte counts, hashes, and replay-safe delivery state to remain unchanged.
- `openclaw-security-rehearsal-audit.py` validates one fixed hostile-prompt
  trajectory. It accepts only the six approved shell probes, correlates calls
  and results, requires the `openclaw` identity inside the Codex service,
  proves denied sudo, Gateway-secret, Docker-socket, and outside-workspace
  access, verifies the one allowed workspace write, and rejects secret bytes
  in trajectory or saved model output.
- `test_openclaw_security_rehearsal_audit.py` covers exact command/result
  correlation, Codex shell-wrapper parsing, path/symlink boundaries, identity
  and denial failures, unexpected tools, and secret leakage.
- `openclaw-security-session-cleanup.py` compares a private pre-run session
  index with current canary state, accepts exactly one new
  `agent:main:explicit:security-*` session, and archives/removes only that
  transcript and its trajectory artifacts for rescue recovery.
- `test_openclaw_security_session_cleanup.py` covers exact-session cleanup,
  transcript-basename trajectory resolution, dry-run behavior, unexpected
  sessions, and path/symlink rejection.
- `test_openclaw_security_rehearsal.py` enforces the disabled/approval gates,
  applied silent-data prerequisite, backup-before-probe ordering, split-service
  and cross-secret boundaries, fixed prompt and trajectory proof, exact native
  session archival, listener/boot parity, and rescue restoration.
- `openclaw-rehearsal-retention.py` bounds state and Doctor rehearsal copies to
  the selected generation plus the exact generation referenced by its current
  rollback archive. Its root-only two-phase plan/apply flow rejects partial
  retained sets, extra selectors, symlink or mount escapes, unknown owners,
  unknown groups, world-writable content, active migration-identity processes,
  unsafe rollback targets, and metadata drift. Trusted group-writable content
  from failed/pre-hardening generations is recorded and can be removed only
  while the dedicated migration identity is quiescent; retained generation
  roots must still be root-owned. Superseded generation payloads are removed
  only through a platform-confirmed symlink-attack-resistant tree operation,
  while their separate evidence directories remain available for the migration
  audit. Doctor runs repeat the gate after successful selector promotion so the
  payload set ends at current plus immediate rollback rather than waiting for a
  later run.
- `test_openclaw_rehearsal_retention.py` covers active and rollback retention,
  partial failed generations, exact-plan application, selector disagreement,
  stale selectors, unknown entries, rollback escapes, trusted group-writable
  failed data, world-writable rejection, writer quiescence, symlink-safe
  deletion, and metadata drift.
- `openclaw-doctor-rehearsal.py` creates service-credential-free structured
  config copies, replaces source secret providers with a fresh canary Gateway
  file `SecretRef`, replaces retained external plugin paths with reviewed
  immutable artifacts, retires explicit legacy plugin ids, performs online
  SQLite backups, scrubs only per-agent auth tables, and emits data-free
  manifests and database summaries for Doctor idempotency checks. Stable-table
  summaries may exclude an explicit reviewed volatile-table set; unknown
  exclusions fail closed. Final Doctor lint JSON and human diagnostics are
  stored separately, and promotion requires parseable JSON with no error
  findings.
  State manifests reject symlinks except for OpenClaw-owned
  `plugin-skills/<name>` links whose real targets and regular `SKILL.md` files
  remain inside explicitly allowlisted immutable plugin roots. Manifests also
  record root and entry ownership so a permission escape is a validation
  failure, not a harmless metadata change.
- `test_openclaw_doctor_rehearsal.py` covers config path and secret handling,
  plugin modernization boundaries, auth-only database scrubbing, SQLite
  summaries, and immutable tree manifest comparison.

## Validation

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/agents -p 'test_*.py' -v
python3 scripts/agents/openclaw-bootstrap-audit.py --root files/openclaw/workspace
python3 scripts/agents/openclaw-modern-config-audit.py --config /path/to/rendered/openclaw.json
python3 scripts/agents/openclaw-provider-auth-boundary-audit.py --help
python3 scripts/agents/openclaw-workspace-inventory.py --source /home/johnny/.openclaw/workspace --policy files/openclaw/workspace-migration-policy.json --pretty
python3 scripts/agents/hermes-openclaw-migration-audit.py --state-root /home/johnny/.openclaw --contract files/hermes/openclaw-state-migration-contract.json --workspace-policy files/openclaw/workspace-migration-policy.json --pretty
python3 scripts/agents/hermes-profile-import-audit.py --contract files/hermes/profile-import-contract.json --workspace-policy files/openclaw/workspace-migration-policy.json --state-migration files/hermes/openclaw-state-migration-contract.json --repository-root . --pretty
black --check scripts/agents
```
