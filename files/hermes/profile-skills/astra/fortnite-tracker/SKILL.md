---
name: fortnite-tracker
description: Use for Fortnite progress, events, locker, and UEFN.
version: 2.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [fortnite, progress, competitive, locker, uefn, coaching]
    related_skills: [guided-operation, evidence-led-investigation]
---

# Fortnite Tracker

## Overview

Use the migrated Fortnite sources as separate evidence domains. Do not merge
scheduled progress, current competitive eligibility, locker ownership, UEFN
project state, or coaching notes into one assumed current state.

## Hermes Sources

- Progress: `data/fortnite-progress/`
- Locker: `data/fortnite-locker.md`
- UEFN: `data/uefn/`
- Current scheduled progress artifact:
  `/var/lib/hermes-automation/fortnite-progress.json`
- Competitive schedule artifact:
  `/var/lib/hermes-automation/fortnite-schedule.json`
- Gaming performance reference:
  `managed-data/references/fortnite-performance-investigation.md` when present

Paths under `data/` are relative to Astra's imported-data working directory.
The scheduled artifacts are current collector outputs; imported tracker files
retain the full history and project state.

## Evidence Boundaries

1. Use the newest direct user report first, then the newest validated tracker
   artifact or session result, then older imported history. State when the
   current source is unavailable instead of reconstructing it from memory.
2. Keep season and lifetime totals separate. Aggregate API deltas are not
   per-match history, and missing deaths never support a K/D calculation.
3. Keep ranked Battle Royale, ranked Reload, unranked Reload, and historical
   LTM aggregates distinct. Division 21 is Unreal when placement evidence is
   present even if an upstream source leaves a promotion field populated.
4. The competitive calendar is a relevance-filtered NAC calendar, not a full
   Epic mirror. Check current eligibility and the user's stated goals before
   treating a candidate event as actionable.
5. Treat the imported locker list as the ownership source. Separate measured
   public locker counts from acquisition exclusivity; age or Founder status is
   not proof of lowest ownership.
6. The Fortnite progress schedule and calendar schedule are production
   automation, not proof that an interactive answer has fresh data. Use the
   latest successful artifact or say that a fresh read is unavailable.
7. Keep Fortnite-API BR, OliTracker, and api-fortnite playlist evidence
   separate. OliTracker and api-fortnite mode rows do not expose deaths, so do
   not compute K/D for those rows. `ltm` is Fortnite-API's historical LTM
   aggregate and is not the OliTracker Reload bucket.
8. Before answering current mechanics, loot pools, events, or season behavior,
   verify current sources. Separate official intent, observed current behavior,
   historical behavior, and undocumented change or regression.

## UEFN And Coaching

- Resume the paused UEFN map only when the user explicitly returns to it.
  During GUI work, also use `guided-operation`, reconcile the current screen,
  and give the longest deterministic safe segment rather than one click at a
  time.
- Ground coaching in the imported improvement plan, decisions, and death
  patterns when those sources are available. Preserve an accepted plan and
  replace only the rejected component unless the user asks for a redesign.
- Log a user-reported Fortnite death in the imported death ledger in the same
  turn, preserving his wording and using `unknown` when the reason awaits VOD
  review. Update the rolling pattern only from accumulated evidence.
- Recruitment, LFG, and ARK community wording belongs to the Fortnite project
  state, but exact user wording must be preserved when the user asks to save it.
- For locker rarity, resolve the complete owned outfit list and define the
  metric. Public locker counts are self-selected tracker populations, not Epic
  global ownership. Age, Founder status, and unavailability do not prove the
  lowest measured ownership.

## Response Contract

- Lead with the requested status, comparison, or next action.
- Do not repeat known API limitations unless they materially change the answer.
- Keep Star reviewer work private. A Fortnite question uses Star only when the
  normal Astra Star criteria apply, not merely because this skill loaded.
- Never claim a current tracker, calendar, locker, or project result without a
  current accessible source or an explicitly dated retained result.

## Verification Checklist

- [ ] Exact Fortnite domain and time window identified
- [ ] Direct reports and validated artifacts ordered by recency
- [ ] Mode, season, and lifetime boundaries preserved
- [ ] Missing fields not converted into invented statistics
- [ ] Calendar eligibility checked before an event is called relevant
- [ ] UEFN or coaching state resumed from the latest accepted plan
- [ ] Final answer is concise and source-bounded
