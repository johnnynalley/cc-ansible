---
name: healthcheck
description: Use for host security and operational health reviews.
version: 1.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [health, security, updates, backups]
    related_skills: [evidence-led-investigation]
---

# Host Healthcheck

Identify the exact host and owner before checking exposure, SSH, firewall,
updates, storage, backups, encryption, service health, and Hermes security.
Use read-only local commands, managed Ansible inventory, and Hermes `doctor`,
`security`, and `monitoring` where applicable. Classify each issue as outage,
drift, dependency failure, expected tradeoff, stale check, or unknown.

For Astra's own runtime, use the native profile commands directly:

- `hermes logs --lines 200` reads the private Gateway/agent log.
- `systemctl is-active hermes-gateway-astra.service` checks live service state.
- `hermes doctor` and `hermes monitoring` inspect native runtime health.

These work as `hermes-astra`; do not claim host logs are unavailable merely
because `journalctl` is restricted. Use the private Hermes log first. System
journal access remains intentionally unavailable unless the private log omits
evidence needed for a specific root-cause investigation.

Do not harden, restart, mute, or update as part of diagnosis. Propose concrete
changes with impact, rollback, and verification; obtain approval first.
