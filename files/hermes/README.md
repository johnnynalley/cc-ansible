# Hermes Static Policy

This directory contains credential-free, machine-readable source for the
isolated Hermes replacement. It is not live Hermes state and must never contain
bot tokens, provider credentials, user/channel IDs, plaintext memories,
sessions, or transcripts. The only memory payloads allowed here are the
reviewed Ansible Vault ciphertext seeds declared by
`profile-memory-contract.json`.

- `shadow-target.json` is the Gate 3 target declaration. It keeps Hermes in a
  tokenless, delivery-disabled, scheduler-disabled shadow state and records the
  required identities, paths, sandbox, approval, broker, backup, and rollback
  boundaries.
- `profiles/*/SOUL.md` contains the root-owned baseline identity for Astra,
  Dubble, and Rigel. It encodes transcript-derived behavior boundaries without
  copying transcript content, user IDs, memories, or credentials.
- `jobs/rigel-academic-alerts.json` is the paused, credential-free declaration
  for Rigel's always-enabled 30-minute script-only schedule. It is activated
  through the Hermes CLI only after cutover approval; Ansible never edits
  Hermes `jobs.json` directly.
- `openclaw-state-migration-contract.json` maps every current OpenClaw
  state-root category to a curated import, disabled rebuild, cutover-only
  credential re-enrollment, external owner, or sealed archive. It delegates
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
- `behavior-contract.json` defines semantic reasoning, concise output,
  correction generalization, and Hermes-native approval-gated self-evolution.
  `behavior-regressions.json` contains sanitized promotion cases derived from
  the private transcript evidence; it contains no transcript text or platform
  identifiers.
- `star-contract.json` defines exactly two private parallel leaf reviewers,
  distinct Vega/Antares goals, bounded inherited authority, both-reviewer
  completion, and one concise Astra synthesis. `star-regressions.json` contains
  six sanitized runtime promotion cases.
- `discord-cutover-contract.json` pins the inert shadow and source-delivery
  controls, declares three distinct private Discord enrollments, and defines
  the attended one-consumer cutover and rollback order. It contains only
  private enrollment references, never identity values or tokens.
  `discord-regressions.json` contains 12 sanitized promotion cases for route
  isolation, authorization, DM silence, duplicate consumers, replay, hostile
  attachments, restart, rollback, and Rigel idle silence.
- `automation-contract.json` inventories all 28 live cron jobs and the three
  active profile heartbeats, assigns each one an agent-backed, external, or
  deterministic-script-only target, preserves the Health receiver as an
  external service, and keeps the absent Siri relay retired.
  `automation-regressions.json` contains 14 sanitized promotion cases for
  inventory drift, one-shot handling, ownership, delivery isolation, Health,
  Siri, scheduler overlap, and rollback.
- `profiles/*/AGENTS.md` contains each profile's root-owned operating contract.
  These files are always-on behavior policy, not keyword-triggered skills.
- `scripts/agents/hermes-shadow-target-audit.py` is the fail-closed validator.
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
- `scripts/agents/hermes-discord-cutover-audit.py` validates source pins,
  distinct profile and Discord identities, inert authority, ordered source
  drain and target activation, rollback, Health continuity, and the complete
  sanitized promotion corpus.
- `scripts/agents/hermes-automation-contract-audit.py` validates the complete
  31-lane schedule inventory, target owner/mode/output boundaries, current
  Health and Siri dispositions, handoff order, source pins, and optionally a
  fresh redacted OpenClaw SQLite inventory.

The target declaration is deliberately structured. Do not replace it with
natural-language phrase matching. Update the schema, validator, tests, and
`docs/hermes-replacement.md` together when a boundary changes.
