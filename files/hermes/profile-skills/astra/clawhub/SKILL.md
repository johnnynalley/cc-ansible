---
name: clawhub
description: Use when finding, reviewing, or installing a skill.
version: 1.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [skills, registry, clawhub, audit]
    related_skills: [skill-creator]
---

# Skill Registry

Use Hermes's native `skills search`, `inspect`, `audit`, `install`, `update`,
and `snapshot` flows. ClawHub is one supported source, not a reason to bypass
Hermes trust and threat scanning. Inspect provenance and contents before an
install. Skill writes and activation require owner approval. Never replace
root-managed Astra skills with a registry result.

