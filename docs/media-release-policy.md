# Media Release Policy

Last updated: 2026-06-05

This documents the current Sonarr/Radarr release selection policy on `docker-vm`.
The goal is better grabbed releases, not just smaller files. Anime is handled as
a separate policy because dual audio is the highest priority there.

## Managed Systems

- Sonarr regular efficient profile: `shows-regular-efficient` id `1`
- Sonarr non-English regular dual-audio efficient profile:
  `shows-regular-dual-audio-efficient` id `13`
- Sonarr anime efficient profile: `shows-anime-efficient` id `7`
- Radarr regular efficient profile: `movies-regular-efficient` id `6`
- Radarr non-English regular dual-audio efficient profile:
  `movies-regular-dual-audio-efficient` id `12`
- Radarr anime efficient profile: `movies-anime-efficient` id `7`
- Frozen legacy/balanced profiles:
  - Sonarr: `shows-regular-balanced` id `11`
  - Sonarr: `shows-anime-balanced` id `12`
  - Radarr: `movies-regular-balanced` id `10`
  - Radarr: `movies-anime-balanced` id `11`
- The retired Radarr `[Don't Use]` profile id `1` was deleted on 2026-06-03
  after all movie and collection references were moved to
  `movies-regular-efficient`. Do not recreate parked request-visible profiles;
  use efficient profiles for active defaults and balanced profiles only as
  inactive policy comparison targets.
- Media stack: `/opt/media-stack` on `docker-vm`
- Recyclarr: disabled and removed from the active media-stack compose service
  list on 2026-05-27; its old config directory may remain on disk as a
  rollback artifact, but no container or scheduled sync should run
- Profilarr stack: `/opt/profilarr` on `docker-vm`, published at
  `profilarr.jnalley.me`
- Seerr stack: `/opt/seerr` on `docker-vm`, published at
  `requests.jnalley.me`; Sonarr entries point at `sonarr:8989`, Radarr entries
  point at `radarr:7878`, and request defaults use the efficient profiles
- Profilarr candidate/test profiles: absent after the 2026-05-27 promotion.
  Recreate them only through the repo-managed staging/import scripts when a new
  candidate policy needs review.
- Release metadata stamper: `playbooks/media/media-release-stamper.yml`
- Sonarr grab/import forensics: `scripts/media-release/sonarr_grab_forensics.py`
- Radarr grab/import forensics: `scripts/media-release/radarr_grab_forensics.py`
- Sonarr transaction audit report: `scripts/media-release/sonarr_transaction_audit.py`
- Arr duplicate media audit: `scripts/media-release/arr_duplicate_media_audit.py`
- Sonarr targeted queue blocklist/removal helper:
  `scripts/media-release/sonarr_blocklist_queue_matches.py`
- Sonarr JoJo Stardust arc-local repair helper:
  `scripts/media-release/sonarr_jojo_stardust_s01_repair.py`
- Arr profile classification audit/repair:
  `scripts/media-release/arr_profile_classification.py`
- Sonarr transaction monitor: `sonarr-transaction-monitor.timer` writes
  `/var/log/sonarr-transaction-monitor/events.jsonl`, rotated daily
- Sonarr recycle bin: disabled
- Radarr recycle bin: disabled
- Media-stack container library bind: `/srv/media/plex:/data`, backed by the single
  `/srv/media` NFS parent mount from TS440. Completed downloads and libraries
  stay under `/data` inside the containers so hardlinks still work.

Recyclarr is no longer part of the active release-policy path. Local custom
formats created directly in Sonarr/Radarr are still valid, but they must be
documented here. Profilarr-backed repo scripts are now the controlled path for
pulling upstream CF definitions into Arr while preserving local scoring,
quality groups, cutoffs, DA/x265 behavior, and the CF limit.

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

These values apply to both Sonarr and Radarr for matching qualities. No active
sync tool should own `Quality Definition` changes; if a future profile manager
tries to change them, stop and reconcile this local policy first.

## Anime Priority Order

Anime scoring is intentionally wide-band so the important choices cannot be
overridden by incidental format bonuses.

1. Hard rejects: `-1000000`
2. Dual audio: `+100000`
3. Quality rank: `+10000`, `+20000`, `+30000`, `+40000`
4. x265/HEVC preference: efficient profiles `+5000`
5. Release-group tiers: bounded Profilarr/Dictionarry primary tiers and TRaSH
   fallback tiers below x265
6. Service/source tags: ordered tie-breakers below the lowest tier gap
7. Soft avoids: small negative values only

This means any acceptable dual-audio release beats a non-dual-audio release,
but within dual audio, a higher enabled quality still beats a lower quality even
when the lower quality has x265 and a better release group.

## Non-English Regular Dual Audio

English-original regular shows and movies stay on `shows-regular-efficient` or
`movies-regular-efficient`; those profiles intentionally score `Regular Dual
Audio` at `0` so a show such as Family Guy does not prefer unrelated multi-audio
releases over normal English releases.

Radarr English-original regular movies also score
`Regular English - Foreign/Multi Audio Guard` at `-100000` on
`movies-regular-efficient` only. This is a title-side block for explicit
foreign/multi-audio release markers such as `German.DL`, `FRENCH.DL`,
standalone `DL.1080p`-style markers, `multi-audio`, `multi-language`,
`VOSTFR`, or technical `DUAL.COMPLETE.BLURAY` / quality-tagged `DUAL` markers.
It exists because Radarr can parse those releases as English when the title
still clearly says the release is foreign-first or multi-audio. The guard stays
at `0` on anime and `movies-regular-dual-audio-efficient` so non-English
original-language+English movies are not penalized.

Non-English regular shows/movies that should prefer original-language+English
audio use the separate `shows-regular-dual-audio-efficient` or
`movies-regular-dual-audio-efficient` profiles. These are cloned from the
regular efficient profiles, then add a parsed-language `Regular Dual Audio`
custom format at `+100000`. That custom format requires both Sonarr/Radarr's
dynamic `Original` language and `English` language metadata, rather than only a
release-title marker. This keeps original-only releases acceptable when no dub
exists, but makes original+English beat original-only x265 when both are
available.

Current live assignment after the 2026-05-31 sweep:

- Sonarr `shows-regular-dual-audio-efficient`: 3 series
- Radarr `movies-regular-dual-audio-efficient`: 19 movies

Seerr defaults remain on `shows-regular-efficient`, `shows-anime-efficient`,
`movies-regular-efficient`, and `movies-anime-efficient`; the dual-audio
regular profiles are for explicit non-English media assignments, not default
user requests.

The profile creation/update helper is
`scripts/media-release/arr_regular_dual_audio_profiles.py`. The retained live
rollback backup for the 2026-05-31 rollout is
`/opt/media-stack/arr-policy-backups/20260531T051612Z-regular-dual-audio-profiles`.
Dry-run backups from that rollout were removed after validation.

The Radarr English-original foreign/multi-audio guard helper is
`scripts/media-release/radarr_regular_english_language_guard.py`. It snapshots
Radarr custom formats, quality profiles, media-management config, queue status,
and command state before applying. The retained live rollback backups for the
2026-05-31 guard rollout are
`/opt/media-stack/arr-policy-backups/20260531T214817Z-radarr-regular-english-language-guard`
and
`/opt/media-stack/arr-policy-backups/20260531T215012Z-radarr-regular-english-language-guard`.

## Profile Classification

All existing Sonarr/Radarr library items should stay on the expected efficient
profile class:

- Anime series and movies: `shows-anime-efficient` or
  `movies-anime-efficient`
- English-original regular series and movies: `shows-regular-efficient` or
  `movies-regular-efficient`
- Non-English non-anime regular series and movies:
  `shows-regular-dual-audio-efficient` or
  `movies-regular-dual-audio-efficient`

The classifier treats Sonarr `seriesType=anime`, an `Anime` genre, or a
Japanese-language Radarr movie with `Animation` genre as anime. That keeps
Japanese animated films such as Ghibli movies on the anime movie profile while
leaving live-action Japanese movies such as `Shin Godzilla` on the non-English
regular dual-audio profile.

Run this read-only audit after profile migrations or library-wide sweeps:

```bash
ansible docker-vm -b -m script -a "scripts/media-release/arr_profile_classification.py --no-backup"
```

