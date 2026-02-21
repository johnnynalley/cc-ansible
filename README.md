# CC-Ansible

> **Last updated:** 2026-02-21

Ansible automation for Johnny's homelab infrastructure (4 Proxmox nodes, 8 VMs/LXCs, Ansible controller LXC, gaming workstation, ThinkPad laptop, MacBook).

**Repository**: https://github.com/johnnynalley/cc-ansible (public)

## Quick Start

```bash
# From the repo directory (on ansible-lxc)
cd ~/cc-ansible

# Run a specific playbook
ansible-playbook playbooks/packages.yml

# Run with limit
ansible-playbook playbooks/packages.yml --limit proxmox_nodes

# Run all playbooks
ansible-playbook site.yml

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
│       └── dev-vm/            # Development VM (Ubuntu 24.04, pve-m70q)
├── playbooks/
│   ├── packages.yml            # Multi-platform package installation
│   ├── msmtp.yml               # SMTP relay (iCloud) for system email
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
│   ├── claude-memory-sync.yml  # Sync Claude Code memory to NAS for Nextcloud
│   ├── proxmox-firewall.yml    # Proxmox firewall rules (datacenter/node/VM)
│   ├── proxmox-backup-server.yml # PBS install, datastore, API token, PVE registration, backup jobs
│   ├── proxmox-notifications.yml # PVE webhook notifications → Apprise → Pushover
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
│   ├── msmtprc.j2              # msmtp SMTP relay config
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
│   ├── proxmox-virtiofs-directory.cfg.j2  # VirtioFS directory mappings
│   ├── proxmox-cluster-firewall.fw.j2    # Datacenter firewall rules
│   ├── proxmox-node-firewall.fw.j2       # Node-level firewall rules
│   └── proxmox-vm-firewall.fw.j2         # VM/CT firewall rules
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
│   │   │   ├── vms (docker-vm, media-vm, nextcloud-vm, dev-vm) ← gets qemu-guest-agent
│   │   │   └── lxcs (homebridge-lxc, syncthing-lxc, pbs-lxc)
│   │   ├── orchestrator (ansible-lxc, pi5-01)
│   │   └── jn-t14s-lin ← ThinkPad T14s (Kubuntu)
│   └── arch_hosts (jn-desktop) ← CachyOS gaming workstation
└── macos_hosts (macbook-pro)

workstations (jn-desktop, jn-t14s-lin, macbook-pro) ← no auto-recovery/reboots

nas_server (ts440) ← portable NAS role group

development (dev-vm) ← dev tooling (gh, shellcheck, yq)

docker_hosts (docker-vm, media-vm, nextcloud-vm) ← Docker Compose stacks

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
- **macOS (macbook-pro)**: Tailscale SSH doesn't work (App Store sandboxed build), so it uses the dedicated key exclusively. SSH is restricted to Tailscale only via `ListenAddress` in sshd_config

`bootstrap.yml` deploys both the personal key (passphrase-protected, for manual SSH) and the Ansible automation key (passwordless) to new hosts.

**Tailscale SSH MOTD**: `ssh-hardening.yml` deploys `/etc/pam.d/remote` so MOTD displays on Tailscale SSH login. Ubuntu hosts get a rich MOTD (system info, updates) via `landscape-common` + `update-notifier-common`.

## Bootstrap New Host

```bash
# Initial setup (as root)
ansible-playbook playbooks/bootstrap.yml -u root --ask-pass --limit new-host

