# Hermes Static Policy

This directory contains credential-free, machine-readable source for the
isolated Hermes replacement. It is not live Hermes state and must never contain
bot tokens, provider credentials, user/channel IDs, plaintext memories,
sessions, or transcripts. The only memory payloads allowed here are the
reviewed Ansible Vault ciphertext seeds declared by
`profile-memory-contract.json`.

- `shadow-target.json` is the retained Gate 3 bootstrap declaration. It keeps
  the explicit shadow rehearsal tokenless, delivery-disabled, and
  scheduler-disabled while recording the required identities, paths, sandbox,
  approval, broker, backup, and rollback boundaries. It is not current native
  profile configuration or production Gateway startup policy.
  Astra's declared terminal is native local under its dedicated no-login
  account. Rigel receives Hermes's native file and local terminal tools against
  only its isolated writable academic tree, under its separate unprivileged
  service identity; Dubble exposes no local execution or file tool.
- `rehearsal/Containerfile` builds a credential-free Ubuntu systemd target for
  the attended replacement-node bootstrap proof. The dedicated rehearsal
  inventory contains no production host; the orchestration play adds only the
  disposable rootless Podman container, keeps every Gateway disabled, rejects
  Discord credentials, validates the native runtime, and removes the container
  and image after acceptance.
- `profiles/*/SOUL.md` preserves the reviewed migration-time identity export for
  Astra, Dubble, and Rigel. It is non-authoritative evidence, not an Ansible
  deployment source. Established live identities are Hermes-native mutable
  state protected by native and off-host backups.
- `jobs/rigel-academic-alerts.json` is the paused, credential-free declaration
  for Rigel's always-enabled 30-minute script-only schedule. It is activated
  through the Hermes CLI only after cutover approval; Ansible never edits
  Hermes `jobs.json` directly.
- `plugins/compose-admin/` exposes Astra's two typed Compose tools. It reads a
  root-owned inventory-derived endpoint manifest, uses a dedicated systemd
  credential and forced remote account, requires request-digest-bound approval
  for apply/remove, and never receives a Docker socket, shell, or secret.
- `plugins/fleet-admin/` exposes Astra's owner-session-only
  `fleet_agent_admin` tool. It authenticates the exact live owner Discord
  session against Astra's native state, then forwards only typed Astra,
  Dubble, and Rigel native-profile operations to a credential-isolated local
  broker. It cannot be called by a target agent, write the root-owned
  `/etc/hermes` policy layer, read Astra/private memory/session/credential
  state, or mutate the canonical shared `self-evolution` skill.
- `plugins/arr-api/` exposes the credential-isolated Arr service inventory and
  request tools plus two Prowlarr-specific indexer tools. The broker filters
  the multi-megabyte native indexer schema before returning bounded matches;
  indexer test/create/update accepts secret fields separately, allows only a
  bound owner turn without another prompt, and redacts responses and
  content-free audit records. Nested secret-shaped keys include private and
  encryption keys; the independent plugin boundary rejects any response the
  broker failed to sanitize. Unbound calls are blocked. The generic request
  tool still requires write approval and rejects all
  secret-bearing mutations, and Astra receives neither the Arr API keys nor a
  general shell or network credential path.
- `plugins/host-admin/` retains one typed host-administration toolset. Its
  `docker-vm` media-release actions call the root-side staged Sonarr verifier:
  read-only search/status/stream verification is immediate, while stage,
  season expansion, and cleanup use the existing turn-bound approval hook.
  The plugin cannot accept tracker URLs or payload paths and cannot import or
  replace library files. Its `arr-queue`, `arr-policy`, `arr-transactions`, and
  `arr-storage` health probes are fixed read-only reports from `docker-vm`;
  they do not add generic shell, API, search, deletion, import, or blocklist
  authority.
- `openclaw-state-migration-contract.json` maps every current OpenClaw
  state-root category to a curated import, source-preserving LCM conversion,
  disabled rebuild, cutover-only credential re-enrollment, external owner, or
  sealed archive. It delegates
  workspace paths to the existing hashed workspace migration policy and grants
  no source mutation, archive, cleanup, live migration, delivery, or scheduler
  activation authority.
- `openclaw-dry-run-contract.json` pins the installed official importer and
  permits only an operator-run shape-only inventory. It excludes raw content,
  credentials, sessions, prompts, executable code, network access, write
  options, service activation, and raw importer-report persistence.
