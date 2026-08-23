# Media Release Scripts

## Scripts

- `arr_grab_context.py`: Internal HTTP ledger for exact Sonarr/Radarr `OnGrab`
  context. It stores canonical media identity, alternate titles, original
  language, expected episodes, release title, release group, quality, and
  grab-time custom formats by exact download ID so download-client stampers do
  not depend on fuzzy queue-title matching at completion time. It also marks
  release-title/media-title conflicts instead of allowing canonical prefixing
  to hide a wrong-series payload.
- `arr_grab_context_configure.py`: Dry-run by default, idempotent Sonarr/Radarr
  webhook configurator for the exact-ID ledger. `--apply` backs up each Arr
  notification set before creating or updating the OnGrab-only webhook.
- `arr_anime_source_rank_policy.py`: Adds or updates the legacy anime Bluray
  source ranking custom format in Sonarr/Radarr balanced anime profiles, with
  backups.
- `arr_disable_recycle_bins.py`: Disables Sonarr/Radarr recycle bins after a
  timestamped live backup.
- `arr_download_client_toggle.py`: Dry-run by default Sonarr/Radarr download
  client toggle for incident response, such as temporarily disabling SABnzbd
  when failed add attempts would repeatedly fetch NZBs. `--apply` requires a
  pre-existing live rollback backup path.
- `arr_cutoff_ceiling_policy.py`: Dry-run by default Sonarr/Radarr cutoff
  helper that backs up live policy state before apply and sets matching
  efficient profiles' `cutoffFormatScore` to the exact sum of every positive
  scored custom format in that profile, including small service/repack
  tiebreakers.
- `arr_duplicate_media_audit.py`: Read-only duplicate media audit. On
  `docker-vm`, compares Sonarr/Radarr tracked files with the visible library;
  on the NAS host with `--mode branch`, checks mergerfs branch roots for hidden
  same-path and parsed episode duplicates. Optional `--apply-delete` writes a
  manifest and removes only conservative generated cleanup candidates, skipping
  title-side language ambiguities instead of guessing hidden audio tracks.
- `arr_dual_audio_title_policy.py`: Updates Arr dual-audio custom formats so
  explicit title markers can be trusted at grab/import time. It also keeps
  `Dubs Only (Block)` from treating hyphenated episode-title words such as
  `Scrubba-dub-dub` as dub-release markers.
- `arr_release_policy_audit.py`: Read-only Sonarr/Radarr release profile and
  custom-format audit for `docker-vm`.
- `arr_profile_math_audit.py`: Read-only Sonarr/Radarr efficient-profile
  score-band audit that checks DA, x265, quality rank, Bluray source rank,
  Dictionarry tier stacks, bounded TRaSH fallback tiers, Bluray/WEB source
  ordering, regular enabled-quality grouping, service/repack tiebreakers,
  legacy tier drift, and the CF limit.
- `arr_import_reconciler.py`: Exact-ledger import fallback for completed
  Sonarr/Radarr downloads blocked only because the release was matched by ID.
  It imports only rejection-free, missing candidates whose episode/movie IDs
  were recorded in the native OnGrab event; active downloads, unexpected pack
  files, current-better candidates, and downloads without exact context are
  never selected. The deployed service can run in dry-run mode before apply.
- `arr_indexer_preference_policy.py`: Dry-run by default policy helper for the
  approved source ordering. It sets Usenet indexers to priority `1`, Seedpool
  to `10`, Nyaa/AnimeTosho specialists to `15`, generic public torrents to
  `25`, and Sonarr/Radarr preferred protocol to Usenet. `--apply` requires an
  existing marked Sanoid-backed rollback path and verifies every downstream
  Prowlarr indexer copy in both Arr applications. It deliberately does not
  alter seeding limits.
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
- `arr_queue_remove.py`: Dry-run by default Sonarr/Radarr queue-row removal
  helper with status/tracked-status/title/message filters. `--summary-only`
  keeps large-queue evidence bounded while retaining aggregate operation
  results. Client-removing cleanup operates once per exact download ID so pack
  rows cannot churn queue IDs during removal. `--apply` requires an existing
  live rollback backup path and supports non-blocklisting cleanup.
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
- `qbit_queue_status.py`: Read-only qBittorrent torrent-state summary for
  Arr queue incidents. Reads `/etc/qbit-port-sync.env` on `docker-vm`, logs in
  without printing secrets, and summarizes torrent states, categories, paths,
  and optional tracker messages. Cleanup is opt-in only: `--apply-delete`
  requires `--delete-states` plus a manifest path, deletes through the
  qBittorrent API with files, and skips finished/seeding torrents by default.
  `--preserve-files` changes an explicit applied removal to retain payload
  files, which is intended for a backed-up recheck canary rather than routine
  queue cleanup.