# Then run packages
ansible-playbook playbooks/packages.yml --limit new-host
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
| `msmtp.yml` | `linux_hosts` | SMTP relay for system email (iCloud) |
| `smartmontools.yml` | `linux_hosts` | SMART disk monitoring with Apprise push alerts |
| `e1000e-tuning.yml` | `proxmox_nodes` | Disable EEE/TSO on Intel e1000e NICs to prevent hardware TX hangs |
| `apcupsd.yml` | `proxmox_nodes` | UPS monitoring with Apprise push alerts (ts440 USB master, others slave). Staggers slave startup to avoid NIS mutex contention |
| `bootstrap.yml` | `linux_hosts` | Create admin user, SSH keys, sudo setup (Debian + Arch) |
| `ssh-hardening.yml` | `linux_hosts` | SSH security (key auth, disable password) |
| `auto-updates.yml` | `linux_hosts` | Configure automatic updates + reboot |
| `unattended-upgrades.yml` | `debian_hosts` | Daily security patches (incl. workstations, Proxmox blacklist) |
| `network-recovery.yml` | `linux_hosts` | Network watchdog for auto-recovery after outages |
| `wifi.yml` | `linux_hosts` | WiFi powersave disable, optional PCI FLR or module reload resume fix |
| `restic.yml` | `backup_clients` | B2 offsite backup with systemd timer |
| `local-restic.yml` | `backup_clients` | Hourly backups to ts440 ZFS |
| `mergerfs.yml` | `nas_server` | MergerFS media pool mount + balance script + config excludes |
| `zfs.yml` | `nas_server` | ZFS snapshots (sanoid), scrub, ARC tuning, property enforcement, ACLs |
| `nfs.yml` | `nas_server` + clients | NFS server/client configuration |
| `filesystem-mounts.yml` | `linux_hosts` | Local filesystem mounts (NTFS, exFAT) |
| `samba.yml` | `nas_server` | Samba + Time Machine configuration |
| `docker-stacks.yml` | `docker_hosts` | Deploy Docker Compose stacks (per-service update reporting with version diffs) |
| `gluetun-watchdog.yml` | media-vm | Gluetun VPN crash loop detection, port forwarding monitoring, and auto-restart |
| `docker-auto-update.yml` | `docker_hosts` | Auto-update selected containers every 6h (Caddy, Gluetun, Diun) |
| `virtiofs.yml` | `proxmox_nodes`, `vms` | Configure VirtioFS shares between Proxmox hosts and VMs |
| `rclone-sync.yml` | `managed_hosts` | rclone sync from OneDrive to Nextcloud (macbook-pro via launchd, pi5-01 via systemd) |
| `git-sync.yml` | `nas_server` | Auto-pull from GitHub every 5 minutes (Nextcloud External Storage) |
| `nextcloud-scan.yml` | nextcloud-vm | Periodic `occ files:scan` for external storage (every 10 min) |
| `claude-memory-sync.yml` | `nas_server`, ansible-lxc | Rsync Claude Code memory to NAS for Nextcloud access (every 10 min) |
| `proxmox-firewall.yml` | `proxmox_nodes` | Deploy Proxmox firewall rules (datacenter, node, VM/CT) |
| `proxmox-backup-server.yml` | pbs-lxc, `proxmox_nodes` | Install PBS, configure datastore/prune/API token, register on all PVE nodes, create vzdump backup jobs |
| `proxmox-notifications.yml` | `proxmox_nodes` | PVE webhook notification targets + matchers → Apprise → Pushover |

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
- media-vm: `/opt/media-stack/` (uses VirtioFS for media access)
- nextcloud-vm: `/opt/nextcloud/` (uses VirtioFS for data storage)

Ansible repo on ansible-lxc: `~/cc-ansible`
Legacy copy on pi5-01: `/srv/configs/ansible/cc-ansible` (NFS from ts440, auto-synced from GitHub)

## Samba Configuration

The NAS server (currently ts440) serves SMB shares over Tailscale, managed by `playbooks/samba.yml`. Shares are defined in `group_vars/nas_server/samba.yml` under `smb_shares`.

### Shares

| Share | Path | Purpose |
|-------|------|---------|
| Configs | `/mnt/nas-zfs/configs` | Ansible repo only (app configs migrated to VMs) |
| Time Machine | `/mnt/nas-zfs/backups/timemachine` | macOS Time Machine (currently unused) |
| Backups | `/mnt/nas-zfs/backups` | General backups |
| NAS-ZFS | `/mnt/nas-zfs` | Full ZFS pool root |
| NAS-01 to NAS-05 | `/srv/nas-*` | Individual drive access |

### Connecting from macOS

