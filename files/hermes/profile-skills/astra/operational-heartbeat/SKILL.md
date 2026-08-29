---
name: operational-heartbeat
description: Use for Astra's stateful operational heartbeat.
version: 1.1.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [heartbeat, health, alerting, continuity]
    related_skills: [caldav-calendar, healthcheck, lossless-claw, self-evolution]
---

# Operational Heartbeat

This is a quiet publication gate, not an invitation to invent work. Preserve
the configured 30-minute wake indefinitely. Silence means the no-op path
worked. Publish only a new verified actionable state, material worsening, a
new owner decision, or a useful recovery from a previously visible outage.

## Scheduled Final Response Contract

For every scheduled invocation, the final response is exactly `[SILENT]` and
nothing else. This is unconditional. Send any verified actionable finding
through the native Discord tool before returning that final response. If the
Discord action cannot complete, preserve the delivery obligation in native
state and still return exactly `[SILENT]`.

Never put a finding, blocked-lane explanation, tool result, guardrail summary,
verification status, maintenance result, or apology in the scheduled final
response. A prohibition in this skill is not a lane to test, explain, or
report. The cron artifact containing only `[SILENT]` is the required local
publication result whether the run found nothing or sent a Discord notice.

## Native Source Contract

This loaded managed skill is the complete production heartbeat procedure.
Use Astra's native profile, skills, state, memory, scripts, and managed
cc-ansible repository as the only runtime sources. Never read
`legacy-openclaw` or `/home/johnny/.openclaw` during a heartbeat. Preserved
OpenClaw material is operator-owned migration and rollback evidence, not a
runtime fallback.

Every lane below is required, including bootstrap, model-route, empty-turn,
workspace-hygiene, review-debt, source-candidate, self-evolution,
deduplication, recovery, and safe-plan rejection behavior. If a lane has no
usable native implementation, classify that as a parity failure and notify
once through the publication gate rather than silently omitting it.

## Unattended Execution Contract

The scheduled heartbeat is unattended. Never request interactive command or
file-mutation approval. Never call `execute_code`, create or execute an ad-hoc
verification script, or use a temporary `/tmp` program to reinterpret state.
Use only the loaded native tools, the exact existing helpers named below, and
direct bounded reads of their structured output.

If a required decisive probe cannot run through those pre-authorized paths,
do not improvise an equivalent command. Preserve the lane as blocked without
advancing its completion time and send one concise deduplicated parity notice
only when that block is actionable. A successful probe, internal verification,
tool transcript, maintenance action, or statement that a temporary file was
removed is never publishable output.

These guardrails are normal operating constraints, not checks that need their
own verification and not evidence that a lane is blocked. Never claim failure,
degradation, or a verification block without a current exact tool error or
state value from the required due-lane probe. When no decisive current evidence
exists, leave that lane unadvanced and remain silent. Do not inspect, validate,
or discuss changed files, patches, source syntax, or test status unless the
24-hour workspace-hygiene lane is actually due. Even then, patch-tool status,
missing optional extra verification, and internal test coverage are never
heartbeat findings.

## State And Routing

- The immutable profile root for this job is
  `/var/lib/hermes/astra/.hermes/profiles/astra`. Never derive it from the
  process CWD, `$PWD`, a repository path, or a prior terminal call.
- Keep schedule state only in
  `/var/lib/hermes/astra/.hermes/profiles/astra/state/heartbeat/schedule.json`,
  schema version 3. Each check owns ISO-8601 `lastAttemptAt`,
  `lastCompletedAt`, optional `notBefore`, and concise `lastResult` fields.
- Keep alert lifecycle files only under
  `/var/lib/hermes/astra/.hermes/profiles/astra/state/heartbeat/alerts/`.
  Scheduling time and alert fingerprints are separate. An alert receipt does
  not prove the underlying condition still exists.
- Repository inspection must use an explicit terminal-tool workdir or
  `git -C /var/lib/hermes/astra/.hermes/profiles/astra/workspaces/cc-ansible`.
  Never use ambient `cd` and never perform a relative state or helper read
  after a repository probe.
- Send actionable messages to Discord `#astra-logs`, channel
  `1482589440663617638`, through the native Discord tool. Return `[SILENT]`
  locally after delivery. Never append automation output to an active user
  turn and never send `[SILENT]`, `NO_REPLY`, or a healthy inventory.
