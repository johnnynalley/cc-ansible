# Astra Heartbeat

Read the heartbeat procedure and check catalog. Run only checks that are due
under their recorded cadence. A missing optional state file never makes every
check due.

Apply resource bounds and the incident RCA gate. Do not overlap heavy checks,
reconstruct commands or destinations from memory, or publish healthy
inventories, unchanged findings, ignored conditions, diagnostic-only state,
expected absence, or all-clear summaries.

Re-probe decisive state before a present-tense outage claim. Notify only for a
new actionable fingerprint, material worsening, a new owner decision, or useful
recovery from a previously visible outage.

Finish every heartbeat with the native `heartbeat_respond` tool. Use
`notify=false` when nothing needs attention. Use `notify=true` with one concise
`notificationText` only when Johnny should be interrupted. Do not call a
messaging tool for an idle outcome and do not include hidden reasoning.
