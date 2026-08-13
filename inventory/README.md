# Inventory Guide

This directory owns host membership, group defaults, host-specific overrides,
and encrypted inventory secrets.

## Layout

- `hosts.ini`: inventory group hierarchy and host membership.
- `group_vars/all/`: global defaults and global vault material.
- `group_vars/<group>/`: group-wide defaults for OS, platform, or role groups.
- `host_vars/<hostname>/`: host-specific overrides, split by concern.
- `vault.yml`: encrypted secrets beside the variables that consume them.
- `vault.yml.example`: non-secret example shape for a vault file.

Prefer modular host var files such as `backup.yml`, `docker.yml`,
`firewall.yml`, `performance-mode.yml`, or `virtiofs.yml`. Do not put unrelated
settings into a broad catch-all file when a concern-specific file exists.

## Group Hierarchy

- `managed_hosts`: normal convergence root.
- `linux_hosts`: Debian/Ubuntu, Proxmox, VMs, LXCs, Raspberry Pi, and the
  controller.
- `macos_hosts`: macOS hosts that need SSH/Homebrew handling.
- `workstations`: user-facing laptops/desktops with conservative defaults.
  `jn-t14s-lin` remains here for desktop package policy, but its controller/server
  role explicitly overrides the group default to enable weekly updates and
  reboot-on-required behavior.
- `nas_server`: portable NAS role owner for storage services.
- `docker_hosts`: hosts that receive Docker Compose stacks.
- `hermes_hosts`: future isolated Hermes VM; intentionally empty until the
  placement gate passes.
- `gluetun_hosts`: hosts with Gluetun/qBittorrent VPN automation.
- `cloudflare_ddns_hosts`: hosts that run Cloudflare DNS-only DDNS timers.
- `tailscale_peer_relay_endpoint_hosts`: hosts that sync peer-relay endpoints.
- `backup_clients`: hosts with restic or local-restic backup policy.
- `retired_hosts`: retained records excluded from normal convergence.

## Where Things Live

| Concern | Inventory owner | Related playbooks | Related sources |
| --- | --- | --- | --- |
| Docker stacks and redacted agent inventory | `host_vars/<host>/docker.yml`, `group_vars/docker_hosts/` | `playbooks/docker/docker-stacks.yml`, `playbooks/docker/docker-auto-update.yml`, `playbooks/docker/openclaw-docker-report.yml` | `templates/docker/`, `scripts/docker/` |
| Cloudflare DDNS | `host_vars/<host>/cloudflare-ddns.yml`, `cloudflare_ddns_hosts` | `playbooks/network/cloudflare-ddns.yml` | `templates/network/` |
| Tailscale peer relay endpoint sync | `host_vars/<host>/tailscale.yml`, `tailscale_peer_relay_endpoint_hosts` | `playbooks/network/tailscale-peer-relay-endpoint.yml` | `templates/network/` |
| Backups | `group_vars/backup_clients/`, `host_vars/<host>/backup.yml` | `playbooks/backup-sync/restic.yml`, `playbooks/backup-sync/local-restic.yml` | `templates/storage/` |
| Proxmox firewall | `group_vars/proxmox_nodes/firewall.yml`, `host_vars/<node>/firewall.yml` | `playbooks/proxmox/proxmox-firewall.yml`, `playbooks/proxmox/proxmox-router-firewall.yml` | `templates/proxmox/` |
| VirtioFS | `host_vars/<proxmox-node>/virtiofs.yml`, `host_vars/<vm>/virtiofs.yml` | `playbooks/storage/virtiofs.yml` | `templates/proxmox/` |
| Windows tuning | `host_vars/lj-gaming-pc/*.yml` | `playbooks/windows/` | `templates/windows/`, `scripts/gaming/` |
| Streaming | `host_vars/media-vm/stream-relay.yml` | `playbooks/media/stream-relay.yml` | `docs/streaming-runbook.md`, `templates/streaming/`, `scripts/streaming/` |
| Immich media inbox | `host_vars/docker-vm/immich-media-inbox.yml` | `playbooks/media/immich-media-inbox.yml` | `docs/immich-media-inbox.md`, Astra skill, `templates/media-inbox/`, `scripts/media-inbox/` |
| Media release policy | `host_vars/docker-vm/*release*`, `host_vars/docker-vm/nightly-media-maintenance.yml` | `playbooks/media/media-release-stamper.yml`, `playbooks/media/nightly-media-maintenance.yml` | `docs/media-release-policy.md`, `scripts/media-release/` |
| Storage pools and shares | `group_vars/nas_server/`, `host_vars/ts440/` | `playbooks/storage/` | `templates/storage/`, `templates/samba/`, `scripts/storage/` |
| Agent services | `host_vars/*/codex.yml`, `host_vars/*/openclaw.yml`, `group_vars/hermes_hosts/` | `playbooks/agents/` | `templates/openclaw/`, `templates/hermes/`, `docs/openclaw-heartbeats.md`, `docs/hermes-replacement.md` |

## Operating Rules

- Add a host to every platform and functional group needed for `site.yml`.
- Keep secrets in encrypted `vault.yml` files, not plain variable files.
- If an inventory variable moves, update consuming playbooks, templates, docs,
  and examples in the same change.
- Validate inventory-sensitive changes with `ansible-inventory --list --yaml`
  and the relevant playbook syntax or check run.