- Johnny's Discord user ID is `740687933803331726`. Mention him only where the
  check below explicitly calls for it. "Non-pinging" means no user, role,
  `@here`, or `@everyone` mention; it still means a real Discord message.
- Immediately re-probe decisive state before a present-tense outage claim.
  Report the exact failed path and label broader service impact unverified
  unless independent evidence proves it.

## Scheduling And Pressure

| Check | Cadence | Lane |
| --- | --- | --- |
| `calendar` | every poll | lightweight |
| `cron-health` | every poll | Hermes CLI, serial |
| `interactive-delivery` | every poll | lightweight local |
| `media-stack` | every poll | lightweight cached remote |
| `stream-relay` | every poll | lightweight remote |
| `homelab` | 2 hours | heavy remote, serial |
| `weather` | 2 hours | lightweight network |
| `model-route-drift` | 2 hours | lightweight local |
| `hermes-runtime-health` | 6 hours | heavy Hermes CLI, serial |
| `memory-system` | 6 hours | native memory, serial |
| `bootstrap-budget` | 6 hours | lightweight local |
| `usb-das` | 12 hours | heavy remote, serial |
| `plex-corrupt-media` | 12 hours | heavy local/remote, serial |
| `workspace-hygiene` | 24 hours | heavy local, serial |
| `self-evolution` | 24 hours | state review only |

On missing, legacy, or partial schedule state, preserve valid timestamps and
upgrade the state to schema 3; never reset the real state from a relative or
missing-path premise. Run the every-poll lane plus at most one eligible due
deferred check on every wake. A deferred check is due when `lastCompletedAt` is
missing or older than its cadence, and eligible when `notBefore` is absent or
has passed. Select by oldest `lastAttemptAt`, treating a missing attempt as
oldest, then by oldest `lastCompletedAt`, then table order. Record
`lastAttemptAt` before the probe starts.

After a blocked or pressure-deferred attempt, preserve the exact reason in
`lastResult`, set `notBefore` to the next normal heartbeat wake, and do not
advance `lastCompletedAt`. That attempted lane must not prevent another due,
eligible lane from being selected on the next wake. On a decisive successful
probe, update both timestamps, clear `notBefore`, and record the normalized
result. Never infer success from a spawned process, partial output, or restart.

Run at most three explicitly lightweight checks concurrently. Run heavy checks
and Hermes CLI commands serially. Before each heavy check read
`MemAvailable`, `SwapFree`, and `Writeback` from `/proc/meminfo`. Defer without
alert when memory available is below 4 GiB, swap free is below 2 GiB, or
writeback exceeds 512 MiB. Never overlap a heartbeat-owned heavy process.

## Every-Poll Checks

### Calendar

Run `vdirsyncer sync`, then `khal list now 2h`. Alert only for an event whose
start remains in the future and is within 15 minutes. Ignore already-started
events and events merely ending soon. Format:
`<@740687933803331726> Calendar: <event> at <time>`.

### Native Cron Health

Run `hermes cron status`, `hermes cron list --all`, and only then
`hermes cron runs <job-id> --limit 5` for a failing enabled job. A stalled
ticker, missing expected job, wrong schedule, duplicate job, or failed run is
actionable. Classify before proposing a change: stale path/payload, dependency
failure, scheduler drift, script/config bug, expected warning, or unknown.

Do not mute, retry, disable, edit, or deduplicate before finding the owner,
exact error, last-good run, and relevant change. A narrow obvious reversible
repair still requires a targeted backup and actual rerun/recheck. Credentials,
provider changes, deletions, broad rewrites, uncertain jobs, service changes,
or changes that could spam Discord require an owner decision. Fingerprint by
job ID plus normalized error in `state/heartbeat/alerts/cron-health.json`.

### Interactive And Delivery Health

Run
`/var/lib/hermes/astra/.hermes/profiles/astra/scripts/hermes-heartbeat-state.py`.
It emits no message content. Treat as actionable: a stale active turn, an
unanswered user turn, a terminal empty
assistant turn, an unfinished tool turn with no active worker, an abandoned
delivery obligation, or a pending/attempting/failed obligation that remains
stale after a gateway re-probe. Hermes already retries empty responses,
notifies stalled sessions, and redelivers durable obligations; diagnose those
native mechanisms before changing session state. Preserve `sessions.json`,
`state.db`, and relevant logs before any repair. Never clear an explicit
`/model` choice as automatic drift.

