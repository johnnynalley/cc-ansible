# Repository Guidelines

> **Last updated:** 2026-05-26

This file provides guidance to Codex CLI when working with code in this repository. It combines a quick contributor guide with the full operational reference migrated from Claude Code.

## Quick Contributor Guide


### Project Structure & Module Organization

This repository manages homelab infrastructure with Ansible. `site.yml` is the top-level playbook and `playbooks/` contains domain-owned targeted runs such as `playbooks/core/packages.yml`, `playbooks/docker/docker-stacks.yml`, and `playbooks/proxmox/proxmox-firewall.yml`. Shared task files live in `tasks/`, Jinja2 templates in `templates/`, helper executables in `scripts/` and `bin/`, static non-template files in `files/`, operator docs in `docs/`, and all host/group configuration under `inventory/`. Start with `playbooks/README.md`, `templates/README.md`, `scripts/README.md`, `docs/README.md`, `inventory/README.md`, and `files/README.md` before adding or moving assets in those areas. Use `inventory/group_vars/` for group defaults and `inventory/host_vars/<hostname>/` for host-specific overrides.

### Playbook Inventory & Domain Ownership

Treat playbooks as managed domain-owned entrypoints. Before adding, moving, or renaming a playbook, read `playbooks/README.md` and the relevant `playbooks/<domain>/README.md` to find the current owner folder, validation command, and related templates/scripts. Do not add new playbooks directly under `playbooks/`; put them in the appropriate `playbooks/<domain>/` directory and update the playbook metadata header, `playbooks/README.md`, the domain README, `site.yml` when applicable, and every operator command or doc reference in the same change.

When moving a playbook, update task imports for the new depth, especially `../../tasks/...` imports, and re-run `scripts/repo/repo-audit` plus targeted syntax checks before committing.


### Script Inventory & Reusable Diagnostics

Treat reusable diagnostics, policy probes, and repair helpers as managed repository assets, not throwaway `/tmp` scripts. Before writing a new helper, read `scripts/README.md` and the relevant script-directory README to find existing tools and extension points. If a script would be useful beyond a single shell one-liner, add or improve a repo-managed script under an appropriate `scripts/<domain>/` directory, document it in that directory's README, and update `scripts/README.md` if the directory or tool category changes.

Do not create standalone diagnostic scripts in `/tmp` as the primary work product and then discard them. If a remote host needs a temporary copy for execution, the source should still live in the repo first, and the remote temporary copy should be cleaned up after use. Do not add new runnable scripts directly under `scripts/`; only the top-level script catalog belongs there.

### Template Inventory & Rendered Configs

Treat Jinja templates, compose templates, service units, scripts, and generated config sources under `templates/` as managed repository assets. Before adding or moving a template, read `templates/README.md` and the relevant template-directory README to find the current owner folder and consumers. Do not add new templates directly under `templates/`; put them in the appropriate `templates/<domain>/` directory, document them in that directory's README, and update `templates/README.md` when the directory or ownership category changes.

When moving, renaming, deleting, or replacing a template, update every playbook, task file, inventory variable, operator doc, and README reference in the same change. Pay special attention to dynamic Ansible template lookups such as Docker compose templates, nightly media maintenance service loops, and Windows script loops.

### Documentation Cross-References

When creating or materially updating operator docs, policy docs, runbooks, or troubleshooting guides under `docs/`, update `docs/README.md` and add or update the matching pointer in `AGENTS.md` in the relevant operational section. The point is discoverability: future agents should know where to find the source of truth without guessing filenames or relying on memory. Current source-of-truth docs include `docs/capture-card-streaming-plan.md`, `docs/fortnite-performance-investigation.md`, `docs/gaming-benchmark.md`, `docs/media-release-policy.md`, `docs/openclaw-heartbeats.md`, `docs/plex-appliance-operations.md`, and `docs/streaming-runbook.md`. If a new doc captures behavior that should persist across sessions, also add a concise Codex memory note when the user explicitly asks for memory persistence.

When a change affects repository layout, operator entrypoints, common commands, source-of-truth document locations, or human-facing workflow guidance, update `README.md` in the same scoped change. Do not leave `README.md` pointing at old paths, stale command examples, or outdated directory structure after moving files, scripts, templates, playbooks, or docs. Also update the relevant catalog README (`docs/README.md`, `playbooks/README.md`, `templates/README.md`, `scripts/README.md`, `inventory/README.md`, or `files/README.md`) and run or extend `scripts/repo/repo-audit` when the change affects paths or references. Docs, README files, AGENTS guidance, and cross-references must not go stale; keeping them current is part of the implementation, not a follow-up.

When renaming, moving, deleting, or replacing a source-of-truth doc, tracker, script, or runbook that OpenClaw references, update the matching OpenClaw workspace skills, hubs, heartbeat prompts, cron jobs, and guidance files in the same change. Do not leave OpenClaw pointing at stale paths after repo-side file moves.

### Session Naming

When the user asks Codex to name a session, consider the full context of the session before proposing a title. Use a natural-language title that describes what the session was really about; do not force lowercase slugs or replace spaces with hyphens unless the user explicitly asks for a filename-safe form.

### Build, Test, and Development Commands

- `ansible-galaxy collection install -r requirements.yml`: install required collections.
- `ansible-playbook site.yml`: apply the full configuration.
- `ansible-playbook playbooks/storage/samba.yml --check --diff`: dry-run a change and show rendered diffs before applying.
- `ansible-playbook playbooks/core/packages.yml --tags fastfetch`: run a tagged subset.
- `./bin/ansible-menu`: launch the interactive playbook runner.

### Coding Style & Naming Conventions

Write YAML with two-space indentation and descriptive task names. Keep playbooks focused on orchestration and move reusable logic into `tasks/*.yml`. Name playbooks and task files with lowercase hyphenated names, for example `network-recovery.yml`, and keep playbooks under the owning `playbooks/<domain>/` directory. Keep variables lowercase snake_case. Prefer modular variable files named for their concern, such as `host_vars/<hostname>/backup.yml`, `docker.yml`, `firewall.yml`, or `performance-mode.yml`; do not pile unrelated settings into a monolithic `vars.yml`. Templates should live under `templates/<domain>/`, use `.j2` suffixes when rendered, and render service/config names clearly, such as `templates/samba/smb.conf.j2`.

### Testing Guidelines

There is no dedicated unit-test suite. Validate changes with full-playbook Ansible dry runs before applying them: `ansible-playbook <playbook> --check --diff`. Do not use `--limit`; playbooks should be safe across their configured `hosts:` target, and if a full run is not safe, fix the playbook or inventory instead of narrowing execution. For YAML and Ansible quality checks, use `yamllint` and `ansible-lint` when available. For shell helpers or shell templates, run `shellcheck` on the rendered or source script when practical.

### Playbook Scope & Site Safety

Prefer integrating behavior into existing playbooks, shared task files, host/group variables, tags, or inventory groups instead of creating host-specific one-off playbooks. Add a new playbook only when it is a reusable feature boundary that matches the repo's domain-owned playbook structure. When adding one, place it under the owning `playbooks/<domain>/` directory and import it from `site.yml` when it belongs in normal convergence.

`site.yml` must be safe to run at any point. Every playbook should be scoped so it can run across its configured `hosts:` target without `--limit` and without destructive side effects on unrelated hosts. Use explicit inventory opt-ins, groups, and variables; skip unrelated hosts without changing them. Do not disable, remove, or reset services on hosts unless that host explicitly opts into that state.

### Commit & Pull Request Guidelines

Git history uses short Conventional Commit-style subjects such as `feat: ...` and `docs: ...`. Follow that pattern with a concise imperative summary. Pull requests should describe the affected hosts or groups, list the playbooks tested, and include dry-run output or a summary of expected changes for infrastructure-impacting updates. Link related issues when available.

When completing repo work, inspect the diff, verify no plaintext secrets or unrelated dirty files are being staged, then commit the completed scoped change without waiting for a separate reminder. If the work should not be committed immediately, state why. Do not leave finished, verified repo changes uncommitted silently. If you touch a file that already has unrelated dirty hunks, surface that immediately, avoid mixing them into your scoped commit unless the user explicitly approves, and either commit the approved prior hunks separately or document why they remain. Never let shared guidance files such as `AGENTS.md` accumulate invisible "someone should commit this later" edits.

Critical shared-file rule: any scoped edit to `AGENTS.md` or `site.yml` must be staged, checked for secrets and unrelated hunks, and committed before the next assistant response. These two files are commonly touched by multiple active sessions, so do not leave completed edits to them sitting uncommitted while continuing other work. If either file already has unrelated dirty hunks, stage only the approved scoped hunk or stop and explain the concrete blocker.

Before closing any repo-mutating session, run `git status --short --branch`. If the branch is ahead or has completed local changes, commit and push the scoped work; if anything remains dirty, explicitly identify it as generated junk, unrelated in-progress work, or a concrete blocker.

### Security & Configuration Tips

Do not commit real secrets. Encrypted values belong in `vault.yml` files beside the relevant `vars.yml`; examples may use `vault.yml.example`. The configured vault password path is `~/.ansible/vault_pass.txt`. Run `scripts/repo/repo-audit` before committing repo layout or source changes; it calls `scripts/repo/secrets-scan` by default so secret scanning is part of the normal audit path. Use `scripts/repo/repo-audit --require-gitleaks` when Gitleaks must be present, such as CI parity checks. Prefer full-playbook `--check --diff` runs for changes touching Proxmox, storage, firewall, backup, or Docker automation.

### Live Change Backups

Before mutating live infrastructure state, application configs, databases, service data, or generated controller/runtime files, take a targeted timestamped backup, snapshot, export, or app-native backup of the affected state unless the change is trivial and fully reproducible or the user explicitly waives backups for that operation. Record the backup path in the working notes, docs, or final response when it matters for rollback. Treat these as temporary rollback aids: keep them while the rollout is being validated, then document or perform cleanup/retention once the change is proven. Read-only diagnostics and dry runs do not need backups.

Do not introduce live or repository mitigation changes during an incident merely because they seem prudent or adjacent to the symptom. If the user did not explicitly ask for that change and it is not strictly required to complete the requested action, stop and ask permission first. When the user narrows scope, drop unrelated safety ideas and focus only on the requested investigation or fix.

### Migration Cleanup

When migrating a managed script, service, scheduled task, config path, binary, or generated artifact, include Ansible-managed cleanup for the legacy path in the same change whenever it is safe. Verify all consumers such as scheduled tasks, startup entries, service units, OBS hooks, wrapper scripts, or documented operator commands point at the new path before considering the migration complete.

### Troubleshooting Assumptions

Do not assume a symptom is an upstream software bug or regression unless there is an exact documented issue, release note, or vendor advisory matching the observed failure. Default to diagnosing local configuration, runtime state, logs, resource pressure, integration drift, and recent local changes first. Avoid update-fragile local patches unless the user explicitly approves a temporary workaround.

For recurring `jn-t14s-lin` Wi-Fi throughput collapse with no media-stack change, prioritize root-cause evidence before remediation: repeated `wlp2s0` association churn, `ath11k_pci` TX completion warnings (`msdu_done bit in attention is not set`), and roaming between nearby BSSIDs are the active signal that the radio path is unstable and likely dominating behavior.

Root cause comes before self-healing. Do not present an auto-restart, retry loop, watchdog, periodic reassertion, or other symptom-recovery automation as the fix for an unexplained incident until the trigger is understood. If immediate service recovery is needed, label it as temporary mitigation, then continue the investigation with logs, timelines, live state, and recent-change evidence until the cause and prevention path are clear. The goal is to explain why it happened and prevent recurrence, not to hide recurrence after the fact.

For incident capture on this host, include at least:
- `journalctl -b -1 -k | rg -i "ath11k|wlp2s0|msdu_done|deauthenticated|rejected association"`
- `journalctl -b -1 -u NetworkManager --since "<event_time>" | rg -i "wlp2s0|dhcp4: restarting|supplicant|reassociate"`
- `cat /proc/net/wireless`

Use this evidence before deciding whether the prevention should be AP/BSSID stabilization, driver/module recovery hooks, or platform firmware updates.

For live Windows gaming PC diagnostics, especially on `lj-gaming-pc` while the user is gaming or streaming, use narrow, bounded probes only. Do not run broad PowerShell/Ansible inspections that enumerate large process/log/state data and serialize deep JSON, and do not leave diagnostic probes running. If a probe hangs or looks expensive, stop it and verify no stale remote PowerShell workers remain before continuing. Ask first before any broad inspection that could consume noticeable CPU, memory, disk, or foreground responsiveness.

