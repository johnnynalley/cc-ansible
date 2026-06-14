#!/usr/bin/env python3
"""Set Arr efficient-profile cutoff scores to the exact positive CF ceiling.

Run this on docker-vm. It reads local Sonarr/Radarr config.xml files for API
keys, snapshots live Arr policy state before apply, and updates matching quality
profiles so cutoffFormatScore equals the sum of every positive custom-format
score present on that profile.

Negative scores are intentionally excluded from the ceiling because the maximum
possible score path avoids matching negative formats. Dry-run is the default.
The script prints no API keys.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_BACKUP_ROOT = "/srv/live-rollbacks/docker-vm/arr-policy"
DEFAULT_PROFILE_PATTERN = r"-efficient$"


@dataclass(frozen=True)
class ArrInstance:
    name: str
    base_url: str
    config_path: str


ARR_INSTANCES = (
    ArrInstance("sonarr", "http://127.0.0.1:8989", "/opt/media-stack/sonarr/config.xml"),
    ArrInstance("radarr", "http://127.0.0.1:7878", "/opt/media-stack/radarr/config.xml"),
)


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def request_json(
    instance: ArrInstance,
    api_key: str,
    method: str,
    path: str,
    body: Any | None = None,
    timeout: int = 90,
) -> Any:
    data = None
    headers = {"X-Api-Key": api_key}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{instance.base_url.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status == 204:
                return None
            payload = response.read()
            if not payload:
                return None
            return json.loads(payload.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{instance.name}: {method} {path} failed: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{instance.name}: {method} {path} failed: {exc.reason}") from exc


def write_snapshot(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ensure_live_rollback_mount(backup_root: Path) -> None:
    live_root = Path("/srv/live-rollbacks")
    try:
        backup_root.relative_to(live_root)
    except ValueError:
        return
    mounts = Path("/proc/mounts").read_text(encoding="utf-8").splitlines()
    if not any(line.split()[1] == str(live_root) for line in mounts if line.split()):
        raise RuntimeError(f"{live_root} is not mounted; refusing to write rollback backup to root disk")


def mark_live_rollback_cache(backup_dir: Path, timestamp: str) -> None:
    (backup_dir / "manifest.txt").write_text(
        "\n".join(
            (
                f"created_utc={timestamp}",
                "host=docker-vm",
                "domain=arr-policy",
                "name=arr-cutoff-ceiling-policy",
                "paths=",
                "  Sonarr/Radarr API policy snapshots",
                "",
            )
        ),
        encoding="utf-8",
    )
    (backup_dir / ".live-rollback-cache").write_text(
        "\n".join(
            (
                f"created_utc={timestamp}",
                "host=docker-vm",
                "domain=arr-policy",
                "",
            )
        ),
        encoding="utf-8",
    )


def snapshot_instance(
    instance: ArrInstance,
    api_key: str,
    backup_dir: Path,
) -> dict[str, Any]:
    data = {
        "custom_formats": request_json(instance, api_key, "GET", "/api/v3/customformat"),
        "quality_profiles": request_json(instance, api_key, "GET", "/api/v3/qualityprofile"),
        "queue_status": request_json(instance, api_key, "GET", "/api/v3/queue/status"),
        "commands": request_json(instance, api_key, "GET", "/api/v3/command"),
    }
    for name, value in data.items():
        write_snapshot(backup_dir / f"{instance.name}-{name.replace('_', '-')}.json", value)
    return data


def custom_format_id_from_item(item: dict[str, Any]) -> int | None:
    value = item.get("format")
    if isinstance(value, dict):
        value = value.get("id")
    if value is None:
        value = item.get("customFormatId")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def custom_format_name_from_item(
    item: dict[str, Any],
    custom_formats_by_id: dict[int, dict[str, Any]],
) -> str:
    value = item.get("format")
    if isinstance(value, dict) and value.get("name"):
        return str(value["name"])
    cf_id = custom_format_id_from_item(item)
    if cf_id is not None and cf_id in custom_formats_by_id:
        return str(custom_formats_by_id[cf_id].get("name") or f"id:{cf_id}")
    return str(item.get("name") or f"id:{cf_id}")


def positive_components(
    profile: dict[str, Any],
    custom_formats_by_id: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    for item in profile.get("formatItems") or []:
        score = int(item.get("score") or 0)
        if score <= 0:
            continue
        components.append(
            {
                "custom_format_id": custom_format_id_from_item(item),
                "name": custom_format_name_from_item(item, custom_formats_by_id),
                "score": score,
            }
        )
    return sorted(components, key=lambda item: (-int(item["score"]), str(item["name"])))


def ceiling_score(components: list[dict[str, Any]]) -> int:
    return sum(int(item["score"]) for item in components)


def profile_matches(profile: dict[str, Any], pattern: re.Pattern[str]) -> bool:
    return pattern.search(str(profile.get("name") or "")) is not None


def update_instance(
    instance: ArrInstance,
    data: dict[str, Any],
    profile_pattern: re.Pattern[str],
    apply: bool,
    component_limit: int,
) -> dict[str, Any]:
    api_key = read_api_key(instance.config_path)
    custom_formats_by_id = {
        int(cf["id"]): cf
        for cf in data["custom_formats"]
        if isinstance(cf.get("id"), int)
    }
    profile_reports: list[dict[str, Any]] = []
    for profile in data["quality_profiles"]:
        profile_name = str(profile.get("name") or "")
        if not profile_matches(profile, profile_pattern):
            continue
        profile_id = profile.get("id")
        if not isinstance(profile_id, int):
            raise RuntimeError(f"{instance.name}:{profile_name}: profile has no numeric id")
        components = positive_components(profile, custom_formats_by_id)
        desired = ceiling_score(components)
        current = int(profile.get("cutoffFormatScore") or 0)
        changed = current != desired
        if changed and apply:
            payload = copy.deepcopy(profile)
            payload["cutoffFormatScore"] = desired
            request_json(instance, api_key, "PUT", f"/api/v3/qualityprofile/{profile_id}", payload)
        profile_reports.append(
            {
                "id": profile_id,
                "name": profile_name,
                "current_cutoff_format_score": current,
                "desired_cutoff_format_score": desired,
                "changed": changed,
                "positive_component_count": len(components),
                "positive_components": components[:component_limit],
                "positive_components_truncated": max(0, len(components) - component_limit),
            }
        )
    return {"instance": instance.name, "profiles": profile_reports}


def load_live_data(
    api_keys: dict[str, str],
    backup_dir: Path | None,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for instance in ARR_INSTANCES:
        api_key = api_keys[instance.name]
        if backup_dir is None:
            result[instance.name] = {
                "custom_formats": request_json(instance, api_key, "GET", "/api/v3/customformat"),
                "quality_profiles": request_json(instance, api_key, "GET", "/api/v3/qualityprofile"),
            }
        else:
            result[instance.name] = snapshot_instance(instance, api_key, backup_dir)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write updated cutoffFormatScore values")
    parser.add_argument("--backup-root", default=DEFAULT_BACKUP_ROOT)
    parser.add_argument(
        "--profile-pattern",
        default=DEFAULT_PROFILE_PATTERN,
        help="regex for target quality-profile names; default targets active efficient profiles",
    )
    parser.add_argument(
        "--component-limit",
        type=int,
        default=25,
        help="maximum positive CF components to print per profile",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    profile_pattern = re.compile(args.profile_pattern)
    api_keys = {instance.name: read_api_key(instance.config_path) for instance in ARR_INSTANCES}

    backup_dir: Path | None = None
    if args.apply:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_root = Path(args.backup_root)
        ensure_live_rollback_mount(backup_root)
        backup_dir = backup_root / f"{timestamp}-arr-cutoff-ceiling-policy"
        backup_dir.mkdir(parents=True, exist_ok=False)
        mark_live_rollback_cache(backup_dir, timestamp)

    data = load_live_data(api_keys, backup_dir)
    reports = [
        update_instance(
            instance,
            data[instance.name],
            profile_pattern,
            args.apply,
            args.component_limit,
        )
        for instance in ARR_INSTANCES
    ]
    matched = sum(len(report["profiles"]) for report in reports)
    if matched == 0:
        raise RuntimeError(f"no profiles matched regex {args.profile_pattern!r}")
    print(
        json.dumps(
            {
                "applied": args.apply,
                "backup_dir": str(backup_dir) if backup_dir is not None else None,
                "profile_pattern": args.profile_pattern,
                "instances": reports,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
