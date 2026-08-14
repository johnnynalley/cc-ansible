# Hermes Templates

## Templates

- `hermes-managed-config.yaml.j2`: per-profile root-owned managed scope. It
  pins manual approvals, deny-on-cron, review-gated memory/skills, quiet output,
  suppressed background-learning chat notices, role-specific toolsets, and an
  air-gapped rootless Podman backend. It disables lazy installs and private URL
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
- `hermes-gateway.service.j2`: one hardened system service per OS identity. It
  fixes `HERMES_HOME`, root-writable profile-scoped managed credentials, and
  Podman paths; requires a root-owned shadow-ready marker; runs the shadow,
  Discord, and automation/Health contract audits before startup; rejects any
  managed config or environment checksum drift before Hermes's fail-open
  managed-scope parser can run; and exposes no dashboard or API listener.
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
  session.
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
  root capabilities, and gives the native updater write access only to the
  checkout and Astra's private profile state. It reconciles Hermes's official
  `messaging` extra after the native update because upstream intentionally
  excludes messaging from `all`, then normalizes the credential-free shared
  runtime group and restarts the two production consumers through the existing
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

## Consumer

- `playbooks/agents/hermes-shadow.yml`
- `playbooks/agents/hermes-production-runtime.yml`

## Safety Notes

- These templates contain no provider credentials, bot tokens, user/channel
  IDs, memories, sessions, or transcript data.
- Managed scope is not a sandbox. The OS identity, systemd boundary, and
  rootless Podman backend remain required.
- The shadow services are boot-disabled and cannot start until an attended
  playbook run creates the per-profile root-owned readiness marker.
