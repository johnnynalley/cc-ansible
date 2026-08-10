# Playbook Catalog

This directory contains domain-owned Ansible playbooks. `site.yml` remains
the full convergence entrypoint, but one-off runs should use the domain path
shown here.

## Operating Rules

- Do not add new playbooks directly under `playbooks/`.
- Put new playbooks in the domain directory that owns the behavior.
- Add or update the lightweight metadata header at the top of each playbook.
- Update this catalog, the domain README, `site.yml` when applicable, and
  any operator docs or helper scripts that reference the playbook path.
- Validate with `ansible-playbook <playbook> --syntax-check`; use
  `--check --diff` for infrastructure-impacting changes when the playbook
  supports a meaningful dry run.

## Domains

- `core/`: Base OS and controller hygiene.
- `network/`: Network recovery, adapter tuning, and DNS endpoint automation.
- `storage/`: NAS, mounts, shares, ZFS, MergerFS, VirtioFS.
- `docker/`: Docker Compose stacks and container maintenance.
- `media/`: Plex, streaming, media maintenance, release-policy automation.
- `backup-sync/`: Backups, sync jobs, and Nextcloud external-storage refresh.
- `agents/`: Codex, Claude archive sync, and OpenClaw services.
- `proxmox/`: Proxmox cluster, firewall, PBS, PDM, and VM hardware.
- `windows/`: Windows gaming workstation automation.
- `apps/`: Standalone application appliances.

## Playbooks

### core

Owner area: Base OS and controller hygiene.

