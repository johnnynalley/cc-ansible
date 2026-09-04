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
  custom-format audit for `docker-vm`, including exact duplicate matching
  definitions that may be consolidation candidates after profile-score and
  rename review.
- `arr_profile_math_audit.py`: Read-only Sonarr/Radarr efficient-profile
  score-band audit that checks DA, x265, quality rank, Bluray source rank,
  Dictionarry tier stacks, bounded TRaSH fallback tiers, Bluray/WEB source
  ordering, regular enabled-quality grouping, service/repack tiebreakers,
  legacy tier drift, and the CF limit.
- `astra_arr_readonly_report.py`: Root-only fixed-code adapter for Astra's
  `arr-queue`, `arr-policy`, `arr-transactions`, and `arr-storage` host-admin
  health probes. It invokes only managed read-only audits, allowlists and
  bounds returned fields, and exposes no generic command, Arr write, search,
  import, queue-removal, or blocklist operation.
- `arr_import_reconciler.py`: Exact-ledger import fallback for completed
  Sonarr/Radarr downloads blocked only because the release was matched by ID.
  It imports only rejection-free monitored candidates whose episode/movie IDs
  were recorded in the native OnGrab event. Existing-file candidates are
  eligible only when Arr's own manual-import evaluation says they are valid
  upgrades; active downloads, unexpected pack files, current-better
  candidates, and downloads without exact context are never selected. Its
  structured output compares grab-time and import-time scores/formats and
  classifies identity conflicts, CF drift, current-better rows, and other
  native rejections. Its separately gated terminal-torrent mode probes every
  completed qBittorrent media file, requires complete pack/native-target
  mapping, exact ledger context, and a finite seed quota, then either removes a
  quota-complete torrent through Arr or hands it to qBittorrent's per-torrent
  `RemoveWithContent` action before hiding it from Arr. Ordinary current-better
  and pack-collateral outcomes are not blocklisted; exact stable payload or
  identity contradictions may be blocklisted and receive one cooldown-bounded
  replacement search. `disabled`, `audit`, and `apply` modes support staged
  rollout, and any failed probe/write/readback leaves the queue item untouched.
  Same-media episode/season target mismatches remain review-only, and a
  persistent rotating cursor prevents unresolved rows from starving later
  terminal downloads during bounded cycles. Its opt-in untagged-audio exception
  is restricted to one `und` stream on English-original regular profiles with
  no dual, multi-audio, dubbed, or foreign-language title marker; it remains
  disabled by default and records every accepted assumption in audit output.
- `arr-import-reconciler.Dockerfile`: Minimal local reconciler image extension
  that adds `ffprobe` to the unversioned Python Alpine base. The reconciler
  receives a read-only media mount and no Docker socket.
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
- `arr_native_backup.py`: Trigger and poll one native Sonarr, Radarr, or
  Prowlarr backup, then verify and report the newly created archive without
  printing API keys.
- `arr_zero_score_cf_cleanup.py`: Remove explicitly named custom formats only
  after proving they have zero score on every profile and are not rename
  formats. Apply uses Arr's native custom-format deletion lifecycle and verifies
  that both the definition and all profile references disappear; dry-run is the
  default and creates no files. Apply requires the managed off-host NFS rollback
  mount and writes private CF/profile snapshots before the first deletion.
- `arr_queue_remove.py`: Dry-run by default Sonarr/Radarr queue-row removal
  helper with status/tracked-status/title/message filters plus repeatable exact
  `--download-id` selection. `--summary-only`
  keeps large-queue evidence bounded while retaining aggregate operation
  results. Client-removing cleanup operates once per exact download ID so pack
  rows cannot churn queue IDs during removal. `--apply` requires an existing
  root-only rollback path, writes a `0600` manifest containing the exact
  selected records and filters there before deletion, and supports
  non-blocklisting cleanup.
- `arr_import_status_snapshot.py`: Read-only Sonarr/Radarr import-recovery
  snapshot that fully paginates queues, summarizes blocked import reasons,
  active commands, and recent grab/import/delete history.
- `arr_language_policy_audit.py`: Read-only Sonarr/Radarr current-library
  language and embedded-subtitle policy audit. It inventories Arr's
  import-time subtitle metadata, compares Arr language metadata with optional
  ffprobe audio/subtitle streams, groups releases with no embedded English
  subtitles by title/profile/group/quality/codec, and finds wrong
  original-language/English combinations, DA-title/DA-CF imports without
  English, non-English regular-profile drift, and original-only anime samples
  for follow-up candidate searches.
- `arr_regular_dual_audio_profiles.py`: Creates or updates non-English regular
  dual-audio efficient profiles and the parsed-language `Regular Dual Audio`
  custom format, with live backups before apply.
- `arr_regular_english_language_guard.py`: Maintains the negative title-side
  audio guard used only by English-original regular profiles. It recognizes
  explicit foreign/dual/multi-audio markers and standalone `MULTI` release
  tokens while excluding `MultiSub`/`MULTI.SUBS` subtitle markers.
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
  upgrade scheduler for the overnight maintenance coordinator. It queues one
  immediate Sonarr run when the window opens, keeps the next native Sonarr cron
  outside that window to prevent overlapping full-series searches, and leaves
  Radarr's bounded movie batches hourly.
- `profilarr_selective_cf_import.py`: Imports curated Profilarr custom formats
  into Arr test profiles without importing upstream quality profiles.
