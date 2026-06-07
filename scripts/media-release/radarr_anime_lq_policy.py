#!/usr/bin/env python3
"""Soften Radarr anime LQ penalties without removing them.

Run this on docker-vm. It reads the local Radarr config.xml for the API key,
snapshots the touched Radarr policy state before apply, and updates only the
LQ custom-format scores on `movies-anime-efficient`.

Dry-run is the default. The script prints no API keys.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RADARR_URL = "http://127.0.0.1:7878"
RADARR_CONFIG = "/opt/media-stack/radarr/config.xml"
DEFAULT_BACKUP_ROOT = "/srv/live-rollbacks/docker-vm/arr-policy"
TARGET_PROFILE_NAME = "movies-anime-efficient"
TARGET_SCORE = -20000
EXPECTED_PRIOR_SCORES = {-1000000, TARGET_SCORE}
LQ_FORMAT_NAMES = (
    "Anime LQ Groups",
    "LQ",
    "LQ (Release Title)",
)


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def request_json(
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
        f"{RADARR_URL.rstrip('/')}{path}",
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
        raise RuntimeError(f"radarr: {method} {path} failed: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"radarr: {method} {path} failed: {exc.reason}") from exc


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
                "name=radarr-anime-lq-policy",
                "paths=",
                "  radarr API policy snapshot",
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


def snapshot_radarr(api_key: str, backup_dir: Path) -> dict[str, Any]:
    data = {
        "custom_formats": request_json(api_key, "GET", "/api/v3/customformat"),
        "quality_profiles": request_json(api_key, "GET", "/api/v3/qualityprofile"),
        "queue_status": request_json(api_key, "GET", "/api/v3/queue/status"),
        "commands": request_json(api_key, "GET", "/api/v3/command"),
    }
    for name, value in data.items():
        write_snapshot(backup_dir / f"radarr-{name.replace('_', '-')}.json", value)
    return data


def find_one(items: list[dict[str, Any]], name: str, kind: str) -> dict[str, Any]:
    matches = [item for item in items if item.get("name") == name]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {kind} named {name!r}, found {len(matches)}")
    return matches[0]


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


def profile_scores(
    profile: dict[str, Any],
    custom_formats_by_id: dict[int, dict[str, Any]],
) -> dict[str, int]:
    scores: dict[str, int] = {}
    for item in profile.get("formatItems") or []:
        name = custom_format_name_from_item(item, custom_formats_by_id)
        scores[name] = int(item.get("score") or 0)
    return scores


def set_profile_score(profile: dict[str, Any], cf_id: int, cf_name: str, score: int) -> bool:
    items = profile.setdefault("formatItems", [])
    for item in items:
        if custom_format_id_from_item(item) == cf_id:
            changed = (
                item.get("format") != cf_id
                or item.get("name") != cf_name
                or int(item.get("score") or 0) != score
            )
            item["format"] = cf_id
            item["name"] = cf_name
            item["score"] = score
            return changed
    items.append({"format": cf_id, "name": cf_name, "score": score})
    return True


def update_target_profile(
    api_key: str,
    custom_formats: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
    score: int,
    apply: bool,
) -> dict[str, Any]:
    custom_formats_by_name = {str(cf.get("name") or ""): cf for cf in custom_formats}
    custom_formats_by_id = {int(cf["id"]): cf for cf in custom_formats if isinstance(cf.get("id"), int)}
    target_profile = find_one(profiles, TARGET_PROFILE_NAME, "quality profile")
    profile_id = target_profile.get("id")
    if not isinstance(profile_id, int):
        raise RuntimeError(f"{TARGET_PROFILE_NAME}: profile has no numeric id")

    current_scores = profile_scores(target_profile, custom_formats_by_id)
    unexpected = {
        name: current_scores.get(name)
        for name in LQ_FORMAT_NAMES
        if current_scores.get(name) not in EXPECTED_PRIOR_SCORES
    }
    if unexpected:
        detail = ", ".join(f"{name}={value}" for name, value in sorted(unexpected.items()))
        raise RuntimeError(
            f"{TARGET_PROFILE_NAME}: refusing to change unexpected LQ scores: {detail}"
        )

    payload = copy.deepcopy(target_profile)
    changes: list[dict[str, Any]] = []
    for name in LQ_FORMAT_NAMES:
        cf = custom_formats_by_name.get(name)
        if cf is None or not isinstance(cf.get("id"), int):
            raise RuntimeError(f"missing custom format {name!r}")
        before = current_scores.get(name)
        changed = set_profile_score(payload, int(cf["id"]), name, score)
        changes.append({"name": name, "before": before, "after": score, "changed": changed})

    profile_changed = any(item["changed"] for item in changes)
    if profile_changed and apply:
        request_json(api_key, "PUT", f"/api/v3/qualityprofile/{profile_id}", payload)

    return {
        "profile": TARGET_PROFILE_NAME,
        "profile_id": profile_id,
        "applied": apply,
        "changed": profile_changed,
        "scores": changes,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the updated profile")
    parser.add_argument("--score", type=int, default=TARGET_SCORE)
    parser.add_argument("--backup-root", default=DEFAULT_BACKUP_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = read_api_key(RADARR_CONFIG)
    backup_dir: Path | None = None
    if args.apply:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_root = Path(args.backup_root)
        ensure_live_rollback_mount(backup_root)
        backup_dir = backup_root / f"{timestamp}-radarr-anime-lq-policy"
        backup_dir.mkdir(parents=True, exist_ok=False)
        data = snapshot_radarr(api_key, backup_dir)
        mark_live_rollback_cache(backup_dir, timestamp)
    else:
        data = {
            "custom_formats": request_json(api_key, "GET", "/api/v3/customformat"),
            "quality_profiles": request_json(api_key, "GET", "/api/v3/qualityprofile"),
        }

    result = update_target_profile(
        api_key,
        data["custom_formats"],
        data["quality_profiles"],
        args.score,
        args.apply,
    )
    result["backup_dir"] = str(backup_dir) if backup_dir is not None else None
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
