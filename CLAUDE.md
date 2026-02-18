# CLAUDE.md

> **Last updated:** 2026-02-17

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

Ansible automation for a homelab infrastructure consisting of:
- 4 Proxmox hypervisors (ts440, pve-alto, pve-herc, pve-m70q)
- 7 VMs/LXC containers (docker-vm, media-vm, nextcloud-vm, dev-vm, ansible-lxc, homebridge-lxc, syncthing-lxc)
- 1 Ansible controller LXC (ansible-lxc, CT 104 on pve-m70q) running Ansible locally
- 1 Raspberry Pi 5 (pi5-01)
- 1 CachyOS gaming workstation (jn-desktop)
- 1 Kubuntu laptop (jn-t14s-lin) — ThinkPad T14s, dual-boot with Windows
- 1 macOS workstation (macbook-pro)

All hosts communicate via Tailscale VPN (100.x.x.x addresses).

## IMPORTANT: Infrastructure as Code First

**ALWAYS prioritize Infrastructure as Code (IaC) over ad-hoc commands.** When asked to install packages, configure services, or make any changes to managed hosts:

1. **Check if it can be managed via Ansible** - Add to host_vars, group_vars, or playbooks
2. **Update the appropriate configuration files** - packages.yml, vars.yml, etc.
3. **Run the playbook** - Don't use one-off shell commands that bypass Ansible
4. **Document in CLAUDE.md/README.md** if it's a significant addition

**Never** run ad-hoc `ansible -m shell` or direct SSH commands to make persistent changes. Ad-hoc commands are only for:
- Troubleshooting/diagnostics
- One-time queries (checking status, logs)
- Operations that shouldn't be repeated (manual data migrations)

If a package exists in the system repos, add it to the appropriate `packages_*` variable. If a service needs configuration, create or update the relevant playbook/task file.

## Git Workflow

The repository is hosted on GitHub (public): https://github.com/johnnynalley/cc-ansible

**ansible-lxc** (CT 104 on pve-m70q, Ubuntu 25.04) is the Ansible controller. The working clone lives at `~/cc-ansible` on ansible-lxc. All Ansible commands should be run from there.

**Workflow:**
1. Make changes on ansible-lxc (`~/cc-ansible`)
2. Commit and push to GitHub
3. ts440 automatically pulls every 5 minutes via `git-sync.timer` (deployed by `playbooks/git-sync.yml`), keeping `/srv/nas-zfs/configs/ansible/cc-ansible` in sync for Nextcloud External Storage access
4. pi5-01 still has a copy at `/srv/configs/ansible/cc-ansible` (via NFS mount from ts440), but it is no longer the controller

**git-sync on ts440:**
- Systemd timer runs every 5 minutes
- Pulls latest from GitHub to `/srv/nas-zfs/configs/ansible/cc-ansible`
- Keeps Nextcloud External Storage (Configs folder) up to date automatically
- Deploy with: `ansible-playbook playbooks/git-sync.yml`

## Common Commands

All commands should be run from ansible-lxc (`~/cc-ansible`).

```bash
# Run all playbooks via site.yml
ansible-playbook site.yml

# Run a specific playbook
ansible-playbook playbooks/packages.yml

# Run with host/group limit
ansible-playbook playbooks/packages.yml --limit proxmox_nodes

# Dry run with diff
ansible-playbook playbooks/packages.yml --check --diff

# Run specific tags
ansible-playbook playbooks/packages.yml --tags fastfetch

# Interactive menu
./bin/ansible-menu

# View inventory
ansible-inventory --list --yaml

# Bootstrap new host (first run as root)
ansible-playbook playbooks/bootstrap.yml -u root --ask-pass --limit new-host

# Run ad-hoc command with sudo (when SSH doesn't have sudo access)
ansible <hostname> -m shell -a "command here" --become
```

**Note**: When SSH sessions don't have sudo access but you need elevated privileges, use Ansible's `--become` flag. This works because Ansible uses passwordless sudo configured during bootstrap.

## SSH Authentication

Ansible on ansible-lxc uses a **dedicated passwordless SSH key** (`~/.ssh/ansible_ed25519`) for all host connections. This is configured as the default in `ansible.cfg` via `private_key_file`.

**Two keys are deployed by `bootstrap.yml`:**

| Key | Purpose | Passphrase |
|-----|---------|------------|
| `~/.ssh/id_ed25519.pub` | Personal/manual SSH | Yes |
| `~/.ssh/ansible_ed25519.pub` | Ansible automation | No (passwordless) |

**Linux hosts** also accept Tailscale SSH (no keys needed), which Ansible uses by default when available. The dedicated key is the fallback if Tailscale is down.

**macOS (macbook-pro)** cannot use Tailscale SSH (App Store build is sandboxed). It relies exclusively on the dedicated Ansible key over regular SSH. SSH on macbook-pro is restricted to the Tailscale interface only:
- `ListenAddress 100.119.197.17` in `/etc/ssh/sshd_config`
- Remote Login enabled for user `johnny` only (System Settings → Sharing)

