# CC-Ansible

> **Last updated:** 2026-08-09

Ansible automation for Johnny's homelab infrastructure (4 Proxmox nodes, VMs/LXCs, flat T14s Ansible controller/server, Raspberry Pi Plex appliance, Windows gaming workstation, and MacBook).

**Repository**: https://github.com/johnnynalley/cc-ansible (public)

## Quick Start

```bash
# From the repo directory (on jn-t14s-lin)
cd ~/cc-ansible

# Run a specific playbook
ansible-playbook playbooks/core/packages.yml

# Run all playbooks
ansible-playbook site.yml

# Do not use --limit; playbooks should be safe across their configured target

# Interactive menu
./bin/ansible-menu
```

Routine estate-wide maintenance covers Linux, Proxmox, and Docker systems.
Windows and macOS OS/application updates remain user-managed GUI workflows and
are included only when explicitly requested.

## Streaming Runbook

The current Twitch, YouTube, TikTok, Mac OBS, Aitum Vertical, SleepyChat, and experimental Apple Music routing setup is documented in [docs/streaming-runbook.md](docs/streaming-runbook.md).

## Operator Docs

Start with [docs/README.md](docs/README.md) for the operator-doc index.
Source-of-truth docs currently include:

- [docs/capture-card-streaming-plan.md](docs/capture-card-streaming-plan.md)
- [docs/fortnite-performance-investigation.md](docs/fortnite-performance-investigation.md)
- [docs/gaming-benchmark.md](docs/gaming-benchmark.md)
- [docs/hermes-replacement.md](docs/hermes-replacement.md)
- [docs/immich-media-inbox.md](docs/immich-media-inbox.md)
- [docs/media-release-policy.md](docs/media-release-policy.md)
- [docs/openclaw-docker-access.md](docs/openclaw-docker-access.md)
- [docs/openclaw-heartbeats.md](docs/openclaw-heartbeats.md)
- [docs/openclaw-runtime-security.md](docs/openclaw-runtime-security.md)
- [docs/plex-appliance-operations.md](docs/plex-appliance-operations.md)
- [docs/streaming-runbook.md](docs/streaming-runbook.md)

## Repository Catalogs

- [playbooks/README.md](playbooks/README.md): domain playbook catalog and validation commands.
- [templates/README.md](templates/README.md): template ownership and render-source rules.
- [scripts/README.md](scripts/README.md): script ownership and reusable helper rules.
- [inventory/README.md](inventory/README.md): group hierarchy, host var layout, and where settings live.
- [files/README.md](files/README.md): static file inventory and root clutter notes.
- [scripts/repo/repo-audit](scripts/repo/repo-audit): static repo layout, reference, and secret audit.


## Repository Audit

Run the repository audit before committing layout, docs, script, template,
inventory, or playbook changes:

```bash
scripts/repo/repo-audit
```

`repo-audit` calls `scripts/repo/secrets-scan` by default. The built-in scanner
checks tracked text files for likely plaintext secrets and redacts findings. If
Gitleaks is installed locally, the scan also uses `.gitleaks.toml`; CI runs
`repo-audit --require-gitleaks` so Gitleaks is mandatory there.

## Directory Structure

```
cc-ansible/
├── ansible.cfg                 # Ansible configuration
├── site.yml                    # Full convergence entrypoint
├── AGENTS.md                   # Agent operating rules and source-of-truth pointers
├── README.md                   # Human repo overview
├── docs/                       # Operator docs; start with docs/README.md
├── inventory/                  # Hosts, group vars, host vars; start with inventory/README.md
├── playbooks/                  # Domain-owned playbooks; start with playbooks/README.md
│   ├── core/                   # Base OS, packages, SSH, updates, logging, UPS, users
│   ├── network/                # Network recovery, WiFi, NIC tuning
│   ├── storage/                # NAS, Samba, NFS, ZFS, MergerFS, VirtioFS, storage gates
│   ├── docker/                 # Compose stacks, Gluetun, container auto-updates
│   ├── media/                  # Plex, streaming, media health, release stamping, maintenance
│   ├── backup-sync/            # Restic, local restic, rclone, git sync, Nextcloud scans
│   ├── agents/                 # Codex, Claude archive sync, OpenClaw, Hermes
│   ├── proxmox/                # Proxmox firewall, PBS, PDM, HA, guest hardware, boot ordering
│   ├── windows/                # Windows gaming workstation automation
│   └── apps/                   # Standalone app appliances such as FreePBX/Homebridge
├── tasks/                      # Shared task files imported by playbooks
├── templates/                  # Domain-owned Jinja/rendered sources; start with templates/README.md
├── scripts/                    # Domain-owned helpers; start with scripts/README.md
├── files/                      # Static non-template files; start with files/README.md
├── bin/                        # Operator entrypoints such as ansible-menu
└── backup/                     # Legacy tracked backup material, not active source
```

## Group Hierarchy

