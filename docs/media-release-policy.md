# Media Release Policy

Last updated: 2026-05-26

This documents the current Sonarr/Radarr release selection policy on `docker-vm`.
The goal is better grabbed releases, not just smaller files. Anime is handled as
a separate policy because dual audio is the highest priority there.

## Managed Systems

- Sonarr anime profile: `shows-anime`
- Sonarr regular profile: `shows-regular`
- Radarr anime profile: `movies-anime`
- Radarr regular profile: `movies-regular`
- Media stack: `/opt/media-stack` on `docker-vm`
- Recyclarr config: `/opt/media-stack/recyclarr/recyclarr.yml`
- Recyclarr schedule: daily at midnight
- Profilarr stack: `/opt/profilarr` on `docker-vm`, published at
  `profilarr.jnalley.me`
- Profilarr candidate/test profiles:
  - Sonarr: `shows-anime-profilarr-test` id `9`
  - Sonarr: `shows-regular-profilarr-test` id `10`
  - Radarr: `movies-anime-profilarr-test` id `8`
  - Radarr: `movies-regular-profilarr-test` id `9`
- Release metadata stamper: `playbooks/media/media-release-stamper.yml`
- Sonarr grab/import forensics: `scripts/media-release/sonarr_grab_forensics.py`
- Sonarr transaction audit report: `scripts/media-release/sonarr_transaction_audit.py`
- Sonarr targeted queue blocklist/removal helper:
  `scripts/media-release/sonarr_blocklist_queue_matches.py`
- Sonarr JoJo Stardust arc-local repair helper:
  `scripts/media-release/sonarr_jojo_stardust_s01_repair.py`
- Sonarr transaction monitor: `sonarr-transaction-monitor.timer` writes
  `/var/log/sonarr-transaction-monitor/events.jsonl`, rotated daily
- Sonarr recycle bin: disabled
- Radarr recycle bin: disabled
- Media-stack container library bind: `/srv/media/plex:/data`, backed by the single
  `/srv/media` NFS parent mount from TS440. Completed downloads and libraries
  stay under `/data` inside the containers so hardlinks still work.

Recyclarr manages the TRaSH custom formats and profile scores that are in its
config. Local custom formats created directly in Sonarr/Radarr are still valid,
but they must be documented here and checked after Recyclarr preview. Keep
`delete_old_custom_formats: false` unless the local CFs have been migrated.
Recyclarr's live `base_url` values point at the docker-vm local compose service
names (`http://sonarr:8989` and `http://radarr:7878`). Recyclarr no longer owns
`quality_definition` sync; Sonarr/Radarr quality-size caps are local policy and
must be checked after any Recyclarr config edit.

Sonarr/Radarr naming must preserve the fields that local CFs depend on. On
2026-05-22, Sonarr and Radarr naming formats were updated to include
`{MediaInfo VideoCodec}`. Sonarr anime naming already included
`{MediaInfo AudioLanguages}`, which is why dual-audio scoring survived rename;
codec did not, so existing HEVC/x265 files could lose the `x265` CF after import
and then be treated as cutoff-unmet later. Rename previews confirmed Sonarr will
render existing HEVC files as `[h265]`, which matches the current x265 regex.

## Quality Size Guard

Quality-size definitions are set globally in Sonarr/Radarr as MB/minute caps.
They are intentionally loose outlier guards, not small-encode targets. The goal
is to stop very large "upgrades" such as a 22 GiB single 1080p episode from
winning only because it matches `x265`, while still allowing high-bitrate
Bluray and remux candidates.

Current local caps:

- 480p: preferred `35`, max `60`
- 576p: preferred `50`, max `80`
- 720p: preferred `90`, max `140`
- 1080p: preferred `200`, max `300`
- 1080p remux: preferred `300`, max `450`
- 2160p: preferred `350`, max `550`
- 2160p remux: preferred `650`, max `900`

These values apply to both Sonarr and Radarr for matching qualities. Recyclarr
preview should show no `Quality Definition` changes; if it does, stop before
syncing and reconcile this local policy first.

## Anime Priority Order

Anime scoring is intentionally wide-band so the important choices cannot be
overridden by incidental format bonuses.

1. Hard rejects: `-1000000`
2. Dual audio: `+100000`
3. Quality rank: `+10000`, `+20000`, `+30000`, `+40000`
4. x265/HEVC preference: `+2000`
5. Source rank: `+1500` for Bluray/BD sources
6. Release-group tiers: bounded Profilarr/Dictionarry test tiers below x265
7. Soft avoids: small negative values only

This means any acceptable dual-audio release beats a non-dual-audio release,
but within dual audio, a higher enabled quality still beats a lower quality even
when the lower quality has x265 and a better release group.

## Anime Quality Rank

Sonarr `shows-anime` enabled qualities are grouped together so upgrades are
driven by custom-format scores instead of Sonarr's native quality order.

- `Local Anime Quality Rank - 480p`: `+10000`
- `Local Anime Quality Rank - 576p`: `+20000`
- `Local Anime Quality Rank - 720p`: `+30000`
- `Local Anime Quality Rank - 1080p`: `+40000`

Radarr `movies-anime` currently only enables 720p and 1080p movie qualities.

- `Local Anime Quality Rank - 720p`: `+30000`
- `Local Anime Quality Rank - 1080p`: `+40000`

## Anime Source Rank

`Local Anime Source Rank - Bluray` is scored `+1500` in Sonarr
`shows-anime`, Sonarr `shows-anime-profilarr-test`, Radarr `movies-anime`, and
Radarr `movies-anime-profilarr-test`.

The intent is narrow: same-resolution DA Web x264 should not beat same-resolution
DA Bluray x264 only because Web has a release-tier match and Bluray has no
source preference. Source rank stays below x265/HEVC (`+2000`), so a
same-resolution DA Web x265 with a good Web tier can still beat a bare DA
Bluray x264 when that matches the smaller-file preference.

Do not add new local CFs casually. The custom-format limit matters. Current
counts before the bounded Dictionarry tier test staging are Sonarr `76` and
Radarr `64`; the working limit for staging checks is `100`.

The audit script `scripts/media-release/arr_release_policy_audit.py` checks
current CF counts, profile scores, queue status, and unused/all-zero CFs.
`scripts/media-release/arr_profile_math_audit.py` checks the Profilarr test
profiles as a whole: DA beats all non-DA paths, x265 stays above source+tier
stacking, 1080p DA beats any 720p DA stack, best Bluray HEVC and best WEB HEVC
Dictionarry stacks are source-ordered, service CFs stay below the smallest
release-tier gap, old Recyclarr/TRaSH tier scores such as `WEB Scene` are zero
in the test profiles, and the CF limit is still obeyed.

The read-only live expectation checkers are
`scripts/media-release/sonarr_release_expectation_check.py` and
`scripts/media-release/radarr_release_expectation_check.py`. Run them on `docker-vm` through
Ansible when changing anime release policy. They verify the live anime profile
scores, confirm enabled anime qualities are in one native quality group, check
rename-format preservation of audio languages and video codec, check DA/x265
title-side custom-format matching, print series/movie profile counts, and
smoke-test the Arr parse endpoints.

`scripts/media-release/sonarr_series_audit.py <series>` is the read-only per-series state
check. It summarizes monitoring, per-season file/missing counts, active queue
items, recent series history, and active/recent commands. Use it when a manual
series/season search appears to grab only part of a show.

`playbooks/media/sonarr-transaction-monitor.yml` deploys
`sonarr-transaction-monitor.timer`, which records Sonarr history events and
queue snapshots to `/var/log/sonarr-transaction-monitor/events.jsonl`. The log
is mode `0640` and rotated daily with 90 retained rotations. Keep it enabled
while Profilarr upgrade searches are active so later reviews can compare
grab-time, queue-time, and import/delete outcomes without relying on memory.

`scripts/media-release/sonarr_transaction_audit.py` is the compact report over that monitor
log plus the live Sonarr queue. It summarizes recent history event types,
queue-count movement, recent grabbed/imported/deleted groups, and the current
queue's grouped classifications. Use it for periodic Profilarr review:

```bash
ansible docker-vm --become -m script -a "scripts/media-release/sonarr_transaction_audit.py --hours 24 --limit 25"
```

