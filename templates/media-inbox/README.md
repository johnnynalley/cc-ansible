# Immich Media Inbox Templates

This directory owns the rendered Docker Compose source for the private Immich
movie/TV screenshot review service.

- `docker-compose.yml.j2`: runs the dependency-free headless scanner as an
  unprivileged, read-only container on the existing `caddy-proxy` network. API
  keys are bind-mounted protected files; they are not Compose environment
  values.
- `immich-media-inbox-cli.sh.j2`: root-owned argument-validating boundary that
  exposes only sanitized JSON results to Astra through the restricted `dbc`
  account.

Consumer: `playbooks/media/immich-media-inbox.yml`.
