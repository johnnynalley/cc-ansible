# Hermes Templates

## Templates

- `hermes-gateway-hardening.conf.j2`: security and readiness drop-in for the
  system unit created by Hermes's native `gateway install --system` command.
  Ansible does not replace native lifecycle directives such as `ExecStart`,
  `ExecStop`, restart policy, watchdog behavior, service identity, `HOME`, or
  `HERMES_HOME`. The drop-in requires a root-owned readiness marker; runs the
  shadow, Discord, and automation/Health contract audits before startup;
  validates the agent-owned native profile config and exposes no
  dashboard or API listener.
  It does not bind-mount or checksum-pin profile-owned skills. The one
  Astra-maintained shared `self-evolution` skill is projected read-only to
  Dubble and Rigel through the explicit shared-skill boundary. Its
  reviewed project-data source is bound writable only to the matching profile,
  while root-managed operator references are bound read-only. Root and
  service-identity preflights verify the complete manifest, exact bind pair,
  and read/write mount modes before the Gateway process can start.
  Astra additionally validates identical root-owned plugin trees, including
  the typed Docker inventory/update, host administration, Arr API, and Compose
  transaction boundaries, plus read-only managed-to-runtime plugin binds
  before startup. The unit requires the dedicated Tirith binary
  before Hermes starts and forces the scanner to operate offline. Each service
  also runs the Discord dependency audit through the managed Hermes interpreter
  and cannot become active until its main process owns an established TLS
  session. The completed one-time migration copied legacy flat profile state
  into Hermes's native named-profile layout and retained the old state for
  rollback; its playbook is retired. Astra's drop-in also enables
  stable LCM local summary/chunk embeddings, full-corpus binary prescreen,
  proactive recall, and temporal rollups against the managed local Ollama
  endpoint; no metered embedding provider is configured.
  Astra also points Hermes's native browser detector at the root-managed
  `hermes-agent-browser-chromium` selector, which accepts only canonical
  executable builds owned by Astra under agent-browser's native cache.
- `hermes-launcher.sh.j2`: the normal native Hermes launcher. Its only special
  branch recognizes the exact `update --gateway` argv emitted by Hermes's
  Discord `/update` command and lets only `hermes-astra` invoke the narrow
  systemd update unit. It does not discover, select, download, or install a
  release.
- `hermes-native-update.service.j2` and `hermes-native-update.timer.j2`: a
  narrow root lifecycle boundary around Hermes's unmodified native updater.
  The wrapper records planned stops, stops only the currently active fixed
  Gateway units, and runs `hermes update --yes --backup --branch main
  --switch-branch` as `hermes-astra` in a zero-capability transient service.
  Because each profile has a separate OS identity and native root, the wrapper
  then invokes Hermes's own noninteractive config migration as each profile
  identity and requires its schema to be current. Hermes owns release
  selection, Git movement, backup, migration rules, and dependency resolution
  from its official lock and active memory-provider manifest. The wrapper
  restores only the Gateways that were active before the update and does not
  patch source, resolve packages, replay post-setup hooks, or maintain a second
  updater implementation. Gateway credentials and cross-profile private state
  remain inaccessible to the update identity.
- `hermes-tirith-native-update.service.j2` and
  `hermes-tirith-native-update.timer.j2`: run Tirith's own mandatory-signature,
  atomic self-updater in a root-owned, capability-empty sandbox. Tirith 0.4+
  updates its scanner and root-owned package-approval helper as one signed
  transaction, so only Tirith state and `/usr/local/libexec` are writable.
- `hermes-native-update.sudoers.j2`: permits only `hermes-astra` to start the
  exact root-owned Hermes native update unit. It gets no shell or arbitrary
  systemctl authority; Dubble and Rigel get no sudo access.
- `astra-production-jobs.json.j2`, `dubble-production-jobs.json.j2`, and
  `rigel-production-jobs.json.j2`: render the reviewed native jobs with route
  identifiers supplied from inventory. Before dedicated enrollment, Astra
  retains the Rigel academic lane and Rigel's manifest is empty; afterward,
  that one lane moves to Rigel without duplicating delivery.
- `hermes-gateway-astra-automation.conf.j2` and
  `hermes-gateway-rigel-automation.conf.j2`: grant only the supplemental group
  needed to read shared collector output. Native schedule and historical
  OpenClaw parity are not Gateway startup gates.
- `hermes-private-discord-enrollment.json.j2`: records only the three proven
  application identity fingerprints and fixed route metadata in root-private
  storage; it never renders bot tokens.
