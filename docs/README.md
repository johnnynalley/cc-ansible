# Operator Docs Index

This directory contains human-facing runbooks, policies, and investigation
records. Update the matching row when a doc is added, moved, or changes
ownership.

| Doc | Owner area | Update when | Related assets |
| --- | --- | --- | --- |
| `docs/capture-card-streaming-plan.md` | Streaming hardware planning | Capture-card topology, OBS ingest plans, or hardware assumptions change. | `docs/streaming-runbook.md`, `playbooks/media/stream-relay.yml`, `templates/streaming/` |
| `docs/fortnite-performance-investigation.md` | Fortnite and Windows gaming performance | Benchmarks, drivers, BIOS/chipset changes, in-game setting conclusions, or next test actions change. | `playbooks/windows/`, `templates/windows/`, `scripts/gaming/` |
| `docs/gaming-benchmark.md` | Windows gaming capture workflow | Benchmark capture commands, PresentMon handling, OBS/RTSS capture flow, or gaming test interpretation changes. | `playbooks/windows/windows-gaming-benchmark.yml`, `playbooks/windows/windows-gaming-tuning.yml`, `scripts/gaming/` |
| `docs/immich-media-inbox.md` | Immich screenshot media discovery | Candidate admission, local/cloud semantic vision, Astra image boundary, API permissions, Seerr request gating, deployment, or rollback changes. | `playbooks/media/immich-media-inbox.yml`, `scripts/media-inbox/`, `templates/media-inbox/` |
| `docs/media-release-policy.md` | Sonarr/Radarr/Profilarr release policy | Quality profiles, custom formats, scores, anime/regular/non-English profile classification, non-English regular dual-audio assignments, upgrade search behavior, release-selection audits, import stamping, subtitle/import quality checks, or queue cleanup policy changes. | `playbooks/media/media-release-stamper.yml`, `playbooks/media/nightly-media-maintenance.yml`, `scripts/media-release/`, `templates/media-maintenance/` |
| `docs/media-stack-storage-layout.md` | Media stack storage topology | Sonarr/Radarr/SABnzbd/qBittorrent storage paths, completed-vs-incomplete download locations, hardlink expectations, docker-vm NFS mounts, TS440 mergerfs/download SSD backing, `/usenet-complete` cleanup, or mergerfs-balance pause/RCA behavior changes. | `templates/docker/docker-media-stack.yml.j2`, `inventory/host_vars/docker-vm/nfs.yml`, `inventory/group_vars/nas_server/nfs.yml`, `inventory/group_vars/nas_server/mounts.yml`, `inventory/group_vars/nas_server/mergerfs.yml`, `playbooks/media/nightly-media-maintenance.yml` |
| `docs/openclaw-docker-access.md` | OpenClaw Docker and privilege boundaries | Docker inventory fields, reporter rollout, service identities, threat model, or the approval-bound update design changes. | `playbooks/docker/openclaw-docker-report.yml`, `playbooks/docker/openclaw-docker-update-broker.yml`, `scripts/docker/openclaw-docker-report.py`, `scripts/docker/openclaw-docker-update-broker.py` |
| `docs/openclaw-heartbeats.md` | OpenClaw/Astra external heartbeat checks | Heartbeat commands, target hosts, sentinel files, or OpenClaw monitoring responsibilities change. | `playbooks/agents/openclaw.yml`, `playbooks/media/media-stack-health.yml`, `templates/openclaw/` |
| `docs/openclaw-runtime-security.md` | OpenClaw OS identities and trust boundaries | Gateway/receiver identities, raw-versus-aggregate data access, canary/cutover flow, state-migration rehearsal, prompt-injection containment, or credential reach changes. | `playbooks/agents/openclaw-health-receiver.yml`, `playbooks/agents/openclaw-isolated-gateway.yml`, `playbooks/agents/openclaw-state-rehearsal.yml`, `playbooks/agents/openclaw-doctor-rehearsal.yml`, `scripts/agents/`, `templates/openclaw/`, `docs/openclaw-docker-access.md` |
| `docs/plex-appliance-operations.md` | Plex appliance operator actions | Bedroom/living-room Plex appliance host mapping, Plex server storage backing, Plex server health, Tailscale/LAN Plex reachability, playback identity/session handling, queue safety, HDMI display ownership, skip-current-episode steps, shuffle-state rollback handling, or appliance operator commands change. | `playbooks/media/plex-appliance.yml`, `playbooks/media/plex-server-health.yml`, `templates/plex-appliance/`, `templates/media-maintenance/`, `inventory/host_vars/*/plex-appliance.yml`, `inventory/host_vars/*/nfs.yml`, `inventory/host_vars/media-vm/`, `inventory/host_vars/ts440/` |
| `docs/streaming-runbook.md` | Live streaming operations | Twitch/YouTube/TikTok/Mac OBS/Aitum/SleepyChat routing, stream relay services, VOD handling, or operator steps change. | `playbooks/media/stream-relay.yml`, `templates/streaming/`, `scripts/streaming/` |

## Operating Rules

- Treat this file as the first stop before adding a new operator doc.
- Keep doc path references in `README.md` and `AGENTS.md` current when a doc is
  added, moved, renamed, or becomes a source of truth for future sessions.
- Repo layout and reference consistency is checked by `scripts/repo/repo-audit`.