| Playbook | Hosts | Purpose | Main vars/sources | Safe validation |
| --- | --- | --- | --- | --- |
| `playbooks/core/swap.yml` | `linux_hosts` | Configure swap files. | packages_*, bootstrap_*, auto_updates_*, unattended_upgrades_*, swap_*, sysctl_*, logging_*, smartd_*, apcupsd_*; templates/auto-updates, templates/logging, templates/motd, templates/smartmontools, templates/ups; scripts/repo/repo-audit for repo checks; otherwise none by default. | `ansible-playbook playbooks/core/swap.yml --syntax-check` |
| `playbooks/core/sysctl.yml` | `proxmox_nodes, linux_hosts` | Configure kernel sysctl settings. | packages_*, bootstrap_*, auto_updates_*, unattended_upgrades_*, swap_*, sysctl_*, logging_*, smartd_*, apcupsd_*; templates/auto-updates, templates/logging, templates/motd, templates/smartmontools, templates/ups; scripts/repo/repo-audit for repo checks; otherwise none by default. | `ansible-playbook playbooks/core/sysctl.yml --syntax-check` |
| `playbooks/core/user-separation.yml` | `linux_hosts, orchestrator, media-vm, docker-vm` | Configure separated automation and operational users. | packages_*, bootstrap_*, auto_updates_*, unattended_upgrades_*, swap_*, sysctl_*, logging_*, smartd_*, apcupsd_*; templates/auto-updates, templates/logging, templates/motd, templates/smartmontools, templates/ups; scripts/repo/repo-audit for repo checks; otherwise none by default. | `ansible-playbook playbooks/core/user-separation.yml --syntax-check` |
| `playbooks/core/packages.yml` | `localhost, linux_hosts, macos_hosts` | Install baseline packages. | packages_*, bootstrap_*, auto_updates_*, unattended_upgrades_*, swap_*, sysctl_*, logging_*, smartd_*, apcupsd_*; templates/auto-updates, templates/logging, templates/motd, templates/smartmontools, templates/ups; scripts/repo/repo-audit for repo checks; otherwise none by default. | `ansible-playbook playbooks/core/packages.yml --syntax-check` |
| `playbooks/core/smartmontools.yml` | `linux_hosts` | Configure SMART disk monitoring. | packages_*, bootstrap_*, auto_updates_*, unattended_upgrades_*, swap_*, sysctl_*, logging_*, smartd_*, apcupsd_*; templates/auto-updates, templates/logging, templates/motd, templates/smartmontools, templates/ups; scripts/repo/repo-audit for repo checks; otherwise none by default. | `ansible-playbook playbooks/core/smartmontools.yml --syntax-check` |
| `playbooks/core/apcupsd.yml` | `proxmox_nodes` | Configure apcupsd UPS monitoring. | packages_*, bootstrap_*, auto_updates_*, unattended_upgrades_*, swap_*, sysctl_*, logging_*, smartd_*, apcupsd_*; templates/auto-updates, templates/logging, templates/motd, templates/smartmontools, templates/ups; scripts/repo/repo-audit for repo checks; otherwise none by default. | `ansible-playbook playbooks/core/apcupsd.yml --syntax-check` |
| `playbooks/core/ssh-hardening.yml` | `linux_hosts` | Configure SSH hardening. | packages_*, bootstrap_*, auto_updates_*, unattended_upgrades_*, swap_*, sysctl_*, logging_*, smartd_*, apcupsd_*; templates/auto-updates, templates/logging, templates/motd, templates/smartmontools, templates/ups; scripts/repo/repo-audit for repo checks; otherwise none by default. | `ansible-playbook playbooks/core/ssh-hardening.yml --syntax-check` |
| `playbooks/core/auto-updates.yml` | `linux_hosts` | Configure automatic updates. | packages_*, bootstrap_*, auto_updates_*, unattended_upgrades_*, swap_*, sysctl_*, logging_*, smartd_*, apcupsd_*; templates/auto-updates, templates/logging, templates/motd, templates/smartmontools, templates/ups; scripts/repo/repo-audit for repo checks; otherwise none by default. | `ansible-playbook playbooks/core/auto-updates.yml --syntax-check` |
| `playbooks/core/unattended-upgrades.yml` | `debian_hosts` | Configure unattended-upgrades (security patches). | packages_*, bootstrap_*, auto_updates_*, unattended_upgrades_*, swap_*, sysctl_*, logging_*, smartd_*, apcupsd_*; templates/auto-updates, templates/logging, templates/motd, templates/smartmontools, templates/ups; scripts/repo/repo-audit for repo checks; otherwise none by default. | `ansible-playbook playbooks/core/unattended-upgrades.yml --syntax-check` |
| `playbooks/core/power-management.yml` | `linux_hosts` | Configure power management. | packages_*, bootstrap_*, auto_updates_*, unattended_upgrades_*, swap_*, sysctl_*, logging_*, smartd_*, apcupsd_*; templates/auto-updates, templates/logging, templates/motd, templates/smartmontools, templates/ups; scripts/repo/repo-audit for repo checks; otherwise none by default. | `ansible-playbook playbooks/core/power-management.yml --syntax-check` |
| `playbooks/core/logging.yml` | `linux_hosts, macos_hosts` | Configure centralized logging (Loki + Alloy). | packages_*, bootstrap_*, auto_updates_*, unattended_upgrades_*, swap_*, sysctl_*, logging_*, smartd_*, apcupsd_*; templates/auto-updates, templates/logging, templates/motd, templates/smartmontools, templates/ups; scripts/repo/repo-audit for repo checks; otherwise none by default. | `ansible-playbook playbooks/core/logging.yml --syntax-check` |
| `playbooks/core/bootstrap.yml` | `bootstrap_hosts` | Bootstrap new managed hosts. | packages_*, bootstrap_*, auto_updates_*, unattended_upgrades_*, swap_*, sysctl_*, logging_*, smartd_*, apcupsd_*; templates/auto-updates, templates/logging, templates/motd, templates/smartmontools, templates/ups; scripts/repo/repo-audit for repo checks; otherwise none by default. | `ansible-playbook playbooks/core/bootstrap.yml --syntax-check` |

### network

Owner area: Network recovery, adapter tuning, and DNS endpoint automation.

| Playbook | Hosts | Purpose | Main vars/sources | Safe validation |
| --- | --- | --- | --- | --- |
| `playbooks/network/cloudflare-ddns.yml` | `cloudflare_ddns_hosts` | Configure DNS-only Cloudflare DDNS updater timers. | cloudflare_ddns_*; templates/network/cloudflare-ddns-update.sh.j2. | `ansible-playbook playbooks/network/cloudflare-ddns.yml --syntax-check` |
| `playbooks/network/e1000e-tuning.yml` | `proxmox_nodes` | Tune e1000e NICs (disable EEE/TSO). | e1000e_*; templates/network. | `ansible-playbook playbooks/network/e1000e-tuning.yml --syntax-check` |
| `playbooks/network/network-recovery.yml` | `linux_hosts:!workstations` | Configure network recovery. | network_recovery_*, netplan_*; templates/network. | `ansible-playbook playbooks/network/network-recovery.yml --syntax-check` |
| `playbooks/network/tailscale-peer-relay-endpoint.yml` | `tailscale_peer_relay_endpoint_hosts` | Keep peer-relay static endpoints synced to current WAN IPs. | tailscale_peer_relay_endpoint_*, tailscale_peer_relay_*; templates/network/tailscale-peer-relay-endpoint-sync.sh.j2. | `ansible-playbook playbooks/network/tailscale-peer-relay-endpoint.yml --syntax-check` |
| `playbooks/network/wifi.yml` | `linux_hosts` | Configure WiFi power management. | wifi_*; templates/network. | `ansible-playbook playbooks/network/wifi.yml --syntax-check` |

