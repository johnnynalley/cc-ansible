# CLAUDE.md

> **Last updated:** 2026-02-13

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

Ansible automation for a homelab infrastructure consisting of:
- 4 Proxmox hypervisors (ts440, pve-alto, pve-herc, pve-m70q)
- 6 VMs/LXC containers (docker-vm, media-vm, nextcloud-vm, ansible-lxc, homebridge-lxc, syncthing-lxc)
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

The repository is hosted on GitHub (public): https://github.com/johnnynalley/homelab-ansible

**ansible-lxc** (CT 104 on pve-m70q, Ubuntu 25.04) is the Ansible controller. The working clone lives at `~/homelab-ansible` on ansible-lxc. All Ansible commands should be run from there.

**Workflow:**
1. Make changes on ansible-lxc (`~/homelab-ansible`)
2. Commit and push to GitHub
3. ts440 automatically pulls every 5 minutes via `git-sync.timer` (deployed by `playbooks/git-sync.yml`), keeping `/srv/nas-zfs/configs/ansible/homelab-ansible` in sync for Nextcloud External Storage access
4. pi5-01 still has a copy at `/srv/configs/ansible/homelab-ansible` (via NFS mount from ts440), but it is no longer the controller

**git-sync on ts440:**
- Systemd timer runs every 5 minutes
- Pulls latest from GitHub to `/srv/nas-zfs/configs/ansible/homelab-ansible`
- Keeps Nextcloud External Storage (Configs folder) up to date automatically
- Deploy with: `ansible-playbook playbooks/git-sync.yml`

## Common Commands

All commands should be run from ansible-lxc (`~/homelab-ansible`).

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
    - `debian_hosts`: `proxmox_nodes`, `vms_lxcs` (child groups: `vms` + `lxcs`), `orchestrator` (ansible-lxc), jn-t14s-lin, pi5-01
    - `arch_hosts`: jn-desktop (CachyOS gaming workstation)
  - `macos_hosts`: macbook-pro
- `workstations` → **cross-platform group** for desktops/laptops (jn-desktop, jn-t14s-lin, macbook-pro)
  - Hosts in this group are ALSO in their OS-specific group (debian_hosts, arch_hosts, macos_hosts)
  - Group vars disable automated recovery: `network_watchdog_enabled: false`, `auto_updates_enabled: false`
  - Playbooks like `network-recovery.yml` explicitly exclude this group: `hosts: linux_hosts:!workstations`
- `nas_server` → **portable NAS role group** (currently ts440). Storage services: NFS, Samba, ZFS, mergerfs, drive mounts. Migrate NAS to new hardware by changing membership in this group.
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

Package lists follow naming convention: `packages_linux_common`, `packages_debian_extra`, `packages_<group>_extra`, `packages_host_extra`. Workstation packages are split by OS: `packages_arch_workstations_extra`, `packages_debian_workstations_extra` (in `group_vars/workstations/packages.yml`). Apps not in apt repos (Discord, LocalSend) are installed via Flatpak on Debian workstations using `flatpak_workstations` variable; Arch gets them natively via pacman.

### TS440 Storage Architecture

TS440 is the primary NAS server with a complex storage stack. Key components:

**ZFS Pool**: Primary storage at `/srv/nas-zfs` containing configs, media, and other data. ZFS performance degrades above 80% capacity - keep pools under this threshold.

**MergerFS Media Pool**: `/srv/media` aggregates multiple storage sources:
- `/srv/nas-01/media` (2TB Lacie SSD)
- `/srv/nas-02/media`, `/srv/nas-04/media` (older drives)
- `/srv/nas-zfs/media` (ZFS pool)
- `/srv/media-02/media`, `/srv/media-03/media` (additional ZFS datasets)

The mergerfs mount is managed by a systemd unit at `/etc/systemd/system/srv-media.mount` (not Ansible-managed). Critical options for NFS compatibility:
- `inodecalc=path-hash` - stable inode numbers based on file paths, preventing stale NFS file handles (ESTALE errors)
- `func.getattr=newest` - consistent file attributes across underlying drives for NFS stability

**Incomplete Downloads (Lacie SSD)**: The 2TB Lacie SSD (`/srv/nas-01`) has a dedicated downloads directory **outside** the mergerfs branch tree:

```
/srv/nas-01/
├── downloads/
│   └── media-downloads/    ← bind-mounted to /srv/media-downloads (Ansible-managed via host_vars/ts440/mounts.yml)
│       └── incomplete/     ← VirtioFS to media-vm as /srv/incomplete_downloads
│           ├── usenet/     ← SABnzbd temp downloads
│           └── torrents/   ← qBittorrent temp downloads
└── media/                  ← mergerfs branch (unchanged)
```

The bind mount at `/srv/media-downloads` abstracts the underlying drive — to move incomplete downloads to a different SSD, just update `mounts.yml`. Each download client only sees its own subdirectory:
- SABnzbd: `/srv/incomplete_downloads/usenet:/incomplete`
- qBittorrent: `/srv/incomplete_downloads/torrents:/incomplete`

Once complete, files are moved to `/data/downloads/complete` (SABnzbd) or `/data/downloads/torrents/` (qBittorrent), both on the mergerfs pool where Sonarr/Radarr can hardlink them to media libraries.

Critical boot ordering:
- Must start **after** ZFS mounts and individual drive mounts
- Uses `After=` directives with exact systemd unit names (e.g., `srv-nas\x2d01.mount`)
- Avoids `Requires=` and `RequiresMountsFor=` which caused dependency failures with the mixed ZFS/fstab setup

**Media VM (VM 100 on ts440)**: Runs all media-related Docker services including Plex, Sonarr, Radarr, Prowlarr, Bazarr, SABnzbd, Huntarr, Tautulli, Audiobookshelf, Tdarr, Recyclarr, and Portainer. Uses VirtioFS for high-performance storage access (eliminates NFS overhead - SABnzbd downloads improved from ~25 MB/s over NFS to ~43 MB/s via VirtioFS). Autostart is handled by `/etc/systemd/system/vm-media-autostart.service` which waits for `srv-media.mount`.

VirtioFS mounts on media-vm (Ansible-managed via `host_vars/ts440/virtiofs.yml` and `host_vars/media-vm/virtiofs.yml`):

| Host Path | Guest Mount | Purpose |
|-----------|-------------|---------|
| `/srv/plex-library` | `/srv/plex` | Plex media library |
| `/srv/media` | `/srv/media` | Full mergerfs pool for Sonarr/Radarr/etc. |
| `/srv/media-downloads/incomplete` | `/srv/incomplete_downloads` | Lacie SSD for SABnzbd + qBittorrent temp storage |
| `/srv/nas-zfs/media/books` | `/srv/books` | Audiobooks for Audiobookshelf |
| `/srv/nas-zfs/media/photos` | `/srv/photos` | Photos/videos for Immich |
| `/srv/nas-zfs/media/archive/untitled` | `/srv/untitled` | Immich external library (locked folder) |

All mounts use `cache=never` to prevent host memory exhaustion.

**VirtioFS Memory Optimization**: All VirtioFS mounts use `cache=never` to prevent the virtiofsd daemon from caching file data on the host. Without this, virtiofsd can consume 5GB+ per mount, causing severe memory pressure on ts440. With `cache=never`, virtiofsd uses only a few KB each. The guest OS (media-vm) still caches in its own page cache, so performance impact is minimal for streaming workloads.

**VirtioFS ACL Limitation**: VirtioFS does **not** pass through POSIX ACLs to guest VMs. Files must have adequate **base permissions** (`chmod`) — ACLs set via `setfacl` on the host are invisible to guests. For example, a file with mode `0670` and ACL `user:www-data:rwx` will be unreadable by www-data inside nextcloud-vm because only the base "other" bits (`---`) are visible. A default ACL (`setfacl -R -d -m o::r /srv/nas-zfs/configs`) is set to ensure new files in the configs directory inherit `o+r` for Nextcloud External Storage access.

**Bind Mounts**: `/srv/plex-library` is bind-mounted from `/srv/media/plex` via fstab with `x-systemd.requires-mounts-for=/srv/media`.