```bash
# In Finder: Cmd+K, then enter:
smb://100.71.188.16/Configs

# For ansible repo, navigate to: ansible/cc-ansible
```

### Samba User Management

```bash
# Set Samba password (interactive)
ansible ts440 -m shell -a "smbpasswd -a johnny" --become

# List Samba users
ansible ts440 -m shell -a "pdbedit -L" --become
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

Selected containers are auto-updated every 6 hours via systemd timer (`docker-auto-update.yml`). Opt-in per stack with `auto_update: true` or per service with `auto_update_services: [name]` in `host_vars/<hostname>/docker.yml`. Currently auto-updated: Caddy (docker-vm), Gluetun (media-vm), Diun (all 3 VMs). Pulls/builds new images, uses `docker-stack-diff` to detect changes, only recreates if images changed. Gluetun uses `--force-recreate` with qBittorrent. Sends silent Pushover notification (`push-quiet`). Config in `group_vars/docker_hosts/auto-update.yml`.

Check status: `journalctl -u docker-auto-update`, `systemctl list-timers docker-auto-update*`

## ZFS Configuration

Managed by `zfs.yml` — snapshots, scrub, ARC tuning, property enforcement, ACLs:

- **Pools**: `nas_zfs` (2x8TB mirror), `media-01` (3TB), `media-02` (3TB)
- **Snapshots**: Sanoid timer every 15 minutes
- **Scrub**: Weekly (Sunday 2am) via systemd timer
- **ARC**: 2GB max (`/etc/modprobe.d/zfs.conf`)
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

- **VPN**: ProtonVPN via Gluetun container (all torrent traffic tunneled)
- **qBittorrent**: `network_mode: service:gluetun`, WebUI at `qbit.jnalley.me`
- **Priority**: SABnzbd (1) > qBittorrent (2) - Usenet preferred, torrents fallback
- **Disk I/O**: POSIX-compliant (required for VirtioFS compatibility)
- **Incomplete downloads**: Both SABnzbd and qBittorrent use the Lacie SSD for temp storage, isolated in separate subdirs (`usenet/` and `torrents/`)
- **VirtioFS note**: All containers use `/srv/media/plex:/data` to prevent stale file handles. Hardlinks work across all clients.
- **Automatic port sync**: systemd path unit watches Gluetun's port file and updates qBittorrent via API when VPN reconnects

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
| Uptime Kuma | `status.jnalley.me` | Service monitoring |
| Homepage | `home.jnalley.me` | Dashboard |
| Gitea | `git.jnalley.me` | Self-hosted Git (SSH on 2222) |
| Jellyseerr | `requests.jnalley.me` | Media requests (Plex OAuth) |
| Cloudflared | - | Cloudflare Tunnel (public access) |
| Apprise API | `apprise.jnalley.me` | Notification router (Pushover + email) |
| FreshRSS | `rss.jnalley.me` | RSS aggregator (Google Reader API for Reeder) |
| Diun | - | Docker image update notifier |

Stacks support `start: true/false` in `docker.yml` to control service state.

## Cloudflare Tunnel

Public internet access without port forwarding. Tunnel runs on docker-vm.

**Public services:**

| URL | Backend |
|-----|---------|
| `nextcloud.jnalley.me` | nextcloud-vm:11000 |
| `requests.jnalley.me` | jellyseerr:5055 |

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

**VirtioFS ACL Limitation**: VirtioFS does **not** pass through POSIX ACLs to guest VMs. Files accessed via VirtioFS must have adequate base permissions (`chmod`) — ACLs set via `setfacl` on the host are invisible to guests. For Nextcloud External Storage (Configs), a default ACL ensures new files inherit `o+r`:
```bash
setfacl -R -d -m o::r /srv/nas-zfs/configs
```

**ts440 memory budget** (15GB total): media-vm 10GB, nextcloud-vm 4GB, ZFS ARC 2GB (`/etc/modprobe.d/zfs.conf`), Proxmox ~1-2GB. ARC was reduced from 5GB to 2GB to give media-vm enough headroom for 20+ containers including Immich CUDA ML.

## Ansible Environment

Ansible runs on ansible-lxc (CT 104 on pve-m70q, Ubuntu 25.10) with `ansible-core` 2.19. The repo clone is at `~/cc-ansible` on ansible-lxc.

ts440 auto-pulls from GitHub every 5 minutes (`git-sync.timer`) to keep the Nextcloud External Storage copy current. nextcloud-vm runs `occ files:scan` every 10 minutes (`nextcloud-scan.timer`) so external storage changes appear automatically. Claude Code's project memory is synced from ansible-lxc to ts440 every 10 minutes (`claude-memory-sync.timer`) for Nextcloud access.

## Tips

- Use `--check` for dry runs
- Use `--diff` to see file changes
- Use `-v` through `-vvvv` for verbosity
- Tags: `ansible-playbook playbooks/packages.yml --tags fastfetch`
- Run site.yml for full configuration: `ansible-playbook site.yml`

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
ansible-playbook playbooks/rclone-sync.yml --limit macbook-pro

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
docker-auto-update (6h) ───────┤
Sonarr/Radarr (grabs) ─────────┤
Jellyseerr (requests) ─────────┘

Sonarr/Radarr ──→ Discord (native connection, rich embeds with poster art)
```