- `sab_queue_status.py`: Read-only SABnzbd queue and incomplete-folder summary
  for Arr import incidents. Reads SAB's local config on `docker-vm`, queries the
  API without printing secrets, compares active queue items with `/incomplete`
  directories, and can remove only old unreferenced incomplete folders when
  `--apply-delete` and a manifest path are supplied.
- `radarr_release_expectation_check.py`: Read-only check of live Radarr anime
  release-selection expectations.
- `arr_regular_english_language_guard.py`: Creates or updates a shared
  title-side negative custom format for English-original regular shows and
  movies so explicit foreign/multi-audio markers such as `German.DL`, `DUAL`,
  or bracketed foreign+English audio labels are rejected only on
  `shows-regular-efficient` and `movies-regular-efficient`. Dry-run is the
  default and every run snapshots both Arr instances before apply.
- `radarr_regular_english_language_guard.py`: Compatibility wrapper that runs
  `arr_regular_english_language_guard.py --instance radarr`.
- `radarr_grab_forensics.py`: Classifies Radarr queue items against current
  movie files and Radarr's own import-rejection score messages. Optional
  cleanup is manual and can remove only terminal problem groups where every
  row is current-better after writing a queue snapshot.
- `radarr_language_candidate_audit.py`: Read-only Radarr replacement-candidate
  audit. It performs interactive release searches by exact movie ID or title
  regex and reports whether Radarr sees parsed original-language + English
  candidates, without grabbing anything.
- `radarr_manual_import_candidate.py`: Inspects Radarr manual-import candidates
  for one movie/download ID and can import exactly one rejection-free file by
  exact path, with optional command completion polling. An explicit
  `--allow-unparseable-queue-match` override supports single-file names Radarr
  cannot parse only when movie, download ID, and output path match one live
  queue row exactly.
- `radarr_anime_lq_policy.py`: Legacy Radarr-only anime LQ softener retained for
  rollback context. Prefer `arr_trash_lq_policy.py` for current efficient-profile
  TRaSH LQ policy.
- `arr_trash_lq_policy.py`: Dry-run by default helper that backs up Sonarr and
  Radarr policy state before apply, neutralizes TRaSH LQ scoring in active
  `*-efficient` profiles, and reports remaining TRaSH-sourced negative scores
  for explicit review.
- `radarr_anime_metadata_da_policy.py`: Dry-run by default helper that backs up
  Radarr release-policy state before apply, scores metadata-detected anime DA
  on `movies-anime-efficient`, and creates a duplicate guard from the current
  `Anime Dual Audio` title specs so title+metadata matches net exactly one DA
  bonus instead of stacking.
- `sonarr_anime_metadata_da_policy.py`: Dry-run by default helper that backs up
  Sonarr release-policy state before apply, creates a metadata DA helper from
  `Regular Dual Audio`, scores metadata-detected anime DA on
  `shows-anime-efficient`, and creates a duplicate guard from the current
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
  terminal problem groups where every row is current-better, so mixed packs
  and active transfers are skipped. `--json --summary-only` emits one compact
  record per download ID for large-queue triage. Explicit `SxxEyy` and
  `Nth Season - Epyy` title targets that disagree with Sonarr's queue target
  are flagged for review; the flag does not mutate or reject releases.
- `sonarr_grab_forensics.py`: Classifies why Sonarr queue items were grabbed
  and why they may not import; supports focused `--filter`, recent grab
  `--history-size`, and read-only `--manual-import` rescoring checks for queue
  pollution investigations.
- `sonarr_jojo_stardust_s01_repair.py`: Narrow JoJo Stardust Crusaders S01
  mismatch repair and blocklist helper.
- `sonarr_manual_import_candidates.py`: Manual-import candidate report for one
  Sonarr series folder or download ID. With an exact `--import-path`, it can
  queue one approved `ManualImport` command and wait for completion. With
  `--import-missing`, it queues only candidates whose matched monitored
  episodes currently have no file, which is useful for partially imported
  season packs; add `--dry-run` to preview that selection. For a single queued
  file that Sonarr already mapped to an episode but the manual-import endpoint
  reports as `Unable to parse file`, pair `--download-id` with one or more
  explicit `--episode-id` values to queue a narrow ManualImport using the queue
  row's quality and languages.
  Exact series and alternate-title matches take precedence over substring
  matches so short queries cannot silently select a similarly named series.
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
- Run `python3 scripts/media-release/test_arr_grab_context.py` after changing
  the grab-context schema or identity matching.
- Run `python3 scripts/media-release/test_release_stampers.py` after changing
  exact-ID lookup or canonical-title prefix behavior in either download-client
  stamper.
- Run `python3 scripts/media-release/test_arr_grab_context_configure.py` after
  changing notification payload construction.
- Run `python3 scripts/media-release/test_arr_import_reconciler.py` after
  changing queue eligibility, exact-target selection, or native manual-import
  command construction.
- Run `python3 scripts/media-release/test_arr_indexer_preference_policy.py`
  after changing source-priority bands, name normalization, or downstream
  convergence behavior.