`scripts/media-release/arr_stage_profilarr_test_profiles.py` snapshots live Arr policy state
and creates or refreshes the Profilarr test profiles by cloning the current
anime profiles. It does not assign any series or movies to the test profiles.
It refuses to stage if the live CF count exceeds the configured CF limit.

`scripts/media-release/profilarr_state_audit.py` checks the local Profilarr SQLite database,
linked PCD databases, upgrade configs, recent sync/link/upgrade jobs, and
scheduler health. It treats queued and running jobs as active. Use it after
Profilarr restarts or scheduled upgrade runs.

`scripts/media-release/profilarr_disable_upgrade_jobs.py` disables Profilarr's scheduled
Arr upgrade configs and cancels queued scheduled `arr.upgrade` jobs with a
SQLite backup. It intentionally leaves Profilarr database auto-pull/sync
enabled.

`scripts/media-release/profilarr_sonarr_upgrade_strategy.py` updates the supported stored
settings for the Sonarr Profilarr upgrade filter without patching Profilarr
application code. It creates a SQLite backup before live mutation. Current use:
set the Sonarr selector to `random` so one old/problem series does not
monopolize every scheduled run.

`scripts/media-release/profilarr_candidate_audit.py` materializes the linked Profilarr PCD
repositories in memory and compares candidate CF/profile names with live
Sonarr/Radarr. It is read-only and useful for deciding what to borrow; it does
not sync anything to Arr.

`scripts/media-release/profilarr_selective_cf_import.py` is the controlled Profilarr-to-Arr
bridge. It reads Profilarr's locally synced Dictionarry/Dumpstarr PCD data,
copies only curated custom-format definitions into Arr as `Dumpstarr ...`
formats, and scores only the unassigned Profilarr test profiles. It does not
import upstream quality profiles and does not change production profile
assignments. Run it in `--dry-run` first; it writes timestamped Arr policy
snapshots under `/opt/media-stack/release-policy-snapshots/` before any live
mutation.

`scripts/media-release/profilarr_cf_definition_sync.py` refreshes selected
existing Arr custom-format definitions from enabled Profilarr PCD databases
without importing upstream quality profiles, changing profile structure, or
changing scores. It preserves local DA/x265/quality-rank CFs and enforces the
CF limit. By default it ignores disabled PCD databases and skips large
spec-count collapses, because some upstream names do not represent the same
kind of CF as the existing Arr name. Use `--inspect-target <CF name>` before
reviewing any tier-list replacement.

## Anime Hard Rejects

Hard rejects use `-1000000`. They must stay far below zero even if combined
with dual audio and the highest quality rank.

Sonarr `shows-anime` hard rejects:

- `Anime LQ Groups`
- `Anime Raws`
- `LQ`
- `LQ (Release Title)`
- `Local Anime Raw Group - DBD-Raws`
- `Portuguese (No English)`
- `Dubs Only (Block)`
- `UHD 2160p - Non-Dual (Block)`
- `2160p`

Radarr `movies-anime` hard rejects:

- `Anime LQ Groups`
- `Anime Raws`
- `LQ`
- `LQ (Release Title)`
- `No ISO`

## Anime Soft Avoids

Soft avoids are deliberately small. A soft avoid must not allow a lower-quality
dual-audio release to beat a higher-quality dual-audio release.

Sonarr `shows-anime` soft avoids:

- `AV1`: `-2000`
- `No AV1`: `-2000`
- `Language - Not Original`: `-1000`
- `No German Audio`: `-500`

Radarr `movies-anime` soft avoids:

- `AV1`: `-2000`
- `Language - Not Original`: `-1000`

`Language - Not Original` must not be a hard reject for anime because it can
match releases that are otherwise valid dual audio. The dual-audio CF is the
source of truth for anime language preference.

## Verified Anime Score Math

The verification targets are:

- `720p DA + x265 + best group`: `100000 + 30000 + 2000 + 1400 = 133400`
- `1080p DA`: `100000 + 40000 = 140000`
- `1080p DA Bluray x264`: `100000 + 40000 + 1500 = 141500`
- `1080p DA Web x264 + best Web tier`: `100000 + 40000 + 600 = 140600`
- `1080p DA Web x265 + best Web tier`: `100000 + 40000 + 2000 + 600 = 142600`
- `1080p DA + x265 + Bluray + top single tier`: `100000 + 40000 + 2000 + 1500 + 1400 = 144900`

The live Sonarr check on 2026-05-22 confirmed:

- `shows-anime` has one native quality group named `Anime Enabled Qualities`.
- That group covers the enabled anime resolutions `480`, `576`, `720`, and
  `1080`.
- The largest single non-core positive CF was `Anime BD Tier 01` at `+1400`.
- Lowest enabled DA quality beats strongest single-tier non-DA:
  `110000 > 43400`.
- `1080p DA` beats `720p DA + x265 + top single tier`: `140000 > 133400`.
- `1080p DA Bluray x264` beats `1080p DA Web x264 + Web Tier 01`:
  `141500 > 140600`.
- `1080p DA Web x265 + Web Tier 01` beats bare `1080p DA Bluray x264`:
  `142600 > 141500`.
- Sonarr renaming is enabled, and the anime rename format includes both
  `{MediaInfo AudioLanguages}` and `{MediaInfo VideoCodec}`.
- Series profile distribution was `shows-anime: 150`, `shows-regular: 71`, with
  no series pointing at an unknown quality profile.

The live Radarr check on 2026-05-22 confirmed:

- `movies-anime` has one native quality group named `Anime Enabled Qualities`.
- That group covers the enabled anime movie resolutions `720` and `1080`.
- `Anime Dual Audio` is scored `+100000`; `x265 (HD)` is scored `+2000`.
- The largest single non-core positive CF was `Anime BD Tier 01` at `+1400`.
- Lowest enabled DA quality beats strongest single-tier non-DA:
  `130000 > 43400`.
- `1080p DA` beats `720p DA + x265 + top single tier`: `140000 > 133400`.
- `x265 (HD)` matches HD HEVC/x265 but excludes `2160p`.
- Radarr renaming is enabled, and the movie rename format includes both
  `{MediaInfo AudioLanguages}` and `{MediaInfo VideoCodec}`.
- Movie profile distribution was `movies-anime: 32`, `movies-regular: 238`,
  with no movie pointing at an unknown quality profile.
- Radarr queue status was empty: `totalCount=0`.

After soft avoids:

- Sonarr `1080p DA` with stacked soft avoids: `134500`
- Radarr `1080p DA` with stacked soft avoids: `137000`

Both still beat `720p DA + x265 + best group`.

With a hard reject:

- `1080p DA + hard reject`: `-860000`

That is below the minimum score and should not be eligible.

## Regular Profiles

The regular TV/movie profiles still use the smaller TRaSH-style scoring scale.
Their existing `-10000` unwanted penalties are already larger than the normal
positive score ceiling, so they are not the same risk as anime's `+100000`
dual-audio band.

Do not copy anime score bands into `shows-regular` or `movies-regular` without a
separate audit. Regular profiles should be improved deliberately by reviewing
the current TRaSH profile, quality definitions, release groups, codec policy,
language policy, and observed grabs.

## Change Procedure

For future release-policy changes:

1. Audit all existing nonzero custom-format scores in the affected profiles.
2. Classify each changed CF as hard reject, major preference, quality rank,
   codec preference, release-group preference, or soft avoid.
3. Check the math against realistic competing releases before applying.
4. Apply live changes with backups.
5. Run Recyclarr `sync --preview` and confirm it will not undo the policy.
6. Run Sonarr/Radarr queue/history checks for regressions. For Sonarr, use
   `scripts/media-release/sonarr_grab_forensics.py` before any cleanup so the queue is
   classified as valid upgrade, payload score loss, pack collateral, or client
   failure instead of just deleted after bandwidth has already been spent.
7. Update this document and the short README summary in the same change.

Never change a single score band in isolation without checking the rest of the
profile. A score that was safe in a `10000`-point profile may be wrong in the
anime `100000`-point dual-audio model.

## Profilarr Candidate Migration

Current migration posture as of 2026-05-26:

- Live Sonarr/Radarr source profiles are still active:
  - Sonarr `shows-anime`: 150 series
  - Radarr `movies-anime`: 32 movies
