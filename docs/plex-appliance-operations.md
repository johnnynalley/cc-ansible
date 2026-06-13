# Plex Appliance Operations

Last updated: 2026-06-08

Use this doc for quick operator actions on the managed Plex TV appliances.

## Host Map

- Bedroom Plex: `jn-t14s-lin` / T14s HDMI appliance.
- Living room Plex: `mercury` / Raspberry Pi 5 appliance.

## Plex Server Storage

Plex runs on `media-vm` in the `/opt/media-stack` Docker Compose project. The
Plex config, metadata, thumbnails, intro/credits analysis, and cache live under
`/opt/media-stack/plex`, which is mounted from the dedicated `plex-data` ext4
disk (`LABEL=plex-data`) backed by TS440 ZFS storage `nas-zfs-vm`.

The media libraries are not stored there. Plex reads library media through
`/srv/plex` and `/srv/archive`, which are TS440 VirtioFS paths. Temporary
transcode scratch stays on the VM root disk at `/var/lib/plex-transcode` and is
mounted into the Plex container as `/transcode`.

Plex library scanning must stay out of normal viewing hours. On 2026-06-02,
Bedroom finished an episode, then sat on a black screen while authenticated
Plex metadata endpoints timed out for several minutes. The root cause was a
live Plex scanner/analyzer process started by filesystem change detection
outside the maintenance window; the scanner was observed stuck in uninterruptible
I/O while Plex metadata requests hung. Live file-event and periodic all-day
library scans are disabled, the Plex Butler window is limited to 05:00-07:00,
and `plex-library-nightly-scan.timer` refreshes Plex sections during that late
overnight window.

Do not include `media-vm` / VM 100 in the cluster-wide PBS backup job while it
serves live Plex playback. On 2026-06-03, the all-VM PBS job started at
00:00 while `pbs-main` was unreachable from ts440, left VM 100 under
`lock: backup`, and made media-vm unreachable over LAN, Tailscale, SSH, and
Plex HTTP until the stuck vzdump task was canceled and the stale lock was
cleared. VM 100 is excluded from the all-VM PBS job; use storage-native
snapshots and explicitly scheduled maintenance for Plex data instead of
letting a failed PBS target lock the live Plex server.

## Plex Server Health And Scrub Guardrails

`playbooks/media/plex-server-health.yml` deploys `plex-server-health.timer` on
`media-vm` and `ts440`. The media-vm side verifies Plex identity, `/srv/plex`
as a VirtioFS mount, Plex/Matroska D-state threads, and recent guest kernel
hung-task evidence. The ts440 side verifies VM 100 is running, checks host
`virtiofsd` threads for uninterruptible I/O, and alerts if a ZFS scrub is active
outside the configured scrub safe window.

Use these read-only checks before restarting Plex, the VM, or ts440:

```bash
ansible media-vm -m command -a "/usr/local/sbin/plex-server-health --status" --become
ansible ts440 -m command -a "/usr/local/sbin/plex-server-health --status" --become
ansible media-vm -m shell -a "journalctl -k --since '30 min ago' | grep -Ei 'dmx0:matroska|request_wait_answer|fuse_file_read_iter|blocked for more'" --become
ansible ts440 -m shell -a "ps -eLo pid,tid,etimes,state,wchan,comm,args | grep '[v]irtiofsd'" --become
```

On 2026-06-07, Plex became unavailable after a WAN client forced a universal
transcode of `Gravity Falls - S01E06 - Dipper vs. Manliness` while the backing
`media-01` ZFS pool was actively scrubbing. The Plex transcoder's Matroska
reader blocked in the media-vm kernel FUSE/VirtioFS path
(`request_wait_answer` -> `__fuse_simple_request` -> `fuse_file_read_iter`).
Plex request threads then piled up waiting on database connections. Recovery
attempts could not fully unwind the D-state guest thread, and host-side
`virtiofsd`/VM scope state prevented VM 100 from starting cleanly until ts440
was rebooted.

