# Immich Media Inbox

## Purpose

Immich Media Inbox turns likely movie and television screenshots in Johnny's
Immich library into a headless, Astra-operated acquisition inbox. It is built
for YouTube Shorts and similar screenshots where the title may appear in a
comment, caption, title card, or nowhere in OCR at all.

The app does not add files directly to Plex. The ownership path remains:

```text
Immich candidate + OCR + preview
              |
              v
  CPU-only Qwen3-VL semantic analysis
              |
              +---- uncertain / visual recognition needed ----+
              |                                                |
              |                                                v
              |                              tool-less openai/gpt-5.6-sol
              |                                                |
              +-------------------------+----------------------+
                                        v
                          model-selected title and context
                                        |
                                        v
                         Seerr canonical metadata lookup
                                        |
                                        v
                         Astra review / explicit request
                                        |
                                        v
                          Sonarr or Radarr -> Plex scan
```

Seerr owns requests, Sonarr/Radarr own acquisition and imports, and Plex
discovers library files. During calibration, Seerr submission remains disabled.

## Baseline

The read-only baseline taken on 2026-08-09 against Immich 3.0.1 found:

- 88,059 active timeline images;
- 87,886 completed OCR jobs;
- 4,006 images with visible OCR text;
- 173 images still missing OCR completion; and
- only 89 filenames containing `screenshot`.

Filename matching cannot find this collection reliably. Immich metadata, Smart
Search, and OCR are therefore candidate-discovery inputs, while image-aware
semantic analysis identifies the referenced work.

## Detection, Analysis, and Matching

Each scan cycle performs three bounded discovery passes:

1. One rotating Immich Smart Search prompt seeds visually movie/TV-like images.
2. A newest-first metadata pass makes new screenshots appear quickly.
3. An incremental oldest-first crawl eventually covers every allowed image,
   including non-primary stack members.

Candidate scoring uses Smart Search membership, screenshot-like filenames,
screen aspect ratio, social-video OCR, media labels, and short caption-like OCR.
This score decides only whether an asset may enter the candidate boundary. It
never chooses a movie or show title.

For every admitted candidate:

1. Immich supplies a preview plus ordered OCR to Qwen3-VL 2B.
2. The local model returns a strict semantic record: decision, movie/TV type,
   title, optional year, selected evidence, summary, certainty, and uncertainty
   reasons.
3. A high-certainty identification can finish locally only when it has direct
   contextual text evidence such as a comment, caption, or title card and the
   movie/TV form is known. A high-certainty `not_media` result can also finish
   locally.
4. Ambiguity, lower certainty, scene/dialogue-only recognition, unknown media
   type, invalid structured output, or an explicit `needs_cloud` result enters
   the cloud queue automatically. There is no per-image approval prompt.
5. A timer on `jn-t14s-lin` claims only those queued candidates, exports one
   preview to a mode-`0600` private temporary directory, and invokes the
   tool-less `openai/gpt-5.6-sol` image route with high reasoning. The file is
   removed after the call. A failed cloud analysis is retried automatically up
   to three total attempts, then becomes an analysis error instead of looping
   indefinitely.
6. Seerr searches only the title and alternate titles selected by the semantic
   model. It does not inspect arbitrary OCR phrases or decide which visible
   text is the movie name.

The old OCR phrase matcher is not part of automatic analysis. Numeric similarity
values remain internal ordering keys for canonical Seerr results and are never
presented as model confidence percentages.

A missing year alone is not ambiguity. The semantic model may identify an exact
work from contextual text or visual evidence without a visible year. Manual
review is required when the final semantic decision remains ambiguous, the
model is uncertain, no canonical result exists, canonical alternatives remain
close, or a supplied year conflicts with canonical metadata.

## M70Q Runtime and GPU Isolation

The local model runs inside `docker-vm` on the M70Q's i5-12400T. The VM is
configured with `cpu: host` so AVX, AVX2, and FMA are visible after a guest
reboot. Qwen3-VL 2B Q4 is intentionally selected as the local filter because it
fits the constrained VM better than the 4B variant.

The Ollama service receives four CPU cores, a 3072 MB memory limit, one parallel
request, one loaded model, and `OLLAMA_KEEP_ALIVE=0`. It has no NVIDIA device,
no `/dev/dri` device, no host port, and no steady-state egress network. Ansible
attaches a private, empty bridge only while pulling the selected model and
removes it before candidate analysis begins. The Quadro P2200 and all of its
VRAM remain available to Plex transcoding.