When the dry-run output is correct, apply and queue searches for the changed
items:

```bash
ansible docker-vm -b -m script -a "scripts/media-release/arr_profile_classification.py --apply --search-changed"
```

The 2026-05-31 profile-classification repair moved 8 Japanese animated Radarr
movies from `movies-regular-efficient` to `movies-anime-efficient` and queued
movie searches for each. The retained live rollback backup is
`/opt/media-stack/arr-policy-backups/20260531T052016Z-profile-classification`.
The dry-run backup from that repair was removed after validation.

The 2026-06-03 Radarr cleanup moved `Captain America: The First Avenger` and
`Captain America: The Winter Soldier` from `[Don't Use]` to
`movies-regular-efficient`, then retargeted 10 Radarr collections from profile
id `1` to `movies-regular-efficient` before deleting the retired profile. The
retained live rollback backups are
`/opt/media-stack/arr-policy-backups/20260604T021703Z-profile-classification`
and
`/opt/media-stack/arr-policy-backups/20260604T021951Z-radarr-profile-id-1-retire`.

## Quality Rank

Sonarr `shows-anime-efficient` enabled qualities are grouped together so upgrades are
driven by custom-format scores instead of Sonarr's native quality order.

- `Local Quality Rank - 480p`: `+10000`
- `Local Quality Rank - 576p`: `+20000`
- `Local Quality Rank - 720p`: `+30000`
- `Local Quality Rank - 1080p`: `+40000`

Radarr `movies-anime-efficient` currently only enables 720p and 1080p movie
qualities.

- `Local Quality Rank - 720p`: `+30000`
- `Local Quality Rank - 1080p`: `+40000`

These are generic resolution custom formats, not anime-specific matchers. They
are shared by anime and regular efficient profiles so custom-format math can
rank enabled qualities consistently without spending extra CF slots.

## Anime Source Rank

`Local Anime Source Rank - Bluray` is zero in the efficient profiles. The
balanced profiles are inactive parking profiles for future policy experiments.
The efficient policy should not use a broad local Bluray source bonus, because
it can make a
same-resolution DA Bluray release beat a same-resolution DA WEB release even
when WEB has stronger release-tier, service, or codec evidence. The custom
format row may still be visible in Arr profile pages because Sonarr/Radarr
require all custom formats to be present in `formatItems`; only the nonzero
score matters.

Do not add new local CFs casually. The custom-format limit matters. Current
counts after the bounded Profilarr tier test staging are Sonarr `96` and
Radarr `79`; the working limit for staging checks is `100`.

The audit script `scripts/media-release/arr_release_policy_audit.py` checks
current CF counts, profile scores, queue status, and unused/all-zero CFs.
`scripts/media-release/arr_profile_math_audit.py` checks the efficient profiles
as a whole: DA beats all non-DA paths, x265 stays above tier and
service/repack stacking, quality-rank scores beat lower-quality x265+tier
stacks, 1080p DA beats any 720p DA stack, best Bluray HEVC and best WEB HEVC
Dictionarry stacks are source-ordered, service and repack CFs stay below the
smallest release-tier gap, Profilarr-synced TRaSH fallback tiers have only the
expected bounded scores, no unexpected legacy tier score remains, and the CF
limit is still obeyed.
`scripts/media-release/arr_profile_assignment_check.py` verifies that all
Sonarr/Radarr media assignments and Seerr request defaults use only efficient
profiles and fails if balanced, test, old, or unknown profile names appear.

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
queue snapshots to `/var/log/sonarr-transaction-monitor/events.jsonl`. It also
records Sonarr and Radarr storage snapshots every 15 minutes by default. Sonarr
uses series statistics for total bytes/file counts plus root/profile buckets;
Radarr includes total bytes/file counts plus quality/codec/root/profile buckets.
That is enough to check whether x265 upgrade passes are moving real library
size instead of relying on release names. The log is mode `0640`, rotated daily
with 90 retained rotations, and must not store raw indexer/API URLs or API keys.
Keep it enabled while Profilarr upgrade searches are active so later reviews can
compare grab-time, queue-time, import/delete, and storage outcomes without
relying on memory. If an older log needs redaction, use
`scripts/media-release/sonarr_transaction_log_sanitize.py`.

`scripts/media-release/arr_duplicate_media_audit.py` is the read-only duplicate
media check. Run it on `docker-vm` to compare Sonarr/Radarr tracked file paths
against the visible `/srv/media/plex` library, including untracked files in
series/movie folders and parsed duplicate episode keys. Run it on the NAS host
with `--mode branch` to scan the underlying mergerfs branch roots for hidden
same-relative-path duplicates and parsed episode duplicates that the union mount
may mask. Cleanup is opt-in with `--apply-delete`; it writes a JSON manifest
before unlinking files and only targets generated cleanup candidates: untracked
Arr-visible duplicate files with a tracked file for the same episode/movie, or
hidden same-relative-path branch duplicates with matching file sizes. The
Arr-visible cleanup path is conservative: it skips candidates that appear to
have higher resolution, higher source rank, x265/HEVC, or dual-audio signals
that the tracked comparator lacks. Because `docker-vm` currently does not have
`ffprobe`/`mediainfo` available for hidden audio-track verification, it also
skips candidates with unknown title-side audio-language markers when the
tracked file has explicit language markers.

`scripts/media-release/sonarr_transaction_audit.py` is the compact report over that monitor
log plus the live Sonarr queue. It summarizes recent history event types,
queue-count movement, storage-size deltas, recent grabbed/imported/deleted
groups, release-stamper events, and the current queue's grouped
classifications. The monitor and audit report also flag low-confidence release
scoring with `riskFlags`: `tierless_x265` means an x265/HEVC release did not
match any release-tier CF, `release_group_unranked` means the title appears to
name a release group but no tier CF matched it, and `bare_quality_x265` means
the effective CF set is only local quality/source rank plus x265. Treat those
as review prompts, not automatic rejection reasons; they are meant to catch
cases such as 1080p+x265-only grabs that may be winning despite lacking release
group confidence. Use it for periodic Profilarr review:

```bash
ansible docker-vm --become -m script -a "scripts/media-release/sonarr_transaction_audit.py --hours 24 --limit 25"
```

`media-stack-health.timer` on `docker-vm` is the alert-only storage/import
sentinel for the Arr/download stack. It must not pause Profilarr, stop
searches, delete queue rows, or mutate Arr/qBittorrent state. In addition to
container, endpoint, hardlink, port-sync, and import-copy checks, it now alerts
on repeated docker-vm NFS `fileid changed` kernel errors, media probe processes
such as Arr `ffprobe` stuck in `D` state beyond the configured age threshold,
and Sonarr/Radarr commands that remain active or queued beyond the configured
stale thresholds. These checks are intentionally thresholded so short normal
NFS reads and active search bursts do not become automatic mitigation events.

Long-term docker-vm NFS reliability is still a storage configuration issue, not
a queue-cleanup issue. On 2026-06-03 and 2026-06-04, docker-vm repeatedly
logged `NFS: server 192.168.1.146 error: fileid changed` while Radarr import
scans touched the TS440 `/srv/media` mergerfs export. TS440 owns the single
mergerfs pool, docker-vm keeps the Arr stack, and media-vm keeps Plex.
`inventory/group_vars/nas_server/mergerfs.yml` manages the NFS-safe mergerfs
options `noforget`, `use_ino`, and `inodecalc=path-hash` for that export.
Applying changes to those mount options requires a planned TS440 mergerfs
remount, so treat it as Plex-impacting until proven otherwise.

`scripts/media-release/arr_stage_profilarr_test_profiles.py` snapshots live Arr policy state
and creates or refreshes future Profilarr test profiles by cloning the current
efficient anime profiles. It does not assign any series or movies to the test
profiles. It refuses to stage if the live CF count exceeds the configured CF
limit.

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

Sonarr `shows-anime-efficient` hard rejects:

- `Anime LQ Groups`
- `Anime Raws`
- `LQ`
- `LQ (Release Title)`
- `Local Anime Raw Group - DBD-Raws`
- `Portuguese (No English)`
- `Dubs Only (Block)`
- `UHD 2160p - Non-Dual (Block)`
- `2160p`

Radarr `movies-anime-efficient` hard rejects:

