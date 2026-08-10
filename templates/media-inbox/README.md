# Immich Media Inbox Templates

This directory owns the rendered Docker Compose source for the private Immich
movie/TV screenshot review service.

- `docker-compose.yml.j2`: runs the dependency-free headless scanner and an
  isolated CPU-only Ollama runtime. The model service has no GPU device and no
  published port. API keys are bind-mounted protected files, not environment
  values.
- `immich-media-inbox-cli.sh.j2`: root-owned argument-validating boundary for
  sanitized results and claimed-candidate image analysis through `dbc`.
- `immich-media-inbox-cloud.service.j2` and
  `immich-media-inbox-cloud.timer.j2`: run the bounded, tool-less GPT-5.6
  escalation worker as `johnny` on Astra's controller host.

Consumer: `playbooks/media/immich-media-inbox.yml`.
