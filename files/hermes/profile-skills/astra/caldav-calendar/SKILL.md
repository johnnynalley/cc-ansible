---
name: caldav-calendar
description: Use for calendar sync, queries, and event changes.
version: 1.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [calendar, caldav, vdirsyncer, khal]
    related_skills: [live-task-ledger]
---

# CalDAV Calendar

Use the native local `vdirsyncer` and `khal` clients under Astra's dedicated
home. Sync before queries and after approved changes. Use `khal list` for date
ranges and `khal search` for title searches. Create an event only when date,
time, timezone, calendar, and title are explicit. Interactive edit and deletion
require a TTY and confirmation of the exact matched event.

Do not display credential commands or values. A failed sync means calendar
freshness is unknown; report the error instead of answering from stale cache.

