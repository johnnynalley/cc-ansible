# Plex Appliance Operations

Last updated: 2026-06-02

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

The shuffle cycle must not count any failure path as watched. `played` means
the item reached normal playback completion. A verified corrupt file is moved
to `unplayable`, not `played`, so it does not loop forever and does not
masquerade as watched. Repeated playback failures without verified corruption
keep the same active item and retry later. This preserves the rule that
playable items are played at least once before the cycle repeats.

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