- Test profiles exist but have no assignments:
  - Sonarr `shows-anime-profilarr-test`: 0 series
  - Sonarr `shows-regular-profilarr-test`: 0 series
  - Radarr `movies-anime-profilarr-test`: 0 movies
  - Radarr `movies-regular-profilarr-test`: 0 movies
- Dictionarry is linked in Profilarr, enabled, and auto-pulls hourly.
- Dumpstarr is linked in Profilarr but currently disabled. Do not use
  disabled/stale PCD sources for production definition sync unless the source
  is explicitly re-enabled and revalidated first.
- Dictionarry compact release-tier custom formats have been copied into Arr and
  scored only in the test profiles. Production `shows-anime`, `shows-regular`,
  `movies-anime`, and `movies-regular` still use the existing active policy.
- Selected existing Arr CF definitions were safely refreshed from enabled
  Dictionarry sources on 2026-05-26. This touched service/source/repack-style
  CF definitions only; it did not touch DA, x265, quality ranks, profile
  scores, profile structure, or release-group tier CFs.

The candidate audit found useful material in Dumpstarr and Dictionarry, but
also confirmed that stock Dumpstarr scoring conflicts with this library's codec
policy. Dumpstarr's `TV 1080p` profile scores `x265 (HD)` at `-10000`; this
library wants HD x265/HEVC preferred at `+2000`. Any future Profilarr migration
must override that before assigning real media or syncing replacement profiles.

Candidate material worth evaluating:

- Updated anime/web/bluray group tiers.
- Baseline group tiers.
- Bad/banned group filters.
- Bad dual-audio group filters.
- Bad source / bad multis / LQ release-title filters.
- Dictionarry compact/efficient tiers, if they can be mapped without blowing
  past the CF limit.

Candidate material not safe to adopt blindly:

- Any stock x265 penalty.
- Any stock dual-audio score that is too small to enforce DA-first behavior.
- Any profile cutoff/minimum score that assumes a normal TRaSH score scale.
- Any release-group tiers that duplicate current names without proving better
  regex coverage.
- Dumpstarr exact `WEB Tier 01/02/03` definitions as direct replacements for
  current Arr `WEB Tier` release-group tiers. The 2026-05-26 inspection showed
  those materialized Dumpstarr definitions collapse to WEB source checks, not
  release-group tier regexes.

Historical selective Dumpstarr import state:

- Script: `scripts/media-release/profilarr_selective_cf_import.py`
- Latest applied snapshot:
  `/opt/media-stack/release-policy-snapshots/20260523T063425Z-selective-profilarr-cfs`
- The imported `Dumpstarr ...` formats from this pass were later removed from
  live Arr as stale all-zero non-rename formats during Dictionarry compact-tier
  staging on 2026-05-26.
- Existing TRaSH anime tier scores were zeroed only in the test profiles during
  that historical pass:
  - Sonarr `shows-anime-profilarr-test`
  - Radarr `movies-anime-profilarr-test`
- Historical `Dumpstarr ...` tier/filter scores in the test profiles were:
  - `Dumpstarr Anime BD Tier 01..08`: `+1400` down to `+700`
  - `Dumpstarr Anime WEB Tier 01..6`: `+1400` down to `+900`
  - `Dumpstarr Anime Baseline Groups`: `+150`
  - `Dumpstarr Anime LQ`: `-1000000`
  - `Dumpstarr Bad Multis`: `-1000000`
  - `Dumpstarr Bad Source`: `-1000000` in Sonarr only
  - `Dumpstarr Banned Groups`: `-1000000`
- Skipped because the materialized PCD did not produce usable Arr
  specifications:
  - `Bad Dual Groups`
  - `Banned Groups (Title)`
  - `Bad Source` on Radarr

Current Dictionarry bounded-tier test plan:

- Scripts:
  - `scripts/media-release/profilarr_tier_candidate_compare.py`
  - `scripts/media-release/profilarr_bounded_tier_import.py`
  - `scripts/media-release/arr_profile_math_audit.py`
- Latest applied compact-only snapshot:
  `/opt/media-stack/release-policy-snapshots/20260526T211737Z-dictionarry-compact-tiers`
- Current CF counts before bounded-tier apply:
  - Sonarr: `76/100`
  - Radarr: `64/100`
- Refreshed test profiles only:
  - Sonarr `shows-anime-profilarr-test` id `9`
  - Sonarr `shows-regular-profilarr-test` id `10`
  - Radarr `movies-anime-profilarr-test` id `8`
  - Radarr `movies-regular-profilarr-test` id `9`
- Production profile scores, cutoffs, and media assignments were not changed.
- This is still test-profile only. It is the proposed main-profile replacement
  model staged for inspection before moving any series/movie to the test
  profiles and before changing production profile scores.
- Test profiles are staged in replacement mode, not stacked mode. Legacy
  Recyclarr/TRaSH release-tier scores matching `Tier NN` plus the old regular
  `WEB Scene` tier are zeroed in the test profiles before Dictionarry tiers are
  scored. Sonarr/Radarr require every custom format to stay present in profile
  `formatItems`, so old tier rows may still be visible at `0`; only nonzero
  score affects release selection.
- Imported Sonarr Dictionarry TV tiers:
  - Efficient Bluray Tier 1..6: `+180`, `+172`, `+150`, `+135`, `+120`,
    `+105`
  - Efficient WEB Tier 1..5: `+160`, `+145`, `+130`, `+115`, `+100`
  - Compact Bluray Tier 1..6: `+150`, `+142`, `+126`, `+114`, `+102`, `+90`
  - Compact WEB Tier 1..5: `+130`, `+118`, `+106`, `+94`, `+82`
  - Compact Trash Tier 1..2: `-250`, `-350`
- Imported Radarr Dictionarry movie tiers:
  - Efficient Bluray Tier 1..4: `+180`, `+165`, `+150`, `+135`
  - Efficient WEB Tier 1..4: `+150`, `+132`, `+114`, `+96`
  - Compact Bluray Tier 1..4: `+150`, `+135`, `+120`, `+105`
  - Compact WEB Tier 1..4: `+125`, `+110`, `+95`, `+80`
- Shared imported Dictionarry tiers:
  - `1080p Bluray HEVC Tier 1`: `+60`
  - `1080p WEB-DL HEVC Tier 1`: `+60`
  - `WEB-DL Tier 1..5`: `+20`, `+16`, `+12`, `+8`, `+4`
- Positive service/source tags such as `AMZN`, `NF`, `DSNP`, `CR`, and `VRV`
  are capped to `+1` in the test profiles when they were positive in the
  cloned source profile. Zero-scored service tags stay zero. This makes them
  tie-breakers only: the smallest adjacent Dictionarry tier gap is `+4`, so a
  service tag cannot reorder even the weakest imported tier ladder.
- Score math:
  - Best Bluray HEVC stack: `180 + 150 + 60 = 390`
  - Sonarr second Bluray HEVC stack: `172 + 142 + 60 = 374`
  - Sonarr best WEB HEVC stack: `160 + 130 + 60 + 20 = 370`
  - Radarr second Bluray HEVC stack: `165 + 135 + 60 = 360`
  - Radarr best WEB HEVC stack: `150 + 125 + 60 + 20 = 355`
  - Anime Bluray source plus best tier stack plus service tie-breaker:
    `1500 + 390 + 1 = 1891`, still below x265/HEVC at `+2000`
  - Max non-DA 1080p path: `40000 + 2000 + 1500 + 390 + 1 = 43891`, still
    below DA at `+100000`
  - Max 720p DA path: `100000 + 30000 + 2000 + 1500 + 390 + 1 = 133891`, still
    below the 1080p DA floor of `140000`
- Source ordering checks deliberately keep WEB below Bluray at the near-tier
  boundary: Sonarr Efficient WEB Tier 1 (`+160`) is below Efficient Bluray Tier
  2 (`+172`), Sonarr Compact WEB Tier 1 (`+130`) is below Compact Bluray Tier 2
  (`+142`), Radarr Efficient WEB Tier 1 (`+150`) is below Efficient Bluray Tier
  2 (`+165`), and Radarr Compact WEB Tier 1 (`+125`) is below Compact Bluray
  Tier 2 (`+135`).
- These scores are intentionally below DA (`+100000`), anime quality ranks, and
  x265/HEVC (`+2000` anime, `+3000` regular). Because old Recyclarr/TRaSH tier
  scores are zeroed in the test profiles, Dictionarry tiers do not stack with
  the old tier band or outrank x265 by double-counting release groups.
