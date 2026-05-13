# CC-Ansible

> **Last updated:** 2026-05-12

Ansible automation for Johnny's homelab infrastructure (4 Proxmox nodes, 10 VMs/LXCs, Ansible controller LXC, gaming workstation, ThinkPad laptop, MacBook).

**Repository**: https://github.com/johnnynalley/cc-ansible (public)

## Quick Start

```bash
# From the repo directory (on ansible-lxc)
cd ~/cc-ansible

# Run a specific playbook
ansible-playbook playbooks/packages.yml

# Run all playbooks
ansible-playbook site.yml

# Do not use --limit; playbooks should be safe across their configured target

# Interactive menu
./bin/ansible-menu
```

## Directory Structure

```
cc-ansible/
├── ansible.cfg                  # Ansible configuration
├── site.yml                     # Master playbook (runs all)
├── inventory/
│   ├── hosts.ini               # Host inventory (Tailscale IPs)
│   ├── group_vars/
│   │   ├── all/                # Global defaults
│   │   │   ├── vars.yml        # Non-secret variables
│   │   │   └── vault.yml       # Encrypted secrets (create from .example)
│   │   ├── linux_hosts/        # All Linux hosts
│   │   ├── debian_hosts/       # Debian/Ubuntu specific
│   │   ├── arch_hosts/         # Arch Linux specific
│   │   ├── macos_hosts/        # macOS specific
│   │   ├── proxmox_nodes/      # Proxmox hypervisors
│   │   ├── nas_server/         # NAS role (NFS, Samba, ZFS, mergerfs, mounts)
│   │   ├── vms/                # Virtual machines (qemu-guest-agent)
│   │   ├── lxcs/               # LXC containers
│   │   ├── vms_lxcs/           # Shared VM+LXC configs
│   │   ├── orchestrator/       # Ansible controller (ansible-lxc)
│   │   ├── development/        # Dev tooling (gh, shellcheck, yq)
│   │   └── backup_clients/     # Hosts with restic backups
│   └── host_vars/
│       ├── ts440/              # Per-host overrides
│       ├── pve-alto/
│       ├── pve-herc/
│       ├── pve-m70q/
│       ├── docker-vm/
│       ├── media-vm/
│       ├── nextcloud-vm/       # Nextcloud AIO with VirtioFS storage
│       ├── homebridge-lxc/
│       ├── syncthing-lxc/
│       ├── pbs-lxc/              # Proxmox Backup Server (CT 105, pve-herc)
│       ├── pi5-01/
│       ├── jn-desktop/         # CachyOS gaming workstation
│       ├── jn-t14s-lin/       # ThinkPad T14s (Kubuntu)
│       ├── dev-vm/            # Development VM (Ubuntu 24.04, pve-m70q)
│       └── openclaw-vm/       # OpenClaw AI agent (Ubuntu 25.10, ts440)
├── playbooks/
│   ├── packages.yml            # Multi-platform package installation
│   ├── smartmontools.yml       # SMART disk monitoring (Apprise alerts)
│   ├── e1000e-tuning.yml        # Intel e1000e NIC tuning (disable EEE/TSO)
│   ├── apcupsd.yml             # UPS monitoring (Apprise alerts, master/slave)
│   ├── bootstrap.yml           # Initial user/SSH setup (Debian + Arch)
│   ├── ssh-hardening.yml       # SSH security configuration
│   ├── auto-updates.yml        # Scheduled system updates (Proxmox kernel reboot detection)
│   ├── unattended-upgrades.yml # Daily security patches (Debian/Ubuntu, incl. workstations)
│   ├── network-recovery.yml    # Network watchdog + Tailscale recovery
│   ├── wifi.yml                # WiFi powersave + suspend/resume fix
│   ├── restic.yml              # B2 offsite backup configuration
│   ├── local-restic.yml        # Local backups to ts440 ZFS
│   ├── mergerfs.yml            # MergerFS media pool + balance script (nas_server)
│   ├── mergerfs-recovery.yml   # USB-SATA auto-remount + watchdog + media-app refresh (nas_server)
│   ├── zfs.yml                 # ZFS snapshots, scrub, ARC tuning, property enforcement
│   ├── nfs.yml                 # NFS server/client setup
│   ├── filesystem-mounts.yml   # Local NTFS/exFAT mounts
│   ├── samba.yml               # Samba/Time Machine setup
│   ├── docker-stacks.yml       # Docker Compose stack deployment
│   ├── gluetun-watchdog.yml    # Gluetun VPN crash loop watchdog
│   ├── docker-auto-update.yml  # Auto-update selected Docker containers (timer)
│   ├── virtiofs.yml            # VirtioFS shares (Proxmox → VMs)
│   ├── rclone-sync.yml         # rclone OneDrive → Nextcloud sync (macbook-pro/pi5-01)
│   ├── git-sync.yml            # Auto-pull from GitHub on ts440 (for Nextcloud)
│   ├── nextcloud-scan.yml      # Periodic occ files:scan for external storage
│   ├── claude-memory-sync.yml  # Sync Claude Code memory archive to NAS for Nextcloud
│   ├── codex-memory-sync.yml   # Sync Codex CLI memory to NAS for Nextcloud
│   ├── proxmox-firewall.yml    # Proxmox firewall rules (datacenter/node/VM)
│   ├── proxmox-backup-server.yml # PBS install, datastore, API token, PVE registration, backup jobs, connectivity check
│   ├── proxmox-notifications.yml # PVE webhook notifications → Apprise → Pushover
│   ├── openclaw.yml             # OpenClaw AI agent (npm, gateway, timers)
│   └── swap.yml                # Swap configuration (zvol for ZFS, file for others)
├── tasks/
│   ├── locale.yml              # Debian locale setup
│   ├── tailscale.yml           # Tailscale installation + restart policy
│   ├── fastfetch.yml           # Fastfetch installation
│   ├── docker.yml              # Docker CE installation
│   ├── sanoid.yml              # ZFS snapshot automation
│   ├── zfs-scrub.yml           # ZFS scrub, ARC tuning, ACLs
│   ├── nfs-server.yml          # NFS server configuration
│   ├── nfs-client.yml          # NFS client mounts
│   ├── filesystem-mounts.yml   # NTFS/exFAT local drive mounts
│   ├── samba.yml               # Samba server configuration
│   └── docker-network.yml      # Ensure Docker networks exist
├── templates/
│   ├── exports.j2              # NFS exports template
│   ├── smb.conf.j2             # Samba configuration template
│   ├── sanoid.conf.j2          # ZFS snapshot policy configuration
│   ├── smartd.conf.j2          # smartd monitoring config
│   ├── apcupsd.conf.j2         # apcupsd daemon config (master/slave)
│   ├── apcupsd-event-notify.sh.j2  # apcupsd Apprise notification
│   ├── smartd-notify.sh.j2     # smartd Apprise notification
│   ├── mergerfs-media.mount.j2 # MergerFS systemd mount unit
│   ├── mergerfs-balance.conf.j2 # mergerfs-balance default path excludes
│   ├── avahi-timemachine.service.j2  # Time Machine mDNS advertisement
│   ├── docker-stacks.service.j2  # Docker stacks systemd service
│   ├── auto-updates-debian.sh.j2  # Debian auto-updates with notifications
│   ├── auto-updates-arch.sh.j2  # Arch auto-updates with notifications
│   ├── 50unattended-upgrades.j2  # Security-only unattended-upgrades config
│   ├── unattended-upgrades-notify.sh.j2  # Post-upgrade Apprise notification
│   ├── network-watchdog.sh.j2  # Network recovery watchdog with notifications
│   ├── gluetun-watchdog.sh.j2  # Gluetun VPN crash loop watchdog
│   ├── docker-auto-update.sh.j2  # Docker auto-update script
│   ├── diun.yml.j2              # Diun config (schedule + notifications)
│   ├── proxmox-virtiofs-directory.cfg.j2  # VirtioFS directory mappings
│   ├── proxmox-cluster-firewall.fw.j2    # Datacenter firewall rules
│   ├── proxmox-node-firewall.fw.j2       # Node-level firewall rules
│   ├── proxmox-vm-firewall.fw.j2         # VM/CT firewall rules
│   └── openclaw-update-check.sh.j2      # OpenClaw npm update checker
├── scripts/
│   ├── docker-stack-diff       # Per-service image change detection with version labels
│   ├── mergerfs-balance        # ZFS-compatible mergerfs branch balancer
│   └── storage-status          # Storage usage report (ZFS + mergerfs)
└── bin/
    └── ansible-menu            # Interactive playbook launcher
```

