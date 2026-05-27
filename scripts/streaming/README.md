# Streaming Scripts

## Scripts

- `configure-aitum-tiktok-broker.ps1`: Configures Aitum vertical-canvas broker
  settings for TikTok streaming.
- `configure-gaming-obs-apple-music-ndi.ps1`: Configures Windows OBS Apple
  Music NDI source and monitoring settings.
- `configure-gaming-obs-vod-audio-tracks.ps1`: Configures gaming PC OBS
  landscape output for Track 1 full/music and Track 2 clean/no-music routing.
- `check-gaming-obs-stream-routing.ps1`: Read-only preflight for gaming PC OBS
  output, audio-track, and Aitum vertical audio routing.
- `configure-mac-apple-music-ndi.py`: Configures Mac OBS Apple Music
  application-audio NDI output.
- `configure-mac-apple-music-sonobus.py`: Configures Mac OBS Apple Music app
  capture through SonoBus.
- `configure-mac-tiktok-vbcable.py`: Configures Mac OBS TikTok scene for
  video-only broker audio handling.
- `macos-tiktok-audio-bridge.plist`: LaunchAgent definition for the macOS
  TikTok audio bridge.
- `macos-tiktok-audio-bridge.sh`: macOS ffmpeg audio bridge for TikTok stream
  routing.

## Safety Notes

- These scripts edit OBS/audio-routing user config on their target machines.
- Do not launch visible Windows GUI apps through SSH/Ansible; use the
  established interactive task/watcher path or ask the user to open them.