**Config Storage**: Application configs have been migrated to local storage on each VM for better performance and independence:
- **docker-vm**: `/opt/caddy/`, `/opt/vaultwarden/` (no NFS dependencies)
- **media-vm**: `/opt/media-stack/` (58GB, all media service configs)
- **nas-zfs/configs**: Only contains `ansible/` directory (this repo), auto-synced from GitHub via git-sync timer, accessible via Nextcloud External Storage and pi5-01 NFS

**NFS Exports**: ts440 exports storage for clients over Tailscale:
- `/srv/exports/configs` → pi5-01 (Ansible repo access)
- `/srv/nas-zfs` → jn-desktop (full NAS access for gaming workstation)

VMs no longer use NFS - docker-vm and media-vm store all configs locally and are fully independent of ts440 for config access.

**NFS Export Configuration Warning**: When adding exports in `group_vars/nas_server/nfs.yml`, do NOT use `bind_source` for paths already under the pseudo-root (`/srv`). Using `bind_source: /srv/nas-zfs` for a `name: nas-zfs` export creates a circular bind mount (`/srv/nas-zfs` → `/srv/nas-zfs`) that masks ZFS child datasets. For paths already under `/srv`, omit `bind_source` entirely - the export template will reference the path directly.

**NFS crossmnt option**: The `/srv/nas-zfs` export uses `crossmnt` to traverse ZFS child datasets. This causes the client to show multiple NFS mounts (one per ZFS dataset) but they all work as a unified tree under `/mnt/nas-zfs`. Without `crossmnt`, child dataset directories would appear empty.

**Note**: media-vm (VM 100) runs on ts440 itself and uses VirtioFS instead of NFS for all storage access, providing significantly better performance (~43 MB/s vs ~25 MB/s for downloads).

**ZFS Performance Tuning**: ts440 has 15GB RAM shared between Proxmox, media-vm, and ZFS ARC (read cache). Key tuning:

- **ZFS ARC max**: Configured in `/etc/modprobe.d/zfs.conf` via `options zfs zfs_arc_max=<bytes>`. Currently set to 2GB (`2147483648`). Can be changed live with `echo <bytes> | sudo tee /sys/module/zfs/parameters/zfs_arc_max`.
- **media-vm RAM**: Allocated 10GB. Increased from 6GB after Immich ML processing caused OOM freezes. media-vm runs 20+ containers including Plex, full *arr stack, Immich (with CUDA ML), Booklore, Byparr, and more.
- **Balance**: media-vm needs adequate RAM for all containers. ZFS ARC was reduced from 5GB to 2GB to accommodate — ARC was already self-shrinking to ~2GB under pressure anyway, so this formalizes what the system was doing naturally.

Diagnostic commands:
```bash
# Check ARC stats
cat /proc/spl/kstat/zfs/arcstats | grep -E '^size|^c_max'

# Check memory pressure (swap usage is bad)
free -h

# Check I/O latency
iostat -x 1 5
```

### Samba/SMB Shares (ts440)

ts440 serves SMB shares over Tailscale, managed by Ansible via `playbooks/samba.yml`. Configuration is defined in `inventory/host_vars/ts440/vars.yml` under `smb_shares`.

**Current shares:**

| Share | Path | Purpose |
|-------|------|---------|
| NAS-ZFS | `/mnt/nas-zfs` | Full ZFS pool root |
| Configs | `/mnt/nas-zfs/configs` | All configs (includes ansible) |
| Backups | `/mnt/nas-zfs/backups` | Backup directory |
| Time Machine | `/mnt/nas-zfs/backups/timemachine` | macOS Time Machine target |
| NAS | `/srv/NAS/Files` | Legacy NAS files |
| NAS-01 to NAS-05 | `/srv/nas-01` to `/srv/nas-05` | Individual drive access |

**Key configuration:**
- Uses `@smbusers` group for authentication (not individual users)
- macOS compatibility via fruit VFS module (`catia fruit streams_xattr`)
- Time Machine support with `fruit:time machine = yes`
- Avahi mDNS advertisement for LAN discovery (`/etc/avahi/services/timemachine.service`)

**Connecting from macOS:**
1. Finder → Cmd+K → `smb://100.71.188.16/Configs`
2. Authenticate with Samba credentials
3. Navigate to `ansible/homelab-ansible` for this repo

**Discovery over Tailscale**: Time Machine discovery works via SMB's AAPL extensions, NOT mDNS (mDNS doesn't traverse WireGuard tunnels). Connect using the Tailscale IP.

**Samba user management:**
```bash
# Set/update Samba password (interactive, run on ts440)
ansible ts440 -m shell -a "smbpasswd -a johnny" --become

# List Samba users
ansible ts440 -m shell -a "pdbedit -L" --become
```

Troubleshooting Time Machine not appearing in macOS picker:
```bash
# Restart smbd (most common fix)
ansible ts440 -m systemd -a "name=smbd state=restarted" --become

# Check Avahi service is valid
ansible ts440 -m shell -a "journalctl -u avahi-daemon | grep -i timemachine" --become

# Verify Samba config
ansible ts440 -m shell -a "testparm -s" --become
```

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

Lightweight VM running only infrastructure services. Specs: 6 cores, 6GB RAM, disk on `local-lvm`.

**Stacks on docker-vm**:
- **Caddy**: Reverse proxy with automatic HTTPS via Cloudflare DNS-01 challenge
- **Vaultwarden**: Bitwarden-compatible password manager
- **Uptime Kuma**: Service monitoring dashboard (`status.jnalley.me`)
- **Homepage**: Homelab dashboard (`home.jnalley.me`)
- **Gitea**: Self-hosted Git server (`git.jnalley.me`, SSH on port 2222)
- **Jellyseerr**: Media request management (`requests.jnalley.me`) - uses Plex OAuth
- **Cloudflared**: Cloudflare Tunnel for public access to Nextcloud/Jellyseerr

**Docker Network**: Services use `caddy-proxy` network (created by Caddy stack). Other stacks join it as external.

**Config Storage**: Configs stored locally at `/opt/<service>/` on docker-vm. This avoids NFS dependency issues and allows docker-vm to boot independently of ts440. Configs are backed up via restic (`/opt` is in `restic_backup_paths_extra`).

**Boot Ordering**: `docker-stacks.service` starts containers after docker.service (no NFS dependencies).

**Stack Control**: The `docker_stacks` variable supports a `start` field:
- `start: true` (default) - Ensure stack is running
- `start: false` - Ensure stack is stopped (useful for disabling services without removing config)

#### nextcloud-vm (VM 101 on ts440)

Nextcloud AIO instance with VirtioFS storage access to ts440's ZFS pool.

**VM Specs**: 4GB RAM, 2 cores, 32GB local disk

**Stacks on nextcloud-vm**:
- **Nextcloud AIO**: All-in-one Nextcloud deployment with Collabora, Talk, etc.

**VirtioFS Mounts** (Ansible-managed via `host_vars/ts440/virtiofs.yml` and `host_vars/nextcloud-vm/virtiofs.yml`):

| Host Path | Guest Mount | Purpose |
|-----------|-------------|---------|
| `/srv/nas-zfs/nextcloud` | `/srv/nextcloud` | Nextcloud data directory |
| `/srv/nas-zfs/configs` | `/srv/configs` | Ansible configs (External Storage) |
| `/srv/nas-zfs/backups/nextcloud-aio` | `/srv/nextcloud-aio-backup` | Nextcloud AIO backup location |
| `/srv/nas-zfs/media/photos` | `/srv/photos` | Immich photos (External Storage, read-only) |

All mounts use `cache=never` to prevent host memory exhaustion. Data directory at `/srv/nas-zfs/nextcloud/data` is owned by www-data (UID 33).

**Access**:
- Admin interface: `https://100.112.46.126:8080` (Tailscale only)
- Web interface: `https://nextcloud.jnalley.me` (public via Cloudflare Tunnel)

**Public Access**: Cloudflare Tunnel routes `nextcloud.jnalley.me` → `100.112.46.126:11000`. No ports exposed on router, home IP hidden behind Cloudflare.

**Email Configuration**:
Nextcloud sends email via iCloud SMTP (same account as ts440 smartmontools alerts):
- From: `nextcloud@jnalley.me`
- SMTP: `smtp.mail.me.com:587` (STARTTLS)
- Auth: `jn@jnalley.me` with app-specific password