## Group Hierarchy

```
managed_hosts
├── linux_hosts
│   ├── debian_hosts
│   │   ├── proxmox_nodes (ts440, pve-alto, pve-herc, pve-m70q)
│   │   ├── vms_lxcs
│   │   │   ├── vms (docker-vm, media-vm, nextcloud-vm, dev-vm, freepbx-vm, openclaw-vm) ← gets qemu-guest-agent
│   │   │   └── lxcs (homebridge-lxc, syncthing-lxc, pbs-lxc)
│   │   ├── orchestrator (ansible-lxc, pi5-01)
│   │   └── jn-t14s-lin ← ThinkPad T14s (Kubuntu)
│   └── arch_hosts (jn-desktop) ← CachyOS gaming workstation
└── macos_hosts (macbook-pro)

workstations (jn-desktop, jn-t14s-lin, macbook-pro) ← no auto-recovery/reboots

nas_server (ts440) ← portable NAS role group

development (dev-vm) ← dev tooling (gh, shellcheck, yq)

docker_hosts (docker-vm, media-vm, nextcloud-vm, openclaw-vm) ← Docker Compose stacks

backup_clients
├── proxmox_nodes
├── vms_lxcs
├── orchestrator
├── workstations
└── arch_hosts
```

## Vault Setup

1. Create the vault password file on the controller:
   ```bash
   mkdir -p ~/.ansible
   echo 'your-vault-password' > ~/.ansible/vault_pass.txt
   chmod 600 ~/.ansible/vault_pass.txt
   ```

2. Create vault files from examples:
   ```bash
   # Global secrets (sudo password, B2 creds, etc.)
   ansible-vault create inventory/group_vars/all/vault.yml
   
   # Per-host overrides (if different sudo password)
   ansible-vault create inventory/host_vars/ts440/vault.yml
   ```

3. Required vault variables in `group_vars/all/vault.yml`:
   ```yaml
   # Default sudo password (override in host_vars if different)
   ansible_become_password: "your-sudo-password"
   ansible_become_pass: "your-sudo-password"
   
   # Bootstrap password for new admin user
   admin_default_password: "your-user-password"
   
   # Backblaze B2 credentials
   b2_key_id: "your-b2-key-id"
   b2_application_key: "your-b2-app-key"
   
   # Restic repository encryption
   restic_password: "your-restic-password"
   ```

## SSH Authentication

Ansible uses a dedicated passwordless SSH key (`~/.ssh/ansible_ed25519` on ansible-lxc) for all hosts, configured in `ansible.cfg` as `private_key_file`.

- **Linux hosts**: Tailscale SSH is the primary transport; the dedicated key is a fallback if Tailscale is down
- **Proxmox nodes**: root SSH is disabled by default, with a `Match Address` exception for key-only migration SSH from the Proxmox LAN peer IPs in `inventory/group_vars/proxmox_nodes/vars.yml`
- **macOS (macbook-pro)**: Tailscale SSH doesn't work (App Store sandboxed build), so it uses the dedicated key exclusively. SSH is restricted to Tailscale only via `ListenAddress` in sshd_config

`bootstrap.yml` deploys both the personal key (passphrase-protected, for manual SSH) and the Ansible automation key (passwordless) to new hosts.

**Tailscale SSH MOTD**: `ssh-hardening.yml` deploys `/etc/pam.d/remote` so MOTD displays on Tailscale SSH login. Ubuntu hosts get a rich MOTD (system info, updates) via `landscape-common` + `update-notifier-common`.

## Bootstrap New Host

