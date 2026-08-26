# Hermes Templates

## Templates

- `hermes-managed-config.yaml.j2`: per-profile root-owned managed scope. It
  pins manual approvals, profile-specific cron policy, review-gated
  memory/skills, quiet output, suppressed background-learning chat notices,
  and role-specific toolsets. Astra uses native non-root local terminal, file,
  and code tools plus LCM/Mem0. Rigel uses native file and local terminal tools
  with its working directory fixed to its isolated academic workspace and its
  service identity restricted from runtime secrets and other profiles. Dubble
  exposes no local tools and retains
  an inert air-gapped rootless Podman backend. It disables lazy installs and private URL
  access, points Tirith at the absolute self-managed binary, requires scanner
  failures to deny the command, and makes full native pre-update backups the
  default. Delegation is flat, capped at two
  concurrent children and 12 iterations, with child orchestration disabled.
  Only Astra enables the reviewed hook-only Star privacy plugin; Dubble and
  Rigel keep an empty plugin set.
  Discord fails closed with no shadow allowlists, silent unknown DMs, no bot
  input, no history or missed-message backfill, per-user sessions, explicit
  thread mentions, bounded attachments, and no slash registration. It carries
  the reviewed Hermes config schema version.
- `hermes-gateway-hardening.conf.j2`: security and readiness drop-in for the
  system unit created by Hermes's native `gateway install --system` command.
  Ansible does not replace native lifecycle directives such as `ExecStart`,
  `ExecStop`, restart policy, watchdog behavior, service identity, `HOME`, or
  `HERMES_HOME`. The drop-in requires a root-owned readiness marker; runs the
  shadow, Discord, and automation/Health contract audits before startup;
  rejects managed config or environment checksum drift; and exposes no
  dashboard or API listener.
  It also bind-mounts the profile's root-owned reviewed skill tree read-only
  under Hermes's native local skill root and requires the exact contract plus
  native skill-index validator to pass before the Gateway process starts. Its
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
  session. `hermes-native-gateway-migration.yml` copies legacy flat profile
  state into Hermes's native named-profile layout before installing these
  units and retains the old state for rollback. Astra's drop-in also enables
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
  hardened privilege boundary and automatic schedule around the unmodified
  `hermes update --gateway --yes` command. Hermes retains ownership of
  Git selection, backup, dependency migration, rollback, and gateway restart.
  The unit runs as `hermes-astra`, loads no Gateway secret environment, has no
  ambient capabilities, and bounds its setuid child to `CAP_SETUID` and
  `CAP_SETGID` so exact sudoers-authorized Gateway restarts work. It gives the
  native updater write access only to the checkout and Astra's private profile
  state. A root-owned updater-only Python startup shim raises only the exact
  managed Gateway `systemctl start/restart` subprocess wait to 120 seconds so
  the native updater can honor the units' 90-second `Type=notify` startup
  budget instead of falsely failing at 15 seconds. It reconciles Hermes's
  official `messaging` and `mem0` extras after
  the native update because upstream intentionally excludes them from `all`,
  then reasserts the newest production-stable `mem0ai[nlp]`, `fastembed`,
  and local Ollama client packages with prereleases denied. The compatible
  English spaCy model is required to remain loadable so hybrid keyword and
  entity processing cannot silently degrade. It then normalizes the
  credential-free shared runtime group and restarts the three
  production consumers through the existing
  exact-command sudo boundary. The normal Discord Gateway unit
  keeps `/usr/local` read-only, so Astra can change program files only inside the
  dedicated update namespace. The root-managed Astra directory is entirely
  inaccessible to the updater; selected root-owned runtime policy paths remain
  read-only. The code checkout uses the `hermes-runtime-readers` primary group
  during updates; all three isolated Gateway identities can read that shared
  credential-free runtime but cannot read one another's homes or managed
  credentials.
  After Hermes updates its own declared dependencies, the unit invokes the
  managed compatibility resolver to install newest-stable memory packages
  together with Hermes's active base requirements. This keeps Mem0 current
  without drifting shared libraries beyond the installed Hermes release's
  compatibility contract.
  The post-update gate also executes the managed Chromium selector in check
  mode, so a successful updater cannot leave browser automation falsely
  reported as installed.
- `hermes-tirith-native-update.service.j2` and
  `hermes-tirith-native-update.timer.j2`: run Tirith's own mandatory-signature,
  atomic self-updater in a root-owned, capability-empty sandbox. Tirith 0.4+
  updates its scanner and root-owned package-approval helper as one signed
  transaction, so only Tirith state and `/usr/local/libexec` are writable.
- `hermes-native-update.sudoers.j2`: permits only `hermes-astra` to start the
  exact Hermes native update unit and to issue Hermes's exact `reset-failed`,
  `start`, and `restart` calls for the three enumerated Gateway units. It gets no
  shell or arbitrary systemctl authority; Dubble and Rigel get no sudo access.
- `astra-production-jobs.json.j2`, `dubble-production-jobs.json.j2`, and
  `rigel-production-jobs.json.j2`: render the reviewed native jobs with route
  identifiers supplied from inventory. Before dedicated enrollment, Astra
  retains the Rigel academic lane and Rigel's manifest is empty; afterward,
  that one lane moves to Rigel without duplicating delivery.
- `hermes-gateway-astra-automation.conf.j2`,
  `hermes-gateway-dubble-automation.conf.j2`, and
  `hermes-gateway-rigel-automation.conf.j2`: add profile-specific live-manifest,
  parity, and native cron zero-drift preflights to each configured Gateway.
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
  strictly read-only bindfs ownership mapping for `hermes-astra`. Gateway
  startup and the periodic audit also enforce the exact bootstrap/reference
  source-to-native-target parity contract.
  `hermes-gateway-openclaw-evidence.conf.j2` makes Astra's Gateway require that
  projection and binds it read-only as `legacy-openclaw`. The matching audit
  service/timer reconcile all source paths and the source fingerprint every
  six hours. Namespace-backed filesystem hardening is intentionally absent
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
  staggered, low-priority native LCM summary and conversational-chunk embedding
  batches through local Ollama. They hold no provider credentials, restart no
  Gateway, and leave LCM's uncertainty ledger fail-closed for operator review.
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
- `playbooks/agents/hermes-mem0-native-upgrade.yml`
- `playbooks/agents/hermes-memory-servers.yml`
- `playbooks/agents/hermes-lcm-native-features.yml`
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
