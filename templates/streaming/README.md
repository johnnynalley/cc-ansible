# Streaming Templates

## Templates

- `stream-relay.sh.j2`: Landscape stream relay launcher.
- `stream-relay.service.j2`: Landscape stream relay service.
- `stream-relay-output.sh.j2`: RTMP output worker launcher.
- `stream-relay-output@.service.j2`: RTMP output worker service template.
- `stream-relay-broker.service.j2`: Landscape MediaMTX broker service.
- `stream-relay-health.*.j2`: Stream relay health check service, timer, and
  script.
- `stream-relay-vertical.*.j2`: Vertical relay service and launcher.
- `stream-relay-vertical-broker.service.j2`: Vertical MediaMTX broker service.
- `stream-vod-mover.*.j2`: VOD mover service, timer, and script.
- `mediamtx-*.yml.j2`: MediaMTX broker configuration.

## Consumers

- `playbooks/stream-relay.yml`
- `docs/streaming-runbook.md`

## Safety Notes

- These templates affect live stream routing. Keep stream keys live-only and
  never commit rendered env files or platform secrets.
