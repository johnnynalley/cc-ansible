---
name: himalaya
description: Use for private mailbox listing, reading, and replies.
version: 1.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [email, imap, smtp, himalaya]
    related_skills: [job-application-tracker]
---

# Himalaya Mail

Use the system `himalaya` client with Astra's private account configuration.
Mailbox discovery, listing, reading, and searching are read-only. Summarize the
actual body, not only subject snippets. Drafting, replying, forwarding, moving,
copying, deleting, or sending requires Johnny's explicit instruction and an
exact account, folder, and message target.

Never print the authentication command or secret. If the client or auth path
fails, report that mail is unavailable rather than fabricating inbox state.

