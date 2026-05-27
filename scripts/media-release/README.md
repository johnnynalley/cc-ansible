# Media Release Scripts

## Scripts

- `arr_anime_source_rank_policy.py`: Adds or updates the legacy anime Bluray
  source ranking custom format in Sonarr/Radarr balanced anime profiles, with
  backups.
- `arr_disable_recycle_bins.py`: Disables Sonarr/Radarr recycle bins after a
  timestamped live backup.
- `arr_dual_audio_title_policy.py`: Updates Arr dual-audio custom formats so
  explicit title markers can be trusted at grab/import time.
- `arr_release_policy_audit.py`: Read-only Sonarr/Radarr release profile and
  custom-format audit for `docker-vm`.
- `arr_profile_math_audit.py`: Read-only Sonarr/Radarr efficient-profile
  score-band audit that checks DA, x265, quality rank, Bluray source rank,
  Dictionarry tier stacks, bounded TRaSH fallback tiers, Bluray/WEB source
  ordering, regular enabled-quality grouping, service/repack tiebreakers,
  legacy tier drift, and the CF limit.
- `arr_profile_assignment_check.py`: Read-only Sonarr/Radarr and Seerr check
  that fails if any media assignment or request default uses balanced, test,
  old, or unknown profiles instead of efficient profiles.
- `arr_quality_profile_report.py`: Read-only Sonarr/Radarr report of native
  quality-profile groups, useful for checking whether profile quality order is
  still blocking custom-format upgrades.
- `arr_promote_efficient_profiles.py`: Promotes accepted Profilarr test
  profiles into preserved production profile IDs, creates frozen balanced
  clones, reassigns media to efficient profiles, updates Seerr defaults, and
  removes temporary test profiles.
- `arr_stage_profilarr_test_profiles.py`: Snapshots live Arr policy state and
  clones efficient anime profiles for future Profilarr testing.
- `profilarr_candidate_audit.py`: Read-only audit of Profilarr PCD databases as
  release-policy candidates.
- `profilarr_cf_definition_sync.py`: Syncs selected existing Arr custom-format
  definitions from Profilarr PCD sources while preserving local profile
  structure and scores.
- `profilarr_bounded_tier_import.py`: Imports curated Dictionarry primary tiers
  plus Profilarr-synced TRaSH fallback tiers into refreshed Arr test profiles
  with backups, x265 held at `+5000`, ordered service/repack compression, anime
  source-rank zeroing, regular enabled-quality grouping, legacy tier drift
  checks, and cleanup of all-zero non-rename CFs.
- `profilarr_disable_upgrade_jobs.py`: Disables Profilarr scheduled Arr upgrade
  jobs with a SQLite backup, without disabling PCD sync.
- `profilarr_link_database.py`: Links a Profilarr database through the local
  authenticated web app or a direct SQLite/clone fallback, taking a Profilarr
  DB backup first and without printing secrets.
- `profilarr_nightly_upgrade.py`: Opens and closes Profilarr's native Arr
  upgrade scheduler for the overnight maintenance coordinator.
- `profilarr_selective_cf_import.py`: Imports curated Profilarr custom formats
  into Arr test profiles without importing upstream quality profiles.
- `profilarr_sonarr_upgrade_strategy.py`: Adjusts Profilarr's Sonarr upgrade
  filter through stored settings with a SQLite backup.
- `profilarr_state_audit.py`: Read-only audit of Profilarr database, scheduler,
  and upgrade-job state.
- `profilarr_tier_candidate_compare.py`: Read-only comparison of live Arr
  release-tier custom formats against Profilarr/Dictionarry tier candidates.
- `radarr_release_expectation_check.py`: Read-only check of live Radarr anime
  release-selection expectations.
- `seerr_arr_endpoint_update.py`: Audits or updates Seerr's Sonarr/Radarr
  endpoints, validates candidates through Seerr's own Arr test API, and writes
  a snapshot before live changes.
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
- `sonarr_release_rejection_report.py`: Read-only manual-search report for a
  series, season, or episode that shows current file scores, candidate releases,
  custom formats, and Sonarr rejection reasons.
- `sonarr_release_expectation_check.py`: Read-only check of live Sonarr anime
  release-selection expectations.
- `sonarr_restore_local_better_files.py`: Dry-run by default helper for
  replacing tracked Sonarr files with better existing local files.
- `sonarr_series_audit.py`: Read-only summary of one Sonarr series' monitoring,
  files, queue, and grab history.
- `sonarr_transaction_audit.py`: Read-only summary of Sonarr transaction-monitor
  history, storage snapshots, release-stamper events, and current queue state.
- `sonarr_transaction_log_sanitize.py`: Redacts secret-looking fields and URL
  query parameters from Sonarr transaction-monitor JSONL logs.

## Safety Notes

- Most scripts are intended to run on `docker-vm` and read local Arr/Profilarr
  config files for API access without printing secrets.
- Mutation scripts must take live backups unless explicitly documented
  otherwise; prefer dry-run flags first.
- Use `ansible docker-vm -m script -a "scripts/media-release/<script> ..."` for
  one-off execution so the source remains repo-managed.
