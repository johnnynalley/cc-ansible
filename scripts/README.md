# Script Inventory

This directory contains repo-managed helper scripts for diagnostics, live-policy
audits, controlled repairs, and deployment support.

## Operating Rules

- Do not add new reusable scripts directly to `scripts/` as flat files.
- Put new scripts in a domain directory such as `scripts/media-release/`,
  `scripts/storage/`, `scripts/streaming/`, `scripts/windows-gaming/`, or
  another clearly named directory.
- Every script directory must include a `README.md` that lists each script,
  what it does, where it should run, whether it is read-only by default, and
  any apply/mutation flags.
- If a temporary remote copy is needed to execute a script, keep the source in
  this repo and clean up the remote copy after the run.
- Existing flat scripts are legacy inventory. Move them only in a deliberate
  migration that updates all playbook, documentation, and operator references.

## Current Layout

### `scripts/` Legacy Flat Inventory

These files predate the directory-catalog rule. Prefer improving these in place
until a dedicated migration moves them into domain directories.

#### Media Release Policy, Sonarr, Radarr, and Profilarr

- `arr_anime_source_rank_policy.py`: Adds or updates the anime Bluray source
  ranking custom format in Sonarr/Radarr anime profiles, with backups.
- `arr_disable_recycle_bins.py`: Disables Sonarr/Radarr recycle bins after
  taking a timestamped live backup.
- `arr_dual_audio_title_policy.py`: Updates Arr dual-audio custom formats so
  explicit title markers can be trusted at grab/import time.
- `arr_release_policy_audit.py`: Read-only Sonarr/Radarr release profile and
  custom-format audit for `docker-vm`.
- `arr_stage_profilarr_test_profiles.py`: Snapshots Arr policy state and clones
  anime profiles for Profilarr testing without changing media assignments.
- `profilarr_candidate_audit.py`: Read-only audit of Profilarr PCD databases as
  release-policy candidates.
- `profilarr_disable_upgrade_jobs.py`: Disables Profilarr scheduled Arr upgrade
  jobs with a SQLite backup, without disabling PCD sync.
- `profilarr_link_database.py`: Links a Profilarr database through the local
  authenticated web app without printing secrets.
- `profilarr_nightly_upgrade.py`: Queues controlled Profilarr upgrade jobs for
  the overnight media-maintenance coordinator.
- `profilarr_selective_cf_import.py`: Imports curated Profilarr custom formats
  into Arr test profiles without importing upstream quality profiles.
- `profilarr_sonarr_upgrade_strategy.py`: Adjusts Profilarr's Sonarr upgrade
  filter through stored settings with a SQLite backup.
- `profilarr_state_audit.py`: Read-only audit of Profilarr database, scheduler,
  and upgrade-job state.
- `radarr_release_expectation_check.py`: Read-only check of live Radarr anime
  release-selection expectations.
- `sonarr_blocklist_queue_matches.py`: Backs up Sonarr state, then optionally
  removes and blocklists queued downloads whose titles match a regex.
- `sonarr_episode_file_report.py`: Read-only report of current Sonarr
  episode-file scores for one series.
- `sonarr_grab_diagnostics.py`: Compares queued Sonarr grabs against current
  episode files; read-only by default, cleanup requires explicit flags.
- `sonarr_grab_forensics.py`: Classifies why Sonarr queue items were grabbed
  and why they may not import.
- `sonarr_jojo_stardust_s01_repair.py`: Narrow JoJo Stardust Crusaders S01
  mismatch repair and blocklist helper.
- `sonarr_manual_import_candidates.py`: Read-only manual-import candidate report
  for one Sonarr series folder.
- `sonarr_queue_status_summary.py`: Summarizes Sonarr queue status messages
  without dumping every episode row.
- `sonarr_release_expectation_check.py`: Read-only check of live Sonarr anime
  release-selection expectations.
- `sonarr_restore_local_better_files.py`: Dry-run by default helper for
  replacing tracked Sonarr files with better existing local files.
- `sonarr_series_audit.py`: Read-only summary of one Sonarr series' monitoring,
  files, queue, and grab history.
- `sonarr_transaction_audit.py`: Read-only summary of Sonarr transaction-monitor
  history and current queue state.

#### Storage and Docker Operations

- `docker-stack-diff`: Compares running container image IDs against pulled image
  IDs before a compose stack is updated.
- `mergerfs-balance`: Balances files across mergerfs branches with ZFS-aware
  capacity reporting.
- `nightly-media-maintenance`: Coordinates overnight media maintenance; balance
  jobs take priority, otherwise it queues controlled Profilarr upgrade work.
- `storage-status`: Shows local storage usage with ZFS and mergerfs support.

#### Streaming, OBS, and Audio Routing

- `configure-aitum-tiktok-broker.ps1`: Configures Aitum vertical-canvas broker
  settings for TikTok streaming.
- `configure-gaming-obs-apple-music-ndi.ps1`: Configures Windows OBS Apple
  Music NDI source and monitoring settings.
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

#### Windows Gaming and Capture Analysis

- `analyze-gaming-capture.py`: Parses gaming capture CSV data and summarizes
  frame-time/performance metrics.

## Directory README Template

Each new `scripts/<domain>/README.md` should use this shape:

```markdown
# <Domain> Scripts

## Scripts

- `<script-name>`: Purpose, target host, read-only or mutating behavior, and the
  usual command line.

## Safety Notes

- Backup requirements, destructive flags, secrets handling, and cleanup notes.
```