```
managed_hosts
├── linux_hosts
│   ├── debian_hosts
│   │   ├── proxmox_nodes (ts440, pve-alto, pve-herc, pve-m70q)
│   │   ├── vms_lxcs
│   │   │   ├── vms (docker-vm, media-vm, nextcloud-vm, freepbx-vm, pdm-vm) ← gets qemu-guest-agent
│   │   │   └── lxcs (homebridge-lxc, syncthing-lxc, pbs-lxc)
│   │   ├── raspberry_pis (mercury)
│   │   └── orchestrator (jn-t14s-lin) ← ThinkPad T14s (Kubuntu)
│   └── arch_hosts (currently empty)
└── macos_hosts (macbook-pro)

workstations (jn-t14s-lin, macbook-pro) ← conservative defaults; T14s overrides auto-updates/reboots as a server

nas_server (ts440) ← portable NAS role group

development (currently empty) ← dev tooling (gh, shellcheck, yq)

docker_hosts (docker-vm, media-vm, nextcloud-vm, jn-t14s-lin) ← Docker Compose stacks

gluetun_hosts (media-vm) ← Gluetun/qBittorrent VPN automation

backup_clients
├── proxmox_nodes
├── vms_lxcs
├── raspberry_pis
├── orchestrator
├── workstations
└── arch_hosts

retired_hosts (dev-vm, jn-desktop) ← retained records, excluded from site.yml
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

Ansible uses a dedicated passwordless SSH key (`~/.ssh/ansible_ed25519` on jn-t14s-lin) as a fallback for managed hosts, configured in `ansible.cfg` as `private_key_file`. Tailscale SSH is preferred for managed Linux hosts when tailnet policy allows it.

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
ansible-playbook playbooks/core/bootstrap.yml --ask-become-pass

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
| `sysctl.yml` | `proxmox_nodes` | Kernel VM tuning for Proxmox hosts |
| `smartmontools.yml` | `linux_hosts` | SMART disk monitoring with Apprise push alerts |
| `e1000e-tuning.yml` | `proxmox_nodes` | Disable EEE/TSO on Intel e1000e NICs to prevent hardware TX hangs |
| `apcupsd.yml` | `proxmox_nodes` | UPS monitoring with Apprise push alerts (ts440 USB master, others slave). Staggers slave startup to avoid NIS mutex contention |
| `bootstrap.yml` | `linux_hosts` | Create admin user, SSH keys, sudo setup, timezone (Debian + Arch) |
| `ssh-hardening.yml` | `linux_hosts` | SSH security (key auth, disable password) |
| `auto-updates.yml` | `linux_hosts` | Configure automatic updates (Sun; Proxmox reboots are hourly-staggered, quorum-gated, and shared-lock serialized) |
| `unattended-upgrades.yml` | `debian_hosts` | Daily security patches (incl. workstations, Proxmox blacklist) |
| `network-recovery.yml` | `linux_hosts` | Network watchdog for auto-recovery after outages |
| `wifi.yml` | `linux_hosts` | WiFi powersave disable, optional PCI FLR or module reload resume fix |
| `cloudflare-ddns.yml` | `cloudflare_ddns_hosts` | DNS-only Cloudflare DDNS records for fixed external endpoints with dynamic WAN IPs |
| `tailscale-peer-relay-endpoint.yml` | `tailscale_peer_relay_endpoint_hosts` | Sync Tailscale peer-relay static endpoints to the current WAN IP |
| `windows-signalrgb.yml` | `windows_hosts` | SignalRGB logon/lock/unlock lighting automation on lj-gaming-pc |
| `windows-gaming-tuning.yml` | `windows_hosts` | Low-latency Realtek NIC tuning for the Windows gaming PC |
| `windows-windows-performance-mode.yml` | `windows_hosts` | Windows performance mode triggers for competitive games and OBS streaming/recording |
| `restic.yml` | `backup_clients` | B2 offsite backup with systemd timer |
| `local-restic.yml` | `backup_clients` | Hourly backups to ts440 ZFS |
| `mergerfs.yml` | `nas_server` | MergerFS media pool mount + balance script + config excludes |
| `mergerfs-recovery.yml` | `nas_server` | USB-SATA branch auto-remount (udev) + mount watchdog + Plex/Sonarr/Radarr API refresh on recovery |
| `zfs.yml` | `nas_server` | ZFS snapshots (sanoid), scrub, ARC tuning, property enforcement, ACLs |
| `nfs.yml` | `nas_server` + clients | NFS server/client configuration |
| `filesystem-mounts.yml` | `linux_hosts` | Local filesystem mounts (NTFS, exFAT) |
| `samba.yml` | `linux_hosts` | Samba shares + Time Machine (ts440 + pve-herc) |
| `docker-stacks.yml` | `docker_hosts` | Deploy Docker Compose stacks and the managed Caddyfile (per-service update reporting with version diffs) |
| `immich-media-inbox.yml` | `docker_hosts` (opt-in) | Deploy Astra's headless Immich screenshot semantic-analysis queue |
| `gluetun-watchdog.yml` | media-vm | Gluetun VPN crash loop detection, port forwarding monitoring, auto-restart, and qBittorrent port sync |
| `stream-relay.yml` | media-vm | OBS SRT ingest, Quadro NVENC encode, reliable local fanout, platform RTMP workers, and VOD delivery |
| `plex-server-health.yml` | media-vm, `nas_server` | Plex identity, guest VirtioFS, host virtiofsd, VM 100, and scrub-window sentinel |
| `docker-auto-update.yml` | `docker_hosts` | Auto-update selected containers every 6h with major version guard |
| `agent-docker-report.yml` | `docker_hosts` | Publish a schema-v2 result-only Docker inventory for dedicated agent identities such as Hermes (disabled by default) |
| `openclaw-docker-update-broker.yml` | `docker_hosts` | Install a digest-bound, separately approved service update broker for the isolated OpenClaw identity (disabled by default) |
| `virtiofs.yml` | `proxmox_nodes`, `vms` | Configure VirtioFS shares between Proxmox hosts and VMs |
| `proxmox-vm-hardware.yml` | `proxmox_nodes` | Apply durable Proxmox VM hardware settings such as CPU model overrides |
| `proxmox-boot-order.yml` | `proxmox_nodes` | Configure Proxmox boot ordering guardrails so `pve-cluster` waits for local filesystems and guest autostart waits for `pve-cluster` |
| `rclone-sync.yml` | `managed_hosts` | rclone sync jobs for opted-in managed hosts |
| `git-sync.yml` | `nas_server` | Auto-pull from GitHub every 5 minutes (Nextcloud External Storage) |
| `nextcloud-scan.yml` | nextcloud-vm | Periodic `occ files:scan` for external storage (every 10 min) |
| `claude-memory-sync.yml` | `nas_server`, `orchestrator` | Rsync Claude Code memory archive to NAS for Nextcloud access (every 10 min) |
| `codex-memory-sync.yml` | `nas_server`, `orchestrator` | Rsync Codex CLI memory to NAS for Nextcloud access (every 10 min) |
| `proxmox-firewall.yml` | `proxmox_nodes` | Deploy Proxmox firewall rules (datacenter, node, VM/CT) |
| `proxmox-backup-server.yml` | pbs-lxc, `proxmox_nodes` | Install PBS, configure datastore/prune/GC/API token, register on all PVE nodes, create vzdump backup jobs, deploy connectivity check |
| `proxmox-notifications.yml` | `proxmox_nodes` | PVE webhook notification targets + matchers → Apprise → Pushover |
| `proxmox-ha.yml` | `proxmox_nodes` | Stop/disable/mask `pve-ha-{lrm,crm}` cluster-wide (no HA resources configured; removes fencing risk). Driven by `pve_ha_enabled` (default `false`) |
| `vm-storage-gate.yml` | `proxmox_nodes` | Per-VM start gate: hookscript blocks `qm start`/`pct start` if VM's declared host mountpoints aren't mounted. Per-VM declarations in `host_vars/<vm>/storage.yml` |
| `openclaw.yml` | `openclaw_hosts` | OpenClaw AI agent (npm install, gateway service, repo-sync/update-check timers) |
| `hermes-shadow.yml` | `hermes_hosts` | Boot-disabled, isolated Hermes replacement staging with no production delivery |
| `openclaw-health-receiver.yml` | `openclaw_hosts` | Isolated Health receiver and aggregate-only report publisher (disabled by default) |
| `openclaw-isolated-gateway.yml` | `openclaw_hosts` | Modernized split Gateway/Codex canary with immutable runtime/provider code, separate no-login identities and secrets, isolated executor OAuth, and model proof (disabled by default) |
| `openclaw-state-rehearsal.yml` | `openclaw_hosts` | Verified relocation rehearsal for active file-backed sessions with bounded current/rollback generation retention (disabled by default) |
| `openclaw-doctor-rehearsal.yml` | `openclaw_hosts` | Credential-free Doctor/plugin-modernization rehearsal with bounded upstream and Doctor generation retention (disabled by default) |
| `openclaw-canary-data-rehearsal.yml` | `openclaw_hosts` | Transactional modern-workspace/session handoff to the silent loopback canary with native session plan/apply and rollback (disabled by default) |
| `openclaw-behavior-rehearsal.yml` | `openclaw_hosts` | Channel-less Dubble, native Star delegation, and idle-silent Rigel behavior proof with synthetic-session cleanup (disabled by default) |
| `openclaw-security-rehearsal.yml` | `openclaw_hosts` | Channel-less hostile-prompt proof of the split executor's sudo, Gateway-secret, Docker, and filesystem boundaries (disabled by default) |

## NFS Configuration

TS440 serves NFS exports via Tailscale. VMs have been migrated to local config storage and no longer depend on NFS.

### Server Exports (ts440)

| Export Path | Bind Source | Client | Purpose |
|-------------|-------------|--------|---------|
| `/srv/media` | `/srv/media` | docker-vm | Media pool access |
| `/incomplete-downloads` | `/srv/media-downloads` | docker-vm | Download staging access |

### Client Mounts

| Host | Mount Point | Remote Path |
|------|-------------|-------------|
No active managed clients mount NFS for repo/config storage. The retired Pi and old Linux desktop NFS paths were removed from normal convergence.

**Note**: VMs no longer use NFS. All configs are stored locally:
- docker-vm: `/opt/caddy/`, `/opt/vaultwarden/`, `/opt/uptime-kuma/`, etc.
- media-vm: `/opt/media-stack/` (uses VirtioFS for media access + archive)
- nextcloud-vm: `/opt/nextcloud/` (uses VirtioFS for data storage + archive read-only)

**Archive**: ZFS dataset `nas_zfs/archive` at `/srv/nas-zfs/archive` for ISOs and general archival. Shared via VirtioFS to media-vm (rw) and nextcloud-vm (ro, Nextcloud External Storage at `/srv/external/archive`).

Ansible repo on jn-t14s-lin: `~/cc-ansible`
Retired Pi repo-copy workflow: removed from normal convergence.

## Samba Configuration

Samba is managed by `playbooks/storage/samba.yml` and runs on any `linux_hosts` host with `smb_shares` defined — currently ts440 (nas_server) and pve-herc.

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
| Time Machine | `/srv/pbs-data/timemachine` | macOS Time Machine (active, 350G cap on shared PBS drive) |

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

- Optional static netplan management for hosts with fixed LAN service IPs, such
  as media-vm's `192.168.1.136` OBS/Plex address.
- **Network Watchdog** runs every 60 seconds:
  - Ensures interfaces are UP (catches link flaps where carrier recovers but interface stays DOWN)
  - Fixes Proxmox bridge interfaces that got detached (`eno1`, VM firewall ports like `fwpr100p0`, or plain VM tap ports like `tap130i0` removed from `vmbr0`)
  - Restarts networking/DHCP after gateway failures
  - Restarts Tailscale after connectivity failures
  - Restarts all Docker containers on recovery to clear stale state

- **Tailscale Online Target**: Services depend on `tailscale-online.target` instead of `tailscaled.service` to ensure Tailscale is actually connected before starting.

Check status: `journalctl -t network-watchdog -f`

## Gluetun VPN Watchdog

Gluetun's internal VPN restart doesn't clean up tun0 routes, causing crash loops (`RTNETLINK answers: File exists`). The watchdog (`gluetun-watchdog.yml`) runs every 60 seconds on docker-vm, detects the loop via Docker healthcheck, and does a full `docker compose up -d --force-recreate` of Gluetun + qBittorrent after 3 consecutive failures. Force-recreate (not just restart) is required to destroy the network namespace and clear stale routes. Also monitors port forwarding via Gluetun's internal port file — if the forwarded port is missing for 5 consecutive checks (~5 minutes), force-recreates to get a fresh port assignment. Before recreating, it checks required media bind paths so stale NFS/autofs mounts such as `/srv/archive` block the recreate instead of leaving qBittorrent in `created`. Sends silent Pushover notification on recovery or port forwarding loss (`push-quiet` tag). Rate-limited to 5 restarts/hour.

Check status: `journalctl -t gluetun-watchdog -f`

## Docker Auto-Update

Selected containers are auto-updated every 6 hours via systemd timer (`docker-auto-update.yml`). Opt-in per stack with `auto_update: true` or per service with `auto_update_services: [name]` in `host_vars/<hostname>/docker.yml`. Currently auto-updated: Caddy, Seerr, and Loki-Grafana (docker-vm), Gluetun and LazyLibrarian (media-vm), Diun (all 3 VMs). Pulls/builds new images, uses `docker-stack-diff` to detect changes, only recreates if images changed. Gluetun uses `--force-recreate` with qBittorrent and can require healthy bind paths through `auto_update_required_paths` before compose recreates. **Major version guard**: blocks major version bumps (e.g., `7.x` → `8.x`) and sends a Time Sensitive notification instead of auto-updating. Per-stack opt-out with `major_guard: false`. Config in `group_vars/docker_hosts/auto-update.yml`.

Check status: `journalctl -u docker-auto-update`, `systemctl list-timers docker-auto-update*`

## OpenClaw Docker Reporting

The result-only Docker reporter is implemented but disabled pending the
dedicated OpenClaw service-account migration and an approved canary rollout. It
does not grant Astra Docker socket, Docker group, sudo, or arbitrary SSH access.
See [docs/openclaw-docker-access.md](docs/openclaw-docker-access.md) for the
schema, threat model, rollout gates, and separate update-broker design.

## ZFS Configuration

Managed by `zfs.yml` — snapshots, scrub, ARC tuning, property enforcement, ACLs:

- **Pools**: `nas_zfs` (2x8TB mirror), `media-01` (3TB), `media-02` (3TB)
- **Snapshots**: Sanoid timer every 15 minutes
- **Scrub**: Daily 03:00 timer with a 03:00-09:00 safe window; the script only starts/resumes pools whose last scrub is old enough and pauses long scrubs before viewing hours
- **ARC**: 4GB max (`/etc/modprobe.d/zfs.conf`) — bumped from 1GB after ts440 RAM upgrade to 32GB (2026-05-12), then trimmed as VM footprint grew on ts440
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

`/srv/media` is a mergerfs union of 8 branches:

| Branch | Drive | Type |
|--------|-------|------|
| `/srv/nas-01/media` | 2TB Lacie SSD | ext4 |
| `/srv/nas-02/media` | 2TB LUKS | ext4 on dm-crypt |
| `/srv/nas-zfs/media` | nas_zfs 8TB mirror | ZFS |
| `/srv/media-01/media` | 3TB | ZFS |
| `/srv/media-02/media` | 3TB | ZFS |
| `/srv/media-03/media` | 2TB Hitachi HDD via USB-SATA | ext4 |
| `/srv/media-04/media` | 2TB ex-PBS drive via USB-SATA | ext4 |
| `/srv/media-05/media` | 2TB WD My Passport (ex-Xbox) via USB | ext4 |

- **Create policy**: `epmfs` (existing path most free space) — new files land on the same branch as the existing show/movie directory, which is critical for Sonarr/Radarr hardlinks. Falls back to mfs when no existing path found.
- **USB-SATA drives**: `x-systemd.device-timeout=60s` in fstab — USB enumeration requires more time than the default 5s
- **Config**: `group_vars/nas_server/mergerfs.yml`

## mergerfs-balance

Balances files across mergerfs branches by moving from fullest to emptiest. ZFS-aware (uses `zfs list` for accurate space reporting).

- **Default excludes**: `/etc/mergerfs-balance.conf` protects irreplaceable data on nas_zfs (photos, archive, books) from moving to single-drive pools
- **Config variable**: `mergerfs_balance_exclude_paths` in `group_vars/nas_server/mergerfs.yml`
- **CLI excludes**: `-E` flags merge with config excludes (additive)
- **Evacuation mode**: `--evacuate <branch>` drains one branch to the least-used eligible branches before planned removal or reformat. Dry-run first.
- **Nightly coordinator**: `playbooks/media/nightly-media-maintenance.yml` owns the midnight-7 AM window. The normal nightly path opens Profilarr upgrade work. Mergerfs balance jobs are exception/manual work queued with `nightly-media-maintenance balance add ...`; if a balance job is pending, Profilarr upgrades are skipped until the job is removed, completed, or deferred.
- **Media stack pause/resume**: balance jobs run `/usr/local/sbin/mergerfs-balance-media-stack stop|start` through a forced SSH key to docker-vm. Current balance jobs pause Sonarr, Radarr, Prowlarr, Bazarr, Byparr, qBittorrent, SABnzbd, and Profilarr while Plex stays up. The timer fires hourly inside the window, and the balancer currently scans/selects the first eligible file before the pause hook runs.
- **Storage-layout runbook**: use `docs/media-stack-storage-layout.md` before changing or diagnosing completed-vs-incomplete download paths, hardlinks, docker-vm NFS mounts, TS440 backing storage, `/usenet-complete` cleanup, or balance/import RCA.
- **VirtioFS caveat**: After balancing, media-vm needs a full stop/start (`qm stop`/`qm start`) to clear virtiofsd's stale directory cache

```bash
# Normal balance (5% target spread, config excludes auto-loaded)
mergerfs-balance /srv/media -p 5

