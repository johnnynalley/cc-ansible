---
name: taskflow
description: Use for durable multi-step and delegated task work.
version: 1.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [tasks, kanban, delegation, continuity]
    related_skills: [live-task-ledger]
---

# TaskFlow

Use Hermes's native SQLite-backed kanban and project commands for durable work.
Record owner context, objective, acceptance criteria, dependencies, assignee,
workspace, current status, waits, evidence, and next action. Use child tasks
only for real parallelism. A task awaiting review is not blocked; a task
awaiting time is scheduled; a task awaiting owner input is blocked with the
exact question.

Inspect run history and worker logs before retrying. Reclaim only a proven
stale worker. Completion requires the acceptance criteria and durable result,
not merely a worker exit.