- The bounded-tier import cleanup deletes only all-zero non-rename custom
  formats. It must not delete formats with `includeCustomFormatWhenRenaming`
  enabled, and it protects local helper formats such as DA title/metadata
  helpers, H.265/x265, source rank, hard rejects, soft avoids, and local anime
  quality-rank prefixes.
- Broader Dictionarry tiering is available but deliberately excluded from this
  pass. Balanced, Quality, lower-resolution, HDTV, and Remux families remain
  candidates for later review; do not add them until their scoring can be proven
  not to bias the profile toward larger files or weaker source choices.
- Coverage check from the 2026-05-26 live tier audit: compact-only is narrower
  than the previous tier coverage. Sonarr/Radarr anime TRaSH anime BD+Web tiers
  each exposed about `251` release-title/release-group patterns, while the
  staged Dictionarry compact TV tiers exposed about `58` and compact movie
  tiers exposed about `47`. Sonarr regular `WEB Tier 01..03` exposed about
  `73`; Radarr regular `HD Bluray Tier 01..03` plus `WEB Tier 01..03` exposed
  about `81`. Do not treat compact-only as a full replacement for the old tier
  reach.
- Dictionarry family summary from the same audit:
  - Compact: `20` CFs, about `149` patterns
  - Efficient: `30` CFs, about `300` patterns
  - HEVC-specific: `4` CFs, about `17` patterns
  - Balanced: `5` CFs, about `6` patterns
  - Quality: `12` CFs, about `195` patterns
  - Lower-resolution: `27` CFs, about `152` patterns
  - HDTV: `4` CFs, about `14` patterns
  - WEB-DL: `5` CFs, about `54` patterns
  - Trash-tier: `2` CFs, about `8` patterns
  - Remux: `6` CFs, about `33` patterns
  Efficient and HEVC-specific are the most relevant next candidates for the
  smaller-file/x265 preference. Quality has broad reach, but it should be
  treated carefully because it may bias toward larger, quality-first groups
  rather than compact/efficient encodes.

Current existing-definition sync state:

- Script: `scripts/media-release/profilarr_cf_definition_sync.py`
- Latest applied snapshot:
  `/opt/media-stack/release-policy-snapshots/20260526T202831Z-profilarr-cf-definition-sync`
- Latest idempotence dry-run snapshot:
  `/opt/media-stack/release-policy-snapshots/20260526T202848Z-profilarr-cf-definition-sync-dry-run`
- Applied from enabled Dictionarry sources:
  - Sonarr: `Extras`, `AV1`, `Repack2`, `Repack3`, `AMZN`, `ATVP`, `CR`,
    `DSNP`, `HMAX`, `HULU`, `MAX`, `NF`, `PCOK`, `PMTP`, `SHO`, `STAN`, `iT`
  - Radarr: `Extras`, `AV1`, `Repack2`, `Repack3`, `AMZN`, `ATVP`, `DSNP`,
    `HMAX`, `MAX`, `NF`, `PCOK`, `PMTP`, `STAN`, `iT`
- Post-apply dry run reported `changed=0` for the safe enabled-source sync.
- Validation after the apply:
  - Sonarr/Radarr queues were clean.
  - Sonarr and Radarr DA/x265/quality-rank expectation checks passed.
  - CF counts remained Sonarr `84/100`, Radarr `74/100`.

Profilarr remains the upstream refresh source for imported CFs, but Profilarr
itself is not directly managing the copied Arr formats yet. The sync path is:
Profilarr auto-pulls Dictionarry/Dumpstarr, then repo-managed scripts refresh
selected Arr definitions and reapply local scores. Use
`scripts/media-release/profilarr_bounded_tier_import.py` for the current
Dictionarry bounded-tier test profiles. This preserves upstream CF-definition
updates without accepting upstream profile scoring such as the stock x265
penalty.

Before assigning any series/movie to a Profilarr-derived profile, run:

```bash
ansible docker-vm --become -m script -a "scripts/media-release/arr_stage_profilarr_test_profiles.py --dry-run"
ansible docker-vm -m script -a scripts/media-release/profilarr_candidate_audit.py
ansible docker-vm -m script -a "scripts/media-release/profilarr_tier_candidate_compare.py --only-missing --name-regex '1080p Compact (TV|Movie) (WEB|Bluray|Trash) Tier'"
ansible docker-vm --become -m script -a "scripts/media-release/profilarr_bounded_tier_import.py --dry-run"
ansible docker-vm -m script -a scripts/media-release/arr_profile_math_audit.py
ansible docker-vm --become -m script -a "scripts/media-release/sonarr_transaction_audit.py --hours 24 --limit 25"
ansible docker-vm -m script -a scripts/media-release/sonarr_release_expectation_check.py
ansible docker-vm -m script -a scripts/media-release/radarr_release_expectation_check.py
```

Only after the candidate profile proves the same DA/x265/quality math should a
small pilot set be moved to the test profile.

## Backups And Cleanup

Live release-policy changes require targeted backups before mutation. Current
rollback artifacts from the Profilarr staging pass:

- Arr policy dry-run snapshot:
  `/opt/media-stack/release-policy-snapshots/20260523T014538Z`
- Arr policy pre-stage snapshot:
  `/opt/media-stack/release-policy-snapshots/20260523T014603Z`
- Profilarr DB backup before linking Dumpstarr:
  `/opt/profilarr/config/data/backups/profilarr-pre-dumpstarr-20260523T014640Z.db`
- Selective Profilarr CF dry-run snapshot:
  `/opt/media-stack/release-policy-snapshots/20260523T063216Z-selective-profilarr-cfs-dry-run`
- Selective Profilarr CF applied snapshot:
  `/opt/media-stack/release-policy-snapshots/20260523T063425Z-selective-profilarr-cfs`
- Profilarr DB backup before Sonarr selector change:
  `/opt/profilarr/config/data/backups/profilarr-pre-sonarr-upgrade-strategy-20260524T192516Z.db`
- Existing-CF Dictionarry definition sync snapshots:
  `/opt/media-stack/release-policy-snapshots/20260526T202831Z-profilarr-cf-definition-sync`,
  `/opt/media-stack/release-policy-snapshots/20260526T202848Z-profilarr-cf-definition-sync-dry-run`,
  and inspection snapshot
  `/opt/media-stack/release-policy-snapshots/20260526T203104Z-profilarr-cf-definition-sync-dry-run`
- Dictionarry compact-tier test-profile snapshots:
  `/opt/media-stack/release-policy-snapshots/20260526T203854Z-profilarr-cf-definition-sync-dry-run`,
  `/opt/media-stack/release-policy-snapshots/20260526T210325Z-dictionarry-compact-tiers-dry-run`,
  `/opt/media-stack/release-policy-snapshots/20260526T210414Z-dictionarry-compact-tiers`,
  replacement-mode dry-run
  `/opt/media-stack/release-policy-snapshots/20260526T211726Z-dictionarry-compact-tiers-dry-run`,
  and replacement-mode applied snapshot
  `/opt/media-stack/release-policy-snapshots/20260526T211737Z-dictionarry-compact-tiers`
- JoJo Stardust blocklist / wrong-import repair backups:
  `/opt/media-stack/arr-policy-backups/20260524T210710Z-jojo-stardust-s01-repair`
  and
  `/opt/media-stack/arr-policy-backups/20260524T210853Z-jojo-stardust-s01-repair`
- JoJo bad queue cleanup backups:
  `/opt/media-stack/arr-policy-backups/20260524T211653Z-sonarr-blocklist-queue-matches`,
  `/opt/media-stack/arr-policy-backups/20260524T211853Z-sonarr-blocklist-queue-matches`,
  and
  `/opt/media-stack/arr-policy-backups/20260524T211910Z-sonarr-blocklist-queue-matches`
- Recyclarr URL/quality-definition ownership and size-guard backups:
  `/opt/media-stack/recyclarr/recyclarr.yml.codex-pre-docker-vm-url-fix-20260526T192212Z`,
  `/opt/media-stack/recyclarr/recyclarr.yml.codex-pre-quality-size-guard-20260526T192435Z`,
  `/opt/media-stack/release-policy-snapshots/20260526T192435Z-quality-size-guard`,
  and
  `/opt/media-stack/release-policy-snapshots/20260526T193707Z-loose-quality-size-guard`