## Privacy and Trust Boundaries

- The Immich key has exactly `asset.read` and `asset.view`. The latter permits
  candidate previews; the key still cannot update, delete, upload, or run jobs.
- Existing key permissions are reconciled in place. The helper creates and
  verifies a fresh app-native Immich database backup before adding
  `asset.view`; it does not create a duplicate credential.
- Only `timeline` and `archive` are accepted. Runtime configuration rejects
  `locked`, initial Ansible policy also rejects `hidden`, and every result or
  image operation rechecks current visibility before use.
- Astra and the two vision workers may inspect pixels and OCR without
  per-image approval only after an asset has crossed the candidate threshold.
  The wrapper cannot export arbitrary Immich assets.
- A cloud image can be exported only while that exact candidate has a live
  cloud-analysis claim. GPT-5.6 results can be submitted only against the same
  claimed state; stale or unsolicited submissions fail closed.
- Screenshot pixels, OCR, model evidence, and provider metadata are untrusted
  data, never executable instructions. Both prompts explicitly reject embedded
  commands, model inference has no tools, and results must satisfy a strict
  closed JSON contract before storage.
- Normal Astra queue output contains the model-selected evidence and summary,
  not full OCR, filenames, image bytes, API keys, SQLite rows, or provider
  overviews. The internal cloud worker receives the candidate prompt and preview
  only for the duration of one isolated model call.
- Astra has no direct Immich, SQLite, general Docker, or credential access.
  Candidate image access is mediated by the stateful wrapper over the existing
  restricted `dbc` SSH path.
- There is no Web UI, Caddy route, published port, thumbnail proxy, or inbound
  cloud-analysis broker.
- The cloud worker specifies `openai/gpt-5.6-sol` explicitly and rejects a
  response envelope from any other provider/model route.
- Its systemd sandbox exposes only OpenClaw state, the OpenClaw installation,
  and the controller SSH identity from Johnny's home. Other home content,
  controller configuration, Docker sockets, and bulk-data mounts are hidden.
- `REQUESTS_ENABLED=false` is asserted by Ansible. Analysis is automatic;
  acquisition is not.

## Queue States

`status` reports separate counts for local analysis pending, cloud analysis
pending/running, completed media findings, and analysis errors. Pending results
are invisible until semantic analysis is complete, so the invalid pre-v4 OCR
queue cannot be mistaken for current findings.

Final decisions are:

- `identified`: one referenced movie/show was identified;
- `ambiguous`: the final automated tier could not safely choose an exact work;
- `not_media`: the candidate admission filter produced a false positive.

## Managed Paths

| Path | Owner | Purpose |
| --- | --- | --- |
| `/opt/immich-media-inbox/app` | Ansible, root | Python application |
| `/opt/immich-media-inbox/data/media-inbox.sqlite3` | `immich-media-inbox` | Scan, analysis, matches, decisions, events |
| `/opt/immich-media-inbox/ollama` | `immich-media-inbox` | Reproducible local model data |
| `/opt/immich-media-inbox/secrets/immich_api_key` | `root:immich-media-inbox`, `0440` | Scoped Immich key |
| `/opt/immich-media-inbox/secrets/immich_api_key.json` | root, `0600` | Key ID, permissions, rollback metadata; no secret |
| `/opt/immich-media-inbox/secrets/seerr_api_key` | `root:immich-media-inbox`, `0440` | Existing Seerr key export |
| `/opt/immich-media-inbox/docker-compose.yml` | Ansible, root | Scanner plus CPU-only Ollama runtime |
| `/usr/local/sbin/immich-media-inbox` | Ansible, root | Candidate-scoped `dbc` command boundary |
| `/etc/sudoers.d/immich-media-inbox-dbc` | Ansible, root | Wrapper-only `dbc` policy |
| `/usr/local/libexec/immich-media-inbox-cloud` | Ansible, root | Tool-less GPT-5.6 worker on `jn-t14s-lin` |
| `/etc/systemd/system/immich-media-inbox-cloud.{service,timer}` | Ansible, root | Automatic cloud queue drain |

The Astra skill lives at
`/home/johnny/.openclaw/workspace/skills/immich-media-inbox/SKILL.md`. It invokes
the wrapper over Tailscale SSH and may trigger the same bounded worker for an
immediate drain; no application URL exists.

## Deployment