### storage

Owner area: NAS, mounts, shares, ZFS, MergerFS, VirtioFS.

| Playbook | Hosts | Purpose | Main vars/sources | Safe validation |
| --- | --- | --- | --- | --- |
| `playbooks/storage/nfs.yml` | `nas_server, linux_hosts` | Configure NFS server and clients. | smb_shares, nfs_*, filesystem_mounts, mergerfs_*, zfs_*, virtiofs_*, vm_storage_gate_*; templates/storage, templates/samba, templates/proxmox; scripts/storage. | `ansible-playbook playbooks/storage/nfs.yml --syntax-check` |
| `playbooks/storage/filesystem-mounts.yml` | `linux_hosts` | Configure filesystem mounts and USB storage quirks. | smb_shares, nfs_*, filesystem_mounts, usb_storage_quirks, mergerfs_*, zfs_*, virtiofs_*, vm_storage_gate_*; templates/storage, templates/samba, templates/proxmox; scripts/storage. | `ansible-playbook playbooks/storage/filesystem-mounts.yml --syntax-check` |
| `playbooks/storage/samba.yml` | `samba_hosts` | Configure Samba server. | smb_shares, nfs_*, filesystem_mounts, mergerfs_*, zfs_*, virtiofs_*, vm_storage_gate_*; templates/storage, templates/samba, templates/proxmox; scripts/storage. | `ansible-playbook playbooks/storage/samba.yml --syntax-check` |
| `playbooks/storage/time-machine.yml` | `macos_hosts` | Configure macOS Time Machine destination quotas. | time_machine_destinations; none by default. | `ansible-playbook playbooks/storage/time-machine.yml --syntax-check` |
| `playbooks/storage/mergerfs.yml` | `nas_server, gluetun_hosts:media-vm` | Configure MergerFS media pool. | smb_shares, nfs_*, filesystem_mounts, mergerfs_*, zfs_*, virtiofs_*, vm_storage_gate_*; templates/storage, templates/samba, templates/proxmox; scripts/storage. | `ansible-playbook playbooks/storage/mergerfs.yml --syntax-check` |
| `playbooks/storage/mergerfs-recovery.yml` | `nas_server` | Configure MergerFS branch recovery (udev + watchdog + media-app refresh). | smb_shares, nfs_*, filesystem_mounts, mergerfs_*, zfs_*, virtiofs_*, vm_storage_gate_*; templates/storage, templates/samba, templates/proxmox; scripts/storage. | `ansible-playbook playbooks/storage/mergerfs-recovery.yml --syntax-check` |
| `playbooks/storage/zfs.yml` | `nas_server` | Configure ZFS (snapshots, scrub, tuning, properties, ACLs). | smb_shares, nfs_*, filesystem_mounts, mergerfs_*, zfs_*, virtiofs_*, vm_storage_gate_*; templates/storage, templates/samba, templates/proxmox; scripts/storage. | `ansible-playbook playbooks/storage/zfs.yml --syntax-check` |
| `playbooks/storage/virtiofs.yml` | `proxmox_nodes, vms` | Configure VirtioFS shares. | smb_shares, nfs_*, filesystem_mounts, mergerfs_*, zfs_*, virtiofs_*, vm_storage_gate_*; templates/storage, templates/samba, templates/proxmox; scripts/storage. | `ansible-playbook playbooks/storage/virtiofs.yml --syntax-check` |
| `playbooks/storage/storage-status.yml` | `linux_hosts` | Deploy storage-status utility. | smb_shares, nfs_*, filesystem_mounts, mergerfs_*, zfs_*, virtiofs_*, vm_storage_gate_*; templates/storage, templates/samba, templates/proxmox; scripts/storage. | `ansible-playbook playbooks/storage/storage-status.yml --syntax-check` |
| `playbooks/storage/vm-storage-gate.yml` | `proxmox_nodes` | Deploy per-VM storage gate hookscript. | smb_shares, nfs_*, filesystem_mounts, mergerfs_*, zfs_*, virtiofs_*, vm_storage_gate_*; templates/storage, templates/samba, templates/proxmox; scripts/storage. | `ansible-playbook playbooks/storage/vm-storage-gate.yml --syntax-check` |