Settings configured via `occ` CLI (UI may not save all fields properly):
```bash
occ config:system:set mail_smtpmode --value='smtp'
occ config:system:set mail_smtpsecure --value='tls'
occ config:system:set mail_smtphost --value='smtp.mail.me.com'
occ config:system:set mail_smtpport --value='587'
occ config:system:set mail_smtpauth --value='1' --type=integer
occ config:system:set mail_smtpname --value='jn@jnalley.me'
occ config:system:set mail_smtppassword --value='<app-password>'
occ config:system:set mail_from_address --value='nextcloud'
occ config:system:set mail_domain --value='jnalley.me'
```

**Mail Providers Setting**: Use "System email account" (not "User's email account"). This sends all Nextcloud emails (notifications, calendar invites) from the system SMTP. The "User's email account" option requires users to configure the Nextcloud Mail app with their own email - unnecessary for single-user.

**iOS CalDAV/CardDAV**: App passwords must be created with the correct login name. If you log in with email (`jn@jnalley.me`), app passwords get that as `login_name`, but iOS sends username `Johnny` - causing auth failures. Create app passwords via CLI to ensure correct login name:
```bash
docker exec -u www-data nextcloud-aio-nextcloud php occ user:auth-tokens:add Johnny
```

#### media-vm (VM 100 on ts440)

Primary media services VM. Specs: 10GB RAM, 4 cores, 200GB local disk, Quadro P2200 GPU passthrough, VirtioFS for media access.

**Stacks on media-vm**:
- **media-stack**: Plex, Sonarr, Radarr, Prowlarr, Bazarr, SABnzbd, qBittorrent, Gluetun, Huntarr, Tautulli, Tdarr, Recyclarr, Audiobookshelf
- **immich**: Immich photo/video management (server, machine learning, PostgreSQL, Redis, folder-album-creator) with GPU acceleration
- **portainer**: Docker management UI (ports 9000/9443)

**Config Storage**: All configs stored locally at `/opt/` on media-vm (backed up hourly to ts440 ZFS):
- `/opt/media-stack/docker-compose.yml` - main stack including audiobookshelf
- `/opt/immich/docker-compose.yml` - Immich stack (server, ML, postgres, redis, folder-album-creator)
- `/opt/portainer/docker-compose.yml`

**Media Access**: All containers access media via the same VirtioFS mount path to prevent stale file handle issues:
- `/srv/media/plex:/data` - mergerfs media pool (Plex read-only, Sonarr, Radarr, SABnzbd, Tdarr, qBittorrent)
- `/srv/incomplete_downloads/usenet:/incomplete` - SABnzbd temp downloads (Lacie SSD)
- `/srv/incomplete_downloads/torrents:/incomplete` - qBittorrent temp downloads (Lacie SSD)

**Hardlink compatibility**: All media containers share the same `/data` mount (`/srv/media/plex` on mergerfs). Completed downloads land at `/data/downloads/complete` (SABnzbd) or `/data/downloads/torrents/` (qBittorrent), and Sonarr/Radarr hardlink from there to `/data/Shows/`, `/data/Anime/`, `/data/Movies/` — all on the same filesystem.

**Important**: All media containers must use the same mount path (`/srv/media/plex`). Using different paths (e.g., `/srv/plex` vs `/srv/media/plex`) causes VirtioFS stale file handle errors when files are added, requiring container restarts. Sonarr/Radarr should also have Plex notifications configured (Settings → Connect → Plex) to trigger library updates on import.

**GPU Sharing (Quadro P2200)**: The GPU is shared between Plex (transcoding via NVENC) and Immich (ML inference via CUDA). Plex uses `runtime: nvidia`, Immich uses `deploy.resources.reservations` — both work simultaneously. NVIDIA GPU scheduling handles multi-process access. Contention is rare since Plex transcoding is on-demand and Immich ML is bursty (on new uploads).

#### Immich (Photo/Video Management)

Immich provides self-hosted photo/video management with GPU-accelerated face detection, CLIP search, and video transcoding. Access at `https://photos.jnalley.me` (Tailscale only).

**Storage**:
- Photos/videos: `/srv/photos` (VirtioFS from `nas-zfs/media/photos` on ZFS)
- App data (DB, config): `/opt/immich/` (local disk, backed up hourly via restic)
- ML model cache: Docker volume `immich_model-cache`

**Containers**: `immich_server` (port 2283), `immich_machine_learning` (CUDA, `mem_limit: 2g`), `immich_postgres` (pgvecto.rs), `immich_redis`, `immich_folder_album_creator`

**Memory limit**: The ML container is capped at 2GB (`mem_limit: 2g` in docker-compose) to prevent it from OOM-freezing the entire VM during bulk uploads. Docker kills just the ML container if it exceeds the limit, and Immich auto-restarts it to resume processing.

**External library**: `/srv/untitled` is mounted read-only into the Immich container at `/mnt/external/untitled`. Source is `/srv/nas-zfs/media/archive/untitled` on ts440 (ZFS dataset `nas_zfs/media/archive`). Configured as an external library in Immich — files are indexed in-place, not copied.

