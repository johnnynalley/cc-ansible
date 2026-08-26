---
name: discord
description: Use for Discord history, threads, pins, and reactions.
version: 1.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [discord, history, thread, pin, reaction]
    related_skills: [daily-summary-thread]
---

# Discord Operations

Use Hermes's native Discord tools for permitted server reads and actions. Keep
the current guild, channel, thread, and message IDs explicit. Fetch history
before claiming what was posted. Create or mutate a thread, pin, message, poll,
or reaction only when the target and requested action are clear.

Normal conversation replies use the active Discord route. Cross-channel sends,
edits, deletions, pins, polls, reactions, and thread creation require the
corresponding action tool and Discord permission. Never substitute a guessed
ID, expose the bot token, or claim delivery without an API success result.

Role assignment and removal are outside Astra's allowed action set.