# Dry run
mergerfs-balance /srv/media -p 5 --dry-run

# Additional CLI excludes on top of config
mergerfs-balance /srv/media -p 5 -E "/srv/nas-zfs/media/music/*"

# Planned branch removal/reformat: preview moving data off nas-02
mergerfs-balance /srv/media --evacuate nas-02 --dry-run

# Drain nas-02, leaving at least 100G free on destination branches
mergerfs-balance /srv/media --evacuate nas-02 --min-free 100G

# Exception only: queue a managed overnight evacuation, nas-02 -> media-01..04
nightly-media-maintenance balance add --name nas02-evac --evacuate nas-02 \
  --destination media-01 --destination media-02 --destination media-03 \
  --destination media-04 --min-free 100G
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

## Stream Relay (OBS to platforms via media-vm)

`playbooks/media/stream-relay.yml` deploys the media-vm stream relay. media-vm's LAN IP is `192.168.1.136`, managed as static netplan by `playbooks/network/network-recovery.yml`. `stream-relay.service` receives one OBS SRT feed on UDP 9000 and encodes once with `h264_nvenc` on the Quadro P2200. It fans that encoded feed out locally over MPEG-TS/TCP to `stream-relay-output@<platform>.service` workers, which push to Twitch, YouTube, and any future RTMP platform. Stream keys are live-only in `/etc/stream-relay/stream-relay.env`; do not commit them.