Keep these while the Profilarr candidate path is still being validated. After
the final profile migration is accepted or abandoned, clean up the temporary
snapshots/backups or move the one final known-good export into the normal
retention location. Do not let staging snapshots pile up indefinitely.

## Current Notes

- Recyclarr preview must be treated as part of verification because Recyclarr
  can overwrite managed TRaSH CF scores on its next scheduled sync.
- Local/manual CFs such as `Local Anime Raw Group - DBD-Raws`,
  `Portuguese (No English)`, and the quality-rank CFs must remain documented
  because they are not all represented by TRaSH/Recyclarr defaults.
- Sonarr and Radarr failed-download auto-redownload is intentionally disabled.
  Proactive improvement searches should be owned by a paced tool such as
  Profilarr, not by hidden per-item redownload retries that can spawn searches
  while the queue is already unhealthy.
- Prowlarr indexer hygiene is part of the upgrade plan. On 2026-05-22,
  `BitSearch` was removed because it had no working definition, and `1337x` /
  `LimeTorrents` were disabled after long-term availability failures. Keep bad
  broad public indexers out of automatic searches before enabling Profilarr
  upgrade jobs.
- NZBFinder quota exhaustion by itself is not a disable/remove condition. If it
  reports `Request limit reached`, leave the indexer enabled and let Prowlarr's
  own temporary indexer-status cooldown skip it until the quota window resets.
- A large Sonarr queue does not prove every queued episode was individually
  accepted as an upgrade. On 2026-05-22, `scripts/media-release/sonarr_grab_diagnostics.py`
  showed Bleach queue pollution from multi-episode Judas packs: one
  `056-111` pack had 56 queue rows but only one row where the queued release
  beat the current file score, while two `001-055` pack rows were entirely
  worse than the current files after earlier imports. This is pack collateral
  and duplicate-search timing, not a reason to change DA priority.
- Another observed source of repeated grabs was codec score drift after rename.
  Existing files such as imported Judas/Audio HEVC releases retained DA via
  `[JA+EN]` but did not retain `x265`/`HEVC` in the filename, so the current
  stored file score could be about `+2000` below the release Sonarr just
  searched. Preserve codec in naming and rename/rescan existing files before
  judging whether the final profile scores are looping.
- Multi-file download packs can lose release-title CF evidence before import.
  The observed Judas Bleach packs were grabbed correctly from release titles
  containing `Dual-Audio` and `x265`, but Sonarr later evaluated individual
  payload names such as `[Judas] Bleach - 056.mkv` and no longer saw those
  tokens. `ffprobe` on representative completed files confirmed both Japanese
  and English audio streams were present, so this was metadata loss between
  grab and import, not proof that the pack was actually Japanese-only.
- The current fix for repeated non-better grabs is to make grab-time and
  import-time evidence line up, not to rely on queue deletion. If a release is
  accepted because its parent title has DA, x265/HEVC, platform/source, or a
  recognized release group, the download-client stamper should preserve the
  matching evidence in each eligible payload file before Sonarr imports it.
  Deleting current-better queue rows is a last cleanup step after inspection,
  not the steady-state behavior.
- `scripts/media-release/sonarr_grab_diagnostics.py` is the queue regression check. By
  default it is read-only. `--remove-current-better --remove-from-client`
  removes only downloads where the existing imported file has a higher current
  custom-format score than the queued item; it uses Sonarr queue deletion with
  `blocklist=false`. On 2026-05-22, after inspection, it removed 168 stale
  worse queue rows across 5 downloads. The follow-up check showed 69 remaining
  queue rows, all with `queued_better` and no `current_better` candidates.
- `scripts/media-release/sonarr_grab_forensics.py` is the first-line read-only queue
  classifier for the same problem. It groups queue rows by download, compares
  queued vs current custom-format scores, flags likely payload score loss,
  pack collateral/mapping issues, stalled/warning downloads, and active valid
  upgrades, and prints the release signals Sonarr probably used at grab time.
  Use it before considering any queue removal or download-client cleanup.
- Bleach fresh-search incident, 2026-05-22 local time: after the show was
  deleted/re-added, the manual search began around `20:37` and then `media-vm`
  rebooted at `20:50` and again at `20:58`. Sonarr restarted at `20:50:35` and
  `20:58:41`, leaving already-running searches orphaned/interrupted. The only
  Bleach download left active afterward was the already-grabbed S17 LGH
  dual-audio pack. `scripts/media-release/sonarr_series_audit.py Bleach` confirmed all
  regular seasons were monitored and 360 monitored episodes remained missing,
  so this was not a profile/monitoring choice to only grab S17. A replacement
  Bleach `SeriesSearch` was queued as Sonarr command `559238`.
- Profilarr scheduled upgrade incident, 2026-05-23 UTC: Sonarr's hourly
  cutoff-unmet job selected `Chainsaw Man` and correctly grabbed `[sam]
  Chainsaw Man Season 1 (S01) v2 (BD 1080p HEVC x265 10-bit FLAC)
  [Dual-Audio]` at score `143400`, replacing `Okay-Subs` 1080p Japanese-only
  files scored `41200`. The same cycle exposed a Radarr scoring hole:
  `One Piece Film: Z` was queued as a non-DA 1080p x265 file over an existing
  DA 1080p file because the current file had the hard `LQ` penalty, and
  `One Piece Film: Strong World` was queued as `HDTV-1080p` over an existing
  `Bluray-1080p` DA file for the same reason. Both Radarr queue items were
  removed with `removeFromClient=true` and `blocklist=false`; Konosuba and
  Jujutsu Kaisen 0 remained queued because they were DA Bluray x265 upgrades.
  The durable fix is to rescale or split hard/soft negative CFs and native
  quality/source ranking so release-group or LQ penalties cannot override
  DA-first and higher-native-quality-first behavior.
- qBittorrent hidden Sonarr pollution, 2026-05-23 UTC: Sonarr's tracked queue
  only showed the valid Chainsaw Man DA Bluray x265 batch, but direct qBittorrent
  API inspection found untracked `tv-sonarr` torrents that should not import:
  `[AnimeDevil] Welcome to Demon School! Iruma-kun 2nd Season - Ep01.mkv`
  parsed ambiguously as an absolute episode, `Bleach - Season 2 [BD][1080p]`
  had no DA/x265 signal and no seeds, and `[Judas] Mairimashita! Iruma-kun -
  S01E02.mkv` duplicated a better active full-season EMBER DA x265 BDRip pack.
  All three were removed directly from qBittorrent with files deleted and no
  Arr blocklist action. Keep checking qBittorrent/SAB directly during large
  manual searches because Sonarr's queue API can hide client-side residue.
- Bleach queue cleanup, 2026-05-23 UTC: during the larger Bleach search,
  `scripts/media-release/sonarr_grab_diagnostics.py` found `[Judas] Bleach 001-055 [BD
  1080p][HEVC x265 10bit][Dual-Audio][Eng-Sub]` was still present as 55 SAB
  queue rows even though the current imported files already had higher scores.
  It was removed with `--remove-current-better --remove-from-client` and no
  blocklist action. A follow-up diagnostic showed 93 Sonarr queue rows left:
  Bleach `056-111`, Iruma-kun S01 EMBER, Chainsaw Man `[sam]`, and two
  American Dad WEB-DL rows, with no remaining current-better cleanup candidates.
- Dual-audio title policy fix, 2026-05-23 UTC: Sonarr grabbed `[Judas] Bleach
  056-111 [BD 1080p][HEVC x265 10bit][Dual-Audio][Eng-Sub]` correctly at
  search time with `Anime Dual Audio` and score `142700`, but the active queue
  later showed only parsed language `English`, `Language - Not Original`, and
  score `41700`. The problem was not the release title or release group; it was
  that the live `Anime Dual Audio` CF still depended on optional parsed-language
  specs, so queue/import reparses could lose DA when Sonarr only saw
  `[Eng-Sub]`. `scripts/media-release/arr_dual_audio_title_policy.py --apply` changed Sonarr
  and Radarr `Anime Dual Audio` to trust explicit title markers such as
  `Dual-Audio`, `Multi-Audio`, `JA+EN`, `JP+EN`, `ZH+EN`, or `KO+EN`, and
  changed `Language - Not Original` so it does not apply when those explicit DA
  markers are present. This preserves the DA-first score model without relying
  on parsed language metadata being stable through search, queue, and import.
