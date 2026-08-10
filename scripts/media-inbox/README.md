# Immich Media Inbox

This directory owns the application and deployment helpers that turn likely
movie and TV screenshots in Immich into a human-reviewed Seerr queue.

## Components

- `immich_media_inbox/`: Python standard-library service. It incrementally
  crawls stable Immich metadata, OCR, and Smart Search APIs; sends admitted
  candidates to isolated semantic vision; canonicalizes only model-selected
  titles through Seerr; stores review state in SQLite; and provides a strict
  candidate-scoped CLI for Astra.
- `bootstrap-immich-api-key`: one-time helper that derives a narrowly scoped
  `asset.read` plus `asset.view` key from the existing Immich helper container.
  It first creates and verifies a fresh app-native database backup, refuses
  duplicate names, and never prints either source or created secret.
- `reconcile-immich-api-key`: adds the exact preview permission to the existing
  named key in place after a verified Immich database backup; it restores the
  prior permission set if verification fails.
- `export-seerr-api-key`: extracts the existing Seerr global API key into a
  protected container-mount file. It refuses to replace a changed export until
  the playbook has taken a standard `live-rollback-backup` copy.
- `run-cloud-analysis`: bounded controller-side worker that claims only
  uncertain candidates, uses the explicit tool-less `openai/gpt-5.6-sol` image
  route, submits strict JSON, and deletes its protected temporary image.
- `tests/`: dependency-free unit and service-boundary tests.

The service defaults to calibration mode (`REQUESTS_ENABLED=false`). It can
classify and match assets, but it cannot submit a Seerr request until that flag
is deliberately changed after review quality is measured. Locked Immich assets
are rejected by configuration and are never scanned. Before returning or
acting on cached content, the CLI checks current visibility and purges an asset
that has since moved outside the allowed timeline/archive set.

Astra and the isolated workers may inspect pixels and OCR without per-image
approval only for assets already admitted as likely movie/TV candidates. Image
export also requires a live cloud-analysis claim. Normal queue output remains
sanitized, and Astra still has no arbitrary Immich-library, SQLite, general
Docker, or credential access.

## Validation

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/media-inbox/tests -v
black --check scripts/media-inbox/immich_media_inbox scripts/media-inbox/tests
```

The operator runbook and rollout/rollback procedure live in
`docs/immich-media-inbox.md`.
