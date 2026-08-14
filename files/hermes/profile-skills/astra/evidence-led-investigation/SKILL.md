---
name: evidence-led-investigation
description: Use when behavior needs a causal explanation.
version: 1.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [investigation, evidence, root-cause, verification]
    related_skills: [consequential-recommendation, guided-operation]
---

# Evidence-Led Investigation

## Overview

Use this procedure to explain why a system behaved as observed and to prevent
the same mechanism from recurring. Recovery and noise suppression are not root
cause analysis. A completed investigation identifies the exact object, the
timeline, the evidence, the causal mechanism, and a verified prevention path.

## When to Use

- A service, automation, alert, tool, integration, or agent behaves incorrectly.
- A failure recurs, appears suddenly after a long stable period, or produces
  confusing secondary errors.
- The user asks why something happened or expects a durable fix.

Do not load this for a simple stable fact, translation, or mechanical rewrite.

## Procedure

1. **Pin the object.** Identify the exact product, component, host, profile,
   version, path, and owner that produced the symptom. Restate the observed
   failure in one sentence. Completion: no nearby system is being diagnosed by
   association alone.
2. **Build the timeline.** Find the last known-good event, first bad event,
   recurrence pattern, and relevant changes between them. Treat a long quiet
   interval followed by a burst as evidence about state, scheduling, model,
   configuration, or feedback changes. Completion: dates and ordering are
   explicit, and relative phrases have been resolved.
3. **Collect authoritative evidence.** Prefer live state, exact logs, active
   configuration, source implementation, and primary documentation. Read the
   data shape before applying a shape-specific query. Distinguish a wrapper or
   probe failure from failure of the target system. Completion: every material
   claim points to evidence from the owning layer.
4. **Normalize expected absence.** Missing optional daily files, empty queues,
   no search matches, and idle schedules are normal data unless the contract
   requires their presence. Check optional paths before reading them and handle
   no-match results separately from real command errors. Completion: expected
   idle state cannot become a user-facing failure.
5. **Classify the incident.** Choose one: real outage, stale alert logic,
   configuration drift, dependency failure, expected warning, policy bug, or
   unknown. State what evidence would change the classification. Completion:
   the label follows the mechanism rather than the annoyance level.
6. **Prove the mechanism.** Form the smallest causal chain from trigger to
   symptom and try to falsify it with a bounded test or counterexample. Do not
   infer causation from one correlation or from a successful restart.
   Completion: the explanation predicts both the failure and the last-good
   behavior.
7. **Separate recovery from prevention.** Restore service only when needed,
   label that action as recovery, and continue until the trigger is understood.
   Prefer a fix at the owning boundary over repeated retries, muting, or token
   filtering. Completion: the proposed prevention removes or contains the
   trigger without hiding unrelated real failures.
8. **Verify end to end.** Reproduce the former trigger, confirm the bad output is
   absent, confirm intended output still works, and check restart or next-cycle
   behavior when relevant. Completion: pass and fail criteria are observable,
   and residual uncertainty is stated.

## Common Pitfalls

1. Fixing the latest visible string while leaving the generator unchanged.
2. Turning monitoring off when idle silence is the actual requirement.
3. Treating an expected missing file or no-match exit as infrastructure failure.
4. Trusting a compacted summary over the active delivery record.
5. Applying a product-specific reminder when the reusable failure is evidence
   selection, state handling, or verification.
6. Reporting raw diagnostics without a causal classification or next action.

## Verification Checklist

- [ ] Exact owner, object, version, and environment identified
- [ ] Last-good and first-bad times established
- [ ] Expected absence separated from real errors
- [ ] Wrapper failures separated from target failures
- [ ] Incident classified and causal chain falsified where practical
- [ ] Recovery distinguished from durable prevention
- [ ] Former trigger and intended success path both tested
- [ ] User response leads with the conclusion, not the investigation transcript
