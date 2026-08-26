---
name: live-task-ledger
description: Use for consequential tasks with changing live state.
version: 1.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [continuity, execution, safety, state]
    related_skills: [guided-software-walkthrough]
---

# Live Task Ledger

Before the next instruction, reconstruct the task, completed actions, exact
current state, unknowns, unavailable or forbidden items, pending work, source
of truth, and invalidated advice. Contradicted assistant advice is failure
evidence, not source truth.

If the ledger is inconsistent, stop and reconcile it. Give only a safe hold
instruction when an immediate action must pause.

Answer from the ledger first. Do not reintroduce unavailable options or change
measurements, route, or plan without a new fact. Label adaptations and separate
source-backed values from adjustments. When scaling quantities, state one
basis and verify every actionable amount; explain any exception.

Use current user facts and authoritative sources before historical recall. For
an active task, use at most one recall search and one deep expansion unless
Johnny asks for transcript forensics. Stop recalling if results conflict or
contain only prior assistant claims.

If a prior answer lost state, identify the lost ledger field, reconstruct it,
give the corrected action, and use `self-evolution` when the failure class is
reusable.

