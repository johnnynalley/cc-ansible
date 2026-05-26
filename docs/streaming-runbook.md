# Streaming Runbook

> Last updated: 2026-05-25

This is the current streaming setup across the gaming PC, media-vm, and MacBook.
It is meant to answer one question first: "what do I do to go live?"

## Simple Go Live Steps

Use this when you just want to start the stream.

1. On the gaming PC, open OBS.
2. On the MacBook, open OBS.
3. In Mac OBS, use the `TikTok Vertical` scene.
4. In Mac OBS, start Virtual Camera if it is not already running.
5. On the MacBook, open TikTok LIVE Studio.
6. In TikTok LIVE Studio, confirm:
   - Camera is `OBS Virtual Camera`
   - Mic/audio input is `BlackHole 2ch`
   - Desktop/system audio is muted
   - Mic cleanup/effects/noise suppression are off
7. On the gaming PC, start the Aitum vertical output to the media-vm broker.
8. Confirm TikTok LIVE Studio shows the vertical feed and its mic meter moves with game audio.
9. Open SleepyChat for Twitch, YouTube, and TikTok chat.
10. Optional: if using Apple Music from the MacBook, open `SonoBus Apple Music Receiver` on the gaming PC and connect the Mac OBS SonoBus plugin to the same group.
11. When ready to actually go live, click Start Streaming in gaming PC OBS.
12. When ready to actually go live on TikTok, start the TikTok LIVE Studio stream on the MacBook.

That is the normal flow. The media-vm relay services are expected to already be running in the background.

Starting the gaming PC OBS stream is a real go-live action for Twitch and YouTube. Starting TikTok LIVE Studio is a real go-live action for TikTok.

## Current Topology

```text
Gaming PC OBS
  landscape SRT
    -> media-vm stream-relay.service
    -> local MPEG-TS/TCP fanout on media-vm
    -> media-vm stream-relay-output@twitch.service
    -> media-vm stream-relay-output@youtube.service
    -> Twitch + YouTube landscape RTMP

Gaming PC OBS / Aitum Vertical
  vertical RTMP
    -> media-vm stream-relay-vertical-broker.service
    -> Mac OBS
    -> OBS Virtual Camera
    -> TikTok LIVE Studio on Mac

Mac OBS
  MacBook webcam
    -> DistroAV NDI "MacBook Webcam"
    -> Gaming PC OBS webcam source

Mac OBS
  TikTok Vertical Broker audio monitor
    -> BlackHole 2ch
    -> TikTok LIVE Studio mic input

Mac OBS
  Apple Music app audio
    -> OBS VST filter "SonoBus Apple Music"
    -> Windows SonoBus
    -> SteelSeries Sonar Media
```

## Production Paths

These are the paths to rely on for a real stream.

- Landscape encoding and VOD are handled by `stream-relay.service` on `media-vm`.
- Landscape fanout is handled by local MPEG-TS/TCP feeds from `stream-relay.service` to one `stream-relay-output@<platform>.service` worker per platform.
- The producer copies OBS's incoming AAC audio instead of adding another producer-side AAC encode.
- Twitch copies that audio to RTMP.
- YouTube re-encodes audio with `aresample=async=1:first_pts=0` so YouTube gets fresh 48 kHz audio timestamps.
- The relay does not use FFmpeg `nobuffer`/`low_delay` flags; the SRT path already has explicit latency, and aggressive low-delay buffering caused audible artifacts in live testing.
- With the current TCP fanout, if a platform worker disconnects after latching, restart the full landscape relay set instead of only restarting that output worker.
- TikTok LIVE Studio runs on the MacBook, not the gaming PC.
- TikTok receives video from the Mac OBS virtual camera.
- TikTok receives stream audio from `BlackHole 2ch`, which Mac OBS monitors from the vertical broker source.
- `BlackHole 2ch` is only a virtual cable. It does not process, clean up, compress, or enhance audio.
- TikTok LIVE Studio must not apply mic cleanup/effects/noise suppression to `BlackHole 2ch`, because this input is the full stream mix, not a raw microphone.
- Leave the Mac's normal default input/output as `MacBook Pro Microphone` and `MacBook Pro Speakers`. Do not make `BlackHole 2ch` the Mac default device for day-to-day use.
- SleepyChat is the current unified chat tool for Twitch, YouTube, and TikTok.
- TikTok LIVE Studio should still stay open for TikTok stream control and fallback chat visibility.
- YouTube Shorts/vertical is currently handled by YouTube's automatic dual-stream feature.