### docker

Owner area: Docker Compose stacks and container maintenance.

| Playbook | Hosts | Purpose | Main vars/sources | Safe validation |
| --- | --- | --- | --- | --- |
| `playbooks/docker/docker-stacks.yml` | `docker_hosts` | Deploy Docker Compose stacks. | docker_stacks, docker_daemon_config, docker_auto_update_*, gluetun_*, qbit_*; templates/docker, templates/gluetun; scripts/docker. | `ansible-playbook playbooks/docker/docker-stacks.yml --syntax-check` |
| `playbooks/docker/gluetun-watchdog.yml` | `gluetun_hosts:media-vm` | Configure Gluetun VPN watchdog. | docker_stacks, docker_auto_update_*, gluetun_*, qbit_*; templates/docker, templates/gluetun; scripts/docker. | `ansible-playbook playbooks/docker/gluetun-watchdog.yml --syntax-check` |
| `playbooks/docker/docker-auto-update.yml` | `docker_hosts` | Configure Docker container auto-updates. | docker_stacks, docker_daemon_config, docker_auto_update_*, gluetun_*, qbit_*; templates/docker, templates/gluetun; scripts/docker. | `ansible-playbook playbooks/docker/docker-auto-update.yml --syntax-check` |
| `playbooks/docker/openclaw-docker-report.yml` | `docker_hosts` | Publish a strict redacted Docker inventory through a forced-command account; disabled by default. | openclaw_docker_report_*; scripts/docker/openclaw-docker-report*. | `ansible-playbook playbooks/docker/openclaw-docker-report.yml --syntax-check` |
| `playbooks/docker/openclaw-docker-update-broker.yml` | `docker_hosts` | Install a strict, separately approved, digest-bound service update broker; disabled by default. | openclaw_docker_update_broker_*; templates/docker/openclaw-docker-update-manifest.json.j2; scripts/docker/openclaw-docker-update-broker.py. | `ansible-playbook playbooks/docker/openclaw-docker-update-broker.yml --syntax-check` |

### media

Owner area: Plex, streaming, media maintenance, release-policy automation.

