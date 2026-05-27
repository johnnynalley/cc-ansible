#!/usr/bin/env python3
"""Add anime Bluray source ranking to legacy balanced anime profiles.

Run this on docker-vm. It reads local Arr config.xml files for API keys, backs
up current custom formats and quality profiles, then creates/updates:

- Local Anime Source Rank - Bluray

The CF is scored only in balanced anime profiles. It sits below x265/HEVC and above
release-group tiers so a same-resolution Web x264 tier release cannot replace a
same-resolution Bluray x264 release just because of group tier points.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE_RANK_CF_NAME = "Local Anime Source Rank - Bluray"
SOURCE_RANK_SCORE = 1500
TARGET_CUTOFF_SCORE = 144900


@dataclass(frozen=True)
class Arr:
    name: str
    base_url: str
    config_path: Path
    anime_profiles: tuple[str, ...]
    bluray_source_value: int


def read_api_key(path: Path) -> str:
    root = ET.parse(path).getroot()
    api_key = root.findtext("ApiKey")
    if not api_key:
        raise RuntimeError(f"{path}: ApiKey not found")
    return api_key.strip()


def request_json(
    arr: Arr,
    api_key: str,
    method: str,
    path: str,
    payload: Any | None = None,
) -> Any:
    url = f"{arr.base_url.rstrip('/')}{path}"
    data = None
    headers = {"X-Api-Key": api_key}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = response.read().decode("utf-8", errors="replace")
            if not body:
                return None
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{arr.name} {method} {path} failed: {exc.code} {body}") from exc


def source_spec(arr: Arr) -> dict[str, Any]:
    return {
        "name": "Bluray Source",
        "implementation": "SourceSpecification",
        "implementationName": "Source",
        "infoLink": f"https://wiki.servarr.com/{arr.name}/settings#custom-formats-2",
        "negate": False,
        "required": True,
        "fields": [
            {
                "order": 0,
                "name": "value",
                "label": "Value",
                "value": arr.bluray_source_value,
                "type": "select",
                "advanced": False,
                "privacy": "normal",
                "isFloat": False,
            }
        ],
    }


def desired_custom_format(arr: Arr, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(existing or {})
    payload["name"] = SOURCE_RANK_CF_NAME
    payload["includeCustomFormatWhenRenaming"] = False
    payload["specifications"] = [source_spec(arr)]
    return payload


def backup_state(
    backup_root: Path,
    timestamp: str,
    arr: Arr,
    custom_formats: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
) -> Path:
    backup_dir = backup_root / f"{timestamp}-anime-source-rank-policy"
    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / f"{arr.name}-customformat.json").write_text(
        json.dumps(custom_formats, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (backup_dir / f"{arr.name}-qualityprofile.json").write_text(
        json.dumps(profiles, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return backup_dir


def find_by_name(items: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for item in items:
        if item.get("name") == name:
            return item
    return None


def item_format_id(item: dict[str, Any]) -> int | None:
    value = item.get("format")
    if isinstance(value, dict):
        value = value.get("id")
    if value is None:
        value = item.get("customFormatId")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def format_item(cf_id: int, score: int) -> dict[str, int]:
    return {"format": cf_id, "score": score}


def patch_profile(profile: dict[str, Any], cf_id: int) -> list[str]:
    changes: list[str] = []
    format_items = profile.setdefault("formatItems", [])
    matched = False
    for item in format_items:
        if item_format_id(item) != cf_id:
            continue
        matched = True
        if int(item.get("score") or 0) != SOURCE_RANK_SCORE:
            item["score"] = SOURCE_RANK_SCORE
            changes.append(f"score {SOURCE_RANK_CF_NAME}={SOURCE_RANK_SCORE}")
    if not matched:
        format_items.append(format_item(cf_id, SOURCE_RANK_SCORE))
        changes.append(f"add {SOURCE_RANK_CF_NAME}={SOURCE_RANK_SCORE}")

    current_cutoff = int(profile.get("cutoffFormatScore") or 0)
    if current_cutoff < TARGET_CUTOFF_SCORE:
        profile["cutoffFormatScore"] = TARGET_CUTOFF_SCORE
        changes.append(f"cutoffFormatScore {current_cutoff}->{TARGET_CUTOFF_SCORE}")
    return changes


def patch_arr(arr: Arr, backup_root: Path, timestamp: str, apply: bool) -> dict[str, Any]:
    api_key = read_api_key(arr.config_path)
    custom_formats = request_json(arr, api_key, "GET", "/api/v3/customformat")
    profiles = request_json(arr, api_key, "GET", "/api/v3/qualityprofile")
    backup_dir = backup_state(backup_root, timestamp, arr, custom_formats, profiles)

    existing_cf = find_by_name(custom_formats, SOURCE_RANK_CF_NAME)
    desired_cf = desired_custom_format(arr, existing_cf)
    cf_changes: list[str] = []
    if existing_cf is None:
        cf_changes.append(f"create {SOURCE_RANK_CF_NAME}")
        if apply:
            desired_cf = request_json(arr, api_key, "POST", "/api/v3/customformat", desired_cf)
    elif json.dumps(existing_cf, sort_keys=True) != json.dumps(desired_cf, sort_keys=True):
        cf_changes.append(f"update {SOURCE_RANK_CF_NAME}")
        if apply:
            desired_cf = request_json(
                arr,
                api_key,
                "PUT",
                f"/api/v3/customformat/{existing_cf['id']}",
                desired_cf,
            )
    if not apply and existing_cf is None:
        desired_cf["id"] = -1

    cf_id = int(desired_cf.get("id") or existing_cf["id"])
    profile_changes: dict[str, list[str]] = {}
    profiles_by_name = {str(profile.get("name")): profile for profile in profiles}
    for profile_name in arr.anime_profiles:
        profile = profiles_by_name.get(profile_name)
        if profile is None:
            continue
        changes = patch_profile(profile, cf_id)
        if changes:
            profile_changes[profile_name] = changes
            if apply:
                request_json(
                    arr,
                    api_key,
                    "PUT",
                    f"/api/v3/qualityprofile/{profile['id']}",
                    profile,
                )

    return {
        "arr": arr.name,
        "backup_dir": str(backup_dir),
        "custom_format_changes": cf_changes,
        "profile_changes": profile_changes,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-root", default="/opt/media-stack/arr-policy-backups")
    parser.add_argument("--sonarr-url", default="http://127.0.0.1:8989")
    parser.add_argument("--radarr-url", default="http://127.0.0.1:7878")
    parser.add_argument("--sonarr-config", default="/opt/media-stack/sonarr/config.xml")
    parser.add_argument("--radarr-config", default="/opt/media-stack/radarr/config.xml")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = Path(args.backup_root)
    instances = (
        Arr(
            "sonarr",
            args.sonarr_url,
            Path(args.sonarr_config),
            ("shows-anime-balanced",),
            6,
        ),
        Arr(
            "radarr",
            args.radarr_url,
            Path(args.radarr_config),
            ("movies-anime-balanced",),
            9,
        ),
    )
    report = {
        "apply": args.apply,
        "source_rank_score": SOURCE_RANK_SCORE,
        "target_cutoff_score": TARGET_CUTOFF_SCORE,
        "instances": [
            patch_arr(instance, backup_root, timestamp, args.apply)
            for instance in instances
        ],
    }
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    print()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
