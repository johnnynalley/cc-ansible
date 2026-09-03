# Media Stack Storage Layout

> Last updated: 2026-06-18

This is the first reference for Sonarr/Radarr/SABnzbd/qBittorrent storage
questions after the media automation moved to `docker-vm`. Check this document
before reconstructing the layout from memory during import, hardlink, NFS, or
mergerfs-balance incidents.

## Source Of Truth

- Docker container mounts: `templates/docker/docker-media-stack.yml.j2`
- docker-vm NFS client mounts: `inventory/host_vars/docker-vm/nfs.yml`
- TS440 NFS exports: `inventory/group_vars/nas_server/nfs.yml`
- TS440 physical and bind mounts: `inventory/group_vars/nas_server/mounts.yml`
- mergerfs branches and balance excludes:
  `inventory/group_vars/nas_server/mergerfs.yml`
- release/import policy details: `docs/media-release-policy.md`

## Active Layout

Plex stays on `media-vm`. Sonarr, Radarr, SABnzbd, qBittorrent, Prowlarr,
Bazarr, Byparr, and Profilarr run in the `media-stack` compose project on
`docker-vm`.

`docker-vm` mounts the TS440 media export at `/srv/media`. Media-stack
containers bind `/srv/media/plex` to `/data`. This is intentional: completed
downloads and final libraries stay under one visible filesystem so Arr imports
can hardlink when branch placement allows it.

Bazarr also binds `/srv/media/plex` to `/data` without `:ro`. That is
intentional because Bazarr's output is sidecar subtitle files next to existing
media. A read-only `/data` mount can make Bazarr look healthy while every
downloaded subtitle fails with `OSError(30, 'Read-only file system')`.
`media-stack-health` must check the functional contract, not only the container:
enabled providers, provider auth/throttle state, a writable subtitle target, the
missing-English backlog, and the age of the last successful subtitle download.

`docker-vm` mounts the TS440 incomplete-downloads export at
`/srv/incomplete_downloads`. SABnzbd binds
`/srv/incomplete_downloads/incomplete/usenet` to `/incomplete`, and qBittorrent
binds `/srv/incomplete_downloads/incomplete/torrents` to `/incomplete`. This
SSD-backed incomplete path is outside the mergerfs branch tree.

`docker-vm` also mounts the TS440 archive export at `/srv/archive`; media-stack
containers that expose archive storage bind it as `/archive`. If `/srv/archive`
goes stale, Docker can fail before qBittorrent starts and leave the container in
`created` state. The managed qBittorrent/Gluetun recreate paths therefore
preflight `/srv/archive`, `/srv/media/plex/downloads/complete`,
`/srv/media/plex/Anime`, and
`/srv/incomplete_downloads/incomplete/torrents` before recreating containers.
If one of those checks fails, repair the docker-vm NFS/autofs mount first and
then recreate the affected containers so their bind namespaces refresh.

`media-stack-health.service` now has a separate
`media-stack-storage-recover.service` failure hook on `docker-vm`. The health
script remains the classifier and alert surface. The recovery script only acts
after a failed health unit proves required NFS-backed paths are stale,
unreadable, or missing. It does not remount for `fileid changed` messages by
themselves. When triggered, it stops the media-stack compose project, refreshes
the affected NFS mounts, starts the compose project again, runs qBittorrent
port sync when available, and validates with `media-stack-health --no-alert`.

Verified live on 2026-06-18:

- `docker-vm:/srv/media` is NFS `192.168.1.146:/media`.
- `docker-vm:/srv/incomplete_downloads` is NFS
  `192.168.1.146:/incomplete-downloads`.
- `ts440:/srv/media` is `fuse.mergerfs`.
- `ts440:/srv/media-downloads` is a dedicated ext4 filesystem on the Samsung
  860 EVO USB-SATA SSD, configured by UUID in
  `inventory/group_vars/nas_server/mounts.yml`. The old Lacie-backed source
  path, `/srv/nas-01/downloads/media-downloads`, must remain intact as the
  rollback copy until the migration is fully proven. The transient kernel
  device name shown by `findmnt` or `df` is not stable and should not be used as
  an identity.
