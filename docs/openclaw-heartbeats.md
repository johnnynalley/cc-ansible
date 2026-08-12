# OpenClaw Heartbeats

The current production Astra heartbeat is still driven by the legacy
human-owned workspace:

```text
/home/johnny/.openclaw/workspace/HEARTBEAT.md
```

on the current OpenClaw host. That path remains production evidence only until
the attended dedicated-user cutover. The modern source is
`files/openclaw/workspace/HEARTBEAT.md`, with role-specific files for Dubble
and Rigel. Vega and Antares are request-scoped and have no heartbeat file.

Do not model this as an OpenClaw cron unless exact timing or isolated delivery
is the requirement. Heartbeat-owned policy belongs in the live heartbeat
catalog, but checks run by cadence and cost rather than as one all-at-once
batch.

## Management Model

In the modern runtime, heartbeat behavior is root-deployed, read-only source.
Astra may write proposals and evidence but cannot mutate active heartbeat
policy. Mutable cadence state and delivery receipts remain runtime data. This
replaces the legacy model where Astra could edit live prompt policy in place.

When adding a heartbeat check:

1. Update the repo-owned role heartbeat source and the exact procedure under
   the reviewed heartbeat catalog.
2. Assign a stable check ID, cadence, owner, and execution lane.
3. Run `scripts/agents/openclaw-bootstrap-audit.py` and the semantic heartbeat
   regressions before promotion.
4. Verify the exact command works as the dedicated identity without overlapping
   another heavy or OpenClaw CLI check.
5. Promote through the owner/Codex deployment path with rollback evidence.

## Scheduling And Resource Model

The heartbeat stays enabled continuously so it is ready when a check or alert
becomes relevant. An idle heartbeat should produce no Discord message.

The modern response contract uses OpenClaw's native structured
`heartbeat_respond` tool. An idle run records `notify=false`; a real alert uses
`notify=true` with one concise notification. `lightContext: true`,
`isolatedSession: true`, and `includeReasoning: false` prevent old conversation
history and hidden reasoning from becoming delivery input. This replaces the
custom suffix-matching guard for heartbeat text. The guard is retired at
cutover rather than expanded to match more truncated token variants.

Rigel remains scheduled every 30 minutes around the clock. Its no-op path reads
only the canonical semester source and an optional pending-calendar file after
a non-failing existence check, then records `notify=false`. Empty semesters do
not disable Rigel and do not produce a message, reasoning dump, or expected
missing-file banner.

Before production cutover, `playbooks/agents/openclaw-behavior-rehearsal.yml`
proves this contract in the channel-less loopback canary. Its normal baseline
sets every heartbeat to `0m`. The attended probe temporarily renders only
Rigel at `24h`, triggers one targeted native system event, and requires a new
isolated heartbeat transcript containing exactly one `heartbeat_respond` with
`notify=false`, no visible assistant text or tool errors, and a silent
structured heartbeat event with no channel or recipient. It then immediately
restores the all-`0m` baseline and archives the synthetic sessions through
OpenClaw's native session RPC. This proof has not run yet because it requires a
successful applied silent-canary data handoff first.

The legacy production sources remain:

```text
/home/johnny/.openclaw/workspace/HEARTBEAT.md
/home/johnny/.openclaw/workspace/references/heartbeat-procedures.md
/home/johnny/.openclaw/workspace/references/heartbeat-checks.md
/home/johnny/.openclaw/workspace/memory/heartbeat-state.json
```

`heartbeat-state.json` schema 2 stores an ISO-8601 `lastCompletedAt` and a
concise `lastResult` per check. Result prose, alert timestamps, and the mere
existence of a prior state row do not decide whether a check is due. A missing
or legacy state file cold-starts the every-poll lane plus at most one deferred
check; it never makes the full catalog due at once.

Execution boundaries:

- At most three explicitly lightweight checks may run concurrently.
- Heavy checks run one at a time.
- OpenClaw CLI checks run one at a time and wait for their process trees to
  exit before another OpenClaw CLI check starts.
- OpenClaw CLI initialization may touch or permission-check its configured
  state even for `--help`, status, or dry-run commands. Product-discovery probes
  use a credential-free writable scratch profile; live operational checks run
  as the exact state-owning identity. Never point a read-only sandbox or wrong
  user at production state and then publish its expected permission diagnostics.