For Fortnite/Windows gaming performance work, treat `docs/fortnite-performance-investigation.md` as the running source of truth. Before suggesting a tweak or A/B test, check that document and the saved benchmark state so you do not repeat already-tested ideas or confuse untested candidates with proven wins. After every meaningful benchmark, setting change, driver/BIOS/chipset change, or conclusion, update that document in the same turn with the capture label/path, conditions, key metrics, interpretation, and next action.

Do not manage Fortnite in-game settings or user-owned game config files such as `GameUserSettings.ini` with Ansible. Record observations and benchmark results in the investigation doc, but leave Fortnite gameplay/video setting changes to the user or to explicit one-off user approval for that exact setting.

Before live `lj-gaming-pc` work or repeated Windows playbook runs, check Ansible controller health with `./bin/ansible-controller-guard check`; run it outside the Codex sandbox or with escalation when process visibility across sessions matters. Normal concurrent sessions should be supported through controller capacity and per-run pressure control, not by killing unrelated playbooks. If the controller is already under swap or IO pressure, prefer resource fixes, lower-priority execution, or a narrower managed playbook instead of adding more heavy work. If an Ansible run is interrupted, run the guard again and use its cleanup mode only when no playbook is active.

For Ansible controller and homelab control-plane reliability, prioritize stability over resource minimalism. If the controller or another core automation host shows resource-related instability, prefer overprovisioning CPU/RAM/swap/disk or migrating the workload to stronger idle hardware before accepting flaky sessions or failed convergence. Surface tradeoffs clearly, but do not be stingy with available hardware when stability is the goal.

When a Windows `win_shell`/PowerShell probe is interrupted or times out, killing the local Ansible process is not enough. Immediately verify the remote `powershell.exe` command line on the target and terminate only the abandoned diagnostic worker if it is still running, then recheck target memory/process state before continuing.

For `lj-gaming-pc` Windows OpenSSH, do not pin `C:\ProgramData\ssh\sshd_config` to the Tailscale IP with an active `ListenAddress 100.x.x.x` line. OpenSSH can start before Tailscale owns that address, which creates a boot race where `sshd` terminates or listens only after recovery actions. Keep SSH listening on `0.0.0.0:22` and use Windows Firewall/Tailscale policy for reachability control.

For `lj-gaming-pc` Ansible-managed Windows scripts, deploy local managed copies under `C:\ProgramData\Johnny\...`, not `C:\Users\jn\Nextcloud\Scripts\...`. The repo and Ansible/controller backups are the source of truth; Nextcloud script copies are legacy drift and should be removed by the relevant playbook after local deployment.

Do not launch visible Windows GUI applications such as OBS through SSH/Ansible on `lj-gaming-pc`; Windows session isolation can put them in a hidden or non-interactive desktop. For visible app launches, use an interactive scheduled task/watcher that is known to target the logged-in user session, or ask the user to open the app locally.

Even if the client has a persisted approval for `ansible lj-gaming-pc -m win_shell`, do not treat that prefix as broadly pre-approved. Ask for explicit user approval before using that exact ad-hoc PowerShell path unless the user has just requested the specific command/action in the current exchange. Prefer managed playbooks or narrower non-shell modules where practical.

Do not make empty future-behavior assurances. Avoid phrases like "this won't happen again", "I won't do that again", or "I'll make sure" unless the behavior change is immediately backed by a durable note or an `AGENTS.md` rule. If a promise cannot be persisted or should not be persisted, say that plainly and do not frame it as a future guarantee.

## Historical Claude Reference

This repository was migrated from Claude Code to Codex CLI on 2026-05-12. The active Codex guidance is this `AGENTS.md` file and the active project memory is `~/.codex/memories/`.

The original Claude-era sources are intentionally retained as dated fallback references:

- `/home/johnny/cc-ansible/CLAUDE.md`
- `/home/johnny/.claude/projects/-home-johnny-cc-ansible/memory/`
- `/home/johnny/codex-migration.md`

Treat those as archive material. They may become stale after migration, so prefer `AGENTS.md` and Codex memory for current instructions.

## Codex Operating Reference

The reference below was migrated from `CLAUDE.md` on 2026-05-12 and rewritten only where active agent names, document names, memory paths, or sync names needed to point at Codex. Operational details are otherwise preserved.

## Repository Overview

Ansible automation for a homelab infrastructure consisting of:
- 4 Proxmox hypervisors (ts440, pve-alto, pve-herc, pve-m70q)
- VMs/LXC containers (docker-vm, media-vm, nextcloud-vm, freepbx-vm, pdm-vm, homebridge-lxc, syncthing-lxc, pbs-lxc; retired records such as openclaw-vm stay in `retired_hosts`)
- 1 flat Ansible controller on jn-t14s-lin (Kubuntu)
- 1 Raspberry Pi 5 (mercury)
- 1 Kubuntu laptop (jn-t14s-lin) — ThinkPad T14s, dual-boot with Windows
- 1 Windows gaming workstation (lj-gaming-pc)
- 1 macOS workstation (macbook-pro)
- Retired inventory records for dev-vm and the old jn-desktop Linux install are kept in `retired_hosts` only and excluded from normal convergence.

All hosts communicate via Tailscale VPN (100.x.x.x addresses). All hosts are set to `America/Chicago` timezone (enforced by `bootstrap.yml`).

## IMPORTANT: Infrastructure as Code First

**ALWAYS prioritize Infrastructure as Code (IaC) over ad-hoc commands.** When asked to install packages, configure services, or make any changes to managed hosts:

Infrastructure changes should converge through the normal playbook graph. Before adding a new playbook, check whether an existing playbook plus variables, tags, or shared tasks can express the change. Host-specific bootstrap/baseline work should usually be inventory and existing playbook changes, not a new one-off playbook.

1. **Check if it can be managed via Ansible** - Add to host_vars, group_vars, or playbooks
2. **Update the appropriate configuration files** - packages.yml, vars.yml, etc.
3. **Run the playbook** - Don't use one-off shell commands that bypass Ansible
4. **Document in AGENTS.md/README.md** if it's a significant addition

**Never** run ad-hoc `ansible -m shell` or direct SSH commands to make persistent changes. Ad-hoc commands are only for:
- Troubleshooting/diagnostics
- One-time queries (checking status, logs)
- Operations that shouldn't be repeated (manual data migrations)

If a package exists in the system repos, add it to the appropriate `packages_*` variable. If a service needs configuration, create or update the relevant playbook/task file.

### New Host Onboarding

A new managed device is not complete when its feature-specific playbook works. Add it to the correct OS/platform group plus functional groups such as `backup_clients`, `bootstrap_hosts`, service-specific groups, and any relevant role groups. Add modular host_vars such as `vars.yml`, `packages.yml`, `backup.yml`, and service-specific files rather than a broad catch-all file. Bootstrap the host, then validate and apply through `ansible-playbook site.yml --syntax-check`, `ansible-playbook site.yml --check --diff`, and `ansible-playbook site.yml` without `--limit`.

## Git Workflow

The repository is hosted on GitHub (public): https://github.com/johnnynalley/cc-ansible

**jn-t14s-lin** (ThinkPad T14s, Kubuntu) is the flat Ansible controller. The working clone lives at `~/cc-ansible` on jn-t14s-lin. All Ansible commands should be run from there. It is also a workstation, but controller availability takes priority while plugged into AC power.

**Workflow:**
1. Make changes on jn-t14s-lin (`~/cc-ansible`)
2. Commit and push to GitHub
3. ts440 automatically pulls every 5 minutes via `git-sync.timer` (deployed by `playbooks/backup-sync/git-sync.yml`), keeping `/srv/nas-zfs/configs/ansible/cc-ansible` in sync for Nextcloud External Storage access
4. Raspberry Pi hosts are regular managed clients. They should not be treated as Ansible controllers or given a separate repo-copy workflow.

**git-sync on ts440:**
- Systemd timer runs every 5 minutes
- Pulls latest from GitHub to `/srv/nas-zfs/configs/ansible/cc-ansible`
- Keeps Nextcloud External Storage (Configs folder) up to date automatically
- Deploy with: `ansible-playbook playbooks/backup-sync/git-sync.yml`

## Common Commands

All commands should be run from jn-t14s-lin (`~/cc-ansible`).

```bash
# Run all playbooks via site.yml
ansible-playbook site.yml

# Run a specific playbook
ansible-playbook playbooks/core/packages.yml

# Do not use --limit; fix playbooks/inventory so full target runs are safe

# Dry run with diff
ansible-playbook playbooks/core/packages.yml --check --diff

# Run specific tags
ansible-playbook playbooks/core/packages.yml --tags fastfetch

# Interactive menu
./bin/ansible-menu

# View inventory
ansible-inventory --list --yaml

# Bootstrap new host (copy key to admin user first, then use su)
ssh-copy-id -i ~/.ssh/ansible_ed25519.pub johnny@<LAN_IP>
ansible-playbook playbooks/core/bootstrap.yml --ask-become-pass

# Run ad-hoc command with sudo (when SSH doesn't have sudo access)
ansible <hostname> -m shell -a "command here" --become
```

**Note**: When SSH sessions don't have sudo access but you need elevated privileges, use Ansible's `--become` flag. This works because Ansible uses passwordless sudo configured during bootstrap.

## SSH Authentication

Ansible on jn-t14s-lin uses a **dedicated passwordless SSH key** (`~/.ssh/ansible_ed25519`) for fallback host connections. Tailscale SSH is preferred for managed Linux hosts when the tailnet policy allows it. The key is configured as the default in `ansible.cfg` via `private_key_file`.

**Two keys are deployed by `bootstrap.yml`:**

| Key | Purpose | Passphrase |
|-----|---------|------------|
| `~/.ssh/id_ed25519.pub` | Personal/manual SSH | Yes |
| `~/.ssh/ansible_ed25519.pub` | Ansible automation | No (passwordless) |

**Tailscale SSH preference**: Prefer Tailscale SSH for managed Linux hosts whenever the tailnet policy allows it. Regular OpenSSH over a Tailscale IP is for bootstrap, break-glass, or hosts where Tailscale SSH is explicitly disabled. If OAuth enrollment uses advertised tags, keep host-side `tailscale_advertise_tags` and tailnet `tagOwners`/`ssh` policy aligned through Ansible-managed configuration instead of fixing tagged-device SSH manually in the admin console.

**Tailscale client safety**: Do not run `tailscale up`, `tailscale set`, tag changes, hostname changes, SSH preference changes, or automatic re-enrollment against an existing Tailscale host unless that host explicitly opts into that exact behavior. Existing stable Tailscale identities and IPs are live infrastructure dependencies. The shared Tailscale task may install/start `tailscaled`, but it must leave already-authenticated hosts' identity/preferences alone by default. New unattended enrollment requires an explicit inventory opt-in such as temporary `bootstrap_hosts` membership with `tailscale_auto_enroll: true`; remove hosts from that bootstrap scope after onboarding.

**Linux hosts** also accept Tailscale SSH (no keys needed), which Ansible uses by default when available. The dedicated key is the fallback if Tailscale is down.

**Proxmox migration SSH**: Proxmox migrations use root SSH between cluster nodes. `ssh-hardening.yml` sets `PermitRootLogin no` for `proxmox_nodes`, then appends a `Match Address` exception allowing key-only root login (`prohibit-password`) from the Proxmox LAN peer IPs defined in `inventory/group_vars/proxmox_nodes/vars.yml`. The same playbook manages `/etc/hosts` entries for cluster names so migration SSH resolves over LAN instead of Tailscale MagicDNS/Tailscale SSH. Do not broaden root SSH on ts440; add or update the LAN peer list if cluster nodes change.

**macOS (macbook-pro)** cannot use Tailscale SSH (App Store build is sandboxed). It relies exclusively on the dedicated Ansible key over regular SSH. SSH on macbook-pro is restricted to the Tailscale interface only:
- `ListenAddress 100.119.197.17` in `/etc/ssh/sshd_config`
- Remote Login enabled for user `johnny` only (System Settings → Sharing)

