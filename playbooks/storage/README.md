# storage Playbooks

Owner area: NAS, mounts, shares, ZFS, MergerFS, VirtioFS.

## Operating Notes

- Key vars: smb_shares, nfs_*, filesystem_mounts, mergerfs_*, zfs_*, virtiofs_*, vm_storage_gate_*.
- Template owners: templates/storage, templates/samba, templates/proxmox.
- Script owners: scripts/storage.
- Keep playbook metadata headers and `playbooks/README.md` in sync when behavior changes.

## Playbooks

| Playbook | Hosts | Purpose | Validation |
| --- | --- | --- | --- |
| `filesystem-mounts.yml` | `linux_hosts` | Configure filesystem mounts (NTFS, exFAT, etc.). | `ansible-playbook playbooks/storage/filesystem-mounts.yml --syntax-check` |
| `mergerfs-recovery.yml` | `nas_server` | Configure MergerFS branch recovery (udev + watchdog + media-app refresh). | `ansible-playbook playbooks/storage/mergerfs-recovery.yml --syntax-check` |
| `mergerfs.yml` | `nas_server, gluetun_hosts:media-vm` | Configure MergerFS media pool. | `ansible-playbook playbooks/storage/mergerfs.yml --syntax-check` |
| `nfs.yml` | `nas_server, linux_hosts` | Configure NFS server and clients. | `ansible-playbook playbooks/storage/nfs.yml --syntax-check` |
| `samba.yml` | `samba_hosts` | Configure Samba server. | `ansible-playbook playbooks/storage/samba.yml --syntax-check` |
| `storage-status.yml` | `linux_hosts` | Deploy storage-status utility. | `ansible-playbook playbooks/storage/storage-status.yml --syntax-check` |
| `virtiofs.yml` | `proxmox_nodes, vms` | Configure VirtioFS shares. | `ansible-playbook playbooks/storage/virtiofs.yml --syntax-check` |
| `vm-storage-gate.yml` | `proxmox_nodes` | Deploy per-VM storage gate hookscript. | `ansible-playbook playbooks/storage/vm-storage-gate.yml --syntax-check` |
| `zfs.yml` | `nas_server` | Configure ZFS (snapshots, scrub, tuning, properties, ACLs). | `ansible-playbook playbooks/storage/zfs.yml --syntax-check` |
