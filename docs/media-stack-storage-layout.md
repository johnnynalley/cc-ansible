# Media Stack Storage Layout

> Last updated: 2026-06-06

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

`docker-vm` mounts the TS440 incomplete-downloads export at
`/srv/incomplete_downloads`. SABnzbd binds
`/srv/incomplete_downloads/incomplete/usenet` to `/incomplete`, and qBittorrent
binds `/srv/incomplete_downloads/incomplete/torrents` to `/incomplete`. This
SSD-backed incomplete path is outside the mergerfs branch tree.

Verified live on 2026-06-06:

- `docker-vm:/srv/media` is NFS `192.168.1.146:/media`.
- `docker-vm:/srv/incomplete_downloads` is NFS
  `192.168.1.146:/incomplete-downloads`.
- `ts440:/srv/media` is `fuse.mergerfs`.
- `ts440:/srv/media-downloads` is a bind mount from the managed downloads path
  on the Lacie SSD configured in `inventory/group_vars/nas_server/mounts.yml`.
  The transient kernel device name shown by `findmnt` or `df` is not stable and
  should not be used as an identity.

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

The safety requirement is that no process is writing to the files being moved.
The nightly coordinator pauses the docker-vm media stack before each actual
rsync move and resumes it afterward. The timer may fire at midnight, but the
current `mergerfs-balance` implementation scans branch stats and selects the
first eligible file before running the pause hook. A manual copy, import,
unpack, or cleanup that writes into `/srv/media/plex` during a maintenance
window can still create changing files and break the balance run.

Before diagnosing balance/import behavior, verify both sides:

```bash
systemctl cat nightly-media-maintenance.timer
cat /var/lib/nightly-media-maintenance/balance-queue.json
cat /var/lib/nightly-media-maintenance/state.json
cat /etc/mergerfs-balance.conf
```

When the Arr queue is intentionally busy, defer balance jobs with the managed
coordinator instead of disabling random services:

```bash
nightly-media-maintenance --state-dir /var/lib/nightly-media-maintenance \
  balance defer set --for-days 7 --reason arr-queue-drain
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
