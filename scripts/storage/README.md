# Storage Scripts

## Scripts

- `mergerfs-balance`: Balances files across mergerfs branches with ZFS-aware
  capacity reporting. Deployed as `/usr/local/bin/mergerfs-balance`.
- `storage-status`: Shows local storage usage with ZFS and mergerfs support.
  Deployed as `/usr/local/bin/storage-status`.
- `live-rollback-backup`: Creates timestamped one-off rollback copies under a
  Sanoid-managed live rollback dataset. Deployed on hosts that mount
  `/srv/live-rollbacks` as `/usr/local/sbin/live-rollback-backup`. Before any
  write, it requires an NFS mount exposing the managed ZFS origin marker; a
  stale server-side bind or local-directory fallback fails closed.
- `live-rollback-cache-prune`: Sanoid hook for pruning marked live rollback
  cache directories after a newer snapshot exists. Deployed on the NAS as
  `/usr/local/sbin/live-rollback-cache-prune`.
- `restic-snapshot-freshness.py`: Validates that a named Restic host has a
  recent snapshot containing every required recovery path. The TS440 monitor
  uses it to detect source-node loss independently of the backed-up host.

## Safety Notes

- `storage-status` is read-only.
- `mergerfs-balance` can move files; run dry-run style checks first and respect
  configured exclude paths before applying balance or evacuation jobs.
- `live-rollback-backup` copies only absolute paths passed with `--path`; it
  does not inspect application state or invent backup targets. It activates a
  systemd on-demand mount before checking that the rollback root is writable.
- `live-rollback-cache-prune` only deletes directories containing a
  `.live-rollback-cache` marker under `/srv/nas-zfs/backups/live-rollbacks`,
  and only after a newer ZFS snapshot exists.
- `restic-snapshot-freshness.py` reads snapshot metadata only. It never mounts,
  restores, forgets, prunes, or unlocks a repository.
