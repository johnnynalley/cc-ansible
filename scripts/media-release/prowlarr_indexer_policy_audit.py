#!/usr/bin/env python3
"""Audit non-secret Prowlarr indexer policy fields.

Run this on docker-vm. The report deliberately excludes tracker URLs,
credentials, API paths, and arbitrary field values.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET


PROWLARR_SAFE_FIELD_NAMES = {
    "downloadVolumeFactor",
    "grabLimit",
    "minimumSeeders",
    "packSeedTime",
    "queryLimit",
    "seedRatio",
    "seedTime",
    "uploadVolumeFactor",
}

ARR_SAFE_FIELD_NAMES = {
    "minimumSeeders",
    "rejectBlocklistedTorrentHashesWhileGrabbing",
    "seedCriteria.seasonPackSeedTime",
    "seedCriteria.seedRatio",
    "seedCriteria.seedTime",
}

ARRS = {
    "sonarr": ("http://127.0.0.1:8989", "/opt/media-stack/sonarr/config.xml"),
    "radarr": ("http://127.0.0.1:7878", "/opt/media-stack/radarr/config.xml"),
}


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def api_get(base_url: str, api_key: str, path: str) -> Any:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers={"X-Api-Key": api_key, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {path} failed: HTTP {exc.code}: {detail}") from exc


def safe_field_values(fields: Any, allowed_names: set[str]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if not isinstance(fields, list):
        return values
    for field in fields:
        if not isinstance(field, dict):
            continue
        name = field.get("name")
        if name not in allowed_names:
            continue
        value = field.get("value")
        if value is None or isinstance(value, (bool, int, float, str)):
            values[str(name)] = value
    return dict(sorted(values.items()))


def safe_indexer(indexer: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": indexer.get("id"),
        "name": indexer.get("name"),
        "protocol": indexer.get("protocol"),
        "priority": indexer.get("priority"),
        "enable": indexer.get("enable"),
        "app_profile_id": indexer.get("appProfileId"),
        "tags": indexer.get("tags") or [],
        "limits": safe_field_values(indexer.get("fields"), PROWLARR_SAFE_FIELD_NAMES),
    }


def safe_arr_indexer(indexer: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": indexer.get("id"),
        "name": indexer.get("name"),
        "implementation": indexer.get("implementation"),
        "priority": indexer.get("priority"),
        "enable_rss": indexer.get("enableRss"),
        "enable_automatic_search": indexer.get("enableAutomaticSearch"),
        "enable_interactive_search": indexer.get("enableInteractiveSearch"),
        "limits": safe_field_values(indexer.get("fields"), ARR_SAFE_FIELD_NAMES),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:9696")
    parser.add_argument("--config", default="/opt/media-stack/prowlarr/config.xml")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    indexers = api_get(args.base_url, read_api_key(args.config), "/api/v1/indexer")
    prowlarr_report = sorted(
        (safe_indexer(indexer) for indexer in indexers),
        key=lambda row: (int(row["priority"] or 999), str(row["name"] or "").casefold()),
    )
    arr_reports: dict[str, list[dict[str, Any]]] = {}
    for name, (base_url, config_path) in ARRS.items():
        arr_reports[name] = sorted(
            (
                safe_arr_indexer(indexer)
                for indexer in api_get(base_url, read_api_key(config_path), "/api/v3/indexer")
            ),
            key=lambda row: (
                int(row["priority"] or 999),
                str(row["name"] or "").casefold(),
            ),
        )
    report = {"prowlarr": prowlarr_report, **arr_reports}
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
        return 0

    print("prowlarr:")
    for row in prowlarr_report:
        state = "enabled" if row["enable"] else "disabled"
        print(
            f"  {row['id']}: {row['name']} protocol={row['protocol']} "
            f"priority={row['priority']} {state} limits={row['limits']}"
        )
    for name, rows in arr_reports.items():
        print(f"{name}:")
        for row in rows:
            print(
                f"  {row['id']}: {row['name']} implementation={row['implementation']} "
                f"priority={row['priority']} rss={row['enable_rss']} "
                f"automatic={row['enable_automatic_search']} "
                f"interactive={row['enable_interactive_search']} limits={row['limits']}"
            )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