| Playbook | Hosts | Purpose | Main vars/sources | Safe validation |
| --- | --- | --- | --- | --- |
| `playbooks/media/immich-media-inbox.yml` | `docker_hosts` (opt-in) | Deploy Astra's headless Immich screenshot semantic-analysis queue. | immich_media_inbox_*; templates/media-inbox; scripts/media-inbox. | `ansible-playbook playbooks/media/immich-media-inbox.yml --syntax-check` |
| `playbooks/media/plex-appliance.yml` | `plex_appliances` | Configure Plex appliance. | nightly_media_*, media_release_stamper_*, media_stack_health_*, stream_relay_*, plex_appliance_*; templates/media-maintenance, templates/streaming, templates/plex-appliance, templates/docker; scripts/media-maintenance, scripts/media-release, scripts/streaming. | `ansible-playbook playbooks/media/plex-appliance.yml --syntax-check` |
| `playbooks/media/nightly-media-maintenance.yml` | `nas_server, media-vm:docker-vm` | Configure nightly media maintenance. | nightly_media_*, media_release_stamper_*, media_stack_health_*, stream_relay_*, plex_appliance_*; templates/media-maintenance, templates/streaming, templates/plex-appliance, templates/docker; scripts/media-maintenance, scripts/media-release, scripts/streaming. | `ansible-playbook playbooks/media/nightly-media-maintenance.yml --syntax-check` |
| `playbooks/media/media-release-stamper.yml` | `gluetun_hosts` | Configure media release metadata stamping. | nightly_media_*, media_release_stamper_*, media_stack_health_*, stream_relay_*, plex_appliance_*; templates/media-maintenance, templates/streaming, templates/plex-appliance, templates/docker; scripts/media-maintenance, scripts/media-release, scripts/streaming. | `ansible-playbook playbooks/media/media-release-stamper.yml --syntax-check` |
| `playbooks/media/sonarr-transaction-monitor.yml` | `gluetun_hosts:media-vm` | Configure Sonarr transaction monitor. | nightly_media_*, media_release_stamper_*, media_stack_health_*, stream_relay_*, plex_appliance_*; templates/media-maintenance, templates/streaming, templates/plex-appliance, templates/docker; scripts/media-maintenance, scripts/media-release, scripts/streaming. | `ansible-playbook playbooks/media/sonarr-transaction-monitor.yml --syntax-check` |
| `playbooks/media/media-stack-health.yml` | `docker-vm` | Configure media health monitoring and classified NFS/container-bind recovery. | nightly_media_*, media_release_stamper_*, media_stack_health_*, stream_relay_*, plex_appliance_*; templates/media-maintenance, templates/streaming, templates/plex-appliance, templates/docker; scripts/media-maintenance, scripts/media-release, scripts/streaming. | `ansible-playbook playbooks/media/media-stack-health.yml --syntax-check` |
| `playbooks/media/plex-server-health.yml` | `media-vm, nas_server` | Configure Plex server, VirtioFS, and scrub-window health monitor. | nightly_media_*, media_release_stamper_*, media_stack_health_*, plex_server_health_*, stream_relay_*, plex_appliance_*; templates/media-maintenance, templates/streaming, templates/plex-appliance, templates/docker; scripts/media-maintenance, scripts/media-release, scripts/streaming. | `ansible-playbook playbooks/media/plex-server-health.yml --syntax-check` |
| `playbooks/media/stream-relay.yml` | `media-vm` | Configure stream relay. | nightly_media_*, media_release_stamper_*, media_stack_health_*, stream_relay_*, plex_appliance_*; templates/media-maintenance, templates/streaming, templates/plex-appliance, templates/docker; scripts/media-maintenance, scripts/media-release, scripts/streaming. | `ansible-playbook playbooks/media/stream-relay.yml --syntax-check` |

### backup-sync

Owner area: Backups, sync jobs, and Nextcloud external-storage refresh.

| Playbook | Hosts | Purpose | Main vars/sources | Safe validation |
| --- | --- | --- | --- | --- |
| `playbooks/backup-sync/restic.yml` | `backup_clients:!macos_hosts` | Configure restic backups (B2 offsite). | restic_*, local_restic_*, rclone_sync_*, git_sync_*, nextcloud_scan_*; templates/storage, templates/docker when sync jobs consume generated configs; none by default. | `ansible-playbook playbooks/backup-sync/restic.yml --syntax-check` |
| `playbooks/backup-sync/local-restic.yml` | `backup_clients:!macos_hosts, ts440` | Configure local restic backups with bounded transient target-outage retries. | restic_*, local_restic_*, rclone_sync_*, git_sync_*, nextcloud_scan_*; templates/storage, templates/docker when sync jobs consume generated configs; none by default. | `ansible-playbook playbooks/backup-sync/local-restic.yml --syntax-check` |
| `playbooks/backup-sync/rclone-sync.yml` | `managed_hosts` | Configure rclone sync jobs. | restic_*, local_restic_*, rclone_sync_*, git_sync_*, nextcloud_scan_*; templates/storage, templates/docker when sync jobs consume generated configs; none by default. | `ansible-playbook playbooks/backup-sync/rclone-sync.yml --syntax-check` |
| `playbooks/backup-sync/git-sync.yml` | `nas_server` | Configure git-sync timer (ts440). | restic_*, local_restic_*, rclone_sync_*, git_sync_*, nextcloud_scan_*; templates/storage, templates/docker when sync jobs consume generated configs; none by default. | `ansible-playbook playbooks/backup-sync/git-sync.yml --syntax-check` |
| `playbooks/backup-sync/nextcloud-scan.yml` | `nextcloud-vm` | Configure Nextcloud external storage scan. | restic_*, local_restic_*, rclone_sync_*, git_sync_*, nextcloud_scan_*; templates/storage, templates/docker when sync jobs consume generated configs; none by default. | `ansible-playbook playbooks/backup-sync/nextcloud-scan.yml --syntax-check` |

