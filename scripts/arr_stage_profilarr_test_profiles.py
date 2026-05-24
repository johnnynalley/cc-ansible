#!/usr/bin/env python3
"""Snapshot Arr release policy and clone anime profiles for Profilarr testing.

Run this on media-vm. It reads local Sonarr/Radarr config.xml files for API
keys, writes JSON snapshots under /opt/media-stack, and creates or refreshes
test quality profiles without changing any series/movie assignments.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_CF_LIMIT = 100


@dataclass(frozen=True)
class ArrProfileSpec:
    name: str
    base_url: str
    config_path: str
    source_profile_name: str
    test_profile_name: str
    assignment_path: str
    assignment_label: str


INSTANCES = (
    ArrProfileSpec(
        name="sonarr",
        base_url="http://127.0.0.1:8989",
        config_path="/opt/media-stack/sonarr/config.xml",
        source_profile_name="shows-anime",
        test_profile_name="shows-anime-profilarr-test",
        assignment_path="/api/v3/series",
        assignment_label="series",
    ),
    ArrProfileSpec(
        name="radarr",
        base_url="http://127.0.0.1:7878",
        config_path="/opt/media-stack/radarr/config.xml",
        source_profile_name="movies-anime",
        test_profile_name="movies-anime-profilarr-test",
        assignment_path="/api/v3/movie",
        assignment_label="movies",
    ),
)


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def request_json(
    spec: ArrProfileSpec,
    api_key: str,
    method: str,
    path: str,
    body: Any | None = None,
) -> Any:
    data = None
    headers = {"X-Api-Key": api_key}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{spec.base_url.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.status == 204:
                return None
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{spec.name}: {method} {path} failed: {exc.code} {detail}") from exc


def find_one(items: list[dict[str, Any]], name: str, item_type: str) -> dict[str, Any] | None:
    matches = [item for item in items if item.get("name") == name]
    if len(matches) > 1:
        raise RuntimeError(f"multiple {item_type} entries named {name!r}")
    return matches[0] if matches else None


def clone_profile_payload(source: dict[str, Any], target_name: str, target_id: int | None) -> dict[str, Any]:
    payload = copy.deepcopy(source)
    payload["name"] = target_name
    if target_id is None:
        payload.pop("id", None)
    else:
        payload["id"] = target_id
    return payload


def profile_assignment_count(
    assignments: list[dict[str, Any]], profile_id: int | None
) -> int:
    if profile_id is None:
        return 0
    return sum(1 for item in assignments if item.get("qualityProfileId") == profile_id)


def snapshot_instance(
    spec: ArrProfileSpec,
    api_key: str,
    snapshot_dir: Path,
) -> dict[str, Any]:
    data = {
        "custom_formats": request_json(spec, api_key, "GET", "/api/v3/customformat"),
        "quality_profiles": request_json(spec, api_key, "GET", "/api/v3/qualityprofile"),
        "naming": request_json(spec, api_key, "GET", "/api/v3/config/naming"),
        "queue_status": request_json(spec, api_key, "GET", "/api/v3/queue/status"),
        "assignments": request_json(spec, api_key, "GET", spec.assignment_path),
    }
    for key, value in data.items():
        path = snapshot_dir / f"{spec.name}-{key.replace('_', '-')}.json"
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    return data


def stage_profile(
    spec: ArrProfileSpec,
    api_key: str,
    quality_profiles: list[dict[str, Any]],
) -> tuple[str, int]:
    source = find_one(quality_profiles, spec.source_profile_name, "quality profile")
    if source is None:
        raise RuntimeError(f"{spec.name}: missing source profile {spec.source_profile_name!r}")
    existing = find_one(quality_profiles, spec.test_profile_name, "quality profile")
    target_id = int(existing["id"]) if existing and isinstance(existing.get("id"), int) else None
    payload = clone_profile_payload(source, spec.test_profile_name, target_id)
    if target_id is None:
        created = request_json(spec, api_key, "POST", "/api/v3/qualityprofile", payload)
        return "created", int(created["id"])
    request_json(spec, api_key, "PUT", f"/api/v3/qualityprofile/{target_id}", payload)
    return "refreshed", target_id


def process_instance(
    spec: ArrProfileSpec,
    snapshot_dir: Path,
    cf_limit: int,
    dry_run: bool,
) -> dict[str, Any]:
    api_key = read_api_key(spec.config_path)
    before = snapshot_instance(spec, api_key, snapshot_dir)
    custom_formats = before["custom_formats"]
    profiles = before["quality_profiles"]
    assignments = before["assignments"]
    source = find_one(profiles, spec.source_profile_name, "quality profile")
    existing = find_one(profiles, spec.test_profile_name, "quality profile")
    source_id = int(source["id"]) if source and isinstance(source.get("id"), int) else None
    existing_id = int(existing["id"]) if existing and isinstance(existing.get("id"), int) else None

    if len(custom_formats) > cf_limit:
        raise RuntimeError(
            f"{spec.name}: custom format count {len(custom_formats)} exceeds configured limit {cf_limit}"
        )

    action = "dry-run"
    test_profile_id = existing_id
    if not dry_run:
        action, test_profile_id = stage_profile(spec, api_key, profiles)

    refreshed_profiles = request_json(spec, api_key, "GET", "/api/v3/qualityprofile")
    refreshed_test = find_one(refreshed_profiles, spec.test_profile_name, "quality profile")
    refreshed_test_id = (
        int(refreshed_test["id"])
        if refreshed_test and isinstance(refreshed_test.get("id"), int)
        else test_profile_id
    )

    return {
        "instance": spec.name,
        "source_profile": spec.source_profile_name,
        "source_profile_id": source_id,
        "test_profile": spec.test_profile_name,
        "test_profile_id": refreshed_test_id,
        "action": action,
        "custom_format_count": len(custom_formats),
        "custom_format_limit": cf_limit,
        "quality_profile_count_before": len(profiles),
        "quality_profile_count_after": len(refreshed_profiles),
        "source_assignment_count": profile_assignment_count(assignments, source_id),
        "test_assignment_count": profile_assignment_count(assignments, refreshed_test_id),
        "queue_status": before["queue_status"],
        "snapshot_dir": str(snapshot_dir),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot-root",
        default="/opt/media-stack/release-policy-snapshots",
        help="directory where timestamped Arr policy snapshots are written",
    )
    parser.add_argument(
        "--cf-limit",
        type=int,
        default=DEFAULT_CF_LIMIT,
        help="maximum allowed custom-format count before refusing to stage",
    )
    parser.add_argument("--dry-run", action="store_true", help="snapshot and report without creating profiles")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_dir = Path(args.snapshot_root) / timestamp
    snapshot_dir.mkdir(parents=True, exist_ok=False)

    results = [
        process_instance(spec, snapshot_dir, args.cf_limit, args.dry_run)
        for spec in INSTANCES
    ]
    report = {
        "snapshot_dir": str(snapshot_dir),
        "dry_run": args.dry_run,
        "instances": results,
    }

    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        print(f"Snapshot: {snapshot_dir}")
        for result in results:
            print(
                "{instance}: {action} {test_profile} id={test_profile_id}; "
                "CFs {custom_format_count}/{custom_format_limit}; "
                "{source_profile} assignments={source_assignment_count}; "
                "test assignments={test_assignment_count}; queue={queue_status}".format(**result)
            )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
