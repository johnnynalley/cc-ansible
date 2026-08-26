---
name: self-evolution
description: Use when a reusable agent behavior failure is exposed.
version: 1.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [learning, correction, regression, continuity]
    related_skills: []
---

# Self Evolution

The compact self-evolution gate is always present in each agent's managed profile
instructions. Read this procedure before changing durable behavior. Decide
from the relationship between the current message and prior exchange whether
the owner is correcting the agent, rejecting an unresolved premise, identifying a
contradiction, or exposing an avoidable miss. Do not decide from keywords,
capitalization,
profanity, or example phrasings.

An ordinary request, normal follow-up, or new information that does not
invalidate prior work proceeds without self-evolution commentary. When
uncertain, repair the active task and inspect the evidence; uncertainty alone
does not justify changing durable state.

## Unattended Maintenance Contract

Scheduled maintenance and daily backstop runs are unattended. Never request interactive
command or file-mutation approval. Never call `execute_code`,
create or execute an ad-hoc verification script, or use a temporary `/tmp`
program to reinterpret state. Use loaded native tools, direct bounded reads,
and existing reviewed helpers only. If an operator-owned gap cannot be
validated through those paths, persist content-free native evidence and send
one concise deduplicated notice when action is required; do not improvise a
replacement command.

Successful verification, a memory or skill maintenance action, tool output,
and statements about temporary-file cleanup are internal. They are never the
scheduled run's final response. After any required Discord notice return only
`[SILENT]`; when no operator action is required, return only `[SILENT]`.

## Native Layout And Bounded Probes

Use Hermes-native profile layout, never retired compatibility locations. The
private user and agent memory files are `memories/USER.md` and
`memories/MEMORY.md`; do not assume either file exists at the profile root.
State produced by this skill belongs under `state/self-evolution/`, and native
agent-created skills belong under `skills/`.

The canonical Compute Corner repository is `workspaces/cc-ansible` beneath
Astra's profile home. A read-only Git probe may encounter ownership protection
because the repository is shared with the operator. Use an invocation-scoped
command such as `git -c safe.directory="$PWD" status --short --branch` while
that repository is the current directory. Never modify global or system Git
configuration and never treat the ownership guard itself as repository drift.

Do not assume the `sqlite3` CLI is installed. Prefer a loaded native tool or an
existing reviewed helper for SQLite-backed state. If no reviewed interface
exposes the required bounded fact, preserve that exact gap for the operator;
do not create an ad-hoc query program during unattended maintenance.

## Handle The Active Turn

1. Reconstruct the objective, hard constraints, current facts, prior valid
   work, and exactly what the new evidence invalidates.
2. Correct the requested deliverable before discussing maintenance.
3. Preserve valid project state. Do not restart the task merely because one
   premise was corrected.
4. Inspect any image, transcript, file, or exact source supplied in the turn
   before answering. Do not substitute recollection for available evidence.

## Find The Reusable Mechanism

Identify the earliest decision boundary that would have prevented the miss:
the source that should have been checked, premise that should have remained
stable, verification that was skipped, continuity handoff that failed, tool
result that was misread, or delivery path that was never proven.

Inspect the existing architecture before writing anything:

- always-loaded profile guidance;
- the owning managed or agent-created skill;
- the canonical project reference or ledger;
- runtime configuration and hook behavior;
- existing validators and behavioral scenarios;
- recent correction changes that may claim to solve the same class.

The incident is evidence, not automatically a new rule.

## Choose The Right Change

Use the smallest truthful outcome:

- **Correct current facts only.** Update the owning project state when facts or
  requirements changed, without claiming behavior evolved.
- **Write native memory.** Store a well-supported, stable, nonsecret user fact,
  preference, decision, or unresolved commitment when it is not already
  represented. Do not store transient incidents, secrets, copied transcripts,
  or uncertain inferences as facts.
- **Enforce an existing control.** If guidance already covered the miss,
  determine why it was not loaded, selected, followed, or tested. Repair that
  mechanism instead of restating the rule.
- **Revise an agent-owned workflow.** Improve an agent-created skill when its
  reusable procedure is weak, then validate discovery and behavior.
- **Create a missing agent-owned skill.** Add one only after proving no existing
  control owns a genuinely reusable task boundary.
- **Escalate operator-managed work.** Preserve evidence and request operator
  action for managed skills, profile instruction or identity policy, runtime
  configuration, models, schedules, credentials, services, security,
  deployment, or authority.
- **Make no durable change.** A one-time correction can be fixed in the answer
  without manufacturing policy.

Do not turn corrected nouns, product names, screenshots, commands, connectors,
or topologies into policy sentences. Put domain facts in the owning project
ledger and use incidents as regression scenarios. A memory write, apology,
promise, commit, restart, or generic "tests passed" claim is not proof.

## Correction Clusters

When several recent corrections share a task, or the owner reports the same
behavior persists, stop adding patches. Reconstruct the correction history,
inspect controls and edits already made, find the common mechanism, and
consolidate redundant guidance. A long quiet interval is unknown, not proof:
intermittent generation and delivery defects can remain latent until a run
crosses a publication boundary.

## Validate Behavior

Validate the path that failed, not merely file syntax:

- prove the policy or skill is visible to the active agent;
- reconstruct last-known-good, first-known-bad, route or config changes, and
  post-repair recurrences from raw timestamps before selecting one trigger;
- separate canonical state, generation, tool invocation, tool-result handling,
  runtime normalization, scheduler routing, and external transport;
- exercise a fresh scenario with different wording and domain details;
- include a normal non-correction case to prevent over-application;
- for intermittent or externally visible behavior, run the configured primary
  more than once on the actual route and inspect trajectories, warnings,
  normalization, and delivery receipts;
- test fallback models only when fallback use was observed, changed, or
  explicitly requested;
- require independent adversarial review when a correction cluster affected
  spending, live systems, security, destructive operations, or repeated public
  output;
- verify current-session activation, including any required Gateway restart;
- write only within the active agent's native memory, data, and agent-created
  skill authority.

## Report Naturally

Lead with the corrected answer. When a durable change was made, state naturally
what mechanism failed, what control changed, where it lives, when it is active,
and what behavioral test proved it. Never claim a behavior was fixed before the
enforcement path exists. Keep internal review and maintenance plumbing out of
the answer unless the owner must act.

## Failed Tools

Treat a failed tool result as evidence. Determine whether it was an expected
negative probe, bad invocation, missing access or dependency, external failure,
or unresolved. Correct and rerun avoidable failures when useful. Explain only
material limitations to the owner; do not emit a status taxonomy for its own
sake.