### agents

Owner area: Codex, Claude archive sync, and OpenClaw services.

| Playbook | Hosts | Purpose | Main vars/sources | Safe validation |
| --- | --- | --- | --- | --- |
| `playbooks/agents/codex-cli.yml` | `orchestrator` | Configure Codex CLI. | codex_*, claude_memory_sync_*, openclaw_*; templates/openclaw; none by default. | `ansible-playbook playbooks/agents/codex-cli.yml --syntax-check` |
| `playbooks/agents/openclaw.yml` | `openclaw_hosts` | Deploy OpenClaw AI agent. | codex_*, claude_memory_sync_*, openclaw_*; templates/openclaw; none by default. | `ansible-playbook playbooks/agents/openclaw.yml --syntax-check` |
| `playbooks/agents/openclaw-health-receiver.yml` | `openclaw_hosts` | Isolate Health ingestion and publish aggregate-only reports; disabled by default. | openclaw_health_receiver_*; scripts/agents; none by default. | `ansible-playbook playbooks/agents/openclaw-health-receiver.yml --syntax-check` |
| `playbooks/agents/openclaw-isolated-gateway.yml` | `openclaw_hosts` | Stage a modernized two-phase Gateway canary with immutable versioned core/provider releases, isolated OAuth enrollment, and a required model proof; disabled by default. | openclaw_isolated_gateway_*; templates/openclaw; scripts/agents. | `ansible-playbook playbooks/agents/openclaw-isolated-gateway.yml --syntax-check` |
| `playbooks/agents/openclaw-state-rehearsal.yml` | `openclaw_hosts` | Rehearse verified relocation of active file-backed OpenClaw session stores without copying config, credentials, plugins, channels, or the full legacy workspace; disabled by default. | openclaw_state_rehearsal_*; scripts/agents/openclaw-session-relocate.py. | `ansible-playbook playbooks/agents/openclaw-state-rehearsal.yml --syntax-check` |
| `playbooks/agents/claude-memory-sync.yml` | `nas_server, orchestrator` | Configure Claude memory sync to NAS. | codex_*, claude_memory_sync_*, openclaw_*; templates/openclaw; none by default. | `ansible-playbook playbooks/agents/claude-memory-sync.yml --syntax-check` |
| `playbooks/agents/codex-memory-sync.yml` | `nas_server, orchestrator` | Configure Codex memory sync to NAS. | codex_*, claude_memory_sync_*, openclaw_*; templates/openclaw; none by default. | `ansible-playbook playbooks/agents/codex-memory-sync.yml --syntax-check` |

### proxmox

Owner area: Proxmox cluster, firewall, PBS, PDM, and VM hardware.

| Playbook | Hosts | Purpose | Main vars/sources | Safe validation |
| --- | --- | --- | --- | --- |
| `playbooks/proxmox/proxmox-vm-hardware.yml` | `proxmox_nodes, linux_hosts` | Configure Proxmox guest hardware settings. | proxmox_*, pve_*, pbs_*, pdm_*; templates/proxmox; none by default. | `ansible-playbook playbooks/proxmox/proxmox-vm-hardware.yml --syntax-check` |
| `playbooks/proxmox/proxmox-boot-order.yml` | `proxmox_nodes` | Configure Proxmox boot ordering guardrails. | proxmox_*, pve_*; none by default. | `ansible-playbook playbooks/proxmox/proxmox-boot-order.yml --syntax-check` |
| `playbooks/proxmox/proxmox-backup-server.yml` | `pbs-lxc, proxmox_nodes` | Configure Proxmox Backup Server. | proxmox_*, pve_*, pbs_*, pdm_*; templates/proxmox; none by default. | `ansible-playbook playbooks/proxmox/proxmox-backup-server.yml --syntax-check` |
| `playbooks/proxmox/proxmox-notifications.yml` | `proxmox_nodes` | Configure Proxmox notification webhooks. | proxmox_*, pve_*, pbs_*, pdm_*; templates/proxmox; none by default. | `ansible-playbook playbooks/proxmox/proxmox-notifications.yml --syntax-check` |
| `playbooks/proxmox/proxmox-firewall.yml` | `proxmox_nodes` | Configure Proxmox firewall. | proxmox_*, pve_*, pbs_*, pdm_*; templates/proxmox; none by default. | `ansible-playbook playbooks/proxmox/proxmox-firewall.yml --syntax-check` |
| `playbooks/proxmox/proxmox-ha.yml` | `proxmox_nodes` | Manage Proxmox HA service state. | proxmox_*, pve_*, pbs_*, pdm_*; templates/proxmox; none by default. | `ansible-playbook playbooks/proxmox/proxmox-ha.yml --syntax-check` |
| `playbooks/proxmox/pdm.yml` | `pdm_servers` | Configure Proxmox Datacenter Manager services. | proxmox_*, pve_*, pbs_*, pdm_*; templates/proxmox; none by default. | `ansible-playbook playbooks/proxmox/pdm.yml --syntax-check` |
| `playbooks/proxmox/proxmox-pdm-vm.yml` | `pve-alto` | Provision the Proxmox Datacenter Manager VM. | proxmox_*, pve_*, pbs_*, pdm_*; templates/proxmox; none by default. | `ansible-playbook playbooks/proxmox/proxmox-pdm-vm.yml --syntax-check` |
| `playbooks/proxmox/proxmox-router-firewall.yml` | `proxmox_nodes` | Configure router firewall rules on Proxmox nodes. | proxmox_*, pve_*, pbs_*, pdm_*; templates/proxmox; none by default. | `ansible-playbook playbooks/proxmox/proxmox-router-firewall.yml --syntax-check` |

