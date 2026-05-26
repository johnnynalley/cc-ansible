# Proxmox Templates

## Templates

- `proxmox-cluster-firewall.fw.j2`: Datacenter firewall rules.
- `proxmox-node-firewall.fw.j2`: Node firewall rules.
- `proxmox-vm-firewall.fw.j2`: VM/CT firewall rules.
- `proxmox-virtiofs-directory.cfg.j2`: VirtioFS directory mapping snippets.
- `pbs-connectivity-check.sh.j2`: PBS connectivity check helper.
- `wait-for-mounts.sh.j2`: VM storage-gate hookscript.

## Consumers

- `playbooks/proxmox/proxmox-firewall.yml`
- `playbooks/storage/virtiofs.yml`
- `playbooks/proxmox/proxmox-backup-server.yml`
- `playbooks/storage/vm-storage-gate.yml`

## Safety Notes

- Proxmox firewall and pmxcfs-backed files are high-impact. Use check mode and
  review rendered diffs before applying.