```bash
# Copy Ansible SSH key to the admin user first
ssh-copy-id -i ~/.ssh/ansible_ed25519.pub johnny@<LAN_IP>

# Bootstrap (uses su, not sudo — sudo may not be installed yet)
ansible-playbook playbooks/bootstrap.yml --ask-become-pass

# Then run full site.yml (installs Tailscale, packages, SSH hardening, etc.)
ansible-playbook site.yml
```

## Adding New Hosts

### Adding a VM:
1. Add to `[vms]` in `hosts.ini`
2. Host automatically gets `qemu-guest-agent` via `packages_vms_extra`
3. Create `host_vars/<hostname>/` if needed for overrides

### Adding an LXC:
1. Add to `[lxcs]` in `hosts.ini`
2. No qemu-guest-agent (correct for containers)
3. Create `host_vars/<hostname>/` if needed

### Adding a Debian/Ubuntu workstation:
1. Add to `[debian_hosts]` in `hosts.ini` (direct member, not via child group)
2. Add to `[workstations]` in `hosts.ini`
3. If using sudo-rs (Kubuntu 25.10+), set `ansible_become_flags: "-S"` and configure passwordless sudo
4. Packages playbook will use apt

### Adding an Arch host:
1. Add to `[arch_hosts]` in `hosts.ini`
2. Host automatically inherits from `linux_hosts`
3. Packages playbook will use pacman

### Adding a macOS host:
1. Add to `[macos_hosts]` in `hosts.ini`
2. Ensure Homebrew is installed
3. Packages playbook will use brew

## Package Variables

Packages are merged from multiple sources (all applicable variables combined):

| Variable | Scope | Example |
|----------|-------|---------|
| `packages_linux_common` | All Linux | curl, git, vim, htop, tealdeer |
| `packages_debian_extra` | Debian/Ubuntu | dnsutils, locales |
| `packages_arch_extra` | Arch Linux | bind-tools |
| `packages_macos_common` | macOS | coreutils, mas, tldr |
| `packages_proxmox_extra` | Proxmox nodes | smartmontools, pve-headers |
| `packages_vms_extra` | VMs only | qemu-guest-agent |
| `packages_lxcs_extra` | LXCs only | (empty by default) |
| `packages_arch_workstations_extra` | Arch workstations | nextcloud-client, localsend, discord |
| `packages_debian_workstations_extra` | Debian workstations | nextcloud-desktop, flatpak |
| `flatpak_workstations` | Debian workstations | Discord, LocalSend (Flathub IDs) |
| `packages_orchestrator_extra` | Orchestrator | ansible, nfs-common |
| `packages_host_extra` | Per-host | (custom per host) |

## Playbook Reference

| Playbook | Target | Description |
|----------|--------|-------------|
| `site.yml` | varies | Run all playbooks in order |
| `packages.yml` | `managed_hosts` | Install baseline packages (multi-platform) |
| `smartmontools.yml` | `linux_hosts` | SMART disk monitoring with Apprise push alerts |
| `e1000e-tuning.yml` | `proxmox_nodes` | Disable EEE/TSO on Intel e1000e NICs to prevent hardware TX hangs |
| `apcupsd.yml` | `proxmox_nodes` | UPS monitoring with Apprise push alerts (ts440 USB master, others slave). Staggers slave startup to avoid NIS mutex contention |
| `bootstrap.yml` | `linux_hosts` | Create admin user, SSH keys, sudo setup, timezone (Debian + Arch) |
| `ssh-hardening.yml` | `linux_hosts` | SSH security (key auth, disable password) |
| `auto-updates.yml` | `linux_hosts` | Configure automatic updates + reboot (Sun, staggered for Proxmox quorum) |
| `unattended-upgrades.yml` | `debian_hosts` | Daily security patches (incl. workstations, Proxmox blacklist) |
| `network-recovery.yml` | `linux_hosts` | Network watchdog for auto-recovery after outages |
| `wifi.yml` | `linux_hosts` | WiFi powersave disable, optional PCI FLR or module reload resume fix |
| `restic.yml` | `backup_clients` | B2 offsite backup with systemd timer |
| `local-restic.yml` | `backup_clients` | Hourly backups to ts440 ZFS |
| `mergerfs.yml` | `nas_server` | MergerFS media pool mount + balance script + config excludes |
| `mergerfs-recovery.yml` | `nas_server` | USB-SATA branch auto-remount (udev) + mount watchdog + Plex/Sonarr/Radarr API refresh on recovery |
| `zfs.yml` | `nas_server` | ZFS snapshots (sanoid), scrub, ARC tuning, property enforcement, ACLs |
| `nfs.yml` | `nas_server` + clients | NFS server/client configuration |
| `filesystem-mounts.yml` | `linux_hosts` | Local filesystem mounts (NTFS, exFAT) |
| `samba.yml` | `linux_hosts` | Samba shares + Time Machine (ts440 + pve-herc) |
| `docker-stacks.yml` | `docker_hosts` | Deploy Docker Compose stacks (per-service update reporting with version diffs) |
| `gluetun-watchdog.yml` | media-vm | Gluetun VPN crash loop detection, port forwarding monitoring, and auto-restart |
| `docker-auto-update.yml` | `docker_hosts` | Auto-update selected containers every 6h with major version guard |
| `virtiofs.yml` | `proxmox_nodes`, `vms` | Configure VirtioFS shares between Proxmox hosts and VMs |
| `rclone-sync.yml` | `managed_hosts` | rclone sync from OneDrive to Nextcloud (macbook-pro via launchd, pi5-01 via systemd) |
| `git-sync.yml` | `nas_server` | Auto-pull from GitHub every 5 minutes (Nextcloud External Storage) |
| `nextcloud-scan.yml` | nextcloud-vm | Periodic `occ files:scan` for external storage (every 10 min) |
| `claude-memory-sync.yml` | `nas_server`, ansible-lxc | Rsync Claude Code memory archive to NAS for Nextcloud access (every 10 min) |
| `codex-memory-sync.yml` | `nas_server`, ansible-lxc | Rsync Codex CLI memory to NAS for Nextcloud access (every 10 min) |
| `proxmox-firewall.yml` | `proxmox_nodes` | Deploy Proxmox firewall rules (datacenter, node, VM/CT) |
| `proxmox-backup-server.yml` | pbs-lxc, `proxmox_nodes` | Install PBS, configure datastore/prune/GC/API token, register on all PVE nodes, create vzdump backup jobs, deploy connectivity check |
| `proxmox-notifications.yml` | `proxmox_nodes` | PVE webhook notification targets + matchers → Apprise → Pushover |
| `proxmox-ha.yml` | `proxmox_nodes` | Stop/disable/mask `pve-ha-{lrm,crm}` cluster-wide (no HA resources configured; removes fencing risk). Driven by `pve_ha_enabled` (default `false`) |
| `vm-storage-gate.yml` | `proxmox_nodes` | Per-VM start gate: hookscript blocks `qm start`/`pct start` if VM's declared host mountpoints aren't mounted. Per-VM declarations in `host_vars/<vm>/storage.yml` |
| `openclaw.yml` | `linux_hosts` | OpenClaw AI agent (npm install, gateway service, repo-sync/update-check timers) |

