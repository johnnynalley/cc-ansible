---
name: skill-creator
description: Use for creating or revising a Hermes skill.
version: 1.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [skills, authoring, audit, validation]
    related_skills: [clawhub, self-evolution]
---

# Skill Creator

Use Hermes's native skill format, manager, curator, and threat scanner. Keep a
skill focused on a reusable task boundary, with semantic description and
source-of-truth paths. Inspect existing skills before adding one. Validate
frontmatter, content, threat-scan result, discovery, a fresh behavioral
scenario, and a normal case that should not invoke the skill. Astra may create,
revise, archive, and restore its own agent-created skills without approval.
Root-managed Astra skills are operator-owned and read-only; preserve evidence
and request an operator change instead of shadowing or overriding them.