- `Anime LQ Groups`
- `Anime Raws`
- `LQ`
- `LQ (Release Title)`
- `No ISO`

## Anime Soft Avoids

Soft avoids are deliberately small. A soft avoid must not allow a lower-quality
dual-audio release to beat a higher-quality dual-audio release.

Sonarr `shows-anime-efficient` soft avoids:

- `AV1`: `-2000`
- `No AV1`: `-2000`
- `Language - Not Original`: `-1000`
- `No German Audio`: `-500`

Radarr `movies-anime-efficient` soft avoids:

- `AV1`: `-2000`
- `Language - Not Original`: `-1000`

`Language - Not Original` must not be a hard reject for anime because it can
match releases that are otherwise valid dual audio. The dual-audio CF is the
source of truth for anime language preference.

## Verified Efficient Score Math

The efficient profile verification targets are:

- `720p DA + x265 + max release stack`: `100000 + 30000 + 5000 + 1982 = 136982`
- `1080p DA`: `100000 + 40000 = 140000`
- `1080p DA + x265 + max release stack`: `100000 + 40000 + 5000 + 1982 = 146982`
- `Max non-DA 1080p path`: `40000 + 5000 + 1982 = 46982`
- `Bare 1080p rank`: `40000`, which still beats any regular 720p path
  (`30000 + 5000 + 1982 = 36982`)

The live Sonarr check on 2026-05-27 confirmed:

- `shows-anime-efficient` has one native quality group named `Anime Enabled Qualities`.
- That group covers the enabled anime resolutions `480`, `576`, `720`, and
  `1080`.
- `Anime Dual Audio` is scored `+100000`; `x265` is scored `+5000`.
- `Local Anime Source Rank - Bluray` is scored `0`.
- Lowest enabled DA quality beats strongest single-tier non-DA:
  `110000 > 46979`.
- `1080p DA` beats `720p DA + x265 + top stack`: `140000 > 136979`.
- Sonarr renaming is enabled, and the anime rename format includes both
  `{MediaInfo AudioLanguages}` and `{MediaInfo VideoCodec}`.
- Series profile distribution was `shows-anime-efficient: 151` and
  `shows-regular-efficient: 70`, with no series on balanced or test profiles.

The live Radarr check on 2026-05-27 confirmed:

- `movies-anime-efficient` has one native quality group named `Anime Enabled Qualities`.
- That group covers the enabled anime movie resolutions `720` and `1080`.
- `Anime Dual Audio` is scored `+100000`; `x265 (HD)` is scored `+5000`.
- `Local Anime Source Rank - Bluray` is scored `0`.
- Lowest enabled DA quality beats strongest single-tier non-DA:
  `130000 > 46979`.
- `1080p DA` beats `720p DA + x265 + top stack`: `140000 > 136978`.
- `x265 (HD)` matches HD HEVC/x265 but excludes `2160p`.
- Radarr renaming is enabled, and the movie rename format includes both
  `{MediaInfo AudioLanguages}` and `{MediaInfo VideoCodec}`.
- Movie profile distribution was `movies-anime-efficient: 32` and
  `movies-regular-efficient: 251`, with no movies on balanced or test profiles.
- Radarr queue status was empty: `totalCount=0`.

After soft avoids:

- Sonarr `1080p DA` with stacked soft avoids: `134500`
- Radarr `1080p DA` with stacked soft avoids: `137000`

Both still beat `720p DA + x265 + best group`.

With a hard reject:

- `1080p DA + hard reject`: `-860000`

That is below the minimum score and should not be eligible.

## Regular Profiles

The active regular TV/movie profiles are now `shows-regular-efficient` and
`movies-regular-efficient`. They use the same native-quality strategy as anime:
every enabled quality is grouped into `Regular Enabled Qualities`, then
the generic `Local Quality Rank - ...` CFs provide the resolution order. This
lets x265/HEVC and release-tier custom formats matter across source labels
while still keeping the math bounded so a lower resolution with x265 plus the
best tier stack cannot beat a bare higher-resolution rank.

The frozen balanced profiles are parking profiles for future comparison and
custom experimentation after they receive the same efficient-policy treatment.
Do not point users or request defaults at the balanced profiles unless
explicitly testing a different policy.

## Change Procedure

For future release-policy changes:

1. Audit all existing nonzero custom-format scores in the affected profiles.
2. Classify each changed CF as hard reject, major preference, quality rank,
   codec preference, release-group preference, or soft avoid.
3. Check the math against realistic competing releases before applying.
4. Apply live changes with backups.
5. Confirm Recyclarr remains disabled and no scheduled sync can undo the policy.
6. Run Sonarr/Radarr queue/history checks for regressions. Use
   `scripts/media-release/sonarr_grab_forensics.py` and
   `scripts/media-release/radarr_grab_forensics.py` before any cleanup so the
   queue is classified as valid upgrade, payload score loss, pack
   collateral/mapping, or client failure instead of just deleted after
   bandwidth has already been spent. Routine cleanup should remove only safe
   current-better groups after writing a queue snapshot, so mixed packs with
   any still-valid rows stay intact.
7. Update this document and the short README summary in the same change.

Never change a single score band in isolation without checking the rest of the
profile. A score that was safe in a `10000`-point profile may be wrong in the
anime `100000`-point dual-audio model.

## Profilarr Candidate Migration

Current migration posture as of 2026-05-27:

- The accepted Profilarr-derived test policy has been promoted into the
  preserved production profile IDs and renamed with the `-efficient` suffix.
- All Sonarr/Radarr media is assigned to efficient profiles:
  - Sonarr `shows-anime-efficient`: 152 series
  - Sonarr `shows-regular-efficient`: 71 series
  - Sonarr `shows-regular-dual-audio-efficient`: 3 series
  - Radarr `movies-anime-efficient`: 44 movies
  - Radarr `movies-regular-efficient`: 237 movies
  - Radarr `movies-regular-dual-audio-efficient`: 19 movies
- Temporary `*-profilarr-test` profiles were removed after promotion.
- The old production profiles were cloned before promotion and are retained as
  `*-balanced` side profiles. No media should be assigned to balanced profiles.
- Seerr request defaults were updated to the efficient profiles and its Arr
  endpoints were corrected to docker-vm compose DNS (`sonarr:8989` and
  `radarr:7878`) after validation through Seerr's own test API.
- Dictionarry is linked in Profilarr, enabled, and auto-pulls hourly.
- TRaSH Guides is linked in Profilarr from
  `https://github.com/Dictionarry-Hub/trash-pcd`, enabled, and auto-pulls
  hourly. It is now the intended source for TRaSH-equivalent fallback custom
  formats now that Recyclarr is disabled.
- Dumpstarr is linked in Profilarr but currently disabled. Do not use
  disabled/stale PCD sources for production definition sync unless the source
  is explicitly re-enabled and revalidated first.
- Dictionarry primary release-tier custom formats and bounded TRaSH fallback
  tiers have been copied into Arr and scored in the efficient profiles. The old
  balanced profiles are not active assignments and should be treated as future
  experiment slots, not live policy.
- Selected existing Arr CF definitions were safely refreshed from enabled
  Profilarr sources on 2026-05-26. Custom-format definitions are global in
  Sonarr/Radarr, so this can affect matching behavior everywhere; it did not
  touch DA, x265, quality ranks, profile scores, cutoffs, profile structure, or
  media assignments.

The candidate audit found useful material in Dumpstarr and Dictionarry, but
also confirmed that stock Dumpstarr scoring conflicts with this library's codec
policy. Dumpstarr's `TV 1080p` profile scores `x265 (HD)` at `-10000`; this
library wants HD x265/HEVC preferred, with `+5000` in the efficient profiles.
Any future Profilarr
migration must override upstream x265 penalties before assigning real media or
syncing replacement profiles.

Candidate material worth evaluating:

- Updated anime/web/bluray group tiers.
- Baseline group tiers.
- Bad/banned group filters.
- Bad dual-audio group filters.
- Bad source / bad multis / LQ release-title filters.
- Additional Dictionarry tier families such as Balanced, Quality,
  lower-resolution, HDTV, and Remux if they can be mapped without biasing the
  profile toward larger files or weaker source choices.

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

Current Profilarr tier replacement policy:

- Scripts:
  - `scripts/media-release/profilarr_tier_candidate_compare.py`
  - `scripts/media-release/profilarr_cf_definition_sync.py`
  - `scripts/media-release/profilarr_bounded_tier_import.py`
  - `scripts/media-release/arr_profile_math_audit.py`
- Latest dry-run snapshot:
  `/opt/media-stack/release-policy-snapshots/20260527T001506Z-dictionarry-bounded-tiers-dry-run`
- Latest applied snapshot:
  `/opt/media-stack/release-policy-snapshots/20260527T001517Z-dictionarry-bounded-tiers`
- Current CF counts after bounded-tier apply and regular dual-audio profile
  rollout:
  - Sonarr: `97/100`
  - Radarr: `80/100`
- The former test profiles were promoted into:
  - Sonarr `shows-anime-efficient` id `7`
  - Sonarr `shows-regular-efficient` id `1`
  - Radarr `movies-anime-efficient` id `7`
  - Radarr `movies-regular-efficient` id `6`
- Regular efficient quality structure:
  - Sonarr `shows-regular-efficient` groups all enabled regular qualities
    into `Regular Enabled Qualities`; disabled qualities remain outside the
    group.
  - Radarr `movies-regular-efficient` does the same; disabled 2160p movie
    qualities remain disabled and outside the active group.
  - The regular efficient cutoff points at `Regular Enabled Qualities`.
  - Every efficient profile's `cutoffFormatScore` is computed from that profile's
    actual maximum applicable CF path, not just `1080p + x265`.
    Current values are Sonarr anime `146979`, Sonarr regular `46982`, Sonarr
    regular dual-audio `146982`, Radarr anime `146978`, Radarr regular
    `46979`, and Radarr regular dual-audio `146979`.
  - `Local Anime Quality Rank - ...` was only a resolution matcher. It was
    renamed in place to `Local Quality Rank - ...` and reused for anime and
    regular efficient profiles instead of creating duplicate CFs.
- Efficient profiles are in replacement mode, not stacked mode. Dictionarry
  release-group tiers are the primary ranking band. Profilarr-synced TRaSH
  Guides tiers are retained as low-score fallback only when Dictionarry misses.
  Any old release-tier row that is not part of the expected fallback map must
  be zero, because Sonarr/Radarr require every custom format to stay present in
  profile `formatItems`; only nonzero score affects release selection.
- `Local Anime Source Rank - Bluray` is zeroed in the efficient profiles, so
  the replacement does not add a broad local Bluray source preference.
- Imported Sonarr Dictionarry TV tiers:
  - Efficient Bluray Tier 1..6: `+900`, `+820`, `+700`, `+620`, `+540`,
    `+460`
  - Efficient WEB Tier 1..5: `+600`, `+520`, `+440`, `+360`, `+280`
  - Compact Bluray Tier 1..6: `+700`, `+620`, `+540`, `+460`, `+380`, `+300`
  - Compact WEB Tier 1..5: `+440`, `+360`, `+280`, `+220`, `+160`
  - Compact Trash Tier 1..2: `-250`, `-350`
- Imported Radarr Dictionarry movie tiers:
  - Efficient Bluray Tier 1..4: `+900`, `+800`, `+700`, `+600`
  - Efficient WEB Tier 1..4: `+600`, `+500`, `+400`, `+300`
  - Compact Bluray Tier 1..4: `+700`, `+600`, `+500`, `+400`
  - Compact WEB Tier 1..4: `+440`, `+340`, `+240`, `+140`
- Shared imported Dictionarry tiers:
  - `1080p Bluray HEVC Tier 1`: `+280`
  - `1080p WEB-DL HEVC Tier 1`: `+260`
  - `WEB-DL Tier 1..5`: `+320`, `+260`, `+220`, `+180`, `+140`
- Profilarr-synced TRaSH fallback tiers:
  - Anime BD Tier 01..08: `+96`, `+88`, `+80`, `+72`, `+64`, `+56`, `+48`,
    `+40`, anime test profiles only
  - Anime Web Tier 01..06: `+32`, `+24`, `+16`, `+12`, `+8`, `+4`, anime test
    profiles only
  - Sonarr regular WEB Tier 01..03: `+96`, `+88`, `+80`; `WEB Scene`: `+16`
  - Radarr regular HD Bluray Tier 01..03: `+96`, `+88`, `+80`; WEB Tier
    01..03: `+80`, `+72`, `+64`
- Positive service/source tags such as `AMZN`, `NF`, `DSNP`, `CR`, and `VRV`
  are compressed into an ordered tie-breaker ladder in the efficient profiles:
  high-priority positive services become `+3`, mid positives become `+2`, and
  smaller positives become `+1`. Zero-scored service tags stay zero. Repack
  scores are capped to `Repack/Proper=+1`, `Repack2=+2`, and `Repack3=+3`.
  Combined incidental score is therefore at most `+6`, below the smallest
  Dictionarry tier gap.
- Score math:
  - Best Bluray HEVC stack: `900 + 700 + 280 = 1880`
  - Sonarr second Bluray HEVC stack: `820 + 620 + 280 = 1720`
  - Sonarr best WEB HEVC stack: `600 + 440 + 260 + 320 = 1620`
  - Radarr second Bluray HEVC stack: `800 + 600 + 280 = 1680`
  - Radarr best WEB HEVC stack: `600 + 440 + 260 + 320 = 1620`
  - Max fallback score: `+96`
  - Max incidental score: `+6`
  - Max release stack: `1880 + 96 + 6 = 1982`
  - x265/HEVC in the efficient profiles: `+5000`, leaving `3018` points of margin
    over the strongest release-stack path
  - Max non-DA 1080p path: `40000 + 5000 + 1982 = 46982`, still below DA at
    `+100000`
  - Max 720p DA path: `100000 + 30000 + 5000 + 1982 = 136982`, still below
    the 1080p DA floor of `140000`
  - Max regular 720p path: `30000 + 5000 + 1982 = 36982`, still below the
    bare 1080p rank of `40000`; lower regular quality ranks have even more
    headroom.
  - Cutoff scores are set to each profile's actual max applicable score:
    Sonarr anime `100000 + 40000 + 5000 + 1979 = 146979`, Sonarr regular
    `40000 + 5000 + 1982 = 46982`, Sonarr regular dual-audio
    `100000 + 40000 + 5000 + 1982 = 146982`, Radarr anime
    `100000 + 40000 + 5000 + 1978 = 146978`, Radarr regular
    `40000 + 5000 + 1979 = 46979`, and Radarr regular dual-audio
    `100000 + 40000 + 5000 + 1979 = 146979`.
- Source ordering checks deliberately keep WEB below Bluray at the near-tier
  boundary: Sonarr Efficient WEB Tier 1 (`+600`) is below Efficient Bluray Tier
  2 (`+820`), Sonarr Compact WEB Tier 1 (`+440`) is below Compact Bluray Tier
  2 (`+620`), Radarr Efficient WEB Tier 1 (`+600`) is below Efficient Bluray
  Tier 2 (`+800`), and Radarr Compact WEB Tier 1 (`+440`) is below Compact
  Bluray Tier 2 (`+600`).
- Validation after the 2026-05-27 promotion:
  - `scripts/media-release/profilarr_bounded_tier_import.py --dry-run` showed
    no new CFs, planned in-place CF renames, and the regular enabled-quality
    grouping.
  - `scripts/media-release/profilarr_bounded_tier_import.py` applied the same
    changes with the snapshot above.
  - `scripts/media-release/arr_profile_math_audit.py` passed with no failures
    and reported `Regular Enabled Qualities` in both regular efficient profiles.
  - `scripts/media-release/arr_quality_profile_report.py` confirmed the actual
    Sonarr/Radarr efficient-profile quality groups and max-path cutoff scores:
    Sonarr anime `146979`, Sonarr regular `46982`, Sonarr regular dual-audio
    `146982`, Radarr anime `146978`, Radarr regular `46979`, and Radarr regular
    dual-audio `146979`.
  - `scripts/media-release/sonarr_release_expectation_check.py` and
    `scripts/media-release/radarr_release_expectation_check.py` both passed,
    confirming the efficient anime profiles still score DA, x265, and the
    renamed generic quality ranks as expected.
