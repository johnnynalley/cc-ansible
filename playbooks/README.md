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
- `agents/`: Codex, Claude archive sync, OpenClaw, and Hermes services.
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
| `playbooks/docker/agent-docker-report.yml` | `docker_hosts` | Publish a strict redacted Docker inventory through a dedicated forced-command account. | agent_docker_report_*; scripts/docker/agent-docker-report*. | `ansible-playbook playbooks/docker/agent-docker-report.yml --syntax-check` |
| `playbooks/docker/agent-docker-update-trigger.yml` | `docker_hosts` | Expose only status and start for the existing Ansible-selected Docker auto-updater through a separate forced-command account. | agent_docker_update_trigger_*; scripts/docker/agent-docker-update-trigger.py. | `ansible-playbook playbooks/docker/agent-docker-update-trigger.yml --syntax-check` |

### media

Owner area: Plex, streaming, media maintenance, release-policy automation.

| Playbook | Hosts | Purpose | Main vars/sources | Safe validation |
| --- | --- | --- | --- | --- |
| `playbooks/media/immich-media-inbox.yml` | `docker_hosts` (opt-in) | Deploy Astra's headless Immich screenshot semantic-analysis queue. | immich_media_inbox_*; templates/media-inbox; scripts/media-inbox. | `ansible-playbook playbooks/media/immich-media-inbox.yml --syntax-check` |
| `playbooks/media/plex-appliance.yml` | `plex_appliances` | Configure Plex appliance. | nightly_media_*, media_release_stamper_*, media_stack_health_*, stream_relay_*, plex_appliance_*; templates/media-maintenance, templates/streaming, templates/plex-appliance, templates/docker; scripts/media-maintenance, scripts/media-release, scripts/streaming. | `ansible-playbook playbooks/media/plex-appliance.yml --syntax-check` |
| `playbooks/media/nightly-media-maintenance.yml` | `nas_server, media-vm:docker-vm` | Configure nightly media maintenance. | nightly_media_*, media_release_stamper_*, media_stack_health_*, stream_relay_*, plex_appliance_*; templates/media-maintenance, templates/streaming, templates/plex-appliance, templates/docker; scripts/media-maintenance, scripts/media-release, scripts/streaming. | `ansible-playbook playbooks/media/nightly-media-maintenance.yml --syntax-check` |
| `playbooks/media/media-release-stamper.yml` | `gluetun_hosts` | Configure media release metadata stamping; `--tags media-release-reconciler` scopes deployment to the exact-target reconciler. | nightly_media_*, media_release_stamper_*, media_stack_health_*, stream_relay_*, plex_appliance_*; templates/media-maintenance, templates/streaming, templates/plex-appliance, templates/docker; scripts/media-maintenance, scripts/media-release, scripts/streaming. | `ansible-playbook playbooks/media/media-release-stamper.yml --syntax-check` |
| `playbooks/media/sonarr-transaction-monitor.yml` | `gluetun_hosts:media-vm` | Configure Sonarr transaction monitor. | nightly_media_*, media_release_stamper_*, media_stack_health_*, stream_relay_*, plex_appliance_*; templates/media-maintenance, templates/streaming, templates/plex-appliance, templates/docker; scripts/media-maintenance, scripts/media-release, scripts/streaming. | `ansible-playbook playbooks/media/sonarr-transaction-monitor.yml --syntax-check` |
| `playbooks/media/media-stack-health.yml` | `docker-vm` | Configure media health monitoring and classified NFS/container-bind recovery. | nightly_media_*, media_release_stamper_*, media_stack_health_*, stream_relay_*, plex_appliance_*; templates/media-maintenance, templates/streaming, templates/plex-appliance, templates/docker; scripts/media-maintenance, scripts/media-release, scripts/streaming. | `ansible-playbook playbooks/media/media-stack-health.yml --syntax-check` |
| `playbooks/media/plex-server-health.yml` | `media-vm, nas_server` | Configure Plex server, VirtioFS, and scrub-window health monitor. | nightly_media_*, media_release_stamper_*, media_stack_health_*, plex_server_health_*, stream_relay_*, plex_appliance_*; templates/media-maintenance, templates/streaming, templates/plex-appliance, templates/docker; scripts/media-maintenance, scripts/media-release, scripts/streaming. | `ansible-playbook playbooks/media/plex-server-health.yml --syntax-check` |
| `playbooks/media/stream-relay.yml` | `media-vm` | Configure stream relay. | nightly_media_*, media_release_stamper_*, media_stack_health_*, stream_relay_*, plex_appliance_*; templates/media-maintenance, templates/streaming, templates/plex-appliance, templates/docker; scripts/media-maintenance, scripts/media-release, scripts/streaming. | `ansible-playbook playbooks/media/stream-relay.yml --syntax-check` |

