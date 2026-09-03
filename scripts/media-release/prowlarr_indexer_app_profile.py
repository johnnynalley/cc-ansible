#!/usr/bin/env python3
"""Move one Prowlarr indexer to an existing application profile safely."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET


ARRS = {
    "sonarr": ("http://127.0.0.1:8989", "/opt/media-stack/sonarr/config.xml"),
    "radarr": ("http://127.0.0.1:7878", "/opt/media-stack/radarr/config.xml"),
}


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def request_json(
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    timeout: int = 30,
) -> Any:
    data = None
    headers = {"X-Api-Key": api_key, "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, sort_keys=True).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8", errors="replace")
            return json.loads(payload) if payload else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {path} failed: {exc.reason}") from exc


def select_exact(records: list[dict[str, Any]], name: str, kind: str) -> dict[str, Any]:
    matches = [
        record
        for record in records
        if str(record.get("name") or "").casefold() == name.casefold()
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {kind} named {name!r}; found {len(matches)}")
    return matches[0]


def safe_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": profile.get("id"),
        "name": profile.get("name"),
        "enable_rss": profile.get("enableRss"),
        "enable_automatic_search": profile.get("enableAutomaticSearch"),
        "enable_interactive_search": profile.get("enableInteractiveSearch"),
        "minimum_seeders": profile.get("minimumSeeders"),
    }


def safe_indexer(indexer: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": indexer.get("id"),
        "name": indexer.get("name"),
        "protocol": indexer.get("protocol"),
        "priority": indexer.get("priority"),
        "app_profile_id": indexer.get("appProfileId"),
    }


def write_rollback(
    backup_path: Path,
    indexer: dict[str, Any],
    source_profile: dict[str, Any],
    target_profile: dict[str, Any],
) -> Path:
    if not backup_path.is_dir():
        raise RuntimeError(f"rollback path is not a directory: {backup_path}")
    if backup_path.stat().st_mode & 0o077:
        raise RuntimeError(f"rollback path must be root-only (0700): {backup_path}")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_path / f"{timestamp}-prowlarr-indexer-app-profile.json"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "indexer": indexer,
                "source_profile": source_profile,
                "target_profile": target_profile,
            },
            handle,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")
    return target


def run_command(
    base_url: str,
    api_key: str,
    name: str,
    wait_seconds: int,
) -> int:
    result = request_json(
        base_url, api_key, "POST", "/api/v1/command", {"name": name}
    )
    command_id = result.get("id") if isinstance(result, dict) else None
    if not isinstance(command_id, int):
        raise RuntimeError(f"{name}: command returned no numeric id")
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        current = request_json(
            base_url, api_key, "GET", f"/api/v1/command/{command_id}"
        )
        status = str(current.get("status") or "unknown").casefold()
        if status == "completed":
            return command_id
        if status in {"failed", "aborted", "cancelled", "canceled"}:
            raise RuntimeError(f"{name}: command {command_id} ended as {status}")
        time.sleep(1)
    raise RuntimeError(f"{name}: command {command_id} exceeded {wait_seconds}s")


def downstream_state(indexer_name: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    expected_name = f"{indexer_name} (Prowlarr)".casefold()
    for app, (base_url, config_path) in ARRS.items():
        records = request_json(
            base_url, read_api_key(config_path), "GET", "/api/v3/indexer"
        )
        matches = [
            record
            for record in records
            if str(record.get("name") or "").casefold() == expected_name
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"{app}: expected one synced indexer named {indexer_name!r}; "
                f"found {len(matches)}"
            )
        record = matches[0]
        result[app] = {
            "id": record.get("id"),
            "enable_rss": record.get("enableRss"),
            "enable_automatic_search": record.get("enableAutomaticSearch"),
            "enable_interactive_search": record.get("enableInteractiveSearch"),
        }
    return result


def verify_downstream(
    downstream: dict[str, dict[str, Any]], profile: dict[str, Any]
) -> None:
    expected = {
        "enable_rss": profile.get("enableRss"),
        "enable_automatic_search": profile.get("enableAutomaticSearch"),
        "enable_interactive_search": profile.get("enableInteractiveSearch"),
    }
    for app, state in downstream.items():
        actual = {key: state.get(key) for key in expected}
        if actual != expected:
            raise RuntimeError(f"{app}: downstream policy mismatch: {actual} != {expected}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--indexer", required=True)
    parser.add_argument("--app-profile", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:9696")
    parser.add_argument("--config", default="/opt/media-stack/prowlarr/config.xml")
    parser.add_argument("--backup-path")
    parser.add_argument("--wait-seconds", type=int, default=180)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.backup_path:
        raise RuntimeError("--apply requires --backup-path")

    api_key = read_api_key(args.config)
    indexers = request_json(args.base_url, api_key, "GET", "/api/v1/indexer")
    profiles = request_json(args.base_url, api_key, "GET", "/api/v1/appprofile")
    indexer = select_exact(indexers, args.indexer, "indexer")
    target_profile = select_exact(profiles, args.app_profile, "application profile")
    source_profile = next(
        (
            profile
            for profile in profiles
            if profile.get("id") == indexer.get("appProfileId")
        ),
        None,
    )
    if source_profile is None:
        raise RuntimeError("current indexer application profile was not found")

    result: dict[str, Any] = {
        "apply": args.apply,
        "indexer": safe_indexer(indexer),
        "source_profile": safe_profile(source_profile),
        "target_profile": safe_profile(target_profile),
        "changed": indexer.get("appProfileId") != target_profile.get("id"),
    }
    if not args.apply or not result["changed"]:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    rollback = write_rollback(
        Path(args.backup_path), indexer, source_profile, target_profile
    )
    updated = dict(indexer)
    updated["appProfileId"] = target_profile["id"]
    request_json(args.base_url, api_key, "POST", "/api/v1/indexer/test", updated)
    try:
        request_json(
            args.base_url,
            api_key,
            "PUT",
            f"/api/v1/indexer/{indexer['id']}",
            updated,
        )
        command_id = run_command(
            args.base_url, api_key, "ApplicationIndexerSync", args.wait_seconds
        )
        current = select_exact(
            request_json(args.base_url, api_key, "GET", "/api/v1/indexer"),
            args.indexer,
            "indexer",
        )
        if current.get("appProfileId") != target_profile.get("id"):
            raise RuntimeError("Prowlarr app-profile readback did not match")
        downstream = downstream_state(args.indexer)
        verify_downstream(downstream, target_profile)
    except Exception as exc:
        request_json(
            args.base_url,
            api_key,
            "PUT",
            f"/api/v1/indexer/{indexer['id']}",
            indexer,
        )
        run_command(args.base_url, api_key, "ApplicationIndexerSync", args.wait_seconds)
        raise RuntimeError(f"apply failed and original indexer was restored: {exc}") from exc

    result.update(
        {
            "rollback": str(rollback),
            "command_id": command_id,
            "current_indexer": safe_indexer(current),
            "downstream": downstream,
        }
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
