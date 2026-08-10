# Immich Media Inbox Templates

This directory owns the rendered Docker Compose source for the private Immich
movie/TV screenshot review service.

- `Dockerfile.j2`: builds the non-root scanner runtime with a pinned Pillow
  codec used only to convert candidate-only Immich WebP previews into bounded
  JPEG input for Ollama.
- `docker-compose.yml.j2`: runs the headless scanner and an isolated CPU-only
  Ollama runtime. The model service has no GPU device and no published port.
  API keys are bind-mounted protected files, not environment values. The
  two services are converged through direct, service-scoped `docker compose up`
  commands so a retagged containerd image cannot strand Ansible's project-wide
  Compose image inventory. The explicit local scanner tag is rebuilt only for
  a Dockerfile/base-image change or a missing tag, and every build forces the
  same-call recreation. A dangling digest also forces one recreation, and
  project image inventory is a required post-condition.
- `immich-media-inbox-cli.sh.j2`: root-owned argument-validating boundary for
  sanitized results and claimed-candidate image analysis through `dbc`.
- `immich-media-inbox-cloud.service.j2` and
  `immich-media-inbox-cloud.timer.j2`: run the bounded, tool-less GPT-5.6
  escalation worker as `johnny` on Astra's controller host.

Consumer: `playbooks/media/immich-media-inbox.yml`.