- These scores are intentionally below DA (`+100000`), anime quality ranks, and
  x265/HEVC (`+5000` in the efficient profiles). Dictionarry tiers can stack with
  the low TRaSH fallback tier only inside the proven `1982` release-stack
  ceiling, so they still cannot outrank x265 or collapse the DA/quality bands.
- The bounded-tier import cleanup deletes only all-zero non-rename custom
  formats. It must not delete formats with `includeCustomFormatWhenRenaming`
  enabled, and it protects local helper formats such as DA title/metadata
  helpers, H.265/x265, source rank, hard rejects, soft avoids, and local anime
  quality-rank prefixes.
- Broader Dictionarry tiering is available but deliberately excluded from this
  pass. Balanced, Quality, lower-resolution, HDTV, and Remux families remain
  candidates for later review; do not add them until their scoring can be proven
  not to bias the profile toward larger files or weaker source choices.
- Coverage check from the 2026-05-26 live tier audit: compact-only was narrower
  than the previous tier coverage, which is why this plan now includes
  Efficient, HEVC, WEB-DL, and TRaSH fallback tiers. Sonarr/Radarr anime TRaSH
  anime BD+Web tiers each exposed about `251` release-title/release-group
  patterns; Sonarr regular `WEB Tier 01..03` exposed about `73`; Radarr regular
  `HD Bluray Tier 01..03` plus `WEB Tier 01..03` exposed about `81`. Do not
  treat Dictionarry alone as a full replacement for old tier reach until the
  pilot shows it catches the real releases that matter.
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
  `/opt/media-stack/release-policy-snapshots/20260526T225605Z-profilarr-cf-definition-sync`
- Latest idempotence dry-run snapshot:
  `/opt/media-stack/release-policy-snapshots/20260526T225647Z-profilarr-cf-definition-sync-dry-run`
- Applied from enabled Profilarr sources:
  - Sonarr: `LQ`, `Extras`, `AV1`, `WEB Tier 01`, `Repack2`, `Repack3`,
    `AMZN`, `ATVP`, `CR`, `DSNP`, `HMAX`, `MAX`, `NF`, `PCOK`, `PMTP`, `SHO`,
    `STAN`, `iT`
  - Radarr: `LQ`, `LQ (Release Title)`, `Extras`, `AV1`, `Upscaled`,
    `HD Bluray Tier 01`, `HD Bluray Tier 02`, `HD Bluray Tier 03`, `Repack2`,
    `Repack3`, `AMZN`, `ATVP`, `DSNP`, `HMAX`, `MAX`, `NF`, `PCOK`, `PMTP`,
    `STAN`, `VRV`, `iT`
- Post-apply dry run reported `changed=0` for the safe enabled-source sync.
- Validation after the apply:
  - Sonarr and Radarr DA/x265/quality-rank expectation checks passed for the
    active anime profiles.
  - Efficient-profile math audit passed.
  - CF counts remained Sonarr `96/100`, Radarr `79/100`.

Profilarr remains the upstream refresh source for imported CFs, but Profilarr
itself is not directly managing the copied Arr formats yet. The sync path is:
Profilarr auto-pulls Dictionarry/TRaSH Guides/Dumpstarr, then repo-managed
scripts refresh selected Arr definitions and reapply local scores. Use
`scripts/media-release/profilarr_bounded_tier_import.py` for future
Profilarr tier replacement tests. This preserves upstream
CF-definition updates without accepting upstream profile scoring such as the
stock x265 penalty.

Before staging any future Profilarr-derived replacement profile, run:

```bash
ansible docker-vm --become -m script -a "scripts/media-release/arr_stage_profilarr_test_profiles.py --dry-run"
ansible docker-vm -m script -a scripts/media-release/profilarr_candidate_audit.py
ansible docker-vm -m script -a "scripts/media-release/profilarr_tier_candidate_compare.py --only-missing --name-regex '1080p (Efficient|Compact) (TV|Movie) (WEB|Bluray|Trash) Tier|1080p (WEB-DL|Bluray) HEVC Tier|WEB-DL Tier'"
ansible docker-vm --become -m script -a "scripts/media-release/profilarr_cf_definition_sync.py --dry-run --min-free-slots 0"
ansible docker-vm --become -m script -a "scripts/media-release/profilarr_bounded_tier_import.py --dry-run"
ansible docker-vm -m script -a scripts/media-release/arr_profile_math_audit.py
ansible docker-vm --become -m script -a "scripts/media-release/sonarr_transaction_audit.py --hours 24 --limit 25"
ansible docker-vm -m script -a scripts/media-release/sonarr_release_expectation_check.py
ansible docker-vm -m script -a scripts/media-release/radarr_release_expectation_check.py
```

Only after a future candidate proves the same DA/x265/quality math should a
small pilot set be moved to the recreated test profile.

## Backups And Cleanup

Live release-policy changes require targeted backups before mutation. Current
rollback artifacts from the Profilarr migration and staging passes:

- Efficient profile promotion snapshot:
  `/opt/media-stack/release-policy-snapshots/20260527T015400Z-efficient-profile-promotion`
- Seerr Arr endpoint correction snapshot:
  `/opt/media-stack/release-policy-snapshots/20260527T020309Z-seerr-arr-endpoint-update`
- Recyclarr compose-disable backup:
  `/opt/media-stack/docker-compose.yml.codex-pre-disable-recyclarr-20260527T022517Z`
- Historical Recyclarr balanced-profile retarget backup from before Recyclarr
  was disabled:
  `/opt/media-stack/recyclarr/recyclarr.yml.codex-pre-balanced-profile-retarget-20260527T015745Z`

- Arr policy dry-run snapshot:
  `/opt/media-stack/release-policy-snapshots/20260523T014538Z`
- Arr policy pre-stage snapshot:
  `/opt/media-stack/release-policy-snapshots/20260523T014603Z`
- Profilarr DB backup before linking Dumpstarr:
  `/opt/profilarr/config/data/backups/profilarr-pre-dumpstarr-20260523T014640Z.db`
- Profilarr DB backup before linking TRaSH Guides:
  `/opt/profilarr/config/data/backups/profilarr-pre-link-trash-guides-20260526T224626Z.db`
- Profilarr DB backup from the failed direct API-key attempt before TRaSH
  Guides was linked:
  `/opt/profilarr/config/data/backups/profilarr-pre-link-trash-guides-20260526T224340Z.db`
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
- Existing-CF Profilarr/TRaSH definition sync snapshots:
  `/opt/media-stack/release-policy-snapshots/20260526T225536Z-profilarr-cf-definition-sync-dry-run`,
  `/opt/media-stack/release-policy-snapshots/20260526T225605Z-profilarr-cf-definition-sync`,
  and idempotence snapshot
  `/opt/media-stack/release-policy-snapshots/20260526T225647Z-profilarr-cf-definition-sync-dry-run`
- Dictionarry compact-tier test-profile snapshots:
  `/opt/media-stack/release-policy-snapshots/20260526T203854Z-profilarr-cf-definition-sync-dry-run`,
  `/opt/media-stack/release-policy-snapshots/20260526T210325Z-dictionarry-compact-tiers-dry-run`,
  `/opt/media-stack/release-policy-snapshots/20260526T210414Z-dictionarry-compact-tiers`,
  replacement-mode dry-run
  `/opt/media-stack/release-policy-snapshots/20260526T211726Z-dictionarry-compact-tiers-dry-run`,
  and replacement-mode applied snapshot
  `/opt/media-stack/release-policy-snapshots/20260526T211737Z-dictionarry-compact-tiers`
- Dictionarry/TRaSH bounded-tier test-profile snapshots:
  `/opt/media-stack/release-policy-snapshots/20260526T225536Z-dictionarry-bounded-tiers-dry-run`
  and
  `/opt/media-stack/release-policy-snapshots/20260526T225621Z-dictionarry-bounded-tiers`
- Sonarr transaction-monitor log sanitized rollback copies:
  `/var/log/sonarr-transaction-monitor/sanitized-backups/events.jsonl.sanitized-backup-20260527T003941Z`
  and
  `/var/log/sonarr-transaction-monitor/sanitized-backups/events.jsonl.sanitized-backup-20260527T004021Z`
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

### Live Rollback Backup Location

`/opt/media-stack/arr-policy-backups` is a compatibility path for older
media-release helpers. It should resolve to the Sanoid-managed rollback cache
at `/srv/live-rollbacks/docker-vm/arr-policy` on docker-vm, not to docker-vm's
root filesystem.