- Recyclarr ownership note for that fix: the stock TRaSH/Recyclarr `Anime Dual
  Audio` custom formats were removed from `/opt/media-stack/recyclarr/recyclarr.yml`
  for Sonarr trash ID `418f50b10f1907201b6cfdf881f467b7` and Radarr trash ID
  `4a3b087eea2ce012fcc1ce319259a3be`, because future Recyclarr syncs would
  otherwise overwrite the local title-marker DA behavior. Rollback backups from
  the live change are `/opt/media-stack/arr-policy-backups/20260523T045221Z-dual-audio-title-policy`
  and `/opt/media-stack/recyclarr/recyclarr.yml.codex-pre-da-title-policy-20260523T045211Z`.
  A dry-run backup also exists at `/opt/media-stack/arr-policy-backups/20260523T045113Z-dual-audio-title-policy`;
  clean these temporary rollback aids after the policy has survived normal
  search/import traffic.
- Queue caveat from the same rollout: already-tracked Sonarr queue rows can keep
  their old stored CF list until Sonarr processes monitored-download refreshes
  or the client/import state changes. Immediately after the fix, the existing
  Bleach `056-111` SAB queue rows still displayed score `41700`, but direct
  Sonarr parse of the exact title returned score `142700` with `Anime Dual
  Audio`, and newer Bleach grab history for `168-195` also showed score
  `142700`. At that moment Sonarr command `559257` (`RefreshMonitoredDownloads`)
  was queued behind manual `SeriesSearch` commands for Bleach, Iruma-kun, One
  Piece, JoJo, and Cyberpunk. Treat fresh parse/new history as the policy proof;
  do not remove valid DA downloads only because an old active queue row has not
  recomputed yet.
- Recycle-bin disable and queue cleanup, 2026-05-23 UTC: Sonarr health
  reported `/data/.sonarr-recycle-bin` was not writable. The directories
  existed and had correct ownership, but they existed only on the `media-01`
  mergerfs branch, which was at the configured `minfreespace=50G` threshold, so
  container writes failed with `No space left on device`. `mergerfs_branch_subdirectories`
  in `inventory/group_vars/nas_server/mergerfs.yml` now manages both
  `plex/.sonarr-recycle-bin` and `plex/.radarr-recycle-bin` across every media
  branch. After `ansible-playbook playbooks/storage/mergerfs.yml`, writes from inside
  both Sonarr and Radarr containers succeeded, and Sonarr health no longer
  reported the recycle-bin error. The same pass removed 22 remaining SiQ Bleach
  single-episode queue downloads where the current imported file already had a
  higher CF score, using `scripts/media-release/sonarr_grab_diagnostics.py --remove-current-better
  --remove-from-client` with the default `blocklist=false`. A follow-up
  diagnostic showed 317 queue rows and no remaining current-better cleanup
  candidates.
- Recycle bins are now disabled because preserving old replaced media consumed
  too much mergerfs branch space during large upgrade passes. `scripts/media-release/arr_disable_recycle_bins.py`
  backed up the live media-management configs to
  `/opt/media-stack/arr-policy-backups/20260523T065044Z-recycle-bin-disabled/`,
  then set Sonarr/Radarr `recycleBin` to empty and `recycleBinCleanupDays` to
  `0`. The existing bin contents were removed across all media branches:
  `media-01` had `609G` Sonarr and `26G` Radarr recycle-bin content, and
  `media-04` had `1.8G` Sonarr and `4.5G` Radarr content. After cleanup,
  `media-01/media/plex` had `684G` free. A Sonarr `RefreshMonitoredDownloads`
  command cleared the stored Bleach recycle-bin import errors; the remaining
  queue warnings were only American Dad TBA/XEM metadata issues.
- Follow-up queue cleanup on the same rollout removed 10 inspected Sonarr
  downloads where the imported files already had higher custom-format scores:
  two Bleach BluRay box downloads, one lower-scored Bleach dual-audio download,
  six stalled xDTK Bleach downloads, and one Slime download. Removal used
  `removeFromClient=true` and `blocklist=false`. A final
  `scripts/media-release/sonarr_grab_diagnostics.py` pass showed 194 Sonarr queue rows with
  `current_better=0` on every remaining group. Radarr had one completed
  non-upgrade queue item, `Straume.2024.1080p.BluRay.DD+7.1.x264-playHD`,
  removed with `removeFromClient=true` and `blocklist=false`; the final Radarr
  queue had two active downloads and zero status messages.
- Bleach source-rank incident, 2026-05-24 UTC: LostYears DA Web 1080p x264
  episodes replaced existing LGH DA Bluray 1080p x264 episodes because Web Tier
  01 added `+600` while Bluray had no local source score. This was a scoring
  hole, not a DA-detection failure: the replacement titles had `[EN+JA]` and
  matched `Anime Dual Audio`. `scripts/media-release/arr_anime_source_rank_policy.py --apply`
  created `Local Anime Source Rank - Bluray`, scored it `+1500` in the Sonarr
  and Radarr anime production/test profiles, and raised the anime cutoffs to
  `144900`. Backups are
  `/opt/media-stack/arr-policy-backups/20260524T180618Z-anime-source-rank-policy`
  and
  `/opt/media-stack/arr-policy-backups/20260524T180632Z-anime-source-rank-policy`.
  The bad tracked LostYears Web x264 files for Bleach S17E02/S17E03/S17E04/
  S17E06/S17E08/S17E10/S17E11 were deleted through Sonarr after backing up
  Sonarr DB/config to
  `/opt/media-stack/arr-policy-backups/20260524T182146Z-bleach-web-x264-revert/`;
  after the media-stack mount repair, rescan reattached the still-present LGH
  Bluray files for S17E02/S17E03/S17E04/S17E06/S17E08/S17E10/S17E11.
- Media-stack mount repair, 2026-05-24 UTC: media-vm's whole-media VirtioFS
  mount `/srv/media` was hanging on simple `ls/stat` while the dedicated
  Plex-library mount `/srv/plex` responded normally. Live
  `/opt/media-stack/docker-compose.yml` was backed up to
  `/opt/media-stack/arr-policy-backups/20260524T183559Z-media-stack-plex-bind/`
  and media containers were rebound from `/srv/media/plex:/data` to
  `/srv/plex:/data`. Container-internal paths did not change, and a real
  `ln` test inside Sonarr verified hardlink behavior across
  `/data/downloads/complete` and `/data/Anime`.
- JoJo Stardust arc-local blocklist incident, 2026-05-24 UTC: Sonarr's
  combined `JoJo's Bizarre Adventure (2012)` series maps Jonathan/Joseph/Battle
  Tendency to Season 1 with 26 episodes and maps Stardust Crusaders to Season 2
  with 48 episodes. The bad releases were arc-local iAHD titles shaped like
  `JoJos.Bizarre.Adventure.Stardust.Crusaders.S01E##...x265-iAHD`, which
  Sonarr could parse as combined-series Season 2 episodes while the title still
  said `S01`. Do not solve this with a broad custom format, because legitimate
  Stardust Crusaders releases must remain eligible when they are correctly
  labeled as Season 2. The chosen fix was to blocklist only that known bad
  source-title family. `scripts/media-release/sonarr_jojo_stardust_s01_repair.py` added 49
  matching Sonarr blocklist rows via the local SQLite database after Sonarr's
  blocklist API returned `405` for this insert path, deleted the confirmed wrong
  Season 1 imports for S01E23/S01E24, and queued fresh Season 1/2 searches.
  Existing bad queue rows had to be cleaned separately because adding blocklist
  entries does not purge already-tracked downloads. Direct SAB history cleanup
  handled the first stale completed jobs, then
  `scripts/media-release/sonarr_blocklist_queue_matches.py JoJo --apply
  --no-remove-from-client --no-blocklist` removed the remaining stale Sonarr
  queue records after inspection. Final verification showed
  `desired_missing_blocklist: 0`, `existing_matching_blocklist: 49`,
  `wrong_season_one_files: []`, zero matching bad queue rows, and Season 1
  S01E23/S01E24 missing and monitored for replacement. The legitimate hchcsen
  `S02` Stardust Crusaders DA Bluray HEVC pack remained queued/downloading at
  score `144800`.

