# Hermes Templates

## Templates

- `hermes-managed-config.yaml.j2`: per-profile root-owned managed scope. It
  pins manual approvals, profile-specific cron policy, review-gated
  memory/skills, quiet output, suppressed background-learning chat notices,
  and role-specific toolsets. Astra uses native non-root local terminal, file,
  and code tools plus LCM/Mem0; Dubble and Rigel expose no execution tools and
  retain an inert air-gapped rootless Podman backend. It disables lazy installs and private URL
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
  Astra additionally validates identical root-owned plugin trees, the exact
  six-hook/no-tool registration surface, and a read-only managed-to-runtime
  plugin bind before startup. The unit requires the dedicated Tirith binary
  before Hermes starts and forces the scanner to operate offline. Each service
  also runs the Discord dependency audit through the managed Hermes interpreter
  and cannot become active until its main process owns an established TLS
  session. `hermes-native-gateway-migration.yml` copies legacy flat profile
  state into Hermes's native named-profile layout before installing these
  units and retains the old state for rollback.
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
  state. It reconciles Hermes's official `messaging` and `mem0` extras after
  the native update because upstream intentionally excludes them from `all`.
  It also installs Mem0's declared `google-genai` provider dependency required
  by the selected Gemini embedder on the release track compatible with
  Hermes's lock, without pulling Mem0's broad `llms` extra,
  then normalizes the credential-free shared runtime group and restarts the two
  production consumers through the existing
  exact-command sudo boundary. The normal Discord Gateway unit
  keeps `/usr/local` read-only, so Astra can change program files only inside the
  dedicated update namespace. The root-managed Astra directory is entirely
  inaccessible to the updater; selected root-owned runtime policy paths remain
  read-only. The code checkout uses the `hermes-runtime-readers` primary group
  during updates; all three isolated Gateway identities can read that shared
  credential-free runtime but cannot read one another's homes or managed
  credentials.
- `hermes-tirith-native-update.service.j2` and
  `hermes-tirith-native-update.timer.j2`: run Tirith's own mandatory-signature,
  atomic self-updater under the dedicated no-login `hermes-updater` identity.
- `hermes-native-update.sudoers.j2`: permits only `hermes-astra` to start the
  exact Hermes native update unit and to issue Hermes's exact `reset-failed`,
  `start`, and `restart` calls for the three enumerated Gateway units. It gets no
  shell or arbitrary systemctl authority; Dubble and Rigel get no sudo access.
- `astra-production-jobs.json.j2`: renders the seven reviewed native Astra jobs
  with route identifiers supplied from inventory. The committed template is
  valid JSON and contains no production platform identifiers.
- `hermes-gateway-astra-automation.conf.j2`: adds the production manifest and
  native cron zero-drift preflight only to Astra's Gateway.
- `hermes-retained-automation@.service.j2`,
  `hermes-daily-summary-collect.timer.j2`, and
  `hermes-fortnite-progress-collect.timer.j2`: run the bounded retained
  collectors without exposing the legacy workspace to a model.
- `hermes-warframe-feed.service.j2`, `hermes-warframe-feed.timer.j2`,
  `hermes-fortnite-calendar-fetch.service.j2`,
  `hermes-fortnite-calendar.service.j2`, and
  `hermes-fortnite-calendar.timer.j2`: own feed/calendar fetch and apply lanes
  with separate network and mutation boundaries.
- `hermes-profile-backup@.service.j2` and
  `hermes-profile-backup@.timer.j2`: run native per-profile backups under the
  matching no-login identity with independent locks.
- `hermes-mem0.json.j2`: renders Astra's mode-`0600` native OSS Mem0 provider
  configuration with OpenRouter LLM, Gemini embeddings, the dedicated Hermes
  Qdrant collection, and no embedded credentials.

## Consumer

- `playbooks/agents/hermes-shadow.yml`
- `playbooks/agents/hermes-production-runtime.yml`
- `playbooks/agents/hermes-memory-continuity.yml`
- `playbooks/agents/hermes-automation.yml`

## Safety Notes

- These templates contain no provider credentials, bot tokens, user/channel
  IDs, memories, sessions, or transcript data.
- Managed scope is not a sandbox. Dedicated OS identities and systemd are the
  authority boundary for Astra's local tools; Dubble and Rigel expose none.
- The shadow services are boot-disabled and cannot start until an attended
  playbook run creates the per-profile root-owned readiness marker.