For new one-off live backups, use the repo-managed helper:

```bash
sudo live-rollback-backup --domain arr-policy --name <change-name> --path <absolute-path>
```

Those backups land on ts440's `nas_zfs/backups/live-rollbacks` dataset. Sanoid
snapshots that dataset and runs `live-rollback-cache-prune` to remove marked
live cache directories after a newer snapshot exists. Restic and PBS remain the
durable system backups; this Sanoid-backed cache is for quick operator
rollback artifacts and should not consume docker-vm root space.

On 2026-06-01, stale duplicate 2026-05-24 JoJo/blocklist rollback directories
under `/opt/media-stack/arr-policy-backups` were removed to recover docker-vm
root space. The documented retained examples from that day and the recent
2026-05-31 rollback directories were kept for migration into the Sanoid-backed
location.

## Current Notes

- Recyclarr is disabled. If it reappears in `docker compose ps`, media-stack
  health, or scheduled jobs, treat that as drift and disable it again before
  changing release policy.
- Do not write raw API keys or random tokens into Profilarr's `auth_settings`
  table. Profilarr v2.0.6 crashed when a raw DB-edited API-key hash was used
  during the TRaSH Guides link attempt. The safe path is the authenticated UI
  flow or the backed-up `profilarr_link_database.py --direct` clone/SQLite
  fallback followed by a Profilarr restart.
- Local/manual CFs such as `Local Anime Raw Group - DBD-Raws`,
  `Portuguese (No English)`, and the quality-rank CFs must remain documented
  because they are not all represented by upstream Profilarr sources.
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
  default it is read-only. `--remove-current-better --safe-groups-only
  --remove-from-client` removes only download groups where every queued row is
  worse than the current imported file; it uses Sonarr queue deletion with
  `blocklist=false` unless `--blocklist` is explicitly passed. Each removal
  pass writes a queue snapshot under `/opt/media-stack/arr-policy-backups/`.
  On 2026-05-22, after inspection, it removed 168 stale worse queue rows across
  5 downloads. The follow-up check showed 69 remaining queue rows, all with
  `queued_better` and no `current_better` candidates.
- `scripts/media-release/sonarr_grab_forensics.py` is the first-line read-only queue
  classifier for the same problem. It groups queue rows by download, compares
  queued vs current custom-format scores, flags likely payload score loss,
  pack collateral/mapping issues, stalled/warning downloads, and active valid
  upgrades, and prints the release signals Sonarr probably used at grab time.
  Use it before considering any queue removal or download-client cleanup.
- 2026-06-04 import-recovery queue check: current-better rows were not a
  single Sonarr scoring failure. The live queue had stalled qBittorrent rows
  such as `[NH] Sonny Boy` at `45000` queued score while the imported files
  were already `145040` DA/BD/x265, plus mixed packs such as `[Judas] One
  Piece 001-206` with 133 still-valid queued-better rows, 41 current-better
  rows, and 32 unknown rows. Treat this as stale/incomplete download state
  and pack collateral unless a filtered forensic check proves the whole
  download group is current-better. Do not delete a mixed pack just because
  some rows are worse than the current files.
- `scripts/media-release/radarr_grab_forensics.py` is the matching Radarr
  classifier. It compares queued movie downloads against current movie file
  scores when Radarr exposes them and also parses Radarr import-rejection
  messages that say the existing file has a higher custom-format score. It is
  read-only by default; manual cleanup uses `--remove-current-better
  --safe-groups-only --remove-from-client` and writes a queue snapshot first.
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
- Standalone dual marker expansion, 2026-05-27 UTC: JoJo searches showed
  higher-tier HEVC releases such as
  `JoJos.Bizarre.Adventure.2012.S03E04.1080p.BluRay.x265.SDR.Opus.2.0.Dual.Yogi-HONE`
  matching release-tier and x265 CFs but not `Anime Dual Audio`, while lower
  tier/no-tier releases with explicit `Dual-Audio` won on the DA score. The
  dual-audio title regex now also trusts standalone `Dual`/`DUAL` markers,
  except `Dual-Subs`/`Dual-Subtitles`, so these common anime titles receive the
  DA score and can outrank weaker DA+x265-only releases when the release group
  tier is better.
- Dual-audio false-positive and Dubs-only correction, 2026-05-31 UTC:
  a same-day audit found 54 original-language-only Sonarr imports since
  `2026-05-30T05:00:00Z`: 22 JoJo, 26 Umamusume, 5 Asterix, and 1 Second
  Prettiest Girl. Manual searches showed distinct causes:
  `Asterix & Obelix: The Big Fight` had an English+French EDITH candidate, but
  the regular profile scored original+English DA at `0`, so French-only x265
  TARDiS scored `45000` and beat EDITH at `40000`. That Asterix gap was later
  closed with `shows-regular-dual-audio-efficient`, where EDITH now scores
  `140000` from `Regular Dual Audio` and TARDiS remains `45000`. Umamusume and
  Second Prettiest Girl did not show real original+English candidates; apparent
  English hits were subtitle language tags or non-original-language rows below
  the Japanese x265 imports. JoJo Golden Wind exposed a real anime-profile bug: `[KaiDubs] ... [Dual
  Audio] [JPBD]` was being caught by `Dubs Only (Block)` because the positive
  dub-title matcher included `kaidubs`. `arr_dual_audio_title_policy.py
  --apply` now makes `Dubs Only (Block)` require its positive dub-title matcher
  and also require absence of explicit DA markers, so KaiDubs dual-audio is
  accepted at `140000` while KaiDubs English-dub-only remains hard rejected.
  The same rollout added an `Anime Dual Audio` negative guard for explicit
  non-English dub/audio lists without English, so titles such as Fuchs
  Japanese+German `Multi-Audio ... German/Deutsch Dubs` no longer receive the
  DA score. The retained rollback backup for this live change is
  `/opt/media-stack/arr-policy-backups/20260531T041508Z-dual-audio-title-policy`;
  redundant dry-run/intermediate backups from the rollout were removed after
  validation. `sonarr_release_expectation_check.py` and
  `radarr_release_expectation_check.py` now test these exact title cases.
- Historical Recyclarr ownership note for that fix: the stock TRaSH/Recyclarr
  `Anime Dual Audio` custom formats were removed from
  `/opt/media-stack/recyclarr/recyclarr.yml` for Sonarr trash ID
  `418f50b10f1907201b6cfdf881f467b7` and Radarr trash ID
  `4a3b087eea2ce012fcc1ce319259a3be`, because Recyclarr syncs would otherwise
  overwrite the local title-marker DA behavior. Recyclarr is now disabled, but
  rollback backups from the live change are `/opt/media-stack/arr-policy-backups/20260523T045221Z-dual-audio-title-policy`
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
  tracked queue rows can lag. Do not remove valid DA downloads only because an
  old active queue row has not recomputed yet.
- Standalone-dual false-positive tightening, 2026-06-06 UTC: Radarr candidate
  audits found `DUAL-Franceira` and `Dual-YG` releases receiving the full
  `Anime Dual Audio` score even though Radarr parsed them as Japanese+Portuguese
  or Japanese+Spanish with no English track. The title-side DA regex still
  trusts known-good standalone forms like `Dual.Yogi-HONE`, but no longer
  treats standalone `Dual` followed by `Franceira` or `YG` as DA evidence.
  Explicit language pairs such as `JA+EN`, `JP+EN`, `ZH+EN`, `KO+EN`, or
  literal `Dual Audio`/`Dual-Audio` remain valid. `sonarr_release_expectation_check.py`
  and `radarr_release_expectation_check.py` include the non-English suffix
  cases so this does not silently regress.
  Live backups from the apply are
  `/opt/media-stack/arr-policy-backups/20260606T085014Z-dual-audio-title-policy`;
  dry-run backup was
  `/opt/media-stack/arr-policy-backups/20260606T084957Z-dual-audio-title-policy`.
  Post-fix checks passed for Sonarr, Radarr, and profile math: `DUAL-Franceira`
  and `Dual-YG` no longer receive DA, while `Dual-Audio`, `Dual.Yogi-HONE`,
  `JA+EN`, and `EN+JA` still do.
