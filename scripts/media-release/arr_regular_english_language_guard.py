#!/usr/bin/env python3
"""Guard English-original regular Arr profiles from foreign/multi-audio titles.

Run this on docker-vm. It reads local Arr config.xml files for API keys,
snapshots the touched policy state, creates or updates a title-side negative
custom format, and scores it only on each English-original regular profile.

Dry-run is the default. The script prints no API keys.
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
CUSTOM_FORMAT_NAME = "Regular English - Foreign/Multi Audio Guard"
DEFAULT_SCORE = -100000

LANGUAGE_WORDS = (
    r"german|deutsch|french|truefrench|spanish|castilian|latino|italian|"
    r"russian|polish|dutch|portuguese|brazilian|japanese|korean|chinese|"
    r"hindi|turkish|swedish|norwegian|danish|finnish|czech|hungarian|"
    r"romanian|ukrainian"
)
LANGUAGE_CODES = (
    r"ger|deu|de|fre|fra|fr|spa|es|ita|rus|pol|nl|dut|por|pt|jpn|ja|"
    r"kor|ko|chi|zho|zh|hin|tur"
)
FOREIGN_LANGUAGE = rf"(?:{LANGUAGE_WORDS}|{LANGUAGE_CODES})"
ENGLISH_LANGUAGE = r"(?:english|eng)"

# Plain language words require an audio/release marker. A bounded bracketed
# pair is also accepted because releases commonly express audio as
# `[Hindi DD5.1 + English DD5.1]`. This avoids matching title phrases such as
# `The French Dispatch` while rejecting explicit foreign+English audio labels.
GUARD_REGEX = (
    rf"\b(?:{LANGUAGE_WORDS})[ ._-]?(?:dl|dubbed|dub|dual(?:[ ._-]?audio)?)\b"
    rf"|\b(?:{LANGUAGE_CODES})[ ._-]?dl\b"
    r"|\b(?:dual[ ._-]?audio|multi[ ._-]?audio|multi[ ._-]?language|"
    r"multilang(?:uage)?|multi[ ._-]?lang)\b"
    r"|\b(?:vostfr|vff|vfq|truefrench)\b"
    r"|(?:^|[ ._(])dl[ ._-]?(?:480p|576p|720p|1080p|2160p|4k|uhd|bluray|"
    r"bdrip|bdremux|webrip|hdtv)\b"
    r"|\bdual[ ._-]?(?:complete|bluray|bdrip|bdremux|webrip|web-dl|hdtv)\b"
    r"|\b(?:480p|576p|720p|1080p|2160p|4k|uhd)\b.*\bdual\b"
    rf"|[\[(][^\])\r\n]{{0,80}}\b{FOREIGN_LANGUAGE}\b"
    rf"[^\])\r\n]{{0,80}}\b{ENGLISH_LANGUAGE}\b[^\])\r\n]{{0,80}}[\])]"
    rf"|[\[(][^\])\r\n]{{0,80}}\b{ENGLISH_LANGUAGE}\b"
    rf"[^\])\r\n]{{0,80}}\b{FOREIGN_LANGUAGE}\b[^\])\r\n]{{0,80}}[\])]"
)


@dataclass(frozen=True)
class ArrInstance:
    name: str
    base_url: str
    config_path: str
    target_profile_name: str


INSTANCES = (
    ArrInstance(
        name="sonarr",
        base_url="http://127.0.0.1:8989",
        config_path="/opt/media-stack/sonarr/config.xml",
        target_profile_name="shows-regular-efficient",
    ),
    ArrInstance(
        name="radarr",
        base_url="http://127.0.0.1:7878",
        config_path="/opt/media-stack/radarr/config.xml",
        target_profile_name="movies-regular-efficient",
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
            return json.loads(payload.decode("utf-8")) if payload else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"{instance.name}: {method} {path} failed: {exc.code} {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"{instance.name}: {method} {path} failed: {exc.reason}"
        ) from exc


def write_snapshot(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def snapshot_instance(
    instance: ArrInstance, api_key: str, backup_dir: Path
) -> dict[str, Any]:
    data = {
        "custom_formats": request_json(instance, api_key, "GET", "/api/v3/customformat"),
        "quality_profiles": request_json(instance, api_key, "GET", "/api/v3/qualityprofile"),
        "media_management": request_json(
            instance, api_key, "GET", "/api/v3/config/mediamanagement"
        ),
        "queue_status": request_json(instance, api_key, "GET", "/api/v3/queue/status"),
        "commands": request_json(instance, api_key, "GET", "/api/v3/command"),
    }
    for name, value in data.items():
        write_snapshot(backup_dir / f"{instance.name}-{name.replace('_', '-')}.json", value)
    return data


def find_one(
    items: list[dict[str, Any]], name: str, kind: str
) -> dict[str, Any] | None:
    matches = [item for item in items if item.get("name") == name]
    if len(matches) > 1:
        raise RuntimeError(f"multiple {kind} named {name!r}")
    return matches[0] if matches else None


def title_spec(pattern: str) -> dict[str, Any]:
    return {
        "name": "Foreign or multi-audio title marker",
        "implementation": "ReleaseTitleSpecification",
        "implementationName": "Release Title",
        "infoLink": "https://wiki.servarr.com/radarr/settings#custom-formats-2",
        "negate": False,
        "required": True,
        "fields": [
            {
                "order": 0,
                "name": "value",
                "label": "Regular Expression",
                "helpText": "Custom Format RegEx is Case Insensitive",
                "value": pattern,
                "type": "textbox",
                "advanced": False,
                "privacy": "normal",
                "isFloat": False,
            }
        ],
    }


def custom_format_payload(
    existing: dict[str, Any] | None, pattern: str
) -> dict[str, Any]:
    payload = copy.deepcopy(existing) if existing is not None else {}
    if existing is not None and isinstance(existing.get("id"), int):
        payload["id"] = existing["id"]
    payload["name"] = CUSTOM_FORMAT_NAME
    payload["includeCustomFormatWhenRenaming"] = False
    payload["specifications"] = [title_spec(pattern)]
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


def set_profile_score(
    profile: dict[str, Any], cf_id: int, cf_name: str, score: int
) -> bool:
    items = profile.setdefault("formatItems", [])
    for item in items:
        if format_id(item) == cf_id:
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


def upsert_custom_format(
    instance: ArrInstance,
    api_key: str,
    custom_formats: list[dict[str, Any]],
    pattern: str,
    apply: bool,
) -> tuple[dict[str, Any], str]:
    existing = find_one(custom_formats, CUSTOM_FORMAT_NAME, "custom format")
    payload = custom_format_payload(existing, pattern)
    if not apply:
        return payload, "would-create" if existing is None else "would-update"
    if existing is None:
        return request_json(instance, api_key, "POST", "/api/v3/customformat", payload), "created"
    return (
        request_json(
            instance,
            api_key,
            "PUT",
            f"/api/v3/customformat/{existing['id']}",
            payload,
        ),
        "updated",
    )


def update_profiles(
    instance: ArrInstance,
    api_key: str,
    profiles: list[dict[str, Any]],
    cf_id: int,
    score: int,
    apply: bool,
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for profile in profiles:
        profile_id = profile.get("id")
        profile_name = str(profile.get("name") or "")
        target_score = score if profile_name == instance.target_profile_name else 0
        payload = copy.deepcopy(profile)
        changed = set_profile_score(payload, cf_id, CUSTOM_FORMAT_NAME, target_score)
        if changed and apply:
            if not isinstance(profile_id, int):
                raise RuntimeError(f"profile {profile_name!r} has no numeric id")
            request_json(
                instance,
                api_key,
                "PUT",
                f"/api/v3/qualityprofile/{profile_id}",
                payload,
            )
        changes.append(
            {
                "id": profile_id,
                "name": profile_name,
                "score": target_score,
                "changed": changed,
            }
        )
    return changes


def regex_matches(pattern: str, title: str) -> bool:
    return re.search(pattern, title, flags=re.IGNORECASE) is not None


def selected_instances(names: list[str]) -> list[ArrInstance]:
    selected = set(names)
    return [instance for instance in INSTANCES if not selected or instance.name in selected]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="mutate live Arr state")
    parser.add_argument(
        "--instance",
        action="append",
        choices=[instance.name for instance in INSTANCES],
        default=[],
        help="limit work to one Arr instance; repeatable; default is both",
    )
    parser.add_argument("--backup-root", type=Path, default=Path(DEFAULT_BACKUP_ROOT))
    parser.add_argument("--score", type=int, default=DEFAULT_SCORE)
    parser.add_argument("--pattern", default=GUARD_REGEX)
    parser.add_argument(
        "--test-title",
        action="append",
        default=[],
        help="print whether a title matches the guard regex; can be repeated",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = args.backup_root / f"{timestamp}-arr-regular-english-language-guard"
    backup_dir.mkdir(parents=True, exist_ok=False)
    reports: list[dict[str, Any]] = []

    for instance in selected_instances(args.instance):
        api_key = read_api_key(instance.config_path)
        snapshot = snapshot_instance(instance, api_key, backup_dir)
        custom_format, action = upsert_custom_format(
            instance,
            api_key,
            snapshot["custom_formats"],
            args.pattern,
            args.apply,
        )
        cf_id = custom_format.get("id")
        if args.apply and not isinstance(cf_id, int):
            raise RuntimeError(f"{instance.name}: created custom format has no id")
        if not args.apply:
            existing = find_one(
                snapshot["custom_formats"], CUSTOM_FORMAT_NAME, "custom format"
            )
            cf_id = (
                int(existing["id"])
                if existing and isinstance(existing.get("id"), int)
                else -1
            )
        profiles = (
            request_json(instance, api_key, "GET", "/api/v3/qualityprofile")
            if args.apply
            else snapshot["quality_profiles"]
        )
        reports.append(
            {
                "instance": instance.name,
                "target_profile": instance.target_profile_name,
                "custom_format_id": cf_id,
                "custom_format_action": action,
                "profile_changes": update_profiles(
                    instance, api_key, profiles, int(cf_id), args.score, args.apply
                ),
                "custom_format_count_before": len(snapshot["custom_formats"]),
            }
        )

    test_titles = [
        {"title": title, "matched": regex_matches(args.pattern, title)}
        for title in args.test_title
    ]
    report = {
        "mode": "apply" if args.apply else "dry-run",
        "backup_dir": str(backup_dir),
        "custom_format": CUSTOM_FORMAT_NAME,
        "score": args.score,
        "instances": reports,
        "test_titles": test_titles,
    }
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        print(f"mode={report['mode']}")
        print(f"backup_dir={report['backup_dir']}")
        print(f"custom_format={CUSTOM_FORMAT_NAME} score={args.score}")
        for instance_report in reports:
            print(
                f"{instance_report['instance']}: action="
                f"{instance_report['custom_format_action']} target="
                f"{instance_report['target_profile']}"
            )
            for item in instance_report["profile_changes"]:
                state = "changed" if item["changed"] else "unchanged"
                print(f"  - {state}: {item['name']} score={item['score']}")
        if test_titles:
            print("test_titles:")
            for item in test_titles:
                print(f"  - matched={item['matched']} {item['title']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
