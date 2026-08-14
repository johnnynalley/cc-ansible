---
name: source-grounded-study
description: Use for tutoring and verified academic event tracking.
version: 1.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [study, tutoring, coursework, source-verification]
    related_skills: []
---

# Source-Grounded Study

## Overview

Tutor and track academic work from verified course state. Never create an exam,
deadline, score, weakness, or progress claim because the channel is about study
or because an earlier generated alert mentioned it.

## When to Use

- The user requests tutoring, review, practice, planning, or explanation.
- A verified academic event or course record needs interpretation.
- A scheduled academic check has already passed its deterministic evidence gate
  and requires a user-facing alert.

Do not load this merely because an idle schedule ran. No verified event means
no user-facing output.

## Procedure

1. **Read the current course state.** Identify the active term, enrolled course,
   source document, and current date in the configured timezone. Completion:
   completed terms and inactive courses cannot generate current obligations.
2. **Verify each academic fact.** Use the authoritative course source for exam
   dates, deadlines, topics, grades, and commitments. Generated memory markers
   and prior alerts may prevent duplicates but cannot establish that an event
   exists. Completion: every event has an independent source record.
3. **Normalize idle state.** Missing optional daily notes, an empty pending
   queue, no active courses, and no events in the alert window are successful
   idle outcomes. Do not probe absent optional paths in a way that produces
   public failures. Completion: an inactive semester stays quiet indefinitely.
4. **Teach from evidence.** Ask or infer the user's goal from the active thread,
   explain the concept, check understanding, and adapt using demonstrated
   answers rather than invented mastery scores. Completion: progress claims are
   tied to observed work in the current or stored verified session.
5. **Alert only on verified changes.** For an approved event, include the exact
   course, event, date and time, source, and actionable next step. Record a
   duplicate marker only after successful delivery. Completion: repeated idle
   cycles and repeat checks do not create duplicate or partial messages.

## Common Pitfalls

1. Inferring an exam from a study-channel topic or generic semester context.
2. Treating a prior generated alert as the source of the event it announced.
3. Reading optional date files without checking whether they exist.
4. Emitting internal control text, hidden reasoning, or an all-clear summary.
5. Claiming mastery or weak areas before a study session supplies evidence.

## Verification Checklist

- [ ] Active term and course confirmed from current source state
- [ ] Dates resolved in the configured timezone
- [ ] Every event exists independently of prior alerts or memory markers
- [ ] Empty or absent optional state remains silent
- [ ] Tutoring claims reflect demonstrated user work
- [ ] Verified alerts are actionable, deduplicated, and delivered once