## NFS Configuration

TS440 serves NFS exports via Tailscale. VMs have been migrated to local config storage and no longer depend on NFS.

### Server Exports (ts440)

| Export Path | Bind Source | Client | Purpose |
|-------------|-------------|--------|---------|
| `/srv/exports/configs` | `/srv/nas-zfs/configs` | pi5-01 | Ansible repo only |
| `/srv/nas-zfs` | (direct, no bind) | jn-desktop | Full NAS access with `crossmnt` |

### Client Mounts

| Host | Mount Point | Remote Path |
|------|-------------|-------------|
| pi5-01 | `/srv/configs` | `100.71.188.16:/exports/configs` |
| jn-desktop | `/mnt/nas-zfs` | `100.71.188.16:/nas-zfs` |

**Note**: VMs no longer use NFS. All configs are stored locally:
- docker-vm: `/opt/caddy/`, `/opt/vaultwarden/`, `/opt/uptime-kuma/`, etc.
- media-vm: `/opt/media-stack/` (uses VirtioFS for media access + archive)
- nextcloud-vm: `/opt/nextcloud/` (uses VirtioFS for data storage + archive read-only)

**Archive**: ZFS dataset `nas_zfs/archive` at `/srv/nas-zfs/archive` for ISOs and general archival. Shared via VirtioFS to media-vm (rw) and nextcloud-vm (ro, Nextcloud External Storage at `/srv/external/archive`).

Ansible repo on ansible-lxc: `~/cc-ansible`
Legacy copy on pi5-01: `/srv/configs/ansible/cc-ansible` (NFS from ts440, auto-synced from GitHub)

## Samba Configuration

Samba is managed by `playbooks/samba.yml` and runs on any `linux_hosts` host with `smb_shares` defined — currently ts440 (nas_server) and pve-herc.

### ts440 Shares

| Share | Path | Purpose |
|-------|------|---------|
| Configs | `/mnt/nas-zfs/configs` | Ansible repo only (app configs migrated to VMs) |
| Backups | `/mnt/nas-zfs/backups` | General backups |
| NAS-ZFS | `/mnt/nas-zfs` | Full ZFS pool root |
| NAS-01, NAS-02 | `/srv/nas-01`, `/srv/nas-02` | Individual drive access |

### pve-herc Shares

| Share | Path | Purpose |
|-------|------|---------|
| Time Machine | `/srv/pbs-data/timemachine` | macOS Time Machine (active, 1TB drive) |

### Connecting from macOS

```bash
# In Finder: Cmd+K, then enter:
smb://100.71.188.16/Configs          # ts440
smb://100.97.139.95/Time Machine     # pve-herc (Time Machine destination)
```

### Samba User Management

```bash
# Set Samba password (interactive)
ansible ts440 -m shell -a "smbpasswd -a johnny" --become
ansible pve-herc -m shell -a "smbpasswd -a johnny" --become

# List Samba users
ansible pve-herc -m shell -a "pdbedit -L" --become
```

## Network Recovery

Automatic recovery after router/WiFi restarts via `network-recovery.yml`:

- **Network Watchdog** runs every 60 seconds:
  - Ensures interfaces are UP (catches link flaps where carrier recovers but interface stays DOWN)
  - Fixes Proxmox bridge interfaces that got detached (`eno1` removed from `vmbr0`)
  - Restarts networking/DHCP after gateway failures
  - Restarts Tailscale after connectivity failures
  - Restarts all Docker containers on recovery to clear stale state

- **Tailscale Online Target**: Services depend on `tailscale-online.target` instead of `tailscaled.service` to ensure Tailscale is actually connected before starting.

Check status: `journalctl -t network-watchdog -f`

## Gluetun VPN Watchdog

Gluetun's internal VPN restart doesn't clean up tun0 routes, causing crash loops (`RTNETLINK answers: File exists`). The watchdog (`gluetun-watchdog.yml`) runs every 60 seconds on media-vm, detects the loop via Docker healthcheck, and does a full `docker compose up -d --force-recreate` of Gluetun + qBittorrent after 3 consecutive failures. Force-recreate (not just restart) is required to destroy the network namespace and clear stale routes. Also monitors port forwarding via Gluetun's internal port file — if the forwarded port is missing for 5 consecutive checks (~5 minutes), force-recreates to get a fresh port assignment. Sends silent Pushover notification on recovery or port forwarding loss (`push-quiet` tag). Rate-limited to 5 restarts/hour.

Check status: `journalctl -t gluetun-watchdog -f`

## Docker Auto-Update

Selected containers are auto-updated every 6 hours via systemd timer (`docker-auto-update.yml`). Opt-in per stack with `auto_update: true` or per service with `auto_update_services: [name]` in `host_vars/<hostname>/docker.yml`. Currently auto-updated: Caddy, Seerr, and Loki-Grafana (docker-vm), Gluetun and LazyLibrarian (media-vm), Diun (all 3 VMs). Pulls/builds new images, uses `docker-stack-diff` to detect changes, only recreates if images changed. Gluetun uses `--force-recreate` with qBittorrent. **Major version guard**: blocks major version bumps (e.g., `7.x` → `8.x`) and sends a Time Sensitive notification instead of auto-updating. Per-stack opt-out with `major_guard: false`. Config in `group_vars/docker_hosts/auto-update.yml`.

