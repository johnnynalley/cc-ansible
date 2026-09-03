# Hermes Replacement And Modernization

## Status

The official Nous Research Hermes Agent is the production runtime on
`jn-t14s-lin`. Astra, Dubble, and Rigel are active as three distinct Discord
applications, profiles, service identities, and Gateways. OpenClaw delivery
and update units are stopped and disabled, while their files remain offline
for reference and operator-controlled rollback.

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
- Give Hermes no general sudo, Docker socket, Docker group, human home,
  Ansible vault, controller SSH keys, or unrestricted host shell. Astra's only
  sudo authority is the exact native-updater start and named-Gateway lifecycle
  commands required by Hermes's own update flow.
- Add Docker inventory, version reporting, and updates only through separate
  fixed-schema forced-command identities. Immediate updates require native
  turn-bound approval; the existing external systemd schedule remains automatic.
- Keep exactly one production messaging and scheduler path during cutover.
- Let Hermes own Gateway service lifecycle through native named-profile units.
  Ansible may add security/readiness drop-ins, but must not replace native
  `ExecStart`, restart, watchdog, identity, `HOME`, or `HERMES_HOME` behavior.
  The current stable native units do not define `ExecStop`; every operator stop must
  use Hermes's planned-stop marker before systemd sends `SIGTERM`.
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
complete security boundary against prompt injection. File-write guards do not
constrain shell commands. Astra therefore runs native local tools as the
dedicated no-login `hermes-astra` account, with no sudo, Docker socket/group, or
Linux capabilities and with systemd restricting writes to its owned profile and
reviewed work roots. Dubble has no local tools; Rigel has native file and local
terminal tools confined to its isolated academic workspace and unprivileged
service identity.

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
| Lossless conversation context | Reviewed stable `hermes-lcm` plugin with separate profile-owned databases and source-preserving conversion from stopped OpenClaw history | Native plugin with conversion | Astra and Rigel reconcile their approved scopes; Dubble imports only route-proven public history; SQLite integrity passes and source state remains unchanged |
| Mem0/Qdrant knowledge | Hermes OSS Mem0 provider backed by separate Astra, Rigel, and Dubble v3 hybrid collections | Native provider with conversion | Astra/Rigel source boundaries reconcile; Dubble starts empty because legacy provenance is unresolved; every profile proves dense and BM25 recall without cross-profile points |
| Self-evolution | Hermes background review with approval-free guarded profile-local memory and skill writes; Astra alone reviews and writes the shared fleet skill | Native with isolated ownership | A correction improves the owning native memory/skill, does not mutate root policy, and shared changes are evidence-backed, validated, audited, and reversible |
| Owner-directed agent administration | Astra-only native fleet tool backed by an authenticated typed broker for Astra, Dubble, and Rigel native profile/workspace state | Native with owner provenance | An exact owner Astra session can inspect, hash-guard, back up, mutate, validate, and restart any profile while target sessions and users cannot call the broker, disclose cross-profile data, or rewrite root-owned policy |
| Astra root-cause learning | Root-owned behavior policy plus review-gated agent memory/skills and transcript regression tests | Manual policy port | Repeated incidents consolidate into a general rule; incident-specific rule accumulation is rejected |
| OpenClaw sessions and trajectories | Preserve as offline searchable archive; new Hermes sessions live in each profile's SQLite state | Archive, not live migration | Archive manifest, sampled transcript restore, and Hermes access through a read-only search boundary if later required |
| Native scheduled jobs | Import the reviewed 17 Astra, one Dubble, and one Rigel declarations once, then leave each profile's native cron store authoritative | Native after one-time seed | Read-only declaration audit, missing-only seed, explicit exact restore, native edit persistence across restart, and natural delivery receipts |
| 10 deterministic command jobs | Root-managed unprivileged systemd services/timers or no-agent Hermes prechecks | Replace | Empty stdout is silent, failures are bounded and classified, and no Gateway credential enters the worker |
| Main heartbeat catalog | Deterministic collectors and per-check state feed bounded semantic jobs; do not fan out the full catalog in one turn | Manual modernization | Existing cadence, pressure gates, dedupe, and maximum concurrency are regression-tested |
| Discord | Two isolated Gateways and bot tokens, explicit user/channel allowlists, DMs denied, and nonempty pairing grants rejected at startup | Native | Unauthorized user, unauthorized channel, duplicate token, DM, attachment, pairing-state, and restart tests |
| Health receiver | Retain the current isolated receiver and aggregate report publisher; Hermes reads only the aggregate report | Retain externally | Hermes cannot read token, raw database, row-level records, or source-device names |
| Docker visibility and updates | Separate result-only reporter and fixed trigger for the existing Ansible-selected updater | Retain externally with native approval | No Docker socket/group/shell; strict response schemas; scheduled updates remain automatic; immediate runs require a fresh turn-bound approval |
| Model routing | Per-profile providers plus a named MoA preset for Star; no policy-level exact-version pin unless explicitly approved | Native with reconciliation | Provider auth, context size, fallback, model identity, and no unintended exact pin are verified |
| Hooks and plugins | Default to none. Add only root-reviewed hooks or plugins required by a proven parity gap | Manual | Hash/provenance, consent, tool scope, failure mode, update behavior, and rollback are documented |
| Dashboard and API | Disabled during shadow and initial production; any later UI remains loopback-only behind independent authentication | Deliberately omitted | No listener or remote route exists during initial rollout |
| Backups and rollback | Full native profile archives for short-horizon rollback plus application-consistent SQLite/Qdrant staging in encrypted Restic on NAS ZFS | Native plus managed DR boundary | Native profile extraction, complete staged-artifact verification, disposable Qdrant restore, and replacement-node recovery order are tested |

## Backup And Node-Loss Recovery

Hermes recovery has two independent layers with different failure domains:

1. `hermes backup` creates a full archive for each discovered profile. These
   same-node archives are the fast rollback path for a bad agent, skill,
   schedule, or configuration change. They include profile configuration,
   skills, sessions, memory, and data, but they are not node-loss protection.
2. Before each `jn-t14s-lin` local Restic run,
   `/usr/local/libexec/hermes-disaster-recovery-stage` refreshes every native
   profile archive, creates SQLite online-backup copies with
   `PRAGMA quick_check`, and downloads one Qdrant full-storage snapshot after
   proving Qdrant is single-node and collection point counts stayed stable.
   The immutable manifest and artifacts are verified before Restic can copy
   them to the encrypted per-host repository on `nas-zfs`.

The Restic snapshot also includes the complete mutable Hermes roots under
`/var/lib/hermes`, `/var/lib/hermes-automation`, and `/etc/hermes`, plus the
controller checkout and owner home needed for rebuild reconciliation. It also
retains `/var/lib/tailscale`, which is native mutable node and Serve state
needed to recover the T14s identity and named service advertisements without
making Ansible the authority for their contents. Large
rebuildable caches, duplicated evidence worktrees, rootless container storage,
and the raw live Qdrant directory are excluded from the local repository;
Qdrant is recovered from its application-consistent snapshot instead.