**Tailscale SSH MOTD**: Tailscale SSH invokes `login(1)` with PAM service `remote`, which by default has no config file (PAM falls back to `other`, which lacks `pam_motd.so`). The `ssh-hardening.yml` playbook deploys `/etc/pam.d/remote` to all Linux hosts to enable MOTD display over Tailscale SSH. Ubuntu hosts show a rich MOTD (system info, available updates) via `landscape-common` and `update-notifier-common` (installed by `packages.yml`). Debian hosts get custom MOTD scripts (`templates/motd/motd-*.sh.j2`) deployed to `/etc/update-motd.d/` showing system info, available updates, and reboot-required status.

**Deploying the key to a new host:**
```bash
# For Linux hosts (via Tailscale SSH or bootstrap)
ansible-playbook playbooks/core/bootstrap.yml -u root --ask-pass

# For macOS (manual first-time copy, then bootstrap handles future hosts)
ssh-copy-id -i ~/.ssh/ansible_ed25519.pub johnny@<tailscale-ip>
```

## Architecture

### Inventory Structure

Host groups form a hierarchy in `inventory/hosts.ini`:
- `managed_hosts` → all managed systems
  - `linux_hosts` → `debian_hosts` + `arch_hosts`
    - `debian_hosts`: `proxmox_nodes`, `vms_lxcs` (child groups: `vms` + `lxcs`), `orchestrator` (jn-t14s-lin), `raspberry_pis` (mercury)
    - `arch_hosts`: currently empty; add active Arch Linux hosts here only when they should participate in `site.yml`
  - `macos_hosts`: macbook-pro
- `workstations` → **cross-platform group** for desktops/laptops (jn-t14s-lin, macbook-pro)
  - Hosts in this group are ALSO in their OS-specific group (debian_hosts, arch_hosts, macos_hosts)
  - Group vars disable automated recovery: `network_watchdog_enabled: false`, `auto_updates_enabled: false`
  - Playbooks like `network-recovery.yml` explicitly exclude this group: `hosts: linux_hosts:!workstations`
- `nas_server` → **portable NAS role group** (currently ts440). Storage services: NFS, Samba, ZFS, mergerfs, drive mounts. Migrate NAS to new hardware by changing membership in this group.
- `development` → **cross-platform group** for dev tooling (gh, shellcheck, yq). Currently empty; the orchestrator gets controller/dev tools via its own host vars and the `orchestrator` group. Packages split by OS: `packages_debian_development_extra`, `packages_arch_development_extra`
- `docker_hosts` → systems running Docker Compose stacks (docker-vm, media-vm, nextcloud-vm, jn-t14s-lin)
- `gluetun_hosts` → hosts with Gluetun/qBittorrent VPN automation (currently media-vm)
- `backup_clients` → separate group for restic backups (includes `proxmox_nodes`, `vms_lxcs`, `orchestrator`, `raspberry_pis`, `workstations`, `arch_hosts`)
- `retired_hosts` → stale/offline inventory records retained for reference; these hosts are not children of `managed_hosts` and must not be targeted by normal convergence.

VMs and LXCs are split so VMs get `qemu-guest-agent` while LXCs don't need it.

### Variable Precedence

Variables merge from multiple sources (highest to lowest precedence):
1. Files under `inventory/host_vars/<hostname>/` - per-host overrides, split by concern when more than one domain is configured
2. Group-specific files in `inventory/group_vars/<group>/`
3. `inventory/group_vars/all/` - global defaults

**Important**: All group_vars and host_vars are under `inventory/`, not at the project root. This is Ansible's recommended structure for inventory-based configurations.

Encrypted secrets go in `vault.yml` files alongside the relevant variable files.

### Playbooks vs Roles

This repo uses **flat playbooks with imported tasks** rather than formal Ansible roles. Reusable task files live in `tasks/` and are imported with `import_tasks`.

### Multi-Platform Pattern

Playbooks detect OS via `ansible_facts.os_family` and conditionally execute platform-specific blocks:
- Debian/Ubuntu: apt package manager
- Arch: pacman
- macOS: homebrew (brew/casks)

Package lists follow naming convention: `packages_linux_common`, `packages_debian_extra`, `packages_<group>_extra`, `packages_host_extra`. Cross-platform groups split packages by OS: `packages_arch_workstations_extra`, `packages_debian_workstations_extra` (in `group_vars/workstations/packages.yml`); `packages_debian_development_extra`, `packages_arch_development_extra` (in `group_vars/development/packages.yml`). Apps not in apt repos (Discord, LocalSend) are installed via Flatpak on Debian workstations using `flatpak_workstations` variable; Arch gets them natively via pacman. `tealdeer` (the `tldr` command) is in `packages_linux_common` for all Linux hosts; macOS uses the Homebrew formula `tldr` in `packages_macos_common`.

**APT Release Pin**: Opt-in via `apt_pin_release` variable in host_vars (e.g., `apt_pin_release: bookworm`). Pins both the release and its `-security` companion to priority 900, preventing accidental major version upgrades while allowing normal security patches. Currently used by freepbx-vm to stay on Debian 12.

### TS440 Storage Architecture

TS440 is the primary NAS server (currently the sole `nas_server` group member). Key components:

**ZFS Pool**: 2x 8TB mirror at `/srv/nas-zfs` (~7.3TB usable). Keep under 80% capacity. ARC max set to 4GB (in `group_vars/nas_server/zfs.yml`) — bumped from 1GB after ts440 RAM upgrade to 32GB on 2026-05-12, then trimmed as VM footprint grew on ts440. media-vm has 10GB RAM for 20+ containers including GPU-accelerated Immich ML. Proxmox nodes use `vm.swappiness=10` to avoid swapping QEMU guest RAM too eagerly. Balloon disabled on media-vm due to GPU passthrough.

**Archive Dataset**: `nas_zfs/archive` at `/srv/nas-zfs/archive` for ISOs and general-purpose archival storage. Shared via VirtioFS to media-vm (read-write, mounted at `/srv/archive`, mapped as `/archive` in the qBittorrent container) and nextcloud-vm (read-only, at `/srv/external/archive` for Nextcloud External Storage). qBittorrent's `isos` category saves to `/archive/isos` with per-torrent subdirectory overrides (e.g., `/archive/isos/linux/kubuntu`).

**Media ZFS Pools**: Two 3TB single-drive pools (`media-01`, `media-02`) for plex/podcast overflow. Properties enforced by `playbooks/storage/zfs.yml` (compression=lz4, atime=off, recordsize=1M, acltype=posixacl). Sanoid snapshots: daily:7, weekly:4, monthly:3.

**MergerFS**: `/srv/media` aggregates 8 branches into a unified media pool: nas-01 (2TB SSD), nas-02 (2TB LUKS), nas_zfs, media-01 (3TB ZFS), media-02 (3TB ZFS), media-03 (2TB ext4 via USB-SATA), media-04 (2TB ext4 via USB-SATA, ex-PBS drive), media-05 (2TB ext4 via USB, ex-Xbox WD My Passport). Create policy: `epmfs` (existing path most free space) — keeps files in the same directory on the same branch, which is critical for Sonarr/Radarr hardlinks. Falls back to mfs when no existing path found. Branches and options defined in `group_vars/nas_server/mergerfs.yml`. Boot ordering uses `After=` directives only — `Requires=` and `RequiresMountsFor=` caused dependency failures with the mixed ZFS/fstab setup.

Do not remove, disable, exclude, remount around, or otherwise take a mergerfs branch out of the active media pool without explicit user approval for that exact action. First state the downstream impact: Plex library items on that branch may disappear, Sonarr/Radarr may report missing media, and automation may redownload or duplicate releases. Any approved branch-removal plan must include media-app pause/read-only safeguards or another explicit mitigation before changing the pool.

**media-03 (USB-SATA)**: 2TB Hitachi HDD connected via USB-SATA adapter, formatted ext4 (not ZFS — USB disconnects would fault a ZFS pool). Powered by UPS via power strip. Mount managed in `group_vars/nas_server/mounts.yml` with `nofail` so ts440 boots even if the drive is disconnected.

**media-04 (USB-SATA)**: 2TB ext4 drive added via USB-SATA adapter — the former PBS drive from pve-herc, repurposed for additional media storage. Same nofail pattern as media-03.

**media-05 (USB My Passport)**: 2TB WD My Passport (WD20NMVW-11EDZS6, ex-Xbox One game drive) added 2026-05-12 via USB. Integrated USB-on-PCB, not shuckable. SMART clean (0 reallocated/pending/UDMA-CRC). Same `nofail`/`x-systemd.device-timeout=60s` pattern. Added to mergerfs to drain nas_zfs/media (which had filled to 96% from non-media pool consumers); first balance moved 1.4 TiB across 858 files, freed 750 GiB on nas_zfs, ended at 4.9% spread.

**MergerFS Recovery (auto-remount + watchdog + media-app refresh)**: Deployed by `playbooks/storage/mergerfs-recovery.yml`. Three layers handle USB-SATA branch disconnects automatically so users don't see "missing files" in Plex:

1. **udev auto-remount** (`/etc/udev/rules.d/99-mergerfs-remount.rules`) — when a known UUID re-attaches, systemd-mounts the corresponding fstab unit within seconds. Configured per-branch via `mergerfs_recovery_branches` in `group_vars/nas_server/mergerfs-recovery.yml`.
2. **Mount watchdog** (`mergerfs-mount-watchdog.timer`, every 60s) — backstop that checks every protected branch via `findmnt`. If missing, attempts `systemctl start <mount-unit>`. After 3 consecutive failures (~3 min), sends a loud Apprise alert (`push,dbc`). State in `/var/lib/mergerfs-mount-watchdog/`. 6-hour alert dedup so it doesn't spam.
3. **Recovery hook** (`/usr/local/sbin/mergerfs-branch-recovered <name>`) — called by both udev and watchdog after a successful remount. Refreshes Plex (`/library/sections/all/refresh`) on media-vm and Sonarr/Radarr (`RescanSeries` / `RescanMovie`) on docker-vm. Bazarr auto-follows. Sends a quiet Apprise notification (`push-quiet,dbc`) with per-API result. ts440 reaches these services directly over Tailscale.

API tokens live in `inventory/group_vars/nas_server/vault.yml` (encrypted): `vault_media_api_plex_token`, `vault_media_api_sonarr_key`, `vault_media_api_radarr_key`. See `vault.yml.example` for how to obtain them. Opt-out per host with `mergerfs_recovery_enabled: false`.

This addresses the recurring USB-SATA disconnect class of failure (see `~/.codex/memories/` for retained diagnostic memory and runbooks) and the hardware swap-test runbook to identify the actual bad component.

**mergerfs-balance**: Balances files across mergerfs branches by moving from the fullest to the emptiest. Default path excludes in `/etc/mergerfs-balance.conf` (deployed by `playbooks/storage/mergerfs.yml` from `mergerfs_balance_exclude_paths` variable) protect irreplaceable data on mirrored nas_zfs (photos, archive, books) from being moved to single-drive pools. CLI `-E` flags are merged with config excludes. `--evacuate <branch>` drains a single branch to the least-used eligible destination branches before planned removal or reformat; dry-run first. Overnight balance jobs are now queued through `nightly-media-maintenance balance add ...` and run under `playbooks/media/nightly-media-maintenance.yml`; balance jobs own the whole midnight-7 AM window, skip Profilarr for that night, record state under `/var/lib/nightly-media-maintenance/`, use rsync partial files for next-window resume, and can pause/resume docker-vm `media-stack` while leaving Plex on media-vm up.

**Incomplete Downloads**: The Lacie SSD (`/srv/nas-01`) has a downloads directory **outside** the mergerfs branch tree, bind-mounted to `/srv/media-downloads` (defined in `group_vars/nas_server/mounts.yml`). This abstracts the underlying drive — to move downloads to a different SSD, just update `mounts.yml`. docker-vm mounts it over NFS as `/srv/incomplete_downloads`, while media-vm's old VirtioFS mount is disabled with the migrated media automation. The NFS export manages writable temp roots for qBittorrent and SABnzbd under the historical `/srv/media-downloads/incomplete/` layout (`incomplete/torrents`, `incomplete/torrents/tv-sonarr`, `incomplete/torrents/sonarr`, `incomplete/torrents/radarr`, and `incomplete/usenet`) as UID/GID 1000; if qBittorrent logs `mkdir ... Permission denied` or `missing files` under `/incomplete`, check these NAS-side directory owners and the docker-vm compose bind paths first.

