# HEARTBEAT.md - Rigel

This heartbeat runs every 30 minutes around the clock so Rigel is continuously
ready for newly recorded academic work. An empty semester is the normal no-op
case, not a reason to disable the cadence or publish status.

## Source Gate

1. Read required `courses/semester-context.md`. Read optional
   `courses/pending-calendar-requests.md` only after a non-failing existence
   check. Prefer native file reads; when this runtime exposes only shell access,
   use one bounded command against those exact paths. Do not enumerate
   directories or probe daily memory on the no-op path.
2. An event exists only when the current `Active Courses` or `Upcoming Exams`
   sections contain an explicit sourced date. Archived notes, `TBD` rows, chat
   recollection, daily memory, prior alerts, and channel metadata are not event
   sources.
3. If there are no active dated events and no unfinished entry containing
   `confirmed: true`, return exactly `HEARTBEAT_OK` immediately. Do not inspect
   daily memory, scorecards, course directories, or run another probe.

## Event Check

4. Compute the current event distance from the runtime-provided
   America/Chicago date. Alert only at 7 days, 3 days, 1 day, or day-of. Skip
   passed events and events outside that window.
5. Only after a real alert candidate exists, check today's optional memory note
   for a matching `heartbeat-alerted: [event]` receipt. Missing optional files
   are normal: use a non-failing existence check before reading and never use
   `ls` as the probe.
6. Only after a real exam alert survives deduplication, read its scorecard when
   the canonical course path exists. A missing scorecard means "no session
   started yet," not a tool failure.
7. Return one alert as the final assistant response. The configured heartbeat
   target owns Discord delivery. Never call the `message` tool from a heartbeat.
8. After a sourced alert is selected, append its receipt to today's daily note.
   The receipt proves only that the alert was issued; it must never become the
   source for an event or date.
9. Re-attempt only unfinished calendar entries that explicitly contain
   `confirmed: true`. Comments, placeholders, and malformed entries are no-ops.

## Alert Format

Exam with scorecard:

```text
📚 [Course] [Exam] in [N] days ([date])
Mastery: [X]/[total] concepts ([%]%)
Weak areas: [weak concepts, or "no session started yet"]
Want to run a session?
```

Reading or deadline:

```text
📖 [Course]: [assignment] due [in N days / tomorrow / today] ([date])
```

## No-Op Contract

`HEARTBEAT_OK` must be the entire final response. Do not explain the no-op,
include reasoning, call a messaging tool, record the token as posted, or probe
irrelevant optional paths. Expected absence and healthy state produce no
external Discord message.
