---
name: guided-operation
description: Use for an interactive setup, repair, or migration.
version: 1.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [walkthrough, setup, repair, migration]
    related_skills: [evidence-led-investigation, consequential-recommendation]
---

# Guided Operation

## Overview

Use this procedure for an interactive setup, repair, or migration. Give the
longest verified sequence the user can safely complete without new evidence.
Pause only at a real branch, irreversible action, safety boundary, or result
that changes the next instruction.

## When to Use

- The user asks to be walked through configuration, flashing, installation,
  account setup, recovery, or migration.
- The procedure depends on a particular device, release, interface, or current
  state.

Do not load this for a conceptual explanation with no action sequence.

## Procedure

1. **Pin the starting state.** Confirm the exact product, version, role, current
   screen or state, completed steps, and desired end state. Reuse evidence
   already supplied in the thread. Completion: do not ask the user to repeat a
   fact already established.
2. **Verify the procedure.** Prefer the current official workflow for the exact
   target. Reconcile interface labels, required tools, recovery behavior, and
   ordering before instructing the user. Completion: every named control or
   command is supported by the current target or visible evidence.
3. **Map branches before writing.** Separate the normal path, expected state
   transitions, and recovery branches. Identify irreversible actions and the
   rollback point. Completion: a foreseeable state change cannot make the next
   step invalid without warning.
4. **Give a continuous safe segment.** Include all steps up to the first real
   decision point. Download completion, waiting for a progress bar, or another
   action whose only possible next step is already known is not a checkpoint.
   Completion: each pause requests evidence that selects a different branch.
5. **Use exact observable cues.** Name the expected screen, device, field,
   status, or output and explain which similarly named item to avoid. Never
   invent a menu path from memory when the current interface is uncertain;
   inspect the user's screenshot or current documentation instead.
6. **Handle deviations from evidence.** Preserve the current failure state,
   compare it with documented recovery behavior, and change only the step that
   the evidence disproves. Do not guess through successive menus or make the
   user test speculative branches. Completion: the revised path explains why
   the observed state occurred.
7. **Verify the outcome.** Confirm persisted configuration, intended function,
   recovery or restart behavior, and any privacy or security boundary.
   Completion: success is based on the end-to-end function, not merely a flash,
   save button, connection, or process exit.

## Common Pitfalls

1. Asking the user to report that a prerequisite download completed when there
   is no alternate next step.
2. Giving a single step at a time despite a deterministic sequence.
3. Assuming a browser control and a physical recovery control are equivalent.
4. Repeating setup from the beginning after the user states what is complete.
5. Describing a different editor or plan tier as though it were the visible UI.
6. Declaring success at an intermediate state without testing the intended use.

## Verification Checklist

- [ ] Exact target, version, role, and current state pinned
- [ ] Current official or directly observed procedure reconciled
- [ ] Normal and recovery branches mapped before instruction
- [ ] Checkpoints occur only where evidence changes the next branch
- [ ] Expected cues and look-alike choices are explicit
- [ ] Deviations are explained before the path changes
- [ ] End-to-end function and persistence are verified
