# Media Release Scripts

## Scripts

- `arr_anime_source_rank_policy.py`: Adds or updates the anime Bluray source
  ranking custom format in Sonarr/Radarr anime profiles, with backups.
- `arr_disable_recycle_bins.py`: Disables Sonarr/Radarr recycle bins after a
  timestamped live backup.
- `arr_dual_audio_title_policy.py`: Updates Arr dual-audio custom formats so
  explicit title markers can be trusted at grab/import time.
- `arr_release_policy_audit.py`: Read-only Sonarr/Radarr release profile and
  custom-format audit for `docker-vm`.
- `arr_stage_profilarr_test_profiles.py`: Snapshots live Arr policy state and
  clones anime profiles for Profilarr testing.
- `profilarr_candidate_audit.py`: Read-only audit of Profilarr PCD databases as
  release-policy candidates.
- `profilarr_disable_upgrade_jobs.py`: Disables Profilarr scheduled Arr upgrade
  jobs with a SQLite backup, without disabling PCD sync.
- `profilarr_link_database.py`: Links a Profilarr database through the local
  authenticated web app without printing secrets.
- `profilarr_nightly_upgrade.py`: Queues controlled Profilarr upgrade jobs for
  the overnight maintenance coordinator.
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
  episode files; cleanup requires explicit flags.
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

## Safety Notes

- Most scripts are intended to run on `docker-vm` and read local Arr/Profilarr
  config files for API access without printing secrets.
- Mutation scripts must take live backups unless explicitly documented
  otherwise; prefer dry-run flags first.
- Use `ansible docker-vm -m script -a "scripts/media-release/<script> ..."` for
  one-off execution so the source remains repo-managed.