## Download Client Metadata Stamping

`playbooks/media/media-release-stamper.yml` manages a conservative metadata stamper
for SABnzbd and qBittorrent on `docker-vm`.

- qBittorrent script: `/opt/media-stack/qbittorrent/scripts/qbit-release-stamper.py`
- qBittorrent env: `/opt/media-stack/qbittorrent/scripts/qbit-release-stamper.env`
- qBittorrent hook: `/usr/bin/python3 /config/scripts/qbit-release-stamper.py --hash "%I" --name "%N" --category "%L"`
- SABnzbd script: `/opt/media-stack/sabnzbd/scripts/sab-release-stamper.py`
- SABnzbd script directory: `scripts`
- SABnzbd categories using the stamper: `shows`, `movies`
- Stamper env files are owned by UID/GID `1000` with mode `0600`, matching the
  media containers' `PUID=1000` / `PGID=1000`. Root-only env files cause
  qBittorrent completion hooks to fail with `Permission denied`.

The qBittorrent script runs when a torrent finishes. It looks up the finished
torrent through the qBittorrent Web API, iterates each video file, and renames
individual payload files through qBittorrent's `renameFile` API. Do not replace
this with direct filesystem renames, because direct renames can break seeding or
hash-check state.

The SABnzbd script runs as a normal post-processing script for media
categories. Usenet payloads are not seeded, so it renames completed files
directly before Sonarr/Radarr import them.

Stamping rules:

- Language-combo tags are file-by-file only. The scripts parse individual
  MKV/MP4 audio-track language metadata and require English plus the configured
  original language. qBittorrent first tries optional Sonarr/Radarr queue lookup
  by torrent hash/download ID; SABnzbd tries optional Sonarr/Radarr queue lookup
  by release/job title. If Arr lookup fails, times out, or finds no match, both
  scripts fall back to the configured default `jpn`, so `eng+jpn` becomes
  `[JA+EN]` and `eng+kor` gets no language-combo tag. A release/job/torrent
  title saying `Dual-Audio` is not enough by itself.
- `[x265]` is file-by-file only. The scripts scan the individual video file for
  HEVC markers (`V_MPEGH/ISO/HEVC`, `hvc1`, `hev1`, `x265`, `HEVC`) and MKV
  video-track `CodecID` data, and only stamp that specific file when the
  payload itself looks like HEVC.
- Mixed or mislabeled packs should not be bulk-labeled. Each video file must
  qualify for each tag independently.
- Exact per-series/per-movie original-language matching depends on optional
  Sonarr/Radarr context. That context is an enhancement, not a dependency; if
  Sonarr/Radarr is down, download completion must continue and use the safe
  fallback language.
- The scripts are intentionally non-fatal. If stamping fails, they log the
  error and exit successfully so they do not block SABnzbd or qBittorrent
  completion/import flows.

Verification on 2026-05-22:

- qBittorrent preferences showed `autorun_enabled=True` and the managed
  completion hook above.
- SABnzbd config showed `script_dir=scripts`, with `shows` and `movies` using
  `sab-release-stamper.py`.
- qBittorrent dry-run against `[EMBER] Jujutsu Kaisen S03E11 ... Dual Audio
  HEVC ...` reported a single candidate rename from `[EMBER] Jujutsu Kaisen S3
  - 11.mkv` to `[EMBER] Jujutsu Kaisen S3 - 11 [JA+EN] [x265].mkv`.
- qBittorrent fallback test with `SONARR_API` and `RADARR_API` pointed at a
  dead local port logged both optional lookup failures, fell back to `jpn`, and
  still completed the dry run.
- SABnzbd temp-file test renamed `Episode.mkv` to `Episode [x265].mkv` when the
  fake payload contained only an HEVC marker and no DA audio metadata, confirming
  title text alone does not add a language-combo tag.
- Local predicate test confirmed `eng+kor` does not get a tag under the `jpn`
  fallback, `eng+kor` with Korean as the expected original language becomes
  `[KO+EN]`, and `eng+jpn+kor` with Japanese as the expected original language
  becomes `[JA+KO+EN]`.
- The deployed qBittorrent stamper env sets `DA_ORIGINAL_LANGUAGES=jpn`. That
  prevents an `eng+kor` file from being tagged as DA-compatible for a
  Japanese-original series.

Additional grab/import parity rules added on 2026-05-23:

- Platform/source tags such as `[CR]`, `[NF]`, `[DSNP]`, `[AMZN]`, `[FUNi]`,
  `[ADN]`, `[HULU]`, and similar service tags are release-context tags. They
  may be copied from the parent release/job/torrent title to each video payload
  filename when the payload name is missing them. The scripts deliberately do
  not copy generic `WEB`, `BD`, resolution, or quality tags this way.
- Release-group context is also preserved from the parent title when possible.
  A parent title like `[EMBER] ...` or `...-NTb` can cause a missing payload
  filename to receive `-EMBER` or `-NTb` before import. If the payload already
  starts with `[EMBER]` or ends in `-EMBER`, the scripts do not duplicate it.
- DA and x265 remain stricter than release context: a parent title saying
  `Dual-Audio` or `HEVC` is not enough by itself to stamp `[JA+EN]` or
  `[x265]`. Those still require per-file media inspection.
- Existing-tag checks use the payload basename only. qBittorrent paths include
  the parent torrent directory, and that directory can contain `x265`, service
  tags, or release-group text that is missing from the actual payload filename.
- If `ffprobe` is available where the script runs, it is used as an
  audio-language fallback before the lightweight MKV/MP4 parser. This is
  especially useful for SABnzbd, which runs on the media-vm host and has
  `/usr/bin/ffprobe`.
- If optional Sonarr context is available and a TV payload basename starts with
  only a bare episode token such as `S01E01-...`, the scripts prefix the
  canonical Sonarr series title before adding tags. Example:
  `S01E01-Title [JA+EN].mkv` becomes
  `Welcome to Demon School! Iruma-kun - S01E01-Title [JA+EN] [x265] -EMBER.mkv`.
  This is intentionally narrow: it fixes packs where Sonarr ignores the parent
  torrent/job folder during import, but it does not rewrite arbitrary filenames
  or invent DA/x265 evidence.
- The intended result is that Sonarr's search-time custom-format score and its
  import-time custom-format score are based on the same practical evidence.
  For example, a parent release `[EMBER] Example S01 1080p NF HEVC
  [Dual-Audio]` with a generic payload `Example - 01.mkv` can import as
  `Example - 01 [JA+EN] [x265] [NF] -EMBER.mkv` only when that individual file
  actually has qualifying audio tracks and HEVC markers.
- Live deployment backups from this rollout are under
  `/opt/media-stack/arr-policy-backups/`:
  `20260523T220942Z-release-stamper-v2`,
  `20260523T222640Z-release-stamper-pre-codec-parser`,
  `20260523T223520Z-release-stamper-pre-basename-fix`, and
  `20260523T224208Z-release-stamper-pre-ffprobe-fallback`,
  `20260523T225125Z-release-stamper-pre-title-prefix`. Clean these up after
  the new stamper behavior has survived normal search/import traffic.

## Profilarr Evaluation

Profilarr is being evaluated as both a profile/CF manager and the proactive
library-upgrade scheduler. Do not treat it as only a Recyclarr replacement.

Current reasons to evaluate it:

- The GitHub project advertises Profilarr v2 as a configuration-management
  platform for Radarr/Sonarr. The latest observed release was `v2.0.4` on
  2026-05-20.
- Its README describes support for linked databases, quality-profile
  simulation, custom-format testing, sync, scheduled jobs, and local
  customization.
- Its upgrade system runs scheduled jobs with filters, selectors, cooldown tags,
  dry runs, and live searches.
- Current Profilarr source shows Sonarr live upgrades triggering `SeriesSearch`
  one series at a time, while Radarr uses movie search batches. That matches the
  intended workflow better than episode-level search churn.
- Current Profilarr source and the deployed `/app/server.js` both show Arr
  command waiting hard-capped at 60 minutes. The public issue tracker did not
  show a confirmed Sonarr `SeriesSearch` timeout issue or a documented timeout
  setting during the 2026-05-24 check. Related Profilarr issue
  <https://github.com/Dictionarry-Hub/profilarr/issues/616> and PR
  <https://github.com/Dictionarry-Hub/profilarr/pull/617> cover a different
  Radarr library-fetch timeout, not the Sonarr command wait. Open issue
  <https://github.com/Dictionarry-Hub/profilarr/issues/398> tracks future
  adaptive backoff for upgrade filters, but it is not a current fix for
  long-running Sonarr `SeriesSearch` waits.