This is intentionally parked for now:

- `stream-relay-vertical.service` for a separate standalone YouTube Shorts stream key.
- A separate YouTube Shorts event/key, because SleepyChat does not handle multiple YouTube live chats cleanly enough for the current workflow.

This is optional:

- Apple Music from the MacBook to the gaming PC through SonoBus. It is not required for going live.

## Hosts And Addresses

| Host | Role | Relevant addresses |
| --- | --- | --- |
| `lj-gaming-pc` | Gaming PC, OBS compositor, Aitum Vertical output | Tailscale `100.78.248.44`, LAN `192.168.1.9` |
| `media-vm` | FFmpeg/Quadro stream relay and vertical RTMP broker | Tailscale `100.66.6.113`, LAN `192.168.1.136` |
| `macbook-pro` | TikTok LIVE Studio, Mac OBS, webcam, optional Apple Music sender | Tailscale `100.119.197.17`, dock Ethernet `192.168.1.60`, Wi-Fi `192.168.1.104` |

The production landscape stream relay binds to media-vm's LAN IP so the high-bitrate OBS SRT feed stays on the switch instead of traversing Tailscale. The gaming PC has a persistent host route for `192.168.1.136/32` through Ethernet because Tailscale advertises `192.168.1.0/24`. The vertical TikTok broker still uses Tailscale.

## Go Live Checklist

### 1. media-vm

Confirm the relay, platform workers, health timers, and TikTok broker are up:

```bash
ansible media-vm -m shell -a "systemctl is-active stream-relay.service stream-relay-output@twitch.service stream-relay-output@youtube.service stream-vod-mover.timer stream-relay-health.timer stream-relay-vertical-broker.service" --become
```

Expected:

```text
active
active
active
active
active
active
```

The parked standalone YouTube vertical relay should normally be stopped:

```bash
ansible media-vm -m shell -a "systemctl is-enabled stream-relay-vertical.service; systemctl is-active stream-relay-vertical.service" --become
```

Expected normal state:

```text
disabled
inactive
```

### 2. Gaming PC OBS

Open OBS on the gaming PC.

Landscape output:

- Service: Custom
- Server: `srt://192.168.1.136:9000?mode=caller&transtype=live&latency=5000000`
- Stream key: any non-empty placeholder, for example `obs`
- Streaming bitrate: `12000 Kbps`

Starting the OBS stream is a real go-live action for any platform enabled in `stream_relay_outputs`. The media-vm output workers forward that feed to Twitch and YouTube using the live stream keys on media-vm.

The gaming PC keeps a persistent host route for `192.168.1.136/32` through the Ethernet interface. Tailscale advertises a `192.168.1.0/24` subnet route with a lower metric, so this host route is required or Windows may send the media-vm LAN address through Tailscale instead of the switch.

Aitum vertical output:

- Server: `rtmp://100.66.6.113:1936/live`
- Stream key: `vertical`
- Audio bitrate: `160`
- Video bitrate used during setup: `12000`

Start or verify the Aitum vertical output before checking TikTok Studio on the Mac.

### 3. Mac OBS

Open OBS normally. Do not launch it with `--startvirtualcam`; that path showed a misleading macOS virtual-camera warning even when the camera extension was enabled.

In the `TikTok Vertical` scene:

- `TikTok Vertical Broker` should show the Aitum vertical feed.
- `TikTok Vertical Broker` audio monitoring should be `Monitor and Output`.
- `Video Capture Device` / MacBook webcam should stay visible, locked, and parked off-canvas. Do not hide it. Hiding it froze the DistroAV webcam feed before.
- Monitoring device should be `BlackHole 2ch`.
- The `Apple Music` source should not be monitored into BlackHole; it is only used for the optional SonoBus sender path.
- Start OBS Virtual Camera if it is not already started.