- `profile-import-contract.json` assigns every workspace `retain` rule and
  state-root curation rule exactly once to Astra, Dubble, or Rigel. It separates
  ordinary data, operator policy, structured transforms, approved memory, and
  private reviewer evidence while forbidding raw prompt injection and
  cross-profile mounts.
- `profile-memory-contract.json` declares the four compact, vault-encrypted
  native Hermes seeds for Astra and Rigel. Dubble is intentionally unseeded.
  It requires the pinned Hermes scanner, exact character limits, a complete
  three-profile rollback archive, atomic install, and no service activation.
  `profile-memory/*/*.vault` is ciphertext only; decrypted staging is
  root-private under `/run` and removed after every transaction.
- `profile-skills-contract.json` declares reviewed Hermes-native declarative
  migration baselines for Astra, Dubble, and Rigel. The source and one-time
  import evidence remain hash-exact, but they are not a live restore source and
  normal convergence does not compare them with or publish them over native
  profile state. Rigel's migration evidence includes the complete
  academic skill plus its 13 hash-pinned protocol/template files. All three
  profiles receive `self-evolution` from the single canonical
  `profile-skills/shared/self-evolution/SKILL.md`; profile-specific duplicate
  sources are forbidden. Astra owns the canonical local `self-evolution` tree;
  Dubble and Rigel receive only that directory through a read-only service bind.
  Installed trees remain isolated and profile memory/state is not shared. Skill
  sources include Astra's unified `compute-corner-administration` entry point,
  which routes live discovery and approved changes through the existing typed
  Docker, Compose, host-administration, Arr, schedule, and native skill tools;
  it does not add a second administration plugin or a general privilege path.
  The reviewed skill sources and approved supporting Markdown/JSON contain no
  executable, credential requirement, inline command expansion, or automation
  blueprint. The pinned native frontmatter validator and threat scanner must
  pass the retained source before a one-time migration. Node-loss recovery uses
  the complete off-host Hermes backup, not `/etc/hermes/<profile>/skills`.
  One canonical shared `self-evolution` tree is writable only by Astra and
  read-only to Dubble/Rigel. The bootstrap
  contract treats the native operational heartbeat as seeded mutable, so the
  reviewed recovery content stays pinned without freezing Astra's live
  self-maintained procedure. Self-evolution and heartbeat share one bounded
  semantic-maintenance lease: self-evolution holds it for semantic review,
  while heartbeat uses it only for its daily workspace/self-evolution lane.
  Native maintenance discovery is allowlisted and excludes imported, managed,
  legacy, preserved-evidence, backup, and migration roots.
- `profile-data-stage-contract.json` permits a copy-only inactive transaction
  for exactly the `data-stage` and `operator-reference` mappings from the
  pinned profile-import and workspace-policy contracts. It defines distinct
  per-profile writable and managed roots, fixed no-login identities, strict
  size and object limits, source-stability and rollback gates, and no memory,
  reviewer, structured-transform, credential, messaging, scheduler, model, or
  Gateway authority. The complete manifest is root-private; each runtime sees
  only its own writable bind and read-only managed bind.
- `profile-transform-contract.json` permits five schema-checked legacy-state
  conversions into a separate small transactional generation for Astra and
  Dubble. Rigel is deliberately absent: its complete course, memory, syllabus,
  and inbound trees are copied into native writable profile data, and its
  scheduler reads `courses/academic-state.json` directly.
- `behavior-contract.json` defines semantic reasoning, concise output,
  correction generalization, isolated profile-local evolution, and Astra-only
  review of proposed changes to the fleet-shared `self-evolution` skill.
  `behavior-regressions.json` contains sanitized promotion cases derived from
  the private transcript evidence; it contains no transcript text or platform
  identifiers.
- `star-contract.json` defines exactly two private parallel leaf reviewers,
  distinct Vega/Antares goals, asynchronous completion, same-session opaque-ID
  trust, bounded inherited authority, both-reviewer completion, and one concise
  Astra synthesis. `plugins/star-dispatch-privacy/` is Astra's root-owned,
  hook-only output boundary; it exposes no model tool and leaves ordinary
  delegation unchanged. `star-regressions.json` contains seven sanitized runtime
  promotion cases.
- `discord-cutover-contract.json` is retained historical migration evidence. It
  records the reviewed one-consumer-per-identity cutover and rollback order and
  contains only private enrollment references, never identity values or tokens.
  The completed executable cutover playbook is retired; Git history and the
  retained rollback/evidence artifacts preserve that transaction without
  leaving a stale path that can overwrite current native profile state.
  `discord-regressions.json` contains 12 sanitized promotion cases for route
  isolation, authorization, DM silence, duplicate consumers, replay, hostile
  attachments, restart, rollback, and Rigel idle silence.
