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
  boundaries. It also requires a root-managed offline command scanner, disabled
  runtime lazy installs, blocked private URLs, and fail-closed Tirith behavior.
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
- `profile-skills-contract.json` declares six reviewed Hermes-native,
  declarative skill deployments: four for Astra, one for Dubble, and one for
  the preserved Rigel profile. The study skill is intentionally present under
  Astra because Astra is the production Discord consumer for `#rigel`.
  `profile-skills/*/*/SKILL.md` contains no legacy skill copy, executable,
  credential requirement, inline command expansion, or automation blueprint.
  The pinned native frontmatter validator and threat scanner must pass exact
  hashes before root-owned `/etc/hermes/<profile>/skills` content is installed.
  Each Gateway bind-mounts that tree read-only under its native local skill
  root and revalidates both the tree and Hermes's own skill index before start.
- `profile-data-stage-contract.json` permits a copy-only inactive transaction
  for exactly the `data-stage` and `operator-reference` mappings from the
  pinned profile-import and workspace-policy contracts. It defines distinct
  per-profile writable and managed roots, fixed no-login identities, strict
  size and object limits, source-stability and rollback gates, and no memory,
  reviewer, structured-transform, credential, messaging, scheduler, model, or
  Gateway authority. The complete manifest is root-private; each runtime sees
  only its own writable bind and read-only managed bind.
- `profile-transform-contract.json` permits six schema-checked legacy-state
  conversions into a separate small transactional generation. It reads only
  seven declared source objects, rejects links and active/unparsed Rigel
  semesters, exposes no raw source tree, and produces isolated writable state
  for Astra/Dubble plus one root-managed read-only Rigel schedule input.
- `behavior-contract.json` defines semantic reasoning, concise output,
  correction generalization, and Hermes-native approval-gated self-evolution.
  `behavior-regressions.json` contains sanitized promotion cases derived from
  the private transcript evidence; it contains no transcript text or platform
  identifiers.
- `star-contract.json` defines exactly two private parallel leaf reviewers,
  distinct Vega/Antares goals, asynchronous completion, same-session opaque-ID
  trust, bounded inherited authority, both-reviewer completion, and one concise
  Astra synthesis. `plugins/star-dispatch-privacy/` is Astra's root-owned,
  hook-only output boundary; it exposes no model tool and leaves ordinary
  delegation unchanged. `star-regressions.json` contains six sanitized runtime
  promotion cases.
- `discord-cutover-contract.json` pins the inert shadow and source-delivery
  controls, declares two Discord consumers for three logical roles, and
  defines the attended one-consumer-per-identity cutover and rollback order.
  It contains only private enrollment references, never identity values or
  tokens.
  `playbooks/agents/hermes-production-cutover.yml` is the disabled-by-default
  live transaction that implements that order. It uses Hermes's native cron
  and send interfaces, never edits `jobs.json` directly, and restores
  OpenClaw automatically if a promotion assertion fails.
  `discord-regressions.json` contains 12 sanitized promotion cases for route
  isolation, authorization, DM silence, duplicate consumers, replay, hostile
  attachments, restart, rollback, and Rigel idle silence.
- `automation-contract.json` preserves the historical source inventory of 28
  observed cron declarations and three logical heartbeat lanes. It is design
  evidence, not the production scheduler source of truth.
  `automation-regressions.json` contains 14 sanitized promotion cases for
  inventory drift, one-shot handling, ownership, delivery isolation, Health,
  Siri, scheduler overlap, and rollback.
- `production-automation-reconciliation.json` gives every one of the 31 source
  lanes an explicit retained, replaced, collapsed, completed, or retired
  disposition. The seven current native jobs are rendered from
  `templates/hermes/astra-production-jobs.json.j2`; route identifiers remain in
  inventory and are never committed to this static-policy directory.
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
- `scripts/agents/hermes-profile-skills-validate.py` applies Hermes's pinned
  native frontmatter validator, threat scanner, exact inventory/hash checks,
  and native runtime-index proof to the reviewed per-profile skills.
- `scripts/agents/hermes-profile-data-stage.py` plans, copies, and verifies the
  reviewed project/reference inventory without following links, preserving
  executable bits, mounting the source, or importing raw content as prompts.
  It fails on source drift, manifest or inventory drift, unsafe ownership,
  unexpected object kinds, and incorrect runtime bind modes.
- `scripts/agents/hermes-profile-transform.py` validates and canonicalizes the
  six reviewed structured-transform mappings, writes a root-private manifest,
  verifies source stability and output hashes, and enforces separate writable
  and read-only runtime bind identities without mounting legacy state.
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