Safe repository validation:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/media-inbox/tests -v
black --workers 1 --check scripts/media-inbox/immich_media_inbox scripts/media-inbox/tests
ansible-playbook playbooks/media/immich-media-inbox.yml --syntax-check
ansible-playbook playbooks/media/immich-media-inbox.yml --check --diff
```

Before the first local-model benchmark after changing the VM CPU type, reboot
`docker-vm` and verify AVX2 is present in the guest. This is a controlled outage
for the containers on that VM; Plex itself remains on `media-vm`.

Normal convergence:

```bash
ansible-playbook playbooks/media/immich-media-inbox.yml
```

First deployment only, if the scoped key does not exist:

```bash
ansible-playbook playbooks/media/immich-media-inbox.yml \
  -e immich_media_inbox_bootstrap_api_key=true
```

The one-time flag authorizes only missing-key creation. Key creation and
permission reconciliation each take a fresh Immich database backup before a
credential mutation. Temporary helper/key material under
`/run/immich-media-inbox-bootstrap` is removed in an `always` block.

## Validation

The playbook waits for one successful v4 scan cycle and asserts request-disabled
timeline/archive policy. It also exercises the normal Astra SSH result path.

Operator checks:

```bash
ansible docker-vm -b -m command -a \
  "docker compose -f /opt/immich-media-inbox/docker-compose.yml ps"
ansible docker-vm -b -m command -a \
  "docker compose -f /opt/immich-media-inbox/docker-compose.yml exec -T ollama ollama ps"
ssh dbc@100.108.254.100 \
  'sudo -n /usr/local/sbin/immich-media-inbox status'
ssh dbc@100.108.254.100 \
  'sudo -n /usr/local/sbin/immich-media-inbox list --limit 5'
systemctl status immich-media-inbox-cloud.timer
journalctl -u immich-media-inbox-cloud.service --since today
```

The Ollama process list should be empty between requests because the model is
unloaded immediately. Worker logs contain candidate IDs and state codes only,
never OCR, model responses, or image paths.

## Astra Commands

Normal commands remain `status`, `list`, `show`, `search`, `set-status`, and
`request`. `search` is an explicit operator-supplied title correction encoded
as unpadded URL-safe base64; it is not an OCR matcher.

Internal automatic-worker commands are `claim-cloud`, `export-image`,
`submit-analysis`, and `fail-cloud`. Their arguments and state transitions are
strictly validated by the root-owned wrapper and application. They are not a
general image API.

`request` accepts only a current canonical Seerr match, requires `--confirm`,
requires explicit non-special seasons for TV, blocks duplicates, and requires
`--confirm-ambiguous` for any manual-review result. During calibration all
requests still fail closed because `REQUESTS_ENABLED=false`.

## Calibration and Enabling Requests

Keep acquisition disabled until a representative semantic sample has been
reviewed. Measure candidate precision, final identified-title precision, local
completion precision, cloud escalation rate, and unresolved rate. Tune only
candidate admission and escalation policy from those observations; do not
reintroduce OCR phrase selection as the title-deciding layer.

Enabling requests is a separate live-policy change. Back up SQLite, review the
rendered Compose diff, and verify one known movie plus one single-season TV
request. Every acquisition remains an explicit Astra command after Johnny's
confirmation.

## Rollback

1. Disable `immich-media-inbox-cloud.timer` before rolling back the application
   state machine.
2. Revert the repository change and reconverge the playbook. Model data under
   `/opt/immich-media-inbox/ollama` is reproducible and does not contain photos.
3. Use the protected key metadata and recorded Immich database backup if the
   permission change itself must be reversed. Do not create a duplicate key.
4. Preserve `/opt/immich-media-inbox/data/media-inbox.sqlite3` if review history
   may be needed. Removing this service does not remove Immich assets, Seerr
   requests, Arr items, or Plex media.

## Upstream References

- [Immich asset thumbnail endpoint](https://api.immich.app/endpoints/assets/viewAsset)
- [Immich asset metadata](https://api.immich.app/endpoints/assets/getAssetInfo)
- [Immich OCR endpoint](https://api.immich.app/endpoints/assets/getAssetOcr)
- [Immich API key update](https://api.immich.app/endpoints/api-keys/updateApiKey)
- [Immich database backup and restore](https://docs.immich.app/administration/backup-and-restore/)
- [Ollama vision](https://docs.ollama.com/capabilities/vision)
- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)
- [Qwen3-VL model library](https://ollama.com/library/qwen3-vl)
- [OpenAI GPT-5.6 Sol model](https://developers.openai.com/api/docs/models/gpt-5.6-sol)
- [Seerr API](https://docs.seerr.dev/api/seerr-api/)