Check status: `journalctl -u docker-auto-update`, `systemctl list-timers docker-auto-update*`

## ZFS Configuration

Managed by `zfs.yml` — snapshots, scrub, ARC tuning, property enforcement, ACLs:

- **Pools**: `nas_zfs` (2x8TB mirror), `media-01` (3TB), `media-02` (3TB)
- **Snapshots**: Sanoid timer every 15 minutes
- **Scrub**: Weekly (Sunday 2am) via systemd timer
- **ARC**: 6GB max (`/etc/modprobe.d/zfs.conf`) — bumped from 1GB after ts440 RAM upgrade to 32GB (2026-05-12), then trimmed from 8GB after openclaw-vm moved to ts440 because 8GB caused host swap/PSI during balance + backups
- **Properties**: Automatically enforced via `zfs set` (compression, acltype, recordsize, atime)
- **Config**: `group_vars/nas_server/zfs.yml`

### Retention Policies

| Dataset | Hourly | Daily | Weekly | Monthly |
|---------|--------|-------|--------|---------|
| configs, appdata, files, nextcloud, media/photos | 24 | 7 | 4 | 6 |
| backups | - | 7 | 4 | 3 |
| media/plex, media/podcasts | ignored | ignored | ignored | ignored |

### Commands

```bash
# Check sanoid status
ansible ts440 -m shell -a "systemctl status sanoid.timer" --become

# List snapshots
ansible ts440 -m shell -a "zfs list -t snapshot -o name,creation,used -s creation" --become

# Restore from snapshot
ls /srv/nas-zfs/.zfs/snapshot/
cp /srv/nas-zfs/.zfs/snapshot/autosnap_2026-01-26_hourly/configs/file.txt /srv/nas-zfs/configs/
```

## mergerfs Pool (ts440)

`/srv/media` is a mergerfs union of 7 branches:

| Branch | Drive | Type |
|--------|-------|------|
| `/srv/nas-01/media` | 2TB Lacie SSD | ext4 |
| `/srv/nas-02/media` | 2TB LUKS | ext4 on dm-crypt |
| `/srv/nas-zfs/media` | nas_zfs 8TB mirror | ZFS |
| `/srv/media-01/media` | 3TB | ZFS |
| `/srv/media-02/media` | 3TB | ZFS |
| `/srv/media-03/media` | 2TB Hitachi HDD via USB-SATA | ext4 |
| `/srv/media-04/media` | 2TB ex-PBS drive via USB-SATA | ext4 |

- **Create policy**: `epmfs` (existing path most free space) — new files land on the same branch as the existing show/movie directory, which is critical for Sonarr/Radarr hardlinks. Falls back to mfs when no existing path found.
- **USB-SATA drives**: `x-systemd.device-timeout=60s` in fstab — USB enumeration requires more time than the default 5s
- **Config**: `group_vars/nas_server/mergerfs.yml`

## mergerfs-balance

Balances files across mergerfs branches by moving from fullest to emptiest. ZFS-aware (uses `zfs list` for accurate space reporting).

- **Default excludes**: `/etc/mergerfs-balance.conf` protects irreplaceable data on nas_zfs (photos, archive, books) from moving to single-drive pools
- **Config variable**: `mergerfs_balance_exclude_paths` in `group_vars/nas_server/mergerfs.yml`
- **CLI excludes**: `-E` flags merge with config excludes (additive)
- **VirtioFS caveat**: After balancing, media-vm needs a full stop/start (`qm stop`/`qm start`) to clear virtiofsd's stale directory cache

```bash
# Normal balance (5% target spread, config excludes auto-loaded)
mergerfs-balance /srv/media -p 5

# Dry run
mergerfs-balance /srv/media -p 5 --dry-run

# Additional CLI excludes on top of config
mergerfs-balance /srv/media -p 5 -E "/srv/nas-zfs/media/music/*"
```

## Immich (Photo/Video Management)

Immich runs on media-vm as its own Docker Compose stack, sharing the Quadro P2200 GPU with Plex.

- **URL**: `https://photos.jnalley.me` (Tailscale only)
- **Storage**: `/srv/photos` (VirtioFS from `nas-zfs/media/photos`)
- **Config/DB**: `/opt/immich/` (backed up hourly via restic)
- **Containers**: `immich_server` (port 2283), `immich_machine_learning` (CUDA, 2GB mem limit), `immich_postgres`, `immich_redis`, `immich_folder_album_creator`
- **External library**: `/srv/untitled` (VirtioFS from `nas-zfs/media/archive/untitled`) — indexed in-place, auto-locked every 6h

```bash
# Check container status
ansible media-vm -m shell -a "docker ps --filter name=immich" --become

# Check GPU in ML container
ansible media-vm -m shell -a "docker exec immich_machine_learning nvidia-smi" --become

# Manually trigger auto-lock
ansible media-vm -m shell -a "docker exec immich_folder_album_creator python3 -m immich_auto_album" --become
```

## Recyclarr Configuration

Recyclarr syncs TRaSH Guides custom formats to Sonarr/Radarr on media-vm.

- **Config**: `/opt/media-stack/recyclarr/recyclarr.yml`
- **Profiles**: `1080p-Anime`, `1080p`
- **Anime scoring**: Dual Audio +3000, LQ Groups -10000 (default), x265 +50
- **Manual CFs**: 2160p (-1500), Portuguese Releases (-10000) - created directly in Sonarr

```bash
# Manual sync
ansible media-vm -m shell -a "docker exec recyclarr recyclarr sync" --become
```

## Torrent Fallback (Gluetun + qBittorrent)

Torrents via Nyaa as fallback when Usenet doesn't have a release.