### backup-sync

Owner area: Backups, sync jobs, and Nextcloud external-storage refresh.

| Playbook | Hosts | Purpose | Main vars/sources | Safe validation |
| --- | --- | --- | --- | --- |
| `playbooks/backup-sync/restic.yml` | `backup_clients:!macos_hosts` | Configure restic backups (B2 offsite). | restic_*, local_restic_*, rclone_sync_*, git_sync_*, nextcloud_scan_*; templates/storage, templates/docker when sync jobs consume generated configs; none by default. | `ansible-playbook playbooks/backup-sync/restic.yml --syntax-check` |
| `playbooks/backup-sync/local-restic.yml` | `backup_clients:!macos_hosts, ts440` | Configure local Restic backups with bounded transient target-outage retries, application-consistent Hermes recovery staging, and independent NAS-side freshness alerts. | restic_*, local_restic_*, hermes_disaster_recovery_*; scripts/agents/hermes-disaster-recovery-stage.py; scripts/storage/restic-snapshot-freshness.py; templates/storage and templates/docker when sync jobs consume generated configs. | `ansible-playbook playbooks/backup-sync/local-restic.yml --syntax-check` |
| `playbooks/backup-sync/rclone-sync.yml` | `managed_hosts` | Configure rclone sync jobs. | restic_*, local_restic_*, rclone_sync_*, git_sync_*, nextcloud_scan_*; templates/storage, templates/docker when sync jobs consume generated configs; none by default. | `ansible-playbook playbooks/backup-sync/rclone-sync.yml --syntax-check` |
| `playbooks/backup-sync/git-sync.yml` | `nas_server` | Configure git-sync timer (ts440). | restic_*, local_restic_*, rclone_sync_*, git_sync_*, nextcloud_scan_*; templates/storage, templates/docker when sync jobs consume generated configs; none by default. | `ansible-playbook playbooks/backup-sync/git-sync.yml --syntax-check` |
| `playbooks/backup-sync/nextcloud-scan.yml` | `nextcloud-vm` | Configure Nextcloud external storage scan. | restic_*, local_restic_*, rclone_sync_*, git_sync_*, nextcloud_scan_*; templates/storage, templates/docker when sync jobs consume generated configs; none by default. | `ansible-playbook playbooks/backup-sync/nextcloud-scan.yml --syntax-check` |

### agents

Owner area: Codex, Claude archive sync, OpenClaw, and Hermes services.