- `automation-contract.json` preserves the historical source inventory of 28
  observed cron declarations and three logical heartbeat lanes. It is design
  evidence, not the production scheduler source of truth. Its source pins cover
  immutable migration evidence only; it does not hash-pin the current mutable
  Health receiver implementation.
  `automation-regressions.json` contains 14 sanitized promotion cases for
  inventory drift, one-shot handling, ownership, delivery isolation, Health,
  Siri, scheduler overlap, and rollback.
- `production-automation-reconciliation.json` separates the 26 enabled jobs in
  OpenClaw's canonical SQLite scheduler from the 28 enabled rows in its older
  JSON export. It reconciles all 29 current lanes, including three logical
  heartbeats, and preserves all seven historical-only lanes without treating
  them as current or reactivating them. The 18 Astra and one Dubble active
  native jobs are rendered from their production templates; the remaining
  current lanes map to bounded systemd collectors/timers. FreshRSS remains a
  collection-only input to the single Daily Summary compose path, matching the
  current OpenClaw policy. Route identifiers remain in inventory and are never
  committed to this static-policy directory.
- `profiles/*/AGENTS.md` preserves migration-time operating-contract exports.
  These copies are non-authoritative and are never converged into established
  profiles. Each live Hermes-native `AGENTS.md` is the active always-on policy
  and evolves through the owning agent's reviewed native workflow, with local
  rollback and off-host recovery coverage.
- `scripts/agents/hermes-shadow-target-audit.py` is the fail-closed validator
  for the explicit retained shadow/bootstrap audit, not a production Gateway
  dependency.
- `scripts/agents/hermes-openclaw-migration-audit.py` validates the migration
  contract and inventories top-level source metadata without reading contents.
- `scripts/agents/hermes-openclaw-dry-run.py` builds a temporary placeholder
  view from source shape, runs the pinned importer in a networkless read-only
  transient service, writes only root-private structural evidence, and removes
  the view. Top-level legacy skill symlinks are never followed or copied; only
  their anonymous count becomes generic placeholders in the symlink-free view.
  Secret migration is proven disabled by the absent mutation flag because the
  pinned importer's JSON redactor intentionally hides its boolean report field.
  The importer runs through the exact root-owned Hermes venv link and verifies
  the complete link target, resolved Python hash, and `pyvenv.cfg` hash before
  using the pinned dependency environment.
- `scripts/agents/hermes-profile-import-audit.py` validates profile ownership,
  target namespaces, owner classes, source hashes, and memory isolation.
- `scripts/agents/hermes-memory-seed-validate.py` validates one decrypted seed
  with Hermes's pinned native parser and threat scanner while returning only
  bounded metadata and hashes.
- `scripts/agents/hermes-profile-skills-validate.py` applies Hermes's pinned
  native frontmatter validator, threat scanner, exact recursive inventory/hash
  checks to retained migration sources and supports explicit one-time native
  import verification. It is not a recurring profile-state convergence tool.
- `scripts/agents/hermes-profile-data-stage.py` plans, copies, and verifies the
  reviewed project/reference inventory without following links, preserving
  executable bits, mounting the source, or importing raw content as prompts.
  It fails on source drift, manifest or inventory drift, unsafe ownership,
  unexpected object kinds, and incorrect runtime bind modes.
- `scripts/agents/hermes-profile-transform.py` validates and canonicalizes the
  five reviewed structured-transform mappings, writes a root-private manifest,
  verifies source stability and output hashes, and enforces separate writable
  and read-only runtime bind identities without mounting legacy state.
- `scripts/agents/hermes-discord-cutover-audit.py` validates source pins,
  distinct profile and Discord identities, inert authority, ordered source
  drain and target activation, rollback, Health continuity, and the complete
  sanitized promotion corpus. It is retained migration evidence and is not a
  production Gateway readiness gate.
- `scripts/agents/hermes-automation-contract-audit.py` validates the complete
  31-lane schedule inventory, target owner/mode/output boundaries, current
  Health and Siri dispositions, handoff order, immutable evidence pins, and
  optionally a fresh redacted OpenClaw SQLite inventory.

The target declaration is deliberately structured. Do not replace it with
natural-language phrase matching. Update the schema, validator, tests, and
`docs/hermes-replacement.md` together when a boundary changes.
