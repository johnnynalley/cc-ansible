# Media Release Scripts

## Scripts

- `arr_anime_source_rank_policy.py`: Adds or updates the legacy anime Bluray
  source ranking custom format in Sonarr/Radarr balanced anime profiles, with
  backups.
- `arr_disable_recycle_bins.py`: Disables Sonarr/Radarr recycle bins after a
  timestamped live backup.
- `arr_duplicate_media_audit.py`: Read-only duplicate media audit. On
  `docker-vm`, compares Sonarr/Radarr tracked files with the visible library;
  on the NAS host with `--mode branch`, checks mergerfs branch roots for hidden
  same-path and parsed episode duplicates. Optional `--apply-delete` writes a
  manifest and removes only conservative generated cleanup candidates, skipping
  title-side language ambiguities instead of guessing hidden audio tracks.
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
- `arr_profile_classification.py`: Audits or repairs Sonarr/Radarr media
  profile classification so anime uses anime efficient profiles,
  English-original regular media uses regular efficient profiles, and
  non-English non-anime media uses regular dual-audio efficient profiles.
- `arr_quality_profile_report.py`: Read-only Sonarr/Radarr report of native
  quality-profile groups, useful for checking whether profile quality order is
  still blocking custom-format upgrades.
- `arr_import_status_snapshot.py`: Read-only Sonarr/Radarr import-recovery
  snapshot that fully paginates queues, summarizes blocked import reasons,
  active commands, and recent grab/import/delete history.
- `arr_language_policy_audit.py`: Read-only Sonarr/Radarr current-library
  language policy audit. It compares Arr language metadata with optional
  ffprobe audio-track tags to find wrong original-language/English combinations,
  DA-title/DA-CF imports without English, non-English regular-profile drift,
  and original-only anime samples for follow-up candidate searches.
- `arr_regular_dual_audio_profiles.py`: Creates or updates non-English regular
  dual-audio efficient profiles and the parsed-language `Regular Dual Audio`
  custom format, with live backups before apply.
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
  release-tier custom formats against Profilarr/Dictionarry tier candidates,
  including optional token filtering for checking whether specific release
  groups are present upstream.
- `radarr_release_expectation_check.py`: Read-only check of live Radarr anime
  release-selection expectations.
- `radarr_regular_english_language_guard.py`: Creates or updates a Radarr
  title-side negative custom format for English-original regular movies so
  explicit foreign/multi-audio release markers such as `German.DL` are rejected
  only on `movies-regular-efficient`, with live backups before apply.
- `radarr_grab_forensics.py`: Classifies Radarr queue items against current
  movie files and Radarr's own import-rejection score messages. Optional
  cleanup is manual and can remove only safe current-better groups after
  writing a queue snapshot.
- `radarr_language_candidate_audit.py`: Read-only Radarr replacement-candidate
  audit. It performs interactive release searches by exact movie ID or title
  regex and reports whether Radarr sees parsed original-language + English
  candidates, without grabbing anything.
- `radarr_anime_lq_policy.py`: Dry-run by default helper that backs up Radarr
  release-policy state before apply and softens only the `movies-anime-efficient`
  anime LQ penalty scores so DA/x265 releases can still beat non-DA files while
  LQ remains a meaningful negative signal.
- `radarr_anime_metadata_da_policy.py`: Dry-run by default helper that backs up
  Radarr release-policy state before apply, scores metadata-detected anime DA
  on `movies-anime-efficient`, and creates a duplicate guard from the current
  `Anime Dual Audio` title specs so title+metadata matches net exactly one DA
  bonus instead of stacking.
- `radarr_anime_da_double_score_audit.py`: Read-only audit of every current
  Radarr movie and active queue row on `movies-anime-efficient`, checking that
  title DA plus metadata DA either includes the duplicate guard and nets exactly
  one DA bonus or is flagged for review.
- `seerr_arr_endpoint_update.py`: Audits or updates Seerr's Sonarr/Radarr
  endpoints, validates candidates through Seerr's own Arr test API, and writes
  a snapshot before live changes.
- `sonarr_blocklist_queue_matches.py`: Backs up Sonarr state, then optionally
  removes and blocklists queued downloads whose titles match a regex.
- `sonarr_episode_file_report.py`: Read-only report of current Sonarr
  episode-file scores for one series.
- `sonarr_grab_diagnostics.py`: Compares queued Sonarr grabs against current
  episode files; cleanup requires explicit flags and can be restricted to
  safe current-better groups so mixed packs are skipped.
- `sonarr_grab_forensics.py`: Classifies why Sonarr queue items were grabbed
  and why they may not import; supports focused `--filter`, recent grab
  `--history-size`, and read-only `--manual-import` rescoring checks for queue
  pollution investigations.
- `sonarr_jojo_stardust_s01_repair.py`: Narrow JoJo Stardust Crusaders S01
  mismatch repair and blocklist helper.
- `sonarr_manual_import_candidates.py`: Manual-import candidate report for one
  Sonarr series folder or download ID. With an exact `--import-path`, it can
  queue one approved `ManualImport` command and wait for completion.
- `sonarr_original_language_audit.py`: Read-only audit of recent
  original-language-only imports against live manual-search candidates, useful
  for checking whether original+English/DA releases were missed or outscored.
- `sonarr_queue_status_summary.py`: Summarizes Sonarr queue status messages
  without dumping every episode row.
- `sonarr_release_rejection_report.py`: Read-only manual-search report for a
  series, season, or episode that shows current file scores, candidate releases,
  custom formats, and Sonarr rejection reasons, with optional unique-title
  output for suspicious grab investigations.
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
- `subtitle_language_mismatch_audit.py`: Read-only media-file subtitle audit
  that samples target-language subtitle tracks and flags obvious tag/content
  mismatches such as an English-tagged subtitle stream containing mostly
  Chinese text. Used manually and by the Sonarr transaction monitor.

## Safety Notes

- Most scripts are intended to run on `docker-vm` and read local Arr/Profilarr
  config files for API access without printing secrets.
- Mutation scripts must take live backups unless explicitly documented
  otherwise; prefer dry-run flags first.
- Use `ansible docker-vm -m script -a "scripts/media-release/<script> ..."` for
  one-off execution so the source remains repo-managed.