```bash
# Deploy relay files and apply the configured service state
ansible-playbook playbooks/media/stream-relay.yml

# On media-vm, create the live env file from the root-only example
sudo cp /etc/stream-relay/stream-relay.env.example /etc/stream-relay/stream-relay.env
sudo nano /etc/stream-relay/stream-relay.env

# Start the listener and output workers before OBS
sudo systemctl start stream-relay.service
sudo systemctl start stream-relay-output@twitch.service stream-relay-output@youtube.service
sudo journalctl -u stream-relay.service -u stream-relay-output@twitch.service -u stream-relay-output@youtube.service -f
```

Set `stream_relay_outputs` in `inventory/host_vars/media-vm/stream-relay.yml` to add platform workers, and `stream_relay_output_ports` to assign each worker's local TCP feed. OBS sender settings: Custom service, server `srt://192.168.1.136:9000?mode=caller&transtype=live&latency=5000000`, stream key `obs`, and stream bitrate `12000 Kbps`. The relay binds to media-vm's LAN address so the high-bitrate OBS feed stays on the same switch. The producer copies OBS's incoming AAC audio instead of adding another producer-side AAC encode; Twitch receives Track 1 for live playback and confirmed clean Track 2 for VODs, while YouTube re-encodes Track 2 with `aresample=async=1:first_pts=0` so YouTube gets fresh 48 kHz audio timestamps. The relay intentionally avoids FFmpeg `nobuffer`/`low_delay` flags because the SRT path already has explicit latency and overly aggressive buffering caused audible artifacts in live testing. With the current TCP fanout, a platform worker that disconnects after latching usually needs a full landscape relay restart, not an output-only restart. Landscape VOD recording discards tiny header-only fragments and salvages stale readable incoming recordings before remux.

`stream-relay-vertical.service` is the separate Aitum Vertical path for a standalone YouTube vertical/Shorts live stream. It listens for Aitum on `rtmp://100.66.6.113:1936/live` with stream key `vertical`, then sends the 9:16 feed to `YOUTUBE_VERTICAL_STREAM_KEY` from `/etc/stream-relay/stream-relay.env`. This is currently parked in favor of YouTube's automatic dual-stream mode because the unified chat workflow only tracks one YouTube live chat cleanly. Leave the Aitum layout intact for TikTok/virtual-camera use later, but keep Aitum's separate stream output disabled while this relay is parked.

The Proxmox firewall uses the `streaming-pc` datacenter IP set. Current entries include lj-gaming-pc's Windows LAN IP and Tailscale IP. Because Tailscale advertises `192.168.1.0/24`, Windows also needs a persistent host route for media-vm's LAN IP so OBS traffic to `192.168.1.136` uses Ethernet instead of the Tailscale tunnel.

## Profilarr Release Policy

Sonarr/Radarr now run on docker-vm. The active library and request defaults use
the promoted efficient profiles: `shows-regular-efficient`,
`shows-anime-efficient`, `movies-regular-efficient`, and
`movies-anime-efficient`. Recyclarr is disabled and removed from the active
media-stack compose service list; future profile/CF work should go through
Profilarr-backed repo scripts.
The detailed release-selection policy and score-band rules are documented in
[docs/media-release-policy.md](docs/media-release-policy.md).

- **Profiles**: efficient profiles for live media; balanced profiles for
  future experiments after they get the same efficient-policy treatment.
  Non-English regular media that should prefer original-language+English audio
  can use `shows-regular-dual-audio-efficient` or
  `movies-regular-dual-audio-efficient`; defaults stay on the normal efficient
  profiles so English-original shows do not prefer unrelated multi-audio
  releases.
- **Anime scoring**: Dual Audio +100000, quality-rank CFs
  +10000/+20000/+30000/+40000 by enabled resolution tier, x265 +5000,
  Dictionarry primary tiers plus Profilarr-synced TRaSH fallback tiers below
  x265, hard rejects -1000000, soft avoids kept small enough not to outrank
  quality
