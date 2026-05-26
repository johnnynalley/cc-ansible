# backup-sync Playbooks

Owner area: Backups, sync jobs, and Nextcloud external-storage refresh.

## Operating Notes

- Key vars: restic_*, local_restic_*, rclone_sync_*, git_sync_*, nextcloud_scan_*.
- Template owners: templates/storage, templates/docker when sync jobs consume generated configs.
- Script owners: none by default.
- Keep playbook metadata headers and `playbooks/README.md` in sync when behavior changes.

## Playbooks

| Playbook | Hosts | Purpose | Validation |
| --- | --- | --- | --- |
| `git-sync.yml` | `nas_server` | Configure git-sync timer (ts440). | `ansible-playbook playbooks/backup-sync/git-sync.yml --syntax-check` |
| `local-restic.yml` | `backup_clients:!macos_hosts, ts440` | Configure local restic backups (ts440 ZFS). | `ansible-playbook playbooks/backup-sync/local-restic.yml --syntax-check` |
| `nextcloud-scan.yml` | `nextcloud-vm` | Configure Nextcloud external storage scan. | `ansible-playbook playbooks/backup-sync/nextcloud-scan.yml --syntax-check` |
| `rclone-sync.yml` | `managed_hosts` | Configure rclone sync jobs. | `ansible-playbook playbooks/backup-sync/rclone-sync.yml --syntax-check` |
| `restic.yml` | `backup_clients:!macos_hosts` | Configure restic backups (B2 offsite). | `ansible-playbook playbooks/backup-sync/restic.yml --syntax-check` |