**Tailscale SSH MOTD**: Tailscale SSH invokes `login(1)` with PAM service `remote`, which by default has no config file (PAM falls back to `other`, which lacks `pam_motd.so`). The `ssh-hardening.yml` playbook deploys `/etc/pam.d/remote` to all Linux hosts to enable MOTD display over Tailscale SSH. Ubuntu hosts show a rich MOTD (system info, available updates) via `landscape-common` and `update-notifier-common` (installed by `packages.yml`). Debian hosts get custom MOTD scripts (`templates/motd-*.sh.j2`) deployed to `/etc/update-motd.d/` showing system info, available updates, and reboot-required status.

**Deploying the key to a new host:**
```bash
# For Linux hosts (via Tailscale SSH or bootstrap)
ansible-playbook playbooks/bootstrap.yml -u root --ask-pass --limit new-host

# For macOS (manual first-time copy, then bootstrap handles future hosts)
ssh-copy-id -i ~/.ssh/ansible_ed25519.pub johnny@<tailscale-ip>
```

## Architecture

### Inventory Structure

Host groups form a hierarchy in `inventory/hosts.ini`:
- `managed_hosts` → all managed systems
  - `linux_hosts` → `debian_hosts` + `arch_hosts`
    - `debian_hosts`: `proxmox_nodes`, `vms_lxcs` (child groups: `vms` + `lxcs`), `orchestrator` (ansible-lxc, pi5-01), jn-t14s-lin
    - `arch_hosts`: jn-desktop (CachyOS gaming workstation)
  - `macos_hosts`: macbook-pro
- `workstations` → **cross-platform group** for desktops/laptops (jn-desktop, jn-t14s-lin, macbook-pro)
  - Hosts in this group are ALSO in their OS-specific group (debian_hosts, arch_hosts, macos_hosts)
  - Group vars disable automated recovery: `network_watchdog_enabled: false`, `auto_updates_enabled: false`
  - Playbooks like `network-recovery.yml` explicitly exclude this group: `hosts: linux_hosts:!workstations`
- `nas_server` → **portable NAS role group** (currently ts440). Storage services: NFS, Samba, ZFS, mergerfs, drive mounts. Migrate NAS to new hardware by changing membership in this group.
- `development` → **cross-platform group** for dev tooling (gh, shellcheck, yq). Currently: dev-vm. ansible-lxc gets these via `packages_host_extra` in host_vars instead. Packages split by OS: `packages_debian_development_extra`, `packages_arch_development_extra`
- `backup_clients` → separate group for restic backups (includes `proxmox_nodes`, `vms_lxcs`, `orchestrator`, `workstations`, `arch_hosts`)

VMs and LXCs are split so VMs get `qemu-guest-agent` while LXCs don't need it.

### Variable Precedence

Variables merge from multiple sources (highest to lowest precedence):
1. `inventory/host_vars/<hostname>/vars.yml` - per-host overrides
2. Group-specific files in `inventory/group_vars/<group>/`
3. `inventory/group_vars/all/vars.yml` - global defaults

**Important**: All group_vars and host_vars are under `inventory/`, not at the project root. This is Ansible's recommended structure for inventory-based configurations.

Encrypted secrets go in `vault.yml` files alongside `vars.yml`.

### Playbooks vs Roles

This repo uses **flat playbooks with imported tasks** rather than formal Ansible roles. Reusable task files live in `tasks/` and are imported with `import_tasks`.

### Multi-Platform Pattern

Playbooks detect OS via `ansible_facts.os_family` and conditionally execute platform-specific blocks:
- Debian/Ubuntu: apt package manager
- Arch: pacman
- macOS: homebrew (brew/casks)

Package lists follow naming convention: `packages_linux_common`, `packages_debian_extra`, `packages_<group>_extra`, `packages_host_extra`. Cross-platform groups split packages by OS: `packages_arch_workstations_extra`, `packages_debian_workstations_extra` (in `group_vars/workstations/packages.yml`); `packages_debian_development_extra`, `packages_arch_development_extra` (in `group_vars/development/packages.yml`). Apps not in apt repos (Discord, LocalSend) are installed via Flatpak on Debian workstations using `flatpak_workstations` variable; Arch gets them natively via pacman. `tealdeer` (the `tldr` command) is in `packages_linux_common` for all Linux hosts; macOS uses the Homebrew formula `tldr` in `packages_macos_common`.

### TS440 Storage Architecture

TS440 is the primary NAS server (currently the sole `nas_server` group member). Key components:

**ZFS Pool**: 2x 8TB mirror at `/srv/nas-zfs` (~7.3TB usable). Keep under 80% capacity. ARC max set to 2GB (in `group_vars/nas_server/zfs.yml`). media-vm has 10GB RAM to accommodate 20+ containers including GPU-accelerated Immich ML.

**MergerFS**: `/srv/media` aggregates multiple drives into a unified media pool. Branches and options defined in `group_vars/nas_server/mergerfs.yml`. Boot ordering uses `After=` directives only — `Requires=` and `RequiresMountsFor=` caused dependency failures with the mixed ZFS/fstab setup.

