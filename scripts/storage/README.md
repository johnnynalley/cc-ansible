# Storage Scripts

## Scripts

- `mergerfs-balance`: Balances files across mergerfs branches with ZFS-aware
  capacity reporting. Deployed as `/usr/local/bin/mergerfs-balance`.
- `storage-status`: Shows local storage usage with ZFS and mergerfs support.
  Deployed as `/usr/local/bin/storage-status`.

## Safety Notes

- `storage-status` is read-only.
- `mergerfs-balance` can move files; run dry-run style checks first and respect
  configured exclude paths before applying balance or evacuation jobs.
