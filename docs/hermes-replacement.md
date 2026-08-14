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
| Vega and Antares review | Native parallel batch delegation with two fresh leaf agents and Astra as the only synthesizer | Native after policy port | Both independent child runs are proven, final answer remains concise, and seeded premise errors are caught |
| Antares's intentionally critical role | Distinct `goal` and `context` for the adversarial leaf; reviewer model inherits Astra's reviewed route without an exact-version pin | Native, one child-model route | Promotion proves Antares challenges rather than echoes while neither reviewer sees the other's output |
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

A root-owned, read-only script-only job runs without a model:

1. Read only declared canonical course and calendar sources.
2. Treat an absent optional daily memory file, empty event list, completed
   semester, and no due event as normal state.
3. Return empty stdout and no delivery for normal state.
4. Format only explicit source-backed candidates; the scheduler path never asks
   a model to infer whether an event exists.
5. Fingerprint and privately record malformed-source or evaluator failures.
   Route one deduplicated operational alert through the health path; do not
   leak shell errors, reasoning, or control strings into `#rigel`.
6. Require every event record to carry a canonical evidence reference before
   the script can emit it. A prior alert marker is never evidence that the
   underlying event was real.

Hermes officially supports script-only cron, where empty stdout is a silent
tick with no model or provider call. `[SILENT]` is not used because failed
agent jobs are still delivered. Expected absence and source errors are caught
as successful no-output evaluations and written to local health state; a
separate freshness/health check owns operational failure alerts outside
`#rigel`.

The legacy academic Markdown is migration input, not runtime authority. Its
current layout can place archived dated entries beneath an "Upcoming Exams"
heading even after the semester is marked complete, which is ambiguous to a
model. The attended migration converts that material once into structured
semester/event records with explicit status and evidence fields. The running
schedule never parses the legacy Markdown, delivery receipts, channel metadata,
or prior generated alerts, and it needs no heartbeat control-token filter.

## Star Verification Design

Star uses Hermes' native parallel batch delegation for reviewer execution, not
MoA. A root-reviewed hook-only plugin enforces the privacy and completion
boundary because Hermes v0.20.0 forces model-facing top-level delegation into
the background. The plugin does not choose when Star applies, answer the
question, register a model tool, or replace reviewer judgment. Astra still
selects Star semantically and creates exactly two fresh leaf agents in one
batch:

- Vega independently verifies the exact object, current primary evidence,
  constraints, calculations, and strongest defensible answer.
- Antares assumes the candidate answer may be wrong and searches for premise
  errors, contradictory evidence, stale facts, ignored user constraints,
  commitment harm, unsafe action, and stronger alternatives.

The initial goals carry exact internal Vega and Antares tags so the host can
distinguish a private Star batch from ordinary delegation. The parent passes
only necessary case context. Neither reviewer receives
Astra's hidden reasoning or the other review. Leaf restrictions remove memory
writes, clarification, and further delegation; root-managed configuration caps
the batch at two, depth at one, and each reviewer at 12 iterations. Both reviews
are required before Astra may treat the result as Star-verified. One failed
reviewer gets one retry; a continued failure produces a concise unverified
caveat or deferral, not a fake success.

Hermes returns a dispatch handle immediately and later injects one consolidated
background completion. The hook suppresses only a successfully recorded Star
dispatch turn, binds the opaque completion ID to the dispatching session, and
marks only the matching completion as trusted reviewer evidence. A pasted,
mismatched, stale, or post-reset completion header remains ordinary untrusted
content. Only one Star batch may be active per session, and only one tagged
failed-reviewer retry is permitted. Ordinary Hermes delegation is unchanged.

Only Astra talks to the user. On the host-verified completion turn, it resolves
disagreements and emits one direct, normal-length answer. Reviewer labels,
prose, status narration, confidence ledgers, contradiction dumps, and research
dossiers remain private. A material unresolved conflict is stated only when it
changes what the user should do. This directly corrects the transcript failure
where independent review became a wall of process output.