- **VPN**: ProtonVPN WireGuard via Gluetun container (NL P2P servers, `WIREGUARD_MTU=1420` required)
- **qBittorrent**: `network_mode: service:gluetun`, WebUI on port 8085 at `qbit.jnalley.me`
- **Priority**: SABnzbd (1) > qBittorrent (2) - Usenet preferred, torrents fallback
- **Disk I/O**: POSIX-compliant (required for VirtioFS compatibility)
- **Incomplete downloads**: Both SABnzbd and qBittorrent use the Lacie SSD for temp storage, isolated in separate subdirs (`usenet/` and `torrents/`)
- **VirtioFS note**: All containers use `/srv/media/plex:/data` to prevent stale file handles. Hardlinks work across all clients.
- **Automatic port sync**: systemd path unit watches Gluetun's port file and updates qBittorrent via API when VPN reconnects
- **Known bad server**: ProtonVPN node-nl-215 (103.69.224.3) has broken port forwarding — gluetun-watchdog should detect and force-recreate
- **Tuning**: `max_active_downloads: 5` to reduce I/O contention with uploads; `max_active_uploads: 200`

```bash
# Verify VPN is working
ansible media-vm -m shell -a "docker exec gluetun wget -qO- https://ipinfo.io/json" --become

# Check port sync logs
journalctl -t qbit-port-sync -n 10
```

## Nextcloud AIO (nextcloud-vm)

Nextcloud All-in-One running on VM 101 (ts440) with VirtioFS storage access.

- **VM Specs**: 4GB RAM, 2 cores, 32GB local disk
- **VirtioFS Mount**: `/srv/nextcloud` → `/srv/nas-zfs/nextcloud` on ts440
- **Data Directory**: `/srv/nas-zfs/nextcloud/data` (owned by www-data, UID 33)
- **Access**:
  - Admin: `https://100.112.46.126:8080` (Tailscale only)
  - Web: `https://nextcloud.jnalley.me` (via Caddy on docker-vm)
- **Public Access**: Cloudflare Tunnel (no port forwarding, hides home IP)

```bash
# Check Nextcloud containers
ansible nextcloud-vm -m shell -a "docker ps" --become
```

## docker-vm Services

docker-vm (VM 110 on pve-m70q) runs infrastructure services:

| Service | URL | Purpose |
|---------|-----|---------|
| Caddy | - | Reverse proxy (DNS-01 via Cloudflare) |
| Vaultwarden | `vaultwarden.jnalley.me` | Password manager |
| Portainer CE | `portainer.jnalley.me` | Multi-host Docker UI (edge agents on media-vm/nextcloud-vm/openclaw-vm) |
| Seerr | `requests.jnalley.me` | Media requests (Plex OAuth) |
| Cloudflared | - | Cloudflare Tunnel (public access) |
| Apprise API | `apprise.jnalley.me` | Notification router (Pushover + email) |
| FreshRSS | `rss.jnalley.me` | RSS aggregator (Google Reader API for Reeder) |
| Diun | - | Docker image update notifier |
| Grafana | `grafana.jnalley.me` | Loki log dashboards |
| Dispatcharr | `iptv.jnalley.me` | HDHomeRun emulator for Plex Live TV (disabled — free streams unreliable) |
| OpenClaw | `openclaw.jnalley.me` | AI agent gateway (proxied to openclaw-vm:18789) |
| ~~Uptime Kuma~~ | ~~`status.jnalley.me`~~ | Disabled 2026-04-13 (unused); compose preserved at `/opt/uptime-kuma/` |
| ~~Homepage~~ | ~~`home.jnalley.me`~~ | Disabled 2026-04-13 (unused); compose preserved at `/opt/homepage/` |
| ~~Gitea~~ | ~~`git.jnalley.me`~~ | Disabled 2026-04-13 (unused); compose preserved at `/opt/gitea/` |

Stacks support `start: true/false` in `docker.yml` to control service state.

## Cloudflare Tunnel

Public internet access without port forwarding. Tunnel runs on docker-vm.

**Public services:**

| URL | Backend |
|-----|---------|
| `nextcloud.jnalley.me` | nextcloud-vm:11000 |
| `requests.jnalley.me` | seerr:5055 |

**Management:** Cloudflare Zero Trust → Networks → Connectors

```bash
# Check tunnel status
ansible docker-vm -m shell -a "docker logs cloudflared 2>&1 | grep -i registered" --become
```

## VirtioFS Playbook

`virtiofs.yml` manages VirtioFS shares between Proxmox hosts and VMs:

1. **Host side** (Proxmox): Creates `/etc/pve/mapping/directory.cfg` and adds VirtioFS lines to VM configs
2. **Guest side** (VM): Creates mount points and fstab entries

Configuration in `host_vars/<host>/virtiofs.yml`:
```yaml
# Proxmox host
virtiofs_directory_mappings:
  - name: plex_library
    path: /srv/plex-library
virtiofs_host_configs:
  - vmid: 101
    name: nextcloud_data
    host_path: /srv/nas-zfs/nextcloud
    cache: never

# VM guest
virtiofs_mounts:
  - name: nextcloud_data
    mount_point: /srv/nextcloud
```

## Proxmox Firewall

`proxmox-firewall.yml` manages firewall rules at three levels:

1. **Datacenter** (`cluster.fw`): IP sets and security groups
2. **Node** (`host.fw`): Node-level rules (API, SSH, cluster)
3. **VM/CT** (`<vmid>.fw`): Per-VM rules with default deny

Configuration:
- `group_vars/proxmox_nodes/firewall.yml` - Shared IP sets and security groups
- `host_vars/<node>/firewall.yml` - Node and VM rules

```bash
# Deploy firewall rules
ansible-playbook playbooks/proxmox-firewall.yml

# Verify rules
ansible ts440 -m shell -a "cat /etc/pve/firewall/cluster.fw" --become
```

## VirtioFS Memory Optimization

media-vm uses VirtioFS mounts with `cache=never` to prevent host memory exhaustion:

```bash
# In /etc/pve/qemu-server/100.conf on ts440:
virtiofs0: plex_library,cache=never
virtiofs3: incomplete_downloads,cache=never
virtiofs4: media,cache=never
virtiofs6: photos,cache=never
```

Without `cache=never`, virtiofsd daemons cache aggressively (5GB+ each), causing ts440 to swap heavily. With it, they use only a few KB. The VM still caches in its own RAM.

**VirtioFS ACL Limitation**: VirtioFS does **not** pass through POSIX ACLs to guest VMs. Files accessed via VirtioFS must have adequate base permissions (`chmod`) — ACLs set via `setfacl` on the host are invisible to guests. ZFS ACLs are managed by `playbooks/zfs.yml`; normal runs set dataset-root ACLs and default ACLs for new files. Existing-tree recursive ACL repair is intentionally opt-in with `zfs_acl_recursive_repair: true` because it can walk large datasets.

