#!/usr/bin/env python3
"""Guard Radarr English-original regular movies from foreign/multi-audio titles.

Run this on docker-vm. It reads the local Radarr config.xml for the API key,
snapshots the touched Radarr policy state, creates or updates a title-side
negative custom format, and scores it only on `movies-regular-efficient`.

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RADARR_URL = "http://127.0.0.1:7878"
RADARR_CONFIG = "/opt/media-stack/radarr/config.xml"
DEFAULT_BACKUP_ROOT = "/opt/media-stack/arr-policy-backups"
CUSTOM_FORMAT_NAME = "Regular English - Foreign/Multi Audio Guard"
TARGET_PROFILE_NAME = "movies-regular-efficient"
DEFAULT_SCORE = -100000

# This intentionally avoids plain language words such as "French" or "German"
# unless they are paired with release-marker terms, so movie titles like
# "The French Dispatch" are not matched just because of their name.
GUARD_REGEX = (
    r"\b(?:german|deutsch|french|truefrench|spanish|castilian|latino|italian|"
    r"russian|polish|dutch|portuguese|brazilian|japanese|korean|chinese|"
    r"hindi|turkish|swedish|norwegian|danish|finnish|czech|hungarian|"
    r"romanian|ukrainian)[ ._-]?(?:dl|dubbed|dub|dual(?:[ ._-]?audio)?)\b"
    r"|\b(?:ger|deu|de|fre|fra|fr|spa|es|ita|rus|pol|nl|dut|por|pt|jpn|ja|"
    r"kor|ko|chi|zho|zh|hin|tur)[ ._-]?dl\b"
    r"|\b(?:dual[ ._-]?audio|multi[ ._-]?audio|multi[ ._-]?language|"
    r"multilang(?:uage)?|multi[ ._-]?lang)\b"
    r"|\b(?:vostfr|vff|vfq|truefrench)\b"
    r"|(?:^|[ ._(])dl[ ._-]?(?:480p|576p|720p|1080p|2160p|4k|uhd|bluray|"
    r"bdrip|bdremux|webrip|hdtv)\b"
    r"|\bdual[ ._-]?(?:complete|bluray|bdrip|bdremux|webrip|web-dl|hdtv)\b"
    r"|\b(?:480p|576p|720p|1080p|2160p|4k|uhd)\b.*\bdual\b"
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


def snapshot_radarr(api_key: str, backup_dir: Path) -> dict[str, Any]:
    data = {
        "custom_formats": request_json(api_key, "GET", "/api/v3/customformat"),
        "quality_profiles": request_json(api_key, "GET", "/api/v3/qualityprofile"),
        "media_management": request_json(api_key, "GET", "/api/v3/config/mediamanagement"),
        "queue_status": request_json(api_key, "GET", "/api/v3/queue/status"),
        "commands": request_json(api_key, "GET", "/api/v3/command"),
    }
    for name, value in data.items():
        write_snapshot(backup_dir / f"radarr-{name.replace('_', '-')}.json", value)
    return data


def find_one(items: list[dict[str, Any]], name: str, kind: str) -> dict[str, Any] | None:
    matches = [item for item in items if item.get("name") == name]
    if len(matches) > 1:
        raise RuntimeError(f"multiple {kind} named {name!r}")
    return matches[0] if matches else None


def title_spec(name: str, pattern: str) -> dict[str, Any]:
    return {
        "name": name,
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


def custom_format_payload(existing: dict[str, Any] | None, pattern: str) -> dict[str, Any]:
    payload = copy.deepcopy(existing) if existing is not None else {}
    if existing is not None and isinstance(existing.get("id"), int):
        payload["id"] = existing["id"]
    payload["name"] = CUSTOM_FORMAT_NAME
    payload["includeCustomFormatWhenRenaming"] = False
    payload["specifications"] = [
        title_spec("Foreign or multi-audio title marker", pattern),
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


def set_profile_score(profile: dict[str, Any], cf_id: int, cf_name: str, score: int) -> bool:
    items = profile.setdefault("formatItems", [])
    for item in items:
        if format_id(item) == cf_id:
            changed = item.get("format") != cf_id or item.get("name") != cf_name or int(item.get("score") or 0) != score
            item["format"] = cf_id
            item["name"] = cf_name
            item["score"] = score
            return changed
    items.append({"format": cf_id, "name": cf_name, "score": score})
    return True


def upsert_custom_format(
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
        return request_json(api_key, "POST", "/api/v3/customformat", payload), "created"
    return request_json(api_key, "PUT", f"/api/v3/customformat/{existing['id']}", payload), "updated"


def update_profiles(
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
        target_score = score if profile_name == TARGET_PROFILE_NAME else 0
        payload = copy.deepcopy(profile)
        changed = set_profile_score(payload, cf_id, CUSTOM_FORMAT_NAME, target_score)
        if changed and apply:
            if not isinstance(profile_id, int):
                raise RuntimeError(f"profile {profile_name!r} has no numeric id")
            request_json(api_key, "PUT", f"/api/v3/qualityprofile/{profile_id}", payload)
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="mutate live Radarr state")
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
    backup_dir = args.backup_root / f"{timestamp}-radarr-regular-english-language-guard"
    backup_dir.mkdir(parents=True, exist_ok=False)

    api_key = read_api_key(RADARR_CONFIG)
    snapshot = snapshot_radarr(api_key, backup_dir)
    custom_format, custom_format_action = upsert_custom_format(
        api_key,
        snapshot["custom_formats"],
        args.pattern,
        args.apply,
    )
    cf_id = custom_format.get("id")
    if args.apply and not isinstance(cf_id, int):
        raise RuntimeError("created custom format has no id")
    if not args.apply:
        existing = find_one(snapshot["custom_formats"], CUSTOM_FORMAT_NAME, "custom format")
        cf_id = int(existing["id"]) if existing and isinstance(existing.get("id"), int) else -1

    profiles = request_json(api_key, "GET", "/api/v3/qualityprofile") if args.apply else snapshot["quality_profiles"]
    profile_changes = update_profiles(api_key, profiles, int(cf_id), args.score, args.apply)
    test_titles = [
        {"title": title, "matched": regex_matches(args.pattern, title)}
        for title in args.test_title
    ]

    report = {
        "mode": "apply" if args.apply else "dry-run",
        "backup_dir": str(backup_dir),
        "custom_format": {
            "name": CUSTOM_FORMAT_NAME,
            "id": cf_id,
            "action": custom_format_action,
            "score_on_target_profile": args.score,
        },
        "target_profile": TARGET_PROFILE_NAME,
        "profile_changes": profile_changes,
        "custom_format_count_before": len(snapshot["custom_formats"]),
        "custom_format_count_after": len(snapshot["custom_formats"]) + (1 if custom_format_action in {"created", "would-create"} else 0),
        "test_titles": test_titles,
    }
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        print(f"mode={report['mode']}")
        print(f"backup_dir={report['backup_dir']}")
        print(
            "custom_format={name} id={id} action={action} count={before}->{after}".format(
                name=report["custom_format"]["name"],
                id=report["custom_format"]["id"],
                action=report["custom_format"]["action"],
                before=report["custom_format_count_before"],
                after=report["custom_format_count_after"],
            )
        )
        print(f"target_profile={TARGET_PROFILE_NAME} score={args.score}")
        for item in profile_changes:
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