Ansible ownership is enforced by
`files/hermes/ansible-ownership-contract.json` and
`scripts/agents/hermes-ansible-ownership-audit.py`. The audit scans every
absolute host-path reference in all Hermes agent playbooks, the Restic
disaster-recovery playbook, and the owning inventory declarations. Every path
must resolve to one reviewed class: rebuildable platform, bootstrap seed,
mutable native state, migration, restore-only, evidence, rollback, transient,
cache, external read-only state, legacy retirement, or a forbidden interface.
The most-specific prefix wins, so a native profile path cannot be hidden by the
broader root-owned `/var/lib/hermes` platform layout. New unclassified paths
fail `scripts/repo/repo-audit`.

TS440 runs `restic-snapshot-freshness@hermes-jn-t14s-lin.timer` independently
of the source node. It requires a snapshot no older than three hours containing
`/var/backups/hermes-disaster-recovery/current` and sends a deduplicated Apprise
alert when the proof is missing or stale. This is the source-node-loss alert;
the source-side status file alone is not sufficient when the T14s is offline.

The retired complete OpenClaw source is preserved once as the root-only,
SHA-256-verified SquashFS image under
`/srv/live-rollbacks/jn-t14s-lin/hermes-openclaw-evidence/20260826T192343Z/`.
T14s mounts that immutable image read-only at `/home/johnny/.openclaw`; the
redaction overlay and Astra-only bindfs view continue to consume the historical
contract path. The mount is rebuildable platform state in
`inventory/host_vars/jn-t14s-lin/mounts.yml`, while the image is retained data
owned by nas-zfs snapshots rather than Ansible. Restore `/srv/live-rollbacks`
first, run the filesystem-mount playbook second, and converge the Hermes
OpenClaw evidence playbook third. The projection unit must create its volatile
`/run/hermes-openclaw-evidence` tree with `RuntimeDirectory=` and recreate the
Astra-only `view` mountpoint before each bindfs start; never rely on a
pre-reboot directory under `/run`. The service starts as root only to assemble
the root-only source and redaction overlay, uses the reviewed profile-reader
group, and exposes the final view through a `0710` runtime parent; this does not
grant Astra direct access to the sealed source. The periodic audit timer uses
`OnActiveSec=1h` plus `OnUnitActiveSec=6h`. A changed timer is restarted once
to establish the first monotonic deadline, while an unchanged waiting timer is
left alone. Local Restic excludes the loopback view because its immutable
backing image is already on nas-zfs; normal offsite backup policy for
`/home/johnny` remains independent.

