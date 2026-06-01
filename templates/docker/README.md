# Docker Templates

## Templates

- `Caddyfile.j2`: Internal HTTPS routes and reverse proxies.
- `caddy.yml`: Caddy Docker Compose stack.
- `caddy.Dockerfile`: Caddy image build with Cloudflare DNS support.
- `diun.yml.j2`: Diun update-monitor configuration.
- `docker-auto-update.sh.j2`: Docker auto-update runner.
- `docker-media-stack.yml.j2`: docker-vm media automation compose template.
  It applies bounded `json-file` logging to media-stack containers and raises
  SABnzbd's `nofile` limit to avoid file-descriptor exhaustion during heavy
  download/unpack bursts. It also overrides Byparr's healthcheck timing so
  the media-stack sentinel can settle quickly after a controlled restart.
- `docker-socket-proxy.yml`: Docker socket proxy compose file.
- `docker-stacks.service.j2`: Systemd service for Docker Compose stacks.
- `media-stack-health.sh.j2`: Media stack health sentinel.
- `media-stack.yml`: media-vm Plex-side media compose file.
- `profilarr.yml`: Profilarr compose file.
- `qdrant.yml`: Qdrant compose file.

## Consumers

- `playbooks/docker/docker-stacks.yml`
- `playbooks/docker/docker-auto-update.yml`
- `playbooks/media/media-stack-health.yml`
- Docker stack definitions in `inventory/host_vars/*/docker.yml`

## Safety Notes

- `Caddyfile.j2`, `caddy.yml`, and `caddy.Dockerfile` are canonical for Caddy;
  live edits under `/opt/caddy/` must be backported here.
- Compose templates can restart services when rendered output changes. Use
  `--check --diff` and review rendered diffs before applying stack changes.
- `docker-auto-update.sh.j2` uses per-stack Compose locks. The media stack lock
  must stay aligned with the Gluetun/qBittorrent helpers so updates cannot race
  VPN recovery.