- Wrong-language movie audit, 2026-06-06 UTC: `arr_language_policy_audit.py
  --app radarr --probe` scanned 59 anime/regular-dual-audio movie files and
  found 21 suspect files. Confirmed actual-audio mismatches include
  Japanese+Portuguese `Evangelion: 2.0`, `Howl's Moving Castle`, and `Princess
  Mononoke`; Japanese+Spanish `Demon Slayer: Infinity Castle`; English-only
  `One Piece Film: Z`, `One Piece: Adventure of Nebulandia`, `One Piece Film:
  Strong World`, `Asterix Conquers America`, `Asterix: Mansions of Gods`,
  `Avengers Confidential: Black Widow & Punisher`, `Flow`, and `Sisu: Road to
  Revenge`; French-only or French+Greek Asterix files; plus Spanish/French
  regular-dual-audio files missing English such as `I Am Frankelda`, `Unicorn
  Wars`, and `The Suicide Shop`.
- Post-fix Radarr candidate audit for the false-positive anime movies found
  approved English+Japanese replacements for `Evangelion: 2.0`, `Princess
  Mononoke`, and `Howl's Moving Castle` at scores around `145040`. `Demon
  Slayer: Infinity Castle` had only English+Japanese telesync candidates, which
  are unwanted and correctly rejected. `One Piece Film: Z` and `One Piece Film:
  Strong World` had English+Japanese iVy candidates, but the live `LQ` custom
  format drives them to `-955000`. Radarr history confirms this is not only a
  search rejection: `One Piece Film: Strong World` imported an iVy
  English+Japanese x265 file, then later deleted it and imported the English-only
  BHDStudio file because the `LQ` penalty made the DA file lose. Do not remove
  or weaken `LQ` without a separate review because it has broad release-quality
  impact, but the current `-1000000` anime LQ score violates the intended
  DA-first priority for metadata-only DA candidates.
- Anime metadata-only DA gap, 2026-06-06 UTC: `movies-anime-efficient` scores
  `Anime Dual Audio` at `+100000`, but helper CFs `Anime - Dual Audio
  (Metadata)`, `Anime - Dual Audio (Title)`, and `Regular Dual Audio` are all
  scored `0` on that profile. This means an English+Japanese candidate that
  Radarr parses as dual-audio but whose title lacks `Dual-Audio`, `JA+EN`, or a
  similar title marker can still lose to a non-DA current file. `Avengers
  Confidential` showed this exact pattern: the 720p English+Japanese candidate
  matched only `Anime - Dual Audio (Metadata)` and scored `30000`, while the
  current English-only 1080p file scored `39000`. The same zero-scored metadata
  DA behavior combines with the hard `LQ` penalty for iVy One Piece releases.
- Asterix candidate audit, 2026-06-06 UTC: current Radarr candidates show no
  approved English+French replacement for most Asterix movies. `Asterix: The
  Secret of the Magic Potion` has English+French candidates only as unwanted
  2160p remuxes. `Asterix: Mansions of Gods` and `Asterix Conquers America`
  have approved original-language-only replacements for English-only current
  files. Several older Asterix Greek+French files tie original-only French
  candidates at score `40000`, so Radarr will not replace them without a
  deliberate policy change such as penalizing non-English extra dubs without
  English on regular dual-audio profiles.
- Search-versus-import language mismatch, 2026-06-06 UTC: Radarr history shows
  `Flow` and `Sisu: Road to Revenge` were grabbed at higher scores
  (`45440`/`45088`) because release search treated the candidates as original
  language, but imported files probed as `eng` audio and lost the
  `Language - Not Original` penalty at import (`35440`/`35088`). Targeted
  ffprobe confirmed the current files have only `eng` audio tags: `Flow` has one
  E-AC-3 5.1 `eng` stream; `Sisu: Road to Revenge` has one E-AC-3 Atmos `eng`
  stream. This mismatch is why repeated searches can download a release that
  Radarr later refuses as not an upgrade. Preventing the download requires
  search-time policy changes such as stricter title-language evidence, because
  actual audio tags are not known until after download.
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
  `/data/downloads/complete` and `/data/Anime`. This was a historical
  media-vm-era repair; the current docker-vm media-stack layout is documented
  in `docs/media-stack-storage-layout.md` and uses `/srv/media/plex:/data`.
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
- qBittorrent event log:
  `/opt/media-stack/qbittorrent/scripts/release-stamper-events.jsonl`
- qBittorrent hook: `/usr/bin/python3 /config/scripts/qbit-release-stamper.py --hash "%I" --name "%N" --category "%L"`
- SABnzbd script: `/opt/media-stack/sabnzbd/scripts/sab-release-stamper.py`
- SABnzbd script directory: `scripts`
- SABnzbd event log:
  `/opt/media-stack/sabnzbd/scripts/release-stamper-events.jsonl`
- SABnzbd categories using the stamper: `shows`, `movies`
- Stamper script directories and executable scripts under the linuxserver
  `/config` bind mounts are owned by UID/GID `1000`, matching the media
  containers' `PUID=1000` / `PGID=1000`. The env files are also UID/GID `1000`
  with mode `0600`, and event logs are UID/GID `1000` with mode `0640`. Do not
  force these `/config` paths back to `root:root`; container startup and normal
  app writes expect the configured media user.

## Download Client Storage Layout

For the full verified mount/export/container topology, use
`docs/media-stack-storage-layout.md` first. This section only captures the
release-policy reason for the layout.

The media stack intentionally keeps qBittorrent completed downloads under
`/data/downloads/torrents` so Sonarr/Radarr can hardlink seeded torrents into
the library. SABnzbd completed downloads also stay under
`/data/downloads/complete` before Arr import. Even though Usenet does not need
seeding semantics, moving SAB completed downloads to a separate mount forces
Arr imports into copy/delete behavior and removes the chance for same-tree
hardlinks.

Do not move qBittorrent or SABnzbd completed paths to a separate completed
download mount unless Johnny explicitly approves that copy/delete tradeoff for
the affected client. Keep only incomplete/temp downloads on the dedicated
`/srv/media-downloads` SSD export by default.

`/usenet-complete` was a temporary legacy drain path from a reverted live-path
experiment. Do not configure SABnzbd to write new completed jobs there. The
desired state is no `/usenet-complete` mount in the media-stack containers.

2026-06-04 Radarr import-stall mitigation:

- Evidence pointed to TS440 NFS workers blocking in mergerfs/FUSE writes while
  `/srv/media-06` (`/dev/sdh`) was saturated. `media-06` was deliberately left
  writable because it still needs to remain part of the pool until it can be
  phased out.
- A runtime increase of TS440 NFS worker threads from `16` to `64` did not fix
  the stall and was reverted to `16`.
- Docker-vm rollback backup before the reverted SAB path change:
  `/srv/live-rollbacks/docker-vm/media-stack/20260604T222322Z-sab-complete-dir-ssd`.
- SABnzbd `complete_dir` was changed live from `/data/downloads/complete` to
  `/usenet-complete`, then reverted on 2026-06-05 after review because it
  removed SAB's same-tree hardlink opportunity and was too broad without
  explicit approval. The reverted desired state is
  `/data/downloads/complete`.
- Existing payloads already completed under `/usenet-complete` were temporarily
  left visible through the compatibility bind mount so Arr could still see them
  during the rollback. On 2026-06-06, the remaining Sonarr references were
  confirmed to be X-Men Anime trouble rows that Sonarr had already refused to
  auto-import. Those queue rows were removed with `blocklist=false` and
  `skipRedownload=true`, the matching legacy/copied payload directories were
  deleted, and `/usenet-complete` was removed from the managed media-stack
  compose template.
- Full `playbooks/storage/nfs.yml --check --diff` and
  `playbooks/docker/docker-stacks.yml --check --diff` runs showed unrelated
  drift (`/srv/media` group ownership and `docker-stacks.service`
  `/srv/live-rollbacks` dependencies). Those broader playbook changes were not
  applied as part of the scoped SAB storage-path mitigation.

## Media Stack Health Alert Semantics

`media-stack-health` should page only on actual brokenness, not on slow but
advancing workload. Long-running Sonarr/Radarr commands become critical only
after they are older than the stale threshold and their command message has not
advanced for the no-progress window. Transient container health or HTTP
endpoint failures require consecutive failing checks before they become
critical. Below-threshold NFS `fileid changed` events are suppressed from
heartbeat output.