**ts440 memory budget** (32GB total, upgraded from 16GB on 2026-05-12): media-vm 8GB, nextcloud-vm 8GB, openclaw-vm 8GB max / 4GB balloon minimum, homebridge-lxc 736MB, ZFS ARC 6GB (`/etc/modprobe.d/zfs.conf`), Proxmox ~2-3GB. Balloon disabled on media-vm due to GPU passthrough.

## Ansible Environment

Ansible runs on ansible-lxc (CT 104 on pve-m70q, Ubuntu 25.10) with `ansible-core` 2.20 (via Ansible PPA — Ubuntu's 2.19 has a threading bug). The repo clone is at `~/cc-ansible` on ansible-lxc.

ts440 auto-pulls from GitHub every 5 minutes (`git-sync.timer`) to keep the Nextcloud External Storage copy current. nextcloud-vm runs `occ files:scan` every 10 minutes (`nextcloud-scan.timer`) so external storage changes appear automatically. Codex CLI's project memory is synced from ansible-lxc to ts440 every 10 minutes (`codex-memory-sync.timer`) for active Nextcloud access; Claude Code's memory archive continues syncing via `claude-memory-sync.timer` as a dated fallback.

## Tips

- Use `--check` for dry runs
- Use `--diff` to see file changes
- Use `-v` through `-vvvv` for verbosity
- Tags: `ansible-playbook playbooks/packages.yml --tags fastfetch`
- Run site.yml for full configuration: `ansible-playbook site.yml`

## FreePBX (freepbx-vm, VM 130 on pve-herc)

FreePBX 17 / Asterisk 22 PBX server on Debian 12. VoIP.ms SIP trunk with Yealink T54W desk phone. Web GUI: `http://100.97.139.95/admin`. APT pinned to bookworm (`apt_pin_release: bookworm` in host_vars). Sangoma Smart Firewall enabled with Tailscale trusted. Proxmox firewall: SIP, RTP, SSH, web GUI (Tailscale only).

## HomeKit / Home Assistant

- **homebridge-lxc** (CT 102): Bridges Govee devices to HomeKit. Firewall needs TCP 51000-56000 (HAP) + UDP 5353 (mDNS).
- **haos-vm** (VM 120): Home Assistant OS. Some devices chain: Homebridge → HA → HomeKit. Firewall needs TCP 21000-21100 (HAP) + UDP 5353.
- **HA Companion App**: Set both Internal and External URL to `http://homeassistant.hinny-liberty.ts.net:8123`

## rclone Sync (OneDrive to Nextcloud)

Scheduled sync from school OneDrive to Nextcloud via `rclone-sync.yml` on macbook-pro. The OneDrive desktop app syncs files locally, then rclone copies the local folder to Nextcloud via WebDAV (no OneDrive OAuth needed — UTD tenant blocks third-party apps).

- **Schedule**: Every 2 hours (launchd LaunchAgent, runs when logged in)
- **Mode**: `rclone sync` (deletes propagate, safe due to ZFS snapshots + restic)
- **Config**: `host_vars/macbook-pro/rclone-sync.yml`
- **rclone remote**: Only `nextcloud` WebDAV remote needed (configured manually via `rclone config`)
- **Monitoring**: Uptime Kuma push monitor

```bash
# Deploy
ansible-playbook playbooks/rclone-sync.yml

# Manual trigger (on MacBook)
~/.local/bin/rclone-sync

# Check logs
cat ~/Library/Logs/rclone-sync.log

# Re-auth if Nextcloud password changes
rclone config reconnect nextcloud:
```

## Notification Stack (Apprise + Pushover)

Centralized notification router for infrastructure and media alerts using tag-based routing via Pushover.

```
Diun (container updates) ──────┐
smartd (disk health) ──────────┤
apcupsd (UPS power) ───────────┤
auto-updates (weekly) ─────────┼──→ Apprise API (docker-vm) → Pushover "Computer Corner" (Time Sensitive)
unattended-upgrades (daily) ───┤                           → Pushover "Computer Corner" (silent/quiet)
network-watchdog (recovery) ───┤                           → Email (iCloud SMTP)
gluetun-watchdog (VPN) ────────┤                           → Pushover "cc-media-feed" (silent)
docker-auto-update (6h) ───────┤                           → DBC alert receiver (openclaw-vm)
Sonarr/Radarr (grabs) ─────────┤
Seerr (requests) ──────────────┘

Sonarr/Radarr ──→ Discord (native connection, rich embeds with poster art)
```

- **Apprise API**: Notification router at `/opt/notifications/` on docker-vm. Config uses `pover://` URLs for Pushover
- **Two Pushover apps**: "Computer Corner" (normal + quiet priority) and "cc-media-feed" (priority -2, silent/in-app only)
- **Six Apprise tags**: `push` (infrastructure → Computer Corner app, Time Sensitive), `push-quiet` (automated recovery → Computer Corner app, silent), `email` (iCloud SMTP), `media-feed` (Sonarr/Radarr → cc-media-feed app), `media-requests` (Seerr → cc-media-feed app), `dbc` (DBC alert receiver on openclaw-vm). All Ansible-managed notifications include `dbc` automatically via tag variables; Sonarr/Radarr/Seerr have `dbc` added in their web UI Apprise settings
- **Diun**: Container image update notifier on all Docker VMs. Config managed by Ansible (`docker-auto-update.yml`), schedule offset to run after auto-updates. Sends with `push` tag
- **smartd/apcupsd**: Infrastructure alerts, send with `push` tag
- **auto-updates**: Notifies before updates (package count), after completion, and before reboots
- **unattended-upgrades**: Silent notification (`push-quiet`) when daily security patches are applied
- **network-watchdog**: Best-effort notifications on gateway/Tailscale recovery, pre-reboot, and max-reboot exceeded
- **gluetun-watchdog**: Silent notifications on VPN recovery, port forwarding loss, or max-restart exhaustion (`push-quiet` tag)
- **Sonarr/Radarr**: Dual notifications — Discord (rich embeds) + Apprise `media-feed` tag (silent Pushover)
- **Seerr**: Webhook to Apprise with `media-requests` tag (silent Pushover)
- **ntfy**: Commented out in docker-compose, config preserved at `/opt/notifications/ntfy/`. Switched to Pushover because ntfy iOS lacks per-topic push control.
- **Adding apps**: POST to `https://apprise.jnalley.me/notify/notifications` with `tag` field for routing

```bash
# Test notifications
ansible docker-vm -m shell -a "docker exec diun diun notif test" --become

# Check Apprise config
curl -s https://apprise.jnalley.me/json/urls/notifications/?privacy=1

# Edit targets: /opt/notifications/apprise-config/notifications.cfg on docker-vm
# Then restart: cd /opt/notifications && docker compose restart apprise
```

## Centralized Logging (Loki + Grafana + Alloy)

Centralized log aggregation. Loki + Grafana run on docker-vm, Alloy agents on all hosts ship logs over Tailscale.

- **Grafana**: `https://grafana.jnalley.me` (Tailscale only, admin/vault password)
- **Loki**: `http://100.108.254.100:3100` (internal, Alloy agents push here)
- **Retention**: 30 days
- **Config**: `group_vars/all/loki.yml`, `templates/alloy-config.alloy.j2`
- **Playbook**: `ansible-playbook playbooks/logging.yml`

**What's collected:**
- All Linux hosts: systemd journal (unit, transport, level labels)
- Docker hosts: container logs via Docker socket
- macOS: `/var/log/system.log`

**Querying in Grafana:**
```
{host="ts440"}                              # All logs from ts440
{host="media-vm", container="plex"}         # Plex container logs
{unit="docker.service"} |= "error"          # Docker errors across all hosts
```

**Opt out a host:** Set `alloy_enabled: false` in its host_vars.

## Proxmox Backup Server (pbs-lxc)

PBS runs in an unprivileged LXC (CT 105) on pve-herc with a dedicated 1TB ext4 drive. 4 cores, 2GB RAM.

- **Web UI**: `https://100.110.176.37:8007` (login as `root@pam`)
- **Datastore**: `main` at `/srv/pbs-data` (~900GB usable)
- **Storage name**: `pbs-main` (registered on all 4 Proxmox nodes)
- **Backup schedule**: Hourly, all guests except pbs-lxc (Ansible-managed via Play 3)
- **Prune job**: Daily — 24 hourly, 7 daily, 4 weekly, 3 monthly
- **Garbage collection**: Daily (frees space from pruned snapshots — **required**, prune alone doesn't free disk)
- **API auth**: Token `backup@pbs!ansible` (secret in vault)
- **Connectivity check**: Runs at `:59` on all nodes (Play 4), logs to `pbs-check` tag in Loki
- **Config**: `host_vars/pbs-lxc/vars.yml`, `host_vars/pbs-lxc/vault.yml`

```bash
# Deploy/update PBS
ansible-playbook playbooks/proxmox-backup-server.yml

# Check datastore status
ansible pbs-lxc -m shell -a "proxmox-backup-manager datastore list" --become

# Check prune jobs
ansible pbs-lxc -m shell -a "proxmox-backup-manager prune-job list" --become

# Verify storage on PVE nodes
ansible proxmox_nodes -m shell -a "pvesm status | grep pbs" --become
```

**Backup jobs** are Ansible-managed (Play 3 of `proxmox-backup-server.yml`). Config in `group_vars/proxmox_nodes/vars.yml` (`pbs_backup_schedule`, `pbs_backup_exclude`).

### Proxmox Notification Webhooks

PVE notifications route to Apprise → Pushover via webhook. Deployed by `playbooks/proxmox-notifications.yml`.

- **Warnings/errors** (failed backups, fencing): `push` tag → Time Sensitive
- **Info** (package-updates, replication, fencing): `push-quiet` tag → silent
- **Backup success**: suppressed (vzdump info events filtered out to reduce noise)
- Built-in `default-matcher` (mail-to-root) is disabled

```bash
# Deploy/update notification webhooks
ansible-playbook playbooks/proxmox-notifications.yml
```

## OpenClaw (openclaw-vm, VM 140 on ts440)

OpenClaw AI agent platform — personal homelab admin assistant via web UI and Discord. Can read/edit the Ansible repo but cannot run playbooks or SSH into hosts.

- **Web UI**: `https://openclaw.jnalley.me` (Tailscale only)
- **Gateway**: Port 18789, token auth, trustedProxies: docker-vm only
- **VM**: 4 cores, 8GB RAM (balloon 4096MB), Ubuntu 25.10, Node.js 22 (NodeSource)
- **Service**: User-level systemd via `openclaw gateway install` (NOT a custom system service)
- **Config**: `~/.openclaw/openclaw.json` + `.env` — manual, backed up by restic
- **Timers**: repo-sync (5 min), update-check (daily 08:00 → Apprise)
- **Playbook**: `ansible-playbook playbooks/openclaw.yml` (opt-in via `openclaw_enabled`)
- **Mem0 memory**: `@mem0/openclaw-mem0` plugin with Qdrant (localhost:6333), Gemini embeddings, Claude Haiku via OpenRouter for fact extraction. Auto-capture + auto-recall across sessions.
- **dbc ops access**: Least-privilege write on media-vm (`docker-compose.yml`, `.env`) and docker-vm (`Caddyfile`) with scoped apply scripts. Deployed by `user-separation.yml` Phase 1d (`--tags dbc-ops`).

```bash
# Check gateway status (on openclaw-vm)
systemctl --user status openclaw-gateway.service

# Check update-check timer
systemctl list-timers openclaw-update-check*
```

## Planned: WAN Failover

LTE failover on pve-m70q to maintain Cloudflare Tunnel connectivity during Spectrum outages.

- **Hardware**: Netgear LB1120 LTE modem (~$50-80 used) + US Mobile SIM (~$10/mo)
- **Scope**: Only pve-m70q needs failover (runs cloudflared for Nextcloud/Seerr)
- **Detection**: ~30 seconds, Recovery: ~50 seconds

See AGENTS.md "Future Considerations" section for full implementation plan.