Native MoA remains deliberately outside the Star path. It supports parallel
reference models, private aggregator context, bounded advisor output, and
`fanout: user_turn`, but current official documentation says reference models
receive conversation text without the Hermes system prompt and documents no
per-reference role instruction. It therefore cannot guarantee Vega
corroboration and Antares challenge semantics. Reconsider it only if Hermes
adds per-reference instructions or actual promotion tests prove equivalent
adversarial behavior. See official
[delegation](https://hermes-agent.nousresearch.com/docs/user-guide/features/delegation/)
and
[Mixture of Agents](https://hermes-agent.nousresearch.com/docs/user-guide/features/mixture-of-agents)
behavior.

`files/hermes/star-regressions.json` defines six runtime promotion cases:
seeded premise error, purchased-item reversal, current-source conflict,
reviewer independence, single normal answer, and reviewer failure. Static
policy tests do not establish model behavior. Gate 7 must prove two actual
child calls, Antares's adversarial value, concise Discord output, and failure
handling before Star parity is accepted.

## Discord Routing And Cutover

The retained OpenClaw configuration has two Discord applications. Astra's
application serves both `#astra` and `#rigel`; Dubble has the second
application. Production Hermes therefore runs two delivery Gateways for three
logical roles. Astra owns the Astra route plus a channel-scoped Rigel persona
and study skill, while Dubble owns only its support route. The isolated Rigel
profile remains preserved and stopped unless a future third Discord
application is enrolled. Native Hermes token locks are a last defensive check,
not permission to overlap consumers: OpenClaw and Hermes must never use the
same Discord identity concurrently. Bot-authored input is disabled.

The managed shadow config is deliberately inert. It has no Discord token,
user, role, channel, home-channel, or free-response enrollment; unknown DMs
are ignored rather than paired; slash registration, reactions, history
backfill, and missed-message backfill are off. Server threads still require an
explicit mention and shared-channel sessions remain per user. Attachments are
bounded and remain untrusted input subject to the same policy and sandbox.

Private production enrollment happens through root-owned mode-`0440`
managed-scope environments after OpenClaw has stopped. Astra and Dubble receive
their distinct Discord tokens; Dubble and the preserved Rigel profile receive
their independently scoped model provider environment. Only root can write a
file and only its matching service group can read it. Managed-scope precedence
prevents profile-local or inherited values from overriding pinned authority.
Values never enter Git, shell arguments, normal logs, or cutover evidence.
Astra requires explicit owner and channel scope for both private routes.
Dubble uses approved channel scope for public support plus a private admin-user
set; it still has no terminal or infrastructure authority. Slash-command
registration remains off during initial cutover.

The owner-authorized handoff is break-before-make and is implemented by the
disabled-by-default `playbooks/agents/hermes-production-cutover.yml`:

1. Back up OpenClaw and every Hermes profile; prove both schedulers and all
   sessions idle.
2. Stop and disable the production OpenClaw user Gateway, isolated Gateway,
   and isolated Codex service. Prove no OpenClaw Discord consumer remains.
3. Run the existing metadata-only
   `openclaw-delivery-cutover-audit.py`. Pending queue rows or active session
   recovery fields block cutover; failed history may be archived but is never
   replayed.
4. Enroll both Discord identities and all three provider scopes. Start Astra,
   prove the Astra and Rigel channel routes, then start Dubble and prove its
   route. Keep the Rigel Gateway stopped because Astra is its sole delivery
   consumer.
5. Enable only reviewed schedules and prove Rigel's idle tick remains empty.

The playbook also enables Hermes's and Tirith's native update timers, keeps the
independent Health receiver online, records only content-free root-private
evidence, and has an automatic rescue block that stops Hermes and restores the
previous OpenClaw unit state if any post-stop assertion fails. The neutral
`.gateway-ready` marker replaces the staging-era `.shadow-ready` name.
The shadow convergence permits one narrow mutable-config schema migration for
Astra's already-proven native Codex route: schema 34, exactly the provider,
model, and official Codex base URL fields, to schema 35. Any additional field
or route drift still requires an offline reviewed migration.

History and missed-message backfill remain disabled, so a message sent during
the maintenance gap is not reconstructed later. This is an explicit short
availability tradeoff for duplicate-delivery safety. Rollback reverses the
boundary: pause Hermes schedules, wait for idle, stop every Hermes consumer,
quarantine its credential files, prove absence, then restart OpenClaw and prove
one new response. Neither runtime is cleaned up, and the external Health
receiver stays running during cutover and rollback.

The machine-readable source is
`files/hermes/discord-cutover-contract.json`; its validator is
`scripts/agents/hermes-discord-cutover-audit.py`; private route discovery and
credential enrollment are performed by
`scripts/agents/hermes-discord-enroll.py`. Twelve sanitized runtime
cases in `files/hermes/discord-regressions.json` block promotion until the
isolated deployment proves route isolation, unauthorized user/channel and DM
silence, token-lock behavior, bot-loop prevention, no restart replay, hostile
attachment containment, source queue drain, maintenance-gap handling,
rollback, and post-cutover Rigel silence.

## Scheduled Automation And Health

The live metadata-only inventory on 2026-08-13 found 28 enabled OpenClaw cron
jobs: 18 agent turns and 10 command jobs. The current agent configuration also
has three enabled 30-minute heartbeats for Astra, Dubble, and Rigel. All 31
lanes are represented explicitly in `files/hermes/automation-contract.json`;
none is dropped merely because its implementation changes.

The target classification is:

- 16 agent-backed lanes produce local structured proposals under a future
  non-messaging `hermes-automation` owner. They do not inherit a Discord token
  and cannot post directly. A separately scoped publisher must validate the
  destination, evidence, dedupe state, and output size before delivery.
- 10 command lanes move to explicit unprivileged systemd service/timer owners.
  OpenClaw self-maintenance becomes Hermes proposal/diagnostic maintenance;
  Daily Summary collection and assembly, backup, repo drift, memory proposal,
  and thread archival do not run inside a messaging Gateway.
- Five deterministic lanes use Hermes no-agent semantics: Rigel plus the four
  pending source-backed Warframe reminders observed on August 13. Empty stdout
  is the only idle result, so no model, control token, or status explanation is
  involved.

Hermes cron jobs cannot recursively create more cron jobs. The Warframe sync
therefore becomes an agent-reviewed local plan; an external reconciler creates
validated no-agent one-shots. Completed source one-shots are not replayed.
Before cutover, the query-only OpenClaw SQLite inventory must be rerun and
compared with the contract. A new job, changed schedule, or missing recurring
lane blocks promotion; an absent delete-after-run reminder is allowed only as
expired source history.

The current `health-receiver.service` remains an active user service while the
Hermes runtime is designed and tested. It stays running through messaging and
scheduler handoff. Its separate attended modernization uses
`playbooks/agents/openclaw-health-receiver.yml` to move ingestion to a dedicated
system identity while exposing only aggregate reports to models; raw Health
rows and the upload token remain outside Hermes. No Siri relay unit is active,
and migration is forbidden from recreating one.

The shadow deployment installs only the root-owned contract and audit. It does
not create `hermes-automation`, systemd timers, publishers, one-shot jobs, or
live schedules. Fourteen sanitized promotion cases in
`files/hermes/automation-regressions.json` cover source drift, one-shot expiry,
command isolation, direct-message prevention, recursive scheduling, idle
silence, scheduler overlap, Health continuity/data containment, Siri
retirement, and rollback ordering.

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

The target uses three dedicated no-login Hermes service identities distinct
from the retained `openclaw` identity. Profile state is writable only where
Hermes requires runtime state. Behavior policy, broker clients, systemd units,
and deployment configuration are root-owned and read-only to Hermes.

Initial production policy:

- `terminal.backend: docker` with no Docker socket, host bind mounts, forwarded
  environment variables, or credential files by default.
- `computer_use` is explicitly disabled for every profile. Browser retrieval
  remains available for current-source research, but no agent receives desktop
  control merely because Hermes includes that tool in its built-in safe set.
- Host facts and actions are exposed only through fixed-schema, allowlisted,
  independently authenticated report or action brokers.
- `approvals.mode: manual`, `approvals.cron_mode: deny`, empty permanent command
  allowlist, and destructive session confirmations enabled.
- Explicit Discord allowlists; no allow-all mode.
- `memory.write_approval: true` and `skills.write_approval: true`.
- Agent-created skill scanning enabled; third-party skills are not installed
  until inspected and pinned by provenance, not by stale application version.
- Reviewed baseline skills are declarative, exact-hashed, and root-owned under
  `/etc/hermes/<profile>/skills`. Each Gateway bind-mounts only its own tree
  read-only under `~/.hermes/skills/managed`; its service identity cannot edit
  or replace the mounted content while running. Hermes's native frontmatter
  validator, threat scanner, exact inventory, and model-visible skill index
  must all pass before startup. Profile-local agent proposals remain separate
  and retain native scan plus explicit write approval.
- No auto-accepted hooks. Any hook is root-reviewed and its consent record is
  audited after edits because Hermes hook consent keys the command path, not
  script content.
- Prompt-injection scanning and secret redaction enabled. Tirith is bootstrapped
  from an exact official release after Sigstore identity and signed-checksum
  verification, then maintained by its own signed atomic updater under the
  dedicated `hermes-updater` identity. Gateways use only the absolute binary,
  run it offline, reject runtime lazy installs, and fail closed on scanner
  errors. Hermes's background downloader is never part of the production path.
- Dashboard/API disabled. Gateway listeners remain loopback-only unless a
  separately authenticated Tailscale proxy is deliberately approved.
- Egress is restricted to required model, web, Discord, Health-report, and
  broker endpoints. Private/link-local metadata destinations remain blocked.
- The Hermes profiles have no general sudo or supplementary group that can
  write controller code, read secrets, or administer containers. Astra alone
  may start the exact root-owned native update unit; Dubble and Rigel cannot.
- That unit still runs Hermes's own updater as Astra. It sets uv's documented
  `UV_LINK_MODE=copy` behavior so cache files cannot become hardlinked to the
  shared runtime tree and normal updates do not emit hardlink fallback noise.

This boundary assumes any user-authorized agent conversation can be malicious.
Messaging authorization limits who can ask Hermes to act; it does not make
prompt content trustworthy. Tirith and the native prompt scanner are heuristic
defenses, not containment. Separate no-login identities, systemd confinement,
the rootless terminal sandbox, and narrow authenticated brokers remain the
authority boundary even when a scanner misses adversarial content.

## Isolated Target Design

### Deployment Topology

Hermes replaces OpenClaw directly on `jn-t14s-lin`; it does not require a new
VM. The earlier VM-placement branch came from misreading "keep OpenClaw just in
case" as a requirement to retain a concurrently runnable OpenClaw system. The
actual requirement is to preserve OpenClaw's files for offline reference while
Hermes becomes the only running agent platform.

A bounded 2026-08-13 host check found 16 logical CPUs, about 10.6 GiB available
RAM, and about 31.9 GiB free on `/`. That is sufficient for the cloud-model
Hermes runtime after OpenClaw stops. The host does not have room for another
wholesale copy of the roughly 37.3-GB OpenClaw tree, and none is needed. Curated
profile state is imported into the separate Hermes homes; the original tree
stays in place as offline source evidence.

Hermes uses three no-login service users, `/var/lib/hermes/*` profile homes,
root-owned policy and secrets, and rootless Podman. `ProtectHome=true`, the
absence of host mounts, and separate UIDs prevent Hermes from reading the raw
OpenClaw tree or the controller user's home. If later migration needs another
source fact, a root-controlled review/import step extracts only that approved
item instead of mounting the legacy tree into an agent context.

Installation may coexist only while Hermes is stopped and has no production
credentials. Starting any Hermes gateway requires the production OpenClaw
listener and the loopback OpenClaw canary listeners to be stopped first. The
attended cutover then proves the old listeners and schedules are inactive
before enrolling Discord routes and starting Hermes. Health remains a separate
service. After acceptance, OpenClaw stays disabled; its files remain available
for operator-controlled reference, not executable fallback authority.

### Identities And State

Use three separate no-login service accounts, not three writable profiles under
one Unix identity:

| Identity | Hermes home | Authority |
| --- | --- | --- |
| `hermes-astra` | `/var/lib/hermes/astra` | Primary conversation, web research, review synthesis, approved learning proposals, aggregate reports, and broker proposals |
| `hermes-dubble` | `/var/lib/hermes/dubble` | Public support only; no terminal, host report, infrastructure, update, or cross-profile credential access |
| `hermes-rigel` | `/var/lib/hermes/rigel` | Study context and the continuously enabled, deterministically pre-gated scheduler only |

Each home has independent config, auth, state database, memory, skills,
sessions, cron, pending approvals, cache, sandbox metadata, and logs. Files are
mode `0600` and directories `0700` unless a documented root-owned input needs a
narrow group read. No service identity is a member of another profile's group.

Common mandatory policy lives in root-owned `/etc/hermes/` managed scope.
Role-specific identity and behavior sources live under
`/etc/hermes/profiles/<role>/` and are read-only bind-mounted over the runtime
view by systemd. Hermes runtime data remains writable; root policy, service
units, broker clients, and acceptance tests do not.

Provider and Discord credentials are supplied by separate root-owned systemd
environment files, readable only by root and the matching service group. Do
not duplicate secrets in profile distributions, shell profiles, Compose files,
or shared environment files. Codex OAuth state is profile-specific and never
shared with another role or copied into a terminal sandbox.

### Runtime And Updates

Install the official Git distribution under `/usr/local/lib/hermes-agent` with
`/usr/local/bin/hermes` as the launcher. Root performs the reviewed bootstrap,
then `hermes-astra` owns the checkout so Hermes can use its native updater.
The Discord Gateway still cannot patch that code because its hardened systemd
namespace makes `/usr/local` read-only. Track the official default branch rather
than setting a policy-level exact-version pin.

The initial reviewed bootstrap uses stable release `v2026.8.3` (Hermes
v0.20.0), annotated tag object
`7de39e700d2c329e15d32eb0b96e2f7cdd9fbdb2`, and exact commit
`3c27eb6234bf91b8ceee9e9071591b31e9b148cb`. GitHub reports the tag signature
as valid. The exact tag and commit are transaction provenance, not a permanent
update-policy pin.

Do not execute the release's monolithic installer for this managed bootstrap.
It can download a mutable `uv` installer, fall back from `uv sync --locked` to
an unlocked PyPI resolve, and install Node dependencies that the headless
runtime does not need. Instead, deploy official `uv` `0.12.4` from its reviewed
archive with SHA-256
`c8c60f47e6f88d18dbf6f33d7279fb1fbf7ae76631768152cf5578c3d65729b4`,
check out the exact official Hermes commit, and require `uv sync --extra all
--locked` to succeed without fallback. Keep `uv`'s cache and managed Python
under Hermes-owned `/var/cache/hermes` and `/usr/local/share/uv`, not root's
home. Preserve the source tree's `[tool.uv]` settings because the committed
lockfile includes that resolution policy; isolate user/system configuration
through empty root-owned XDG config roots instead of disabling project config.
Preserve Hermes's native Git install marker and launcher layout, disable bundled
skill seeding, and require the post-install origin, tag object, commit, and
clean-tree checks before configuration proceeds.

Updates use Hermes's native lifecycle. The root-owned launcher recognizes only
the exact `update --gateway` argv that Hermes's own Discord `/update` command
emits. For Astra only, that branch starts a hardened systemd oneshot which runs
`hermes update --gateway --yes`; all release discovery, Git movement,
backup, dependency migration, syntax rollback, config migration, and Gateway
restart remain in upstream Hermes. The bridge does not implement an updater.
Dubble and Rigel have no update trigger or sudoers entry.

The oneshot runs as `hermes-astra`, not root, and invokes the native CLI entry
directly so it cannot recurse through the launcher trigger. This lets Hermes use
its normal private mode-`0700` profile home without ACL or group exceptions. The
unit does not set `HERMES_MANAGED_DIR`; the entire root-managed Astra directory
is inaccessible to it, so Hermes cannot load the Gateway's credentials while
updating. It has no Linux capabilities and sees root-owned behavior, plugin,
script, and imported-data paths read-only. Hermes's own restart logic may issue
only `reset-failed`, `start`, and `restart` for the three enumerated Hermes
Gateway units. Together with the exact update-unit trigger, those commands are
Astra's entire sudo surface. Dubble and Rigel have no sudo authority.

The same native oneshot is scheduled automatically after production cutover.
It remains staged and disabled while Hermes has no production route so the
accepted source cannot move underneath migration testing. Hermes's native
default quick snapshot protects critical Astra state before code or dependency
changes; the retained host migration backup protects the complete profile,
checkout, and separately managed Dubble and Rigel profiles. Config checks and
policy hashes remain startup gates, not a replacement update pipeline.

The first capability-stripped root unit was rejected in live testing before it
changed Git or dependencies. Hermes tried to inspect the optional
`/var/lib/hermes/astra/.env`, but root with an empty capability bounding set
could not traverse Astra's mode-`0700` home. Broad DAC capabilities would have
defeated the security boundary. A subsequent separate-updater design completed
one native update, but required home ACLs and directory modes that Hermes's own
config checks correctly restored to private state. That design was retired
rather than preserving recurring permission churn. Running the native updater
as Astra inside a separate systemd write namespace is the durable correction.
The unit still excludes `HERMES_MANAGED_DIR`, because Hermes loads managed
`.env` before dispatching every subcommand and an update must not receive the
Gateway's credentials.

The first successful native update exposed one more boundary error before any
Gateway start: `UMask=0077` made newly checked-out Python files mode `0600`, so
the three service identities could not import the shared runtime. Runtime code
contains no credentials and must be executable/readable by all three isolated
Gateway identities. The updater therefore uses normal install umask `0022`,
and convergence normalizes only the official checkout's ownership to Astra.
It does not recursively rewrite native source modes; the updater's `0022` umask
produces the shared read/execute permissions and the stopped acceptance probes
verify all three service identities can import the runtime. Gateway secrets
remain outside the checkout under inaccessible root-managed profile
directories.

Runtime lazy dependency installation is disabled. The reviewed bootstrap
installs required extras once; future dependency changes remain inside native
`hermes update` inside the dedicated update unit, never the live Gateway unit.
Hermes's no-key DDGS search provider is an upstream-supported post-setup
backend rather than a core locked extra. Astra explicitly selects it for
search-only web research. Bootstrap and the native update unit run the
idempotent `hermes tools post-setup ddgs` hook, using the reviewed managed `uv`
binary, so an environment rebuild cannot leave `web_search` nominally enabled
but unavailable. Dubble and Rigel do not receive web search by default; they
retain bounded handoff/canonical-source workflows instead of unnecessary
public egress. DDGS remains a rate-limited search backend and does not provide
page extraction; a credentialed extraction provider is an optional future
upgrade, not assumed parity.
Bundled skills are initially opted out; only reviewed, required skills are
seeded per role. Do not configure root-owned baseline skills only through
`skills.external_dirs` in managed scope: Hermes v0.20.0's lightweight runtime
skill loader reads the profile-local config directly and would ignore that
merged managed value even though `hermes config check` accepts it.

Hermes v0.20.0 otherwise starts a background Tirith installer when the scanner
is absent. The managed deployment disables that lazy path and authenticates the
initial Tirith release with exact SHA-256 plus `cosign` verification against
the official GitHub Actions identity and issuer. It installs that bootstrap
artifact at `/var/lib/hermes-updater/.local/bin/tirith`, owned by a dedicated
no-login identity. This location matters: Tirith classifies system paths such
as `/usr/local/libexec` as package-managed and refuses native self-replacement,
whereas its supported `~/.local/bin` layout is self-managed. Future scanner
updates therefore run unmodified `tirith update --yes --format json`, retaining
Tirith's mandatory signature check, atomic swap, previous-binary sidecar, and
native rollback. Service startup uses the absolute binary with
`TIRITH_OFFLINE=1`; attended deployment also proves one benign allow verdict
and one pipe-to-interpreter block verdict without network access.
The policy-schema transaction advances an existing profile-local config only
when it is the exact prior one-key version stub. Any profile with additional
mutable settings remains blocked for an explicit reviewed migration.

### Terminal Sandbox

Use Hermes's `docker` terminal backend with
`HERMES_DOCKER_BINARY=/usr/bin/podman`. Podman runs rootless under the matching
service account; there is no rootful Docker daemon, Docker group, or API socket
available to Hermes. Hermes officially scopes persistent terminal containers
by profile labels, and the separate Unix identities add a second boundary.

Mandatory baseline for every role that has terminal tools:

```yaml
terminal:
  backend: docker
  home_mode: profile
  docker_mount_cwd_to_workspace: false
  docker_volumes: []
  docker_forward_env: []
  docker_network: false
  docker_run_as_host_user: false
  container_persistent: true
```

Set CPU, memory, PID, and disk limits only after a live rootless-cgroup-v2 test
proves Podman enforces them; a configured but ignored limit is a failed gate.
The sandbox gets no host bind mounts, profile secrets, broker credentials, or
network by default. Generated files cross the boundary only through a bounded
export directory after extension, size, ownership, and path validation.

Dubble and Rigel start without terminal or code-execution toolsets. Astra gets
the rootless terminal only if transcript tests demonstrate a real need. Native
web tools handle research; shell network access is not required for browsing.

### Mandatory Hermes Policy

Root-owned managed scope enforces at least:

- manual command approvals and `cron_mode: deny`;
- no permanent command allowlist;
- memory and skill write approval enabled;
- agent-created skill scanning enabled;
- lazy runtime installs disabled;
- secret redaction, context injection scanning, SSRF protection, and website
  policy enabled;
- destructive slash-command and MCP reload confirmation enabled;
- no automatic hook acceptance;
- dashboard and API server disabled;
- a write-safe root limited to the role's export/work area; and
- only the minimum role-specific toolsets.

Hermes's native managed-scope loader is deliberately fail-open on parse errors,
so filesystem ownership alone is not the startup gate. Each profile unit first
verifies a root-owned SHA-256 manifest covering its managed `config.yaml` and
`.env`; any edit, truncation, or unapproved credential/policy change therefore
blocks startup before Hermes can ignore the managed layer. Both mutable and
managed config carry the release's reviewed schema version, and an older
non-empty mutable config requires an attended offline migration.

Hooks and plugins default to empty. Astra alone enables the reviewed
`star-dispatch-privacy` hook plugin. Root owns identical managed and runtime
trees; startup rejects inventory, ownership, mode, hash, configured-plugin,
hook-set, or tool-registration drift before the Gateway process runs. The
service bind-mounts the managed tree read-only over the runtime tree. Any other
hook or plugin still requires source review, provenance, a failure-mode test, a
rollback artifact, and explicit activation. Because Hermes hook consent keys
the command string rather than script content, an unchanged path with changed
bytes is untrusted until re-audited.

### Systemd And Network

Root owns one unit per role:

- `hermes-gateway-astra.service`
- `hermes-gateway-dubble.service`
- `hermes-gateway-rigel.service`

Each unit has one `User=`, one `Group=`, explicit `HERMES_HOME`, a minimal
`PATH`, its own environment file, its own runtime directory, an event-loop
watchdog, restart bounds, CPU/memory/task limits, and no capabilities. Apply
`NoNewPrivileges`, strict system and home protection, private temporary state,
kernel/control-group/module protections, and a restrictive umask. Keep the
namespace operations rootless Podman needs; reject hardening that silently
breaks the sandbox and causes fallback to local execution.

Hermes adds no administrative SSH path to the host and has no public inbound
listener or dashboard route. Profile services receive only the outbound paths
needed for selected model providers, Discord, and explicitly approved report
or broker endpoints. Rootless tool containers default to no network. Broker
exceptions are exact destination and port rules, not private-network ranges.

### Host Data And Action Brokers

Hermes never receives the controller's Ansible, SSH, Docker, Health, Git, or
vault credentials. Root-managed collectors on `jn-t14s-lin` use dedicated
read-only credentials to fetch bounded Health and Docker reports, validate
their schema/signature/age, and atomically publish root-owned read-only inputs
for Astra. Dubble and Rigel cannot traverse those paths.

The Docker inventory reporter is now platform-neutral under `agent-report`,
uses a prompt-resistant schema-v2 result, and includes backed, validation-gated
cleanup for the old OpenClaw reporter artifacts. It remains disabled until the
Hermes identity, source CIDR, and dedicated key are approved for live rollout.
The Docker update broker is also platform-neutral under `agent-update`. It
validates before exposing access, emits only token-safe results, preserves old
history without activating old approvals, and remains disabled until a target
and dedicated key are explicitly approved. Astra may submit a fixed-schema
proposal and later invoke only an already-approved, unexpired plan. It cannot
approve a plan, select arbitrary compose paths or commands, broaden targets,
or reach a Docker daemon.

### Backups And Recovery

Use both application and infrastructure backups:

- nightly `hermes backup` archives for each home, using SQLite's backup API;
- pre-update and pre-migration full Hermes backups;
- encrypted restic copies of profile homes and root-owned policy, excluding
  transient rootless container layers unless a test explicitly needs them;
- the existing managed host backup for `jn-t14s-lin`; and
- a manifest of code revision, config schema, profile declarations, bot-token
  identities, cron declarations, and backup hashes.

Restore tests use a channel-less clone with replaced credentials. A backup is
not accepted because an archive exists; Doctor, session search, memory, skills,
cron declarations, and one synthetic model turn must work after restore.

Immediate cutover rollback remains independent until Hermes acceptance: the
OpenClaw services, state, secrets, sessions, workspace, package runtime, and
backups remain available but stopped. Cutover does not reuse OpenClaw state
directories or run migration cleanup. After acceptance, OpenClaw stays disabled
and its files remain offline for operator-controlled reference. Hermes cannot
read them directly or treat them as an executable fallback.

### Gate 3 Acceptance

This design gate is complete when implementation assets express these
boundaries without installing Hermes:

1. The target is exactly `jn-t14s-lin`, its live CPU/RAM/disk preflight passes,
   and the contract rejects concurrent OpenClaw and Hermes gateways.
2. Service identities, homes, groups, units, managed scope, secrets paths, and
   rootless Podman prerequisites are explicit and lintable.
3. Every profile's allowed tools, Discord scope, inputs, outputs, and forbidden
   paths are machine-readable.
4. Shadow mode has no production token, scheduler delivery, dashboard, remote
   listener, host credential, or broker mutation authority.
5. Backup, restore, cutover, and OpenClaw rollback procedures have explicit
   pass/fail checks.
6. A static audit rejects Docker group/socket access, general sudoers, host
   mounts, cross-profile secret reads, local-terminal fallback, and allow-all
   Discord while requiring the exact Astra-only native-update trigger.

The credential-free machine-readable declaration is
`files/hermes/shadow-target.json`. The fail-closed validator is
`scripts/agents/hermes-shadow-target-audit.py`; it rejects unknown top-level
schema instead of using natural-language phrase matching. The declaration pins
`jn-t14s-lin`, forbids concurrent OpenClaw/Hermes gateways, forbids raw source
mounts or wholesale copies, and retains the source files offline.

## Gate 4 Declarative Runtime

The disabled-by-default implementation is
`playbooks/agents/hermes-shadow.yml`, with defaults under
`inventory/group_vars/hermes_hosts/`, policy under `files/hermes/`, and
rendered sources under `templates/hermes/`. The `hermes_hosts` inventory group
contains only `jn-t14s-lin`; the playbook is not imported by `site.yml` and its
default disabled mode cannot install or start Hermes.

Its modes are explicit:

- `disabled`: stop existing shadow units and end without mutation.
- `bootstrap`: require owner approval, a reviewed official-installer hash, and
  a reviewed immutable release tag plus expected commit; install/configure the
  isolated runtime, verify its origin/commit, and keep all units stopped.
- `shadow`: additionally requires attended start approval, creates readiness
  markers, and starts boot-disabled gateways without production Discord tokens,
  scheduler delivery, route, dashboard, or API listener.

Each profile has a distinct no-login OS identity, fixed home, subordinate-ID
range, root-owned managed scope, and hardened system unit. Agent command/file
execution remains disabled. The dormant terminal backend is rootless Podman
with no Docker group/socket, host mounts, host user mapping, forwarded
environment, forwarded credentials, or network. Managed-scope validation is
not treated as the sandbox: official Hermes documentation says malformed
managed YAML is ignored and filesystem ownership is its enforcement boundary.
The systemd/OS/Podman controls therefore remain independently required.

Validation on 2026-08-12 passed YAML lint, Ansible syntax, the structured target
audit, and 21 contract/deployment regressions. `ansible-lint` did not inspect the
playbook because the controller currently exposes an Ansible CLI 2.20.1/Python
module 2.21.0 mismatch; that validator-environment failure is not a Hermes
runtime result. No live host was changed and no Hermes runtime was installed.

## Source Migration Contract

`files/hermes/openclaw-state-migration-contract.json` is the source-wide Gate 5
classifier. It does not duplicate the existing path-level workspace policy.
Instead, it pins that policy by SHA-256, requires a handler for every legacy
disposition, and gives every top-level object outside the workspace one of
these explicit treatments:

- curated profile data import after review and parity;
- reconstruction as a disabled Hermes job, root-owned policy, or external
  service;
- cutover-only credential and identity re-enrollment without copying the
  source secret;
- queue drain and sealed archive without delivery replay;
- root-only offline archive for sessions, databases, logs, attachments,
  retired integrations, alternate workspaces, and runtime evidence; or
- discard only after a complete archive, parity, sampled restore, and separate
  retention approval.

The contract keeps all source mutation, source archival, source cleanup, live
migration, secret copying, messaging activation, and scheduler activation
unauthorized in this gate. OpenClaw session databases and trajectories do not
become Hermes sessions. Cron declarations are rebuilt disabled. The production
delivery queue must be reconciled and archived rather than replayed. Current
Discord, device, identity, provider, and Gateway credentials are re-enrolled
only at cutover. The Health database is the sole workspace rule override: it
remains owned by the dedicated receiver and requires a consistent SQLite
backup after the receiver is stopped. The retired Nextcloud Talk relay is
archive-only and is not migrated.

On 2026-08-13 the metadata-only state audit classified all 102 current
top-level entries: 45 directories and 57 files. The existing recursive
workspace auditor independently classified all 7,744 current workspace
objects under its 107 rules. Neither audit read file contents, followed a
symlink, changed the source, invoked the Hermes importer, copied a credential,
or activated a job or messaging route. Any future unknown top-level category,
workspace policy hash change, filesystem-kind drift, or top-level symlink
fails closed and requires an explicit review.

## Protected Importer Dry Run

The official importer is an advisory inventory source, not the migration
authority. `playbooks/agents/hermes-openclaw-dry-run.yml` deploys the pinned
shape-only contract and root wrapper only after explicit operator approval.
The wrapper builds a disposable source containing generic placeholders and a
disposable copy of Astra's inert target config. It copies no source text,
credential, identifier, session, transcript, prompt, executable code, or
symlink target. Top-level skill links contribute only an anonymous count.

The importer runs as the existing no-login `openclaw-migrate` account in a
transient systemd service with a private network, no capabilities, strict
system protection, and read-only source and target trees. The exact root-owned
Hermes venv link, resolved Python binary hash, `pyvenv.cfg` hash, importer
hash, release, and commit are pinned before execution. The wrapper passes no
execute, secret, output-directory, workspace-target, overwrite, cleanup,
archive-source, messaging, scheduler, or activation argument. Raw importer
items are discarded; retained files contain only source counts and totals by
kind/status, are root-owned mode `0600`, and the temporary view must be absent
before the playbook accepts the run.

The accepted 2026-08-13 run inventoried 125 shape objects: one config, one
approval policy, seven standard documents, 102 daily-memory placeholders, 11
workspace-skill placeholders, three shared-skill placeholders, and no project
skills. One shared-skill entry was a link represented only by count. The
aggregate report at
`/var/backups/hermes-openclaw-dry-run/20260813T233105Z` contained 23 advisory
"would migrate" results, 11 "would archive" results, 21 skipped results, and
zero errors. Secret migration and forbidden-option selection were both false.
All three Hermes gateways remained inactive and disabled, the OpenClaw and
Health service-state snapshots matched exactly before and after, and the
temporary work root was empty.

The report does not authorize any direct import:

- behavior, identity, user profile, and session proposals are replaced by the
  reviewed profile contracts;
- command allowlists are rebuilt through root-managed policy and brokers, not
  copied from OpenClaw;
- memory and daily memory enter profile-specific curation only;
- all skill proposals remain review-and-rebuild inputs, never copied code;
- cron, logging, memory-backend, and skills-config archive proposals are
  reconciled against their modern Hermes or external owners; and
- skipped credentials, providers, messaging, channels, plugins, hooks, MCP,
  browser, TTS, and Gateway categories remain excluded or cutover-only.

Three fail-closed corrections were required before acceptance. The first run
rejected a known shared-skill symlink; the durable fix anonymously represents
skill-link count without following the target. The initial transient service
could not traverse a `0700` work parent; it is now `root:openclaw-migrate 0710`
while evidence remains `root:root 0700`. Finally, using the canonical base
Python omitted Hermes venv dependencies, so the exact root-owned venv link and
complete resolution chain are now pinned. The importer also redacts its own
`migrate_secrets` boolean and reports excluded categories for reconciliation;
the wrapper therefore proves authority from the exact command and selected
options instead of misclassifying redacted fields or advisory item labels.

## Profile Import Contract

`files/hermes/profile-import-contract.json` owns the next Gate 5 boundary. It
pins both source classifiers by SHA-256 and maps every current workspace
`retain` rule exactly once: 24 sources to Astra, four to Dubble, and three to
Rigel. It also maps the two top-level curated categories, provider memory and
durable task state, to Astra staging. The contract grants no copy or runtime
authority; it only defines where reviewed data belongs.

Five import modes keep unlike data from being treated as generic memory:

- `data-stage` preserves normal user project data outside the prompt;
- `structured-transform` converts legacy runtime-shaped state into a typed
  target owned by the new workflow;
- `operator-reference` keeps authorization, configuration, and course
  references read-only and on-demand;
- `memory-curation` creates reviewable profile-specific memory proposals; and
- `private-reviewer-curation` preserves Vega and Antares evidence for private
  Star work without exposing reviewer prose to the user or promoting it into
  Astra's ordinary memory.

Every raw source has prompt injection disabled. Raw sessions, transcripts,
credentials, executable bits, symlinks, automatic memory approval, cross-profile
mounts, source mutation, and runtime activation remain forbidden. Dubble and
Rigel sources can target only their own isolated profile roots. The current
contract maps all 31 retained workspace rules and both state-root curation
rules with no duplicate targets or unmapped source. Fourteen negative
regressions enforce those boundaries. That contract copied no raw profile data;
only the separately reviewed compact memory transaction below has changed live
Hermes profile state.

## Curated Profile Memory

Raw legacy daily memory is not promoted into Hermes prompts. It remains an
offline operator reference. `files/hermes/profile-memory-contract.json`
declares four compact Ansible Vault ciphertext seeds: `MEMORY.md` and `USER.md`
for Astra, and the same pair for Rigel. Dubble starts with an empty memory store
instead of inheriting historical incidents or another profile's preferences.

The managed Hermes limits are the documented compact defaults: 2,200
characters for `MEMORY.md` entries and 1,375 for `USER.md`. The staging
validator imports the parser and threat scanner from the exact installed
Hermes runtime, rejects symlinks and executable files, enforces clean native
entry round trips, and emits no seed text. Agent-written memory remains
approval-gated after cutover.

`playbooks/agents/hermes-profile-memory.yml` is disabled by default and has no
Gateway, scheduler, messaging, credential, or model path. An approved run
requires all three Gateways stopped and boot-disabled, verifies Dubble is
empty, backs up all three stores, decrypts only into a root-private transient
directory, installs the four files atomically, revalidates each file as its
service identity, compares exact SHA-256 checksums, and restores all three
stores if any post-install or service-state proof fails.

The accepted 2026-08-13 staging installed four mode-`0600` files owned by the
matching Astra and Rigel identities. Their file sizes are 1,797, 1,346, 551,
and 278 bytes; all four passed the native scanner and clean parser round trip.
Dubble remained empty, decrypted staging was absent afterward, all Hermes
Gateways remained inactive and disabled, and the production OpenClaw and
Health user services remained active and enabled. The pre-seed rollback is
`/srv/live-rollbacks/jn-t14s-lin/hermes-migration/20260813T235259Z-pre-profile-memory`;
its manifest hash matches the retained archive.

The first live attempt exposed an Ansible transport issue: `become_user`
could not create a module directory beneath the controller's root-only remote
temporary path. The transaction restored all three stores before failing. The
durable path now invokes the content-free validator through root-controlled
`runuser`, and both identity execution and the complete retry passed.

The subsequent stopped-Gateway convergence updated all three root-managed
configs to 2,200/1,375 and regenerated their policy checksum manifests. Hermes
native `config check` passed as each service identity, the manifests verify,
and a complete second bootstrap run reported zero changes. Production OpenClaw
and Health remained active and enabled; the Hermes Gateways remained inactive
and disabled. The pre-change config rollback is
`/srv/live-rollbacks/jn-t14s-lin/hermes-migration/20260814T000527Z-hermes-managed-memory-limits`.
Check-mode safety probes now explicitly execute instead of returning empty
Ansible placeholder results, and native merged-config validation occurs during
every bootstrap before checksum promotion.

## Reviewed Profile Skills And Data

Five legacy procedural areas have been rebuilt as declarative Hermes-native
skills rather than copied from mutable phrase-triggered trees. Their
root-owned sources are staged per profile, parsed and threat-scanned by the
exact installed Hermes runtime, bound read-only under each profile's native
skill root, and checked through Hermes's own runtime skill index before any
Gateway can start. The accepted inactive transaction left all Gateways stopped
and production OpenClaw and Health unchanged.

Normal project data is a separate boundary from memory and skills.
`files/hermes/profile-data-stage-contract.json` permits only the 16
`data-stage` mappings and four `operator-reference` mappings already assigned
by the pinned profile-import contract. Current planning selects 1,195 objects,
1,125 files, and 752,637,034 bytes: 1,120 Astra files, four Dubble files, and
one Rigel reference file. The bulk is user project/media data; it is not loaded
into a model prompt.

`playbooks/agents/hermes-profile-data.yml` is disabled by default. An approved
run requires every Hermes Gateway stopped and boot-disabled, verifies the
OpenClaw source and both source-contract hashes, copies into a root-private
generation without links or executable bits, verifies source stability and
every content hash, records a root-only rollback artifact, and promotes the
complete generation as one transaction. Writable project data is owned by the
matching no-login profile. Managed authorization, configuration, and course
references are root-owned and read-only at runtime. The active generation root
is root-owned execute-only traversal (`0711`); each profile subtree is `0750`
with a distinct group, so a profile can verify and enter only its own sources.
The full manifest is never exposed to a profile; a fixed root preflight
verifies it, then an unprivileged preflight proves only that profile's exact
writable and read-only bind pair.

Memory curation, private reviewer evidence, structured transforms,
credentials, sessions, transcripts, delivery queues, provider state, and raw
prompt injection are excluded from this transaction. The original OpenClaw
tree remains untouched and unmounted. Gateway, model, Discord, scheduler, and
readiness activation are outside this playbook.

The accepted 2026-08-13 transaction installed all 1,125 files and
752,637,034 bytes. The root-private mode-`0400` manifest strictly revalidated
in the post-install check run, and all three transient service namespaces
proved the exact writable/read-only bind pair as their no-login identities.
The active generation root is `root:root 0711`; profile roots and data retain
their distinct group and mode boundaries. Production OpenClaw and Health
remain active and enabled, both isolated OpenClaw canaries remain active but
boot-disabled, and all Hermes Gateways remain inactive and disabled. A full
stopped-bootstrap convergence afterward reported zero changes. The successful
pre-data rollback is
`/srv/live-rollbacks/jn-t14s-lin/hermes-migration/20260814T012914962035272Z-pre-profile-data`;
its recorded archive SHA-256 matches the retained artifact.

The first live attempt was intentionally rejected by its unprivileged
namespace proof after copy and promotion because the initial active root mode
`0700` blocked a profile from traversing to its own source path. The rescue
removed the generation and manifest, restored the prior absent state, and left
no staging tree. The corrected `0711` top level grants traversal but no list or
read permission; each `0750` profile subtree still rejects every other profile.
The failed-attempt rollback and the targeted pre-correction contract/stager
rollback remain under the same live-rollbacks domain for diagnosis.

Structured legacy runtime state is a separate transaction from copied project
data. `files/hermes/profile-transform-contract.json` declares exactly six
conversions and seven input objects. The root-owned transformer parses and
canonicalizes FreshRSS dedupe state, Reddit sync state, the private sobriety
tracker, Nextcloud task state, an empty Dubble user registry, and Rigel's
completed-semester/calendar-request source. It neither copies nor mounts the
169 MB Rigel course archive into a profile.

Rigel migration is intentionally fail-closed. The legacy source is accepted
only when it explicitly identifies a completed semester, says there are no
upcoming exams, and has no pending calendar request below its marker. Active,
ambiguous, or pending state must be curated into the native academic schema by
an operator instead of being guessed from Markdown. The accepted migration
produces zero events and zero calendar requests, so the always-on 30-minute
evaluator is immediately idle and emits no stdout, reasoning text, token, or
Discord message.

`playbooks/agents/hermes-profile-transforms.yml` stages the small generation
under `/var/lib/hermes/profile-transforms`, records a root-only manifest and
rollback archive, verifies stable input/output hashes, then proves each
no-login profile sees only its own writable bind and read-only managed bind.
The Hermes Gateway units verify both the root manifest and unprivileged bind
identity before start. This component remains disabled until an attended
staging run and does not start a Gateway, model, scheduler, or messaging route.

## Behavior And Self-Evolution

The replacement does not use a plugin or phrase table to decide when Astra
should research, compare hardware, perform RCA, or learn. The root-owned
`AGENTS.md` for each profile is always loaded with its `SOUL.md`. Astra selects
evidence from the request's intent, stakes, uncertainty, exact object, current
thread, and durable project state. Dubble and Rigel have separate operating
contracts and cannot read Astra's policy or data through a shared profile.

Hermes' native background review is the semantic self-evolution mechanism. It
runs after a turn and can propose compact memory or procedural skill changes.
Both `memory.write_approval` and `skills.write_approval` remain enabled in the
root-managed config, so foreground and background writes are staged rather
than applied. Pending proposals survive restart and are reviewed with
`/memory pending`, `/memory approve`, `/memory reject`, `/skills pending`,
`/skills diff`, `/skills approve`, and `/skills reject`. Background memory
notifications are off so this mechanism does not append another process wall
to an otherwise normal answer. Official behavior and approval semantics are
documented under
[persistent memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory/)
and [skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/).

The agent may propose only three writable outcomes: user preference/stable fact
memory, profile memory, or a reusable profile skill. Behavior, security,
deployment, tool authority, `SOUL.md`, and `AGENTS.md` remain root-owned and
outside agent write access. The agent cannot approve its own proposal. If an
existing general rule already covered a failure, the correct outcome is a
regression or enforcement proposal, not another incident-specific reminder.

`files/hermes/behavior-regressions.json` converts the saved private transcripts
into 12 sanitized promotion cases without copying transcript text, private
paths, or platform identifiers into the repository. The cases cover antecedent
resolution, current regional research, purchase-state reconciliation,
compatibility versus performance, direct decisions, useful walkthrough
checkpoints, expected absence, incident RCA, scope/preferences, concise Star,
source-backed alerts, and correction generalization. Static tests prove the
policy and deployment shape now; Gate 7 must still run the cases against the
actual isolated model before promotion.

The corpus assigns each case to its real execution owner. Nine reasoning cases
run privately through `scripts/agents/hermes-behavior-acceptance.py` and require
independent Vega and Antares semantic pass verdicts. Current regional research
waits for the reviewed live-evidence route, idle absence remains owned by the
deterministic Rigel evaluator, and concise Star synthesis remains a Gateway
integration test. The runner must not collapse those three boundaries into a
generic model prompt merely to report a complete gate.

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