Hermes currently has a native `backup` command but no native `restore`
subcommand. A profile rollback therefore extracts its full archive into a new
private Hermes root, restores the service identity ownership, runs static
Doctor and SQLite integrity checks, and only then performs an attended atomic
cutover. Node-loss recovery rebuilds the platform with Ansible first, restores
the mutable roots and staged artifacts from Restic second, then restores the
Qdrant full-storage snapshot into a compatible server. Qdrant full snapshots
must be restored to the same minor version or the next minor version, followed
by exact collection-name and point-count verification. See the official
[snapshot](https://qdrant.tech/documentation/snapshots/) and
[recovery operations](https://qdrant.tech/documentation/operations/snapshots/) guidance.

Do not claim this layer healthy from a successful backup service alone. The
acceptance gate requires a local native-profile rollback rehearsal and an
off-host Restic restore into disposable storage, including an actual Qdrant
start and exact manifest comparison, without modifying production Qdrant.

The remaining platform-order gate uses
`playbooks/agents/hermes-replacement-node-rehearsal.yml` with
`inventory/hermes-replacement-rehearsal.ini`. That inventory contains no
production target. With the exact attended confirmation, the play builds a
fresh credential-free Ubuntu systemd container through rootless Podman, applies
the same `hermes-shadow.yml` platform/bootstrap boundary used for production,
requires Astra, Dubble, and Rigel to remain stopped and disabled, rejects all
Discord enrollment, validates the native updater/runtime wiring, and removes
the accepted container and image. The disposable proof retains the production
CPU contract but uses bounded 4 GiB available-memory and 4 GiB free-disk floors
because it shares the already-running production host; the real replacement
target still requires the full production capacity contract. This proves the
required recovery order:
rebuild the platform first, then apply the separately verified Restic mutable
restore and Qdrant recovery layers.

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

`files/hermes/star-regressions.json` defines seven runtime promotion cases:
seeded premise error, purchased-item reversal, current-source conflict,
reviewer independence, single normal answer, and reviewer failure. Static
policy tests do not establish model behavior. The seventh case proves that an
ordinary low-cost reversible pilot bypasses Star and receives a prompt initial
answer. Gate 7 must prove two actual child calls, Antares's adversarial value,
concise Discord output, failure handling, and the reversible-pilot bypass
before Star parity is accepted.

## Discord Routing And Cutover

The retained OpenClaw configuration has two Discord applications. Astra's
application served both `#astra` and `#rigel`; Dubble had the second
application. Hermes initially retained that transport shape as a compatibility
fallback, but it is not the final parity topology. The managed target uses a
new third Discord application for Rigel, with one bot token, service identity,
profile, Gateway, channel route, and scheduler per logical role. Native Hermes
token locks are a last defensive check, not permission to overlap consumers:
OpenClaw and Hermes must never use the same Discord identity concurrently.
Bot-authored input is disabled.

All three logical profiles have independent full-parity requirements. During
the transition, `#rigel` remains transported by Astra so the route stays usable.
Promotion removes that fallback only after the dedicated Rigel bot proves its
identity and exact guild/channel access. Rigel must then load its own
instructions, study skill, course/calendar state, memory, model route, schedule,
and behavior contract. Astra Gateway health or generic skill discovery is not
Rigel acceptance. Dubble likewise retains its own independent behavior and
state contract despite the shared host runtime.

Hermes busy-session input is managed as `queue`, not the native `interrupt`
default. Each conversational message received while a turn is active is
preserved as a separate per-session FIFO turn. The active answer is delivered
first, then queued follow-ups drain in arrival order; text messages are not
newline-merged. Native `/stop`, `/new`, and `/reset` remain the explicit ways
to cancel or replace work. Hermes caps the busy queue at 32 entries and carries
queue-mode input across a planned Gateway restart. The delivery ledger begins
only after a final response exists, so it cannot repair a response suppressed
before delivery registration; preventing interruption at the input boundary is
the required fix for that failure class.

Native cron execution completion and Discord delivery are separate acceptance
signals. Every scheduled platform send appends a content-free child receipt to
the native execution ledger with the execution ID, target, delivery status,
timestamp, and platform message ID when the adapter returns one. A timeout that
the adapter confirms as sent is recorded as `assumed_delivered`; receipt
persistence failure makes the delivery result fail without retrying the send
and risking a duplicate. `hermes cron runs` is the operator interface for these
receipts. `last_status=ok`, a completed execution, or a fresh producer artifact
alone is not proof that Discord received Daily Summary, Fortnite, or another
scheduled report.

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
4. Enroll three distinct Discord identities and all three provider scopes.
   Prove Rigel's new identity can access the exact existing `#rigel` route,
   remove the Astra-owned fallback from the rendered policy, then start and
   prove Astra, Dubble, and Rigel as separate consumers.
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

Production currently has 19 reviewed native jobs: 17 owned by Astra, one by
Dubble, and one by Rigel. The original declaration is retained as migration
and disaster-recovery evidence, but each service-owned `cron/jobs.json` is the
normal source of truth after the one-time import. Gateway startup validates
the immutable OpenClaw parity contract and never runs exact cron
reconciliation. Normal `hermes-automation.yml` convergence uses schedule mode
`preserve`; it reports content-free drift counts and does not add, remove, or
rewrite native jobs.

Schedule reconciliation is an explicit operator action with separate modes:

- `audit` compares reviewed managed declarations without mutation. It ignores
  unrelated profile-authored jobs and returns a distinct drift status.
- `seed` creates only missing reviewed jobs. It preserves edited managed jobs,
  stale managed rows, and profile-authored jobs, and rejects an unmanaged name
  collision rather than adopting it.
- `restore` performs exact reviewed restoration and may update or remove
  managed rows. It requires its own exact confirmation string and a current
  rollback set.

A live persistence proof created a disabled Astra-native job with the Hermes
CLI, restarted only Astra, verified the same paused job remained, confirmed
the managed audit still reported zero changes, and then removed the test job
through the native CLI. Dubble and Rigel retained their exact PIDs throughout.
This is the acceptance boundary for native schedule ownership; Ansible remains
the platform/bootstrap/restore mechanism rather than the continuous owner of
mutable schedules.

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

The retired `health-receiver.service` user unit was preserved through messaging
and scheduler handoff, then replaced by `hermes-health-receiver.service` after
an authenticated canary and rollback-backed cutover. The supported rebuild path
is `playbooks/agents/hermes-health-receiver.yml`; raw Health rows and the upload
token remain isolated from model-visible Hermes profiles while aggregate-only
reports remain available. No Siri relay unit is active, and migration is
forbidden from recreating one.

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
12. Self-evolution applies a general correction to isolated native state and
    cites the triggering failure. Shared-skill changes remain Astra-reviewed;
    no profile can rewrite root-owned security, runtime, or deployment policy.

## Security Boundary

The target uses three dedicated no-login Hermes profile identities and three
active Gateways. The active-consumer selector resolves to Astra, Dubble, and
Rigel for runtime, memory, Docker inventory, and offline-maintenance
transactions. Profile state is writable only where Hermes requires runtime
state. Behavior policy, typed host access plugins, systemd units, and
deployment configuration remain root-owned. Astra receives only explicit
typed administration paths, including the owner-session-only three-profile
native fleet boundary; it does not receive general root, root-policy mutation,
or unrestricted cross-profile filesystem access.

Initial production policy:

- Astra uses Hermes's native `local` terminal plus file and code toolsets as
  `hermes-astra`. That account has no sudo, Docker group/socket, Linux
  capabilities, cross-profile access, or write access outside its private
  profile and reviewed work roots. This is normal host tool access, not a
  wrapper-per-action interface.
- Dubble has no terminal, file, or code-execution toolsets. Rigel has native
  file and local terminal tools only in its owned academic workspace, as the
  unprivileged `hermes-rigel` identity, with terminal-originated network,
  runtime-secret, host-administration, and cross-profile access denied.
- `computer_use` is explicitly disabled for every profile. Browser retrieval
  remains available for current-source research, but no agent receives desktop
  control merely because Hermes includes that tool in its built-in safe set.
- Cross-host Docker facts and managed updates remain exposed through the
  existing fixed-schema, independently authenticated forced-command boundary;
  ordinary work on `jn-t14s-lin` uses Astra's native non-root tools.
- `approvals.mode: manual`, an empty permanent command allowlist, and
  destructive session confirmations are enabled. Astra cron uses manual
  approval policy; Dubble and Rigel deny cron commands.
- Explicit Discord allowlists; no allow-all mode.
- `memory.write_approval: false` and `skills.write_approval: false` for guarded
  profile-local evolution. Root-managed policy and shared-skill authority remain
  outside ordinary profile writes.
- Agent-created skill scanning enabled; third-party skills are not installed
  until inspected and pinned by provenance, not by stale application version.
- The retained reviewed-skill baseline is declarative, exact-hashed, and
  root-owned under `/etc/hermes/<profile>/skills`. It remains mounted read-only
  at `~/.hermes/skills/managed` as a validated rollback source during the
  ownership transition. `hermes-profile-skills.yml` may audit it without
  mutation or restore it only with explicit approval; ordinary convergence
  must not re-project it over agent-authored state. The accepted target moves
  ordinary skills into each profile-owned native root and keeps one canonical
  `self-evolution` tree writable only by Astra and read-only to Dubble/Rigel.
  `hermes_native_profile_skills_enabled` is the default-off unit-layout gate
  for that handoff. It must be enabled only in the attended import transaction
  after all 39 installed skill instances and supporting files are backed up,
  copied into native roots, validated, and covered by off-host rollback. In
  native mode the broad managed-skill bind disappears; Dubble and Rigel receive
  only Astra's local `skills/self-evolution` through a read-only bind.
- No auto-accepted hooks. Any hook is root-reviewed and its consent record is
  audited after edits because Hermes hook consent keys the command path, not
  script content.
- Prompt-injection scanning and secret redaction enabled. Tirith is bootstrapped
  from an exact official release after Sigstore identity and signed-checksum
  verification, then maintained by its own signed atomic updater in a
  root-owned, capability-empty systemd sandbox. Tirith 0.4+ updates the scanner
  and `/usr/local/libexec/tirith-package-approval-authority` as one signed
  transaction, so the unit can write only `/var/lib/hermes-updater` and
  `/usr/local/libexec`. Gateways use only the absolute binary, run it offline,
  reject runtime lazy installs, and fail closed on scanner errors. Hermes's
  background downloader is never part of the production path.
- Dashboard/API disabled. Gateway listeners remain loopback-only unless a
  separately authenticated Tailscale proxy is deliberately approved.
- Egress is restricted to required model, web, Discord, aggregate-report, and
  fixed-action endpoints. Private/link-local metadata destinations remain
  blocked.
- The Hermes profiles have no general sudo or supplementary group that can
  write controller code, read secrets, or administer containers. Astra alone
  may start the exact native update service and restart/reset the three named
  Gateway units; Dubble and Rigel have no sudo. The automatic timer invokes the
  same update service without model involvement.
- The native update unit sets uv's documented
  `UV_LINK_MODE=copy` behavior so cache files cannot become hardlinked to the
  shared runtime tree and normal updates do not emit hardlink fallback noise.

This boundary assumes any user-authorized agent conversation can be malicious.
Messaging authorization limits who can ask Hermes to act; it does not make
prompt content trustworthy. Tirith and the native prompt scanner are heuristic
defenses, not containment. Separate no-login identities, systemd confinement,
disabled host-execution toolsets, and narrow authenticated forced commands
remain the authority boundary even when a scanner misses adversarial content.

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

Hermes uses three no-login service users, separate account homes under
`/var/lib/hermes/*`, native named-profile homes below each account's
`.hermes/profiles/` directory, and root-owned policy and secrets. Astra and
Rigel use native local backends within their separate service accounts and
hardened systemd namespaces; Dubble exposes no terminal tools. `ProtectHome=true`,
separate UIDs, and the absence of raw-source mounts prevent Hermes from reading
the OpenClaw tree or the controller user's home. Memory conversion runs as a
separate attended root-controlled transaction against stopped source state and
writes only new Hermes-owned stores.

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

| Identity | Account home | Native profile home | Authority |
| --- | --- | --- | --- |
| `hermes-astra` | `/var/lib/hermes/astra` | `/var/lib/hermes/astra/.hermes/profiles/astra` | Primary conversation, native non-root local tools, web research, review synthesis, LCM/Mem0 recall, guarded native learning, aggregate reports, and inventory-derived cross-host Docker tools; temporarily retains the Rigel route until dedicated promotion |
| `hermes-dubble` | `/var/lib/hermes/dubble` | `/var/lib/hermes/dubble/.hermes/profiles/dubble` | Public support only; no terminal, host report, infrastructure, update, or cross-profile credential access |
| `hermes-rigel` | `/var/lib/hermes/rigel` | `/var/lib/hermes/rigel/.hermes/profiles/rigel` | Dedicated academic conversation, study skill, course/calendar state, memory, model route, vision, no-agent reminder schedule, and unprivileged local C++ coursework tools confined to its owned academic workspace |

Each native profile home has independent config, auth, state database, memory, skills,
sessions, cron, pending approvals, cache, sandbox metadata, and logs. Files are
mode `0600` and directories `0700` unless a documented root-owned input needs a
narrow group read. No service identity is a member of another profile's group.

Common mandatory policy lives in root-owned `/etc/hermes/` managed scope.
Role-specific identity and behavior sources live under
`/etc/hermes/profiles/<role>/` and are read-only bind-mounted over the runtime
view by systemd. Hermes runtime data remains writable; root policy, service
units, fixed-access plugins, and acceptance tests do not.

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
--extra messaging --extra mem0 --locked` to succeed without fallback. Keep
`uv`'s cache and managed Python
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

One reviewed reliability correction is maintained as a committed
`astra-managed-parity` branch rather than an uncommitted source edit. It
persists the complete accepted inbound event FIFO before Gateway teardown,
including message, media, routing, profile, and trust fields; restores those
events through normal adapter/session dispatch; and acknowledges each event
only after that event's turn and transcript/session writes succeed. Production
convergence applies the patch in an isolated Git worktree, validates and
compiles the exact four changed paths, commits before switching the live
checkout, and takes a full Git bundle first. Hermes's supported
`updates.parked_branch_strategy: update_in_place` keeps the maintained branch
checked out and merges `origin/main` into it during native updates. A merge
conflict aborts the update without dropping the patch, and a source validator
runs after every successful native update.

The oneshot runs as `hermes-astra`, not root, and invokes the native CLI entry
directly so it cannot recurse through the launcher trigger. This lets Hermes use
its normal private mode-`0700` profile home without ACL or group exceptions. The
unit does not set `HERMES_MANAGED_DIR`; the entire root-managed Astra directory
is inaccessible to it, so Hermes cannot load the Gateway's credentials while
updating. It has no Linux capabilities. Profile-authored behavior remains
profile-owned; security policy, plugins, managed support scripts, and retained
evidence remain root-owned and read-only. Hermes's own restart logic may issue
only `reset-failed`, `start`, and `restart` for the three enumerated Hermes
Gateway units. Together with the exact update-unit trigger, those commands are
Astra's entire sudo surface. Dubble and Rigel have no sudo authority.

The same native oneshot is scheduled automatically after production cutover.
It is now enabled in production together with Tirith's native updater. Hermes's native
default quick snapshot protects critical Astra state before code or dependency
changes; the retained host migration backup protects the complete profile,
checkout, and separately managed Dubble and Rigel profiles. Config checks and
policy hashes remain startup gates, not a replacement update pipeline.

Hermes intentionally excludes the optional `messaging` and `mem0` profiles from
`all`. Bootstrap therefore synchronizes both official extras from the reviewed
lock, and the native update unit reconciles the current source tree's official
`messaging` and `mem0` extras after Hermes completes its own update. The updater runs with
the code-only `hermes-runtime-readers` primary group, then normalizes that
shared credential-free checkout and restarts Astra, Dubble, and Rigel through the same
exact-command sudo boundary. This does not grant access to another profile's
home, managed environment, token, memory, or imported data.

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
seeded per role. The currently retained root-owned baseline is bind-mounted at
`skills/managed` and validated through the same `skill_view` path cron uses.
That path is a migration/restore baseline, not the mutable ownership target.
Hermes searches the profile-local native skill root before configured external
roots, and treats external roots as externally owned for autonomous lifecycle
maintenance. The ownership migration therefore seeds ordinary skills into the
profile-local root and uses a separate Astra-owned shared path for
`self-evolution`; it must remove duplicate-name ambiguity before retiring the
retained bind.

Hermes v0.20.0 otherwise starts a background Tirith installer when the scanner
is absent. The managed deployment disables that lazy path and authenticates the
initial Tirith release with exact SHA-256 plus `cosign` verification against
the official GitHub Actions identity and issuer. It installs that bootstrap
artifact at `/var/lib/hermes-updater/.local/bin/tirith` and installs Tirith
0.4's paired package-approval helper at its required root-owned
`/usr/local/libexec` path. The scanner's home location matters: Tirith
classifies `/usr/local/libexec` as package-managed and refuses scanner
self-replacement there, whereas its supported `~/.local/bin` layout is
self-managed. Future updates therefore run unmodified
`tirith update --yes --format json` as root inside a capability-empty unit with
strict filesystem protection and only those two writable roots. The unit does
not set `RestrictSUIDSGID`: on stable 0.4 that restriction makes GNU tar return
`ENOSYS` while extracting the signed archive's completion/manpage files. All
other reviewed hardening remains. Tirith retains mandatory signature checks,
atomic replacement, previous-binary sidecars, and native rollback. Service
startup uses the absolute binary with `TIRITH_OFFLINE=1`; attended deployment
also proves one benign allow verdict and one pipe-to-interpreter block verdict
without network access.
Ubuntu 24.04 does not provide Cosign in its default package repositories, so a
fresh bootstrap installs the reviewed official stable Linux AMD64 binary at
`/usr/local/bin/cosign`, enforces its GitHub-published SHA-256, and verifies its
exact version before it may authenticate Tirith.
On a first install, Ansible's Git checkout can normalize line endings in three
upstream PowerShell test files. The bootstrap accepts only that exact path set
and only when `git diff --ignore-space-at-eol` proves no semantic change, then
restores those worktree files from the reviewed commit and requires a fully
clean checkout before dependency synchronization. Existing runtime checkouts
are outside this normalization path.
The policy-schema transaction advances an existing profile-local config only
when it is the exact prior one-key version stub. Any profile with additional
mutable settings remains blocked for an explicit reviewed migration.

### Native Local Tools

Astra uses Hermes's native `local` terminal backend with
`terminal.cwd=/var/lib/hermes/astra/imported-data`. Commands run as the same
dedicated no-login `hermes-astra` identity as the Gateway. This is the intended
native Hermes execution path and restores ordinary filesystem inspection,
editing, diagnostics, and skill maintenance without building wrappers for each
operation.

The authority boundary is Linux and systemd: no sudo rule, Docker group/socket,
administrative SSH key, capabilities, setuid execution, or cross-profile group
membership; `ProtectSystem=strict`, `ProtectHome=true`, private devices and
temporary state, and explicit `ReadWritePaths` limited to Astra's profile and
reviewed work roots. Host paths outside those roots may be inspected when Unix
permissions and the systemd namespace permit, but cannot be modified. Material
infrastructure changes still require the normal Hermes approval policy and an
operator-controlled privileged path.

Dubble exposes no terminal, file, or code toolsets. Rigel exposes Hermes's
native file and local terminal tools, with both its process working directory
and `TERMINAL_CWD` fixed to its isolated writable academic tree. The terminal
runs as `hermes-rigel`, supports ordinary C++ source, compile, run, test, and
debug work, and cannot read profile secrets, other profiles, the owner home, or
administrator surfaces; terminal-originated network is denied. Rigel can also
ingest syllabuses, slides, notes, and course state directly. Dubble's
retained Docker backend configuration stays rootless, networkless, and
mountless only as inert defense in depth.

### Mandatory Hermes Policy

Root-owned managed scope enforces at least:

- manual command approvals, with `cron_mode: manual` for Astra and `deny` for
  Dubble and Rigel;
- no permanent command allowlist;
- approval-free guarded profile-local memory and skill writes, without authority
  over root-managed policy or another profile;
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

Hermes's native system installer owns one base unit per role; Ansible owns only
the hardened drop-ins and readiness gates:

- `hermes-gateway-astra.service`
- `hermes-gateway-dubble.service`
- `hermes-gateway-rigel.service`

Each unit has one `User=`, one `Group=`, explicit `HERMES_HOME`, a minimal
`PATH`, its own environment file, its own runtime directory, an event-loop
watchdog, restart bounds, CPU/memory/task limits, and no capabilities. Apply
`NoNewPrivileges`, strict system and home protection, private temporary state,
kernel/control-group/module protections, and a restrictive umask. Preserve
Hermes v0.20.4's official base units do not define `ExecStop`. Its CLI writes a
planned-stop marker before asking systemd to stop a Gateway. Ansible uses the
same native marker contract before an operator stop; a bare systemd stop sends
an unmarked `SIGTERM`, which Hermes classifies as unexpected before the restart
policy revives it.

Hermes adds no administrative SSH path to the host and has no public inbound
listener or dashboard route. Profile services receive only the outbound paths
needed for selected model providers, Discord, and explicitly approved report
or fixed-action endpoints. Rootless tool containers default to no network.
Remote exceptions use pinned host keys, one source address, and forced commands.

### Host Data And Fixed Actions

Hermes never receives the controller's Ansible, SSH, Docker, Health, Git, or
vault credentials. Root-managed collectors on `jn-t14s-lin` use dedicated
read-only credentials to fetch bounded Health and Docker reports, validate
their schema/signature/age, and atomically publish root-owned read-only inputs
for Astra. Dubble and Rigel cannot traverse those paths.

The live Docker inventory reporter uses a prompt-resistant schema-v2 result and
a dedicated `agent-report` identity on every current Ansible `docker_hosts`
member. Ansible derives the endpoint manifest and pinned SSH host keys from
inventory and live host facts; the Astra plugin reloads the root-owned manifest
on every call. Container membership is discovered from each live Engine every
five minutes and is never hardcoded into the plugin. The update path uses a
different key and `agent-auto-update` identity only where the existing
`docker-auto-update.timer` policy is enabled. It accepts only `status` or `run`
for that root-owned service, adds a one-hour cooldown, and emits bounded result
tokens. Astra cannot select images, services, paths, arguments, or Compose
options and cannot reach a Docker daemon.

Scheduled systemd updates remain automatic. The native Astra plugin asks for
fresh approval only for an unscheduled `run`, and its rule key includes the
current turn ID so a session or permanent choice cannot authorize a later
turn. The Docker socket proxy is excluded from blind updates because a
compromised proxy image has daemon authority. It is updated only through
attended Ansible convergence.

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
2. Service identities, homes, groups, native units, managed scope, secrets
   paths, and Astra's non-root local-tool boundary are explicit and lintable.
3. Every profile's allowed tools, Discord scope, inputs, outputs, and forbidden
   paths are machine-readable.
4. Shadow mode has no production token, scheduler delivery, dashboard, remote
   listener, host credential, or broker mutation authority.
5. Backup, restore, cutover, and OpenClaw rollback procedures have explicit
   pass/fail checks.
6. A static audit rejects Docker group/socket access, general sudoers,
   cross-profile secret reads, local tools for Dubble/Rigel, non-local terminal
   execution for Astra, and allow-all Discord while requiring the exact
   Astra-only native-update trigger.

The credential-free machine-readable declaration is
`files/hermes/shadow-target.json`. The fail-closed validator is
`scripts/agents/hermes-shadow-target-audit.py`; it rejects unknown top-level
schema instead of using natural-language phrase matching. The declaration pins
`jn-t14s-lin`, forbids concurrent OpenClaw/Hermes gateways, forbids raw source
mounts or wholesale copies, retains the raw source files offline, and requires
Astra's separate redacted read-only evidence projection to remain available.

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
range, root-owned managed scope, and hardened system unit. Astra exposes native
local terminal, file, and code tools. Rigel exposes native file and local
terminal operations inside its own academic tree; Dubble exposes none. Any retained dormant
Docker backend has no Docker group/socket, host mounts, host user mapping,
forwarded environment, forwarded credentials, or network.
Managed-scope validation is not treated as the sandbox: filesystem ownership,
the dedicated identities, and systemd controls remain independently required.

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

That compact file-memory seed is distinct from provider-backed conversation
memory. Dubble's later native activation audited all 3,228 canonical retained
conversations against five retained route indexes and imported only the one
conversation with exact public-route proof (11 eligible messages). The other
3,227 conversations remain preserved offline and are not model-visible.
Dubble's separate `memories_hermes_dubble_v3` Qdrant collection was initialized
empty because no legacy Mem0 point set had equally strong public provenance.
The live provider passed temporary add, dense recall, BM25 recall, and delete
acceptance, and the collection returned to zero points afterward.

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

### LCM And Mem0 Continuity

The compact native seeds remain useful policy memory, but they are not a
replacement for Astra's prior conversational continuity. The approved target
therefore enables both reviewed continuity mechanisms:

- `hermes-lcm` runs as Hermes's context engine and imports from a consistent
  backup of the stopped OpenClaw LCM SQLite database. The source database and
  historical sidecars remain unchanged and offline.
- Hermes's native OSS Mem0 provider uses local Ollama
  `qwen3-embedding:0.6b` at 1,024 dimensions and Qdrant hybrid collections with
  a BM25/IDF sparse vector. Astra, Dubble, and Rigel have separate v3
  collections and separate profile-owned LCM databases. No Gemini, OpenRouter,
  or metered OpenAI API route is part of this memory path.

The `v3` suffix is the reviewed Qdrant collection/schema generation, not a
Mem0 product major version. The installed production-stable Mem0 package is
`mem0ai` 2.x. Astra's v3 collection was seeded from the 4,148 owner/Astra
points selected from the 4,435-point preserved source; subsequent native Mem0
writes and deletes make the live count mutable. Rigel imported only its 111
route-scoped points. Dubble started from the one route-proven public
conversation and an empty Mem0 collection because the remaining retained
history lacks safe public-agent provenance.

The attended transaction is
`playbooks/agents/hermes-memory-continuity.yml`. It requires OpenClaw offline,
Hermes-native system units plus the native planned-stop marker contract, exact
owner approval, the approved local embedding models already present, and
source/target backups before any write. It updates the official
Hermes lock with `all`, `messaging`, and `mem0`; installs the reviewed LCM
plugin from its stable upstream track; runs both importers in dry-run first;
starts Astra only after SQLite, Qdrant, config, plugin, and native-tool policy
checks pass; and restores prior files, plugin state, LCM database, target
collection, services, and timers on failure.

The accepted preflight against the offline source found 306 importable LCM
conversations, 161,005 scanned messages, 139,435 eligible messages, 21,570
empty messages, no invalid rows, 4,192 importable summaries, and 1,649
unresolved summaries. The Mem0 source collection contained 4,435 points. The
Astra conversion selects 4,148 general, main, and owner-scoped points and
excludes 287 Dubble, Rigel, Vega, and Antares points. The source identity is
retained as provenance while the target is normalized to Hermes's `user_id`
and `agent_id` schema. Dry-run evidence contains counts and canonical digests,
not memory text or vectors.

The attended conversion completed on 2026-08-20. LCM imported all 139,435
eligible messages and 4,192 resolved summaries with zero invalid rows; the
21,570 empty messages and 1,649 unresolved summaries remained explicitly
excluded. SQLite `quick_check` passed. Mem0 reconciled all 4,148 selected
points into the target with canonical digest
`c9894f1c1f5dde7dca7623ffb0f61de2f18228ab1a5863c4ed00ba6964dc6138`,
while the 4,435-point source collection and its Qdrant snapshot remained
unchanged. Native provider recall passed without emitting memory content.

The initial Gemini-backed provider attempt exposed an optional-dependency gap
and was retired rather than made part of production. The accepted local
embedding path is covered by dependency checks and real dense/BM25
add-search-delete smokes for each profile. The accepted conversion rollback is
`/srv/live-rollbacks/jn-t14s-lin/hermes-migration/20260820T044531-pre-memory-continuity`;
the final provider reconciliation rollback is
`/srv/live-rollbacks/jn-t14s-lin/hermes-migration/20260820T045620-pre-mem0-provider-reconcile`.

Enabling `context.engine: lcm` is not sufficient when a profile also carries
an explicit toolset allowlist. Each profile must include `context_engine` in
that allowlist so Hermes publishes `lcm_doctor`, `lcm_recall`, and the other
context-engine schemas to the model. Database ingest and proactive recall can
otherwise remain healthy while direct model-visible LCM tools are absent. Live
acceptance must therefore prove both database health and an actual recorded
`lcm_doctor` tool call for Astra, Dubble, and Rigel.

This is a source-preserving conversion, not a shared live store. The old LCM
database, Mem0 history database, and Qdrant collection remain intact for
rollback and for a later separately reviewed profile-specific import. Re-running
the migration is idempotent only when the target count and digest match exactly;
an inconsistent nonempty target is a hard failure.

The 2026-08-26 local chunk backfill exposed a stable-plugin boundary defect:
`hermes-lcm` v0.20.0 treated one punctuation-free sentence as one atomic chunk,
so Qwen rejected retained spans whose real tokenizer expansion exceeded its
32K context even though LCM's `cl100k` estimate remained below 16K. The reviewed
temporary patch at
`files/hermes/patches/hermes-lcm-oversized-sentence.patch` bounds only those
atomic spans at 600 estimated tokens and 4,096 characters without truncating,
dropping, or reordering retained text. It is promoted as clean local plugin
commit `057614f6f550418eba519eec24a5bddfbe8f6e6f` atop official stable v0.20.0;
all 27 upstream chunking tests pass. Retire that commit and patch when a newer
production-stable upstream tag includes equivalent behavior.

The content-private `reconcile-chunks` maintenance operation compares active
chunk metadata with the current chunker and re-embeds only mismatched rows. It
refuses cloud providers, missing source reconstructions, approval omissions,
and an owner-selected repair limit. Seven stale rows across three messages were
repaired after a SQLite-consistent, hash-verified off-host backup at
`/srv/live-rollbacks/jn-t14s-lin/hermes-lcm-hotfix/20260826T230436Z-pre-lcm-atomic-span-hotfix/`.
Post-repair reconciliation reports zero mismatches, both LCM databases pass
`quick_check`, the uncertain ledger is empty, and a 16K Ollama proof run embedded
another 128 chunks successfully. The 16K service context is therefore retained
to avoid unnecessary KV-cache pressure on the 16 GB host; background bounded
backfill continues from 4,323 chunk vectors with 67,734 chunks remaining.

## Reviewed Profile Skills And Data

The retained contract describes 39 profile skill instances from 37 reviewed
Hermes-native sources. The exact root-owned projection is parser-, scanner-,
hash-, identity-, discovery-, and namespace-validated and remains available for
read-only audit or explicit rollback restore. It is not routine ownership.
Rigel's academic baseline includes 13 hash-pinned Markdown/JSON protocols and
course-state templates. The completed native-ownership transaction seeded
ordinary skills once into profile-owned local roots and promoted
`self-evolution` into one Astra-writable shared tree consumed read-only by
Dubble and Rigel. Profile memory and durable state remain isolated, all three
profile owners can maintain their own native skill roots, and normal
convergence does not overwrite those agent-authored changes.

Normal project data is a separate boundary from memory and skills.
`files/hermes/profile-data-stage-contract.json` permits exactly the 24 mappings
assigned by the pinned profile-import contract. Rigel's complete OpenClaw
`courses/`, `memory/`, syllabus PDF, ECS-2390 inbound tree, and general inbound
tree now map to its native writable profile data; they are no longer reduced to
one reference file or a lossy state transform. The stager recomputes and proves
the full object/byte inventory against source hashes before promotion. Project
and course content is available on demand through native file operations; it is
not injected wholesale into a model prompt.

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

The prior accepted 2026-08-13 generation installed 1,125 files and
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
data. `files/hermes/profile-transform-contract.json` now declares exactly five
Astra/Dubble conversions: FreshRSS dedupe state, Reddit sync state, the private
sobriety tracker, Nextcloud task state, and an empty Dubble user registry.
Rigel is absent from this transformer. Its source archive is copied intact into
native writable profile data, and the academic skill maintains
`courses/academic-state.json` using a hash-pinned native template.

Rigel scheduling remains fail-closed without a legacy compatibility directory.
The always-on 30-minute evaluator reads only
`imported-data/courses/academic-state.json`. A missing state file is a healthy
`idle-uninitialized` result, while expected idle or malformed state emits no
stdout, reasoning text, token, or Discord message. Alerts become possible only
after Rigel has ingested source-grounded course dates into that native file.

`playbooks/agents/hermes-profile-transforms.yml` stages the small generation
under `/var/lib/hermes/profile-transforms`, records a root-only manifest and
rollback archive, verifies stable input/output hashes, then proves each
no-login profile sees only its own writable bind and read-only managed bind.
The Hermes Gateway units verify both the root manifest and unprivileged bind
identity before start. This component remains disabled until an attended
staging run and does not start a Gateway, model, scheduler, or messaging route.

## Behavior And Self-Evolution

The replacement does not use a plugin or phrase table to decide when Astra
should research, compare hardware, perform RCA, or learn. Each profile's
Hermes-native `AGENTS.md` is always loaded with its `SOUL.md`; neither file is
deployed, converged, or runtime-pinned from Ansible after profile establishment.
Astra selects evidence from the request's intent, stakes, uncertainty, exact object,
current thread, and durable project state. Dubble and Rigel have separate
operating contracts and cannot read Astra's policy or data through a shared
profile.

Hermes' native background review is the semantic self-evolution mechanism. It
runs after a turn and can directly persist compact memory, profile-local skill,
or operating-guidance changes inside the owning agent's native write boundary.
The fleet-shared self-evolution skill gives all three agents the same review and
evidence procedure. Astra is its sole writer; Dubble and Rigel can propose a
change for Astra to accept only when it is necessary and beneficial fleet-wide.
This does not merge their memories or grant cross-profile reads.
All three profiles set `memory.write_approval: false` and
`skills.write_approval: false` for their isolated native state, with
`guard_agent_created: true`. Foreground and background improvements can
therefore persist without waiting for Johnny, while root-owned platform policy,
credentials, tools, and other profiles remain outside ordinary write authority.
Astra is the sole reviewer and writer for the shared
`self-evolution` tree; Dubble and Rigel submit bounded proposals through their
peer path. Background maintenance remains silent unless a real owner or
operator decision is blocked. Official behavior is documented under
[persistent memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory/)
and [skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/).

The native maintenance lane runs every two hours at minute 5 on odd hours,
with a daily 04:20 backstop. It holds one profile-local semantic-maintenance
lease while reviewing only the explicit native source allowlist and the
read-only `cc-ansible` workspace. Imported, managed, legacy, preserved-evidence,
backup, and migration roots are not unattended discovery sources. Heartbeat
acquires the same lease only for its daily workspace/self-evolution lane, so a
busy semantic review cannot starve calendar, cron, delivery, storage, weather,
runtime, memory, bootstrap, or route checks.

The agent may write stable preference or profile memory and create or improve
a reusable profile-local skill. Profile-owned `SOUL.md` and `AGENTS.md` may
evolve through the reviewed native workflow after ownership migration.
Security floors, deployment, credentials, and tool authority remain root-owned
and outside agent write access. Ansible never reverts valid profile-authored
behavior during normal convergence. If an existing general rule already
covered a failure, the correct outcome is a regression or enforcement repair,
not another incident-specific reminder.

`files/hermes/behavior-regressions.json` converts the saved private transcripts
into 14 sanitized promotion cases without copying transcript text, private
paths, or platform identifiers into the repository. The cases cover antecedent
resolution, current regional research, purchase-state reconciliation,
compatibility versus performance, direct decisions, useful walkthrough
checkpoints, expected absence, incident RCA, scope/preferences, concise Star,
reversible recommendation latency, busy follow-up FIFO delivery, source-backed
alerts, and correction generalization. The isolated model suite contains ten
model-owned cases; current research, deterministic idle silence, concise Star
synthesis, and busy follow-up FIFO retain separately owned integration gates.

The corpus assigns each case to its real execution owner. Ten reasoning cases
run privately through `scripts/agents/hermes-behavior-acceptance.py` and require
independent Vega and Antares semantic pass verdicts. Current regional research
waits for the reviewed live-evidence route, idle absence remains owned by the
deterministic Rigel evaluator, and concise Star synthesis plus busy follow-up
FIFO remain Gateway integration tests. The runner must not collapse those four boundaries into a
generic model prompt merely to report a complete gate.

## Migration Gates

1. **Source checkpoint:** freeze and verify OpenClaw state, runtime, listeners,
   sessions, jobs, and backups without stopping production.
2. **Parity:** approve this matrix and record every unsupported/manual item.
3. **Target design:** define the service identity, paths, systemd units,
   sandbox, secrets, backup, loopback listeners, and inventory-derived typed
   host-action schemas.
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

## Production Status

Gates 1 through 8 completed on 2026-08-14. OpenClaw's production Gateway,
isolated canaries, repo-sync timer, and update-check timer are stopped and
disabled; its files remain offline for reference and rollback. Health remains
an independent active user service. Astra, Dubble, and Rigel are active Hermes
Discord consumers with distinct applications, tokens, service identities,
profile homes, routes, and OAuth state. Rigel owns its academic server/channel
route and exact 30-minute no-model scheduler; Astra no longer carries a
temporary Rigel route.

The Discord consumers were migrated to Hermes's official native named-profile
base units on 2026-08-20, and dedicated Rigel enrollment completed on
2026-08-24. All three units run as their dedicated service identities
with Ansible-owned hardening/readiness drop-ins, while Hermes retains ownership
of the base lifecycle and command.

The root cause of the earlier repeated shutdown notices was that the former
handwritten units stopped Hermes with a bare `SIGTERM`. Hermes classified that
unmarked signal as unexpected, exited nonzero, and the restart policy started
it again. The official v0.20.4 unit also has no `ExecStop`; the native contract
is the planned-stop marker written by `hermes gateway stop --system` before
systemd sends `SIGTERM`. Managed maintenance now writes that marker through the
shared planned-stop task before stopping a Gateway.

`playbooks/agents/hermes-native-gateway-migration.yml` is the exact-approval
transaction used for that repair. It pauses update and automation timers,
marks configured stops as planned, stops each active consumer once, refreshes the stopped
file inventory, archives and copy-migrates profile state into native named
profiles, invokes Hermes's native system installer, applies only hardened
drop-ins, verifies Discord ownership, and retains the old roots and units for
rollback. The follow-up runtime and automation playbooks converge all
consumers and timers against the new paths.

Gate 9 was not exercised against production during this closeout because it
would deliberately interrupt the now-live Hermes Discord path and briefly
reactivate the legacy delivery/scheduler path while the owner was relying on
the agent. Transaction rescue and retained rollback artifacts are verified;
an attended end-to-end OpenClaw message drill remains optional rather than a
condition for keeping Hermes live.

The first cutover acceptance incorrectly treated active systemd processes as
proof of messaging. Both processes had stayed alive for cron after logging
`No adapter available for discord`. Root cause was the missing official
`messaging` extra plus shared-runtime group modes that denied Dubble after the
first repair. The corrected service now runs the dependency audit with the
managed Hermes interpreter before startup and cannot become active until its
main process owns an established TLS session. Production convergence restarts
Astra, Dubble, and Rigel sequentially through Hermes's native lifecycle and rejects
adapter, dependency, permission,
audit, or traceback journal patterns while treating an expected no-match as a
successful probe.

Current rollback artifacts include:

- `20260814T133103Z-pre-discord-runtime-repair`
- `20260814T133908Z-pre-runtime-reader-group`
- `20260814T085809-pre-runtime-converge` for the failed-closed interpreter
  preflight and automatic unit restore
- `20260814T090022-pre-runtime-converge` for the accepted live unit convergence
- `20260820T050007-pre-automation` for native production automation convergence
- `20260820T050342-pre-runtime-converge` for the final native runtime gates
- `20260820T050753-pre-automation` for the managed schema-38 reconciliation

The Docker/security boundary first completed on 2026-08-14 and its dynamic host
manifest converged on 2026-08-23. The result-only reporter is live on every
current `docker_hosts` member, while the managed-updater trigger is live only
where updater policy is enabled. Astra
receives the two credentials
through systemd; Dubble and Rigel receive neither. Native turn-bound approval
protects unscheduled runs, and scheduled systemd updates remain automatic.
Docker group, socket, arbitrary SSH, general sudo, and free-form update access
remain prohibited. The final risk analysis is maintained in
`docs/openclaw-runtime-security.md` and `docs/agent-docker-access.md`.

Production automation first converged on 2026-08-14 and was re-converged after
native profile and memory migration on 2026-08-20. The source
inventory contained 26 current cron rows, three logical heartbeats, and two
historical completed one-shots. All 31 lanes have an explicit final
disposition in `files/hermes/production-automation-reconciliation.json`.
In fallback mode, Astra retains Rigel's 30-minute deterministic academic poll
alongside the STW and Warframe minute watches, the hourly HDD deal watch, the
07:08 Daily Summary, the 06:50 Fortnite progress report, and the Sunday 09:00
social-seed review. Dedicated mode moves only the academic poll into Rigel's
own native manifest. Root-managed systemd timers own the retained collectors,
Warframe feed, Fortnite calendar, and three profile backups. Completed
one-shots were not replayed. Astra's operational heartbeat is a native
30-minute stateful job rather than a generic status prompt: every wake runs the
lightweight lane and at most one oldest eligible deferred check, records
blocked attempts with a bounded retry time, and persists a
publish/suppress/resolve/re-alert transition before any Discord call. Its typed
host probes treat an automount's `autofs` parent plus concrete `nfs4` leaf as
one healthy NFS view. Scoped native cron reconciliation can update selected
managed jobs without resuming an unrelated paused one-shot.

The 2026-08-16 through 2026-08-20 transcript exposed two post-cutover runtime
regressions in that automation. This was not a generic Hermes capability gap:

- the retained summary collector's `ProtectHome=tmpfs` namespace omitted the
  existing Health database, SSH known-host/key files, and vdirsyncer/khal
  configuration, so the summary falsely reported those inputs as missing;
- the HDD collector's anonymous Reddit request returned HTTP 403, and the
  semantic job converted the same upstream source failure into an hourly wall
  of repetitive Discord diagnostics instead of one bounded source-health
  state.

The corrected retained service binds only those exact existing inputs
read-only. The HDD collector evaluates Reddit and the already-credentialed eBay
Browse API independently, records `ok`, `partial`, or `degraded` source health,
deduplicates cross-source results, and exits successfully with an empty
candidate set when every source is unavailable. A degraded run is silent in
Discord; it is not misreported as "no deals" and does not spend a model turn
restating the same repair advice. Live acceptance passed on 2026-08-20: an
isolated run of the deployed collector authenticated to eBay and returned
bounded candidates without touching the production delivery ledger, and a
manual non-delivering Daily Summary collector run completed successfully,
created a fresh artifact, and contained none of the prior false missing-Health,
SSH-host-key, vdirsyncer, or khal signatures.

The automation transaction is rollback-first. Check mode is read-only, active
timers are excluded and restored around mutation, native profile backups run
as each no-login profile through `runuser`, and rescue restores both files and
the pre-transaction timer set. Missing optional Rigel files and an idle
semester are successful silent states, not tool failures or Discord output.

The first native Hermes update fetched upstream successfully but could not
restart Dubble because an empty systemd capability bounding set prevented the
host sudo implementation from restoring user IDs. The updater now bounds only
`CAP_SETUID` and `CAP_SETGID`, keeps ambient capabilities empty, and still
depends on exact-command sudoers for the three named Gateways. A second native
Hermes update and the Tirith native updater both completed successfully.

The final `systemd-analyze security` exposure scores were 3.0 for each Gateway,
4.5 for the Hermes updater, 4.0 for the Tirith updater, and 3.8 for the retained
summary/feed/calendar services. Identity-level Discord TLS audits, native cron
reconciliation, Rigel idle health, Docker forced-command smoke tests, updater
status, and direct Docker-socket denial all passed after convergence.

The 2026-08-24 checkpoint validates three distinct Discord applications,
active Gateways, isolated routes, Rigel's academic behavior and schedule, and
Astra's native non-root tool path. Overall acceptance remains open for the
remaining exhaustive source/reference and latest-stable audit; no beta,
preview, RC, or legacy/v1 dependency may remain where a supported stable
replacement exists.

## Astra Prowlarr Administration

The 2026-08-26 Prowlarr failure was credential drift, not missing Astra
authority. Prowlarr's native API key had rotated on 2026-08-23 while the
root-private credential isolated behind Astra's Arr broker retained the prior
key. The stale key returned HTTP 401, and the broker misclassified Prowlarr's
non-JSON error body as `unsupported-response`. In addition, Prowlarr's native
indexer schema exceeded the generic two-megabyte response limit and the generic
Arr mutation boundary correctly rejected tracker secret fields. Those three
independent conditions made tracker enrollment unusable.

The existing Arr plugin and broker now expose two narrow Prowlarr operations;
no second plugin, shell, Docker access, or direct API key was added. Filtered
schema discovery reads up to eight megabytes inside the broker but returns no
more than 20 sanitized matches. Indexer test, create, and positive-integer-ID
update accept declared tracker secrets in a separate map, require a valid bound
owner turn, reject unmatched or non-secret-shaped fields, and redact every
response recursively. A direct owner request for that exact typed operation
does not trigger a second approval prompt; an unbound call is blocked. The
generic Arr request tool continues to require write approval and deny all
secret-bearing mutations. Broker audit records contain only service, method,
path, and status; they never contain request or response bodies.

Live acceptance as `hermes-astra` passed for Bazarr, Prowlarr, Radarr, and
Sonarr. A filtered Prowlarr schema query returned bounded matches from 134
eligible definitions, the deployed validator reported all four model-visible
tools, and a synthetic secret redaction probe proved that the supplied value
was absent from rendered tool-call text. No production tracker was added
without an owner-supplied tracker identity and settings. The deployment used
rollback
`/srv/live-rollbacks/jn-t14s-lin/hermes-migration/20260826T003854-pre-arr-api`.
A subsequent owner interaction created SeedCore through the narrow tool with
ratio `5.0`, no time limits, and priority `11`; a native read-back and HTTP 200
indexer test passed. HD-Space was corrected natively to priority `12`, and both
Sonarr and Radarr synchronized the complete requested ordering. The obsolete
hardcoded indexer-priority mutator was retired instead of expanded. Prowlarr
indexer settings remain native backed-up application state, not Ansible-owned
policy. A subsequent zero-drift convergence did not restart Astra. Prowlarr API-key
rotation remains a platform-secret event: the rotation workflow must run the
exact Arr credential convergence transaction so the isolated broker copy is
refreshed and revalidated without exposing the key to Astra.

## Deferred Movie DJ Research

After Astra's native tools, memory continuity, vision, skills, and scheduled
automation are stable, research a separate Hermes-operated Discord movie-DJ
agent that could remain in a voice channel and stream video continuously. This
is deliberately deferred and no implementation is authorized by this note.
The investigation must cover Discord API and Terms-of-Service constraints,
whether screen sharing can be automated through a supported bot or requires an
interactive user account, copyright and content-licensing boundaries, audio
and video capture architecture, process/session isolation, operator controls,
and 24/7 recovery behavior before recommending any design.