- `profilarr_sonarr_upgrade_strategy.py`: Adjusts Profilarr's Sonarr upgrade
  filter through stored settings with a SQLite backup. Its optional episode
  ceiling keeps Profilarr's native whole-series search limited to bounded
  series without patching Profilarr.
- `profilarr_state_audit.py`: Read-only audit of Profilarr database, scheduler,
  and upgrade-job state.
- `profilarr_tier_candidate_compare.py`: Read-only comparison of live Arr
  release-tier custom formats against Profilarr/Dictionarry tier candidates,
  including optional token filtering for checking whether specific release
  groups are present upstream.
- `prowlarr_indexer_policy_audit.py`: Read-only Prowlarr indexer-policy report
  plus synchronized Sonarr/Radarr indexer settings, limited to enabled/search
  state, protocol, priority, application profile, tags, seeding criteria, and
  query/grab/minimum-seeder limits. It excludes tracker URLs, API keys,
  credentials, and arbitrary indexer fields.
- `prowlarr_indexer_app_profile.py`: Dry-run by default helper that moves one
  exact Prowlarr indexer to an existing application profile. Apply requires a
  root-only rollback path, stores the complete pre-change indexer record there,
  runs Prowlarr's native downstream sync, verifies Sonarr and Radarr flags, and
  restores the original record if convergence fails.
- `qbit_queue_status.py`: Read-only qBittorrent torrent-state summary for
  Arr queue incidents. Reads `/etc/qbit-port-sync.env` on `docker-vm`, logs in
  without printing secrets, and summarizes torrent states, categories, paths,
  add/last-activity/completion timestamps, and optional tracker messages.
  `--correlate-arr` joins exact torrent hashes to Sonarr/Radarr queue rows and
  classifies long-idle zero-peer stalls, partial stalls, missing payloads,
  orphaned client records, and explicit release-title/queue-season conflicts.
  `--include-arr-history` adds event counts, timestamp-deduplicated grab-batch
  counts, and originating indexer names from exact-download-ID Arr history.
  The correlator is read-only and does not blocklist, remove, or search.
  Tracker URLs are reduced to scheme/host/port so announce credentials cannot
  enter console output or deletion manifests.
  Cleanup is opt-in only: `--apply-delete`
  requires `--delete-states`, a manifest directly inside a root-only rollback
  path, and a complete `.torrent` plus `.fastresume` metadata backup for every
  selected hash before it deletes through the qBittorrent API. Optional
  repeatable `--arr-classification` filters allow an exact correlated class such
  as `orphaned_in_download_client`. Applied cleanup can also require repeatable
  exact `--expected-hash` values; any missing hash or classification drift
  aborts the entire operation. Finished/seeding torrents remain skipped by
  default. `--backup-metadata-only` requires exact expected hashes and stores
  both restorable qBittorrent metadata files plus a `0600` manifest without
  deleting or changing the torrent.
  `--preserve-files` changes an explicit applied removal to retain payload
  files, which is intended for a backed-up recheck canary rather than routine
  queue cleanup.
- `sonarr_embedded_subtitle_verifier.py`: Root-side typed helper used by Astra's
  existing host-administration boundary on `docker-vm`. It searches Sonarr by
  exact series/season, returns opaque candidate IDs without download URLs,
  stages one torrent outside Sonarr's category, downloads a single sample
  episode, verifies actual `ffprobe` streams, and can expand only an eligible
  sample to the exact season episode set. It never imports or replaces library
  files. Transaction IDs, qBittorrent categories, paths, and cleanup remain
  bounded; tracker and application credentials never leave the host.
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
  `--history-size`, exact repeatable `--classification` filters, and read-only
  `--manual-import` rescoring checks for queue pollution investigations.
- `sonarr_large_series_upgrade.py`: Dry-run-by-default companion for series
  excluded from Profilarr's whole-series episode ceiling. During the open
  overnight window it rotates through monitored seasons, queues at most one
  native `SeasonSearch`, and skips if Profilarr, RSS, another Sonarr search, or
  the available-memory guard is active. It never imports, deletes, or
  blocklists releases.
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
  history, storage snapshots, release-stamper events, exact-ID reconciler
  decisions, recurring bounded qBittorrent-to-Arr stall snapshots, and current
  queue state.
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
- Run `python3 scripts/media-release/test_sonarr_embedded_subtitle_verifier.py`
  after changing staged-release selection, path mapping, stream eligibility,
  or transaction state.
- Run `python3 scripts/media-release/test_release_stampers.py` after changing
  exact-ID lookup or canonical-title prefix behavior in either download-client
  stamper.
- Run `python3 scripts/media-release/test_arr_grab_context_configure.py` after
  changing notification payload construction.
- Run `python3 scripts/media-release/test_arr_import_reconciler.py` after
  changing queue eligibility, exact-target selection, or native manual-import
  command construction.
- Run `python3 scripts/media-release/test_sonarr_transaction_audit.py` after
  changing persistent reconciler-event parsing or summary classifications.
- Run `python3 scripts/media-release/test_profilarr_nightly_upgrade.py`,
  `python3 scripts/media-release/test_profilarr_sonarr_upgrade_strategy.py`,
  and `python3 scripts/media-release/test_sonarr_large_series_upgrade.py` after
  changing the overnight upgrade split, search-overlap guards, or season
  rotation.