### 4. TikTok LIVE Studio On Mac

TikTok LIVE Studio source setup:

- Camera: `OBS Virtual Camera`
- Mic/audio input: `BlackHole 2ch`
- Desktop/system audio: muted
- Mic cleanup/effects/noise suppression/voice enhancement: off

The muted desktop/system audio matters because TikTok LIVE Studio on macOS can grab desktop audio by default. Keep TikTok alerts on the Mac speakers if needed, but do not let TikTok Studio capture desktop/system audio unless that is intentional.

BlackHole should not be the Mac's default mic. The MacBook remains a normal work laptop; Teams and normal apps should continue to use `MacBook Pro Microphone` unless intentionally changed.

### 5. Chat And Dashboards

- SleepyChat: use for Twitch, YouTube, and TikTok chat.
- TikTok LIVE Studio: keep open for TikTok stream control and fallback chat.
- Twitch: check Creator Dashboard or Twitch Inspector for stable bitrate.
- YouTube: check Live Control Room. YouTube can sit on "Preparing stream" for a few minutes before the stream appears.

## Stopping After Stream

Stop OBS streaming and Aitum vertical output on the gaming PC.

The media-vm services can stay enabled. When no sender is connected, they are just waiting for the next feed or being restarted by systemd after FFmpeg exits.

Do not force-close OBS unless it is stuck. Force-closing OBS caused crash prompts during setup and makes it harder to know whether there is a real OBS problem.

## Managed Config

Repo-managed files:

- `playbooks/media/stream-relay.yml`
- `inventory/host_vars/media-vm/stream-relay.yml`
- `templates/streaming/stream-relay.sh.j2`
- `templates/streaming/stream-relay.service.j2`
- `templates/streaming/stream-relay-output.sh.j2`
- `templates/streaming/stream-relay-output@.service.j2`
- `templates/streaming/stream-relay-vertical.sh.j2`
- `templates/streaming/stream-relay-vertical.service.j2`
- `templates/streaming/stream-relay-vertical-broker.service.j2`
- `templates/streaming/mediamtx-vertical-broker.yml.j2`
- `scripts/streaming/configure-aitum-tiktok-broker.ps1`
- `scripts/streaming/configure-mac-apple-music-ndi.py`
- `scripts/streaming/configure-mac-apple-music-sonobus.py`

The old landscape MediaMTX broker templates are still in the repo, but the active landscape path has `stream_relay_broker_enabled: false` and uses local TCP fanout instead.

Live-only secrets and platform keys:

- `/etc/stream-relay/stream-relay.env` on `media-vm`

Do not commit stream keys. The repo only stores the root-readable example file generated by the playbook.

Current relay output workers are controlled by `stream_relay_outputs` in `inventory/host_vars/media-vm/stream-relay.yml`, for example:

```text
stream_relay_outputs:
  - twitch
  - youtube
```

`/etc/stream-relay/stream-relay.env` still holds the live-only platform URLs, stream keys, and per-output query flags. Do not commit stream keys.

## Health Checks And VOD Delivery

The stream relay has two health layers:

- `stream-relay-health.timer` runs on `media-vm` and alerts through Apprise/DBC.
- Astra reads `/home/johnny/.openclaw/workspace/HEARTBEAT.md` on the current OpenClaw host (`jn-t14s-lin` / T14s as of 2026-05-24) and runs the external heartbeat check from there.

Manual check from the Ansible controller:

```bash
ansible jn-t14s-lin -m shell -a "ssh -o BatchMode=yes -o ConnectTimeout=8 dbc@100.66.6.113 '/usr/local/sbin/stream-relay-health --no-alert'"
```

Expected:

```text
OK: stream relay health checks passed
```

The Astra heartbeat entry lives directly in `/home/johnny/.openclaw/workspace/HEARTBEAT.md` on the OpenClaw host. See `docs/openclaw-heartbeats.md` before changing heartbeat behavior.

Current VOD recording covers the landscape relay only. It records into `/srv/stream-vod-spool` on `media-vm`, then remuxes and delivers to `Stream VODs` inside the Nextcloud Media folder. The vertical/mobile path is not recorded until it is explicitly wired later.

