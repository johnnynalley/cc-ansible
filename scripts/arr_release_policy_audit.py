#!/usr/bin/env python3
"""Audit Sonarr/Radarr release profiles and custom-format usage.

Run this on media-vm. It reads the local Arr config.xml files for API keys,
queries localhost APIs only, and does not print secrets.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ArrInstance:
    name: str
    base_url: str
    config_path: str


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def api_get(instance: ArrInstance, api_key: str, path: str) -> Any:
    url = f"{instance.base_url.rstrip('/')}{path}"
    req = urllib.request.Request(url, headers={"X-Api-Key": api_key})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{instance.name}: GET {path} failed: {exc.code} {body}") from exc


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


def item_format_name(item: dict[str, Any], custom_formats_by_id: dict[int, dict[str, Any]]) -> str:
    value = item.get("format")
    if isinstance(value, dict) and value.get("name"):
        return str(value["name"])
    cf_id = item_format_id(item)
    if cf_id is not None and cf_id in custom_formats_by_id:
        return str(custom_formats_by_id[cf_id].get("name", f"id:{cf_id}"))
    return str(item.get("name") or f"id:{cf_id}")


def summarize_instance(instance: ArrInstance) -> dict[str, Any]:
    api_key = read_api_key(instance.config_path)
    custom_formats = api_get(instance, api_key, "/api/v3/customformat")
    quality_profiles = api_get(instance, api_key, "/api/v3/qualityprofile")
    queue_status = api_get(instance, api_key, "/api/v3/queue/status")
    commands = api_get(instance, api_key, "/api/v3/command")

    custom_formats_by_id = {
        int(cf["id"]): cf for cf in custom_formats if isinstance(cf.get("id"), int)
    }

    referenced: dict[int, set[str]] = {}
    scored: dict[int, set[str]] = {}
    profiles: list[dict[str, Any]] = []

    for profile in sorted(quality_profiles, key=lambda p: str(p.get("name", ""))):
        nonzero_items: list[dict[str, Any]] = []
        zero_items: list[dict[str, Any]] = []

        for item in profile.get("formatItems", []):
            cf_id = item_format_id(item)
            if cf_id is None:
                continue
            profile_name = str(profile.get("name", ""))
            referenced.setdefault(cf_id, set()).add(profile_name)
            score = int(item.get("score") or 0)
            row = {
                "id": cf_id,
                "name": item_format_name(item, custom_formats_by_id),
                "score": score,
                "include_in_rename": bool(
                    custom_formats_by_id.get(cf_id, {}).get("includeCustomFormatWhenRenaming")
                ),
            }
            if score:
                scored.setdefault(cf_id, set()).add(profile_name)
                nonzero_items.append(row)
            else:
                zero_items.append(row)

        profiles.append(
            {
                "id": profile.get("id"),
                "name": profile.get("name"),
                "upgrade_allowed": profile.get("upgradeAllowed"),
                "cutoff": profile.get("cutoff"),
                "min_format_score": profile.get("minFormatScore"),
                "cutoff_format_score": profile.get("cutoffFormatScore"),
                "nonzero_custom_formats": sorted(
                    nonzero_items, key=lambda row: (-abs(row["score"]), row["name"])
                ),
                "zero_custom_format_count": len(zero_items),
            }
        )

    all_ids = set(custom_formats_by_id)
    referenced_ids = set(referenced)
    scored_ids = set(scored)

    unused = sorted(
        (
            {"id": cf_id, "name": custom_formats_by_id[cf_id].get("name")}
            for cf_id in all_ids - referenced_ids
        ),
        key=lambda row: str(row["name"]).lower(),
    )
    all_zero = sorted(
        (
            {
                "id": cf_id,
                "name": custom_formats_by_id[cf_id].get("name"),
                "include_in_rename": bool(
                    custom_formats_by_id[cf_id].get("includeCustomFormatWhenRenaming")
                ),
                "profiles": sorted(referenced[cf_id]),
            }
            for cf_id in referenced_ids - scored_ids
        ),
        key=lambda row: str(row["name"]).lower(),
    )

    active_commands = [
        {
            "id": command.get("id"),
            "name": command.get("name"),
            "status": command.get("status"),
            "message": command.get("message"),
        }
        for command in commands
        if command.get("status") not in {"completed", "failed", "aborted", "cancelled"}
    ]

    return {
        "name": instance.name,
        "base_url": instance.base_url,
        "custom_format_count": len(custom_formats),
        "quality_profile_count": len(quality_profiles),
        "unused_custom_format_count": len(unused),
        "all_zero_custom_format_count": len(all_zero),
        "unused_custom_formats": unused,
        "all_zero_custom_formats": all_zero,
        "queue_status": {
            "total_count": queue_status.get("totalCount"),
            "count": queue_status.get("count"),
            "unknown_count": queue_status.get("unknownCount"),
            "errors": queue_status.get("errors"),
            "warnings": queue_status.get("warnings"),
        },
        "active_commands": active_commands,
        "quality_profiles": profiles,
    }


def print_text(report: dict[str, Any]) -> None:
    for instance in report["instances"]:
        print(f"{instance['name']}:")
        print(f"  custom formats: {instance['custom_format_count']}")
        print(f"  quality profiles: {instance['quality_profile_count']}")
        print(f"  unused custom formats: {instance['unused_custom_format_count']}")
        print(f"  all-zero custom formats: {instance['all_zero_custom_format_count']}")
        print(f"  queue: {instance['queue_status']}")
        if instance["active_commands"]:
            print("  active commands:")
            for command in instance["active_commands"]:
                print(f"    - {command['id']} {command['name']} {command['status']}: {command['message']}")
        if instance["unused_custom_formats"]:
            print("  unused custom formats:")
            for cf in instance["unused_custom_formats"]:
                print(f"    - {cf['id']}: {cf['name']}")
        if instance["all_zero_custom_formats"]:
            print("  all-zero custom formats:")
            for cf in instance["all_zero_custom_formats"]:
                profiles = ", ".join(cf["profiles"])
                rename = ", rename" if cf["include_in_rename"] else ""
                print(f"    - {cf['id']}: {cf['name']} ({profiles}{rename})")
        print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--sonarr-url", default="http://127.0.0.1:8989")
    parser.add_argument("--radarr-url", default="http://127.0.0.1:7878")
    parser.add_argument("--sonarr-config", default="/opt/media-stack/sonarr/config.xml")
    parser.add_argument("--radarr-config", default="/opt/media-stack/radarr/config.xml")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    instances = [
        ArrInstance("sonarr", args.sonarr_url, args.sonarr_config),
        ArrInstance("radarr", args.radarr_url, args.radarr_config),
    ]
    report = {"instances": [summarize_instance(instance) for instance in instances]}
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        print_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