- **Live check**: run
  `ansible docker-vm -m script -a scripts/media-release/sonarr_release_expectation_check.py`
  and
  `ansible docker-vm -m script -a scripts/media-release/radarr_release_expectation_check.py`
  to verify the active anime scores, native quality grouping, DA/x265
  title-side custom-format matching, rename-format preservation of audio
  languages and video codec, and profile assignment counts. For suspected
  original-language-only regressions, run
  `ansible docker-vm -m script -a "scripts/media-release/sonarr_original_language_audit.py --since <UTC timestamp> --history-only"`
  first, then targeted `sonarr_release_rejection_report.py` manual checks for
  the affected patterns. Run
  `ansible docker-vm -b -m script -a "scripts/media-release/arr_regular_dual_audio_profiles.py --apply --assign-sonarr-title-regex '<title regex>'"`
  when a non-English regular series should move to the dual-audio efficient
  profile.
- **Profile classification**: run
  `ansible docker-vm -b -m script -a "scripts/media-release/arr_profile_classification.py --no-backup"`
  to verify every series/movie is on the expected efficient profile. The
  classifier maps anime to anime efficient profiles, English-original regular
  media to regular efficient profiles, and non-English non-anime media to the
  regular dual-audio efficient profiles. Apply with `--apply --search-changed`
  only after reviewing the dry-run output.
- **Queue check**: run
  `ansible docker-vm -m script -a scripts/media-release/sonarr_grab_forensics.py` first to
  classify queued grabs as valid upgrades, payload score loss, pack
  collateral/mapping issues, or client warnings. For Radarr, run
  `ansible docker-vm -m script -a scripts/media-release/radarr_grab_forensics.py`
  to classify movie downloads against current file scores and import-rejection
  score messages. Then run
  `ansible docker-vm -m script -a scripts/media-release/sonarr_grab_diagnostics.py` before
  clearing suspected bad grabs; cleanup requires explicit flags and does not
  blocklist by default
- **Import metadata stamping**: `playbooks/media/media-release-stamper.yml` deploys
  qBittorrent/SABnzbd stampers so DA/x265/platform/release-group evidence seen
  at grab time survives into payload filenames before Sonarr/Radarr import.
  DA/x265 are per-file media-verified; platform tags and release-group suffixes
  are copied only as parent-title release context. If Sonarr context is
  available, ambiguous TV payload names with episode tokens can be rewritten to
  the canonical series title so multi-file packs stay parseable at import.
- **Series check**: run
  `ansible docker-vm -m script -a "scripts/media-release/sonarr_series_audit.py Bleach"` to
  inspect one show's monitored seasons, missing episode counts, queue, recent
  history, and active commands
- **Profilarr staging**: run
  `ansible docker-vm --become -m script -a "scripts/media-release/arr_stage_profilarr_test_profiles.py --dry-run"`
  before changing candidate profiles; the script snapshots live Arr policy and
  enforces the current CF limit
- **Selective Profilarr CF sync**: run
  `ansible docker-vm --become -m script -a "scripts/media-release/profilarr_selective_cf_import.py --dry-run"`
  before applying curated Dictionarry/Dumpstarr CF definition refreshes; this
  imports selected CFs and scores only candidate profiles until explicitly
  promoted
- **Manual/local CFs**: Local anime quality-rank CFs, Local Anime Raw Group -
  DBD-Raws (-1000000), Portuguese (No English) (-1000000), 2160p guards
  (-1000000) - created directly in Sonarr/Radarr

## Profilarr Upgrade Automation

Profilarr is staged on docker-vm as a managed Docker stack at `/opt/profilarr`
and is published at `profilarr.jnalley.me`. It is being evaluated as the
proactive library-upgrade layer: upgrade jobs with filters, selectors,
cooldowns, dry runs, and live searches. Native Profilarr scheduled Arr upgrades
stay disabled; the nightly media maintenance coordinator opens the Profilarr
upgrade window hourly from midnight through 6 AM. Routine mergerfs balance is
disabled by policy; an explicitly queued exception balance job blocks Profilarr
until removed, completed, or deferred.

Operational rules:

- Keep Sonarr/Radarr failed-download auto-redownload disabled; Profilarr should
  own paced proactive upgrade searches.
- For Sonarr, prefer Profilarr upgrade filters that trigger `SeriesSearch`
  one series at a time; do not use episode-level upgrade churn.
- Keep Prowlarr's automatic-search indexer set clean before enabling live
  upgrade jobs. Broken broad public indexers should be disabled or removed
  instead of left to time out every search.
- NZBFinder quota exhaustion is not a disable/remove condition by itself; leave
  it enabled and let Prowlarr's temporary cooldown skip it until quota resets.
- Run Profilarr dry-run jobs first and compare results against the DA-first,
  quality-rank-second anime policy before enabling live jobs.
- Keep Recyclarr disabled; do not reintroduce it unless the policy-management
  direction explicitly changes.
- Evaluate linked Profilarr databases with
  `ansible docker-vm -m script -a scripts/media-release/profilarr_candidate_audit.py` before
  syncing any candidate CF/profile into Sonarr or Radarr.
- For curated CF sync, use
  `ansible docker-vm --become -m script -a "scripts/media-release/profilarr_selective_cf_import.py --dry-run"`
  first, then rerun without `--dry-run` only if the CF count remains under the
  limit and the upstream profile scores are not being imported.
- Check scheduler health with
  `ansible docker-vm -m script -a scripts/media-release/profilarr_state_audit.py` after
  Profilarr restarts or coordinator-triggered upgrade runs.

Current deployment notes:

- Profilarr's first admin was created through the setup form endpoint. The
  generated password is not in the repo; it is root-only on `media-vm` at
  `/root/profilarr-admin.initial-password`.
- Profilarr API status is available at `/api/v1/status`; `/api/v1/arr` is
  read-only in the current build. Arr creation and upgrade-filter saves are
  automated through authenticated form endpoints.
- Sonarr and Radarr upgrade filters remain configured but native scheduling is
  disabled. The coordinator queues one controlled cycle per hour when storage
  maintenance is not reserving the night. Sonarr uses one cutoff-unmet
  monitored-series search per run; Radarr uses up to five cutoff-unmet
  monitored-movie searches per run.
- Temporary Profilarr test profiles are removed after the 2026-05-27 promotion;
  recreate them only through the managed staging scripts for the next candidate
  policy.
- Dictionarry and Dumpstarr are linked in Profilarr. Dumpstarr is candidate
  material only for now; its stock `TV 1080p` profile penalizes `x265 (HD)` at
  `-10000`, which conflicts with this library's preferred HD x265/HEVC policy.

## Download Client Release Metadata Stamping

SABnzbd and qBittorrent use managed post-download metadata stamping to preserve
release-title evidence before Sonarr/Radarr import multi-file packs.

- **Playbook**: `playbooks/media/media-release-stamper.yml`
- **qBittorrent**: completion hook calls `/config/scripts/qbit-release-stamper.py`
  with torrent hash/name/category, then renames payload files through
  qBittorrent's Web API so seeding state stays intact. The script retries
  transient Web API failures before giving up and logging a non-fatal stamper
  error, and skips the qBit file-list endpoint for obvious single-file video
  torrents because that endpoint can hang while torrent metadata still works.
- **SABnzbd**: `shows` and `movies` categories run
  `sab-release-stamper.py` from the configured `scripts` folder.
- **DA rule**: language-combo tags such as `[JA+EN]`, `[KO+EN]`, or
  `[JA+KO+EN]` are only stamped per file after the script sees audio-language
  metadata for English plus the configured original language. qBittorrent can
  optionally get the original language from Sonarr/Radarr by torrent
  hash/download ID; SABnzbd can optionally get it by release/job title. If Arr
  lookup fails, both fall back to `jpn`; title text alone is not enough.
