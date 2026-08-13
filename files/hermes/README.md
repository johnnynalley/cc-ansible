# Hermes Static Policy

This directory contains credential-free, machine-readable source for the
isolated Hermes replacement. It is not live Hermes state and must never contain
bot tokens, provider credentials, user/channel IDs, memories, sessions, or
transcripts.

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
- `profile-import-contract.json` assigns every workspace `retain` rule and
  state-root curation rule exactly once to Astra, Dubble, or Rigel. It separates
  ordinary data, operator policy, structured transforms, approved memory, and
  private reviewer evidence while forbidding raw prompt injection and
  cross-profile mounts.
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
- `profiles/*/AGENTS.md` contains each profile's root-owned operating contract.
  These files are always-on behavior policy, not keyword-triggered skills.
- `scripts/agents/hermes-shadow-target-audit.py` is the fail-closed validator.
- `scripts/agents/hermes-openclaw-migration-audit.py` validates the migration
  contract and inventories top-level source metadata without reading contents.
- `scripts/agents/hermes-profile-import-audit.py` validates profile ownership,
  target namespaces, owner classes, source hashes, and memory isolation.
- `scripts/agents/hermes-discord-cutover-audit.py` validates source pins,
  distinct profile and Discord identities, inert authority, ordered source
  drain and target activation, rollback, Health continuity, and the complete
  sanitized promotion corpus.

The target declaration is deliberately structured. Do not replace it with
natural-language phrase matching. Update the schema, validator, tests, and
`docs/hermes-replacement.md` together when a boundary changes.