That incident is a storage-path stall, not evidence that the episode file is
bad. The file later read cleanly and ZFS reported `0` scrub errors. The managed
ZFS scrub runner in `playbooks/storage/zfs.yml` now runs daily at 03:00 but only
inside the 03:00-09:00 safe window. Long scrubs are paused at the window end and
resumed on the next overnight run, so a serial scrub across `nas_zfs`,
`media-01`, and `media-02` does not spill into evening Plex usage.

## Playback Identity And Queue Safety

The appliances intentionally depend on Plex for metadata, access control, stream
decisioning, and media delivery. They are passive Plex health monitors: if Plex
cannot serve media, the appliances should fail visibly instead of bypassing Plex
with direct filesystem playback.

Default playback uses Plex raw part URLs,
`/library/parts/.../file.mkv`, so Plex remains in the media path without forcing
every x265 file through the transcoder. Raw part URLs must stay token-only. Do
not add static per-host `X-Plex-Session-Identifier` or client identity query
parameters to raw part URLs; the 2026-06-02 incident showed same-token ad-hoc
part requests fighting, and using the same fixed client identity for both
appliances made that collision easier to trigger.

`PLEX_APPLIANCE_STREAM_MODE=universal` is an explicit fallback, not the default.
The same 2026-06-02 incident showed Plex universal playback creating ad-hoc
hardware transcode sessions that can evict another appliance session with
`Streaming Resource: Terminating session ... which is using transcoder slot`,
even when the appliances have distinct client identifiers and session IDs.
Universal also forces HEVC-to-H.264 transcode and subtitle burn for common x265
episodes, which caused freezing/buffering that was not present with direct Plex
part streaming. Do not restart both appliances and call that fixed. Keep the
second appliance stopped until the Plex session/account/client-model root cause
is proven and corrected. Do not "fix" this by mounting the library locally or by
adding retry loops that hide recurrence.

Direct mpv playback starts without blocking on subtitle-content probes. When
subtitle content checks are enabled, the player lets mpv open the file normally,
then samples the active English subtitle stream and alternate English streams in
a background worker. If the active stream is CJK-heavy or has a cumulative cue
count that is far larger than a valid alternate stream, the player switches
`sid` over mpv IPC while playback continues. Universal stream mode cannot rely
on this live `sid` switching because Plex sessionized streams choose subtitles
through the Plex URL before playback starts.

The shuffle cycle must not count any failure path as watched. `played` means
the item reached normal playback completion. A verified corrupt file is moved
to `unplayable`, not `played`, so it does not loop forever and does not
masquerade as watched. Repeated playback failures without verified corruption
keep the same active item and retry later. This preserves the rule that
playable items are played at least once before the cycle repeats.

The saved shuffle state is authoritative per appliance. Reboots, playbook
runs, and player restarts must not reshuffle an appliance queue while that
appliance still has queued, active, or newly discovered playable items that
have not completed in the current cycle. New Plex items that enter the
collection mid-cycle are inserted at a random position after the current
playback position. If no item is actively playing but a queued item is about
to start, the queued head is treated as the current position so new items do
not jump ahead of it. Bedroom and Mercury keep separate cycles.

Plex HTTP stream interruptions are not file-corruption proof. If ffmpeg is
checking a Plex URL and Plex returns `503`, resets the stream, or ends the HTTP
response prematurely, the check is inconclusive and the item must remain active
rather than moving to `unplayable` or advancing the queue. Treat file-level
corruption as verified only when the evidence is not just Plex
transport/session failure.

Full collection refreshes are expensive because the Adult Swim collection
expands show directories through Plex metadata paging. The 2026-06-02 retry
incident showed both appliances refreshing the same collection at the same time,
with Plex metadata requests taking 80-100 seconds and exceeding the player read
timeout. Do not set both appliances back to synchronized hourly refreshes. Keep
saved queue state authoritative across restarts, delay the first full refresh
when a queue already exists, and keep refresh jitter enabled so bedroom and
Mercury do not stampede Plex together.