- **x265 rule**: `[x265]` is only stamped per file after the script sees HEVC
  markers in that individual payload.
- **Mixed packs**: no bulk labels. Each video file must qualify for each tag.
- **Arr dependency**: Sonarr/Radarr lookup is optional and bounded. If either is
  down, stamping continues with the configured fallback language.
- **Ambiguous episode names**: when Sonarr context is available, TV payload
  files with an episode token but without the canonical series title are
  rewritten to include the canonical series title before tagging so Sonarr can
  map them during import.
- **Env ownership**: stamper env files are mode `0600` and owned by UID/GID
  `1000`, matching the media containers' `PUID`/`PGID`.

## Torrent Fallback (Gluetun + qBittorrent)

Torrents via Nyaa as fallback when Usenet doesn't have a release.

- **VPN**: ProtonVPN WireGuard via Gluetun container (NL P2P servers, `WIREGUARD_MTU=1420` required)
- **qBittorrent**: `network_mode: service:gluetun`, WebUI on port 8085 at `qbit.jnalley.me`
- **Priority**: SABnzbd (1) > qBittorrent (2) - Usenet preferred, torrents fallback
- **Disk I/O**: POSIX-compliant (required for VirtioFS compatibility)
- **Incomplete downloads**: Both SABnzbd and qBittorrent use the dedicated Samsung 860 EVO SSD for temp storage, isolated in separate subdirs (`usenet/` and `torrents/`). The previous Lacie-backed path remains temporarily as rollback at `/srv/nas-01/downloads/media-downloads`.
- **Storage layout**: Media-stack containers on docker-vm use `/srv/media/plex:/data` from the single media NFS mount. Incomplete/temp downloads use the SSD-backed `/incomplete` mount; completed Arr downloads intentionally stay under `/data` (`/data/downloads/complete` for SABnzbd, `/data/downloads/torrents` for qBittorrent) so imports can hardlink when branch placement allows it. See `docs/media-stack-storage-layout.md`.
- **Automatic port sync**: managed by `playbooks/docker/gluetun-watchdog.yml`. The systemd path unit watches Gluetun's port file and updates qBittorrent via API when VPN reconnects. Repaired on docker-vm on 2026-05-22 to accept qBittorrent 5.2.0's HTTP 204 login success response and to clean up stale lockfiles before recreating qBittorrent. Recreates now preflight required media bind paths so stale `/srv/archive` or `/srv/media/plex` state is fixed before Docker is asked to recreate qBittorrent.
- **Known bad server**: ProtonVPN node-nl-215 (103.69.224.3) has broken port forwarding — gluetun-watchdog should detect and force-recreate
- **Tuning**: `max_active_downloads: 5` to reduce I/O contention with uploads; `max_active_uploads: 200`

```bash
# Verify VPN is working
ansible media-vm -m shell -a "docker exec gluetun wget -qO- https://ipinfo.io/json" --become

# Check port sync logs
journalctl -t qbit-port-sync -n 10

# qBittorrent 5.2.0 stale-lockfile symptom: WebUI port resets/refuses after restart.
# Recovery used on 2026-05-22: move aside the stale lockfile and recreate qBittorrent.
if [ -f /opt/media-stack/qbittorrent/qBittorrent/lockfile ]; then
  sudo mv /opt/media-stack/qbittorrent/qBittorrent/lockfile /opt/media-stack/qbittorrent/qBittorrent/lockfile.stale
fi
cd /opt/media-stack && sudo docker compose up -d qbittorrent
sudo systemctl enable --now qbit-port-sync.path
```

## Nextcloud AIO (nextcloud-vm)

Nextcloud All-in-One running on VM 101 (ts440) with VirtioFS storage access.

- **VM Specs**: 8GB RAM, 2 cores, 32GB local disk, Proxmox CPU model `host`
- **VirtioFS Mount**: `/srv/nextcloud` → `/srv/nas-zfs/nextcloud` on ts440
- **Data Directory**: `/srv/nas-zfs/nextcloud/data` (owned by www-data, UID 33)
- **Access**:
  - Admin: `https://100.112.46.126:8080` (Tailscale only)
  - Web: `https://nextcloud.jnalley.me` (via Caddy on docker-vm)
- **Public Access**: Cloudflare Tunnel (no port forwarding, hides home IP)

The `host` CPU model is managed by `playbooks/proxmox/proxmox-vm-hardware.yml` so Nextcloud AIO fulltextsearch sees AVX/AVX2/FMA CPU flags. Hardware changes require a Proxmox-level VM stop/start, not just a guest reboot.

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
| Portainer CE | `portainer.jnalley.me` | Multi-host Docker UI (managed edge agents on media-vm/nextcloud-vm) |
| Seerr | `requests.jnalley.me` | Media requests (Plex OAuth) |
| Cloudflared | - | Cloudflare Tunnel (public access) |
| Apprise API | `apprise.jnalley.me` | Notification router (Pushover + email) |
| FreshRSS | `rss.jnalley.me` | RSS aggregator (Google Reader API for Reeder) |
| Diun | - | Docker image update notifier |
| Grafana | `grafana.jnalley.me` | Loki log dashboards |
| Proxmox UIs | `pve-ts440.jnalley.me`, `pve-alto.jnalley.me`, `pve-herc.jnalley.me`, `pve-m70q.jnalley.me` | Proxmox node web UIs via Caddy |
| Proxmox Backup Server | `pbs.jnalley.me` | PBS web UI via Caddy |
| Proxmox Datacenter Manager | `pdm.jnalley.me` | PDM web UI via Caddy |
| Dispatcharr | `iptv.jnalley.me` | HDHomeRun emulator for Plex Live TV (disabled — free streams unreliable) |
| OpenClaw | `openclaw.jnalley.me` | AI agent gateway; current direct tailnet origin is retained only until loopback + Tailscale Serve cutover |
| Mercury Tailscale peer relay | `mercury-relay.jnalley.me` | DNS-only A record for Mercury UDP 40000 relay endpoint; updated by `cloudflare-ddns.yml` on docker-vm |
| ~~Uptime Kuma~~ | ~~`status.jnalley.me`~~ | Disabled 2026-04-13 (unused); compose preserved at `/opt/uptime-kuma/` |
| ~~Homepage~~ | ~~`home.jnalley.me`~~ | Disabled 2026-04-13 (unused); compose preserved at `/opt/homepage/` |
| ~~Gitea~~ | ~~`git.jnalley.me`~~ | Disabled 2026-04-13 (unused); compose preserved at `/opt/gitea/` |

Stacks support `start: true/false` in `docker.yml` to control service state.

Caddy is now Ansible-managed. Edit `templates/docker/Caddyfile.j2` for routes, `templates/docker/caddy.yml` for compose, and `templates/docker/caddy.Dockerfile` for the Cloudflare DNS build. Apply with `ansible-playbook playbooks/docker/docker-stacks.yml --tags caddy`. The live files under `/opt/caddy/` are generated except `.env`, which stays live because it contains the Cloudflare API token. Emergency live edits should be backported to the templates or they will be overwritten.