Tiny recorder fragments under the minimum valid size are moved to `/srv/stream-vod-spool/discarded` instead of the failed queue. Stale incoming recordings are checked by `stream-vod-mover`: readable files are salvaged into the remux queue, unreadable files move to `failed`, and stale tiny header-only fragments are discarded.

## Troubleshooting

### Twitch Or YouTube Does Not Go Live

Check the relay log:

```bash
ansible media-vm -m shell -a "journalctl -u stream-relay.service -n 120 --no-pager" --become
```

Check the platform worker logs:

```bash
ansible media-vm -m shell -a "journalctl -u stream-relay-output@twitch.service -u stream-relay-output@youtube.service -n 160 --no-pager" --become
```

Check that the Quadro encoder is being used:

```bash
ansible media-vm -m shell -a "nvidia-smi" --become
```

If YouTube says "Preparing stream", wait a few minutes and refresh Live Control Room before changing anything. This happened during testing and later recovered.

### TikTok Preview Is Black Or Frozen

Check the broker service:

```bash
ansible media-vm -m shell -a "systemctl status stream-relay-vertical-broker.service --no-pager" --become
```

Then check the chain in order:

- Aitum is publishing to `rtmp://100.66.6.113:1936/live` with stream key `vertical`.
- Mac OBS `TikTok Vertical Broker` source is live.
- Mac OBS Virtual Camera is started.
- TikTok LIVE Studio camera is `OBS Virtual Camera`.

### TikTok Audio Meter Does Not Move

Expected path:

```text
Gaming PC Aitum vertical audio
  -> media-vm vertical broker
  -> Mac OBS TikTok Vertical Broker
  -> OBS audio monitoring device BlackHole 2ch
  -> TikTok LIVE Studio mic input BlackHole 2ch
```

Do not change the Mac's default input to BlackHole. Keep the Mac default input on `MacBook Pro Microphone`.

Check the chain in order:

- Gaming PC Aitum vertical output is running.
- Mac OBS `TikTok Vertical Broker` source meter moves with game audio.
- Mac OBS Settings -> Audio -> Advanced -> Monitoring Device is `BlackHole 2ch`.
- Mac OBS Advanced Audio Properties has `TikTok Vertical Broker` set to `Monitor and Output`.
- TikTok LIVE Studio mic/audio input is `BlackHole 2ch`.
- TikTok LIVE Studio desktop/system audio is muted.

If Mac OBS meters move but TikTok is silent, restart TikTok LIVE Studio first, then restart Mac OBS if needed. If it still fails, open QuickTime Player -> New Audio Recording, set the recording dropdown to `BlackHole 2ch`, and verify whether the meter moves while Mac OBS is receiving game audio.

If QuickTime also sees silence, test BlackHole itself:

1. Temporarily set System Settings -> Sound -> Output to `BlackHole 2ch`.
2. Play loud local Mac audio for a few seconds.
3. Confirm QuickTime's `BlackHole 2ch` meter moves.
4. Immediately set System Settings -> Sound -> Output back to `MacBook Pro Speakers`.

If this wake-up test makes BlackHole work again, leave Mac defaults on the MacBook devices and continue. BlackHole is the virtual pipe only; it should not stay as a normal default output or input.

### TikTok Audio Sounds Like A Phone Call

This is TikTok LIVE Studio processing the full stream mix as if it were a raw microphone.

Fix:

- In TikTok LIVE Studio, keep the mic/audio input as `BlackHole 2ch`.
- Turn off noise suppression, voice enhancement, audio effects, echo cancellation, and similar mic-cleanup options.
- Keep desktop/system audio muted.

BlackHole does not add this processing. If both mic and game audio sound narrow, gated, or cut in and out, check TikTok's mic processing first.

### SleepyChat YouTube Says Disconnected

SleepyChat works for Twitch, YouTube, and TikTok in the current setup.

Expected behavior:

- Twitch usually connects immediately.
- TikTok may retry only while the TikTok stream exists; it often connects once TikTok LIVE Studio is actually live.
- YouTube can be flaky because SleepyChat has to find the current YouTube live chat for the active event/video, and that binding can lag or get stale even when Twitch is fine.

