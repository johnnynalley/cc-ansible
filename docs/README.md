# Operator Docs Index

This directory contains human-facing runbooks, policies, and investigation
records. Update the matching row when a doc is added, moved, or changes
ownership.

| Doc | Owner area | Update when | Related assets |
| --- | --- | --- | --- |
| `docs/capture-card-streaming-plan.md` | Streaming hardware planning | Capture-card topology, OBS ingest plans, or hardware assumptions change. | `docs/streaming-runbook.md`, `playbooks/media/stream-relay.yml`, `templates/streaming/` |
| `docs/fortnite-performance-investigation.md` | Fortnite and Windows gaming performance | Benchmarks, drivers, BIOS/chipset changes, in-game setting conclusions, or next test actions change. | `playbooks/windows/`, `templates/windows/`, `scripts/gaming/` |
| `docs/gaming-benchmark.md` | Windows gaming capture workflow | Benchmark capture commands, PresentMon handling, OBS/RTSS capture flow, or gaming test interpretation changes. | `playbooks/windows/windows-gaming-benchmark.yml`, `playbooks/windows/windows-gaming-tuning.yml`, `scripts/gaming/` |
| `docs/media-release-policy.md` | Sonarr/Radarr/Recyclarr/Profilarr release policy | Quality profiles, custom formats, scores, upgrade search behavior, release-selection audits, import stamping, or queue cleanup policy changes. | `playbooks/media/media-release-stamper.yml`, `playbooks/media/nightly-media-maintenance.yml`, `scripts/media-release/`, `templates/media-maintenance/` |
| `docs/openclaw-heartbeats.md` | OpenClaw/Astra external heartbeat checks | Heartbeat commands, target hosts, sentinel files, or OpenClaw monitoring responsibilities change. | `playbooks/agents/openclaw.yml`, `playbooks/media/media-stack-health.yml`, `templates/openclaw/` |
| `docs/plex-appliance-operations.md` | Plex appliance operator actions | Bedroom/living-room Plex appliance host mapping, HDMI display ownership, skip-current-episode steps, shuffle-state handling, or appliance operator commands change. | `playbooks/media/plex-appliance.yml`, `templates/plex-appliance/`, `inventory/host_vars/*/plex-appliance.yml` |
| `docs/streaming-runbook.md` | Live streaming operations | Twitch/YouTube/TikTok/Mac OBS/Aitum/SleepyChat routing, stream relay services, VOD handling, or operator steps change. | `playbooks/media/stream-relay.yml`, `templates/streaming/`, `scripts/streaming/` |

## Operating Rules

- Treat this file as the first stop before adding a new operator doc.
- Keep doc path references in `README.md` and `AGENTS.md` current when a doc is
  added, moved, renamed, or becomes a source of truth for future sessions.
- Repo layout and reference consistency is checked by `scripts/repo/repo-audit`.
