# Storage Templates

## Templates

- `exports.j2`: NFS exports.
- `sanoid.conf.j2`: Sanoid snapshot policy.
- `zfs-scrub.sh.j2`: ZFS scrub helper.
- `mergerfs-media.mount.j2`: MergerFS mount unit.
- `mergerfs-balance.conf.j2`: mergerfs-balance exclude configuration.
- `mergerfs-balance-*.j2`: Balance scheduling and media-stack control units.
- `mergerfs-branch-recovered.sh.j2`: Branch recovery hook.
- `mergerfs-mount-watchdog.*.j2`: Branch mount watchdog service, timer, and
  script.
- `mergerfs-remount.rules.j2`: udev remount rules.

## Consumers

- `tasks/nfs-server.yml`
- `tasks/sanoid.yml`
- `tasks/zfs-scrub.yml`
- `playbooks/mergerfs.yml`
- `playbooks/mergerfs-recovery.yml`

## Safety Notes

- Storage templates can affect mounts, snapshots, and media pool visibility.
  Run full check mode and inspect rendered diffs before applying.
