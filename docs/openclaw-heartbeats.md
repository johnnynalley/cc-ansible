# Agent Scheduling And Heartbeats

## Current Production

Hermes owns production scheduling on `jn-t14s-lin`. OpenClaw's Gateway and
scheduler are stopped and disabled. Astra has seven native jobs:

- Rigel academic evaluation every 30 minutes, continuously;
- STW and Warframe deterministic watches every minute;
- the HDD deal review every hour;
- Daily Summary at 07:08 America/Chicago;
- Fortnite progress at 06:50 America/Chicago; and
- weekly social-seed review Sunday at 09:00 America/Chicago.

The source inventory contained 26 current OpenClaw cron rows, three logical
heartbeats, and two historical completed one-shots. All 31 lanes have an
explicit retained, replaced, collapsed, completed, or retired disposition in
`files/hermes/production-automation-reconciliation.json`. OpenClaw-specific
self-maintenance, session janitors, and generic all-clear heartbeats were not
recreated. Root-managed systemd timers own retained data collectors, feed and
calendar synchronization, profile backups, native updates, and service health.

## Production Contract

The scheduling source of truth is the credential-free template
`templates/hermes/astra-production-jobs.json.j2`, rendered with private route
values into `/etc/hermes/astra/production-jobs.json`. The convergence entrypoint
is `playbooks/agents/hermes-automation.yml`. It backs up profile and runtime
state, keeps check mode read-only, excludes active timers from the transaction,
restores their prior state, reconciles through Hermes's native cron API, and
rolls back on any failed assertion.

Rigel is never disabled merely because a semester is complete. Its script-only
job reads structured canonical course state and an optional pending-calendar
file after non-failing existence checks. No due event, a completed semester,
an empty optional file, and an absent optional daily-memory file are normal
successful states with empty output. Only source-backed due events reach
`#rigel`; expected absence, control tokens, reasoning text, and command errors
must never become Discord messages.

Agent-backed jobs receive bounded collector output and produce one concise
message or `[SILENT]`. Deterministic jobs run without a model. A failed
collector or malformed source is recorded in private state and owned by the
service-health path; it is not reformatted into user-facing noise. The Gateway
serializes native jobs to avoid the legacy unbounded heartbeat fan-out.

When changing production scheduling:

1. Update the production job template or the owning systemd collector.
2. Update the 31-lane reconciliation when ownership or disposition changes.
3. Extend the relevant `test_hermes_*automation.py` regression.
4. Run the automation playbook in check mode, then apply it transactionally.
5. Prove native cron zero drift, expected idle silence, timer health, profile
   backups, OpenClaw exclusion, and Health receiver continuity.

## Retained OpenClaw Historical Reference

The remainder of this document records the source system, incidents, and
migration rationale. It is not current production guidance. The retained
legacy sources are:

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
