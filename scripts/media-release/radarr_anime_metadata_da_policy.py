#!/usr/bin/env python3
"""Score Radarr anime metadata DA exactly once.

Run this on docker-vm. It reads the local Radarr config.xml for the API key,
snapshots the touched Radarr policy state before apply, creates/updates a
duplicate guard custom format, and updates only `movies-anime-efficient` scores.

The intended score model is:
- title-only DA: +100000
- metadata-only DA: +100000
- title + metadata DA: +100000 +100000 -100000 = +100000

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
TITLE_DA_CF_NAME = "Anime Dual Audio"
METADATA_DA_CF_NAME = "Anime - Dual Audio (Metadata)"
TITLE_HELPER_CF_NAME = "Anime - Dual Audio (Title)"
REGULAR_DA_CF_NAME = "Regular Dual Audio"
GUARD_CF_NAME = "Anime Dual Audio - Metadata/Title Duplicate Guard"
DA_SCORE = 100000
GUARD_SCORE = -100000


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
                "name=radarr-anime-metadata-da-policy",
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


def find_optional(items: list[dict[str, Any]], name: str, kind: str) -> dict[str, Any] | None:
    matches = [item for item in items if item.get("name") == name]
    if len(matches) > 1:
        raise RuntimeError(f"expected at most one {kind} named {name!r}, found {len(matches)}")
    return matches[0] if matches else None


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
        scores[custom_format_name_from_item(item, custom_formats_by_id)] = int(item.get("score") or 0)
    return scores


def assert_expected_existing_scores(scores: dict[str, int]) -> None:
    expected = {
        TITLE_DA_CF_NAME: {DA_SCORE},
        METADATA_DA_CF_NAME: {0, DA_SCORE},
        TITLE_HELPER_CF_NAME: {0},
        REGULAR_DA_CF_NAME: {0},
        GUARD_CF_NAME: {0, GUARD_SCORE},
    }
    unexpected = {
        name: scores.get(name, 0)
        for name, allowed in expected.items()
        if scores.get(name, 0) not in allowed
    }
    if unexpected:
        detail = ", ".join(f"{name}={score}" for name, score in sorted(unexpected.items()))
        raise RuntimeError(f"{TARGET_PROFILE_NAME}: refusing to change unexpected DA scores: {detail}")


def guard_payload(
    existing: dict[str, Any] | None,
    metadata_cf: dict[str, Any],
    title_cf: dict[str, Any],
) -> dict[str, Any]:
    payload = copy.deepcopy(existing) if existing is not None else {}
    if existing is not None and isinstance(existing.get("id"), int):
        payload["id"] = existing["id"]
    metadata_specs = copy.deepcopy(metadata_cf.get("specifications") or [])
    title_specs = copy.deepcopy(title_cf.get("specifications") or [])
    if not metadata_specs:
        raise RuntimeError(f"{METADATA_DA_CF_NAME}: no specifications found")
    if not title_specs:
        raise RuntimeError(f"{TITLE_DA_CF_NAME}: no specifications found")
    payload["name"] = GUARD_CF_NAME
    payload["includeCustomFormatWhenRenaming"] = False
    payload["specifications"] = metadata_specs + title_specs
    return payload


def upsert_guard(
    api_key: str,
    custom_formats: list[dict[str, Any]],
    apply: bool,
) -> tuple[dict[str, Any], str]:
    metadata_cf = find_one(custom_formats, METADATA_DA_CF_NAME, "custom format")
    title_cf = find_one(custom_formats, TITLE_DA_CF_NAME, "custom format")
    existing = find_optional(custom_formats, GUARD_CF_NAME, "custom format")
    payload = guard_payload(existing, metadata_cf, title_cf)
    changed = (
        existing is None
        or json.dumps(existing, sort_keys=True) != json.dumps(payload, sort_keys=True)
    )
    if not apply:
        if existing is None:
            return payload, "would-create"
        return payload, "would-update" if changed else "unchanged"
    if existing is None:
        return request_json(api_key, "POST", "/api/v3/customformat", payload), "created"
    if not changed:
        return existing, "unchanged"
    return request_json(api_key, "PUT", f"/api/v3/customformat/{existing['id']}", payload), "updated"


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


def set_existing_profile_score(profile: dict[str, Any], cf_id: int, cf_name: str, score: int) -> bool:
    for item in profile.get("formatItems") or []:
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
    return False


def update_profiles(
    api_key: str,
    custom_formats: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
    guard_cf: dict[str, Any],
    apply: bool,
) -> list[dict[str, Any]]:
    custom_formats_by_name = {str(cf.get("name") or ""): cf for cf in custom_formats}
    custom_formats_by_name[GUARD_CF_NAME] = guard_cf
    custom_formats_by_id = {
        int(cf["id"]): cf
        for cf in custom_formats_by_name.values()
        if isinstance(cf.get("id"), int)
    }
    required_ids = {
        name: int(custom_formats_by_name[name]["id"])
        for name in (TITLE_DA_CF_NAME, METADATA_DA_CF_NAME, TITLE_HELPER_CF_NAME, REGULAR_DA_CF_NAME, GUARD_CF_NAME)
        if isinstance(custom_formats_by_name.get(name, {}).get("id"), int)
    }
    if apply and GUARD_CF_NAME not in required_ids:
        raise RuntimeError(f"{GUARD_CF_NAME}: no numeric id available; apply is required before profile update")
    guard_cf_id = required_ids.get(GUARD_CF_NAME)

    changes: list[dict[str, Any]] = []
    for profile in profiles:
        profile_id = profile.get("id")
        profile_name = str(profile.get("name") or "")
        payload = copy.deepcopy(profile)
        changed = False
        if profile_name == TARGET_PROFILE_NAME:
            if not isinstance(profile_id, int):
                raise RuntimeError(f"{profile_name}: profile has no numeric id")
            assert_expected_existing_scores(profile_scores(profile, custom_formats_by_id))
            changed |= set_profile_score(payload, required_ids[METADATA_DA_CF_NAME], METADATA_DA_CF_NAME, DA_SCORE)
            if guard_cf_id is None:
                changed = True
            else:
                changed |= set_profile_score(payload, guard_cf_id, GUARD_CF_NAME, GUARD_SCORE)
            changed |= set_existing_profile_score(payload, required_ids[TITLE_HELPER_CF_NAME], TITLE_HELPER_CF_NAME, 0)
            changed |= set_existing_profile_score(payload, required_ids[REGULAR_DA_CF_NAME], REGULAR_DA_CF_NAME, 0)
        elif guard_cf_id is not None:
            changed |= set_existing_profile_score(payload, guard_cf_id, GUARD_CF_NAME, 0)

        if changed and apply:
            if not isinstance(profile_id, int):
                raise RuntimeError(f"{profile_name}: profile has no numeric id")
            request_json(api_key, "PUT", f"/api/v3/qualityprofile/{profile_id}", payload)
        changes.append({"id": profile_id, "name": profile_name, "changed": changed})
    return changes


def score_model() -> dict[str, int]:
    return {
        "title_only": DA_SCORE,
        "metadata_only": DA_SCORE,
        "title_and_metadata": DA_SCORE + DA_SCORE + GUARD_SCORE,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the updated custom format and profile")
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
        backup_dir = backup_root / f"{timestamp}-radarr-anime-metadata-da-policy"
        backup_dir.mkdir(parents=True, exist_ok=False)
        data = snapshot_radarr(api_key, backup_dir)
        mark_live_rollback_cache(backup_dir, timestamp)
    else:
        data = {
            "custom_formats": request_json(api_key, "GET", "/api/v3/customformat"),
            "quality_profiles": request_json(api_key, "GET", "/api/v3/qualityprofile"),
        }

    guard_cf, guard_action = upsert_guard(api_key, data["custom_formats"], args.apply)
    effective_custom_formats = [
        cf for cf in data["custom_formats"] if cf.get("name") != GUARD_CF_NAME
    ] + [guard_cf]
    profile_changes = update_profiles(
        api_key,
        effective_custom_formats,
        data["quality_profiles"],
        guard_cf,
        args.apply,
    )
    result = {
        "applied": args.apply,
        "backup_dir": str(backup_dir) if backup_dir is not None else None,
        "guard": {
            "action": guard_action,
            "id": guard_cf.get("id"),
            "name": GUARD_CF_NAME,
            "spec_count": len(guard_cf.get("specifications") or []),
        },
        "profile_changes": profile_changes,
        "score_model": score_model(),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