### windows

Owner area: Windows gaming workstation automation.

| Playbook | Hosts | Purpose | Main vars/sources | Safe validation |
| --- | --- | --- | --- | --- |
| `playbooks/windows/windows-gaming-tuning.yml` | `localhost, windows_gaming_tuning_targets` | Configure Windows gaming tuning and deploy streaming helpers. | windows_gaming_*, windows_performance_mode_*, windows_signalrgb_*, gaming_benchmark_*, windows_streaming_*; templates/windows; scripts/gaming, scripts/streaming. | `ansible-playbook playbooks/windows/windows-gaming-tuning.yml --syntax-check` |
| `playbooks/windows/windows-performance-mode.yml` | `localhost, windows_performance_mode_targets` | Configure optional/manual Windows Performance Mode scripts and shortcuts; auto watcher can be disabled per host. | windows_gaming_*, windows_performance_mode_*, windows_signalrgb_*, gaming_benchmark_*; templates/windows; scripts/gaming. | `ansible-playbook playbooks/windows/windows-performance-mode.yml --syntax-check` |
| `playbooks/windows/windows-signalrgb.yml` | `localhost, windows_signalrgb_targets` | Configure Windows SignalRGB lock and unlock automation. | windows_gaming_*, windows_performance_mode_*, windows_signalrgb_*, gaming_benchmark_*; templates/windows; scripts/gaming. | `ansible-playbook playbooks/windows/windows-signalrgb.yml --syntax-check` |
| `playbooks/windows/windows-gaming-monitoring.yml` | `localhost, windows_gaming_monitoring_targets` | Configure Windows gaming monitoring. | windows_gaming_*, windows_performance_mode_*, windows_signalrgb_*, gaming_benchmark_*; templates/windows; scripts/gaming. | `ansible-playbook playbooks/windows/windows-gaming-monitoring.yml --syntax-check` |
| `playbooks/windows/windows-gaming-benchmark.yml` | `localhost, windows_gaming_benchmark_targets` | Configure Windows gaming benchmark capture. | windows_gaming_*, windows_performance_mode_*, windows_signalrgb_*, gaming_benchmark_*; templates/windows; scripts/gaming. | `ansible-playbook playbooks/windows/windows-gaming-benchmark.yml --syntax-check` |

### apps

Owner area: Standalone application appliances.

| Playbook | Hosts | Purpose | Main vars/sources | Safe validation |
| --- | --- | --- | --- | --- |
| `playbooks/apps/freepbx.yml` | `freepbx-vm` | Configure FreePBX/Asterisk guardrails. | freepbx_*, apt_pin_release; templates/freepbx; none by default. | `ansible-playbook playbooks/apps/freepbx.yml --syntax-check` |
| `playbooks/apps/homebridge.yml` | `homebridge-lxc` | Configure Homebridge appliance guardrails. | none by default; none by default; none by default. | `ansible-playbook playbooks/apps/homebridge.yml --syntax-check` |