| Playbook | Hosts | Purpose | Main vars/sources | Safe validation |
| --- | --- | --- | --- | --- |
| `playbooks/agents/codex-cli.yml` | `orchestrator` | Configure Codex CLI. | codex_*, claude_memory_sync_*, openclaw_*; templates/openclaw; none by default. | `ansible-playbook playbooks/agents/codex-cli.yml --syntax-check` |
| `playbooks/agents/hermes-shadow.yml` | `hermes_hosts` | Stage three isolated Hermes profiles; seed profile-owned identity and operating contracts only when absent; retain root-owned Discord, automation, security, and tool-authority policy; install signed root-managed offline Tirith; validate native merged config as each profile; and keep production delivery and schedules disabled by default. | hermes_shadow_*; hermes_tirith_*; templates/hermes; files/hermes; scripts/agents. | `ansible-playbook playbooks/agents/hermes-shadow.yml --syntax-check` |
| `playbooks/agents/hermes-replacement-node-rehearsal.yml` | `rehearsal_controller`, disposable dynamic `hermes_hosts` member | Build a credential-free Ubuntu systemd container through rootless Podman, apply the production Hermes platform/bootstrap boundary without starting Gateways, validate runtime wiring, and remove the accepted target. The dedicated inventory contains no production host. | hermes_replacement_rehearsal_*; hermes_shadow_*; `inventory/hermes-replacement-rehearsal.ini`; `files/hermes/rehearsal/Containerfile`. | `ansible-playbook -i inventory/hermes-replacement-rehearsal.ini playbooks/agents/hermes-replacement-node-rehearsal.yml --syntax-check` |
| `playbooks/agents/hermes-production-cutover.yml` | `hermes_hosts` | Replace OpenClaw delivery with two Hermes Discord consumers for Astra, Dubble, and the Astra-owned Rigel channel, preserving Health and automatic rollback; disabled by default. | hermes_production_cutover_*; templates/hermes; files/hermes; scripts/agents. | `ansible-playbook playbooks/agents/hermes-production-cutover.yml --syntax-check` |
| `playbooks/agents/hermes-production-runtime.yml` | `hermes_hosts` | Safely converge the live Hermes shared runtime, official messaging dependencies, functional Discord readiness, native updater, and two production consumers while OpenClaw stays offline and Health stays active; disabled by default. | hermes_production_runtime_*; hermes_shadow_*; templates/hermes; scripts/agents. | `ansible-playbook playbooks/agents/hermes-production-runtime.yml --syntax-check` |
| `playbooks/agents/hermes-native-gateway-migration.yml` | `hermes_hosts` | Transactionally migrate retained flat Hermes profile state to native named profiles and replace handwritten base units with Hermes-installed system units while preserving hardened drop-ins and rollback; disabled without exact approval. | hermes_native_gateway_migration_*; hermes_shadow_*; templates/hermes; scripts/agents. | `ansible-playbook playbooks/agents/hermes-native-gateway-migration.yml --syntax-check` |
| `playbooks/agents/hermes-memory-continuity.yml` | `hermes_hosts` | Transactionally enable Astra's reviewed LCM context engine and native OSS Mem0 provider, convert approved existing OpenClaw stores into separate Hermes targets, reconcile exact counts/digests, and restore prior state on failure; disabled without exact approval. | hermes_memory_continuity_*; hermes_shadow_*; templates/hermes; files/hermes; scripts/agents. | `ansible-playbook playbooks/agents/hermes-memory-continuity.yml --syntax-check` |
| `playbooks/agents/hermes-profile-memory-continuity.yml` | `hermes_hosts` | Audit or transactionally activate isolated stable LCM and Mem0 v3 for one reviewed non-Astra profile using exact source hashes/scopes, local plus managed rollback, and changed-run-only native Gateway restart; Rigel is enabled before Dubble's public-memory review. | hermes_profile_memory_continuity_*; hermes_lcm_*; hermes_mem0_*; templates/hermes; scripts/agents. | `ansible-playbook playbooks/agents/hermes-profile-memory-continuity.yml --syntax-check` |
| `playbooks/agents/hermes-mem0-native-upgrade.yml` | `hermes_hosts` | Transactionally advance Astra's native Mem0 runtime to newest stable dependencies and a source-preserving v3 dense+BM25 Qdrant collection, with exact package/count/schema/recall gates and local plus NFS rollback; disabled without exact approval. | hermes_mem0_native_upgrade_*; hermes_mem0_*; templates/hermes; scripts/agents. | `ansible-playbook playbooks/agents/hermes-mem0-native-upgrade.yml --syntax-check` |
| `playbooks/agents/hermes-memory-servers.yml` | `hermes_hosts` | Audit or transactionally advance the Qdrant and Ollama servers behind Astra memory to their newest official stable releases, with a full Qdrant snapshot, checksummed staging, exact data/model/schema gates, native Mem0 recall, and rollback. | hermes_memory_servers_*; hermes_mem0_*; templates/hermes. | `ansible-playbook playbooks/agents/hermes-memory-servers.yml --syntax-check` |
| `playbooks/agents/hermes-lcm-native-features.yml` | `hermes_hosts` | Audit or transactionally enable Astra's stable native LCM semantic, proactive, temporal, and all-session recall features with local-only embeddings, verified SQLite/NFS rollback, and zero-drift restart suppression. | hermes_lcm_native_features_*; templates/hermes; scripts/agents. | `ansible-playbook playbooks/agents/hermes-lcm-native-features.yml --syntax-check` |
| `playbooks/agents/hermes-lcm-backfill.yml` | `hermes_hosts` | Audit or converge staggered low-priority native LCM summary/chunk backfill timers against local Ollama without blocking or restarting Astra. | hermes_lcm_backfill_*; hermes_lcm_embedding_*; templates/hermes; scripts/agents. | `ansible-playbook playbooks/agents/hermes-lcm-backfill.yml --syntax-check` |
| `playbooks/agents/hermes-automation.yml` | `hermes_hosts` | Transactionally converge the canonical current OpenClaw schedule as 18 Astra jobs, one Dubble job, bounded collectors/timers, and native profile backups; preserve seven historical-only rows without reactivating them; keep FreshRSS inside the single Daily Summary path and OpenClaw offline; disabled by default. | hermes_automation_*; templates/hermes; files/hermes; scripts/agents. | `ansible-playbook playbooks/agents/hermes-automation.yml --syntax-check` |
| `playbooks/agents/hermes-remote-access.yml` | `hermes_hosts, linux_hosts:!hermes_hosts` | Provision Astra's dedicated non-root SSH identity across reachable managed Linux, require critical media/storage/Plex hosts, record unavailable hosts for heartbeat follow-up, and prohibit sudo, Docker-group, owner-key, or old-user fallback; disabled by default. | hermes_remote_access_*; templates/hermes/astra-ssh-config.j2. | `ansible-playbook playbooks/agents/hermes-remote-access.yml --syntax-check` |
| `playbooks/agents/hermes-docker-inventory.yml` | `hermes_hosts` | Back up and promote Astra's inventory-derived Docker host manifest, live-container report/update plugin, two dedicated SSH credentials, native per-turn update approval, policy checksums, and live smoke verification; disabled without exact approval. | hermes_docker_inventory_*; files/hermes/plugins/agent-docker-inventory; scripts/agents. | `ansible-playbook playbooks/agents/hermes-docker-inventory.yml --syntax-check` |
| `playbooks/agents/hermes-compose-admin.yml` | `hermes_hosts, docker_hosts` | Back up and promote Astra's inventory-derived typed Compose transaction broker with a dedicated forced-command identity, exact mutation approvals, rollback journals, and live status/plan smoke verification; disabled without exact approval. | hermes_compose_admin_*; files/hermes/plugins/compose-admin; scripts/docker/agent-compose-transaction.py; scripts/agents. | `ansible-playbook playbooks/agents/hermes-compose-admin.yml --syntax-check` |
| `playbooks/agents/hermes-openclaw-dry-run.yml` | `hermes_hosts` | Inventory the pinned official importer through an ephemeral shape-only, networkless, read-only OpenClaw view and root-private structural report; disabled by default. | hermes_openclaw_dry_run_*; files/hermes/openclaw-dry-run-contract.json; scripts/agents/hermes-openclaw-dry-run.py. | `ansible-playbook playbooks/agents/hermes-openclaw-dry-run.yml --syntax-check` |
| `playbooks/agents/hermes-openclaw-evidence.yml` | `hermes_hosts` | Reconcile every preserved OpenClaw path and expose the untouched source to Astra through a generated secret-redaction overlay and strictly read-only, Astra-only evidence mount; disabled without exact approval. | hermes_openclaw_evidence_*; files/hermes/openclaw-evidence-contract.json; scripts/agents/hermes-openclaw-evidence.py; templates/hermes. | `ansible-playbook playbooks/agents/hermes-openclaw-evidence.yml --syntax-check` |
| `playbooks/agents/hermes-profile-memory.yml` | `hermes_hosts` | Back up all three memory stores, validate four vault-encrypted Astra/Rigel seeds with Hermes's native scanner, install atomically, and restore on any verification failure; disabled by default. | hermes_profile_memory_*; files/hermes/profile-memory-contract.json; files/hermes/profile-memory; scripts/agents/hermes-memory-seed-validate.py. | `ansible-playbook playbooks/agents/hermes-profile-memory.yml --syntax-check` |
| `playbooks/agents/hermes-profile-skills.yml` | `hermes_hosts` | Back up root-managed profile skills, native-validate seven reviewed declarative skill deployments, install exact per-profile inventories, prove native discovery through read-only service bindings, and restore on verification failure; disabled by default. | hermes_profile_skills_*; files/hermes/profile-skills-contract.json; files/hermes/profile-skills; scripts/agents/hermes-profile-skills-validate.py. | `ansible-playbook playbooks/agents/hermes-profile-skills.yml --syntax-check` |
| `playbooks/agents/hermes-profile-data.yml` | `hermes_hosts` | Copy reviewed project data and operator references into isolated per-profile writable/read-only roots with source-stability checks, exact manifests, rollback, runtime bind proof, and no activation; disabled by default. | hermes_profile_data_*; files/hermes/profile-data-stage-contract.json; files/hermes/profile-import-contract.json; files/openclaw/workspace-migration-policy.json; scripts/agents/hermes-profile-data-stage.py. | `ansible-playbook playbooks/agents/hermes-profile-data.yml --syntax-check` |
| `playbooks/agents/openclaw.yml` | `openclaw_hosts` | Deploy OpenClaw AI agent. | codex_*, claude_memory_sync_*, openclaw_*; templates/openclaw; none by default. | `ansible-playbook playbooks/agents/openclaw.yml --syntax-check` |
| `playbooks/agents/hermes-health-receiver.yml` | `hermes_hosts` | Migrate Health ingestion to a Hermes-native isolated service and publish aggregate-only reports; disabled by default. | hermes_health_receiver_* migration vars; scripts/agents; none by default. | `ansible-playbook playbooks/agents/hermes-health-receiver.yml --syntax-check` |
| `playbooks/agents/openclaw-isolated-gateway.yml` | `openclaw_hosts` | Stage a modernized split Gateway/Codex canary with immutable runtime/provider code, separate no-login identities and secrets, isolated executor OAuth, and a required model proof; disabled by default. | openclaw_isolated_gateway_*; templates/openclaw; scripts/agents. | `ansible-playbook playbooks/agents/openclaw-isolated-gateway.yml --syntax-check` |
| `playbooks/agents/openclaw-state-rehearsal.yml` | `openclaw_hosts` | Rehearse verified relocation of active file-backed OpenClaw session stores without copying config, credentials, plugins, channels, or the full legacy workspace; bound retained payloads to current plus rollback generations; disabled by default. | openclaw_state_rehearsal_*; scripts/agents/openclaw-session-relocate.py; scripts/agents/openclaw-rehearsal-retention.py. | `ansible-playbook playbooks/agents/openclaw-state-rehearsal.yml --syntax-check` |
| `playbooks/agents/openclaw-doctor-rehearsal.yml` | `openclaw_hosts` | Rehearse supported Doctor migrations and replace legacy plugin install mechanisms on credential-free protected state copies with bounded generation retention; disabled by default. | openclaw_doctor_rehearsal_*; tasks/openclaw-doctor-plugin-source.yml; tasks/openclaw-doctor-snapshot.yml; scripts/agents/openclaw-doctor-rehearsal.py; scripts/agents/openclaw-rehearsal-retention.py. | `ansible-playbook playbooks/agents/openclaw-doctor-rehearsal.yml --syntax-check` |
| `playbooks/agents/openclaw-canary-data-rehearsal.yml` | `openclaw_hosts` | Transactionally promote the verified modern workspace and sessions into the silent loopback canary and use native RPC for classified session transition; disabled by default. | openclaw_canary_data_*; files/openclaw; scripts/agents. | `ansible-playbook playbooks/agents/openclaw-canary-data-rehearsal.yml --syntax-check` |
| `playbooks/agents/openclaw-behavior-rehearsal.yml` | `openclaw_hosts` | Prove concise Dubble output, native two-reviewer Star lineage, and idle-silent Rigel heartbeat behavior without channel delivery; disabled by default. | openclaw_behavior_rehearsal_*; templates/openclaw/openclaw-modern.json.j2; scripts/agents. | `ansible-playbook playbooks/agents/openclaw-behavior-rehearsal.yml --syntax-check` |
| `playbooks/agents/openclaw-security-rehearsal.yml` | `openclaw_hosts` | Prove the split Codex executor cannot use sudo, read Gateway secrets, reach Docker, or write outside its workspace under one channel-less hostile prompt; disabled by default. | openclaw_security_rehearsal_*; templates/openclaw/openclaw-modern.json.j2; scripts/agents. | `ansible-playbook playbooks/agents/openclaw-security-rehearsal.yml --syntax-check` |
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
| `playbooks/windows/windows-gaming-tuning.yml` | `localhost, windows_gaming_tuning_targets` | Configure Windows gaming tuning, optional gated shader-cache maintenance, and streaming helpers. | windows_gaming_*, windows_performance_mode_*, windows_signalrgb_*, gaming_benchmark_*, windows_streaming_*; templates/windows; scripts/gaming, scripts/streaming. | `ansible-playbook playbooks/windows/windows-gaming-tuning.yml --syntax-check` |
| `playbooks/windows/windows-performance-mode.yml` | `localhost, windows_performance_mode_targets` | Configure optional/manual Windows Performance Mode scripts and shortcuts; auto watcher can be disabled per host. | windows_gaming_*, windows_performance_mode_*, windows_signalrgb_*, gaming_benchmark_*; templates/windows; scripts/gaming. | `ansible-playbook playbooks/windows/windows-performance-mode.yml --syntax-check` |
| `playbooks/windows/windows-signalrgb.yml` | `localhost, windows_signalrgb_targets` | Retire legacy SignalRGB lock/unlock automation and preserve ordinary user startup. | signalrgb_*; none; none. | `ansible-playbook playbooks/windows/windows-signalrgb.yml --syntax-check` |
| `playbooks/windows/windows-gaming-monitoring.yml` | `localhost, windows_gaming_monitoring_targets` | Configure Windows gaming monitoring. | windows_gaming_*, windows_performance_mode_*, windows_signalrgb_*, gaming_benchmark_*; templates/windows; scripts/gaming. | `ansible-playbook playbooks/windows/windows-gaming-monitoring.yml --syntax-check` |
| `playbooks/windows/windows-gaming-benchmark.yml` | `localhost, windows_gaming_benchmark_targets` | Configure Windows gaming benchmark capture. | windows_gaming_*, windows_performance_mode_*, windows_signalrgb_*, gaming_benchmark_*; templates/windows; scripts/gaming. | `ansible-playbook playbooks/windows/windows-gaming-benchmark.yml --syntax-check` |

### apps

Owner area: Standalone application appliances.

| Playbook | Hosts | Purpose | Main vars/sources | Safe validation |
| --- | --- | --- | --- | --- |
| `playbooks/apps/freepbx.yml` | `freepbx-vm` | Configure FreePBX/Asterisk guardrails. | freepbx_*, apt_pin_release; templates/freepbx; none by default. | `ansible-playbook playbooks/apps/freepbx.yml --syntax-check` |
| `playbooks/apps/homebridge.yml` | `homebridge-lxc` | Configure Homebridge appliance guardrails. | none by default; none by default; none by default. | `ansible-playbook playbooks/apps/homebridge.yml --syntax-check` |
