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

## Isolated Target Design

### Deployment Topology

Provision a new `hermes-vm`; do not reuse VM 140 or any retired OpenClaw disk.
The preferred placement is `pve-alto`, subject to a fresh attended capacity,
storage, UPS, and VMID check immediately before provisioning. If that gate
fails, select another Proxmox node from live evidence rather than silently
shrinking the VM or co-locating it on the controller.

Use the then-current Tier-1 Ubuntu LTS cloud image with verified publisher
checksum and signature. The baseline allocation is four vCPUs, 8 GiB RAM, and
a 64 GiB system disk, with memory increased before accepting swap pressure or
Gateway instability. The VM has no NAS, controller-home, Docker-socket, USB, or
host filesystem passthrough.

OpenClaw stays on `jn-t14s-lin` as the production source and later rollback
system. The Hermes shadow has no production channel token or Caddy/Tailscale
route. Both systems may be installed during migration, but only OpenClaw may
deliver production messages or run production schedules before cutover.

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

Install the official supported root-mode Git distribution under
`/usr/local/lib/hermes-agent` with `/usr/local/bin/hermes` as the launcher. The
service users cannot update or patch that code. Track the official default
stable branch rather than setting a policy-level exact-version pin.

Updates are root-managed transactions:

1. Back up every profile with Hermes's SQLite-safe backup path and take the VM
   rollback artifact.
2. Update the shared code through the official mechanism with full pre-update
   backup enabled.
3. Run offline config migration, Doctor, supply-chain audit, prompt-size,
   profile, and declaration checks.
4. Start a tokenless shadow service and run behavior/security smoke tests.
5. Restart production profiles one at a time only after the shadow passes.
6. Restore the prior code and profile backup if any gate fails.

Runtime lazy dependency installation is disabled. Required extras are installed
and audited during the root-owned build transaction, never by a live Gateway.
Bundled skills are initially opted out; only reviewed, required skills are
seeded per role.

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

Hooks and plugins begin empty. A new hook or plugin requires source review,
provenance, a failure-mode test, a rollback artifact, and explicit activation.
Because Hermes hook consent keys the command string rather than script content,
an unchanged path with changed bytes is untrusted until re-audited.

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

The VM accepts administrative SSH only from the controller/owner path. It has
no public inbound listener and no dashboard route. Outbound policy permits DNS,
time, system updates, the selected model providers, Discord, and explicitly
approved report/broker endpoints. Deny LAN, tailnet, metadata, link-local, and
other private destinations by default. Broker exceptions are exact destination
and port rules, not private-network ranges.

### Host Data And Action Brokers

Hermes never receives the controller's Ansible, SSH, Docker, Health, Git, or
vault credentials. Root-managed collectors on `hermes-vm` use dedicated
read-only credentials to fetch bounded Health and Docker reports, validate
their schema/signature/age, and atomically publish root-owned read-only inputs
for Astra. Dubble and Rigel cannot traverse those paths.

The Docker update broker remains separately approved and digest-bound. Astra
may submit a fixed-schema proposal and later invoke only an already-approved,
unexpired plan. It cannot approve a plan, select arbitrary compose paths or
commands, broaden targets, or reach a Docker daemon. Renaming OpenClaw-specific
service accounts and paths to platform-neutral agent names occurs only in the
later Docker gate with compatibility cleanup and rollback coverage.

### Backups And Recovery

Use both application and infrastructure backups:

- nightly `hermes backup` archives for each home, using SQLite's backup API;
- pre-update and pre-migration full Hermes backups;
- encrypted restic copies of profile homes and root-owned policy, excluding
  transient rootless container layers unless a test explicitly needs them;
- Proxmox Backup Server VM backups; and
- a manifest of code revision, config schema, profile declarations, bot-token
  identities, cron declarations, and backup hashes.

Restore tests use a channel-less clone with replaced credentials. A backup is
not accepted because an archive exists; Doctor, session search, memory, skills,
cron declarations, and one synthetic model turn must work after restore.

OpenClaw rollback remains independent: its services, state, secrets, sessions,
workspace, package runtime, and backups are preserved unchanged. Cutover does
not uninstall OpenClaw, reuse its ports/state directories, rotate away its only
working credentials, or run OpenClaw/Hermes cleanup commands.

### Gate 3 Acceptance

This design gate is complete when implementation assets express these
boundaries without installing Hermes:

1. VM provisioning inputs have no conflicting live VMID and the chosen node
   passes capacity/UPS/storage checks.
2. Service identities, homes, groups, units, managed scope, secrets paths, and
   rootless Podman prerequisites are explicit and lintable.
3. Every profile's allowed tools, Discord scope, inputs, outputs, and forbidden
   paths are machine-readable.
4. Shadow mode has no production token, scheduler delivery, dashboard, remote
   listener, host credential, or broker mutation authority.
5. Backup, restore, cutover, and OpenClaw rollback procedures have explicit
   pass/fail checks.
6. A static audit rejects Docker group/socket access, sudoers, host mounts,
   cross-profile secret reads, local-terminal fallback, and allow-all Discord.

The blank multi-node capacity probe attempted during this design gate stalled
in Ansible SSH interpreter discovery and left workers after the wrapper ended.
Those exact workers were terminated and no capacity result was inferred. The
live placement check therefore remains an implementation precondition, not a
fabricated design fact.

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
