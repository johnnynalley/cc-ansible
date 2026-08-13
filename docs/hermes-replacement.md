# Hermes Replacement And Modernization

## Status

The target is the official Nous Research Hermes Agent. OpenClaw remains the
production system until an isolated Hermes deployment passes every gate in
this document. OpenClaw must then be stopped and disabled, not cleaned up or
deleted, so it remains a complete rollback system.

This document owns the replacement architecture, parity decisions, behavior
acceptance tests, security boundary, migration order, and rollback contract.
The existing OpenClaw documents remain authoritative for the source system.

## Non-Negotiable Outcomes

- Preserve Astra, Dubble, Rigel, two-reviewer Star verification, Discord,
  durable memory and learning, scheduled automation, and Health reporting.
- Keep Rigel scheduled continuously. An idle poll produces no Discord message,
  control token, reasoning trace, or expected-absence error.
- Present Star results as one normal concise answer. Reviewer work is private
  evidence, not a user-facing transcript or status wall.
- Keep the Health receiver and its aggregate-only boundary. The retired Siri
  relay is not migrated.
- Give Hermes no sudo, Docker socket, Docker group, human home, Ansible vault,
  controller SSH keys, or unrestricted host shell.
- Add Docker inventory, version reporting, and updates only through the
  separately authenticated report and one-use approval broker.
- Keep exactly one production messaging and scheduler path during cutover.
- Preserve all OpenClaw source state, sessions, transcripts, secrets, runtime,
  and rollback instructions until Hermes has passed an attended rollback test.

## Official Capability Baseline