qBittorrent copied-import findings remain warnings because they are real
storage-efficiency evidence, but they do not mean the media stack is down.
Astra should not send recurring heartbeat alerts for zero-exit warning output;
warnings belong in manual review or a digest unless they become a nonzero
`CRITICAL:` result.

The qBittorrent script runs when a torrent finishes. It looks up the finished
torrent through the qBittorrent Web API, iterates each video file, and renames
individual payload files through qBittorrent's `renameFile` API. Do not replace
this with direct filesystem renames, because direct renames can break seeding or
hash-check state. The deployed env also sets bounded qBittorrent API
retry/backoff (`QBIT_API_RETRIES`, `QBIT_API_RETRY_DELAY`, `QBIT_API_TIMEOUT`)
so transient Web API stalls do not immediately leave completed torrents
unstamped. For obvious single-file video torrents, the stamper uses
qBittorrent's torrent metadata instead of calling the `torrents/files`
endpoint, because that endpoint has been observed to hang and wedge qBit's Web
API on some completed torrents; the actual rename still goes through
`renameFile`. For one-off repair commands where Sonarr context is known but the
qBit-side lookup cannot recover it, the script supports `--series-title` to
provide the canonical Sonarr title explicitly.
- qBittorrent file-list lookup has separate bounded controls
  (`QBIT_FILES_API_RETRIES`, `QBIT_FILES_API_RETRY_DELAY`,
  `QBIT_FILES_API_TIMEOUT`). If `torrents/files` times out, the script falls
  back to scanning the completed torrent path from qBittorrent metadata and
  still uses `renameFile` for any rename. Event logs include `file_list_source`
  and `file_list_error` so timeout-driven filesystem fallback is visible.

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
  title saying `Dual-Audio` is not enough by itself. English is never treated
  as the original-language side of a DA tag, so English-original content does
  not get a duplicate `[EN+EN]` marker.
- `[x265]` is file-by-file only. The scripts scan the individual video file for
  HEVC markers (`V_MPEGH/ISO/HEVC`, `hvc1`, `hev1`, `x265`, `HEVC`) and MKV
  video-track `CodecID` data, and only stamp that specific file when the
  payload itself looks like HEVC.
- Mixed or mislabeled packs should not be bulk-labeled. Each video file must
  qualify for each tag independently.
- When Sonarr context is available, TV payload names with an episode token but
  without the canonical series title are rewritten to use the canonical title
  prefix before DA/x265/release-context tags are appended. A leading release
  group such as `[Judas]` is preserved. This covers both bare `SxxEyy` names and
  ambiguous short-title names such as `[Judas] JoJo - S06E01`.
- Exact per-series/per-movie original-language matching depends on optional
  Sonarr/Radarr context. That context is an enhancement, not a dependency; if
  Sonarr/Radarr is down, download completion must continue and use the safe
  fallback language.
- The scripts are intentionally non-fatal. If stamping fails, they log the
  error and exit successfully so they do not block SABnzbd or qBittorrent
  completion/import flows.
- Both stampers write compact JSONL event logs with result, rename count,
  scanned-video count, skipped-no-stamp count, category, and download name.
  `scripts/media-release/sonarr_transaction_audit.py` summarizes these logs
  alongside Sonarr history. A completed event with `changes=0` is not
  automatically bad: it is expected when payload files already include all
  needed evidence such as `H.265`, service tags, and release group. qBittorrent
  events also include `skip_reasons` and sampled skipped files, so a zero-rename
  event can distinguish already-tagged files from unresolved paths, unknown audio
  languages, missing English/original audio, missing HEVC markers, or absent
  release-group evidence.

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
- Local predicate test on 2026-05-27 confirmed English-original audio no
  longer emits `[EN+EN]`; English-only and English-original `eng+jpn` files get
  no language-combo tag, while `jpn+eng`, `kor+eng`, and `jpn+kor+eng` still
  emit `[JA+EN]`, `[KO+EN]`, and `[JA+KO+EN]`.
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
7. Recyclarr should stay disabled unless the policy-management direction is
   explicitly changed.
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

## Queue Pollution Findings - 2026-05-31

Focused Sonarr queue forensics used
`scripts/media-release/sonarr_grab_forensics.py --filter ... --manual-import`
against the live queue. The current bad rows are not one single CF math bug:

- `[Judas] JoJo - S06E01` / Steel Ball Run was grabbed at `+145000`
  (`Anime Dual Audio`, `Local Quality Rank - 1080p`, `x265`), but manual import
  rescored the completed payload as `+40000` (`Local Quality Rank - 1080p`,
  `Regular Dual Audio`). The qBittorrent stamper event for the original
  completion was `result=error`, `error="timed out"` at
  `2026-05-30T15:56:53Z`, so `[JA+EN]`/`[x265]` were not written to the file
  before Sonarr rescored it. A later in-container dry-run proved the media file
  really would stamp as `[JA+EN] [x265]`, but the current stamper still leaves
  the ambiguous series name `JoJo`; Sonarr's parser does not map that title to
  `JoJo's Bizarre Adventure (2012)` without the grab-history ID, so automatic
  import remains blocked unless the stamper also prefixes or otherwise
  preserves the full Arr series title for ambiguous payload names.
- `Sonny Boy S01 1080p Dual Audio BDRip 10 bits DD x265-EMBER` was a valid
  stamped payload after qBittorrent post-processing, but Sonarr parsed the
  release title as absolute episode `10` because of the separated `10 bits`
  token. It imported only S01E10 and rejected the other files with
  `Episode 1xNN was not found in the grabbed release`. The Sonarr parse endpoint
  showed `seasonNumber=0`, `absoluteEpisodeNumbers=[10]`,
  `isAbsoluteNumbering=true`, and `releaseType=singleEpisode` for the original
  pack title.
- `Spider-Noir.2026.S01.1080p...` was accepted as a season pack at grab time,
  but the extracted payload file is named
  `Spider.2002.1080p... -DNU.TAoE.mkv`. Sonarr parses that payload as
  `seriesTitle=Spider`, `seasonNumber=20`, `episodeNumbers=[2]`, with no
  matching series. This should be treated as a bad/mispacked release rather than
  a profile preference issue.
- `Paris.has.Fallen.S01E03...POOTLED` was grabbed at `+45000` from title-side
  `Local Quality Rank - 1080p` plus `x265`, then import rescored it as
  `+35000` after `Language - Not Original` applied from the payload. The
  existing file is `+35441`, so Sonarr correctly refused import at that point.
  This is grab-time versus import-time metadata drift: the media language cannot
  be fully known before download unless the release title exposes it.
- The SAB release stamper's Arr queue matcher is too loose: it includes all SAB
  script arguments as match terms and accepts substring matches. Short terms
  such as `0` can match unrelated queued releases containing `1080p`, which
  explains contaminated `parent_title` telemetry such as Spider-Noir inheriting
  context from The Seven Deadly Sins and Paris inheriting context from JoJo. The
  2026-05-31 stamper update now filters tiny/generic terms and only accepts
  exact or long-title containment matches.
- The qBittorrent stamper needs retry/backoff around API calls and a repair path
  for completed queue items whose first stamp timed out. The 2026-05-31 stamper
  update added bounded qBittorrent Web API retries and endpoint-specific retry
  logging. A dry-run writes telemetry but does not rename; use an explicit live
  backup/change window before running non-dry-run repair on active torrents.

Open prevention work:

- Decide whether to add a negative CF for anime season-pack titles with
  separated `10 bits`/`8 bits` tokens that Sonarr parses as absolute episodes,
  or handle these as manual/blocklist exceptions per release.

Reference links:

- <https://github.com/Dictionarry-Hub/profilarr>
- <https://github.com/Dictionarry-Hub/profilarr/releases>
- <https://github.com/Dictionarry-Hub/profilarr/blob/33d73a36de8206e79928ecb1ed82556875206b1c/src/lib/server/utils/arr/base.ts>
- <https://github.com/Dictionarry-Hub/profilarr/blob/33d73a36de8206e79928ecb1ed82556875206b1c/src/lib/server/upgrades/processor.ts>
- <https://www.dumpstarr.dev/>