**Incomplete Downloads**: The Lacie SSD (`/srv/nas-01`) has a downloads directory **outside** the mergerfs branch tree, bind-mounted to `/srv/media-downloads` (defined in `host_vars/ts440/mounts.yml`). This abstracts the underlying drive — to move downloads to a different SSD, just update `mounts.yml`. Passed to media-vm via VirtioFS as `/srv/incomplete_downloads`.

**VirtioFS**: media-vm and nextcloud-vm access storage via VirtioFS (not NFS). Config in `host_vars/ts440/virtiofs.yml` (host side) and `host_vars/<vm>/virtiofs.yml` (guest side). All mounts use `cache=never` to prevent virtiofsd from consuming 5GB+ per mount on the host. Guest page cache still works, so streaming performance is unaffected.

**VirtioFS ACL Limitation**: VirtioFS does **not** pass through POSIX ACLs to guests. Files must have adequate **base permissions** (`chmod`) — ACLs set via `setfacl` on the host are invisible inside VMs. Default ACL `setfacl -R -d -m o::r /srv/nas-zfs/configs` ensures new files get `o+r` for Nextcloud access through VirtioFS.

**Config Storage**: Application configs are stored locally at `/opt/` on each VM (not NFS). This eliminates NFS boot dependencies and improves performance. Configs are backed up hourly to ts440 ZFS via `local-restic.yml`.

**Bind Mounts**: `/srv/plex-library` is bind-mounted from `/srv/media/plex` via fstab with `x-systemd.requires-mounts-for=/srv/media`.

**NFS Configuration Warnings**:
- Do NOT use `bind_source` in `group_vars/nas_server/nfs.yml` for paths already under the pseudo-root (`/srv`). It creates circular bind mounts that mask ZFS child datasets.
- The `/srv/nas-zfs` export uses `crossmnt` to traverse ZFS child datasets. Clients show multiple NFS mounts but they work as a unified tree.

### Samba/SMB Shares (ts440)

Managed by `playbooks/samba.yml`. Shares defined in `inventory/host_vars/ts440/vars.yml` under `smb_shares`. Uses `@smbusers` group for authentication and fruit VFS module (`catia fruit streams_xattr`) for macOS compatibility and Time Machine support. Avahi mDNS advertisement for LAN discovery.

**Discovery over Tailscale**: Time Machine discovery works via SMB's AAPL extensions, NOT mDNS (mDNS doesn't traverse WireGuard tunnels). Connect using the Tailscale IP: `smb://100.71.188.16/<share>`.

### Docker Container Management

Docker Compose stacks are managed via the `docker-stacks.yml` playbook. Services are split between two VMs:
- **docker-vm (VM 110 on pve-m70q)**: Infrastructure services (Caddy, Vaultwarden, monitoring, etc.)
- **nextcloud-vm (VM 101 on ts440)**: Nextcloud AIO with VirtioFS storage
- **media-vm (VM 100 on ts440)**: All media services (Plex, *arr stack, etc.)

**Stack Configuration**: Define stacks in `host_vars/<hostname>/docker.yml`:
```yaml
docker_stacks:
  - name: caddy           # Stack name (for logging)
    path: /opt/caddy      # Path to docker-compose.yml
    build: true           # true = rebuild, false = pull only
  - name: vaultwarden
    path: /opt/vaultwarden
    build: false
```

#### docker-vm (VM 110 on pve-m70q)

Lightweight VM (6 cores, 6GB RAM) running infrastructure services. Stacks defined in `host_vars/docker-vm/docker.yml`. Services use `caddy-proxy` Docker network (created by Caddy stack; other stacks join as external). Configs stored locally at `/opt/<service>/`, backed up via restic.

#### nextcloud-vm (VM 101 on ts440)

Nextcloud AIO with VirtioFS storage access (mounts in `host_vars/nextcloud-vm/virtiofs.yml`). Public via Cloudflare Tunnel at `nextcloud.jnalley.me`. Email via iCloud SMTP (same account as smartmontools alerts; credentials in vault). Stacks: Nextcloud AIO, Diun.

#### media-vm (VM 100 on ts440)

Primary media VM (10GB RAM, 4 cores, 200GB disk, Quadro P2200 GPU passthrough). Stacks in `host_vars/media-vm/docker.yml`. GPU shared between Plex (NVENC transcoding) and Immich (CUDA ML inference).

**Critical**: All media containers must use the same VirtioFS mount path (`/srv/media/plex:/data`). Using different paths causes stale file handle errors. Hardlinks work because all downloads and media libraries share the same `/data` mount on mergerfs.

**Immich**: Photo/video management at `photos.jnalley.me`. ML container capped at `mem_limit: 2g` to prevent OOM-freezing the VM. External library (`/srv/untitled`) is auto-locked by `immich_folder_album_creator` every 6 hours.

**Recyclarr**: Syncs TRaSH Guides custom formats to Sonarr/Radarr. Config at `/opt/media-stack/recyclarr/recyclarr.yml`. Runs daily at midnight.

#### Torrent Fallback (Gluetun + qBittorrent)

Torrents are used as a fallback when Usenet doesn't have a release (e.g., older anime dual audio). All torrent traffic is routed through ProtonVPN.

