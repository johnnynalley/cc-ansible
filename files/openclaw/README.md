# OpenClaw Static Behavior Sources

This directory owns the reviewed, credential-free behavior bundle for the
modern dedicated-service OpenClaw deployment. It is a reconstruction of the
required behavior, not a copy of the legacy human-home workspace.

## Layout

- `workspace/`: compact bootstrap files for Astra, Dubble, Rigel, Vega, and
  Antares.
- `workspace-migration-policy.json`: exhaustive classification of the current
  legacy workspace into `replace`, `retain`, `archive`, `retire`, or `discard`
  lanes. Every retained rule declares a target and either Gateway-writable or
  operator-read-only ownership.

Agent identity metadata is applied through OpenClaw's native agent identity
configuration. It is intentionally not duplicated in `IDENTITY.md`. Vega and
Antares have no heartbeat files because they are request-scoped workers.
Personal memories, project data, course material, authorization data, and
other writable state are separate migration inputs and are not stored here.

## Deployment Contract

- Root deploys these files read-only before the production Gateway starts.
- `agents.defaults.skipBootstrap` remains enabled so OpenClaw cannot recreate
  generic starter files beside the managed source.
- Mutable memory and project data live in separately owned writable paths.
- Unknown legacy paths block staging. The complete stopped legacy source stays
  in the rollback archive until parity, sampled restore, and retention approval
  pass; a `discard` row never authorizes early deletion.
- The legacy cognitive-stack hook, generic starter prompts, hardcoded session
  keys, and heartbeat control-token filters are not migrated.
- Run `scripts/agents/openclaw-bootstrap-audit.py` before promotion. The audit
  rejects unknown files, legacy paths, opaque platform IDs, polling loops,
  control tokens, missing role invariants, and bootstrap-budget regressions.

Do not place secrets, credentials, private channel IDs, or mutable runtime
state in this directory.