**Auto-lock (folder-album-creator)**: The `immich_folder_album_creator` container ([Salvoxia/immich-folder-album-creator](https://github.com/Salvoxia/immich-folder-album-creator)) runs every 6 hours and automatically moves all external library assets to Immich's locked folder. Config at `/opt/immich/folder-album-creator.env`. Uses `VISIBILITY: locked` so assets are hidden from timeline/search/face recognition.

**Backup coverage**: Photos are protected by ZFS snapshots (production policy: 24h/7d/4w/6m), B2 offsite backup (auto-included), and the PostgreSQL database at `/opt/immich/postgres` is covered by media-vm's hourly local restic backup.

#### Recyclarr (Custom Format Sync)

Recyclarr syncs TRaSH Guides custom formats to Sonarr/Radarr. Config location: `/opt/media-stack/recyclarr/recyclarr.yml`

**Key settings:**
- `replace_existing_custom_formats: true` - Allows Recyclarr to update existing CF scores
- Two profiles configured: `1080p-Anime` and `1080p`

**Anime scoring (via Recyclarr):**

| Custom Format | Score | Notes |
|---------------|-------|-------|
| Anime Dual Audio | +3000 | Strong preference for dual audio |
| Anime LQ Groups | -10000 | Default TRaSH score, blocks LQ groups |
| x265 (HEVC) | +50 | Slight preference for x265 |
| BD/WEB Tiers | default | SeaDex-based quality tiers |

**Manual CFs in Sonarr** (not managed by Recyclarr):

| Custom Format | Score | Purpose |
|---------------|-------|---------|
| 2160p | -1500 | Penalize 4K unless dual audio (+3000) overcomes it |
| Portuguese Releases | -10000 | Block Brazilian Portuguese releases (PTBR, Dublado, Anitsu) |

The 1080p-Anime quality profile groups 1080p and 2160p together, letting CF scores decide. This allows 2160p dual audio (+1500 net) to be grabbed when no 1080p dual audio exists, while preferring 1080p otherwise.

**Manual sync:**
```bash
# Run from ansible-lxc
ansible media-vm -m shell -a "docker exec recyclarr recyclarr sync" --become
```

Recyclarr runs automatically via cron inside the container (daily at midnight).

#### Torrent Fallback (Gluetun + qBittorrent)

Torrents are used as a fallback when Usenet doesn't have a release (e.g., older anime dual audio). All torrent traffic is routed through ProtonVPN.

**Architecture:**
```
Prowlarr → Nyaa.si (anime indexer)
    ↓
Sonarr/Radarr → qBittorrent (priority 2) → Gluetun (VPN tunnel)
             → SABnzbd (priority 1, preferred)
```

**Gluetun container:**
- VPN provider: ProtonVPN (Plus tier required for P2P)
- Username suffix: `+pmp` required for port forwarding
- Port forwarding enabled for better torrent connectivity
- Kill switch built-in (if VPN drops, no traffic leaks)

**qBittorrent container:**
- `network_mode: "service:gluetun"` - all traffic routes through VPN
- WebUI port 8085 exposed via Gluetun
- **Disk I/O Type: POSIX-compliant** - required for VirtioFS compatibility (mmap doesn't work)
- Network interface bound to `tun0` for extra leak protection
- Completed downloads to `/data/downloads/torrents/` (mergerfs via VirtioFS)
- Incomplete downloads to `/incomplete/` (Lacie SSD via `/srv/incomplete_downloads/torrents`)

**Download client priorities:**
- SABnzbd: Priority 1 (preferred)
- qBittorrent: Priority 2 (fallback)

This means Usenet is always tried first. Torrents only grab releases that don't exist on Usenet.

**Seeding behavior:**
- Ratio limit: 1.0
- After ratio reached: Pause torrent
- Sonarr/Radarr handle cleanup after import + seeding complete

**Automatic Port Sync**: ProtonVPN's port forwarding assigns dynamic ports that change on reconnect. A systemd-based automation keeps qBittorrent's listening port in sync:

1. **Gluetun** writes the forwarded port to `/opt/media-stack/gluetun/forwarded_port` via `VPN_PORT_FORWARDING_UP_COMMAND`
2. **systemd path unit** (`qbit-port-sync.path`) watches that file for changes
3. **Sync script** (`/usr/local/bin/qbit-port-sync`) updates qBittorrent via API:
   - Reads Gluetun's port from file
   - Connects to qBittorrent API (with retries)
   - If API unreachable (Gluetun restart broke qBittorrent's network), restarts qBittorrent via docker compose
   - Updates listening port via API so qBittorrent saves it correctly

**IP Protection**: qBittorrent uses `network_mode: "service:gluetun"`, so all traffic goes through Gluetun's network namespace. Gluetun's built-in kill switch blocks all traffic when VPN is down. During reconnects, qBittorrent simply can't reach the internet until VPN is back up.

**Port sync troubleshooting:**
```bash
# Check sync logs
journalctl -t qbit-port-sync -n 20

# Check current ports match
ansible media-vm -m shell -a "cat /opt/media-stack/gluetun/forwarded_port" --become
# Compare with qBittorrent WebUI → Options → Connection → Listening Port

# Manually trigger sync
ansible media-vm -m shell -a "/usr/local/bin/qbit-port-sync" --become

# Check systemd path unit status
ansible media-vm -m shell -a "systemctl status qbit-port-sync.path" --become
```

**Verify VPN is working:**
```bash
# Check Gluetun logs
ansible media-vm -m shell -a "docker logs gluetun 2>&1 | grep -E 'connected|Initialization|port forward'" --become

# Verify external IP is VPN (should be Netherlands)
ansible media-vm -m shell -a "docker exec gluetun wget -qO- https://ipinfo.io/json" --become
```

#### Gluetun VPN Watchdog

Gluetun's internal VPN restart (`HEALTH_RESTART_VPN=on`) doesn't properly clean up tun0 routes, causing self-reinforcing crash loops where OpenVPN connects but traffic can't flow (`RTNETLINK answers: File exists`). The watchdog detects this and does a full `docker restart` to clear the stale state.

**How it works:**
- Systemd timer runs every 60 seconds on media-vm
- Checks Gluetun's Docker healthcheck status
- After 3 consecutive failures (~3 minutes), restarts the container
- Rate-limited to 5 restarts per hour to prevent infinite restart loops
- If max restarts exceeded, logs error and requires manual intervention

**Configuration** (in `host_vars/media-vm/vars.yml`):
```yaml
gluetun_watchdog_enabled: true
gluetun_watchdog_compose_dir: /opt/media-stack
# Optional overrides (defaults shown):
# gluetun_watchdog_interval: 60        # Check interval in seconds
# gluetun_watchdog_max_failures: 3     # Failures before restart
# gluetun_watchdog_max_restarts: 5     # Max restarts per window
# gluetun_watchdog_restart_window: 3600 # Window in seconds (1 hour)
# gluetun_watchdog_container: gluetun  # Container name
```

**Troubleshooting:**
```bash
# Check watchdog status and logs
systemctl status gluetun-watchdog.timer
journalctl -t gluetun-watchdog -n 20

# Manually trigger watchdog
sudo /usr/local/sbin/gluetun-watchdog

# Check state files
cat /var/lib/gluetun-watchdog/failure_count
cat /var/lib/gluetun-watchdog/restart_log
```

#### Reverse Proxy (Caddy on docker-vm)

Caddy proxies all services over Tailscale with HTTPS (DNS-01 via Cloudflare):
- **docker-vm services** (via Docker network): `vaultwarden`
- **media-vm services** (via Tailscale IP 100.66.6.113): `plex`, `sonarr`, `radarr`, `prowlarr`, `bazarr`, `sabnzbd`, `qbit`, `huntarr`, `tautulli`, `audiobookshelf`, `tdarr`, `photos` (Immich)

Caddyfile location: `/opt/caddy/Caddyfile` (on docker-vm, stored locally)

Example Caddyfile entries:
```caddyfile
# Local service on docker-vm (container name)
vaultwarden.jnalley.me {
    reverse_proxy vaultwarden:80
}

# Remote service on media-vm (Tailscale IP)
sonarr.jnalley.me {
    reverse_proxy 100.66.6.113:8989
}
```

All services require Tailscale connection to access (internal-only HTTPS).

**Image Updates**: The playbook separates pull and update steps - it only runs `docker compose up -d` if images were actually updated (detected via "Pull complete" or "Downloaded newer" in pull output). This avoids unnecessary container restarts when images are already current. Pull has retry logic (3 attempts, 10s delay) to handle transient registry timeouts. Dangling images are pruned after each run.

#### Cloudflare Tunnel (Public Access)

Cloudflare Tunnel provides public internet access to select services without exposing ports or revealing the home IP.

**Architecture:**
```
Public Internet → Cloudflare Edge → cloudflared (docker-vm) → Backend Services
```

**Publicly accessible services:**

| URL | Backend | Purpose |
|-----|---------|---------|
| `nextcloud.jnalley.me` | `100.112.46.126:11000` | Nextcloud (file sharing) |
| `requests.jnalley.me` | `jellyseerr:5055` | Jellyseerr (media requests) |

**Configuration:**
- Tunnel managed in Cloudflare Zero Trust dashboard (Networks → Connectors)
- Token stored in `/opt/cloudflared/.env` on docker-vm
- Container joins `caddy-proxy` network to reach other containers by name

**Security:**
- No ports open on router (outbound tunnel connection only)
- Home IP hidden behind Cloudflare
- Cloudflare provides DDoS protection
- Geo-blocking via Cloudflare Security Rules (US only)
- Services have their own authentication (Nextcloud login, Plex OAuth for Jellyseerr)

**Geo-Blocking (Cloudflare Security Rules):**

All non-US traffic to `jnalley.me` is blocked via a custom security rule:

1. Cloudflare Dashboard → `jnalley.me` → Security → Security Rules
2. Create rule with expression: `(not ip.src.country in {"US"})`
3. Action: Block

This applies to all subdomains including tunnel hostnames. Security rules are per-domain - repeat for other domains if needed.

**Troubleshooting:**
```bash
# Check tunnel status
ansible docker-vm -m shell -a "docker logs cloudflared 2>&1 | tail -10" --become

# Verify tunnel is connected (should show "Registered tunnel connection")
ansible docker-vm -m shell -a "docker logs cloudflared 2>&1 | grep -i registered" --become
```

**Adding new public hostnames:**
1. Go to Cloudflare Zero Trust → Networks → Connectors → Your tunnel
2. Add public hostname with subdomain, domain, and backend URL
3. For docker-vm containers, use container name (e.g., `jellyseerr:5055`)
4. For other VMs, use Tailscale IP (e.g., `100.112.46.126:11000`)

### Backup Architecture

Three-tier backup strategy:

**Offsite (Backblaze B2)**: Daily backups via `restic.yml`
- Runs at 00:00 UTC with 30m random delay
- Retention: 7 daily, 4 weekly, 6 monthly
- ts440 backs up entire `/srv/nas-zfs` with excludes for replaceable media (plex, podcasts) and Time Machine

**Local (ts440 ZFS)**: Hourly backups via `local-restic.yml`
- Backs up `/opt` from docker-vm and media-vm to `/srv/nas-zfs/backups/<hostname>/`
- Retention: 24 hourly, 7 daily, 4 weekly, 6 monthly
- Uses dedicated SSH key (stored in `group_vars/backup_clients/vault.yml`)
- Requires Tailscale ACL: `tag:backup` hosts can SSH to `tag:server`

**ZFS Snapshots (sanoid)**: Automated snapshots via `zfs-snapshots.yml`
- Runs every 15 minutes on ts440 via systemd timer
- Production datasets (configs, appdata, files, nextcloud, media/photos): 24 hourly, 7 daily, 4 weekly, 6 monthly
- Backup datasets (backups, timemachine): 7 daily, 4 weekly, 3 monthly
- Ignored datasets (media/plex, media/podcasts): no snapshots (replaceable content)
- Configuration in `group_vars/nas_server/zfs.yml`

**Enable local backups** for a host in `host_vars/<hostname>/vars.yml`:
```yaml
local_restic_enabled: true
local_restic_backup_paths:
  - /opt
```

**Accessing restic repos manually**: The env file must be sourced with `set -a` to export variables:
```bash
# From the backed-up host (has /etc/restic/local-backup.env)
sudo bash -c 'set -a && source /etc/restic/local-backup.env && restic snapshots'

# To access a different repo (e.g., old gaming-pc backup from jn-desktop):
sudo bash -c 'set -a && source /etc/restic/local-backup.env && export RESTIC_REPOSITORY=sftp:johnny@100.71.188.16:/srv/nas-zfs/backups/gaming-pc && restic snapshots'
```

**Pre-CachyOS backup**: The `gaming-pc` repo at `/srv/nas-zfs/backups/gaming-pc` contains the Kubuntu backup with `/home/jnalley` from before the CachyOS migration.

**Restore commands**:
```bash
# List restic snapshots
restic -r sftp:johnny@100.71.188.16:/srv/nas-zfs/backups/docker-vm snapshots

# Restore specific file from restic
restic -r sftp:johnny@100.71.188.16:/srv/nas-zfs/backups/docker-vm restore latest --target /tmp/restore --include /opt/caddy/Caddyfile

# List ZFS snapshots
zfs list -t snapshot -o name,creation,used -s creation

# Restore from ZFS snapshot (browse snapshot contents)
ls /srv/nas-zfs/.zfs/snapshot/
cp /srv/nas-zfs/.zfs/snapshot/autosnap_2026-01-26_hourly/configs/file.txt /srv/nas-zfs/configs/
```

### rclone Sync (OneDrive to Nextcloud)

Scheduled one-way sync from a school Microsoft OneDrive account to Nextcloud via WebDAV, managed by `playbooks/rclone-sync.yml`. Runs on macbook-pro.

**Architecture:**
```
OneDrive for Mac (desktop app) → local folder → rclone sync → nextcloud:UTD OneDrive/ (WebDAV)
```

**Why macbook-pro**: The UTD Microsoft 365 tenant blocks third-party OAuth apps, so rclone can't access OneDrive directly. Instead, the OneDrive desktop app syncs files locally, and rclone copies the local folder to Nextcloud. Only syncs when the MacBook is awake (catches up on login via `RunAtLoad`).

**Configuration** (`host_vars/macbook-pro/rclone-sync.yml`):
- Source: `/Users/johnny/Library/CloudStorage/OneDrive-TheUniversityofTexasatDallas` (local)
- Schedule: Every 2 hours (launchd `StartInterval: 7200`)
- Mode: `rclone sync` (deletes propagate — safe due to ZFS snapshots + restic backups)
- Monitoring: Uptime Kuma push monitor (pings on success)

**rclone remotes** are configured manually (not Ansible-managed) because they contain credentials. Config lives at `~/.config/rclone/rclone.conf` on macbook-pro. Only the `nextcloud` WebDAV remote is needed (no OneDrive remote).

**Key commands:**
```bash
# Deploy the playbook
ansible-playbook playbooks/rclone-sync.yml --limit macbook-pro

# Manual sync trigger (on MacBook)
~/.local/bin/rclone-sync

# Check status
launchctl list | grep rclone
cat ~/Library/Logs/rclone-sync.log

# Check failure count
cat ~/.local/share/rclone-sync/consecutive_failures

# Re-authenticate Nextcloud WebDAV if password changes
rclone config reconnect nextcloud:
```

**Auth failure handling**: The sync script detects exit code 6 (auth failure), logs a clear message with re-auth instructions, and tracks consecutive failures in `~/.local/share/rclone-sync/consecutive_failures`. If the Uptime Kuma push monitor stops receiving heartbeats, it alerts.

**Fallback**: If UTD IT approves the OAuth request (submitted 2026-02-06), the sync can be moved back to pi5-01 using rclone's OneDrive remote directly. The pi5-01 config is preserved (commented out) in `host_vars/pi5-01/rclone-sync.yml`.

### Network Recovery

Automatic recovery after router/WiFi restarts is handled by `playbooks/network-recovery.yml`. This deploys two components to Linux servers (excludes `workstations` group):

**Network Watchdog** (`network-watchdog.timer`): Runs every 60 seconds and:
- Checks gateway connectivity (pings router)
- Checks Tailscale connectivity (pings 100.100.100.100)
- On Proxmox hosts: Fixes bridge interfaces that got detached (common issue when router restarts - `eno1` gets removed from `vmbr0`)
- After 3 gateway failures: Restarts networking/DHCP
- After 5 Tailscale failures: Restarts tailscaled
- After 5 DHCP recovery failures: Reboots (with backoff) if router is reachable
- On recovery: Restarts all docker compose stacks (`docker compose restart`) to clear stale connection state, remounts NFS

**Router Reachability Check**: Before auto-rebooting for DHCP failures, the watchdog checks if the router is actually reachable (to avoid boot loops during real outages). Uses a multi-layered approach that works in all environments:
1. **Carrier check** - If physical link is down, skip reboot (network outage)
2. **ARP cache check** - If gateway MAC is cached, router was recently reachable (works in LXC)
3. **arping fallback** - Only on hosts where raw sockets work (Proxmox)

**Tailscale Online Target** (`tailscale-online.target`): A systemd target that only activates when Tailscale is actually connected (not just the daemon running). Services like `docker-stacks.service` depend on this instead of `tailscaled.service`.

Key files:
- `templates/network-watchdog.sh.j2` - Watchdog script with Proxmox bridge fix and router reachability check
- `playbooks/network-recovery.yml` - Deploys watchdog and tailscale-online target (hosts: `linux_hosts:!workstations`)

Troubleshooting network issues:
```bash
# Check watchdog status and logs
systemctl status network-watchdog.timer
journalctl -t network-watchdog -f

# Manually run watchdog
sudo /usr/local/sbin/network-watchdog

# Check if Proxmox bridge has all interfaces attached
brctl show vmbr0  # Should include eno1

# Manually fix detached bridge interface
sudo brctl addif vmbr0 eno1

# Check Tailscale status
tailscale status
```

### jn-desktop (Gaming Workstation)

jn-desktop is a CachyOS (Arch-based) gaming PC with dual-boot Windows. Tailscale IP: `100.123.248.34`.

**Hardware:**
- Custom gaming build with RGB (NZXT Kraken X3 AIO, Corsair RAM, MSI motherboard)
- 1.8TB NVMe games drive (shared with Windows, NTFS)
- GPU for gaming (no GPU passthrough - native Linux gaming)

**OS Choice**: CachyOS was chosen over standard Arch for its gaming-optimized defaults:
- Pre-configured gaming kernel with performance patches
- CachyOS "Install Gaming packages" meta-package handles Steam, Proton, Wine, Lutris, mangohud, gamescope
- Optimized builds of gaming-related packages

**Ansible Configuration:**

jn-desktop is in both `arch_hosts` (for pacman package management) and `workstations` (for workstation-specific behavior). The `workstations` group_vars disable network watchdog and auto-updates.

Host vars in `inventory/host_vars/jn-desktop/`:

| File | Purpose |
|------|---------|
| `vars.yml` | `admin_user: johnny` (watchdog/updates inherited from `group_vars/workstations`) |
| `packages.yml` | OpenRGB, liquidctl, Discord, Flatpak (gaming packages from CachyOS) |
| `nfs.yml` | NFS mount for `/mnt/nas-zfs` (full nas-zfs access) |
| `mounts.yml` | NTFS `/mnt/games` drive (1.8TB NVMe shared with Windows) |
| `backup.yml` | Restic backup of `/home/johnny` and `/etc/udev/rules.d` |

**Storage Mounts:**

| Mount | Type | Source | Purpose |
|-------|------|--------|---------|
| `/mnt/games` | NTFS (ntfs3) | Local NVMe (UUID: 763A44543A441391) | Games shared with Windows dual-boot |
| `/mnt/nas-zfs` | NFS | ts440:/nas-zfs | Full NAS access over Tailscale |

**NTFS Mount Options**: Uses `ntfs3` kernel driver (not ntfs-3g FUSE) with `uid=1000,gid=1000,umask=0022,nofail` for proper permissions and boot resilience.

**Nextcloud Symlinks:**

XDG directories are symlinked to Nextcloud-synced folders:
- `~/Documents` → `~/Nextcloud/Documents`
- `~/Downloads` → `~/Nextcloud/Downloads/jn-desktop`
- `~/Pictures` → `~/Nextcloud/Photos`

This allows apps that save to standard locations to automatically sync via Nextcloud. Downloads uses a machine-specific subfolder to avoid conflicts with other devices.

**Gaming Setup:**

CachyOS's gaming meta-package handles most gaming software. Ansible only manages:
- `openrgb` - RGB control for Corsair RAM, MSI motherboard
- `liquidctl` - NZXT Kraken X3 AIO and Smart Device V2 control
- `discord` - Communication
- `flatpak` - For apps not in AUR

**Proton**: CachyOS provides `proton-cachyos` which appears in Steam as "proton-cachyos-X.X-YYYY-MMDD (steam linux runtime)". This is the recommended default for most games. For problematic games, try GE-Proton or official Steam Proton versions.

**RGB Configuration** (not Ansible-managed, backed up via restic):

RGB control uses a hybrid approach with OpenRGB and liquidctl:
- `~/.local/bin/rgb-hybrid.sh` - Main script that applies all RGB settings
- `~/.config/autostart/rgb-hybrid.desktop` - Autostart entry
- `~/.config/OpenRGB/` - OpenRGB profiles and settings
- `/etc/udev/rules.d/` - udev rules for liquidctl hardware access

**liquidctl devices:**
- NZXT Kraken X3 (AIO cooler) - Controlled via liquidctl
- NZXT Smart Device V2 (fan/LED controller) - Controlled via liquidctl

**OpenRGB devices:**
- Corsair Vengeance RGB RAM
- MSI motherboard RGB

Restore RGB config from backup:
```bash
# Restore from restic (home directory backup)
restic -r sftp:johnny@100.71.188.16:/srv/nas-zfs/backups/jn-desktop restore latest --target /tmp/restore --include /home/johnny/.local/bin/rgb-hybrid.sh --include /home/johnny/.config/OpenRGB --include /home/johnny/.config/autostart

# Restore udev rules
restic -r sftp:johnny@100.71.188.16:/srv/nas-zfs/backups/jn-desktop restore latest --target /tmp/restore --include /etc/udev/rules.d
```

**BeamMP (BeamNG Multiplayer):**

A launcher script exists at `~/.local/bin/beamng-launcher.sh` that provides a KDialog menu for:
1. Single Player BeamNG.drive
2. Multiplayer via BeamMP
3. Check for BeamMP updates

The BeamMP launcher is stored at `/mnt/games/BeamMP/BeamMP-Launcher`.

**Proton Prefix Issues:**

Steam games on Linux use Proton prefixes at `/mnt/games/SteamLibrary/steamapps/compatdata/<appid>/`. Common issues:
- `My Documents` is a Windows .lnk file, not a real directory - Steam cloud sync may fail trying to write to literal path
- If cloud sync fails with "error 2" (file not found), the Proton prefix may need recreation
- Fix: Delete the compatdata folder for the game and let Steam recreate it on next launch

**Bootstrap Notes:**

jn-desktop uses Arch Linux, so bootstrap.yml handles:
- `wheel` group instead of `sudo` group for admin users
- `sshd` service name instead of `ssh` (Debian naming)
- `pacman` package manager instead of `apt`

### jn-t14s-lin (ThinkPad T14s Laptop)

jn-t14s-lin is a Lenovo ThinkPad T14s running Kubuntu 25.10 (Questing Quokka) with dual-boot Windows. Tailscale IP: `100.73.46.86`.

**Ansible Configuration:**

jn-t14s-lin is in both `debian_hosts` (directly, for apt package management) and `workstations` (for workstation-specific behavior). The `workstations` group_vars disable network watchdog and auto-updates.

Host vars in `inventory/host_vars/jn-t14s-lin/`:

| File | Purpose |
|------|---------|
| `vars.yml` | `admin_user: johnny`, sudo-rs become flags |
| `backup.yml` | Restic backup of `/home/johnny` (offsite B2 + local ts440 ZFS) |
| `wifi.yml` | WiFi powersave disable + optional ath11k resume hooks (PCI FLR or module reload) |
| `packages.yml` | `plasma-discover-backend-flatpak` (KDE Flatpak/Discover integration) |

**sudo-rs Compatibility:**

Ubuntu 25.10+ ships `sudo-rs` (Rust implementation) as the default sudo. sudo-rs doesn't support `!requiretty` and wraps custom prompts in `[sudo: ...]`, breaking Ansible's become nonce detection. The `bootstrap.yml` playbook automatically detects sudo-rs (checks for `/usr/lib/cargo/bin/sudo`) and deploys `NOPASSWD: ALL` instead of `!requiretty`. Hosts with sudo-rs also need `ansible_become_flags: "-S"` in host_vars.

**WiFi (Qualcomm QCNFA765 / ath11k_pci):**

The WCN6855 chipset (firmware `WLAN.HSP.1.1-03125...3.6510.41`) has a known kernel bug where WiFi fails to reconnect after suspend/resume. A kernel fix landed in 6.16 and is present in Kubuntu 25.10's 6.17 kernel, but Arch users report it's still intermittent on 6.17-6.18.

Current config:
- WiFi power saving disabled (`wifi.powersave = 2` in NetworkManager) to reduce random disconnects
- Two optional resume hooks in `wifi.yml` (both commented out in host_vars):
  - **PCI FLR** (preferred): `wifi_pci_flr_fix` + `wifi_pci_device` — lightweight hardware reset without tearing down driver
  - **Module reload** (fallback): `suspend_resume_wifi_fix` + `wifi_module` — full modprobe -r/modprobe cycle

**Backups:**
- Offsite (B2): `/etc`, `/home/johnny` — daily
- Local (ts440 ZFS): `/home/johnny` — hourly to `/srv/nas-zfs/backups/jn-t14s-lin/`

## Key Files

| File | Purpose |
|------|---------|
| `site.yml` | Master playbook that imports packages, msmtp, smartmontools, apcupsd, ssh-hardening, auto-updates, network-recovery, wifi, restic, local-restic, nfs, filesystem-mounts, samba, mergerfs, zfs-snapshots, virtiofs, docker-stacks, gluetun-watchdog, rclone-sync, storage-status, proxmox-firewall |
| `playbooks/packages.yml` | Multi-platform package installation |
| `playbooks/msmtp.yml` | Lightweight SMTP relay (iCloud) for system email alerts |
| `playbooks/smartmontools.yml` | SMART disk monitoring with email alerts |
| `playbooks/apcupsd.yml` | UPS monitoring (pve-m70q master, other nodes as network slaves) |
| `playbooks/ssh-hardening.yml` | SSH security configuration (key auth, disable password) |
| `playbooks/bootstrap.yml` | Initial admin user/SSH setup (run as root first time, supports Debian and Arch) |
| `playbooks/auto-updates.yml` | Systemd timer for scheduled updates |
| `playbooks/network-recovery.yml` | Network watchdog and Tailscale online target for auto-recovery |
| `playbooks/wifi.yml` | WiFi powersave disable, optional PCI FLR or module reload resume fix |
| `playbooks/restic.yml` | Backblaze B2 offsite backup configuration |
| `playbooks/local-restic.yml` | Local backups to ts440 ZFS (hourly) |
| `playbooks/mergerfs.yml` | MergerFS media pool (nas_server) |
| `playbooks/zfs-snapshots.yml` | ZFS snapshots (sanoid), scrub, ARC tuning, ACLs (nas_server) |
| `playbooks/nfs.yml` | NFS server (nas_server) and client mounts |
| `playbooks/filesystem-mounts.yml` | Local filesystem mounts (NTFS, exFAT, bind mounts) for non-NFS drives |
| `playbooks/samba.yml` | Samba/SMB shares and Time Machine (nas_server) |
| `playbooks/docker-stacks.yml` | Deploy Docker Compose stacks and prune dangling images |
| `playbooks/gluetun-watchdog.yml` | Gluetun VPN crash loop detection and auto-restart (media-vm) |
| `playbooks/virtiofs.yml` | Configure VirtioFS shares between Proxmox hosts and VMs |
| `playbooks/rclone-sync.yml` | rclone sync from OneDrive to Nextcloud (macbook-pro via launchd, pi5-01 via systemd) |
| `playbooks/git-sync.yml` | Git auto-pull timer on ts440 (syncs GitHub repo every 5 minutes for Nextcloud External Storage) |
| `playbooks/proxmox-firewall.yml` | Deploy Proxmox firewall rules (datacenter, node, VM/CT) |
| `tasks/tailscale.yml` | Tailscale VPN installation |
| `tasks/docker-network.yml` | Ensure Docker networks exist |
| `tasks/fastfetch.yml` | System info tool with login hook |
| `tasks/docker.yml` | Docker CE installation from official repository |
| `tasks/sanoid.yml` | Sanoid installation and ZFS snapshot configuration |
| `tasks/zfs-scrub.yml` | ZFS scrub schedule, ARC tuning, dataset validation, ACLs |
| `tasks/nfs-server.yml` | NFS server setup with bind mounts and exports |
| `tasks/nfs-client.yml` | NFS client mount configuration |
| `tasks/filesystem-mounts.yml` | Local filesystem mounts (NTFS/exFAT drives, bind mounts) |
| `tasks/samba.yml` | Samba server setup with fruit VFS for macOS |
| `templates/exports.j2` | Jinja2 template for /etc/exports |
| `templates/smb.conf.j2` | Jinja2 template for /etc/samba/smb.conf |
| `templates/sanoid.conf.j2` | Jinja2 template for sanoid snapshot configuration |
| `templates/msmtprc.j2` | msmtp SMTP relay configuration |
| `templates/smartd.conf.j2` | smartmontools monitoring configuration |
| `templates/apcupsd.conf.j2` | apcupsd UPS daemon configuration (master/slave) |
| `templates/apcupsd-event-notify.sh.j2` | apcupsd email notification script |
| `templates/mergerfs-media.mount.j2` | MergerFS systemd mount unit |
| `templates/avahi-timemachine.service.j2` | Avahi mDNS advertisement for Time Machine |
| `templates/docker-stacks.service.j2` | Systemd service to start Docker stacks (depends on tailscale-online.target) |
| `templates/network-watchdog.sh.j2` | Network watchdog script with Proxmox bridge fix |
| `templates/gluetun-watchdog.sh.j2` | Gluetun VPN crash loop watchdog script |
| `templates/proxmox-virtiofs-directory.cfg.j2` | VirtioFS directory mappings for Proxmox |
| `templates/proxmox-cluster-firewall.fw.j2` | Datacenter firewall (IP sets, security groups) |
| `templates/proxmox-node-firewall.fw.j2` | Node-level firewall rules |
| `templates/proxmox-vm-firewall.fw.j2` | VM/CT firewall rules |
| `bin/ansible-menu` | Interactive bash script for running playbooks |

**media-vm specific files** (not Ansible-managed, deployed manually):

| File | Purpose |
|------|---------|
| `/usr/local/bin/qbit-port-sync` | Script to sync qBittorrent port with Gluetun forwarded port |
| `/etc/systemd/system/qbit-port-sync.path` | Watches Gluetun port file for changes |
| `/etc/systemd/system/qbit-port-sync.service` | Runs port sync script when triggered |

### Proxmox Firewall (Ansible-Managed)

The `proxmox-firewall.yml` playbook manages firewall rules at three levels.

**VM/CT Reference:**

| VMID | Name | Node | Purpose |
|------|------|------|---------|
| 100 | media-vm | ts440 | Plex, *arr stack, media services |
| 101 | nextcloud-vm | ts440 | Nextcloud AIO |
| 102 | homebridge-lxc | ts440 | Apple HomeKit bridge (Govee, dummy switches) |
| 106 | syncthing-lxc | pve-alto | File synchronization |
| 110 | docker-vm | pve-m70q | Caddy, Vaultwarden, monitoring |
| 120 | haos-vm | pve-alto | Home Assistant OS (HomeKit bridge) |

**Three firewall levels:**

**1. Datacenter (`/etc/pve/firewall/cluster.fw`):**
- IP sets: Named groups of IPs (e.g., `haos-vm`, `docker-vm`, `pve-alto`)
- Security groups: Reusable rule sets (e.g., `corosync-lan` for cluster heartbeat)
- Configuration: `group_vars/proxmox_nodes/firewall.yml`

**2. Node (`/etc/pve/nodes/<node>/host.fw`):**
- Node-level rules for API, SSH, cluster traffic
- Each node can have different rules (e.g., ts440 has NFS/SMB rules)
- Configuration: `host_vars/<node>/firewall.yml` under `pve_node_firewall`

**3. VM/CT (`/etc/pve/firewall/<vmid>.fw`):**
- Per-VM rules with default deny policy
- Only allows traffic from specific sources (e.g., Caddy for reverse proxy)
- Configuration: `host_vars/<node>/firewall.yml` under `pve_vm_firewalls`

**Key configuration files:**

| File | Purpose |
|------|---------|
| `inventory/group_vars/proxmox_nodes/firewall.yml` | Shared IP sets, security groups, firewall enabled flag |
| `inventory/host_vars/ts440/firewall.yml` | ts440 node + VM 100, 101, 102 rules |
| `inventory/host_vars/pve-alto/firewall.yml` | pve-alto node + VM 120, CT 106 rules |
| `inventory/host_vars/pve-m70q/firewall.yml` | pve-m70q node + VM 110 rules |
| `inventory/host_vars/pve-herc/firewall.yml` | pve-herc node rules (no VMs yet) |

**Security model:**
- Default deny on all VM/CT inbound traffic (`policy_in: DROP`)
- Caddy (docker-vm) is the only entry point for web services
- Direct access to service ports (8989, 7878, etc.) is blocked except from Caddy
- SSH allowed from Tailscale for management

**Firewall commands:**
```bash
# Deploy firewall rules
ansible-playbook playbooks/proxmox-firewall.yml

# Deploy to specific node
ansible-playbook playbooks/proxmox-firewall.yml --limit ts440

# View deployed rules
ansible ts440 -m shell -a "cat /etc/pve/firewall/cluster.fw" --become
ansible ts440 -m shell -a "cat /etc/pve/nodes/\$(hostname)/host.fw" --become
ansible ts440 -m shell -a "cat /etc/pve/firewall/100.fw" --become

# Test that direct access is blocked (should timeout)
curl -m 5 100.66.6.113:8989

# Verify Caddy can still reach services (from docker-vm)
ansible docker-vm -m shell -a "curl -s http://100.66.6.113:8989" --become
```

**IP Set reference format:**
- In node rules: `+<ipset_name>` (e.g., `+pve-alto`)
- In VM rules: `+dc/<ipset_name>` (e.g., `+dc/docker-vm`) - `dc/` prefix references datacenter-level IP sets

### homebridge-lxc (CT 102 on ts440)

Homebridge instance bridging smart home devices to Apple HomeKit.

**Plugins:**
- `homebridge-govee` - Govee Smart Air Purifier (connects via HTTP API)
- `homebridge-dummy` - Virtual switches for automations

**Firewall requirements** (in `host_vars/ts440/firewall.yml`):
- TCP 8581 - Homebridge web UI
- TCP 51000-56000 - HomeKit Accessory Protocol (HAP) for main bridge and child bridges
- UDP 5353 - mDNS/Bonjour for HomeKit discovery

**Important**: Homebridge uses dynamic ports for child bridges. The main bridge port is configured in Homebridge (default 51217), but each plugin running as a child bridge gets its own port. Allow a range (51000-56000) rather than a single port.

**Troubleshooting "No Response" in Home app:**
1. Check Homebridge service: `ansible homebridge-lxc -m shell -a "systemctl status homebridge" --become`
2. Check logs: `ansible homebridge-lxc -m shell -a "tail -50 /var/lib/homebridge/homebridge.log" --become`
3. Verify firewall allows HAP ports and mDNS
4. Ensure iOS device is on the same LAN (192.168.1.x) as homebridge-lxc (192.168.1.106)

**Web UI**: `http://100.96.116.42:8581` (Tailscale) or `http://192.168.1.106:8581` (LAN)

### haos-vm (VM 120 on pve-alto)

Home Assistant OS instance for home automation.

**Integration with Homebridge:**
Some devices flow through a chain: Device → Homebridge → Home Assistant (via HomeKit Controller) → HomeKit (via HomeKit Bridge). For example, the Govee purifier appears in HomeKit via this path, not directly from Homebridge.

**Firewall requirements** (in `host_vars/pve-alto/firewall.yml`):
- TCP 8123 - Home Assistant web UI
- TCP 22 - SSH
- TCP 21000-21100 - HomeKit bridge HAP (for HA's HomeKit integration)
- UDP 5353 - mDNS/Bonjour for HomeKit discovery

**HA Companion App Configuration:**
The iOS/Android Companion app has separate Internal URL and External URL settings. For Tailscale-based access, set **both** to the same MagicDNS URL:
```
http://homeassistant.hinny-liberty.ts.net:8123
```
If the Internal URL is blank, the app fails to connect when it detects being on the "local" network.

**Web UI**: `http://100.73.17.121:8123` (Tailscale) or `http://192.168.1.64:8123` (LAN)

**Tailscale MagicDNS**: `http://homeassistant.hinny-liberty.ts.net:8123`

### VirtioFS Ansible Management

The `virtiofs.yml` playbook manages VirtioFS shares between Proxmox hosts and guest VMs:

**Host side (Proxmox):**
1. Creates `/etc/pve/mapping/directory.cfg` with path mappings from `virtiofs_directory_mappings`
2. Adds VirtioFS lines to VM config (`/etc/pve/qemu-server/<vmid>.conf`) based on `virtiofs_host_configs`

**Guest side (VM):**
1. Creates mount point directories
2. Adds entries to `/etc/fstab`
3. Mounts the VirtioFS shares

**Configuration structure:**
```yaml
# host_vars/ts440/virtiofs.yml - Proxmox host
# virtiofs_directory_mappings is the CANONICAL list of all available shares
# The template only uses this list for directory.cfg
virtiofs_directory_mappings:
  - name: plex_library
    path: /srv/plex-library
  - name: nextcloud_data
    path: /srv/nas-zfs/nextcloud

# virtiofs_host_configs specifies which shares attach to which VMs
virtiofs_host_configs:
  - vmid: 101
    index: 0
    name: nextcloud_data      # References name from directory_mappings
    host_path: /srv/nas-zfs/nextcloud
    cache: never

# host_vars/nextcloud-vm/virtiofs.yml - Guest VM
virtiofs_mounts:
  - name: nextcloud_data
    mount_point: /srv/nextcloud
    owner: root
    group: root
    mode: "0755"
```

**Important notes:**
- `virtiofs_directory_mappings` is the single source of truth for available shares
- VM restart required after adding VirtioFS config to host (playbook notifies but doesn't restart)
- Both media-vm and nextcloud-vm VirtioFS configs are now fully Ansible-managed

### Nextcloud External Storage

Nextcloud's External Storage app provides access to ZFS paths via VirtioFS without duplicating data into Nextcloud's data directory.

**Architecture:**
```
ts440 ZFS                    nextcloud-vm                    Nextcloud container
─────────────────────────────────────────────────────────────────────────────────
/srv/nas-zfs/configs    →    /srv/configs (VirtioFS)    →    /srv/external/configs
                              ↓ bind mount
                             /srv/external/configs
```

Nextcloud AIO's `NEXTCLOUD_MOUNT` only supports a single path, so we use bind mounts to consolidate multiple VirtioFS paths under `/srv/external`.

**Configured external storage:**

| Folder Name | Path in Nextcloud | Source on ts440 | Access |
|-------------|-------------------|-----------------|--------|
| Configs | `/srv/external/configs` | `/srv/nas-zfs/configs` | Read-write |
| AIO Backup | `/srv/external/nextcloud-aio-backup` | `/srv/nas-zfs/backups/nextcloud-aio` | Read-write |
| Photos | `/srv/external/photos` | `/srv/nas-zfs/media/photos` | Read-only (Immich-managed) |

**Ansible configuration:**
- VirtioFS mounts: `host_vars/nextcloud-vm/virtiofs.yml`
- Bind mounts: `host_vars/nextcloud-vm/mounts.yml`
- Docker compose with `NEXTCLOUD_MOUNT=/srv/external`: `/opt/nextcloud/docker-compose.yml`

**ACL Setup**: The configs directory is owned by `johnny` but Nextcloud runs as `www-data` (UID 33). ACLs on ts440 grant www-data read-write access:
```bash
# Applied on ts440 (source of VirtioFS)
setfacl -R -m u:33:rwX /srv/nas-zfs/configs
setfacl -R -d -m u:33:rwX /srv/nas-zfs/configs  # Default ACL for new files
setfacl -R -d -m o::r /srv/nas-zfs/configs       # Default other-read for VirtioFS passthrough
```

**Important**: These ACLs are only effective for direct host access. VirtioFS does not pass through POSIX ACLs (see "VirtioFS ACL Limitation" above), so files also need base permissions with `o+r`. The default ACL `o::r` ensures new files are created with other-read, which is what Nextcloud actually uses when reading through VirtioFS. Ansible-vault encrypted files (e.g., `vault.yml`) are safe to be world-readable since their contents are encrypted.

**Enabling Local storage option**: By default, Nextcloud disables the "Local" storage type. Enable it:
```bash
ansible nextcloud-vm -m shell -a "docker exec -u www-data nextcloud-aio-nextcloud php occ config:system:set files_external_allow_create_new_local --value=true --type=boolean" --become
```

**Sync to devices**: External Storage folders are excluded from Nextcloud desktop/mobile sync by default. To sync:
1. Open Nextcloud client settings
2. Find the External Storage folder (e.g., Configs)
3. Enable sync for that folder

This allows selective sync - e.g., sync Configs to laptop but not to phone.

**Setup steps** (manual in Nextcloud UI):
1. Enable "External storage support" app (Settings → Apps)
2. Settings → Administration → External storage
3. Add Local storage with folder name and path (e.g., `/srv/external/configs`)
4. Set "Available for" to specific users or all users

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

### Authentik SSO

Authentik (identity provider/SSO) was considered for protecting internal services but deferred due to complexity for a single-user setup. If added later:

1. Deploy Authentik stack on docker-vm (PostgreSQL + Redis + server + worker)
2. Configure Caddy with forward auth for each protected service:
   ```caddyfile
   sonarr.jnalley.me {
       forward_auth authentik-server:9000 {
           uri /outpost.goauthentik.io/auth/caddy
           copy_headers X-Authentik-Username X-Authentik-Groups X-Authentik-Email
           trusted_proxies private_ranges
       }
       reverse_proxy 100.66.6.113:8989
   }
   ```
3. Create embedded outpost and proxy providers in Authentik admin
4. Firewall already configured to only allow traffic from Caddy (docker-vm)

Services that would bypass Authentik (have their own auth): Plex, Jellyseerr (Plex OAuth), Vaultwarden.

### Docker Compose Migration to Repository

Currently, docker-compose.yml files are created manually on each VM and deployed via `docker_stacks`. A future improvement would be:

1. Store all compose files as Jinja2 templates in `templates/docker-compose/`
2. Create `host_vars/<vm>/docker-services.yml` with service configurations
3. Have Ansible template the compose files to `/opt/<service>/docker-compose.yml`
4. Use ansible-vault for secrets (environment variables)

Benefits:
- Full Infrastructure as Code for Docker services
- Version control for compose file changes
- Centralized secret management

## Ansible Environment

Ansible runs on ansible-lxc (CT 104 on pve-m70q, Ubuntu 25.10) with `ansible-core` 2.19. The controller uses `ansible_connection=local` in the `orchestrator` group. Key collections: `community.docker` 4.6.1, `community.general` 11.1.0, `kewlfft.aur` 0.13.0.

The working repo clone is at `~/homelab-ansible` on ansible-lxc.

**Legacy**: pi5-01 previously served as the Ansible controller using Debian 12's packaged `ansible-core` 2.14. It is now a regular managed host. The repo copy at `/srv/configs/ansible/homelab-ansible` (via NFS from ts440) remains accessible but is read-only (auto-synced from GitHub by git-sync timer).

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