- Heavy checks are deferred when `MemAvailable` is below 4 GiB, `SwapFree` is
  below 2 GiB, or kernel `Writeback` exceeds 512 MiB.
- Deferral is silent scheduling state. It is not itself a Discord alert and it
  does not advance `lastCompletedAt`.

The every-poll lane keeps calendar, cron status, live empty-turn detection, and
the cached media/stream sentinels responsive. Estate-wide storage, Doctor,
skills, memory, model, bootstrap, corruption, DAS, hygiene, and self-evolution
checks are staggered at longer cadences in the live catalog.

## 2026-08-10 OOM RCA

At 09:17 CDT the production Gateway was killed by the global OOM killer and
restarted automatically at 09:18. The heartbeat trajectory showed one turn
launching 21 checks through an unbounded `Promise.all`, including Doctor,
skills, cron, remote storage, media, weather, bootstrap, hygiene, and
self-evolution probes. Those OpenClaw commands spawned additional hook workers
inside the Gateway cgroup while the host had exhausted swap and was carrying
heavy NFS writeback. The heartbeat fan-out was the immediate resource
amplifier; NFS writeback and existing swap pressure were contributing host
conditions.

The durable fix is the scheduling/resource model above. Restarting the Gateway,
muting alerts, or suppressing individual check errors would not address this
cause. A controlled non-delivering validation after the repair ran only the
five every-poll checks, produced no tool failure or Discord `message` call, and
left the production service on the same PID.

## Stream Relay Check

Astra should run this from the current OpenClaw host:

```bash
ssh dbc@100.66.6.113 '/usr/local/sbin/stream-relay-health --no-alert'
```

Healthy output:

```text
OK: stream relay health checks passed
```

Any nonzero exit or `CRITICAL:` output should alert Discord `#astra`.

This is separate from the local `stream-relay-health.timer` on `media-vm`, which also runs the same checks and alerts through Apprise/DBC.

Current VOD recording covers the landscape relay only. Vertical/mobile recording is not included until a separate recording path is explicitly added.

## Media Stack Check

Astra should run this from the current OpenClaw host:

```bash
ssh dbc@100.108.254.100 'sudo -n /usr/local/sbin/media-stack-health --status'
```

Healthy output:

```text
OK: cached media-stack health passed <age>s ago
```

Any nonzero exit or `CRITICAL:` output should alert Discord `#astra`.
If the command exits zero but includes a `WARNINGS:` section, Astra should not
send recurring heartbeat notifications. Those warnings are operator context for
manual review or digest-style summaries, not evidence that the media stack is
down. Current expected warning class: recent qBittorrent imports that were
copied instead of hardlinked because mergerfs placed the download and library
file on different backing branches. Repeated docker-vm NFS `fileid changed`
kernel errors are also warning-only by default because they can occur while Arr
imports are still progressing over the TS440 mergerfs export. They should page
only when paired with a nonzero `CRITICAL:` condition such as missing mounts,
empty library probes, stuck media probes, stopped containers, or failed imports.

This reads the cached result from the local `media-stack-health.timer` on `docker-vm`, which runs the full checks and alerts through Apprise/DBC. The cached heartbeat read avoids starting fresh NFS/mergerfs-touching probes from Astra. The timer covers the migrated Sonarr/Radarr/download automation on docker-vm while Plex stays on media-vm.

The media-stack check is alert-only. It must not pause Profilarr, stop searches,
or mutate queue/download state. Current storage/import guardrails include
warning-only repeated docker-vm NFS `fileid changed` kernel errors, Arr media
probe processes such as `ffprobe` stuck in `D` state, and
Sonarr/Radarr non-long-running commands that are old and have stopped making
command-message progress past the no-progress threshold. Commands the Arr API
explicitly marks `isLongRunning=true`, such as Sonarr's
`ProcessMonitoredDownloads`, are skipped by the stalled-command check; actual
storage stalls for those paths are covered by mount probes and D-state media
probe checks.