The design is based on the current official documentation for
[profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles/),
[Discord](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/discord/),
[cron](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron),
[delegation](https://hermes-agent.nousresearch.com/docs/user-guide/features/delegation/),
[Mixture of Agents](https://hermes-agent.nousresearch.com/docs/user-guide/features/mixture-of-agents),
[memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory/),
[skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills),
[security](https://hermes-agent.nousresearch.com/docs/user-guide/security/),
and the
[OpenClaw migration guide](https://hermes-agent.nousresearch.com/docs/guides/migrate-from-openclaw).

Hermes profiles have independent configuration, credentials, memory, skills,
sessions, cron jobs, and Gateway state. Do not point two processes at one
Hermes home. The OpenClaw importer does not establish parity for this system:
multi-agent setup, channel bindings, cron, plugins, hooks, heartbeat files, and
other behavior-bearing state require manual reconciliation.

Hermes command approval is a guardrail for an honest but mistaken agent, not a
security boundary against prompt injection. Official guidance requires an
isolated terminal backend for a production Gateway. File-write guards do not
constrain shell commands. This deployment therefore treats the sandbox and
narrow host brokers as the authority boundary.

## Parity Matrix

| Source capability | Hermes target | Parity | Required proof |
| --- | --- | --- | --- |
| Astra primary agent | Dedicated `astra` profile with its own home, model, identity, memory, skills, sessions, cron, and Discord Gateway | Native after manual port | Transcript behavior suite, memory recall, approved skill proposal, Discord round trip |
| Dubble public support agent | Dedicated `dubble` profile with a separate bot token, strict Discord allowlists, and no host-operation toolsets | Native except handoff | Public-channel tests prove metadata authorization, no shell/infra access, and a bounded Astra escalation path |
| Dubble to Astra escalation | Durable task handoff through a narrow broker or Hermes Kanban, never shared profile state | Manual | One request, one acknowledged owner, one completion, no duplicate public response, restart survival |
| Rigel study agent | Dedicated `rigel` profile plus an always-enabled 30-minute Hermes cron declaration | Native with deterministic pre-gate | Seven idle cycles, expected missing files, empty semester, real event, duplicate event, malformed source, and process restart all pass |
| Vega and Antares review | Prefer native Mixture of Agents with two reference models and Astra as aggregator; keep reviewer output private and capped | Partial | Two independent model calls are proven, final answer remains concise, and an adversarial reviewer catches seeded premise errors |
| Antares's intentionally critical role | Native MoA has distinct models but no documented per-reference role prompt; delegation has role prompts but one global child model | Unsupported natively | Do not declare Star parity until a native configuration or narrowly reviewed extension proves distinct critical behavior without exposing reviewer prose |
| Long-running multi-agent work | Named profiles and Hermes Kanban for durable asynchronous work | Native | Task survives Gateway restart, retains owner/history, and cannot gain a wider toolset on handoff |
| File memory and user preferences | Per-profile `MEMORY.md` and `USER.md`, plus FTS5 session search | Native with curated import | Exact user preferences and durable facts survive restart; no raw transcript dump is injected into every prompt |
| Mem0/Qdrant knowledge | Start with built-in memory and preserved read-only OpenClaw archive; evaluate one external Hermes memory provider only after baseline behavior | Manual replacement | Retrieval quality and deletion/privacy behavior beat baseline before enabling a provider |
| Self-evolution | Hermes background review with `memory.write_approval: true` and `skills.write_approval: true` | Native with approval | A correction stages one general memory/skill diff, does not mutate policy directly, and can be approved, rejected, audited, and rolled back |
| Astra root-cause learning | Root-owned behavior policy plus review-gated agent memory/skills and transcript regression tests | Manual policy port | Repeated incidents consolidate into a general rule; incident-specific rule accumulation is rejected |
| OpenClaw sessions and trajectories | Preserve as offline searchable archive; new Hermes sessions live in each profile's SQLite state | Archive, not live migration | Archive manifest, sampled transcript restore, and Hermes access through a read-only search boundary if later required |
| 14 semantic scheduled jobs | Recreate disabled in Hermes cron with exact schedule, timezone, owner, bounded tools, and delivery policy | Manual | Declaration diff plus one attended run per job before enabling |
| 10 deterministic command jobs | Root-managed unprivileged systemd services/timers or no-agent Hermes prechecks | Replace | Empty stdout is silent, failures are bounded and classified, and no Gateway credential enters the worker |
| Main heartbeat catalog | Deterministic collectors and per-check state feed bounded semantic jobs; do not fan out the full catalog in one turn | Manual modernization | Existing cadence, pressure gates, dedupe, and maximum concurrency are regression-tested |
| Discord | One Gateway per profile and bot token, explicit user/role/channel allowlists, DMs denied or paired deliberately | Native | Unauthorized user, unauthorized channel, duplicate token, DM, attachment, and restart tests |
| Health receiver | Retain the current isolated receiver and aggregate report publisher; Hermes reads only the aggregate report | Retain externally | Hermes cannot read token, raw database, row-level records, or source-device names |
| Docker visibility and updates | Rename the existing result-only reporter and digest-bound one-use update broker for platform-neutral agent use | Retain externally | No Docker socket/group; report is read-only; updates require independently approved exact target and digest |
| Model routing | Per-profile providers plus a named MoA preset for Star; no policy-level exact-version pin unless explicitly approved | Native with reconciliation | Provider auth, context size, fallback, model identity, and no unintended exact pin are verified |
| Hooks and plugins | Default to none. Add only root-reviewed hooks or plugins required by a proven parity gap | Manual | Hash/provenance, consent, tool scope, failure mode, update behavior, and rollback are documented |
| Dashboard and API | Disabled during shadow and initial production; any later UI remains loopback-only behind independent authentication | Deliberately omitted | No listener or remote route exists during initial rollout |
| Backups and rollback | Per-profile state backup plus untouched OpenClaw state/runtime backup | Manual | Hermes restore and Hermes-to-OpenClaw rollback are both tested before cutover |

## Rigel Idle-Silence Design

Rigel remains scheduled every 30 minutes. The schedule is not disabled during
breaks, an empty semester, or missing optional daily files.

A root-owned, read-only precheck runs before the model:

1. Read only declared canonical course and calendar sources.
2. Treat an absent optional daily memory file, empty event list, completed
   semester, and no due event as normal state.
3. Return `{"wakeAgent": false}` with no stdout or delivery for normal state.
4. Wake Rigel only for a source-backed candidate that needs semantic handling.
5. Fingerprint and privately record malformed-source or precheck failures.
   Route one deduplicated operational alert through the health path; do not
   leak shell errors, reasoning, or control strings into `#rigel`.
6. Require Rigel to cite the canonical source before sending an exam or event
   alert. A prior alert marker is never evidence that the underlying event was
   real.

Hermes cron's `[SILENT]` behavior is useful but is not the primary safety
mechanism because failed jobs are still delivered. Expected absence must be a
successful deterministic no-op before the model runs.

## Star Verification Design

Hermes Mixture of Agents is the closest native match: two reference models run
in parallel, their private outputs are supplied to the aggregator, and only the
aggregator emits tools and the user-facing answer. Use `fanout: user_turn`, a
small `reference_max_tokens`, guidance rather than council-style output, and a
privacy filter. This directly addresses the transcript failure where Star
research became a wall of reviewer prose.

It does not yet prove the intentional Vega/Antares role split. Official MoA
reference models receive conversation text without the Hermes system prompt,
and the documented preset has no per-reference role prompt. Hermes delegation
can provide distinct role prompts, but all delegated children use one global
model route. Gate 6 must choose and prove one of these outcomes:

- native MoA produces materially independent support and challenge behavior;
- Hermes adds an official per-reference instruction mechanism; or
- a narrow reviewed extension provides only this missing orchestration.

Do not recreate the broad OpenClaw plugin strategy. Do not expose reviewer
transcripts or council reports unless the user explicitly asks to inspect them.

## Transcript-Derived Behavior Tests

The saved transcripts are regression inputs, not just incident notes. Hermes
cannot be promoted until the following tests pass:

1. Resolve pronouns and antecedents from the active thread. "That map" must not
   be silently mapped to the most recent technical noun when another project is
   active.
2. Research current, exact product and regional facts before high-consequence
   advice. Generic protocol behavior is not evidence about DFW infrastructure.
3. Separate compatibility, performance, and recommendation. Connector fit does
   not prove antenna quality; a proxy device does not qualify a different RF
   package.
4. Reconcile owned and purchased hardware before recommending another purchase.
   A recommendation reversal after purchase is a release-blocking failure.
5. Give one direct decision first, with the smallest real blocking condition.
   Do not bury the answer under caveats or reviewer output.
6. During walkthroughs, provide the complete safe sequence until the next step
   actually branches. Download completion is not a useful checkpoint.
7. Treat expected absence and no-match results as data, not tool failures. Tool
   banners and internal probe errors never replace the requested answer.
8. Distinguish recovery, symptom suppression, and root cause. Fix the owning
   mechanism and add a general regression; do not accumulate product-specific
   reminders for the same reasoning defect.
9. Preserve explicit user preferences and scope changes. A paused Fortnite map
   is not a MeshCore map; an ignored Bazarr warning is not repeated in quiet
   reports.
10. Star produces a normal concise answer backed by two private reviews. The
    user does not receive a research dossier unless requested.
11. Alerts require authoritative source evidence. A prior generated memory or
    alert marker cannot bootstrap a fabricated exam.
12. Self-evolution proposes a general correction, cites the triggering failure,
    and remains pending until approved. It cannot rewrite root-owned security,
    runtime, or deployment policy.

## Security Boundary

The target uses a dedicated no-login `hermes` service identity distinct from
the retained `openclaw` identity. Profile state is writable only where Hermes
requires runtime state. Behavior policy, broker clients, systemd units, and
deployment configuration are root-owned and read-only to Hermes.

Initial production policy:

- `terminal.backend: docker` with no Docker socket, host bind mounts, forwarded
  environment variables, or credential files by default.
- Host facts and actions are exposed only through fixed-schema, allowlisted,
  independently authenticated report or action brokers.
- `approvals.mode: manual`, `approvals.cron_mode: deny`, empty permanent command
  allowlist, and destructive session confirmations enabled.
- Explicit Discord allowlists; no allow-all mode.
- `memory.write_approval: true` and `skills.write_approval: true`.
- Agent-created skill scanning enabled; third-party skills are not installed
  until inspected and pinned by provenance, not by stale application version.
- No auto-accepted hooks. Any hook is root-reviewed and its consent record is
  audited after edits because Hermes hook consent keys the command path, not
  script content.
- Prompt-injection scanning and secret redaction enabled. Any optional external
  scanner must fail closed.
- Dashboard/API disabled. Gateway listeners remain loopback-only unless a
  separately authenticated Tailscale proxy is deliberately approved.
- Egress is restricted to required model, web, Discord, Health-report, and
  broker endpoints. Private/link-local metadata destinations remain blocked.
- The Hermes service has no sudoers entry and no supplementary group that can
  write controller code, read secrets, or administer containers.

This boundary assumes any user-authorized agent conversation can be malicious.
Messaging authorization limits who can ask Hermes to act; it does not make
prompt content trustworthy.

## Migration Gates

1. **Source checkpoint:** freeze and verify OpenClaw state, runtime, listeners,
   sessions, jobs, and backups without stopping production.
2. **Parity:** approve this matrix and record every unsupported/manual item.
3. **Target design:** define the service identity, paths, systemd units,
   sandbox, secrets, backup, loopback listeners, and broker schemas.
4. **Shadow install:** install Hermes with no production bot token, delivery,
   host authority, cron delivery, dashboard, or external listener.
5. **Dry-run import:** run `hermes claw migrate --dry-run` against a protected
   read-only source view. Never use cleanup or source archival.
6. **Manual reconciliation:** port each profile, policy, memory, skill, job,
   Health input, and Star mechanism; compare manifests rather than file counts.
7. **Behavior and security:** pass transcript, idle-silence, integration,
   hostile-prompt, privilege, restart, backup, and restore tests.
8. **Cutover:** stop the old Gateway and scheduler, prove they are stopped, then
   activate Hermes once. Verify no duplicate delivery or job execution.
9. **Rollback proof:** stop Hermes, restore OpenClaw service without state loss,
   verify one message and one scheduler declaration, then return to the chosen
   production system.
10. **Retention:** keep OpenClaw stopped, disabled, backed up, and documented.
    Do not uninstall or delete it until the owner separately approves removal.

## Gate 2 Decision

Replacement is feasible, but not by blindly importing OpenClaw. Astra, Dubble,
Rigel, Discord, memory, skills, cron, and sandboxing have viable Hermes-native
targets. Health and Docker authority remain safer as external least-privilege
services. OpenClaw session history remains an offline archive. Distinct
role-prompted Vega and Antares reviewers are the only material behavior gap;
Hermes MoA is the preferred native candidate, but it must pass the adversarial
review regression before the gap can be marked closed.

Gate 3 may design the isolated Hermes target. It may not install or start
Hermes until that design and its rollback artifacts are reviewed.
