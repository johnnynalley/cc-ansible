# Immich Media Inbox

This directory owns the application and deployment helpers that turn likely
movie and TV screenshots in Immich into a human-reviewed Seerr queue.

## Components

- `immich_media_inbox/`: Python standard-library service. It incrementally
  crawls stable Immich metadata, OCR, and Smart Search APIs; ranks OCR phrases
  against Seerr; stores review state in SQLite; and provides a strict
  result-only JSON CLI for Astra.
- `bootstrap-immich-api-key`: one-time helper that derives a narrowly scoped
  `asset.read` key from the existing Immich helper container.
  It first creates and verifies a fresh app-native database backup, refuses
  duplicate names, and never prints either source or created secret.
- `export-seerr-api-key`: extracts the existing Seerr global API key into a
  protected container-mount file. It refuses to replace a changed export until
  the playbook has taken a standard `live-rollback-backup` copy.
- `tests/`: dependency-free unit and service-boundary tests.

The service defaults to calibration mode (`REQUESTS_ENABLED=false`). It can
classify and match assets, but it cannot submit a Seerr request until that flag
is deliberately changed after review quality is measured. Locked Immich assets
are rejected by configuration and are never scanned. Before returning or
acting on cached content, the CLI checks current visibility and purges an asset
that has since moved outside the allowed timeline/archive set.

Astra cannot access image bytes, thumbnails, raw OCR, filenames, the SQLite
database, or either service credential. The root-owned host wrapper exposes
only canonical Seerr title results, confidence, ambiguity, request state, an
opaque candidate ID, and an Immich link Johnny can open himself.

Arbitrary scene recognition is intentionally not sent to a cloud vision
provider. Screenshots without a confident OCR/title match remain in the review
queue until a local or explicitly approved external provider is selected.

## Validation

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/media-inbox/tests -v
black --check scripts/media-inbox/immich_media_inbox scripts/media-inbox/tests
```

The operator runbook and rollout/rollback procedure live in
`docs/immich-media-inbox.md`.