Some Plex items report a longer duration than the direct playable stream
actually provides. The 2026-06-02 bedroom loop on `The Boondocks - The Itis`
reached the real credits/end around 1188 seconds while Plex reported 1298
seconds, so the player kept resuming near the credits and never crossed the
Plex-reported completion threshold. Repeated failures at a clean observed EOF
near the end of the Plex duration should count as watched, because the item
reached the actual playable end. Repeated failures after the saved position is
already inside the normal completion threshold should also count as watched
when ffmpeg verifies the remaining end window. Do not count earlier short
decodes or Plex transport failures as watched.

## Bedroom HDMI Display Ownership

The T14s HDMI appliance uses mpv with direct DRM on VT8. When no real local
seat session is active, the HDMI watcher stops `sddm.service` before starting
playback and starts it again when HDMI appliance mode exits.

This prevents the SDDM Wayland greeter/KWin on VT1 from contending with mpv for
the same AMD DRM device. The failure signature that led to this rule was:

- TV shows the login screen or black video while HDMI audio continues.
- `sddm.service` repeatedly logs `Using VT 1`, `Jumping to VT 1`, or greeter
  restart messages.
- Kernel logs show AMDGPU/DMCUB DRM errors near the same timestamp.
- mpv logs show video configuration or AMDGPU initialization failures.

Do not treat a player restart or VT switch as the fix for this class of
incident. Preserve the logs and prove which process owned the display stack
before changing recovery behavior.

For `mpv did not configure video` loops on bedroom, check kernel DRM/amdgpu
logs before blaming Plex or the media file. On 2026-06-02, the loop occurred
while the kernel logged `drm_mode_rmfb_work_fn` CPU hog warnings and an amdgpu
DMCUB diagnostic error, and the host was still booted on `7.0.0-15-generic`
even though `7.0.0-22-generic` was installed. The Plex stream and file were
healthy: the same direct URL later played with mpv reporting `vo-configured`,
VAAPI HEVC decode, and advancing `time-pos`. Prevention for that class is to
boot the newer installed kernel or continue graphics-stack RCA, not to mark the
episode bad. Bedroom uses a 45 second mpv startup window so transient DRM setup
slowness does not cause false playback retries.

If `mpv did not configure video within ...; retrying` appears at the end of
otherwise healthy playback, treat it as a player monitor bug until proven
otherwise. On 2026-06-02, living room reached episode credits, briefly stopped
returning mpv IPC video properties during EOF teardown, and the appliance still
applied the startup timer because readiness was not latched after first video
configuration. The fix is to apply the startup timeout only before the first
successful mpv readiness signal; after playback has been observed, late missing
IPC properties must fall through to normal EOF/stall handling instead of
restarting and replaying the tail.

## Bedroom Not Playing Quick Triage

If Bedroom Plex is not playing but the appliance service appears active, first
check the state file and the player syslog tag before restarting or skipping
anything:

```bash
python3 - <<'PY'
import json
import time

path = "/var/lib/plex-appliance/shuffle-state.json"
data = json.load(open(path))
active = data.get("active") or {}
queue = data.get("queue") or []
updated = active.get("updated_at") or data.get("updated_at") or 0
print(json.dumps({
    "active": active,
    "queue_count": len(queue),
    "queue_head": queue[:5],
    "updated_age_seconds": int(time.time()) - int(updated),
}, indent=2))
PY

journalctl -t plex-appliance-tv --since '30 min ago' --no-pager
pgrep -a -f '[p]lex-appliance|[m]pv'
```

Use `journalctl -t plex-appliance-tv`, not only
`journalctl -u plex-appliance-tv.service`; recent player logs may be easiest to
find by the service's `SyslogIdentifier`.

If `active` is empty, `queue_count` is still nonzero, no `mpv` process exists,
and the log repeats `Plex unavailable` with connection timeouts to
`100.66.6.113:32400`, classify it as a Plex server reachability/dependency
failure. The appliance is waiting for Plex `/identity` to answer before it
selects the next item. Do not mark an episode played or skip the queue for this
failure mode. Investigate Plex/media-vm reachability or let the appliance retry;
when Plex responds again, the player should advance to the next queued item.

