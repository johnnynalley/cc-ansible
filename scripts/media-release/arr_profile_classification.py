#!/usr/bin/env python3
"""Audit or repair Sonarr/Radarr media profile classification.

Run this on docker-vm. It reads local Sonarr/Radarr config.xml files for API
keys, snapshots Arr state before any repair, and assigns media to the expected
efficient profile:

- anime -> anime efficient
- non-anime English-original -> regular efficient
- non-anime non-English-original -> regular dual-audio efficient

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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_BACKUP_ROOT = "/opt/media-stack/arr-policy-backups"


@dataclass(frozen=True)
class ArrInstance:
    name: str
    base_url: str
    config_path: str
    assignment_path: str
    regular_profile: str
    anime_profile: str
    regular_dual_audio_profile: str


INSTANCES = (
    ArrInstance(
        name="sonarr",
        base_url="http://127.0.0.1:8989",
        config_path="/opt/media-stack/sonarr/config.xml",
        assignment_path="/api/v3/series",
        regular_profile="shows-regular-efficient",
        anime_profile="shows-anime-efficient",
        regular_dual_audio_profile="shows-regular-dual-audio-efficient",
    ),
    ArrInstance(
        name="radarr",
        base_url="http://127.0.0.1:7878",
        config_path="/opt/media-stack/radarr/config.xml",
        assignment_path="/api/v3/movie",
        regular_profile="movies-regular-efficient",
        anime_profile="movies-anime-efficient",
        regular_dual_audio_profile="movies-regular-dual-audio-efficient",
    ),
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


def snapshot_instance(instance: ArrInstance, api_key: str, backup_dir: Path) -> dict[str, Any]:
    data = {
        "quality_profiles": request_json(instance, api_key, "GET", "/api/v3/qualityprofile"),
        "assignments": request_json(instance, api_key, "GET", instance.assignment_path),
        "queue_status": request_json(instance, api_key, "GET", "/api/v3/queue/status"),
        "commands": request_json(instance, api_key, "GET", "/api/v3/command"),
    }
    for name, value in data.items():
        write_snapshot(backup_dir / f"{instance.name}-{name.replace('_', '-')}.json", value)
    return data


def fetch_instance_state(instance: ArrInstance, api_key: str) -> dict[str, Any]:
    return {
        "quality_profiles": request_json(instance, api_key, "GET", "/api/v3/qualityprofile"),
        "assignments": request_json(instance, api_key, "GET", instance.assignment_path),
        "queue_status": request_json(instance, api_key, "GET", "/api/v3/queue/status"),
        "commands": request_json(instance, api_key, "GET", "/api/v3/command"),
    }


def profile_names_by_id(profiles: list[dict[str, Any]]) -> dict[int, str]:
    return {
        int(profile["id"]): str(profile.get("name") or profile["id"])
        for profile in profiles
        if isinstance(profile.get("id"), int)
    }


def profile_ids_by_name(profiles: list[dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for profile in profiles:
        profile_id = profile.get("id")
        name = profile.get("name")
        if isinstance(profile_id, int) and isinstance(name, str):
            result[name] = profile_id
    return result


def item_language_name(item: dict[str, Any]) -> str:
    value = item.get("originalLanguage")
    if isinstance(value, dict):
        return str(value.get("name") or value.get("id") or "")
    return str(value or "")


def item_genres(item: dict[str, Any]) -> list[str]:
    genres = item.get("genres")
    if not isinstance(genres, list):
        return []
    return [str(genre) for genre in genres if genre]


def is_non_english_language(name: str) -> bool:
    return bool(name) and name.casefold() not in {"english", "unknown"}


def is_probably_anime(instance: ArrInstance, item: dict[str, Any], current_profile: str | None) -> bool:
    if current_profile and "anime" in current_profile.casefold():
        return True
    if instance.name == "sonarr" and str(item.get("seriesType") or "").casefold() == "anime":
        return True
    genres = {genre.casefold() for genre in item_genres(item)}
    if "anime" in genres:
        return True
    if instance.name == "radarr" and item_language_name(item).casefold() == "japanese" and "animation" in genres:
        return True
    return False


def expected_profile_name(instance: ArrInstance, item: dict[str, Any], current_profile: str | None) -> tuple[str, str]:
    if is_probably_anime(instance, item, current_profile):
        return instance.anime_profile, "anime"
    language = item_language_name(item)
    if is_non_english_language(language):
        return instance.regular_dual_audio_profile, "non_english_regular"
    return instance.regular_profile, "english_regular"


def assignment_endpoint(instance: ArrInstance, item_id: int) -> str:
    return f"{instance.assignment_path}/{item_id}"


def queue_search(
    instance: ArrInstance,
    api_key: str,
    item: dict[str, Any],
    apply: bool,
) -> dict[str, Any]:
    if instance.name == "sonarr":
        body = {"name": "SeriesSearch", "seriesId": item["id"]}
    elif instance.name == "radarr":
        body = {"name": "MoviesSearch", "movieIds": [item["id"]]}
    else:
        raise RuntimeError(f"unknown Arr instance {instance.name}")
    if not apply:
        return {"title": item["title"], "command": body, "queued": False}
    command = request_json(instance, api_key, "POST", "/api/v3/command", body, timeout=30)
    return {
        "title": item["title"],
        "command": body,
        "queued": True,
        "id": command.get("id") if isinstance(command, dict) else None,
        "name": command.get("name") if isinstance(command, dict) else body["name"],
    }


def process_instance(
    instance: ArrInstance,
    backup_dir: Path | None,
    search_changed: bool,
    apply: bool,
) -> dict[str, Any]:
    api_key = read_api_key(instance.config_path)
    snapshot = (
        snapshot_instance(instance, api_key, backup_dir)
        if backup_dir is not None
        else fetch_instance_state(instance, api_key)
    )
    profiles = snapshot["quality_profiles"]
    assignments = snapshot["assignments"]
    names_by_id = profile_names_by_id(profiles)
    ids_by_name = profile_ids_by_name(profiles)

    required_profiles = (
        instance.regular_profile,
        instance.anime_profile,
        instance.regular_dual_audio_profile,
    )
    missing_profiles = [name for name in required_profiles if name not in ids_by_name]
    if missing_profiles:
        raise RuntimeError(f"{instance.name}: missing profiles: {', '.join(missing_profiles)}")

    counts_before: dict[str, int] = {}
    counts_expected: dict[str, int] = {}
    changes: list[dict[str, Any]] = []
    changed_items_by_id: dict[int, dict[str, Any]] = {}
    for item in assignments:
        item_id = item.get("id")
        profile_id = item.get("qualityProfileId")
        current_profile = names_by_id.get(profile_id, f"unknown:{profile_id}")
        expected_name, reason = expected_profile_name(instance, item, current_profile)
        expected_id = ids_by_name[expected_name]
        counts_before[current_profile] = counts_before.get(current_profile, 0) + 1
        counts_expected[expected_name] = counts_expected.get(expected_name, 0) + 1
        if not isinstance(item_id, int) or profile_id == expected_id:
            continue
        row = {
            "id": item_id,
            "title": item.get("title"),
            "original_language": item_language_name(item),
            "genres": item_genres(item),
            "series_type": item.get("seriesType"),
            "from": profile_id,
            "from_name": current_profile,
            "to": expected_id,
            "to_name": expected_name,
            "reason": reason,
        }
        if apply:
            payload = copy.deepcopy(item)
            payload["qualityProfileId"] = expected_id
            request_json(instance, api_key, "PUT", assignment_endpoint(instance, item_id), payload)
        changes.append(row)
        changed_items_by_id[item_id] = item

    search_commands: list[dict[str, Any]] = []
    search_errors: list[dict[str, Any]] = []
    if search_changed:
        for item in changed_items_by_id.values():
            try:
                search_commands.append(queue_search(instance, api_key, item, apply))
            except Exception as exc:  # noqa: BLE001 - keep other queued searches moving.
                search_errors.append({"id": item.get("id"), "title": item.get("title"), "error": str(exc)})

    return {
        "instance": instance.name,
        "counts_before": counts_before,
        "counts_expected": counts_expected,
        "changes": changes,
        "change_count": len(changes),
        "search_changed": search_changed,
        "search_commands": search_commands,
        "search_errors": search_errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="mutate live Arr assignments")
    parser.add_argument(
        "--search-changed",
        action="store_true",
        help="queue a SeriesSearch/MoviesSearch for every changed media item",
    )
    parser.add_argument("--backup-root", type=Path, default=Path(DEFAULT_BACKUP_ROOT))
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="skip read-only snapshot creation; rejected with --apply",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def print_instance_report(instance: dict[str, Any]) -> None:
    print(
        "{name}: changes={change_count} before={before} expected={expected}".format(
            name=instance["instance"],
            change_count=instance["change_count"],
            before=instance["counts_before"],
            expected=instance["counts_expected"],
        )
    )
    if instance["changes"]:
        print("  profile fixes:")
        for item in instance["changes"]:
            language = item["original_language"] or "unknown"
            print(
                "    - {title}: {from_name} -> {to_name} "
                "language={language} reason={reason}".format(
                    title=item["title"],
                    from_name=item["from_name"],
                    to_name=item["to_name"],
                    language=language,
                    reason=item["reason"],
                )
            )
    if instance["search_commands"]:
        print("  searches:")
        for command in instance["search_commands"]:
            action = "queued" if command["queued"] else "would-queue"
            command_id = f" id={command['id']}" if command.get("id") else ""
            print(f"    - {action}:{command_id} {command['title']}")
    if instance["search_errors"]:
        print("  search errors:")
        for error in instance["search_errors"]:
            print(f"    - {error['title']}: {error['error']}")


def main() -> int:
    args = parse_args()
    if args.apply and args.no_backup:
        raise RuntimeError("--no-backup is not allowed with --apply")
    backup_dir = None
    if not args.no_backup:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = args.backup_root / f"{timestamp}-profile-classification"
        backup_dir.mkdir(parents=True, exist_ok=False)

    report = {
        "mode": "apply" if args.apply else "dry-run",
        "backup_dir": str(backup_dir) if backup_dir is not None else None,
        "instances": [
            process_instance(
                instance,
                backup_dir,
                args.search_changed,
                args.apply,
            )
            for instance in INSTANCES
        ],
    }
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        print(f"mode={report['mode']}")
        print(f"backup_dir={report['backup_dir']}")
        for instance in report["instances"]:
            print_instance_report(instance)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