## Cloudflare DDNS

`playbooks/network/cloudflare-ddns.yml` deploys DNS-only Cloudflare updater
timers on `cloudflare_ddns_hosts`. docker-vm owns
`mercury-relay.jnalley.me`, the public endpoint name for Mercury's Tailscale
peer relay on UDP 40000. The updater requires a dedicated token in
`/etc/default/cloudflare-ddns-mercury-relay` or
`vault_cloudflare_ddns_mercury_relay_api_token`; it does not reuse
`/opt/caddy/.env`.

Tailscale peer-relay static endpoints require literal `IP:port` values, not
hostnames. `playbooks/network/tailscale-peer-relay-endpoint.yml` runs on
Mercury to keep `RelayServerStaticEndpoints` synced to the current WAN IP on
UDP 40000.

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
ansible-playbook playbooks/proxmox/proxmox-firewall.yml

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

**VirtioFS ACL Limitation**: VirtioFS does **not** pass through POSIX ACLs to guest VMs. Files accessed via VirtioFS must have adequate base permissions (`chmod`) — ACLs set via `setfacl` on the host are invisible to guests. ZFS ACLs are managed by `playbooks/storage/zfs.yml`; normal runs set dataset-root ACLs and default ACLs for new files. Existing-tree recursive ACL repair is intentionally opt-in with `zfs_acl_recursive_repair: true` because it can walk large datasets.

**ts440 memory policy**: verify current guest allocations from live Proxmox
configuration before capacity work; the old static budget included the retired
`openclaw-vm` and is no longer authoritative. ZFS ARC remains managed through
`/etc/modprobe.d/zfs.conf`, and Proxmox nodes use `vm.swappiness=10` to avoid
swapping QEMU guest RAM too eagerly. Ballooning remains disabled on `media-vm`
because of GPU passthrough; VM memory changes require a Proxmox-level restart.

## Ansible Environment

Ansible runs flat on jn-t14s-lin (ThinkPad T14s, Kubuntu/Ubuntu 26.04) with Ubuntu's packaged `ansible-core` 2.20+. The repo clone is at `~/cc-ansible` on jn-t14s-lin.

ts440 auto-pulls from GitHub every 5 minutes (`git-sync.timer`) to keep the Nextcloud External Storage copy current. nextcloud-vm runs `occ files:scan` every 10 minutes (`nextcloud-scan.timer`) so external storage changes appear automatically. Codex CLI's project memory is synced from jn-t14s-lin to ts440 every 10 minutes (`codex-memory-sync.timer`) for active Nextcloud access; Claude Code's memory archive continues syncing via `claude-memory-sync.timer` as a dated fallback.

## Tips

- Use `--check` for dry runs
- Use `--diff` to see file changes
- Use `-v` through `-vvvv` for verbosity
- Tags: `ansible-playbook playbooks/core/packages.yml --tags fastfetch`
- Run site.yml for full configuration: `ansible-playbook site.yml`

## FreePBX (freepbx-vm, VM 130 on pve-herc)

FreePBX 17 / Asterisk 22 PBX server on Debian 12. VoIP.ms SIP trunk with Yealink T54W desk phone. Web GUI: `http://100.97.139.95/admin`. LAN IP: `192.168.1.241`, managed in `/etc/network/interfaces` by `playbooks/apps/freepbx.yml`. APT pinned to bookworm (`apt_pin_release: bookworm` in host_vars). Sangoma Smart Firewall enabled with Tailscale trusted. Proxmox firewall: SIP, RTP, SSH, web GUI (Tailscale only).

## HomeKit / Home Assistant

- **homebridge-lxc** (CT 102): Bridges Govee devices to HomeKit. Firewall needs TCP 51000-56000 (HAP) + UDP 5353 (mDNS). `playbooks/apps/homebridge.yml` owns Homebridge-specific guardrails, including nftables compatibility with Tailscale interface creation during boot.
- **haos-vm** (VM 120): Home Assistant OS. Some devices chain: Homebridge → HA → HomeKit. Firewall needs TCP 21000-21100 (HAP) + UDP 5353.
- **HA Companion App**: Set both Internal and External URL to `http://homeassistant.hinny-liberty.ts.net:8123`

## rclone Sync (OneDrive to Nextcloud)

Scheduled sync from school OneDrive to Nextcloud via `rclone-sync.yml` on macbook-pro. The OneDrive desktop app syncs files locally, then rclone copies the local folder to Nextcloud via WebDAV (no OneDrive OAuth needed — UTD tenant blocks third-party apps).

- **Schedule**: Every 2 hours (launchd LaunchAgent, runs when logged in)
- **Mode**: `rclone sync` (deletes propagate, safe due to ZFS snapshots + restic)
- **Config**: `host_vars/macbook-pro/rclone-sync.yml`
- **rclone remote**: Only `nextcloud` WebDAV remote needed (configured manually via `rclone config`)
- **Excludes**: OneDrive File Provider pseudo-directories such as root `.Trash` are excluded with `rclone_sync_excludes`
- **Monitoring**: Uptime Kuma push monitor

```bash
# Deploy
ansible-playbook playbooks/backup-sync/rclone-sync.yml

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
Seerr (requests) ──────────────┘

Sonarr/Radarr ──→ Discord (native connection, rich embeds with poster art)
```

- **Apprise API**: Notification router at `/opt/notifications/` on docker-vm. Config uses `pover://` URLs for Pushover
- **Two Pushover apps**: "Computer Corner" (normal + quiet priority) and "cc-media-feed" (priority -2, silent/in-app only)
- **Five Apprise tags**: `push` (infrastructure → Computer Corner app, Time Sensitive), `push-quiet` (automated recovery → Computer Corner app, silent), `email` (iCloud SMTP), `media-feed` (Sonarr/Radarr → cc-media-feed app), and `media-requests` (Seerr → cc-media-feed app). The retired `dbc` destination must not be restored.
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
- **Config**: `group_vars/all/loki.yml`, `templates/logging/alloy-config.alloy.j2`
- **Playbook**: `ansible-playbook playbooks/core/logging.yml`

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

