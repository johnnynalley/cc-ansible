---
name: sober-tracker
description: Use for private sobriety check-ins and milestones.
version: 1.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [sobriety, check-in, milestone, privacy]
    related_skills: [live-task-ledger]
---

# Sober Tracker

Use `../transformed-data/data/sober-tracking/state.json` relative to Astra's
imported-data working directory. This is the writable Hermes conversion of the
preserved OpenClaw state.

## Rules

- Keep raw check-ins local. Do not send them to external services or store them
  as general memories.
- Ask for the substance or habit and start date when initializing. Daily spend
  is optional.
- A check-in records ISO date, mood 1 through 10, cravings 1 through 10, and
  optional notes.
- Milestones are 1 day, 3 days, 1 week, 2 weeks, 1 month, 2 months, 3 months,
  6 months, and 1 year. Record a milestone once.
- If Johnny reports a relapse, record the date and his wording. Do not erase
  prior progress or silently reset history. Ask what tracking interpretation
  he wants if the continuing counter is ambiguous.
- Mention details only in Johnny's private Astra context unless he introduces
  them elsewhere.
- Durable memory may keep milestone dates and helpful patterns, not raw daily
  check-ins.

Use a structured JSON parser and atomic replacement for writes. Preserve
unknown fields. Validate date formats, ranges, and array shapes before saving.
Never reconstruct the state from an assistant message when the file exists.
