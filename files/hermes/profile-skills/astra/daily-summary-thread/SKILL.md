---
name: daily-summary-thread
description: Use for Daily Summary thread reads and updates.
version: 1.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [discord, summary, dedupe, routing]
    related_skills: [discord]
---

# Daily Summary Thread

This is the Hermes adaptation of Astra's complete OpenClaw Daily Summary
contract. The implementation is native Hermes, but the visible behavior,
editorial judgment, continuity, source checks, thread routing, and watchdog
evidence must remain equivalent.

## Fixed Route

- Guild: `1209365945882251294`
- Parent `#astra`: `1482585492330381343`
- Private `#astra-logs`: `1482589440663617638`
- Static `Daily Summary` thread: `1501040629025865779`
- Owner: `740687933803331726`
- Timezone: `America/Chicago`

Use the static thread directly. Never create a dated Daily Summary thread and
never put Daily Summary content in the parent channel.

Use `discord_parity` with these native operations:

- Read: `action=thread_messages`, with the guild ID, static thread ID, and a
  limit of 30.
- Post: `action=thread_reply`, with the static thread ID and one complete
  message at a time.
- Failure alert: `action=send_message`, with the parent or private-log channel
  explicitly selected.

## Per-Run Guardrails

This job carries the prior run's output only for style and editorial
continuity. Prior output is never valid freshness, delivery, or duplicate
evidence.

1. The first tool action must inspect the current file metadata for
   `/var/lib/hermes-automation/daily-summary.md`. Do this in the current run.
2. Require a regular, non-symlink file no older than 15 minutes, bounded to the
   injected artifact limit. If it is stale, missing, empty, or invalid, return
   exactly `[SILENT]`; the watchdog owns failure classification and alerting.
3. Read the artifact in the current run and confirm its generated local date is
   today's `America/Chicago` date. Do not use remembered content.
4. Read the latest 30 messages in the static thread. If the read fails, send
   one concise failure alert to parent `#astra`, then return `[SILENT]`.
5. If today's summary or equivalent content is already present, return exactly
   `[SILENT]`. A rerun never duplicates or re-pings.
6. If required terminal, file, or Discord tools are unavailable, use any
   available Discord send path to report the tool-exposure failure to
   `#astra-logs`; do not pretend the compose succeeded.

The scheduler saying `ok` is not delivery proof. A successful
`thread_reply` response containing the posted message ID is delivery proof.

## Compose Boundary

The artifact is the complete data packet. Do not gather fresh external data in
this job. Read all of it, connect related facts, compare against recent thread
context when useful, and write a fresh briefing in Astra's voice.

The result must be AI-composed. Collection and assembly scripts may produce the
source packet, but no hard-coded formatter may choose wording, priority,
cross-section relationships, or omissions. Never invoke the preserved legacy
`daily-summary-post.py`; it is evidence, not a runtime fallback.

Act as an editor and analyst, not a section concatenator. Keep routine
telemetry compact while preserving concrete information Johnny actually uses.
Connect related signals when useful, including storage plus media deltas,
security/update warnings plus coverage gaps, calendar plus related inbox
items, and health/weather/activity relationships.

## Delivery Shape

Post 2-4 complete thread replies as needed. Prefer 2; use 3 or 4 when complete
sections require them. Split only between section blocks or complete bullets.
Never batch multiple posts in one tool call. Send one reply, verify its
delivery result, then send the next.

### Reply 1: Quick Read

Start exactly with:

`<@740687933803331726> Daily Summary — <today's local date>`

Then add a headline under 120 characters: either `Nothing urgent today` or the
single most important issue.

Use only these sections in this order, skipping empty sections:

**Needs attention**

- 1-3 bullets, under 400 characters total.
- Include only actionable security, money/bills, health anomalies, outages,
  storage risk, urgent calendar items, or failed backup/sync.
- Collapse a genuinely unchanged prior warning to `Still:` and one short
  clause.

**Today**

- 1-3 bullets, under 300 characters total.
- Include time-sensitive calendar items and notable weather.
- Deliveries belong in Inbox. Routine game drops belong in the detailed brief.

**System**

- 1-4 bullets, under 400 characters total.
- Include problems, security updates, large update counts, failed checks,
  notable version changes, and storage/network issues.
- Do not enumerate healthy services or every host with one routine update.

Target the complete Quick Read under 1,500 characters.

### Replies 2-4: Full Brief

Post only when useful non-urgent content exists. Use these sections, skipping
empty or normal sections.

**Inbox**

- Keep it under 500 characters.
- Group and deduplicate Security, Money, Deliveries, and Low priority where
  useful. Prefer counts over repetitive message lists.

**Media/Plex**

- Preserve a compact `viewer: title (played duration)` breakdown whenever
  plays exist. Group repeated episodes of the same series by viewer with
  episode count and total played duration. Never reduce activity to only play
  count and combined duration.
- Name every affected show or movie when grabs, imports, upgrades, or failures
  exist. Separate grab-only items, new imports, and upgrades.
- For upgrades, retain the supplied old-to-new quality, codec,
  audio/languages, repack/proper state, and custom-format score or reason. If
  Arr exposes no meaningful difference, say so.
- Group episodes only when the title and change reason match. Name failed
  downloads and their short failure reason.
- There is no standalone 500-character cap for this section. Use another
  complete reply rather than deleting useful media detail.

**News / RSS**

- Treat `## RSS Candidates` as unapproved evidence, not prepared copy.
- Keep at most three current items concretely useful to Johnny's Hermes,
  Linux, homelab, Apple/Asahi, or security setup.
- Reject generic deals, weak keyword matches, duplicates, stale items, and
  unsupported claims. Preserve direct links and phrase uncertain summaries
  cautiously. Omit the section if nothing qualifies.

**Health**

- Omit routine normal results.
- Preserve artifact health-sanity warnings and helper-generated totals. Do not
  substitute raw database sums.
- Put actionable anomalies in Needs attention as well.

**Fortnite**

- Keep this separate whenever the artifact contains `## Fortnite`.
- Keep it under 500 characters and summarize the week-ahead NAC outlook by
  day/time.
- Preserve source-sync freshness warnings. A same-day event may also appear in
  Today.

**Coverage gaps**

- Keep it under 300 characters.
- Separate incomplete or failed checks from real alerts and state exactly what
  was not checked.

Target each Full Brief reply below 1,800 characters and below 16 visible lines
when practical. More complete replies are better than one truncated reply.

## Editing Rules

- Preserve factual meaning. Do not invent facts, silently treat stale data as
  current, or add unsupported remediation.
- Put important status and numbers first. Use concise briefing bullets, bold
  section labels, no tables, no raw source headers, and at most two nesting
  levels.
- Keep one fact per bullet and logical groups together.
- Do not drop a useful category because it is unchanged, degraded, failed, or
  unavailable; state that condition when it affects the briefing.
- Preserve useful links and important caveats.
- Never end a reply with a truncation ellipsis. Check completeness and the
  Discord hard limit before each post.
- Ping Johnny only in the first substantive post of the day. Never use
  `@everyone` or `@here`.

After every post is confirmed, return a private scheduler continuity capsule
containing the local date and the exact text of the delivered replies. This
final output is saved locally and is not another Discord post. It lets the
next run preserve style and prior-report awareness without trusting old state
for freshness. If no post was due, return exactly `[SILENT]`.