### Media Stack

Use `host_admin_request` with host `docker-vm`, action `health`, and probe
`media-stack`. This is a read-only native broker operation and must not prompt.
`OK:` and `WARNINGS:` are silent. Suppress Bazarr OpenSubtitles authentication,
throttle, and missing-English-subtitle backlog completely until Johnny reverses
his 2026-08-04 opt-out. For another `CRITICAL:` result, send a non-pinging
`Media stack: <exact failed check>` once per fingerprint. This is cached health;
do not start fresh NFS or mergerfs probes from this lane.

### Stream Relay

Use `host_admin_request` with host `media-vm`, action `health`, and probe
`stream-relay`. This is a read-only native broker operation and must not prompt.
Exit zero with `OK: stream relay health checks passed` is silent. Otherwise
send `<@740687933803331726> Stream relay/VOD: <exact failed check>` once per
fingerprint after a decisive re-probe.

## Deferred Checks

### Homelab, Every 2 Hours

- Use `host_admin_hosts` as the complete current managed-Linux inventory and
  the typed probe result as the coverage authority. Remote-access SSH mode is
  intentionally disabled; do not read or require `state/remote-access.json`
  and do not report its absence. A required broker host or typed probe missing
  from the active manifest is an operator-owned parity gap. Never fall back to
  Johnny's, `dbc`'s, or Ansible's private key.
- Use `host_admin_request` health probe `plex-local` on `media-vm`; 200, 302,
  and 401 mean up, while no response is actionable.
- Use `host_admin_request` health probe `nextcloud-local` on `nextcloud-vm`;
  any HTTP response means up, while no response is actionable.
- Use `host_admin_request` health probe `storage-status` on `ts440`; never use
  `df -h` for ZFS.
- Use `host_admin_request` health probe `media-storage-view` on both `ts440`
  and `docker-vm`. This single typed probe owns the exact mergerfs/NFS mount
  type and bounded library-readability checks below; do not reconstruct them
  with terminal or SSH commands.
- Use `docker_inventory` with host `all` for dynamic container state. Do not
  hardcode a container inventory or use the Docker socket.
- On ts440, `/srv/media` must be `fuse.mergerfs` and contain at least one
  `/srv/media/plex/Movies` directory entry.
- On docker-vm, `/srv/media` and `/srv/incomplete_downloads` must be NFS/NFS4;
  the movie library and incomplete torrent path must be readable.
- A broken mergerfs/NFS/library view gets an immediate ping and warning not to
  rescan. A disk above 85 percent gets a non-pinging notice at initial crossing
  and only again after five percentage points or a new severity threshold.

### Weather, Every 2 Hours

Use current Open-Meteo data for Garland, Texas, timezone America/Chicago.
Alert only for precipitation, WMO code 51 or higher, temperature above 105 F
or below 35 F, or severe weather. 100-105 F is routine and silent. Aloe and
spearmint need no heat bring-inside warning; alert only for frost/freeze or
destructive hail/high wind.

### Model Route Drift, Every 2 Hours

Use
`/var/lib/hermes/astra/.hermes/profiles/astra/scripts/hermes-heartbeat-state.py`,
`hermes fallback list`, and the root-managed config. `openai-codex` and
`ollama-cloud` are approved subscription routes. Any recent OpenRouter,
Gemini/Google, or direct OpenAI API billing route is actionable because Johnny
rejected metered usage. Blank provider and billing-mode fields are unknown
provenance, never proof of metered usage. Correlate every
`unknownProvenanceRoutes` row with the currently configured primary and
fallback routes; a configured approved route such as the active Ollama Cloud
fallback is silent. Alert only when current evidence confirms an unapproved or
metered provider. A persisted session model override is an expected explicit
`/model` choice unless it adds an unapproved provider/base URL; do not scrub it
merely because it differs from the global model. Fingerprint exact route and
billing mode.

### Hermes Runtime, Every 6 Hours

Run `hermes doctor` and wait for it to exit, then `hermes skills check`, then
`hermes status --all`. Alert once for a new actionable warning, unavailable
enabled skill, gateway/ticker failure, or materially changed warning set.
Known acknowledged advisories remain silent until their mechanism changes.
Never print credentials or secret values.

