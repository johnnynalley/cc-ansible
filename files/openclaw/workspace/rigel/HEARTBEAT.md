# Rigel Heartbeat

The 30-minute heartbeat remains enabled around the clock. An empty semester is
the normal idle case, not a reason to disable the schedule or publish status.

## Source Gate

1. Read required `courses/semester-context.md`. Read
   `courses/pending-calendar-requests.md` only after a non-failing existence
   check. Do not enumerate course directories or inspect daily memory on the
   idle path.
2. An event exists only when the current canonical course source contains an
   explicit sourced date. Archived notes, placeholders, chat recollection,
   prior alerts, channel metadata, and delivery receipts are not event sources.
3. If there is no active dated event and no unfinished confirmed calendar
   entry, immediately call `heartbeat_respond` with `notify=false`. Run no
   additional probe.

## Event Check

4. Calculate distance using the runtime date in `America/Chicago`. Alert only
   at the configured 7-day, 3-day, 1-day, or day-of boundaries. Skip passed and
   out-of-window events.
5. Only for a real alert candidate, check today's optional delivery receipt
   after a non-failing existence check. A missing receipt is normal.
6. Only for an undelivered assessment alert, read the scorecard when its
   canonical path exists. A missing scorecard means no session has started.
7. Record a delivery receipt only after selecting a sourced alert. It proves
   delivery only and never becomes event authority.
8. Reattempt only unfinished calendar entries explicitly marked confirmed.

For an alert, call `heartbeat_respond` with `notify=true` and one concise
`notificationText` containing the course, event, date, distance, and available
mastery or weak-area state. Otherwise use `notify=false`. Never call a messaging
tool, include hidden reasoning, or emit an idle control message.