- `hermes-retained-automation@.service.j2`,
  `hermes-daily-updates-collect.timer.j2`,
  `hermes-daily-media-collect.timer.j2`,
  `hermes-daily-personal-collect.timer.j2`,
  `hermes-daily-summary-assemble.timer.j2`, and
  `hermes-fortnite-progress-collect.timer.j2`: run the bounded retained
  collectors without exposing the legacy workspace to a model. FreshRSS is
  collected into the Daily Summary scratch artifact through this same path;
  it has no independent publishing schedule.
- `hermes-warframe-feed.service.j2`, `hermes-warframe-feed.timer.j2`,
  `hermes-fortnite-calendar-fetch.service.j2`,
  `hermes-fortnite-calendar.service.j2`, and
  `hermes-fortnite-calendar.timer.j2`: own feed/calendar fetch and apply lanes
  with separate network and mutation boundaries. The public Fortnite fetcher
  runs as `hermes-astra` with no capabilities and uses the checksum-verified
  stable standalone geckodriver plus Firefox's direct binary; it does not use
  the Snap driver wrapper or bind Johnny's home.
- `hermes-profile-backup@.service.j2` and
  `hermes-profile-backup@.timer.j2`: run native per-profile backups under the
  matching no-login identity with independent locks.
- `hermes-openclaw-evidence.service.j2` mounts the untouched complete
  OpenClaw tree as an overlay lowerdir, applies only generated secret/link
  redactions in a root-private upperdir, then publishes the result through
  strictly read-only bindfs ownership mapping for `hermes-astra`. The periodic
  audit enforces the exact bootstrap/reference source-to-native-target parity
  contract independently of Gateway availability.
  `hermes-gateway-openclaw-evidence.conf.j2` asks systemd to start that
  projection and binds it read-only as `legacy-openclaw` when available, but a
  missing or failed historical evidence projection does not block native Astra
  startup. The matching audit service/timer reconcile all source paths and the
  source fingerprint every six hours. Namespace-backed filesystem hardening is intentionally absent
  from the mount service because it must publish mounts into the host namespace;
  its capability bounding set is limited to mounting and bindfs ID mapping.
- `hermes-mem0.json.j2`: renders Astra's mode-`0600` native OSS Mem0 provider
  configuration with a local Ollama LLM, local Qwen embeddings, the selected
  dedicated Hermes Qdrant collection, and no embedded credentials.
- `hermes-ollama.service.j2`: owns the local stable-channel Ollama server unit
  used by native Mem0 and LCM after the guarded memory-server transaction
  replaces the previously unmanaged installer-generated unit. It applies a
  bounded managed context large enough for retained LCM summaries; context-only
  drift uses an Ollama-only rollback transaction and never restarts Astra.
- `hermes-lcm-backfill.service.j2` and `hermes-lcm-backfill.timer.j2`: run
  temporary staggered, low-priority LCM summary and conversational-chunk
  historical-backfill batches. They load semantic choices from Astra's native
  profile-owned `lcm.env`, hold no embedded provider configuration or
  credentials, restart no Gateway, and leave LCM's uncertainty ledger
  fail-closed for operator review. Remove the timers after migration debt is
  zero.
- `hermes-fleet-admin.service.j2`,
  `hermes-gateway-fleet-admin.conf.j2`, and
  `hermes-fleet-admin-policy.json.j2`: define Astra's credential-isolated
  owner-session-only broker, exact provenance policy, runtime socket boundary,
  masked sensitive paths, and one-consumer Gateway attachment for direct
  Dubble/Rigel administration.

## Consumer

- `playbooks/agents/hermes-shadow.yml`
- `playbooks/agents/hermes-production-runtime.yml`
- `playbooks/agents/hermes-memory-continuity.yml`
- `playbooks/agents/hermes-memory-servers.yml`
- `playbooks/agents/hermes-lcm-backfill.yml`
- `playbooks/agents/hermes-compose-admin.yml`
- `playbooks/agents/hermes-fleet-admin.yml`
- `playbooks/agents/hermes-automation.yml`
- `playbooks/agents/hermes-openclaw-evidence.yml`

## Safety Notes

- These templates contain no provider credentials, bot tokens, user/channel
  IDs, memories, sessions, or transcript data.
- Managed scope is not a sandbox. Dedicated OS identities and systemd are the
  authority boundary for Astra's local tools and Rigel's academic file/terminal
  root; Dubble exposes none.
- The shadow services are boot-disabled and cannot start until an attended
  playbook run creates the per-profile root-owned readiness marker.