- `ts440:/srv/media` uses stable NFS-oriented inode options plus
  `func.getattr=ff`. Do not switch `func.getattr` back to `newest` without a
  targeted test: on 2026-06-11, Sonarr import processing repeatedly wedged
  mergerfs/NFS by statting a missing destination file under a branch-local
  season folder while `func.getattr=newest` was active.
- `ts440:/srv/media` uses `category.create=mspmfs`, not plain `epmfs`.
  `mspmfs` keeps the path-preserving "existing path most free space" behavior
  when the exact target directory exists on an eligible branch, but falls back
  to a parent directory search when the exact target path exists only on a full
  branch. This prevents Arr imports from getting trapped on `/srv/nas-01` when
  a season directory exists there but the branch has no usable free space.
- Path preservation can still defeat a qBittorrent hardlink even though both
  paths are exposed through the single `/data` container mount. On 2026-09-03,
  exact mergerfs `user.mergerfs.basepath` evidence showed the Young Sheldon
  S03E18 and My Hero Academia S08E02 source files on
  `/srv/media-01/media`, while their imported library copies were placed on
  `/srv/nas-zfs/media`. Both source and destination had the same byte size but
  link count 1. This is the documented path-preserving-policy `EXDEV` case,
  not a split Docker mount.
- The leading remediation candidate is to retain `category.create=mspmfs` for
  ordinary creates and evaluate `ignorepponrename=true` for link/rename
  operations. That option makes a linked or renamed destination remain on the
  source file's backing filesystem instead of enforcing the target directory's
  existing branch placement. Do not enable it without a planned TS440 remount
  and canaries proving qBittorrent hardlinks, SAB imports, and ordinary Arr
  destination creation; the live pool is also Plex's storage path.

## Completed Vs Incomplete

Completed Arr downloads are supposed to be in the mergerfs-backed `/data` tree:

- SABnzbd completed jobs: `/data/downloads/complete`
- qBittorrent completed jobs: `/data/downloads/torrents`
- Final libraries: `/data/Anime`, `/data/TV`, `/data/Movies`, and related
  library directories

Incomplete and active temp download work is supposed to stay on the SSD-backed
`/incomplete` tree. Do not move completed Arr paths to a separate completed
mount unless Johnny explicitly accepts copy/delete imports for that client.

Verified live downloader paths on 2026-06-06:

- SABnzbd: `download_dir = /incomplete`
- SABnzbd: `complete_dir = /data/downloads/complete`
- qBittorrent: `Downloads\TempPath=/incomplete/`
- qBittorrent: `Downloads\SavePath=/data/downloads/torrents/`

`/usenet-complete` was a temporary compatibility mount from a reverted path
experiment. It must not receive new SAB completed jobs and is not part of the
managed desired state.

## mergerfs Balance

`mergerfs-balance` is allowed to move files inside `/srv/media`, including
`/srv/media/plex/downloads/complete`, unless that path is excluded. That is not
automatically wrong because completed downloads are part of the media tree.

Routine nightly balancing is disabled by policy. The normal
`nightly-media-maintenance` path opens Profilarr upgrade work from midnight
through 6 AM and closes the window at 7 AM. Balance jobs are exception/manual
work only; if one is deliberately queued, it owns that night's window and
Profilarr upgrades are skipped until the job is removed, completed, or
deferred.

The safety requirement for an approved balance run is that no process is
writing to the files being moved. The coordinator pauses the docker-vm media
stack before each actual rsync move and resumes it afterward. The timer may fire
at midnight, but the current `mergerfs-balance` implementation scans branch
stats and selects the first eligible file before running the pause hook. A
manual copy, import, unpack, or cleanup that writes into `/srv/media/plex`
during a maintenance window can still create changing files and break the
balance run.

Before diagnosing balance/import behavior, verify both sides:

```bash
systemctl cat nightly-media-maintenance.timer
cat /var/lib/nightly-media-maintenance/balance-queue.json
cat /var/lib/nightly-media-maintenance/state.json
cat /etc/mergerfs-balance.conf
```

If a queued balance job should no longer block nightly Profilarr upgrades,
remove it with the managed coordinator instead of disabling random services:

```bash
nightly-media-maintenance --state-dir /var/lib/nightly-media-maintenance \
  balance remove <job-name>
```

