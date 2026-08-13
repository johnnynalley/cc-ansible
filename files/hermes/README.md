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
- `scripts/agents/hermes-shadow-target-audit.py` is the fail-closed validator.

The target declaration is deliberately structured. Do not replace it with
natural-language phrase matching. Update the schema, validator, tests, and
`docs/hermes-replacement.md` together when a boundary changes.