- **Apprise API**: Notification router at `/opt/notifications/` on docker-vm. Config uses `pover://` URLs for Pushover
- **Two Pushover apps**: "Computer Corner" (normal + quiet priority) and "cc-media-feed" (priority -2, silent/in-app only)
- **Five Apprise tags**: `push` (infrastructure → Computer Corner app, Time Sensitive), `push-quiet` (automated recovery → Computer Corner app, silent), `email` (iCloud SMTP), `media-feed` (Sonarr/Radarr → cc-media-feed app), `media-requests` (Jellyseerr → cc-media-feed app)
- **Diun**: Container image update notifier on all Docker VMs (`/opt/diun/`), sends with `push` tag
- **smartd/apcupsd**: Infrastructure alerts, send with `push` tag
- **auto-updates**: Notifies before updates (package count), after completion, and before reboots
- **unattended-upgrades**: Silent notification (`push-quiet`) when daily security patches are applied
- **network-watchdog**: Best-effort notifications on gateway/Tailscale recovery, pre-reboot, and max-reboot exceeded
- **gluetun-watchdog**: Silent notifications on VPN recovery, port forwarding loss, or max-restart exhaustion (`push-quiet` tag)
- **Sonarr/Radarr**: Dual notifications — Discord (rich embeds) + Apprise `media-feed` tag (silent Pushover)
- **Jellyseerr**: Webhook to Apprise with `media-requests` tag (silent Pushover)
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

## Proxmox Backup Server (pbs-lxc)

PBS runs in an unprivileged LXC (CT 105) on pve-herc with a dedicated 2TB ext4 drive.

- **Web UI**: `https://100.110.176.37:8007` (login as `root@pam`)
- **Datastore**: `main` at `/srv/pbs-data` (~1.8TB usable)
- **Storage name**: `pbs-main` (registered on all 4 Proxmox nodes)
- **Backup schedule**: Hourly, all guests except pbs-lxc (Ansible-managed via Play 3)
- **Prune job**: Daily — 24 hourly, 7 daily, 4 weekly, 3 monthly
- **API auth**: Token `backup@pbs!ansible` (secret in vault)
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
- **Info** (successful backups): `push-quiet` tag → silent
- Built-in `default-matcher` (mail-to-root) is disabled

```bash
# Deploy/update notification webhooks
ansible-playbook playbooks/proxmox-notifications.yml
```

## Planned: WAN Failover

LTE failover on pve-m70q to maintain Cloudflare Tunnel connectivity during Spectrum outages.

- **Hardware**: Netgear LB1120 LTE modem (~$50-80 used) + US Mobile SIM (~$10/mo)
- **Scope**: Only pve-m70q needs failover (runs cloudflared for Nextcloud/Jellyseerr)
- **Detection**: ~30 seconds, Recovery: ~50 seconds

See CLAUDE.md "Future Considerations" section for full implementation plan.
