# Script Inventory

This directory contains repo-managed helper scripts for diagnostics, live-policy
audits, controlled repairs, and deployment support.

## Operating Rules

- Do not add new reusable scripts directly under `scripts/` as flat files.
- Put runnable scripts in a domain directory and document them in that
  directory's `README.md`.
- If a temporary remote copy is needed to execute a script, keep the source in
  this repo and clean up the remote copy after the run.
- When moving, renaming, deleting, or replacing a script, update playbooks,
  docs, operator commands, and any deployed-source references in the same
  change.

## Directories

- `agents/`: Isolated agent-adjacent services and aggregate-only data publishers.
- `docker/`: Docker stack update helpers and redacted inventory reporting.
- `gaming/`: Capture and frame-time analysis helpers.
- `media-inbox/`: Immich candidate discovery, local/cloud semantic vision, credential reconciliation, and tests.
- `media-maintenance/`: Overnight maintenance coordinators.
- `media-release/`: Sonarr, Radarr, Profilarr, and release-policy tools.
- `repo/`: Repository layout and cross-reference audit helpers.
- `storage/`: Storage reporting and mergerfs balancing tools.
- `streaming/`: OBS, TikTok, Mac audio, and stream-routing helpers.

Start with the relevant directory README before adding or changing a script.