**VirtioFS**: media-vm and nextcloud-vm access storage via VirtioFS (not NFS). Config in `host_vars/ts440/virtiofs.yml` (host side) and `host_vars/<vm>/virtiofs.yml` (guest side). All mounts use `cache=never` to prevent virtiofsd from consuming 5GB+ per mount on the host. Guest page cache still works, so streaming performance is unaffected.

**VirtioFS ACL Limitation**: VirtioFS does **not** pass through POSIX ACLs to guests. Files must have adequate **base permissions** (`chmod`) — ACLs set via `setfacl` on the host are invisible inside VMs. ZFS ACLs are managed by `playbooks/storage/zfs.yml`; normal runs set dataset-root ACLs and default ACLs for new files. Existing-tree recursive ACL repair is intentionally opt-in with `zfs_acl_recursive_repair: true` because it can walk large datasets.

**Config Storage**: Application configs are stored locally at `/opt/` on each VM (not NFS). This eliminates NFS boot dependencies and improves performance. Configs are backed up hourly to ts440 ZFS via `local-restic.yml`.

**Bind Mounts**: `/srv/plex-library` is bind-mounted from `/srv/media/plex` via fstab with `x-systemd.requires-mounts-for=/srv/media`.

**NFS Configuration Warnings**:
- Do NOT use `bind_source` in `group_vars/nas_server/nfs.yml` for paths already under the pseudo-root (`/srv`). It creates circular bind mounts that mask ZFS child datasets.
- The `/srv/nas-zfs` export uses `crossmnt` to traverse ZFS child datasets. Clients show multiple NFS mounts but they work as a unified tree.

### Samba/SMB Shares (ts440)

Managed by `playbooks/storage/samba.yml`, which runs on any `linux_hosts` host with `smb_shares` defined — currently ts440 (nas_server) and pve-herc. Uses `@smbusers` group for authentication and fruit VFS module (`catia fruit streams_xattr`) for macOS compatibility and Time Machine support. Avahi mDNS advertisement runs on each Samba host.

**ts440 shares**: NAS-ZFS, Configs, Backups, NAS-01, NAS-02 — defined in `group_vars/nas_server/samba.yml`.

**pve-herc shares**: Time Machine (`/srv/pbs-data/timemachine` on the 1TB PBS drive) — defined in `host_vars/pve-herc/samba.yml`. Active macOS Time Machine destination. SMB port 445 allowed from tailscale0 in pve-herc's firewall.

**Discovery over Tailscale**: Time Machine discovery works via SMB's AAPL extensions, NOT mDNS. Connect: `smb://100.97.139.95/Time Machine` (pve-herc Tailscale IP).

### Docker Container Management

Docker Compose stacks are managed via the `docker-stacks.yml` playbook. Services are split between dedicated VMs and explicitly opted-in workstation/controller hosts:
- **docker-vm (VM 110 on pve-m70q)**: Infrastructure services plus the Sonarr/Radarr download automation `media-stack`
- **nextcloud-vm (VM 101 on ts440)**: Nextcloud AIO with VirtioFS storage
- **media-vm (VM 100 on ts440)**: Plex-side media services; Plex stays here while Sonarr/Radarr/download automation runs on `docker-vm`
- **jn-t14s-lin (Kubuntu workstation/controller)**: OpenClaw support services such as the local Qdrant vector store

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

**Portainer CE** (multi-host): Central Docker management UI at `portainer.jnalley.me`. Manages docker-vm locally via socket; media-vm and nextcloud-vm connect via Portainer Edge Agents (`portainer/agent:latest` with `EDGE=1`). Edge Agents connect outbound to Portainer — no inbound ports needed on remote hosts. Agent compose files at `/opt/portainer-agent/` where enabled, with per-environment edge keys from the Portainer API. Admin credentials in Portainer's local database (not vault-managed).

**Dispatcharr** (disabled): HDHomeRun emulator for free IPTV in Plex. Commented out in `docker.yml` — free M3U playlists had too many dead streams. Compose file and data preserved at `/opt/dispatcharr/` on docker-vm. Uncomment in `docker.yml` and `templates/docker/Caddyfile.j2` to re-enable. HDHR tuner URL for Plex: `http://100.108.254.100:9191/hdhr` (note the `/hdhr` path — not root).

**Removed services** (disabled 2026-04-13, compose files and data preserved at `/opt/` on docker-vm for easy re-enable): Uptime Kuma (`status.jnalley.me`), Homepage (`home.jnalley.me`), Gitea (`git.jnalley.me`). Commented out in `docker.yml` and `templates/docker/Caddyfile.j2`.

#### nextcloud-vm (VM 101 on ts440)

Nextcloud AIO with VirtioFS storage access (mounts in `host_vars/nextcloud-vm/virtiofs.yml`). Public via Cloudflare Tunnel at `nextcloud.jnalley.me`. Email via iCloud SMTP (same account as smartmontools alerts; credentials in vault). Stacks: Nextcloud AIO, Diun. VM 101 uses Proxmox CPU model `host`, managed by `playbooks/proxmox/proxmox-vm-hardware.yml`, so fulltextsearch receives AVX/AVX2/FMA CPU flags. CPU model changes require a Proxmox-level VM stop/start, not just a guest reboot.

#### media-vm (VM 100 on ts440)

Primary media VM (10GB RAM, 4 cores, 200GB disk, Quadro P2200 GPU passthrough). Stacks in `host_vars/media-vm/docker.yml`. GPU shared between Plex (NVENC transcoding) and Immich (CUDA ML inference).

**Critical**: Plex stays on media-vm and reads `/srv/plex-library` locally through the ts440 storage path. The migrated Sonarr/Radarr/download automation now runs on docker-vm in the `/opt/media-stack` compose project. Those containers must keep one shared in-container parent path (`/data`) backed by docker-vm's single NFS parent mount (`/srv/media/plex:/data`), so downloads and final libraries remain on one visible filesystem for hardlinks. Do not split container mounts back into separate `/downloads`, `/movies`, `/tv`, or per-library mounts. Hardlinks were verified after migration with a real `ln` test across `/data/downloads/complete` and `/data/Anime` from inside the Sonarr container and on the ts440 backing branch.

**Plex appliance operations**: Bedroom Plex is the `jn-t14s-lin` / T14s HDMI appliance; living room Plex is `mercury`. For "skip the current episode on Bedroom Plex", HDMI login-screen/black-video incidents, or other appliance operator actions, start with `docs/plex-appliance-operations.md` before rediscovering service names, display ownership rules, or editing `/var/lib/plex-appliance/shuffle-state.json`.

**Stream relay**: `playbooks/media/stream-relay.yml` deploys `stream-relay.service`, which receives OBS SRT on UDP 9000, encodes video once with the Quadro's `h264_nvenc`, copies OBS's incoming AAC audio tracks, and fans the encoded feed out locally over MPEG-TS/TCP to `stream-relay-output@<platform>.service` workers that push configured RTMP platforms. media-vm's LAN IP is `192.168.1.136`, managed as static netplan by `playbooks/network/network-recovery.yml`. Gaming PC OBS track 1 is the full live mix with Apple Music; track 2 is the clean mix without Apple Music. Twitch uses the FFmpeg Enhanced FLV/RTMP output path available from Ubuntu 26.04's FFmpeg 8.x so it can receive Track 1 for live playback and confirmed clean Track 2 for Twitch VODs; YouTube maps track 2 only with `aresample=async=1:first_pts=0` to give YouTube fresh 48 kHz audio timestamps; local relay VOD recording also maps track 2 only. Ubuntu 24.04's FFmpeg 6.1 FLV muxer rejects multiple audio streams, so do not deploy Twitch multitrack relay there. media-vm keeps Secure Boot enabled; keep `nvidia-dkms-580` absent so the Quadro uses Ubuntu's Canonical-signed `linux-modules-nvidia-580-generic` module. The relay intentionally avoids FFmpeg `nobuffer`/`low_delay` flags because the SRT path already has explicit latency and overly aggressive buffering caused audible artifacts in live testing. The same playbook also deploys `stream-relay-vertical.service`, a disabled-by-default Aitum Vertical RTMP ingest on TCP 1936 for a standalone YouTube vertical/Shorts stream. These services use the live-only root-readable `/etc/stream-relay/stream-relay.env` with platform stream keys; never commit stream keys. With the current TCP fanout, a platform worker that disconnects after latching usually needs a full landscape relay restart, not an output-only restart. The landscape relay binds to media-vm's LAN IP and firewall access is through the Proxmox datacenter `streaming-pc` IP set, which includes the gaming PC's LAN IP; Windows also needs a persistent host route for `192.168.1.136/32` through Ethernet because Tailscale advertises `192.168.1.0/24`. Landscape VOD recording discards tiny header-only fragments, salvages stale readable incoming files through `stream-vod-mover`, and alerts only when real files hit the failed queue or stay stuck. The operator-facing Twitch/YouTube/TikTok/Mac OBS/Aitum/SleepyChat runbook is `docs/streaming-runbook.md`; start there before changing or troubleshooting the streaming setup. Hands-off streaming automation has two health layers: `stream-relay-health.timer` on media-vm for local Apprise/DBC alerts, and Astra's live OpenClaw heartbeat file `/home/johnny/.openclaw/workspace/HEARTBEAT.md` on the OpenClaw host for external checks. Do not say Astra is wired unless that live heartbeat file contains the stream relay/VOD section and the OpenClaw host can run `ssh dbc@100.66.6.113 '/usr/local/sbin/stream-relay-health --no-alert'` successfully.

**Immich**: Photo/video management at `photos.jnalley.me`. ML container capped at `mem_limit: 3g` to prevent OOM-freezing the VM. External library (`/srv/untitled`) is auto-locked by `immich_folder_album_creator` every 6 hours.

**Recyclarr / Profilarr**: Recyclarr is disabled and removed from the active docker-vm media-stack compose service list; do not rely on it for future Sonarr/Radarr policy sync. Profilarr is the managed stack at `/opt/profilarr` on docker-vm for profile/CF evaluation and proactive upgrade searches; native Profilarr scheduled Arr upgrades should stay disabled. Active request/media defaults use the promoted `*-efficient` profiles, and Seerr's Arr endpoints should be docker-vm compose DNS (`sonarr:8989`, `radarr:7878`), not the old media-vm Tailscale IP. Balanced profiles are parking profiles only until they get the same efficient-policy treatment; no media or request defaults should point at them. Anime media belongs on `shows-anime-efficient` or `movies-anime-efficient`; English-original regular media belongs on `shows-regular-efficient` or `movies-regular-efficient`; non-English non-anime media that should prefer original-language+English audio belongs on `shows-regular-dual-audio-efficient` or `movies-regular-dual-audio-efficient`. The dual-audio regular profiles are created by `scripts/media-release/arr_regular_dual_audio_profiles.py`, and `scripts/media-release/arr_profile_classification.py` is the audit/repair helper for library-wide profile classification. Normal English-original regular media stays on the normal regular efficient profiles so unrelated multi-audio releases do not get preferred. `playbooks/media/nightly-media-maintenance.yml` is the owner for overnight proactive upgrades: it queues controlled hourly Profilarr upgrade cycles from midnight through 6 AM only when no balance job is pending for that night. The media release-selection policy is documented in `docs/media-release-policy.md`; update that document whenever changing Sonarr/Radarr quality profiles, custom-format scores, Profilarr assignments, Seerr Arr/profile defaults, local/manual CFs, recycle-bin behavior, proactive upgrade-search behavior, or grab regression monitoring. Before mutating live Sonarr/Radarr/Profilarr/Seerr release-selection state, take timestamped exports or app-native backups of the affected live configs unless the user explicitly waives backups for that operation. For anime policy changes, audit all existing profile CF scores before changing score bands, because the `+100000` dual-audio model makes old `-10000` penalties too small for hard rejects and too large for soft avoids.

**Anime policy checks**: `scripts/media-release/sonarr_release_expectation_check.py` and `scripts/media-release/radarr_release_expectation_check.py` are the read-only live checks for the active `shows-anime-efficient` and `movies-anime-efficient` profiles. Run them on `docker-vm` after anime release-policy changes to verify DA/x265 scores, native quality grouping, quality-rank CFs, rename-format preservation of audio languages/video codec, DA/x265 title-side matching, profile assignment counts, and score math such as `1080p DA > 720p DA + x265 + top tier` and `lowest DA > strongest single-tier non-DA`. Radarr's checker also verifies `x265 (HD)` excludes 2160p.