On 2026-06-13, Bedroom finished `Family Guy - Season 12 - The Most Interesting
Man in the World` at 09:40:41 CDT, then could not start the next item until
09:46:19. Plex itself was healthy: media-vm `plex-server-health.service` passed
at 09:38:52, 09:43:57, and 09:48:59, and TS440 storage-host health passed at
09:41:52 and 09:46:53. Bedroom `NetworkManager` and kernel logs showed no
Wi-Fi/ath11k churn. The failing dependency was the Tailscale path from Bedroom
`100.73.46.86` to media-vm `100.66.6.113:32400`: Bedroom `tailscaled` logged
repeated `open-conn-track: timeout opening ... to node [c0RSf]; online=yes`,
with `lastRecv` from media-vm aging from `3m29s` to `8m58s`. Playback resumed
immediately when Tailscale rediscovered a usable media-vm endpoint.

For this pattern, prove the path issue with:

```bash
journalctl -u tailscaled --since '<event-start>' --until '<event-end>' --no-pager \
  | grep -E '100\.66\.6\.113|open-conn-track|lastRecv|node \[c0RSf\]|lazyEndpoint'
ansible media-vm -m shell -a "journalctl -u plex-server-health.service --since '<event-start>' --until '<event-end>' --no-pager" --become
ansible ts440 -m shell -a "journalctl -u plex-server-health.service --since '<event-start>' --until '<event-end>' --no-pager" --become
```

If local Plex and storage health pass while Bedroom Tailscale shows stale
media-vm endpoint receive times, the prevention path is to stop depending on
the Tailscale address for a same-LAN appliance. Prefer pointing Bedroom at
media-vm's LAN Plex address (`http://192.168.1.136:32400`) after confirming
firewall reachability and preserving the existing Plex token/auth model.

## Skip Current Bedroom Plex Episode

Run this on `jn-t14s-lin` from any shell. It stops the HDMI watcher and player,
creates a Sanoid-backed rollback copy of the shuffle state, marks the active
item as played, and lets the watcher start the next item.

Do not use `/tmp` or a host-local state copy as the durable rollback for this
operation. If `/usr/local/sbin/live-rollback-backup` or `/srv/live-rollbacks`
is missing, deploy the NFS client path first with
`ansible-playbook playbooks/storage/nfs.yml`.

```bash
set -euo pipefail

sudo -n systemctl stop plex-appliance-hdmi-vt-watcher.service plex-appliance-tv.service
trap 'sudo -n systemctl start plex-appliance-hdmi-vt-watcher.service' EXIT

state="/var/lib/plex-appliance/shuffle-state.json"
backup="$(sudo -n live-rollback-backup \
  --domain plex-appliance \
  --name skip-current-bedroom \
  --path "$state")"

sudo -n python3 - <<'PY'
import json
import pathlib
import time

path = pathlib.Path("/var/lib/plex-appliance/shuffle-state.json")
data = json.loads(path.read_text())
active = data.get("active") or {}
key = active.get("key")
title = active.get("title") or key
if not key:
    raise SystemExit("No active Plex appliance item to skip.")

played = data.setdefault("played", [])
if key not in played:
    played.append(key)
data["active"] = None
data["updated_at"] = int(time.time())
path.write_text(json.dumps(data, separators=(",", ":")) + "\n")
print(f"Skipped {title} ({key})")
PY

printf 'State backup: %s\n' "$backup"
```

Verify the player advanced:

```bash
systemctl status plex-appliance-tv.service --no-pager
python3 -c "import json; d=json.load(open('/var/lib/plex-appliance/shuffle-state.json')); print(d.get('active'))"
```

Rollback if the wrong item was skipped:

```bash
sudo -n systemctl stop plex-appliance-hdmi-vt-watcher.service plex-appliance-tv.service
backup="/srv/live-rollbacks/jn-t14s-lin/plex-appliance/YYYYMMDDTHHMMSSZ-skip-current-bedroom"
sudo -n cp "$backup/files/var/lib/plex-appliance/shuffle-state.json" /var/lib/plex-appliance/shuffle-state.json
sudo -n systemctl start plex-appliance-hdmi-vt-watcher.service
```

## Related Commands

Corruption alerts and heartbeat checks are documented in
`docs/openclaw-heartbeats.md`.
