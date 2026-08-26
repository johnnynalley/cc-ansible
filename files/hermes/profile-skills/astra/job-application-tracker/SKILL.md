---
name: job-application-tracker
description: Use for job applications, resumes, and career follow-up.
version: 1.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [jobs, resume, applications, interviews]
    related_skills: [himalaya, live-task-ledger]
---

# Job Application Tracker

## Sources

- `data/job-search/applications/applications.csv`
- `data/job-search/resume-versions/notes.md`
- `data/job-search/strategy.md`

The CSV is the human-editable source of truth. Answer the immediate question
first, then update it when Johnny provides concrete application, interview,
resume, or lead data.

## Tracking Rules

1. Parse the CSV before editing and preserve manual changes.
2. Append a new row for a new opportunity. Update an existing row only when
   company, role, and location or source clearly identify it.
3. Use `unknown` instead of inventing salary, dates, contacts, or status.
4. Use ISO dates. Keep status to `lead`, `applied`, `assessment`,
   `phone_screen`, `interview`, `offer`, `rejected`, `withdrawn`, `ghosted`,
   or `accepted`.
5. Record `next_action` and `next_action_date` when follow-up is due.
6. Track summer income, school and streaming schedule fit, career upside,
   commute, and resume version when relevant.
7. Put reusable interview lessons in `strategy.md` and reusable resume choices
   in the resume notes.
8. Submit durable career facts through the native memory proposal flow, but do
   not store passwords, portal tokens, full SSNs, or other secrets.

For a pipeline review, group by status and next action, flag stale applications
after roughly 7 to 10 days without response, and recommend the next three
actions. For tailored resumes, preserve originals, create a dated variant under
`data/job-search/resume-versions/generated/`, verify the result, and record the
honest reusable changes.

After editing, parse the full CSV and report its row and field counts.