If YouTube says disconnected:

1. Confirm YouTube is actually live or visible in Live Control Room, not just waiting in OBS or still preparing.
2. Refresh the SleepyChat window once.
3. If it immediately returns to disconnected and tells you to refresh again, open the SleepyChat dashboard and relink YouTube.
4. Reopen or refresh the SleepyChat chat window after relinking.

Relinking YouTube is the practical recovery when SleepyChat stops retrying. If YouTube later connects by itself without a refresh, that usually means YouTube finally exposed the active live chat and SleepyChat found it on a later retry.

### OBS Virtual Camera Error On Mac

If OBS says the virtual camera is not installed:

1. Open System Settings.
2. Go to General -> Login Items & Extensions -> Camera Extensions.
3. Enable the OBS camera extension.
4. Restart OBS normally.
5. Start Virtual Camera inside OBS.

### Mac Webcam Freezes

Do not hide the Mac OBS webcam source. Keep it visible but parked off-canvas and locked. The webcam is still feeding the gaming PC OBS through DistroAV NDI.

### Apple Music SonoBus Is Silent

This path is optional. The stream can go live without it.

Fast fix:

- If Music.app is playing but no Apple Music reaches Windows, restart Mac OBS.
- This reinitializes the macOS app-audio capture source and the `SonoBus Apple Music` VST filter.
- After restarting Mac OBS, restart OBS Virtual Camera if TikTok needs it.

Expected source names:

- Mac OBS source: `Apple Music`
- Mac OBS filter on that source: `SonoBus Apple Music`
- Windows shortcut: `SonoBus Apple Music Receiver`

Basic setup:

- On the gaming PC, open `SonoBus Apple Music Receiver`.
- In Windows SonoBus, click the audio device/settings area and set output to the SteelSeries Sonar Media device.
- Mute/disable Windows SonoBus input so the gaming PC is receive-only.
- In Mac OBS, open filters for `Apple Music`, select `SonoBus Apple Music`, then open the plugin interface.
- Put the Mac plugin and Windows app in the same private group, for example `jn-apple-music`.
- If the network/jitter indicator flashes red or audio stutters, adjust the receive jitter buffer on the Windows side:
  - In Windows SonoBus, find the Mac peer/channel strip.
  - Click the network/jitter/latency area in that peer strip; it is the area that flashes red during dropouts.
  - If it is already on `Auto`, switch the receive jitter buffer to `Manual`.
  - Drag the receive jitter buffer higher. Start around `100 ms`; if it still blips, try `150-200 ms`.
  - For streaming background music, latency does not matter much. Prefer a stable high buffer over a low-latency buffer that stutters.

The old NDI Apple Music path was removed from Mac OBS because it stuttered. Historical pinning used during NDI testing:

- Mac dock Ethernet: `192.168.1.60`
- Gaming PC Ethernet: `192.168.1.9`
- Windows NDI config: `C:\ProgramData\NDI\ndi-config.v1.json`
- Mac NDI configs:
  - `/Users/johnny/ndi-config.v1.json`
  - `/Users/johnny/.ndi/ndi-config.v1.json`

Persistent Windows host routes were added for `192.168.1.60/32` and `192.168.1.104/32` because Tailscale was winning the route to `192.168.1.0/24`.

Healthy Studio Monitor receiver path:

```text
192.168.1.9 -> 192.168.1.60:5963
```

If SonoBus is not connected, do not reopen the old NDI shortcut unless intentionally rolling back.

## Rollback

To fall back to direct Twitch/YouTube streaming from OBS:

1. Stop using the OBS custom SRT service.
2. Point OBS back to the platform directly.
3. Stop the media-vm relay services if desired:

```bash
ansible media-vm -m shell -a "systemctl stop stream-relay-output@twitch.service stream-relay-output@youtube.service stream-relay.service" --become
```

To move TikTok back to the gaming PC, stop using the Mac OBS virtual camera path and open TikTok LIVE Studio on the gaming PC again. That puts the TikTok load back on the gaming PC.