If an approved balance job needs to stay queued but not run yet, defer it with
the managed coordinator:

```bash
nightly-media-maintenance --state-dir /var/lib/nightly-media-maintenance \
  balance defer set --for-days 7 --reason arr-queue-drain
```

## NFS Fileid Changed Triage

`docker-vm` consumes the TS440 mergerfs pool through NFS. If the kernel logs
`NFS: server 192.168.1.146 error: fileid changed`, first verify that TS440 is
still running the NFS-safe mergerfs options and that NFS exports have stable
`fsid` values before changing anything:

```bash
ansible ts440 -b -m shell -a 'pgrep -a mergerfs; systemctl cat srv-media.mount'
ansible docker-vm -b -m shell -a 'findmnt -T /srv/media -o TARGET,SOURCE,FSTYPE,OPTIONS -n; journalctl -k --since "10 minutes ago" --no-pager | grep -i "fileid changed" || true'
```

The expected TS440 mergerfs options include `noforget`, `use_ino`,
`inodecalc=path-hash`, `func.getattr=ff`, and `category.create=mspmfs`; the
expected NFS media export uses a stable `fsid`. These match the current
NFS/import-safety guidance for this topology. If those are present and
TS440 has no matching server-side NFS/FUSE errors, treat the symptom as
NFS-client state churn against a mutable FUSE/mergerfs export, especially while
Sonarr/Radarr are importing, renaming, or deleting completed downloads.

Do not call this fixed by only raising alert thresholds. A controlled recovery
test is to wait for active imports to settle, stop the docker-vm media-stack
containers once, remount `docker-vm:/srv/media`, start the stack, then watch
whether new fileid errors stop. This should not interrupt Plex on `media-vm`,
but it does pause Sonarr/Radarr/SABnzbd/qBittorrent, so get explicit operator
approval before running it during active queue work.

Alert policy: repeated `fileid changed` messages are warning-only by default in
`media-stack-health`. They should remain visible for manual review, but they
should not page by themselves while imports continue to progress. Page when they
are paired with real breakage such as a missing mount, empty library probe,
stuck D-state media probe, stopped container, failed endpoint, or import
failure. Set `media_stack_health_nfs_fileid_fail_on_threshold: true` only for a
temporary investigation where the kernel message alone should fail the health
check.

Recovery policy: once the check fails because the NFS-backed mount or required
bind path is stale/unreadable, `media-stack-storage-recover.service` is allowed
to refresh the docker-vm client mount and restart the media-stack containers.
This is root-cause-specific recovery for stale NFS client state, not generic
alert suppression. If recovery fails, inspect:

```bash
journalctl -u media-stack-storage-recover --since "1 hour ago" --no-pager
journalctl -u media-stack-health --since "1 hour ago" --no-pager
```

## 2026-06-06 Incident Notes

The nightly timer is hourly during the local `00:00-07:00` window, not a
one-shot 03:00 timer. On 2026-06-06 it started at midnight, paused the media
stack, and moved data until about 01:00. Later hourly ticks retried the pending
`media06-fill` balance job because failed or partial results leave the job in
`pending`.

At 02:00, the pause hook failed before balancing because TS440 could not SSH to
`docker-vm` at `192.168.1.153:22` (`No route to host`). At 03:00, the retry
stopped the stack and then hit an rsync code 23 after a changing file under
`plex/downloads/complete` was selected. During this same investigation, a manual
cleanup copy was writing legacy Usenet payloads into
`/srv/media/plex/downloads/complete`; do not treat completed-path temp suffixes
from that window as normal SAB behavior without checking the live timeline.

The 2026-06-06 live containers still exposed `/usenet-complete` as a
compatibility bind even after SAB's `complete_dir` was reverted. Follow-up
verification showed Radarr had `0` queue rows still referencing
`/usenet-complete`, and Sonarr had `12`, all for X-Men Anime payloads that
Sonarr had already refused to auto-import. Those queue rows were removed with
`blocklist=false` and `skipRedownload=true`, and the matching legacy/copied
payload directories were deleted. After that cleanup, Sonarr had `0`
`/usenet-complete` queue references, so the compatibility bind was removed from
the managed compose template.