- Dumpstarr is a community-maintained database intended for Profilarr and
  advertises Radarr/Sonarr-tested custom formats and profiles.

Decision rule:

1. Deploy Profilarr without live upgrade jobs first.
2. Link existing Sonarr/Radarr instances and run dry-run upgrade filters before
   enabling live searches.
3. Export or preview Profilarr/Dumpstarr output before touching live profiles.
4. Count custom formats before import; do not exceed the Sonarr/Radarr CF limit.
5. Compare Profilarr's anime scoring against the verified math in this document.
6. Preserve DA-first, quality-rank-second behavior unless the user explicitly
   changes the policy.
7. Keep Recyclarr until Profilarr has been tested against real queue/history
   examples and rollback is clear.
8. Profilarr native scheduled Arr upgrades should stay disabled. Overnight
   proactive upgrades are triggered by `playbooks/media/nightly-media-maintenance.yml`
   only when no mergerfs balance job is pending for that night. If future live
   runs expose bad grabs, fix the Sonarr/Radarr scoring, import metadata, or
   parsing cause rather than relying on cleanup-only handling.

Current deployed state on 2026-05-22:

- Profilarr was bootstrapped through HTTP form/API calls, not the browser UI.
  The originally expected `/root/profilarr-admin.initial-password` file was
  not present during the 2026-05-26 check, so do not assume that path still
  contains the login password.
- `Sonarr` and `Radarr` are registered in Profilarr using docker-vm-local
  service URLs and the public external URLs.
- Upgrade scheduler configs are currently disabled and should stay disabled.
  Sonarr has one cutoff-unmet monitored-series filter (`count: 1`), and Radarr
  has one cutoff-unmet monitored-movies filter (`count: 5`). The nightly media
  maintenance coordinator queues controlled hourly `arr.upgrade` jobs from
  midnight through 6 AM only when no balance job is pending for that night.
- On 2026-05-22, live scheduled upgrades were briefly enabled, queued one
  Sonarr run and one Radarr run for 23:00 UTC, and were disabled again after a
  Sonarr manual dry run selected `Bleach` but timed out while fetching release
  candidates. The queued scheduled runs were cancelled because Sonarr still had
  a large warning-state queue.
- Later on 2026-05-22, Sonarr's queue was cleaned without blocklisting. Before
  removal, the queue had 532 records across 71 unique downloads: 80 completed
  records were import-blocked/import-pending by explicit Sonarr rejection
  messages, and the 452 downloading records mapped to 51 qBittorrent torrents
  that were all `stalledDL` with zero active download speed. Removal used the
  Sonarr queue API with `removeFromClient=true`, `blocklist=false`, and
  `skipRedownload=true`; the verified Sonarr queue count afterward was zero.
- Radarr's queue was also cleaned without blocklisting. It had 6 queue records,
  all non-upgrades, manual-import leftovers, or failed items. Removal used the
  Radarr queue API with `removeFromClient=true`, `blocklist=false`, and
  `skipRedownload=true`; the verified Radarr queue count afterward was zero.
- After both queues were clean, Profilarr scheduled upgrades were temporarily
  re-enabled on 2026-05-22 for testing. They were later parked again and then
  replaced by the nightly media maintenance coordinator so storage balance jobs
  and Profilarr upgrades cannot race for the same overnight window.
- Profilarr's local container build hard-codes Arr command waiting to 60
  minutes in `/app/server.js` (`MAX_TIMEOUT_MS = 3600 * 1000`). On
  2026-05-23, Sonarr upgrade runs failed after Profilarr waited 60 minutes for
  a long Sonarr `SeriesSearch` command (`Command 560787 timed out after 60
  minutes`). This is not currently exposed in the Profilarr compose/template as
  a normal setting. Do not patch `/app/server.js` in-place unless the user
  explicitly approves an update-fragile local workaround.
- Follow-up verification on 2026-05-24 found no `TIMEOUT`, `UPGRADE`,
  `COMMAND`, `POLL`, or `SEARCH` environment variable in the Profilarr
  container that controls this wait. The deployed source has
  `waitForCommand(commandId)` using `MAX_TIMEOUT_MS = 3600 * 1000`, and Sonarr
  live upgrades call `sonarr.searchSeries(item.id)` followed by
  `sonarr.waitForCommand(cmd.id)`.
- Supported upgrade-filter knobs are still useful, but they do not extend the
  60-minute command wait. Selectors include `random`, `oldest`, `newest`,
  `lowest_score`, popularity, and alphabetical modes. Sonarr filters can use
  fields such as `season_count` and `episode_count`, but Profilarr currently
  normalizes Sonarr series `score` to `0` and `cutoff_met` to `false`, so
  `lowest_score` and the `cutoff_met=false` rule cannot truly rank Sonarr
  series by current episode custom-format score.
- On 2026-05-24, the Sonarr Profilarr filter was changed from selector
  `oldest` to `random` with backup
  `/opt/profilarr/config/data/backups/profilarr-pre-sonarr-upgrade-strategy-20260524T192516Z.db`.
  The filter remains enabled inside the disabled upgrade config with `count=1`;
  this is not a patch and does not reduce Profilarr's per-run search count. It
  prevents a single old series whose `SeriesSearch` runs longer than an hour
  from being the deterministic next target every run.
- Live status at 2026-05-24 19:25 UTC: Profilarr had one Sonarr upgrade job
  running and one Radarr upgrade job queued. Recent Sonarr upgrade failures were
  `Command 561401 timed out after 60 minutes` and then `Command 561401
  disappeared`; the active Sonarr command was `SeriesSearch` for KonoSuba
  series id `10`, processing `1322` release candidates. Radarr upgrade runs
  were succeeding.
- On 2026-05-24, after a media-vm VirtioFS hang/restart and resource-contention
  review, Profilarr scheduled Arr upgrades were disabled again and queued
  scheduled `arr.upgrade` jobs were cancelled. Database auto-pull/sync remains
  enabled so Profilarr can still refresh upstream PCD data without launching
  proactive Sonarr/Radarr searches. Rollback backup:
  `/opt/profilarr/config/data/backups/profilarr-pre-disable-upgrade-jobs-20260524T225353Z.db`.
- Later on 2026-05-24, `playbooks/media/nightly-media-maintenance.yml` became the
  owner for overnight proactive upgrade launches. It keeps native Profilarr Arr
  scheduling disabled, queues explicit `arr.upgrade` jobs during midnight-7 AM
  windows when no balance job is pending, and reserves the whole night for
  storage if any queued mergerfs balance job exists.
- First `scripts/media-release/sonarr_transaction_audit.py --hours 2 --limit 8` run after
  monitor deployment skipped `10000` bootstrap history records and showed `11`
  real post-monitor events: `grabbed=10`, `downloadFolderImported=1`. The live
  queue was `203` records across `59` download groups with no
  `current_file_score_higher` groups; the main current blockers were Bleach
  Judas packs rejected by parent-folder/title mismatch and JoJo Stardust
  Crusaders SAB leftovers rejected by Sonarr/XEM season-number mapping.
- NZBFinder was left enabled after its `5000/5000` quota exhaustion warning.
  Prowlarr's temporary disabled-until cooldown is expected in that state and is
  not a reason to remove or park the indexer.
- The official Profilarr API exposes read/status/job/database endpoints, while
  Arr creation and upgrade-config saves are currently SvelteKit form actions
  (`/arr/new` and `/arr/<id>/upgrades?/save`). Treat those as authenticated
  HTTP endpoints when automating setup.

Reference links:

- <https://github.com/Dictionarry-Hub/profilarr>
- <https://github.com/Dictionarry-Hub/profilarr/releases>
- <https://github.com/Dictionarry-Hub/profilarr/blob/33d73a36de8206e79928ecb1ed82556875206b1c/src/lib/server/utils/arr/base.ts>
- <https://github.com/Dictionarry-Hub/profilarr/blob/33d73a36de8206e79928ecb1ed82556875206b1c/src/lib/server/upgrades/processor.ts>
- <https://www.dumpstarr.dev/>