**Architecture:**
```
Prowlarr → Nyaa.si (anime indexer)
    ↓
Sonarr/Radarr → qBittorrent (priority 2) → Gluetun (VPN tunnel)
             → SABnzbd (priority 1, preferred)
```

qBittorrent uses `network_mode: "service:gluetun"`, so all traffic goes through Gluetun's network namespace. Gluetun's built-in kill switch blocks all traffic when VPN is down. **Important**: qBittorrent's Disk I/O Type must be set to **POSIX-compliant** (not mmap) for VirtioFS compatibility.

**Automatic Port Sync** (not Ansible-managed, deployed manually on media-vm): ProtonVPN assigns dynamic forwarded ports that change on reconnect. A systemd-based automation keeps qBittorrent's listening port in sync:

1. **Gluetun** writes the forwarded port to `/opt/media-stack/gluetun/forwarded_port` via `VPN_PORT_FORWARDING_UP_COMMAND`
2. **systemd path unit** (`qbit-port-sync.path`) watches that file for changes
3. **Sync script** (`/usr/local/bin/qbit-port-sync`) updates qBittorrent via API:
   - Reads Gluetun's port from file
   - Connects to qBittorrent API (with retries)
   - If API unreachable (Gluetun restart broke qBittorrent's network), restarts qBittorrent via docker compose
   - Updates listening port via API so qBittorrent saves it correctly

#### Gluetun VPN Watchdog

Gluetun's internal VPN restart (`HEALTH_RESTART_VPN=on`) doesn't properly clean up tun0 routes, causing self-reinforcing crash loops where OpenVPN connects but traffic can't flow (`RTNETLINK answers: File exists`). The watchdog detects this and does a full `docker compose up -d --force-recreate` (not just `restart`) to destroy the container and its network namespace, clearing the stale routes. Dependent containers (qBittorrent) that share Gluetun's network namespace are recreated together.

**Why force-recreate**: `docker compose restart` keeps the same container and network namespace. Since qBittorrent shares Gluetun's namespace (`network_mode: "service:gluetun"`), the namespace stays alive even when Gluetun stops, preserving the stale routes. `--force-recreate` destroys the container entirely, creating a fresh namespace on startup. After 3 consecutive health failures (~3 minutes), it force-recreates Gluetun + dependent containers. Rate-limited to 5 restarts per hour.

#### Notification Stack (Apprise + Pushover)

Centralized notification system using Apprise API (on docker-vm at `/opt/notifications/`) routing to Pushover and email.

**Architecture:**
```
Diun (container updates) ──────┐
smartd (disk health) ──────────┤
apcupsd (UPS power) ───────────┤
auto-updates (weekly) ─────────┼──→ Apprise API ───→ Pushover "Computer Corner" app (infrastructure, Time Sensitive)
unattended-upgrades (daily) ───┤   (docker-vm)  ───→ Pushover "Computer Corner" app (infrastructure, silent/quiet)
network-watchdog (recovery) ───┤                ───→ Pushover "cc-media-feed" app (media, silent)
gluetun-watchdog (VPN) ────────┤                ───→ Email (iCloud SMTP)
Sonarr/Radarr (grabs) ─────────┤
Jellyseerr (requests) ─────────┘

Sonarr/Radarr ──→ Discord (native connection, rich embeds with poster art)
```

**Apprise tags** control routing: `push` (Pushover infrastructure, Time Sensitive), `push-quiet` (Pushover infrastructure, silent), `email` (iCloud SMTP), `media-feed` (Pushover media, silent), `media-requests` (Pushover media, silent). Services specify tags via `apprise_alert_tags` variable (default: `push` in `group_vars/all/vars.yml`). apcupsd supports per-service override via `apcupsd_alert_tags`. Combine tags like `push,email` for multi-target delivery.

**Why Pushover over ntfy**: ntfy's iOS app does not support per-topic notification control. Pushover allows true silent delivery via priority `-2` and per-app iOS settings. ntfy config preserved (commented out) in docker-compose.

**Apprise email URL gotcha**: When SMTP username contains `@`, use `?user=` query parameter format instead of URL path. Apprise's serialization loses `%40` encoding via API, causing auth failures.

Diun runs on all three Docker VMs (docker-vm, media-vm, nextcloud-vm) monitoring containers for image updates. Config at `/opt/diun/diun.yml` on each. Sonarr/Radarr also send to Discord (native connection) for rich embeds with poster art.

#### Reverse Proxy (Caddy on docker-vm)

Caddy provides HTTPS for all internal services via Cloudflare DNS-01 challenge. Caddyfile at `/opt/caddy/Caddyfile`. docker-vm services are proxied by container name (`caddy-proxy` Docker network); media-vm services by Tailscale IP (`100.66.6.113`). All services require Tailscale to access.

**Image Updates**: The playbook separates pull and update steps — it only runs `docker compose up -d` if images were actually updated (detected via "Pull complete" or "Downloaded newer" in pull output). This avoids unnecessary container restarts when images are already current. Pull has retry logic (3 attempts, 10s delay) to handle transient registry timeouts. Dangling images are pruned after each run.

#### Cloudflare Tunnel (Public Access)

Cloudflare Tunnel (`cloudflared` on docker-vm) provides public access to Nextcloud (`nextcloud.jnalley.me` → `100.112.46.126:11000`) and Jellyseerr (`requests.jnalley.me` → `jellyseerr:5055`). No router ports exposed; home IP hidden. Geo-blocking restricts to US only (Cloudflare Security Rules: `(not ip.src.country in {"US"})` → Block). Managed via Cloudflare Zero Trust dashboard.

### Backup Architecture

Three-tier backup strategy:

- **Offsite (Backblaze B2)**: Daily via `restic.yml` at 00:00 UTC +30m random delay. Retention: 7d/4w/6m. ts440 backs up `/srv/nas-zfs` excluding replaceable media.
- **Local (ts440 ZFS)**: Hourly via `local-restic.yml`. Backs up `/opt` from VMs to `/srv/nas-zfs/backups/<hostname>/`. Retention: 24h/7d/4w/6m. Uses dedicated SSH key in `group_vars/backup_clients/vault.yml`.
- **ZFS Snapshots (sanoid)**: Every 15 minutes via `zfs-snapshots.yml`. Policies defined in `group_vars/nas_server/zfs.yml`.

Enable local backups: set `local_restic_enabled: true` and `local_restic_backup_paths` in host_vars. Source env with `set -a` when accessing repos manually: `sudo bash -c 'set -a && source /etc/restic/local-backup.env && restic snapshots'`.

### rclone Sync (OneDrive to Nextcloud)

One-way sync from UTD OneDrive to Nextcloud via `playbooks/rclone-sync.yml`. Runs on macbook-pro because UTD's Microsoft 365 tenant blocks third-party OAuth — OneDrive desktop app syncs locally, then rclone copies to Nextcloud WebDAV every 2 hours. Monitored via Uptime Kuma push monitor. rclone remote config is manual (not Ansible-managed) at `~/.config/rclone/rclone.conf`.

### Unattended-Upgrades (Daily Security Patches)

Deployed via `playbooks/unattended-upgrades.yml` to all `debian_hosts` (including workstations — security patches shouldn't wait). Complements the weekly `auto-updates.yml` full-upgrade.

**How it works**: Uses Debian/Ubuntu's native `unattended-upgrades` package with APT's built-in `apt-daily-upgrade.timer` (daily, randomized 12h window). Only applies security-origin patches — not general updates. A systemd drop-in (`/etc/systemd/system/apt-daily-upgrade.service.d/notify.conf`) hooks an `ExecStartPost` script that sends a silent Apprise notification (`push-quiet` tag) when patches are applied.

**Proxmox nodes**: Blacklist `pve-*`, `proxmox-*`, `ceph-*`, `corosync*`, `pve-kernel-*`, `pve-firmware`, `qemu-server`, `libpve-*` packages (defined in `group_vars/proxmox_nodes/vars.yml`) to avoid breaking cluster operations. Base Debian security patches still apply.

**Variables** (in `group_vars/debian_hosts/packages.yml`):
- `unattended_upgrades_enabled` (default: `true`) — per-host opt-out
- `unattended_upgrades_blacklist` (default: `[]`) — overridden for Proxmox nodes

### Network Recovery

Deployed via `playbooks/network-recovery.yml` to `linux_hosts:!workstations`.

**Network Watchdog** (`network-watchdog.timer`, every 60s):
- Ensures interfaces are UP (catches link flaps)
- On Proxmox: fixes bridge interfaces detached during router restarts (e.g., `eno1` removed from `vmbr0`)
- After 3 gateway failures: restarts networking/DHCP
- After 5 Tailscale failures: restarts tailscaled
- After 5 DHCP recovery failures: reboots (only if router is reachable, to avoid boot loops)
- On recovery: sends Apprise notification, restarts Docker stacks, remounts NFS

**Tailscale Online Target** (`tailscale-online.target`): Activates only when Tailscale is connected (not just daemon running). Services like `docker-stacks.service` depend on this.

### Workstation Hosts

**jn-desktop** (CachyOS/Arch): Gaming workstation in `arch_hosts` + `workstations` groups. NTFS games drive at `/mnt/games` (uses `ntfs3` kernel driver, not FUSE). NFS mount to ts440 at `/mnt/nas-zfs`. Config in `host_vars/jn-desktop/`. Gaming packages (Steam, Proton) handled by CachyOS meta-package; Ansible only manages OpenRGB, liquidctl, and flatpak. RGB config and BeamMP launcher are not Ansible-managed (backed up via restic).

**jn-t14s-lin** (Kubuntu): ThinkPad T14s laptop in `debian_hosts` + `workstations` groups. Requires `ansible_become_flags: "-S"` in host_vars due to sudo-rs (Ubuntu 25.10+ default). WiFi powersave disabled; optional ath11k resume hooks available in `host_vars/jn-t14s-lin/wifi.yml`.

Both hosts inherit `network_watchdog_enabled: false` and `auto_updates_enabled: false` from `group_vars/workstations/vars.yml`. They still receive daily security patches via `unattended-upgrades`.

### Swap Configuration

Managed by `playbooks/swap.yml`. Opt-in via `swap_size_gb` in host_vars. Auto-detects root filesystem type via `findmnt`:
- **ZFS hosts** (Proxmox): Creates a zvol at `rpool/swap` (swap files don't work on ZFS — CoW creates holes that `swapon` rejects, even with `dd`)
- **Non-ZFS hosts**: Creates a swap file at `/swapfile`

Currently enabled on pve-m70q and pve-herc (8GB each). Pool name configurable via `swap_zfs_pool` (defaults to `rpool`).

## Key Files

Playbooks are imported via `site.yml` (with tags). Browse with: `ls playbooks/ tasks/ templates/ scripts/ bin/`. Each file has a descriptive header comment. Docker stacks and VirtioFS configs are defined in `host_vars/<hostname>/docker.yml` and `virtiofs.yml`.

**media-vm specific files** (not Ansible-managed): qBittorrent port sync (`/usr/local/bin/qbit-port-sync`, systemd path unit `qbit-port-sync.path`).

### Proxmox Firewall (Ansible-Managed)

Three-level firewall managed by `playbooks/proxmox-firewall.yml`:
1. **Datacenter** (`cluster.fw`): IP sets and security groups — `group_vars/proxmox_nodes/firewall.yml`
2. **Node** (`host.fw`): Per-node rules — `host_vars/<node>/firewall.yml` under `pve_node_firewall`
3. **VM/CT** (`<vmid>.fw`): Per-VM rules — `host_vars/<node>/firewall.yml` under `pve_vm_firewalls`

Security model: default deny (`policy_in: DROP`) on all VMs. Caddy (docker-vm) is the only web entry point. SSH allowed from Tailscale. In VM rules, use `+dc/<ipset>` prefix to reference datacenter-level IP sets.

### homebridge-lxc (CT 102 on ts440)

Homebridge instance bridging smart home devices to Apple HomeKit. Firewall allows HAP port range 51000-56000 (child bridges use dynamic ports). Web UI: `http://100.96.116.42:8581`.

### haos-vm (VM 120 on pve-alto)

Home Assistant OS. Some devices chain: Device → Homebridge → Home Assistant (HomeKit Controller) → HomeKit (HomeKit Bridge). **HA Companion App**: Set **both** Internal URL and External URL to `http://homeassistant.hinny-liberty.ts.net:8123` (blank Internal URL causes connection failures on local network).

### VirtioFS Ansible Management

`playbooks/virtiofs.yml` manages VirtioFS on both sides: host-side config in `host_vars/<proxmox-node>/virtiofs.yml` (directory mappings + VM attachments), guest-side in `host_vars/<vm>/virtiofs.yml` (mount points + fstab entries). `virtiofs_directory_mappings` is the canonical list of available shares. **VM restart required** after adding VirtioFS config to host.

### Nextcloud External Storage

Provides access to ZFS paths via VirtioFS without duplicating data. Nextcloud AIO's `NEXTCLOUD_MOUNT` only supports a single path, so bind mounts (defined in `host_vars/nextcloud-vm/mounts.yml`) consolidate multiple VirtioFS paths under `/srv/external`. VirtioFS ACLs don't pass through (see TS440 Storage Architecture), so files need base `o+r` permissions.

Ansible config references: VirtioFS mounts in `host_vars/nextcloud-vm/virtiofs.yml`, bind mounts in `host_vars/nextcloud-vm/mounts.yml`, Docker compose with `NEXTCLOUD_MOUNT=/srv/external` at `/opt/nextcloud/docker-compose.yml`.

**External Storage Scanning**: Nextcloud's `filesystem_check_changes: 1` only detects changes when a user browses into the folder — there's no proactive background scan. `playbooks/nextcloud-scan.yml` deploys a systemd timer on nextcloud-vm that runs `occ files:scan` every 10 minutes (offset by 3 min from git-sync) for the Configs and Photo Library external storage paths. This ensures git-sync changes and photo uploads appear in Nextcloud automatically.

**Claude Memory Sync**: Claude Code's project memory (`~/.claude/projects/-home-johnny-cc-ansible/memory/`) lives on ansible-lxc outside the git repo (kept private — repo is public). `playbooks/claude-memory-sync.yml` deploys a timer on ansible-lxc that rsync's the memory directory to `ts440:/srv/nas-zfs/configs/claude-memory/` every 10 minutes (offset by 2 min). This appears in Nextcloud at `Configs/claude-memory/` and syncs to the Mac via Nextcloud desktop app for use with Claude Desktop.

## Future Considerations

### WAN Failover for Cloudflare Tunnel

**Status**: Planned - waiting on hardware purchase

Automatic WAN failover to maintain Cloudflare Tunnel connectivity (Nextcloud, Jellyseerr) during Spectrum outages.

**Architecture:**
```
Internet
    │
    ├─── [Spectrum Router] ──── 192.168.1.1 (Primary Gateway)
    │
    └─── [LB1120 LTE Modem] ─── 192.168.5.1 (Backup Gateway, own subnet)
            │
[LAN Switch]
    │
    ├── [pve-m70q - Proxmox Host] ← Runs failover script
    │       └── docker-vm (cloudflared)
    │
    └── [ts440 - Nextcloud]
```

**Key insight**: Only pve-m70q needs failover. ts440 (Nextcloud storage) only needs to be reachable from docker-vm over the local LAN, which remains functional during WAN outages.

#### Hardware Requirements

| Item | Model | Cost | Notes |
|------|-------|------|-------|
| LTE Modem | Netgear LB1120 (or LB2120) | ~$50-80 used | Ethernet out, no USB/ModemManager complexity |
| SIM | US Mobile "By the Gig" | ~$10/mo | 2GB base, $2/GB additional (rarely needed for failover-only) |

**LB1120 Configuration**: Keep modem on its default subnet (192.168.5.1) with NAT. Double NAT is fine for outbound-only traffic (cloudflared). Connect its LAN port to the switch - pve-m70q will have a route to reach it.

#### Implementation Plan

**Phase 1: Hardware Setup**
1. Insert SIM and power on LB1120
2. Access admin at 192.168.5.1, verify cellular connectivity
3. Connect LB1120 to LAN switch
4. Add static route on pve-m70q to reach backup gateway:
   ```bash
   # Temporary (for testing)
   ip route add 192.168.5.0/24 via 192.168.1.X dev vmbr0  # X = LB1120's IP on main subnet

   # Or simpler: LB1120 gets DHCP from main router, appears as 192.168.1.X
   ```

**Phase 2: Ansible Playbook** (preferred over manual script)

Create `playbooks/wan-failover.yml` targeting pve-m70q:

```yaml
# host_vars/pve-m70q/failover.yml
wan_failover_enabled: true
wan_failover_primary_gw: "192.168.1.1"
wan_failover_backup_gw: "192.168.5.1"      # LB1120 on its own subnet
wan_failover_check_ips:
  - "1.1.1.1"
  - "8.8.8.8"
wan_failover_fail_threshold: 3              # Failures before switching
wan_failover_recovery_threshold: 5          # Successes before restoring
wan_failover_check_interval: 10             # Seconds between checks
```

**Phase 3: Failover Script**

Create `/usr/local/bin/wan-failover.sh` on pve-m70q:

```bash
#!/bin/bash
# WAN Failover Script for pve-m70q
# Maintains Cloudflare Tunnel connectivity during Spectrum outages

set -euo pipefail

# Configuration
PRIMARY_GW="${WAN_FAILOVER_PRIMARY_GW:-192.168.1.1}"
BACKUP_GW="${WAN_FAILOVER_BACKUP_GW:-192.168.5.1}"
CHECK_IPS=("1.1.1.1" "8.8.8.8")
FAIL_THRESHOLD=3
RECOVERY_THRESHOLD=5
CHECK_INTERVAL=10
PING_TIMEOUT=2

# State
fail_count=0
recovery_count=0
current="primary"

log() {
    logger -t wan-failover -p "daemon.${1}" "$2"
    echo "$(date '+%Y-%m-%d %H:%M:%S') [$1] $2"
}

check_connectivity() {
    for ip in "${CHECK_IPS[@]}"; do
        if ping -c 1 -W $PING_TIMEOUT "$ip" &>/dev/null; then
            return 0
        fi
    done
    return 1
}

check_gateway_reachable() {
    ping -c 1 -W 1 "$1" &>/dev/null
}

# Probe primary without affecting active route (avoids interrupting backup)
probe_primary() {
    # Use a separate routing table to test primary
    ip route add 1.1.1.1 via $PRIMARY_GW table 100 2>/dev/null || true
    local result=1
    if ping -c 1 -W $PING_TIMEOUT 1.1.1.1 &>/dev/null; then
        result=0
    fi
    ip route del 1.1.1.1 via $PRIMARY_GW table 100 2>/dev/null || true
    return $result
}

switch_to_backup() {
    log "warning" "FAILOVER: Switching to backup gateway ($BACKUP_GW)"
    ip route replace default via $BACKUP_GW
    current="backup"
    fail_count=0
    recovery_count=0
}

switch_to_primary() {
    log "info" "RECOVERY: Restoring primary gateway ($PRIMARY_GW)"
    ip route replace default via $PRIMARY_GW
    current="primary"
    fail_count=0
    recovery_count=0
}

# Startup
log "info" "Starting WAN failover monitor (primary=$PRIMARY_GW, backup=$BACKUP_GW)"

if ! check_gateway_reachable $PRIMARY_GW; then
    log "error" "Primary gateway $PRIMARY_GW not reachable on LAN"
fi

if ! check_gateway_reachable $BACKUP_GW; then
    log "warning" "Backup gateway $BACKUP_GW not reachable - failover disabled"
fi

# Ensure we start with primary
ip route replace default via $PRIMARY_GW
current="primary"

# Main loop
while true; do
    if [[ "$current" == "primary" ]]; then
        if check_connectivity; then
            fail_count=0
        else
            ((fail_count++))
            log "warning" "Primary check failed ($fail_count/$FAIL_THRESHOLD)"

            if [[ $fail_count -ge $FAIL_THRESHOLD ]]; then
                if check_gateway_reachable $BACKUP_GW; then
                    switch_to_backup
                else
                    log "error" "Backup gateway unreachable - cannot failover"
                    fail_count=0
                fi
            fi
        fi
    else
        # On backup - probe primary without interrupting current traffic
        if probe_primary; then
            ((recovery_count++))
            log "info" "Primary recovery check passed ($recovery_count/$RECOVERY_THRESHOLD)"

            if [[ $recovery_count -ge $RECOVERY_THRESHOLD ]]; then
                switch_to_primary
            fi
        else
            recovery_count=0
        fi
    fi

    sleep $CHECK_INTERVAL
done
```

**Phase 4: Systemd Service**

Create `/etc/systemd/system/wan-failover.service`:

```ini
[Unit]
Description=WAN Failover Monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/wan-failover.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

#### docker-vm Routing Consideration

docker-vm gets its gateway from DHCP on the Proxmox bridge. When pve-m70q's default route changes, docker-vm traffic still goes to pve-m70q's bridge, but pve-m70q then routes it out the new gateway.

**Requirement**: Enable IP forwarding and NAT/masquerade on pve-m70q so VM traffic follows the host's default route:

```bash
# /etc/sysctl.conf (or Proxmox default)
net.ipv4.ip_forward = 1

# iptables NAT (may already exist for Proxmox NAT networks)
iptables -t nat -A POSTROUTING -o vmbr0 -j MASQUERADE
```

If docker-vm uses a static gateway pointing to the Spectrum router directly, update it to point to pve-m70q's bridge IP instead.

#### Testing Procedures

```bash
# Check current default route
ip route show default

# Manual gateway switch test
sudo ip route replace default via 192.168.5.1
curl -s ifconfig.me  # Should show cellular IP
sudo ip route replace default via 192.168.1.1

# Simulate primary failure (block traffic)
sudo iptables -A OUTPUT -d 192.168.1.1 -j DROP
journalctl -u wan-failover -f
# Wait for failover...
sudo iptables -D OUTPUT -d 192.168.1.1 -j DROP

# Check cloudflared reconnection
ansible docker-vm -m shell -a "docker logs cloudflared 2>&1 | tail -20" --become
```

#### Monitoring

```bash
# View failover logs
journalctl -u wan-failover -f
journalctl -t wan-failover --since "1 hour ago"

# Quick status check
/usr/local/bin/wan-status.sh
```

Optional status script at `/usr/local/bin/wan-status.sh`:

```bash
#!/bin/bash
echo "=== WAN Failover Status ==="
echo "Default gateway: $(ip route show default | awk '{print $3}')"
echo "Service: $(systemctl is-active wan-failover.service)"
echo -n "Primary (192.168.1.1): "; ping -c1 -W1 192.168.1.1 &>/dev/null && echo "UP" || echo "DOWN"
echo -n "Backup (192.168.5.1): "; ping -c1 -W1 192.168.5.1 &>/dev/null && echo "UP" || echo "DOWN"
echo "Public IP: $(curl -s --max-time 5 ifconfig.me 2>/dev/null || echo "unknown")"
```

#### Coordination with Network Watchdog

The existing `network-watchdog` handles Tailscale recovery and Proxmox bridge fixes. WAN failover is complementary:

| Component | Purpose | Runs on |
|-----------|---------|---------|
| network-watchdog | Fix Tailscale, bridge detachment, Docker restarts | All Linux hosts |
| wan-failover | Gateway switching for WAN redundancy | pve-m70q only |

They don't conflict - network-watchdog's gateway ping will succeed through either gateway.

#### Cost/Benefit Summary

| Metric | Value |
|--------|-------|
| Detection time | ~30 seconds (3 failures × 10s) |
| Recovery time | ~50 seconds (5 successes × 10s) |
| Monthly cost | ~$10 (minimal data usage) |
| Hardware cost | ~$50-80 one-time |
| Complexity | Single script on one host |

## Ansible Environment

Ansible runs on ansible-lxc (CT 104 on pve-m70q, Ubuntu 25.10) with `ansible-core` 2.19. The controller uses `ansible_connection=local` in the `orchestrator` group. Key collections: `community.docker` 4.6.1, `community.general` 11.1.0, `kewlfft.aur` 0.13.0.

The working repo clone is at `~/cc-ansible` on ansible-lxc.

**Legacy**: pi5-01 previously served as the Ansible controller using Debian 12's packaged `ansible-core` 2.14. It is now a regular managed host. The repo copy at `/srv/configs/ansible/cc-ansible` (via NFS from ts440) remains accessible but is read-only (auto-synced from GitHub by git-sync timer).

## Vault Setup

Vault password must exist at `~/.ansible/vault_pass.txt` (configured in ansible.cfg). Create vault files from `.example` templates using `ansible-vault create`.

## Adding Hosts

1. Add host entry to appropriate group in `inventory/hosts.ini` with Tailscale IP
2. Create `host_vars/<hostname>/` directory if custom variables needed
3. Run bootstrap playbook (for Linux), then packages playbook

## Documentation

**IMPORTANT**: When making changes to this repo, keep both docs updated:
- `CLAUDE.md` - Detailed technical reference for Claude Code
- `README.md` - Quick reference for humans

Update the "Last updated" date in both files when making ANY changes.
