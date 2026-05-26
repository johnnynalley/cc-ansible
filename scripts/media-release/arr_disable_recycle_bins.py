#!/usr/bin/env python3
"""Disable Sonarr/Radarr recycle bins with a timestamped live backup."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any


ARRS = (
    {
        "name": "sonarr",
        "url": "http://127.0.0.1:8989",
        "config": "/opt/media-stack/sonarr/config.xml",
    },
    {
        "name": "radarr",
        "url": "http://127.0.0.1:7878",
        "config": "/opt/media-stack/radarr/config.xml",
    },
)


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def api_json(
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None
    headers = {"X-Api-Key": api_key, "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, sort_keys=True).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code}: {detail}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backup-root",
        default="/opt/media-stack/arr-policy-backups",
        help="Remote directory where before-change JSON backups are written.",
    )
    parser.add_argument(
        "--timestamp",
        default=dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ"),
        help="UTC timestamp prefix for the backup directory.",
    )
    args = parser.parse_args()

    backup_dir = Path(args.backup_root) / f"{args.timestamp}-recycle-bin-disabled"
    backup_dir.mkdir(parents=True, exist_ok=True)

    for arr in ARRS:
        name = arr["name"]
        api_key = read_api_key(arr["config"])
        config = api_json(arr["url"], api_key, "GET", "/api/v3/config/mediamanagement")
        backup_path = backup_dir / f"{name}-media-management.before.json"
        backup_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")

        updated = dict(config)
        old_recycle_bin = updated.get("recycleBin")
        old_cleanup_days = updated.get("recycleBinCleanupDays")
        updated["recycleBin"] = ""
        updated["recycleBinCleanupDays"] = 0

        config_id = updated.get("id")
        if config_id is None:
            raise RuntimeError(f"{name}: media management config did not include id")
        api_json(arr["url"], api_key, "PUT", f"/api/v3/config/mediamanagement/{config_id}", updated)
        verified = api_json(arr["url"], api_key, "GET", "/api/v3/config/mediamanagement")

        print(
            f"{name}: recycleBin {old_recycle_bin!r} -> {verified.get('recycleBin')!r}; "
            f"cleanupDays {old_cleanup_days!r} -> {verified.get('recycleBinCleanupDays')!r}; "
            f"backup={backup_path}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
