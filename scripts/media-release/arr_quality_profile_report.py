#!/usr/bin/env python3
"""Report Arr quality-profile native quality groups.

Run this on docker-vm. It reads local Sonarr/Radarr config.xml files for API
keys, queries localhost APIs only, and does not print secrets.
"""

from __future__ import annotations

import argparse
import json
import re
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


INSTANCES = (
    ArrInstance("sonarr", "http://127.0.0.1:8989", "/opt/media-stack/sonarr/config.xml"),
    ArrInstance("radarr", "http://127.0.0.1:7878", "/opt/media-stack/radarr/config.xml"),
)


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def api_get(instance: ArrInstance, path: str) -> Any:
    request = urllib.request.Request(
        f"{instance.base_url.rstrip('/')}{path}",
        headers={"X-Api-Key": read_api_key(instance.config_path)},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{instance.name}: GET {path} failed: {exc.code} {body}") from exc


def quality_name(item: dict[str, Any]) -> str:
    quality = item.get("quality")
    if isinstance(quality, dict) and quality.get("name"):
        return str(quality["name"])
    return str(item.get("name") or "")


def summarize_item(item: dict[str, Any]) -> dict[str, Any]:
    children = item.get("items")
    if isinstance(children, list) and children:
        return {
            "type": "group",
            "name": str(item.get("name") or ""),
            "allowed": bool(item.get("allowed")),
            "qualities": [quality_name(child) for child in children],
        }
    return {
        "type": "quality",
        "name": quality_name(item),
        "allowed": bool(item.get("allowed")),
    }


def summarize_instance(instance: ArrInstance, profile_pattern: re.Pattern[str]) -> dict[str, Any]:
    profiles = api_get(instance, "/api/v3/qualityprofile")
    return {
        "instance": instance.name,
        "profiles": [
            {
                "id": profile.get("id"),
                "name": profile.get("name"),
                "cutoff": profile.get("cutoff"),
                "upgrade_allowed": profile.get("upgradeAllowed"),
                "min_format_score": profile.get("minFormatScore"),
                "cutoff_format_score": profile.get("cutoffFormatScore"),
                "items": [summarize_item(item) for item in profile.get("items") or []],
            }
            for profile in sorted(profiles, key=lambda item: str(item.get("name") or ""))
            if profile_pattern.search(str(profile.get("name") or ""))
        ],
    }


def print_text(report: dict[str, Any]) -> None:
    for instance in report["instances"]:
        print(f"{instance['instance']}:")
        for profile in instance["profiles"]:
            print(
                "  {name} id={id} cutoff={cutoff} min={min_format_score} cutoffScore={cutoff_format_score}".format(
                    **profile
                )
            )
            for item in profile["items"]:
                if item["type"] == "group":
                    qualities = ", ".join(item["qualities"])
                    print(f"    group {item['name']} allowed={item['allowed']}: {qualities}")
                else:
                    print(f"    quality {item['name']} allowed={item['allowed']}")
        print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile-regex",
        default="profilarr-test|shows-regular|movies-regular",
        help="regular expression for quality profile names to print",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pattern = re.compile(args.profile_regex, re.IGNORECASE)
    report = {"instances": [summarize_instance(instance, pattern) for instance in INSTANCES]}
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        print_text(report)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