### Memory, Every 6 Hours

Use native `memory_search` with a harmless rewritten query and limit one, then
run `hermes memory status` and `hermes curator status` serially. Empty recall is
valid; tool/provider errors, unreachable Mem0, invalid LCM, curator failure, or
processing backlog are not. Do not add/update/delete memory from heartbeat.
Mention Johnny once for a new unresolved fingerprint; unchanged failures and
recoveries are non-pinging when a message is useful.

### Bootstrap Budget, Every 6 Hours

Run `hermes prompt-size --platform discord --json` with terminal workdir
`/var/lib/hermes/astra/.hermes/profiles/astra`, then run `hermes skills check`
from that same explicit workdir. Verify every required identity, owner-context,
memory, and managed-skill source named by the managed bootstrap contract from
the profile root. Alert immediately for truncation, a missing native source,
failed skill discovery, hash drift in a managed source, any production
reference to `legacy-openclaw` or `/home/johnny/.openclaw`, or prompt loading
from another CWD.

### USB DAS, Every 12 Hours

Use the managed `storage-status` health probe on `ts440` and compare its native
storage result with the prior alert state. A mount is unhealthy only when the
probe reports it missing, shutdown, or unreadable. Alert on a new disconnect
only when a mount is unhealthy; a recovered mount gets at most one non-pinging
note. Never repeat events merely because they remain in a prior result.

### Plex Corrupt Media, Every 12 Hours

Use `host_admin_request` health probe `plex-corrupt-media` on `jn-t14s-lin` and
`mercury` when both are present in `host_admin_hosts`.
`OK:` is silent. Suppressed HTTP/storage read failures are not corrupt media.
`CRITICAL:` becomes one non-pinging backlog note keyed by normalized path,
position, and appliance. Never run a collection-wide ffmpeg scan.

### Workspace Hygiene And Self-Evolution, Every 24 Hours

Before this lane's semantic review, acquire the shared maintenance lease with:
`/var/lib/hermes/astra/.hermes/profiles/astra/scripts/hermes-heartbeat-state.py --profile-home /var/lib/hermes/astra/.hermes/profiles/astra --maintenance-lease acquire --lease-owner heartbeat`.
If it returns `busy`, record this lane's attempt and a bounded `notBefore`, do
not advance its completion, and leave all nonsemantic heartbeat lanes
available on later wakes. A lease state error is one deduplicated operator gap,
not permission to bypass the lease. Release with the same absolute helper and
`--maintenance-lease release --lease-owner heartbeat` only after this lane's
schedule and alert state are durable. An interrupted run may leave the lease
until its bounded expiry; never delete or overwrite it manually.

Inspect the live cc-ansible worktree, native curator/skill state, pending
learning backlog, bootstrap/reference reconciliation, and latest
self-evolution state. Attribute changed files to active work before alerting.
Do not reset, delete, stage, commit, or overwrite managed/user work. A source
candidate or review-debt count is internal until an unowned conflict, failed
gate, unsafe deletion, or owner decision blocks resolution. Review recent
correction clusters and prove that native background review wrote or revised
the appropriate memory/agent-created skill; escalate managed-policy gaps to the
operator. Never publish healthy audit summaries.

## Publication Gate

Before any message, apply the incident RCA gate and read the lane's absolute
alert-lifecycle file. Normalize the current condition before comparing it with
`activeFingerprint`, `status`, `lastObservedAt`, `lastPublishedAt`, and
`messageId`. Decide exactly one transition: `publish`, `suppress`, `resolve`,
or `re-alert`. Unchanged known, active, acknowledged, ignored, optional,
diagnostic-only, healthy, or no-op state must select `suppress` regardless of
age. A useful recovery may select `resolve`; re-alert requires material
scope/impact change, a new owner decision, or an explicit reminder.

Persist the selected transition and current observation to the absolute alert
file before invoking Discord. Only `publish`, `resolve`, or `re-alert` may call
the Discord tool; `suppress` may not compose or send a message. After a
successful send, persist the returned platform message ID. If delivery fails,
retain a pending publication transition for native delivery recovery. Never
send first and then search Discord to decide whether the message was a
duplicate, and never retract a message merely because the pre-send state check
was skipped. Regardless of whether a notice was sent, the scheduled final
response must be exactly `[SILENT]`.
Never return an internal verification summary or any other prose.