**Profilarr candidate checks**: `scripts/media-release/arr_stage_profilarr_test_profiles.py` snapshots live Sonarr/Radarr release-policy state under `/opt/media-stack/release-policy-snapshots/` and creates/refreshed unassigned Profilarr test profiles from the current efficient policy. `scripts/media-release/profilarr_state_audit.py` checks linked Profilarr databases, upgrade configs, filters, queued/running scheduler jobs, and recent upgrade errors. `scripts/media-release/profilarr_disable_upgrade_jobs.py` disables Profilarr's scheduled Arr upgrade configs and cancels queued scheduled `arr.upgrade` jobs with a SQLite backup; it does not disable Profilarr database auto-pull/sync. `scripts/media-release/profilarr_sonarr_upgrade_strategy.py` updates supported stored Sonarr upgrade-filter settings with a SQLite backup and must not be used to patch Profilarr application code; current Sonarr selector is `random` because Profilarr normalizes Sonarr series scores to `0`, making `lowest_score` ineffective for current episode CF rank. `scripts/media-release/profilarr_candidate_audit.py` materializes linked PCD repositories in memory and compares candidate CF/profile material with live Arr names. `scripts/media-release/profilarr_selective_cf_import.py` is the controlled Profilarr-to-Arr bridge for curated `Dumpstarr ...` formats. `scripts/media-release/profilarr_bounded_tier_import.py` is the current Dictionarry release-tier bridge for future test profiles, and `scripts/media-release/arr_profile_math_audit.py` verifies the active efficient score bands, service tie-breakers, source ordering, legacy-tier zeroing, and CF limits. `scripts/media-release/arr_profile_assignment_check.py` verifies no Sonarr/Radarr media or Seerr request default uses balanced/test/old profiles; `scripts/media-release/arr_profile_classification.py --no-backup` verifies the stronger anime/regular/non-English classification expectation. `scripts/media-release/seerr_arr_endpoint_update.py` verifies or fixes Seerr Arr endpoints/defaults after migrations. Profilarr can keep pulling upstream databases, but copied Arr CFs update only when these importers are rerun; do not import upstream full profiles or stock x265 penalties unless the user explicitly changes the policy. Use these before assigning media to a Profilarr-derived test profile or syncing candidate CFs.

**Arr queue regression check**: `sonarr-transaction-monitor.timer` on docker-vm records Sonarr history, queue snapshots, and Sonarr/Radarr storage snapshots to `/var/log/sonarr-transaction-monitor/events.jsonl` for later release-policy audits; the log is rotated daily by the same playbook and must not store raw indexer/API URLs or API keys. It is managed by `playbooks/media/sonarr-transaction-monitor.yml` and should stay enabled while Profilarr upgrade searches are active. `scripts/media-release/sonarr_transaction_audit.py --hours 24 --limit 25` is the compact report over that log plus the live queue, including storage deltas for checking whether x265-focused upgrade passes are shrinking the libraries. `scripts/media-release/sonarr_grab_forensics.py` is the first-line read-only classifier for queued Sonarr grabs: it groups queue rows by download, compares queued vs current custom-format scores, and flags likely payload score loss, pack collateral/mapping issues, stalled/warning downloads, and active valid upgrades. `scripts/media-release/radarr_grab_forensics.py` is the matching classifier for Radarr queue items and also parses Radarr import-rejection score messages when current movie-file scores are not exposed in the queue payload. Run the relevant forensic helper before deleting anything so repeated non-better grabs are fixed at the cause instead of cleaned up after bandwidth is spent. Manual cleanup should use `--remove-current-better --safe-groups-only --remove-from-client` so mixed packs with any still-valid rows are skipped, and the helper writes a queue snapshot under `/opt/media-stack/arr-policy-backups/`; blocklisting stays false unless explicitly requested. `scripts/media-release/sonarr_grab_diagnostics.py` compares queued Sonarr downloads against current imported episode files, and `scripts/media-release/sonarr_series_audit.py <series>` is the read-only per-series state check for monitoring, season/file/missing counts, queue items, recent history, and active/recent commands.

**Arr live rollback backups**: Bulky one-off Arr rollback artifacts must not live on docker-vm root. `/opt/media-stack/arr-policy-backups` is a compatibility path that should point at `/srv/live-rollbacks/docker-vm/arr-policy`, backed by ts440's Sanoid-managed `nas_zfs/backups/live-rollbacks` dataset. Use `scripts/storage/live-rollback-backup` / `/usr/local/sbin/live-rollback-backup` for new one-off rollback copies so existing Sanoid snapshot retention owns cleanup.

**Media stack health**: `media-stack-health.timer` on docker-vm runs every 5 minutes and validates the migrated media automation end to end: docker-vm NFS mounts, visible library directories, Sonarr/Radarr/Prowlarr/Bazarr/SABnzbd/qBittorrent/Byparr/Profilarr containers, local HTTP endpoints, qBittorrent forwarded-port sync, an in-container hardlink test from `/data/downloads/complete` to `/data/Anime`, and recent qBittorrent Sonarr/Radarr import history for definite copied imports. The real import audit is a warning by default because mergerfs branch placement can still copy some imports even when the single parent NFS mount is correct; treat `WARNINGS:` as something to track and triage, not as proof the migration failed. It is managed by `playbooks/media/media-stack-health.yml`. Astra's live OpenClaw heartbeat should check the cached sentinel status from outside the VM with `ssh dbc@100.108.254.100 'sudo -n /usr/local/sbin/media-stack-health --status'`, so heartbeat reads do not start fresh NFS/mergerfs-touching probes. Do not say Astra is wired unless that live heartbeat section exists in `/home/johnny/.openclaw/workspace/HEARTBEAT.md` and the SSH command succeeds from the current OpenClaw host. Operator-facing heartbeat documentation is `docs/openclaw-heartbeats.md`.

**Release metadata stamper**: `playbooks/media/media-release-stamper.yml` deploys SABnzbd and qBittorrent post-download stampers that preserve grab-time evidence before Sonarr/Radarr import. qBittorrent renames payload files through its Web API to keep seeding state intact, with bounded retry/backoff configured in the deployed env; for obvious single-file video torrents, the qBit stamper uses torrent metadata directly instead of calling the qBit file-list endpoint, which can hang. DA evidence is stamped as language-combo tags such as `[JA+EN]`, `[KO+EN]`, or `[JA+KO+EN]`, per file only when audio metadata shows English plus the configured original language; qBittorrent can optionally get that original language from Sonarr/Radarr by torrent hash/download ID, and SABnzbd can optionally get it by release/job title. Arr lookup must stay bounded and non-fatal; fallback default is `jpn`, so `eng+kor` does not qualify when context is unavailable, and English-original context must not emit `[EN+EN]`. `[x265]` is stamped per file only after the payload itself contains HEVC markers or MKV video-track CodecID evidence. Platform/source tags and release-group suffixes may be copied from the parent release/job/torrent title to preserve release-context custom formats at import, but generic quality/resolution/source labels are not copied. If Sonarr context is available and a TV payload basename has an episode token but does not already contain the canonical series title, the stamper may rewrite the visible title prefix to the canonical series title while preserving a leading release-group tag. Existing-tag checks must use the payload basename, not the parent torrent directory. Stamper event logs live under the qBittorrent and SABnzbd script directories and are summarized by `scripts/media-release/sonarr_transaction_audit.py`; zero-renames can be valid when payload names already contain the needed evidence. Stamper env files must remain readable by the media containers' UID/GID `1000` without exposing them world-readable. Document behavior changes in `docs/media-release-policy.md`.

**Tdarr** (disabled 2026-04-13): Media transcoding service. Commented out in `/opt/media-stack/docker-compose.yml` and `templates/docker/Caddyfile.j2`. Compose config and `/opt/media-stack/tdarr/` data preserved for easy re-enable.

#### Torrent Fallback (Gluetun + qBittorrent)

Torrents are used as a fallback when Usenet doesn't have a release (e.g., older anime dual audio). All torrent traffic is routed through ProtonVPN.

**Architecture:**
```
Prowlarr → Nyaa.si (anime indexer)
    ↓
Sonarr/Radarr → qBittorrent (priority 2) → Gluetun (VPN tunnel)
             → SABnzbd (priority 1, preferred)
```

qBittorrent uses `network_mode: "service:gluetun"`, so all traffic goes through Gluetun's network namespace. Gluetun's built-in kill switch blocks all traffic when VPN is down. **Important**: qBittorrent's Disk I/O Type must be set to **POSIX-compliant** (not mmap) for VirtioFS compatibility. qBittorrent WebUI is on port **8085** (not 8080).

**VPN Protocol**: WireGuard to ProtonVPN Netherlands P2P servers (`SERVER_COUNTRIES=Netherlands`). `WIREGUARD_MTU=1420` is required — Gluetun has an MTU discovery bug that leaves tun0 at 1500 with no MSS clamping, causing TCP fragmentation and throughput loss. WireGuard achieves ~148 Mbits/sec through the tunnel (vs ~71 Mbits/sec with OpenVPN).

**Known Bad Server**: ProtonVPN node-nl-215 (103.69.224.3) has poor port forwarding — peers can't connect, upload stays near zero. node-nl-309 (169.150.196.67) works well. Server pinning is not used (too fragile); the gluetun-watchdog's port forwarding monitor should detect and force-recreate when a bad server is hit.

**qBittorrent Tuning**: `max_active_downloads: 5` (reduced from 10 — active downloads starve uploads of libtorrent I/O resources). `max_active_uploads: 200`, `max_uploads: 200` (global upload slots). `dont_count_slow_torrents: true` lets stalled 0-seed torrents bypass the active download limit so they don't block well-seeded torrents. Queue uses FIFO ordering (by add time, not by seed availability). Seeding upload speed is primarily limited by over-seeded swarms (~17:1 seed:leech ratio on anime torrents), not connection or settings.

**Automatic Port Sync** (Ansible-managed by `playbooks/docker/gluetun-watchdog.yml`): ProtonVPN assigns dynamic forwarded ports that change on reconnect. A systemd-based automation keeps qBittorrent's listening port in sync:

1. **Gluetun** writes the forwarded port to `/opt/media-stack/gluetun/forwarded_port` via `VPN_PORT_FORWARDING_UP_COMMAND`
2. **systemd path unit** (`qbit-port-sync.path`) watches that file for changes
3. **Sync script** (`/usr/local/bin/qbit-port-sync`) updates qBittorrent via API:
   - Reads Gluetun's port from file
   - Connects to qBittorrent API (with retries)
   - If API unreachable (Gluetun restart broke qBittorrent's network), restarts qBittorrent via docker compose
   - Updates listening port via API so qBittorrent saves it correctly

**2026-05-22 repair note**: `qbit-port-sync.path` is enabled on docker-vm. qBittorrent 5.2.0 returns HTTP 204 on successful API login, so the local script must treat either the legacy `Ok.` body or HTTP 204 as success. If qBittorrent shows `Recv failure: Connection reset by peer` on port 8085 after a restart, check `/opt/media-stack/qbittorrent/qBittorrent/lockfile`; moving that stale lockfile aside and recreating qBittorrent recovered the service during the 2026-05-22 incident. The port-sync script's recreate path now stops qBittorrent, moves a stale lockfile aside, and starts qBittorrent again instead of using a plain restart.

#### Docker Auto-Update

Systemd timer on each Docker VM that auto-pulls/builds and recreates selected containers every 6 hours. Deployed via `playbooks/docker/docker-auto-update.yml`. Containers opt-in via flags in `host_vars/<hostname>/docker.yml`:

```yaml
docker_stacks:
  - name: caddy
    path: /opt/caddy
    build: true
    auto_update: true              # Entire stack auto-updates
  - name: media-stack
    path: /opt/media-stack
    build: false
    auto_update_services:          # Only specific services
      - gluetun
```

**Currently auto-updated**: Caddy, Seerr, Loki-Grafana, and Gluetun (docker-vm), LazyLibrarian (media-vm), Diun (all 3 VMs). Change by editing `docker.yml` and re-running the playbook.

**How it works**: The script (`/usr/local/sbin/docker-auto-update`) is templated by Ansible with the auto-update stack list baked in. For each stack, it pulls/builds, runs `docker-stack-diff` to detect changes, and only recreates if images actually changed. Gluetun uses `--force-recreate` with dependent containers (qBittorrent) to clear the network namespace. Sends `push-quiet` Apprise notification summarizing updates. Timer runs at :30 past 00/06/12/18 with 30m random delay.

**Major version guard**: `docker-stack-diff --check-major` compares the `org.opencontainers.image.version` label on running vs pulled images. If the first numeric component differs (e.g., `7.x` → `8.x`), the update is blocked and a Time Sensitive Pushover notification is sent instead. The pulled image stays local for manual update when ready. A state file (`/var/lib/docker-auto-update/`) prevents repeat notifications for the same blocked version. Per-stack opt-out via `major_guard: false` in docker.yml. Safe defaults: missing/unparseable version labels allow the update (guard only blocks when confident).

**Configuration** (in `group_vars/docker_hosts/auto-update.yml`):
- `docker_auto_update_enabled` (default: `true`) — per-host opt-out
- `docker_auto_update_oncalendar` (default: `*-*-* 00/6:30:00`) — timer schedule
- `docker_auto_update_notify_tag` (default: `push-quiet`) — Apprise notification tag
- `docker_auto_update_major_guard` (default: `true`) — block major version bumps
- `docker_auto_update_major_notify_tag` (default: `push`) — louder tag for blocked updates

**Troubleshooting**: `journalctl -u docker-auto-update`, `systemctl list-timers docker-auto-update*`, manual trigger: `systemctl start docker-auto-update.service`.

#### Gluetun VPN Watchdog

Gluetun's internal VPN restart (`HEALTH_RESTART_VPN=on`) doesn't properly clean up tun0 routes, causing self-reinforcing crash loops where OpenVPN connects but traffic can't flow (`RTNETLINK answers: File exists`). The watchdog detects this and does a full `docker compose up -d --force-recreate` (not just `restart`) to destroy the container and its network namespace, clearing the stale routes. Dependent containers (qBittorrent) that share Gluetun's network namespace are recreated together.

**Why force-recreate**: `docker compose restart` keeps the same container and network namespace. Since qBittorrent shares Gluetun's namespace (`network_mode: "service:gluetun"`), the namespace stays alive even when Gluetun stops, preserving the stale routes. `--force-recreate` destroys the container entirely, creating a fresh namespace on startup. After 3 consecutive health failures (~3 minutes), it force-recreates Gluetun + dependent containers. Rate-limited to 5 restarts per hour.

**Port forwarding monitoring**: The watchdog reads Gluetun's internal port file (`/tmp/gluetun/forwarded_port` inside the container) to check port forwarding status. Gluetun clears this file when port forwarding fails. ProtonVPN's NAT-PMP port mapping can silently fail even while the VPN tunnel remains healthy. After 5 consecutive checks with no port (~5 minutes), the watchdog force-recreates Gluetun to get a fresh port assignment. Configurable via `gluetun_watchdog_max_portfwd_failures` (default: 5). Note: Gluetun's control server API (`/v1/portforward`) requires authentication as of commit `0c3e5d9` (2026-02-20), so the watchdog uses the file-based approach instead.

#### Notification Stack (Apprise + Pushover)

Centralized notification system using Apprise API (on docker-vm at `/opt/notifications/`) routing to Pushover and email.

**Architecture:**
```
PVE notifications (backup) ────┐
Diun (container updates) ──────┤
smartd (disk health) ──────────┤
apcupsd (UPS power) ───────────┤
auto-updates (weekly) ─────────┼──→ Apprise API ───→ Pushover "Computer Corner" app (infrastructure, Time Sensitive)
unattended-upgrades (daily) ───┤   (docker-vm)  ───→ Pushover "Computer Corner" app (infrastructure, silent/quiet)
network-watchdog (recovery) ───┤                ───→ Pushover "cc-media-feed" app (media, silent)
gluetun-watchdog (VPN) ────────┤                ───→ Email (iCloud SMTP)
docker-auto-update (6h) ───────┤                ───→ DBC alert receiver (OpenClaw host, triage + morning summary)
Sonarr/Radarr (grabs) ─────────┤
Seerr (requests) ──────────────┘

Sonarr/Radarr ──→ Discord (native connection, rich embeds with poster art)
```

**Apprise tags** control routing: `push` (Pushover infrastructure, Time Sensitive), `push-quiet` (Pushover infrastructure, silent), `email` (iCloud SMTP), `media-feed` (Pushover media, silent), `media-requests` (Seerr media requests, silent), `dbc` (DBC alert receiver on the OpenClaw host). The `dbc` tag is included alongside existing tags in all notification calls so DBC gets a copy of every alert. Services specify tags via `apprise_alert_tags` variable (default: `push,dbc` in `group_vars/all/vars.yml`). apcupsd supports per-service override via `apcupsd_alert_tags`. Combine tags like `push,email` for multi-target delivery.

**DBC alert receiver**: DBC (OpenClaw agent) receives a copy of all infrastructure alerts via `dbc=jsons://openclaw.jnalley.me/alerts` in the Apprise config. Alerts are stored in SQLite on the OpenClaw host and triaged: errors get an immediate ping in Discord #dbc-logs, routine alerts are batched into the morning summary. The receiver runs on port 18792, proxied through Caddy. Ansible-managed notifications include the `dbc` tag automatically via variables; Sonarr/Radarr/Seerr have `dbc` added manually to their Apprise tag fields in their web UIs.

**Why Pushover over ntfy**: ntfy's iOS app does not support per-topic notification control. Pushover allows true silent delivery via priority `-2` and per-app iOS settings. ntfy config preserved (commented out) in docker-compose.

**Apprise email URL gotcha**: When SMTP username contains `@`, use `?user=` query parameter format instead of URL path. Apprise's serialization loses `%40` encoding via API, causing auth failures.

Diun runs on all three Docker VMs (docker-vm, media-vm, nextcloud-vm) monitoring containers for image updates. Config templated by Ansible (`templates/docker/diun.yml.j2`) and deployed by `docker-auto-update.yml`. Schedule (`0 1/6 * * *` — 01:00, 07:00, 13:00, 19:00) is offset to run after the auto-update timer so already-updated containers don't trigger redundant alerts. Config vars in `group_vars/docker_hosts/diun.yml`. Sonarr/Radarr also send to Discord (native connection) for rich embeds with poster art.

#### Centralized Logging (Loki + Grafana + Alloy)

Centralized log aggregation using Grafana Loki on docker-vm with Alloy agents on all managed hosts.

**Architecture:**
```
All hosts (Alloy) ──→ Loki (docker-vm:3100) ←── Grafana (caddy-proxy)
                         │                            │
                    Tailscale push              grafana.jnalley.me
```

**Server** (docker-vm): Loki + Grafana Docker Compose stack at `/opt/loki-grafana/`. Loki stores logs with TSDB schema v13, 30-day retention, filesystem storage. Grafana auto-provisioned with Loki datasource. Grafana accessible at `grafana.jnalley.me` via Caddy (Tailscale only, not publicly exposed). Admin password in `host_vars/docker-vm/vault.yml`.

**Clients**: Alloy agent deployed to all `managed_hosts` by `playbooks/core/logging.yml`:
- **Linux**: systemd journal logs with relabeling (unit, transport, level labels). Alloy installed from Grafana APT repo (Debian) or AUR `alloy-bin` (Arch).
- **Docker hosts**: additionally scrape container logs via Docker socket (`discovery.docker`).
- **macOS**: tails `/var/log/system.log` via `loki.source.file`. Installed via Homebrew (`grafana-alloy`), runs as LaunchAgent.

**Variables** (in `group_vars/all/loki.yml`):
- `loki_url` — Loki endpoint (docker-vm Tailscale IP, port 3100)
- `alloy_enabled` (default: `true`) — per-host opt-out
- `alloy_journal_max_age` — how far back to read journal on first start

**Querying**: In Grafana, use LogQL: `{host="ts440"}`, `{host="media-vm", container="plex"}`, `{unit="docker.service"} |= "error"`.

#### Reverse Proxy (Caddy on docker-vm)

Caddy provides HTTPS for all internal services via Cloudflare DNS-01 challenge. The canonical sources are `templates/docker/Caddyfile.j2` for routes, `templates/docker/caddy.yml` for compose, and `templates/docker/caddy.Dockerfile` for the Cloudflare DNS build. `docker-stacks.yml --tags caddy` renders them under `/opt/caddy/`, validates the Caddyfile, and recreates the Caddy container when the Caddyfile changes. `/opt/caddy/.env` remains live-only because it contains the Cloudflare API token. docker-vm services are proxied by container name (`caddy-proxy` Docker network); media-vm services by Tailscale IP (`100.66.6.113`). Proxmox/PBS/PDM management UIs are proxied at `pve-ts440.jnalley.me`, `pve-alto.jnalley.me`, `pve-herc.jnalley.me`, `pve-m70q.jnalley.me`, `pbs.jnalley.me`, and `pdm.jnalley.me`. All services require Tailscale to access.

**Image Updates**: The playbook separates pull and update steps — it only runs `docker compose up -d` if images were actually updated (detected via "Pull complete" or "Downloaded newer" in pull output). This avoids unnecessary container restarts when images are already current. Pull has retry logic (3 attempts, 10s delay) to handle transient registry timeouts. Dangling images are pruned after each run. Between pull and update, `scripts/docker/docker-stack-diff` runs to report per-service image changes with version labels (`org.opencontainers.image.version`) when available, falling back to truncated image digests. The `up -d` output is also displayed, showing which specific containers were recreated vs. left running.

#### Cloudflare Tunnel (Public Access)

Cloudflare Tunnel (`cloudflared` on docker-vm) provides public access to Nextcloud (`nextcloud.jnalley.me` → `100.112.46.126:11000`) and Seerr (`requests.jnalley.me` → `seerr:5055`). No router ports exposed; home IP hidden. Geo-blocking restricts to US only (Cloudflare Security Rules: `(not ip.src.country in {"US"})` → Block). Managed via Cloudflare Zero Trust dashboard.

### Backup Architecture

Four-tier backup strategy:

- **Proxmox Backup Server (PBS)**: Hourly VM/CT snapshot backups via `proxmox-backup-server.yml`. pbs-lxc (CT 105 on pve-herc, Debian 13, 4 cores, 2GB RAM) with 1TB ext4 datastore at `/srv/pbs-data`. The same 1TB drive also hosts `/srv/pbs-data/timemachine/` for macOS Time Machine (served by Samba on pve-herc). Registered as `pbs-main` storage on all 4 Proxmox nodes. All guests backed up hourly except pbs-lxc itself (circular); uses `--all --exclude 105`. API token auth (`backup@pbs!ansible`, secret in `host_vars/pbs-lxc/vault.yml`). Daily prune job: 24h/7d/4w/3m. **Daily garbage collection** (frees disk space from pruned snapshots — without GC, orphaned chunks accumulate indefinitely). Web UI: `https://100.110.176.37:8007`. PBS dedup makes hourly backups viable — only changed blocks are stored after the initial full backup. Connectivity check runs at `:59` on all nodes (Play 4), logging to journald tag `pbs-check` for Loki.
- **Offsite (Backblaze B2)**: Daily via `restic.yml` at 00:00 UTC +30m random delay. Retention: 7d/4w/6m. ts440 backs up `/srv/nas-zfs` excluding replaceable media.
- **Local (ts440 ZFS)**: Hourly via `local-restic.yml`. Backs up configured local paths to `/srv/nas-zfs/backups/<hostname>/`. Retention: 24h/7d/4w/6m. Most hosts use SFTP over Tailscale SSH with a dedicated key in `group_vars/backup_clients/vault.yml`. Hosts without Tailscale SSH access can use a **restic REST server** on ts440 (port 8500) with append-only mode — no SSH, no shell, no filesystem browsing, and existing backups cannot be deleted. REST credentials live in host vault, htpasswd lives on ts440, and `--private-repos` ensures each user can only access their own repo directory. Append-only clients skip client-side retention and need server-side maintenance timers on ts440.
- **ZFS Snapshots (sanoid)**: Every 15 minutes via `zfs.yml`. Policies defined in `group_vars/nas_server/zfs.yml`. Property enforcement (`zfs set`) runs automatically to fix drift.

Enable local backups: set `local_restic_enabled: true` and `local_restic_backup_paths` in host_vars. Source env with `set -a` when accessing repos manually: `sudo bash -c 'set -a && source /etc/restic/local-backup.env && restic snapshots'`.

**PBS Notes**:
- LXC is **unprivileged** — the host-side datastore directory must be owned by UID 100000 (`chown 100000:100000 /srv/pbs-data` on pve-herc)
- PBS 4.x replaced per-datastore retention with prune jobs (`proxmox-backup-manager prune-job`)
- The enterprise repo is auto-added on install and must be removed (no subscription)
- Repo and GPG key use `ansible_distribution_release` for automatic Debian version detection
- PBS tokens use privilege separation — both user AND token ACLs must be set (intersection model)
- **GC is critical**: Prune jobs only remove snapshot metadata. Without daily GC, orphaned chunks fill the datastore. Config: `pbs_gc_schedule` in `host_vars/pbs-lxc/vars.yml`
- Config: `host_vars/pbs-lxc/vars.yml` (datastore name, retention, GC schedule, API user/token)
- Vzdump job config: `group_vars/proxmox_nodes/vars.yml` (`pbs_backup_schedule`, `pbs_backup_exclude`)
- **4 cores required** — pve-herc's AMD GX-415GA is a low-power 1.5GHz SOC. With 2 cores, simultaneous WireGuard+TLS connections from all 4 PVE nodes at `:00` caused intermittent TCP timeouts (first 2 succeed, 3rd/4th fail). 4 cores resolved this.

### Proxmox Notification Webhooks

PVE's notification system routes alerts via webhook to Apprise → Pushover. Deployed by `playbooks/proxmox/proxmox-notifications.yml`. Config is cluster-wide (pmxcfs) — playbook runs on one node with `run_once: true`.

**Webhook targets** (two, for severity-based routing):
- `apprise-infra` — warnings/errors → `push` tag (Time Sensitive)
- `apprise-infra-quiet` — info → `push-quiet` tag (silent)

**Matchers**:
- `pve-critical` — routes warning/error severity to `apprise-infra`
- `pve-info` — routes non-backup info to `apprise-infra-quiet` (filtered by `match-field regex:type=^(package-updates|fencing|replication)$`)
- `default-matcher` — disabled (built-in mail-to-root has no relay)

**Vzdump (backup) notifications**: Success notifications are suppressed (vzdump `info` events don't match any matcher). Backup **failures** (warning/error severity) still route to Pushover Time Sensitive via `pve-critical`. Check PBS UI or Loki for backup status. PVE's Rust regex engine doesn't support negative lookahead, so the filter uses a positive match on non-vzdump event types instead.

**Event types**: vzdump (backup success/failure), replication, fencing, package-updates. Body templates use PVE Handlebars syntax (`{{escape title}}`, `{{escape message}}`) and are base64-encoded in the pvesh API. Opt-out: set `pve_notifications_enabled: false` in host_vars.

### rclone Sync (OneDrive to Nextcloud)

One-way sync from UTD OneDrive to Nextcloud via `playbooks/backup-sync/rclone-sync.yml`. Runs on macbook-pro because UTD's Microsoft 365 tenant blocks third-party OAuth — OneDrive desktop app syncs locally, then rclone copies to Nextcloud WebDAV every 2 hours. Monitored via Uptime Kuma push monitor. rclone remote config is manual (not Ansible-managed) at `~/.config/rclone/rclone.conf`.

### Unattended-Upgrades (Daily Security Patches)

Deployed via `playbooks/core/unattended-upgrades.yml` to all `debian_hosts` (including workstations — security patches shouldn't wait). Complements the weekly `auto-updates.yml` full-upgrade (Sundays, staggered per-host).

**Proxmox update window**: Proxmox nodes run the weekly full-upgrade on a staggered schedule, but `group_vars/proxmox_nodes/vars.yml` sets `auto_updates_reboot_if_required: false`, so they notify on reboot-required instead of rebooting themselves. Per-host `auto_updates_oncalendar` overrides in host_vars with `auto_updates_randomized_delay_sec: "0"`: ts440 05:00 → pve-alto 05:20 → pve-herc 05:40 → pve-m70q 06:00. pve-m70q goes last because it hosts docker-vm and several control-plane guests. VMs/LXCs use `group_vars/vms_lxcs/vars.yml` to run after the Proxmox update window (`Sun *-*-* 07:00:00` + 30m random delay), so host updates do not interrupt guest dpkg transactions. Other Debian hosts use the default schedule from `group_vars/debian_hosts/packages.yml` (`Sun *-*-* 05:00:00` + 15m random delay).

**How it works**: Uses Debian/Ubuntu's native `unattended-upgrades` package with APT's built-in `apt-daily-upgrade.timer` (daily, randomized 12h window). Only applies security-origin patches — not general updates. A systemd drop-in (`/etc/systemd/system/apt-daily-upgrade.service.d/notify.conf`) hooks an `ExecStartPost` script that sends a silent Apprise notification (`push-quiet` tag) when patches are applied.

**Proxmox nodes**: Blacklist `pve-*`, `proxmox-*`, `ceph-*`, `corosync*`, `pve-kernel-*`, `pve-firmware`, `qemu-server`, `libpve-*` packages (defined in `group_vars/proxmox_nodes/vars.yml`) to avoid breaking cluster operations. Base Debian security patches still apply.

**Variables** (in `group_vars/debian_hosts/packages.yml`):
- `unattended_upgrades_enabled` (default: `true`) — per-host opt-out
- `unattended_upgrades_blacklist` (default: `[]`) — overridden for Proxmox nodes

### e1000e NIC Tuning

Three of four Proxmox nodes (ts440, pve-m70q, pve-alto) have Intel e1000e NICs (I217/I218/I219) prone to "Detected Hardware Unit Hang" errors where the TX descriptor ring gets stuck. The driver resets the NIC, which unregisters it from the bridge — dropping all connectivity until the network watchdog reattaches it.

**Mitigations** (`playbooks/network/e1000e-tuning.yml`):
- **EEE (Energy Efficient Ethernet)**: Disabled via udev rule. Low-power link negotiation stalls the TX ring. The old `modprobe e1000e EEE=0` parameter was removed from newer kernels and silently ignored.
- **TSO/GSO (TCP/Generic Segmentation Offload)**: Disabled via the same udev rule. Large segment offloads can wedge TX descriptors on these NICs.
- **ASPM (Active State Power Management)**: Already disabled kernel-wide via `pcie_aspm=off` boot parameter on ts440.

The udev rule (`/etc/udev/rules.d/99-e1000e-disable-eee-tso.rules`) fires on NIC add events, including after driver resets, so settings are re-applied automatically. pve-herc (Realtek r8169) is skipped.

### Network Recovery

Deployed via `playbooks/network/network-recovery.yml` to `linux_hosts:!workstations`.

**Network Watchdog** (`network-watchdog.timer`, every 60s):
- Optionally manages static netplan for fixed LAN service IPs, such as media-vm's `192.168.1.136` OBS/Plex address
- Ensures interfaces are UP (catches link flaps)
- On Proxmox: fixes bridge interfaces detached during router restarts or switch moves (e.g., `eno1`, VM firewall ports like `fwpr100p0`, or plain VM tap ports like `tap130i0` removed from `vmbr0`)
- After 3 gateway failures: restarts networking/DHCP
- After 5 Tailscale failures: restarts tailscaled
- After 5 DHCP recovery failures: reboots (only if router is reachable, to avoid boot loops)
- On recovery: sends Apprise notification, restarts Docker stacks, remounts NFS

**Tailscale Online Target** (`tailscale-online.target`): Activates only when Tailscale is connected (not just daemon running). Services like `docker-stacks.service` depend on this.

### Workstation Hosts

The old `jn-desktop` CachyOS install is retained in `retired_hosts` only because it has been offline long enough to break normal `site.yml` convergence. Do not add retired hosts back to active groups unless they are reachable and intentionally managed again.

**jn-t14s-lin** (Kubuntu): ThinkPad T14s laptop in `orchestrator`, `debian_hosts`, `workstations`, `docker_hosts`, `openclaw_hosts`, and `backup_clients`. Requires `ansible_become_flags: "-S"` in host vars due to sudo-rs (Ubuntu 25.10+ default). WiFi powersave disabled; optional ath11k resume hooks available in `host_vars/jn-t14s-lin/wifi.yml`. As the flat controller, it advertises `tag:orchestrators`, stays awake on AC power, and runs explicit Docker stacks from `host_vars/jn-t14s-lin/docker.yml`.

Workstations inherit `network_watchdog_enabled: false` and `auto_updates_enabled: false` from `group_vars/workstations/vars.yml`. Linux workstations still receive daily security patches via `unattended-upgrades`.

### Swap Configuration

Managed by `playbooks/core/swap.yml`. Opt-in via `swap_size_gb` in host_vars. Auto-detects root filesystem type via `findmnt`:
- **ZFS hosts** (Proxmox): Creates a zvol at `rpool/swap` (swap files don't work on ZFS — CoW creates holes that `swapon` rejects, even with `dd`)
- **Non-ZFS hosts**: Creates a swap file at `/swapfile`

Currently enabled on pve-m70q and pve-herc (8GB each). Pool name configurable via `swap_zfs_pool` (defaults to `rpool`).

## Key Files

Playbooks are imported via `site.yml` (with tags). Browse with: `ls playbooks/ tasks/ templates/ scripts/ bin/`. Each file has a descriptive header comment. Docker stacks and VirtioFS configs are defined in `host_vars/<hostname>/docker.yml` and `virtiofs.yml`.

**media-vm / docker-vm specific files**: stream relay remains Ansible-managed on media-vm (`/usr/local/sbin/stream-relay`, `/usr/local/sbin/stream-relay-output`, `stream-relay.service`, `stream-relay-output@.service`, `stream-relay-vertical-broker.service`). qBittorrent port sync is Ansible-managed on docker-vm by `playbooks/docker/gluetun-watchdog.yml` (`/usr/local/bin/qbit-port-sync`, `/etc/qbit-port-sync.env`, systemd path unit `qbit-port-sync.path`). Release metadata stamping is Ansible-managed on docker-vm by `playbooks/media/media-release-stamper.yml` (`/opt/media-stack/qbittorrent/scripts/qbit-release-stamper.py`, `/opt/media-stack/sabnzbd/scripts/sab-release-stamper.py`).

### Proxmox Firewall (Ansible-Managed)

Three-level firewall managed by `playbooks/proxmox/proxmox-firewall.yml`:
1. **Datacenter** (`cluster.fw`): IP sets and security groups — `group_vars/proxmox_nodes/firewall.yml`
2. **Node** (`host.fw`): Per-node rules — `host_vars/<node>/firewall.yml` under `pve_node_firewall`
3. **VM/CT** (`<vmid>.fw`): Per-VM rules — `host_vars/<node>/firewall.yml` under `pve_vm_firewalls`

Security model: default deny (`policy_in: DROP`) on all VMs. Caddy (docker-vm) is the only web entry point. SSH allowed from Tailscale. In VM rules, use `+dc/<ipset>` prefix to reference datacenter-level IP sets.

### Proxmox HA (disabled)

`pve-ha-lrm` and `pve-ha-crm` are stopped, disabled, and **masked** cluster-wide via `playbooks/proxmox/proxmox-ha.yml`. Driven by `pve_ha_enabled` in `group_vars/proxmox_nodes/vars.yml` (default `false`). HA had zero resources configured anyway, so its only effect was unnecessary watchdog/fencing risk during boot or transient cluster blips. To re-enable later: set `pve_ha_enabled: true` and re-run the playbook.

### Per-VM Storage Gate (Ansible-Managed)

A Proxmox hookscript refuses to start a VM/CT until that VM's declared host mountpoints are present, so VMs that depend on broken storage stay off (no stale VirtioFS handles, no Sonarr/Radarr "missing files" cascades) while unrelated VMs (e.g., docker-vm with no host storage deps) start normally.

- Hookscript binary: `templates/proxmox/wait-for-mounts.sh.j2` → `/var/lib/vz/snippets/wait-for-mounts.sh` on every Proxmox node
- Per-VM declarations: `host_vars/<vm>/storage.yml` with `vmid` and `required_host_mounts: [/srv/...]`
- Aggregated cluster-wide config: `/etc/pve/wait-for-mounts.json` (lives on pmxcfs, so it travels with VM migrations automatically)
- Wired per-VM via `qm set <vmid> --hookscript local:snippets/wait-for-mounts.sh`
- Playbook: `playbooks/storage/vm-storage-gate.yml`

To gate a new VM:
1. Add `host_vars/<vm>/storage.yml` with `vmid` + `required_host_mounts` list.
2. Run `ansible-playbook playbooks/storage/vm-storage-gate.yml`.
3. The next time that VM starts (auto or manual), the hookscript checks all required paths via `mountpoint -q` first. Missing → start aborted, Apprise `push,dbc` alert fired. All present → start proceeds.

Initial gates: `media-vm` → `[/srv/media, /srv/nas-zfs]`, `nextcloud-vm` → `[/srv/nas-zfs]`. `homebridge-lxc` and the dev/openclaw/docker-vm class have no host storage dependency and are unaffected.

USB drive timeout standard: all USB drives in `group_vars/nas_server/mounts.yml` use `noatime,nofail,x-systemd.device-timeout=60s` so a slightly slower cold enumeration (e.g., after a UPS swap) doesn't drop ts440 into emergency mode. The `/srv/nas-01` Lacie was previously at 5s; the gate above is the safety net for when timeouts are still exceeded.

### freepbx-vm (VM 130 on pve-herc)

FreePBX 17 PBX server (Asterisk 22, Debian 12 Bookworm). Provides a second phone number via VoIP.ms SIP trunk and Yealink SIP-T54W desk phone, with call forwarding to iPhone. Web GUI: `http://100.97.139.95/admin`. LAN IP: `192.168.1.241`, managed in `/etc/network/interfaces` by `playbooks/apps/freepbx.yml` from `templates/freepbx/interfaces.j2`. APT pinned to `bookworm` via `apt_pin_release` to prevent accidental Debian 13 upgrades. FreePBX/Asterisk packages are held (`apt-mark hold`) by the install script — module updates done through the web GUI. Sangoma Smart Firewall enabled with Tailscale CGNAT (`100.64.0.0/10`) trusted. Proxmox firewall rules: SIP (UDP 5060 from LAN + VoIP.ms), RTP (UDP 10000-20000), web GUI (TCP 80/443 Tailscale only), SSH. Config: `host_vars/freepbx-vm/` (vars.yml, packages.yml). Local restic backups: `/etc/asterisk`, `/var/lib/asterisk`, `/var/spool/asterisk`. `playbooks/apps/freepbx.yml` manages Asterisk open-file guardrails, Asterisk logrotate size caps, journald retention, and the static LAN interface config so the small root disk does not fill from PBX log storms or lose DHCP after bridge events.

### OpenClaw Host (jn-t14s-lin)

OpenClaw AI agent platform (Node.js gateway daemon). Provides a web UI and Discord channel for interacting with the agent fleet (DBC + Fleet of Stars: main, dubble, vega, antares, rigel) — primarily backed by GPT-5.5 via OpenAI Codex, with OpenRouter and Ollama Cloud fallbacks. It runs on the T14s controller/workstation, so treat its repo and host access as controller-adjacent rather than as the old isolated VM boundary. The former `openclaw-vm` inventory record is retained only in `retired_hosts`.

- **Web UI**: `https://openclaw.jnalley.me` (Tailscale only, via Caddy on docker-vm)
- **Gateway port**: 18789 (token auth, trustedProxies: docker-vm only)
- **Host**: `jn-t14s-lin` (Kubuntu workstation/controller)
- **Node.js**: 22 via NodeSource repo (OpenClaw requires >= 22)
- **Docker**: Installed for OpenClaw sandbox containers and Qdrant. In `docker_hosts` group — Qdrant is managed by `docker-stacks.yml`.
- **Gateway service**: Managed by OpenClaw itself via `openclaw gateway install` (user-level systemd unit)
- **Config**: `~/.openclaw/openclaw.json` and `~/.openclaw/.env` — created manually, backed up by restic (NOT templated by Ansible)
- **Astra heartbeat**: The active heartbeat prompt is `/home/johnny/.openclaw/workspace/HEARTBEAT.md` on the OpenClaw host. Treat it as live OpenClaw workspace content that Astra may edit; update it directly when changing heartbeat behavior and document the expectation in this repo. Do not create an OpenClaw cron when the right primitive is the heartbeat file. Heartbeat procedure details, including stream relay and Plex appliance verified-corruption checks, live in `docs/openclaw-heartbeats.md`.
- **Linting tools**: `ansible-lint`, `yamllint` in venv at `/opt/openclaw-venv/`
- **PATH safety**: Do not prepend `/opt/openclaw-venv/bin` to the controller login PATH. That venv can shadow system Ansible with newer `ansible-core`; under the Codex sandbox, Ansible 2.21's local RPC manager fails before any host task runs. Keep system `/usr/bin/ansible` as the default controller Ansible and append the lint venv only as a fallback for lint tools.
- **Timers**: repo-sync (git pull every 5 min), update-check (daily at 08:00 with Apprise notification)
- **Playbook**: `playbooks/agents/openclaw.yml` (opt-in via `openclaw_enabled` variable)
- **Config**: `host_vars/jn-t14s-lin/openclaw.yml`, `packages.yml`, `backup.yml`, and `docker.yml`
- **Firewall**: Caddy proxies OpenClaw through the T14s Tailscale address; avoid opening LAN access unless explicitly required.

**OpenClaw troubleshooting rule**: Do not assume an OpenClaw symptom is an upstream software bug or regression unless there is an exact documented GitHub issue or release note matching the observed failure. Default to diagnosing local configuration, plugin state, runtime health, gateway load, memory/LCM/mem0 state, and update drift first. Avoid update-fragile local plugin patches unless the user explicitly approves a temporary workaround.

**Mem0 Memory Plugin** (`@mem0/openclaw-mem0`): Adds automatic fact extraction (auto-capture) and context injection (auto-recall) to DBC sessions. Runs alongside the existing file-based memory system (MEMORY.md, daily notes, Gemini hybrid search).

- **Plugin**: Installed via `openclaw plugins install`, embeds `mem0ai/oss` SDK in-process (no separate server)
- **Qdrant**: Vector database at `/opt/qdrant/` (Docker, localhost:6333/6334 only). Stores memory embeddings.
- **Embedder**: Gemini (`gemini-embedding-001`) via `GEMINI_API_KEY`
- **LLM (fact extraction)**: Configured through mem0 OSS settings. Current live config uses the OpenAI-compatible LLM provider.
- **Plugin updates**: `openclaw plugins update --all` (DBC can schedule via OpenClaw cron)
- **Tools**: `memory_search`, `memory_store`, `memory_get`, `memory_list`, `memory_forget`

**dbc operational access** (deployed by `user-separation.yml`, Phase 1d):

The `dbc` user (OpenClaw agent) has least-privilege operational access on managed hosts via Tailscale SSH. Not in the docker group — stack changes go through root-owned helper scripts with sudoers entries.

| Host | Writable Files | Apply Command |
|------|---------------|---------------|
| jn-t14s-lin | `~/cc-ansible` (rwx), `~/.claude` (rwx) | `sudo /usr/local/bin/ansible-dryrun` (dry-run only) |
| media-vm | `/opt/media-stack/docker-compose.yml`, `.env` | `sudo /usr/local/sbin/dbc-media-stack-apply` |
| docker-vm | `/opt/caddy/Caddyfile` for emergency live fixes only; backport to `templates/docker/Caddyfile.j2` | `sudo /usr/local/sbin/dbc-caddy-apply` |

Helper scripts validate config before applying (compose config check, Caddy validate+reload). File access is via POSIX ACLs (`setfacl`), not group membership. All hosts also have read-only sudo for `systemctl status`, `journalctl`, `zpool status`, `zfs list`, `findmnt`.

### homebridge-lxc (CT 102 on ts440)

Homebridge instance bridging smart home devices to Apple HomeKit. Firewall allows HAP port range 51000-56000 (child bridges use dynamic ports). Web UI: `http://100.96.116.42:8581`.

### haos-vm (VM 120 on pve-alto)

Home Assistant OS. Some devices chain: Device → Homebridge → Home Assistant (HomeKit Controller) → HomeKit (HomeKit Bridge). **HA Companion App**: Set **both** Internal URL and External URL to `http://homeassistant.hinny-liberty.ts.net:8123` (blank Internal URL causes connection failures on local network).

### VirtioFS Ansible Management

`playbooks/storage/virtiofs.yml` manages VirtioFS on both sides: host-side config in `host_vars/<proxmox-node>/virtiofs.yml` (directory mappings + VM attachments), guest-side in `host_vars/<vm>/virtiofs.yml` (mount points + fstab entries). `virtiofs_directory_mappings` is the canonical list of available shares. **VM restart required** after adding VirtioFS config to host.

**VirtioFS + MergerFS caveat**: virtiofsd caches directory state from when it starts. If mergerfs branches change (e.g., after `mergerfs-balance` moves files between drives), virtiofsd won't see the new layout. A guest reboot is NOT enough — the VM must be fully stopped and started from Proxmox (`qm stop`/`qm start`) to restart the virtiofsd process on the host side.

### Nextcloud External Storage

Provides access to ZFS paths via VirtioFS without duplicating data. Nextcloud AIO's `NEXTCLOUD_MOUNT` only supports a single path, so bind mounts (defined in `host_vars/nextcloud-vm/mounts.yml`) consolidate multiple VirtioFS paths under `/srv/external`. VirtioFS ACLs don't pass through (see TS440 Storage Architecture), so files need base `o+r` permissions.

Ansible config references: VirtioFS mounts in `host_vars/nextcloud-vm/virtiofs.yml`, bind mounts in `host_vars/nextcloud-vm/mounts.yml`, Docker compose with `NEXTCLOUD_MOUNT=/srv/external` at `/opt/nextcloud/docker-compose.yml`.

**External Storage Scanning**: Nextcloud's `filesystem_check_changes: 1` only detects changes when a user browses into the folder — there's no proactive background scan. `playbooks/backup-sync/nextcloud-scan.yml` deploys a systemd timer on nextcloud-vm that runs `occ files:scan` every 10 minutes (offset by 3 min from git-sync) for the Configs and Photo Library external storage paths. This ensures git-sync changes and photo uploads appear in Nextcloud automatically.

**Codex Memory Sync**: Codex CLI's project memory (`~/.codex/memories/`) lives on the Ansible controller outside the git repo (kept private because the repo is public). `playbooks/agents/codex-memory-sync.yml` deploys a timer on `orchestrator` that rsyncs the memory directory to `ts440:/srv/nas-zfs/configs/codex-memory/` every 10 minutes (offset by 2 min). The sync normalizes destination permissions to directories `0775` and files `0664` so Nextcloud can read them through VirtioFS. This appears in Nextcloud at `Configs/codex-memory/` and syncs to the Mac via Nextcloud desktop app for use with Codex on the Mac.

## Future Considerations

### WAN Failover for Cloudflare Tunnel

**Status**: Planned - waiting on hardware purchase

Automatic WAN failover to maintain Cloudflare Tunnel connectivity (Nextcloud, Seerr) during Spectrum outages.

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

Create a domain playbook such as `playbooks/proxmox/<feature>.yml` targeting pve-m70q:

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

Ansible runs flat on jn-t14s-lin (ThinkPad T14s, Kubuntu/Ubuntu 26.04) with Ubuntu's packaged `ansible-core` 2.20+. jn-t14s-lin is the only active controller in the `orchestrator` group. Key collections: `community.docker`, `community.general`, `kewlfft.aur`, `ansible.windows`, and `community.windows`.

The working repo clone is at `~/cc-ansible` on jn-t14s-lin.

**Legacy**: pi5-01 previously served as the Ansible controller using Debian 12's packaged `ansible-core` 2.14. That Pi workflow is retired. mercury is a regular managed Raspberry Pi client, and the old NFS-backed repo-copy workflow is no longer managed.

## Vault Setup

Vault password must exist at `~/.ansible/vault_pass.txt` (configured in ansible.cfg). Create vault files from `.example` templates using `ansible-vault create`.

## Adding Hosts

1. Add host entry to appropriate group in `inventory/hosts.ini` with Tailscale IP
2. Create `host_vars/<hostname>/` directory if custom variables needed
3. Run bootstrap playbook (for Linux), then packages playbook

## Documentation

**IMPORTANT**: When making changes to this repo, keep both docs updated:
- `AGENTS.md` - Detailed technical reference for Codex CLI
- `README.md` - Quick reference for humans

Update the "Last updated" date in both files when making ANY changes.
