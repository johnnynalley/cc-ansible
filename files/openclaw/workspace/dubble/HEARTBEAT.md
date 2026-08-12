# Dubble Heartbeat

Evaluate only live Discord threads whose metadata proves they are directly
under the configured Dubble parent channel. The parent channel itself,
unverified session history, inaccessible channels, synthetic sessions, and
archived threads are no-ops.

A thread is a follow-up candidate only when Dubble sent the last message, the
answer appears complete, no Astra handoff is active, and the configured idle
threshold has elapsed. Send at most one concise check-in. Archive only after
the later timeout or explicit user confirmation defined by the current thread
procedure. Never act while the user is waiting on Dubble.

Finish with `heartbeat_respond`. Use `notify=false` after a no-op or after any
thread-specific message action. Use `notify=true` only for an actionable owner
alert that cannot be handled in the affected thread. Do not include reasoning
or send an idle control message.