- **Web UI**: `https://pbs.jnalley.me` or `https://100.110.176.37:8007` (login as `root@pam`)
- **Datastore**: `main` at `/srv/pbs-data` (~900GB usable)
- **Storage name**: `pbs-main` (registered on all 4 Proxmox nodes)
- **Backup schedule**: Every 6 hours, all guests except `100,103,104,105,142` (Ansible-managed via Play 3)
- **Prune job**: Daily — 6 hourly, 3 daily, 2 weekly, 1 monthly
- **Garbage collection**: Daily (frees space from pruned snapshots — **required**, prune alone doesn't free disk)
- **Capacity split**: The shared ext4 volume uses `prjquota`; PBS chunks are capped at 520 GiB and Time Machine is capped at 350G via Samba and macOS `tmutil setquota`, leaving filesystem headroom on the 1TB disk.
- **API auth**: Token `backup@pbs!ansible` (secret in vault)
- **Connectivity check**: Runs at `:59` on all nodes (Play 4), logs to `pbs-check` tag in Loki
- **Config**: `host_vars/pbs-lxc/vars.yml`, `host_vars/pbs-lxc/vault.yml`

```bash
# Deploy/update PBS
ansible-playbook playbooks/proxmox/proxmox-backup-server.yml

# Check datastore status
ansible pbs-lxc -m shell -a "proxmox-backup-manager datastore list" --become

# Check prune jobs
ansible pbs-lxc -m shell -a "proxmox-backup-manager prune-job list" --become

# Verify storage on PVE nodes
ansible proxmox_nodes -m shell -a "pvesm status | grep pbs" --become
```

**Backup jobs** are Ansible-managed (Play 3 of `proxmox-backup-server.yml`). Config in `group_vars/proxmox_nodes/vars.yml` (`pbs_backup_schedule`, `pbs_backup_exclude`).

### Proxmox Notification Webhooks

PVE notifications route to Apprise → Pushover via webhook. Deployed by `playbooks/proxmox/proxmox-notifications.yml`.

- **Warnings/errors** (failed backups, fencing): `push` tag → Time Sensitive
- **Info** (package-updates, replication, fencing): `push-quiet` tag → silent
- **Backup success**: suppressed (vzdump info events filtered out to reduce noise)
- Built-in `default-matcher` (mail-to-root) is disabled

```bash
# Deploy/update notification webhooks
ansible-playbook playbooks/proxmox/proxmox-notifications.yml
```

## Hermes Replacement (staged)

The isolated Hermes replacement is declaratively implemented but has no
selected host. `hermes_hosts` is intentionally empty because `pve-alto`,
`ts440`, and `pve-herc` failed the capacity/role gate while `pve-m70q` was
unreachable. The playbook defaults to `disabled`, installs no runtime during
normal convergence, starts no listener, contains no production token, and is
not imported by `site.yml`.

- **Playbook**: `playbooks/agents/hermes-shadow.yml`
- **Architecture and gates**: `docs/hermes-replacement.md`
- **Discord handoff**: three credential-free profile declarations, silent
  unknown DMs, fail-closed allowlists, no replay/backfill, and an attended
  stopped-source-before-target cutover/rollback contract
- **Automation handoff**: all 28 current cron jobs plus three heartbeats are
  classified into agent-backed local proposals, external systemd owners, or
  deterministic no-agent jobs; Health remains external and Siri remains absent
- **Validation**: `ansible-playbook playbooks/agents/hermes-shadow.yml --syntax-check`
- **Do not run bootstrap** until a new VM placement passes and the official
  installer hash, immutable release tag/commit, and attended approvals are
  supplied.

## OpenClaw (jn-t14s-lin)

OpenClaw AI agent platform — personal homelab admin assistant via web UI and Discord. The current Gateway still runs as `johnny` and therefore inherits that account's sudo, Docker, controller credentials, and repository access; the dedicated least-privilege runtime migration remains pending.

- **Web UI**: `https://openclaw.jnalley.me` (Tailscale only)
- **Gateway**: Current production uses port 18789 on the tailnet with token auth
  and `docker-vm` as its only trusted proxy. The migration target preserves
  `openclaw.jnalley.me` while moving the Gateway to loopback behind a root-owned
  named Tailscale Serve service; the OpenClaw account receives no Tailscale
  operator authority.
- **Host**: `jn-t14s-lin` (current OpenClaw controller/runtime)
- **Service**: User-level systemd via `openclaw gateway install` (NOT a custom system service)
- **Config**: `~/.openclaw/openclaw.json` + `.env` — manual, backed up by restic
- **Timers**: repo-sync (5 min), update-check (daily 08:00 → Apprise)
- **Playbook**: `ansible-playbook playbooks/agents/openclaw.yml` (opt-in via `openclaw_enabled`)
- **Isolation canary**: A hardened `openclaw` system service and modernized
  release pipeline are implemented but disabled by default. A credential-less
  ephemeral account resolves stable core and reviewed plugin versions with
  lifecycle scripts disabled; root atomically promotes immutable core, while
  OpenClaw's native installer creates integrity-bearing plugin ownership rows
  before root freezes plugin code read-only. The attended canary uses loopback
  port 19789, has no channels, and does not stop or modify production. Verify
  its current unit/listener state before relying on it; the final corrected
  native-plugin bootstrap replay is still pending.
- **State modernization rehearsals**: The promoted generation contains active
  file-backed history plus only policy-classified retained workspace data and
  the root-owned modern behavior overlay; cached legacy bootstrap snapshots are
  discarded for native rebuilding. Active copied delivery-recovery fields are explicitly
  quarantined and counted so a canary cannot replay a production reply; the
  untouched source indexes remain rollback evidence, and final cutover must
  reconcile pending delivery rather than discard it. A separate
  disabled-by-default Doctor rehearsal
  takes online SQLite backups, scrubs copied provider auth, retires eight
  legacy plugin install records through the supported CLI, rebuilds four
  retained plugins with integrity-bearing npm provenance in an isolated
  credential-free builder, freezes their code root-owned/read-only, and
  requires clean warning gates plus a second idempotent Doctor pass before
  promotion. Neither rehearsal modifies or authenticates production. A third
  attended handoff can transactionally place those verified file-backed
  sessions and a freshly policy-staged workspace into the silent five-agent
  loopback canary, then use native `sessions.list`/`sessions.patch` in plan or
  apply mode. It backs up and restores only canary data and never controls the
  production Gateway.
- **Behavior modernization**: The compact repo-owned Astra/Fleet bootstrap is
  under `files/openclaw/workspace/` and is guarded by
  `scripts/agents/openclaw-bootstrap-audit.py`. It replaces generic worker
  prompts, the hardcoded cognitive-stack hook, hardcoded session routes,
  transcript polling, and text-token heartbeat suppression. It is not deployed
  to production until the attended dedicated-user cutover. A separate
  disabled-by-default behavior rehearsal is designed to prove concise Dubble
  output, native Vega-to-Antares review lineage, and a structured idle-silent
  Rigel heartbeat in the channel-less canary. The applied silent-canary data
  handoff is complete; behavior execution remains pending fresh isolated
  executor authentication. The rehearsal restores the heartbeat-disabled
  baseline and archives only its synthetic sessions.
- **Mem0 memory**: `@mem0/openclaw-mem0` plugin with Qdrant (localhost:6333), Gemini embeddings, and the configured OpenAI-compatible LLM for fact extraction. Auto-capture + auto-recall across sessions.
- **dbc ops access**: Narrow host-specific wrappers, including candidate-scoped Immich Media Inbox access on docker-vm. Its isolated vision workers may read pixels/OCR only for admitted candidates; there is no arbitrary Immich, credential, SQLite, or general Docker access. Existing media-stack/Caddy operational paths remain separately scoped.
- **Docker reporting**: A strict result-only reporter is implemented but remains disabled until the dedicated runtime identity and key are deployed. See `docs/openclaw-docker-access.md`.
- **Docker updates**: A separate target-allowlisted, digest-bound broker is implemented but remains disabled. Astra can propose or execute an independently approved one-use plan; it cannot approve plans, choose paths/commands, or access Docker directly. See `docs/openclaw-docker-access.md`.
- **Health isolation**: The dedicated receiver and aggregate report boundary are implemented but disabled pending an approved canary/cutover. See `docs/openclaw-runtime-security.md`.

```bash
# Check gateway status (on the current OpenClaw host)
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
