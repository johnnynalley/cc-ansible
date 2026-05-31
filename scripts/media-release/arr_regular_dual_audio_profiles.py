#!/usr/bin/env python3
"""Create non-English regular dual-audio Arr profiles.

Run this on docker-vm. It reads local Sonarr/Radarr config.xml files for API
keys, snapshots the touched Arr state, creates a parsed-language based
`Regular Dual Audio` custom format, clones the regular efficient profiles into
dual-audio-efficient profiles, can optionally assign matching media to the new
profile, and can queue follow-up searches.

The script prints no API keys. Dry-run is the default.
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


DEFAULT_BACKUP_ROOT = "/opt/media-stack/arr-policy-backups"
CUSTOM_FORMAT_NAME = "Regular Dual Audio"
CUSTOM_FORMAT_SCORE = 100000


@dataclass(frozen=True)
class ArrInstance:
    name: str
    base_url: str
    config_path: str
    source_profile_name: str
    target_profile_name: str
    assignment_path: str
    assignment_item_name: str


INSTANCES = (
    ArrInstance(
        name="sonarr",
        base_url="http://127.0.0.1:8989",
        config_path="/opt/media-stack/sonarr/config.xml",
        source_profile_name="shows-regular-efficient",
        target_profile_name="shows-regular-dual-audio-efficient",
        assignment_path="/api/v3/series",
        assignment_item_name="series",
    ),
    ArrInstance(
        name="radarr",
        base_url="http://127.0.0.1:7878",
        config_path="/opt/media-stack/radarr/config.xml",
        source_profile_name="movies-regular-efficient",
        target_profile_name="movies-regular-dual-audio-efficient",
        assignment_path="/api/v3/movie",
        assignment_item_name="movie",
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
        "custom_formats": request_json(instance, api_key, "GET", "/api/v3/customformat"),
        "quality_profiles": request_json(instance, api_key, "GET", "/api/v3/qualityprofile"),
        "assignments": request_json(instance, api_key, "GET", instance.assignment_path),
        "queue_status": request_json(instance, api_key, "GET", "/api/v3/queue/status"),
        "commands": request_json(instance, api_key, "GET", "/api/v3/command"),
    }
    for name, value in data.items():
        write_snapshot(backup_dir / f"{instance.name}-{name.replace('_', '-')}.json", value)
    return data


def find_one(items: list[dict[str, Any]], name: str, kind: str) -> dict[str, Any] | None:
    matches = [item for item in items if item.get("name") == name]
    if len(matches) > 1:
        raise RuntimeError(f"multiple {kind} named {name!r}")
    return matches[0] if matches else None


def field(spec: dict[str, Any], name: str) -> dict[str, Any] | None:
    for item in spec.get("fields") or []:
        if item.get("name") == name:
            return item
    return None


def language_template(custom_formats: list[dict[str, Any]]) -> dict[str, Any]:
    source = find_one(custom_formats, "Language - Not Original", "custom format")
    if source is None:
        raise RuntimeError("missing 'Language - Not Original' custom format")
    for spec in source.get("specifications") or []:
        if spec.get("implementation") == "LanguageSpecification":
            return spec
    raise RuntimeError("'Language - Not Original' has no LanguageSpecification")


def language_spec(template: dict[str, Any], name: str, value: int) -> dict[str, Any]:
    spec = copy.deepcopy(template)
    spec["name"] = name
    spec["implementation"] = "LanguageSpecification"
    spec["implementationName"] = "Language"
    spec["negate"] = False
    spec["required"] = True
    value_field = field(spec, "value")
    if value_field is None:
        raise RuntimeError("language template is missing value field")
    value_field["value"] = value
    except_field = field(spec, "exceptLanguage")
    if except_field is not None:
        except_field["value"] = False
    return spec


def regular_dual_audio_payload(
    custom_formats: list[dict[str, Any]], existing: dict[str, Any] | None
) -> dict[str, Any]:
    template = language_template(custom_formats)
    payload = copy.deepcopy(existing) if existing is not None else {}
    if existing is not None and isinstance(existing.get("id"), int):
        payload["id"] = existing["id"]
    payload["name"] = CUSTOM_FORMAT_NAME
    payload["includeCustomFormatWhenRenaming"] = False
    payload["specifications"] = [
        language_spec(template, "Original Language", -2),
        language_spec(template, "English Audio", 1),
    ]
    return payload


def format_id(item: dict[str, Any]) -> int | None:
    value = item.get("format")
    if isinstance(value, dict):
        value = value.get("id")
    if value is None:
        value = item.get("customFormatId")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def set_profile_score(profile: dict[str, Any], cf_id: int, score: int) -> None:
    items = profile.setdefault("formatItems", [])
    for item in items:
        if format_id(item) == cf_id:
            item["format"] = cf_id
            item["name"] = CUSTOM_FORMAT_NAME
            item["score"] = score
            return
    items.append({"format": cf_id, "name": CUSTOM_FORMAT_NAME, "score": score})


def clone_profile_payload(
    source: dict[str, Any], target: dict[str, Any] | None, target_name: str, cf_id: int
) -> dict[str, Any]:
    payload = copy.deepcopy(source)
    payload["name"] = target_name
    if target is None:
        payload.pop("id", None)
    else:
        payload["id"] = target["id"]
    set_profile_score(payload, cf_id, CUSTOM_FORMAT_SCORE)
    payload["cutoffFormatScore"] = int(source.get("cutoffFormatScore") or 0) + CUSTOM_FORMAT_SCORE
    return payload


def title_matches(title: str, pattern: str | None) -> bool:
    if not pattern:
        return False
    return re.search(pattern, title, flags=re.IGNORECASE) is not None


def assignment_endpoint(instance: ArrInstance, item_id: int) -> str:
    return f"{instance.assignment_path}/{item_id}"


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


def profile_names_by_id(profiles: list[dict[str, Any]]) -> dict[int, str]:
    return {
        int(profile["id"]): str(profile.get("name") or profile["id"])
        for profile in profiles
        if isinstance(profile.get("id"), int)
    }


def is_probably_anime(instance: ArrInstance, item: dict[str, Any], profile_name: str | None) -> bool:
    if profile_name and "anime" in profile_name.casefold():
        return True
    if instance.name == "sonarr" and str(item.get("seriesType") or "").casefold() == "anime":
        return True
    genres = {genre.casefold() for genre in item_genres(item)}
    if "anime" in genres:
        return True
    if instance.name == "radarr" and item_language_name(item).casefold() == "japanese" and "animation" in genres:
        return True
    return False


def is_non_english_regular_candidate(
    instance: ArrInstance,
    item: dict[str, Any],
    profile_name: str | None,
) -> bool:
    original_language = item_language_name(item).casefold()
    if not original_language or original_language in {"english", "unknown"}:
        return False
    if is_probably_anime(instance, item, profile_name):
        return False
    return profile_name in {instance.source_profile_name, instance.target_profile_name}


def item_matches_assignment_policy(
    instance: ArrInstance,
    item: dict[str, Any],
    profile_name: str | None,
    title_pattern: str | None,
    include_non_english_regular: bool,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    title = str(item.get("title") or "")
    if title_matches(title, title_pattern):
        reasons.append("title_regex")
    if include_non_english_regular and is_non_english_regular_candidate(instance, item, profile_name):
        reasons.append("non_english_regular")
    return bool(reasons), reasons


def upsert_custom_format(
    instance: ArrInstance,
    api_key: str,
    custom_formats: list[dict[str, Any]],
    apply: bool,
) -> tuple[dict[str, Any], str]:
    existing = find_one(custom_formats, CUSTOM_FORMAT_NAME, "custom format")
    payload = regular_dual_audio_payload(custom_formats, existing)
    if not apply:
        return payload, "would-create" if existing is None else "would-update"
    if existing is None:
        created = request_json(instance, api_key, "POST", "/api/v3/customformat", payload)
        return created, "created"
    updated = request_json(instance, api_key, "PUT", f"/api/v3/customformat/{existing['id']}", payload)
    return updated, "updated"


def upsert_profile(
    instance: ArrInstance,
    api_key: str,
    profiles: list[dict[str, Any]],
    custom_format_id: int,
    apply: bool,
) -> tuple[dict[str, Any], str]:
    source = find_one(profiles, instance.source_profile_name, "quality profile")
    if source is None:
        raise RuntimeError(f"{instance.name}: missing source profile {instance.source_profile_name!r}")
    target = find_one(profiles, instance.target_profile_name, "quality profile")
    payload = clone_profile_payload(source, target, instance.target_profile_name, custom_format_id)
    if not apply:
        return payload, "would-create" if target is None else "would-update"
    if target is None:
        created = request_json(instance, api_key, "POST", "/api/v3/qualityprofile", payload)
        return created, "created"
    updated = request_json(instance, api_key, "PUT", f"/api/v3/qualityprofile/{target['id']}", payload)
    return updated, "updated"


def assign_matching_media(
    instance: ArrInstance,
    api_key: str,
    assignments: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
    target_profile_id: int,
    pattern: str | None,
    include_non_english_regular: bool,
    apply: bool,
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    names_by_id = profile_names_by_id(profiles)
    for item in assignments:
        title = str(item.get("title") or "")
        item_id = item.get("id")
        profile_id = item.get("qualityProfileId")
        profile_name = names_by_id.get(profile_id)
        matched, reasons = item_matches_assignment_policy(
            instance,
            item,
            profile_name,
            pattern,
            include_non_english_regular,
        )
        if not isinstance(item_id, int) or not matched:
            continue
        before = profile_id
        row = {
            "id": item_id,
            "title": title,
            "original_language": item_language_name(item),
            "genres": item_genres(item),
            "profile": profile_name,
            "from": before,
            "to": target_profile_id,
            "changed": before != target_profile_id,
            "reasons": reasons,
        }
        if apply and before != target_profile_id:
            payload = copy.deepcopy(item)
            payload["qualityProfileId"] = target_profile_id
            request_json(instance, api_key, "PUT", assignment_endpoint(instance, item_id), payload)
        changes.append(row)
    return changes


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
    backup_dir: Path,
    assign_pattern: str | None,
    include_non_english_regular: bool,
    search_matches: bool,
    apply: bool,
) -> dict[str, Any]:
    api_key = read_api_key(instance.config_path)
    snapshot = snapshot_instance(instance, api_key, backup_dir)
    custom_format, custom_format_action = upsert_custom_format(
        instance, api_key, snapshot["custom_formats"], apply
    )
    custom_format_id = custom_format.get("id")
    if apply and not isinstance(custom_format_id, int):
        raise RuntimeError(f"{instance.name}: created custom format has no id")
    if not apply:
        existing = find_one(snapshot["custom_formats"], CUSTOM_FORMAT_NAME, "custom format")
        custom_format_id = int(existing["id"]) if existing and isinstance(existing.get("id"), int) else -1

    profile, profile_action = upsert_profile(
        instance,
        api_key,
        snapshot["quality_profiles"],
        int(custom_format_id),
        apply,
    )
    target_profile_id = profile.get("id")
    if apply and not isinstance(target_profile_id, int):
        raise RuntimeError(f"{instance.name}: target profile has no id")
    if not apply:
        existing_profile = find_one(snapshot["quality_profiles"], instance.target_profile_name, "quality profile")
        target_profile_id = (
            int(existing_profile["id"])
            if existing_profile and isinstance(existing_profile.get("id"), int)
            else -1
        )

    assignments = assign_matching_media(
        instance,
        api_key,
        snapshot["assignments"],
        snapshot["quality_profiles"],
        int(target_profile_id),
        assign_pattern,
        include_non_english_regular,
        apply,
    )
    search_commands: list[dict[str, Any]] = []
    search_errors: list[dict[str, Any]] = []
    if search_matches:
        assignments_by_id = {item["id"]: item for item in assignments}
        for item in snapshot["assignments"]:
            item_id = item.get("id")
            if item_id not in assignments_by_id:
                continue
            try:
                search_commands.append(queue_search(instance, api_key, item, apply))
            except Exception as exc:  # noqa: BLE001 - keep other queued searches moving.
                search_errors.append({"id": item_id, "title": item.get("title"), "error": str(exc)})
    return {
        "instance": instance.name,
        "custom_format": {
            "name": CUSTOM_FORMAT_NAME,
            "id": custom_format_id,
            "action": custom_format_action,
            "score": CUSTOM_FORMAT_SCORE,
        },
        "profile": {
            "source": instance.source_profile_name,
            "name": instance.target_profile_name,
            "id": target_profile_id,
            "action": profile_action,
            "cutoffFormatScore": profile.get("cutoffFormatScore"),
        },
        "assignment_pattern": assign_pattern,
        "include_non_english_regular": include_non_english_regular,
        "assignments": assignments,
        "search_matches": search_matches,
        "search_commands": search_commands,
        "search_errors": search_errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="mutate live Arr state")
    parser.add_argument("--backup-root", type=Path, default=Path(DEFAULT_BACKUP_ROOT))
    parser.add_argument(
        "--assign-sonarr-title-regex",
        help="optional case-insensitive Sonarr title regex to assign to the new profile",
    )
    parser.add_argument(
        "--assign-radarr-title-regex",
        help="optional case-insensitive Radarr title regex to assign to the new profile",
    )
    parser.add_argument(
        "--assign-non-english-regular",
        action="store_true",
        help="assign regular-profile non-anime media whose original language is not English",
    )
    parser.add_argument(
        "--search-matches",
        action="store_true",
        help="queue a SeriesSearch/MoviesSearch for every matched assignment candidate",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = args.backup_root / f"{timestamp}-regular-dual-audio-profiles"
    backup_dir.mkdir(parents=True, exist_ok=False)

    patterns = {
        "sonarr": args.assign_sonarr_title_regex,
        "radarr": args.assign_radarr_title_regex,
    }
    report = {
        "mode": "apply" if args.apply else "dry-run",
        "backup_dir": str(backup_dir),
        "instances": [
            process_instance(
                instance,
                backup_dir,
                patterns.get(instance.name),
                args.assign_non_english_regular,
                args.search_matches,
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
            print(
                "{instance}: cf={cf_action} profile={profile_action} cutoff={cutoff}".format(
                    instance=instance["instance"],
                    cf_action=instance["custom_format"]["action"],
                    profile_action=instance["profile"]["action"],
                    cutoff=instance["profile"]["cutoffFormatScore"],
                )
            )
            if instance["assignments"]:
                print(f"  assignments matching {instance['assignment_pattern']!r}:")
                for item in instance["assignments"]:
                    status = "changed" if item["changed"] else "already"
                    reasons = ",".join(item["reasons"])
                    language = item["original_language"] or "unknown"
                    print(
                        f"    - {status}: {item['title']} ({item['from']} -> {item['to']}) "
                        f"language={language} reasons={reasons}"
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
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
