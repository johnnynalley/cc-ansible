# Immich Media Inbox

## Purpose

Immich Media Inbox turns likely movie and television screenshots in Johnny's
Immich library into a headless, Astra-operated acquisition inbox. It is designed
for saved YouTube Shorts and similar screenshots where OCR may contain a title,
year, social-video chrome, subtitles, or only partial clues.

The service does not add files directly to Plex. The controlled path is:

```text
Immich image + OCR + Smart Search
              |
              v
      candidate scoring
              |
              v
   sanitized result-only CLI ----> Astra asks Johnny about ambiguity
              |
              v
     Seerr request (disabled during calibration)
              |
              v
       Sonarr / Radarr ----> Plex library scan
```

This preserves the existing media-stack ownership boundaries: Seerr owns
requests, Sonarr/Radarr own acquisition and imports, and Plex discovers the
resulting library files.

## Baseline and Current State

The read-only baseline taken on 2026-08-09 against Immich 3.0.1 found:

- 88,059 active timeline images
- 87,886 images with completed OCR jobs
- 4,006 images with visible OCR text
- 173 images still missing OCR completion
- only 89 image filenames containing `screenshot`

Filename matching alone is therefore insufficient. Immich OCR and Smart Search
are both first-class discovery inputs. The app uses only Immich's stable
metadata search, Smart Search, OCR, asset metadata, server-feature, and version
API endpoints. It never requests image or thumbnail bytes.

## Detection and Matching

Each scan cycle does three bounded passes:

1. One rotating Immich Smart Search prompt seeds visually movie/TV-like images.
2. A newest-first metadata pass makes new screenshots appear quickly.
3. An incremental oldest-first crawl eventually covers every image, including
   non-primary members of Immich stacks.

Candidate scoring combines Smart Search membership, screenshot-like filenames,
phone/16:9 aspect ratios, social-video OCR, movie/TV labels, labeled titles, and
short lower-third text. Candidates over the configured threshold enter the
review queue. OCR title phrases are searched in Seerr and conservatively ranked
by normalized title similarity and any visible year.

The scanner never decides that an uncertain match is safe to acquire. Astra's
CLI supports manual Seerr search and the dispositions `pending`, `ignored`, and
`not_media`. Missing OCR years, low-confidence matches, close alternatives, and
year conflicts remain explicitly marked for manual review. A request for one of
those candidates needs a separate ambiguity confirmation. A TV request also
requires explicit non-special season selection. Existing or already-requested
Seerr titles are detected before submission to prevent duplicates.

## Privacy and Safety Boundaries

- The Immich key has exactly `asset.read`; it cannot view thumbnails, download
  originals, update, delete, upload, or operate jobs.
- Initial key creation is an explicit one-time action. The bootstrap helper
  creates and verifies a fresh app-native Immich database backup before it
  creates the key, refuses duplicate key names, and records the backup filename
  and key ID in protected rollback metadata.
- Only `timeline` and `archive` visibility are accepted. Runtime configuration
  rejects `locked`, and the initial Ansible policy also rejects `hidden`. The
  CLI rechecks live visibility before returning or acting on cached content and
  deletes disallowed cached rows.
- Immich and Seerr keys are root-owned bind-mounted files. They are not Compose
  environment values, Astra output, URLs, or logs.
- There is no Web UI, listening port, thumbnail proxy, or Caddy route. The
  container is reachable only on its Docker network for outbound Immich/Seerr
  API calls.
- Astra reaches one root-owned wrapper over the existing restricted `dbc` SSH
  path. The wrapper validates every argument and emits only sanitized JSON:
  canonical Seerr title/type/year, confidence, ambiguity codes, request state,
  an opaque candidate ID, and an Immich link Johnny can open himself.
- Astra cannot read image bytes, thumbnails, raw OCR, filenames, SQLite state,
  or either API key through this interface. Provider overviews and source OCR
  queries are also excluded as untrusted result content.
- `REQUESTS_ENABLED=false` is asserted by Ansible and validated after startup.
  Calibration can classify and match, but it cannot acquire media.
- No screenshot is sent to a cloud vision provider. Arbitrary scene/actor
  recognition remains a manual-review case until a local model or a specific
  external provider and privacy policy are explicitly approved.

## Managed Paths

| Path | Owner | Purpose |
| --- | --- | --- |
| `/opt/immich-media-inbox/app` | Ansible, root | Deployed Python application |
| `/opt/immich-media-inbox/data/media-inbox.sqlite3` | `immich-media-inbox` (UID/GID 65532) | Scan cursor, OCR cache, matches, decisions, events |
| `/opt/immich-media-inbox/secrets/immich_api_key` | `root:immich-media-inbox`, `0440` | Scoped metadata/OCR-only Immich key |
| `/opt/immich-media-inbox/secrets/immich_api_key.json` | root, `0600` | Key ID, permissions, and pre-change backup metadata; no secret |
| `/opt/immich-media-inbox/secrets/seerr_api_key` | `root:immich-media-inbox`, `0440` | Derived existing Seerr key |
| `/opt/immich-media-inbox/docker-compose.yml` | Ansible, root | Rendered Compose configuration |
| `/usr/local/sbin/immich-media-inbox` | Ansible, root | Strict result-only Astra command wrapper |
| `/etc/sudoers.d/immich-media-inbox-dbc` | Ansible, root | Wrapper-only `dbc` execution policy |

