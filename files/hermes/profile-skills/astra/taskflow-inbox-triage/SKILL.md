---
name: taskflow-inbox-triage
description: Use for durable inbox triage with later follow-up.
version: 1.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [tasks, inbox, triage, follow-up]
    related_skills: [taskflow, himalaya]
---

# TaskFlow Inbox Triage

List and read mail through `himalaya`, classify each item from its actual body,
and record required actions as native Hermes kanban tasks. Preserve message and
account identifiers without copying credentials. Draft responses for review;
do not send, move, or delete mail unless Johnny explicitly requests it. Park
tasks waiting on a reply and summarize them later from durable task state.

