#!/usr/bin/env python3
"""Check that Arr media and Seerr defaults use only efficient profiles.

Run this on docker-vm. It reads local Arr/Seerr config files for API access,
prints no secrets, and exits non-zero if any series, movie, or request default
uses a balanced, test, old, or unknown profile.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_SEERR_URL = "http://127.0.0.1:5055/api/v1"
DEFAULT_SEERR_SETTINGS = "/opt/seerr/config/settings.json"


@dataclass(frozen=True)
class ArrInstance:
    name: str
    base_url: str
    config_path: str
    assignment_path: str
    allowed_profiles: tuple[str, ...]


INSTANCES = (
    ArrInstance(
        name="sonarr",
        base_url="http://127.0.0.1:8989",
        config_path="/opt/media-stack/sonarr/config.xml",
        assignment_path="/api/v3/series",
        allowed_profiles=("shows-anime-efficient", "shows-regular-efficient"),
    ),
    ArrInstance(
        name="radarr",
        base_url="http://127.0.0.1:7878",
        config_path="/opt/media-stack/radarr/config.xml",
        assignment_path="/api/v3/movie",
        allowed_profiles=("movies-anime-efficient", "movies-regular-efficient"),
    ),
)


FORBIDDEN_NAMES = {
    "shows-anime",
    "shows-regular",
    "movies-anime",
    "movies-regular",
}


def read_arr_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def read_seerr_api_key(path: Path) -> str:
    settings = json.loads(path.read_text(encoding="utf-8"))
    key = ((settings.get("main") or {}).get("apiKey") or "").strip()
    if not key:
        raise RuntimeError(f"{path}: main.apiKey was not found")
    return key


def request_json(
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    api_key_header: str = "X-Api-Key",
) -> Any:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers={api_key_header: api_key},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = response.read()
            if not payload:
                return None
            return json.loads(payload.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {path} failed: {exc.reason}") from exc


def profile_is_forbidden(name: str | None) -> bool:
    if not name:
        return True
    return (
        name in FORBIDDEN_NAMES
        or name.endswith("-balanced")
        or name.endswith("-profilarr-test")
    )


def check_arr(instance: ArrInstance) -> dict[str, Any]:
    api_key = read_arr_api_key(instance.config_path)
    profiles = request_json(instance.base_url, api_key, "GET", "/api/v3/qualityprofile")
    assignments = request_json(instance.base_url, api_key, "GET", instance.assignment_path)
    names_by_id = {
        int(profile["id"]): str(profile["name"])
        for profile in profiles
        if isinstance(profile.get("id"), int)
    }
    counts: dict[str, int] = {}
    bad: list[dict[str, Any]] = []
    allowed = set(instance.allowed_profiles)
    for item in assignments:
        profile_id = item.get("qualityProfileId")
        profile_name = names_by_id.get(profile_id, f"unknown:{profile_id}")
        counts[profile_name] = counts.get(profile_name, 0) + 1
        if profile_name not in allowed or profile_is_forbidden(profile_name):
            bad.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "qualityProfileId": profile_id,
                    "qualityProfileName": profile_name,
                }
            )
    return {"counts": counts, "bad": bad[:25], "bad_count": len(bad)}


def check_seerr(seerr_url: str, settings_path: Path) -> dict[str, Any]:
    api_key = read_seerr_api_key(settings_path)
    results: dict[str, Any] = {}
    for section in ("sonarr", "radarr"):
        rows = request_json(seerr_url, api_key, "GET", f"/settings/{section}", api_key_header="X-API-Key")
        bad: list[dict[str, Any]] = []
        compact: list[dict[str, Any]] = []
        for item in rows:
            row = {
                "id": item.get("id"),
                "name": item.get("name"),
                "hostname": item.get("hostname"),
                "port": item.get("port"),
            }
            for key in ("activeProfileName", "activeAnimeProfileName"):
                if key in item:
                    row[key] = item.get(key)
                    if profile_is_forbidden(item.get(key)):
                        bad.append(row)
            compact.append(row)
        results[section] = {"settings": compact, "bad": bad, "bad_count": len(bad)}
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--seerr-url", default=DEFAULT_SEERR_URL)
    parser.add_argument("--seerr-settings", type=Path, default=Path(DEFAULT_SEERR_SETTINGS))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = {
        "arr": {instance.name: check_arr(instance) for instance in INSTANCES},
        "seerr": check_seerr(args.seerr_url, args.seerr_settings),
    }
    failures: list[str] = []
    for name, result in report["arr"].items():
        if result["bad_count"]:
            failures.append(f"{name}: {result['bad_count']} media items use non-efficient profiles")
    for name, result in report["seerr"].items():
        if result["bad_count"]:
            failures.append(f"seerr {name}: {result['bad_count']} defaults use forbidden profiles")
    report["failures"] = failures

    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        for name, result in report["arr"].items():
            print(f"{name}: counts={result['counts']} bad={result['bad_count']}")
        for name, result in report["seerr"].items():
            print(f"seerr {name}: bad={result['bad_count']} settings={result['settings']}")
        if failures:
            print("FAIL:")
            for failure in failures:
                print(f"  - {failure}")
        else:
            print("PASS: all Arr media and Seerr defaults use efficient profiles")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