The Astra operating skill lives at
`/home/johnny/.openclaw/workspace/skills/immich-media-inbox/SKILL.md` on
`jn-t14s-lin`. It invokes the wrapper over Tailscale SSH; no service URL exists.

## Deployment

Safe local validation:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/media-inbox/tests -v
ansible-playbook playbooks/media/immich-media-inbox.yml --syntax-check
ansible-playbook playbooks/media/immich-media-inbox.yml --check --diff
```

First deployment only, after reviewing the check-mode diff:

```bash
ansible-playbook playbooks/media/immich-media-inbox.yml \
  -e immich_media_inbox_bootstrap_api_key=true
```

The extra variable authorizes only the missing-key bootstrap. Before creating
the key, the helper requests Immich's stable `backup-database` job and polls the
backup inventory until a new, non-empty dump exists. The temporary source and
new key material under `/run/immich-media-inbox-bootstrap` is removed in the
playbook's `always` cleanup.

Normal future convergence does not need the bootstrap flag. If the local key
file is lost while the named Immich key still exists, the helper deliberately
fails instead of creating a duplicate; revoke the unrecoverable key in Immich,
take another backup, and perform a fresh explicit bootstrap.

## Validation

The media playbook waits for one successful scan cycle and asserts from the
container health response that:

- scan state is `idle` with a completion timestamp;
- requests are disabled;
- allowed visibility is exactly `timeline` plus `archive`.

Additional operator checks:

```bash
ansible docker-vm -b -m command -a \
  "docker compose -f /opt/immich-media-inbox/docker-compose.yml ps"
ansible docker-vm -b -m command -a \
  "docker compose -f /opt/immich-media-inbox/docker-compose.yml logs --tail 100"
ssh dbc@100.108.254.100 \
  'sudo -n /usr/local/sbin/immich-media-inbox status'
ssh dbc@100.108.254.100 \
  'sudo -n /usr/local/sbin/immich-media-inbox list --limit 5'
```

Do not paste `docker inspect` environment output, SQLite rows, raw OCR, or
either secret file into logs or chat. The wrapper output is the only approved
Astra data path.

## Astra Commands

The wrapper supports `status`, `list`, `show`, `search`, `set-status`, and
`request`. Astra should normally start with `status`, then `list --limit 20`.
`show` accepts the opaque candidate UUID. `search` accepts an unpadded
URL-safe-base64 UTF-8 title so arbitrary screenshot or chat text never becomes
shell syntax. The skill owns that encoding step.

`set-status` accepts only `pending`, `ignored`, or `not_media`. `request`
accepts only a stored canonical Seerr match, requires `--confirm`, requires
explicit seasons for TV, rejects duplicates, and also requires
`--confirm-ambiguous` for any manual-review candidate. During initial
calibration every request still fails closed because `REQUESTS_ENABLED=false`.

## Calibration and Enabling Requests

Keep acquisition disabled until a representative sample has been reviewed.
Measure at least candidate precision (movie/TV screenshot vs `not_media`) and
top-match precision (exact title/version vs manual correction). Adjust
`candidate_threshold`, `auto_match_threshold`, Smart Search prompts, and OCR
phrase filtering from observed false-positive/false-negative classes.

Enabling requests is a separate live-policy change. Before changing
`immich_media_inbox_requests_enabled`, back up the SQLite database with
`live-rollback-backup`, review the rendered Compose diff, and verify a single
known movie plus a single-season TV request. Do not enable unattended automatic
submission; every request remains an explicit Astra command after Johnny's
confirmation.

## Rollback

1. Stop the Compose project or revert the repo change and reconverge the media
   inbox playbook. Remove the wrapper and its sudoers file only as part of that
   managed rollback.
2. Use the protected `immich_api_key.json` ID to revoke `immich-media-inbox` in
   Immich's API Key settings. Never print the secret file.
3. Preserve `/opt/immich-media-inbox/data/media-inbox.sqlite3` if review work
   may be needed later; it is independent of Immich and Plex.
4. Removing the service does not remove any Immich asset, Seerr request, Arr
   item, or Plex media. If requests are enabled in a later rollout, undo those
   external requests through Seerr/Arr according to their own state rather than
   deleting library files from this app.

## Upstream References

- [Immich OCR endpoint](https://api.immich.app/endpoints/assets/getAssetOcr)
- [Immich metadata search](https://api.immich.app/endpoints/search/searchAssets)
- [Immich Smart Search](https://api.immich.app/endpoints/search/searchSmart)
- [Immich database backup and restore](https://docs.immich.app/administration/backup-and-restore/)
- [Immich API key creation](https://api.immich.app/endpoints/api-keys/createApiKey)
- [Seerr API](https://docs.seerr.dev/api/seerr-api/)
