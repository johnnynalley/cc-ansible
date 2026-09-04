---
name: compute-corner-administration
description: Use for Compute Corner operations and approved changes.
version: 1.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [administration, containers, hosts, media, continuity]
    related_skills: [evidence-led-investigation, guided-operation, healthcheck, live-task-ledger, self-evolution]
---

# Compute Corner Administration

Use this skill as Astra's entry point for inspecting, operating, and improving
Compute Corner. Existing typed tools enforce authority. Do not replace them
with general privilege elevation, direct daemon sockets, root SSH, copied
credentials, or arbitrary remote shell commands.

## Establish Current State

Start with live discovery. Do not rely on remembered host or container names.

- `docker_inventory` with `host: all` discovers current containers, images,
  Compose ownership, health, and local update state on every enrolled Docker
  host. A container added outside Astra must appear here without a skill edit.
- `docker_update` with `action: status` reads the existing managed updater.
- `compose_hosts` lists hosts enrolled for bounded Astra-owned Compose stacks.
  `compose_request` with `action: status` reads one host or stack.
- `host_admin_hosts` lists enrolled Linux hosts. `host_admin_request` with
  `status`, `health`, or `service-status` performs read-only inspection.
- `arr_services` lists credential-isolated media services. Use
  `arr_api_request` with `GET` for supported API reads.

Report unreachable and partial coverage explicitly. A successful response from
one host is not estate-wide health.

## Select The Owning Surface

- Existing repository-owned Docker stacks remain under their current managed
  updater and deployment policy. Inspect them with `docker_inventory`; do not
  adopt or rewrite them through Compose administration.
- New stacks explicitly assigned to Astra use `compose_request`. Validate with
  `plan` before `apply`. Use versioned public images, bounded resources, named
  volumes, nonsecret environment values, and approved ports. Host binds,
  daemon sockets, privileged mode, host namespaces, inline secrets, and
  unversioned images are outside this surface.
- Linux updates, safe service lifecycle work, health probes, and guarded
  reboots use `host_admin_request`. Never use it to bypass protected service or
  quorum rules.
- Sonarr, Radarr, Prowlarr, Bazarr, and other enrolled media applications use
  `arr_api_request`. Read current application state before a write and preserve
  the media release policy, exact IDs, queue/history evidence, and review-first
  handling for ambiguous imports or deletions.
- Profile-local memories and agent-created skills use Hermes's native memory
  and `skill_manage` paths. Schedules use the native `cronjob` toolset. Do not
  edit backing JSON stores directly.

## Embedded Subtitle Release Verification

When the owner asks to replace video files that lack subtitles, require a
Sonarr-managed replacement whose actual media payload contains embedded English
subtitle streams. Do not use Bazarr or external `.srt` files as the repair, and
do not infer streams from a release title, indexer description, custom format,
or prior release-group reputation.

1. Read the current Sonarr series, episode-file, profile, history, queue, and
   release evidence. Confirm affected episodes with payload-level stream
   evidence.
2. Use `host_admin_request` on `docker-vm` with `media-release-search`. Select
   an exact opaque `candidateId`; rejection text such as current-score-higher
   does not prove the candidate lacks subtitles.
3. With approval, use `media-release-stage` for one representative episode.
   The transaction uses an isolated qBittorrent category and never enters
   Sonarr's queue.
4. Poll `media-release-status`, then use `media-release-verify`. Continue only
   when the sample has video, audio, and an actual tagged embedded English
   subtitle stream.
5. With approval, use `media-release-expand`. This is allowed only after the
   sample passes and only when the torrent contains the exact Sonarr episode set
   for that season.
6. After completion, run `media-release-verify` again. `eligibleForImport` must
   be true, with no missing or duplicate episodes and every selected file
   complete and stream-eligible.
7. Before import or existing-file replacement, verify current local and
   off-host rollback coverage and evaluate Sonarr's exact manual-import rows.
   The verifier deliberately cannot perform the import. Keep ambiguous mappings
   review-only and validate imported files through Sonarr and `ffprobe`.
8. Use `media-release-cleanup` for rejected or completed staging transactions.

Never pass download URLs, tracker credentials, filesystem paths, or raw torrent
data to the tool. If the typed operation cannot express the candidate, escalate
the boundary instead of using a general shell or downloading directly into the
library.

## Mutation Contract

Before a change, identify the exact target, current state, intended outcome,
owner, rollback, affected users, and validation. Use the tool's read or plan
operation first. Keep the request narrow enough that the approval prompt names
the actual host, action, stack, service, or API mutation.

Fresh approval is required when the existing tool requests it. Never split,
rephrase, or redirect a request to evade approval. Scheduled maintenance that
already has managed authorization continues through its deterministic timer;
an immediate manual run is a separate change.

After a mutation:

1. Read the resulting state through the same authoritative surface.
2. Run the relevant health or application check.
3. Confirm the intended object changed and unrelated objects did not.
4. Record any rollback artifact or transaction digest returned by the tool.
5. Report partial success, deferred hosts, or unverified delivery honestly.

## Native Agent State

Normal profile guidance, skills, schedules, and memories are mutable Hermes
state after their one-time ownership migration. Preserve valid agent-authored
changes. An infrastructure convergence result is not permission to overwrite
them.

Create or revise a profile-local skill only when a reusable boundary is missing
or weak. Validate native discovery and a fresh behavioral scenario, and keep a
normal non-trigger case. Do not duplicate an existing skill because its title
is unfamiliar.

`self-evolution` is the one fleet-shared skill. Astra is its sole writer.
Dubble and Rigel may send bounded proposals, but they cannot write the shared
tree. Accept a proposal only when evidence shows the change is safe, reusable,
and beneficial across agents; profile-specific improvements stay local. Back
up the prior canonical skill, apply one atomic revision, run parser and threat
validation, prove Astra can write it and Dubble/Rigel cannot, and retain the
decision and content digest. Roll back on any failed check.

## Backup And Recovery

Treat product-native profile archives as fast rollback and encrypted off-host
Restic snapshots as node-loss recovery. Inspect timer, service, artifact age,
and freshness-monitor state before claiming either layer is healthy. A local
archive on the same host is not disaster recovery.

Hermes has no unattended native restore command in this deployment. Restore is
an attended emergency path: preserve the failed state, validate the selected
archive in disposable storage, verify databases and ownership, then perform an
atomic cutover. Do not improvise restoration through ordinary file writes.

## Escalation Boundary

Escalate only when the required action is outside the exposed typed tools,
requires a new privilege or secret, changes the platform/security boundary,
needs off-host restore, or repeatedly fails after the documented rollback.
Include the exact unsupported operation and evidence already gathered so Codex
or the owner can address the missing boundary without repeating discovery.