Stale docker-vm NFS recovery is owned by systemd on `docker-vm`, not by Astra.
If `media-stack-health.service` fails because required NFS-backed bind paths are
stale, unreadable, or missing, `media-stack-storage-recover.service` can refresh
the affected client mounts, restart the media-stack compose project, run
qBittorrent port sync, and validate health. Astra should report the cached
`CRITICAL:` result and recovery/failure messages, but it should not attempt its
own remount or container restart from the heartbeat prompt.

## Plex Appliance Verified Corruption Check

The Plex appliances do not scan media on a schedule. They only write playback
failure records after normal playback fails the same item repeatedly and an
automatic targeted `ffmpeg` decode check confirms the Plex stream could not be
decoded.

Astra should check the verified-corruption report from the current OpenClaw host:

```bash
# jn-t14s-lin / t14s: T14s HDMI Plex appliance on the OpenClaw host.
/usr/local/bin/plex-appliance-corrupt-media-report --since-hours 168

# mercury: living room Raspberry Pi 5 Plex appliance.
ssh dbc@100.81.29.94 '/usr/local/bin/plex-appliance-corrupt-media-report --since-hours 168'
```

Healthy output starts with `OK:`. Plex HTTP/storage-path failures, especially
`input/output error`, are suppressed by default because they can be transient
NAS, mergerfs, VirtioFS, or Plex stream-path failures even when the media file
later decodes cleanly from the backing mount. If the command reports suppressed
storage failures in the `OK:` line, do not page Johnny as corrupt media; rely on
the media mount and media-stack checks for storage-health paging, and inspect
manually with `--show-storage-failures` when needed.

Any output starting with `CRITICAL:` means the appliance found an actionable
file-corruption signature during attempted playback. Alert Johnny in Discord
`#astra` with the title, timestamp/position, reason, and file path so the
release can be replaced and the backing drive can be checked if patterns emerge.

De-duplicate by title, file path, and position in
`memory/plex-corrupt-media-alerts.json`; alert once per finding per 24 hours and
send a recovery/clear note only when the weekly window is clean after a prior
alert.

## Verify

Verify the scheduler contract and structured state first:

```bash
grep -n 'Schedule And Execution Lanes' /home/johnny/.openclaw/workspace/references/heartbeat-checks.md
jq -e '.schemaVersion == 2 and (.checks | type == "object")' /home/johnny/.openclaw/workspace/memory/heartbeat-state.json
awk '/^(MemAvailable|SwapFree|Writeback):/ {print}' /proc/meminfo
```

For a controlled no-op test, invoke one heartbeat turn without direct delivery,
inspect its trajectory for the due check IDs, require exactly one structured
`heartbeat_respond` call with `notify=false`, verify there is no `message` tool
call or assistant text/reasoning delivery, and compare the Gateway PID/cgroup
memory before and after. Text-token suppression alone is not sufficient proof.

Validate the modern bundle before any deployment:

```bash
python3 scripts/agents/openclaw-bootstrap-audit.py --root files/openclaw/workspace
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest scripts.agents.test_openclaw_bootstrap_audit -v
```

Until cutover, check the legacy production heartbeat section separately:

```bash
ansible jn-t14s-lin -m command -a "grep -n 'Stream Relay And VOD Health' /home/johnny/.openclaw/workspace/HEARTBEAT.md"
ansible jn-t14s-lin -m command -a "grep -n 'Media Stack Health' /home/johnny/.openclaw/workspace/HEARTBEAT.md"
```

Check the exact media stack command Astra uses:

```bash
ansible jn-t14s-lin -m shell -a "ssh -o BatchMode=yes -o ConnectTimeout=8 dbc@100.108.254.100 'sudo -n /usr/local/sbin/media-stack-health --status'"
```

Check the exact stream relay command Astra uses:

```bash
ansible jn-t14s-lin -m shell -a "ssh -o BatchMode=yes -o ConnectTimeout=8 dbc@100.66.6.113 '/usr/local/sbin/stream-relay-health --no-alert'"
```

Check the exact Plex appliance corruption commands Astra uses:

```bash
ansible jn-t14s-lin -m command -a "/usr/local/bin/plex-appliance-corrupt-media-report --since-hours 168"
ansible jn-t14s-lin -m shell -a "ssh -o BatchMode=yes -o ConnectTimeout=8 dbc@100.81.29.94 '/usr/local/bin/plex-appliance-corrupt-media-report --since-hours 168'"
```
