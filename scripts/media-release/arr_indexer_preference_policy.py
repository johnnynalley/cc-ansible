#!/usr/bin/env python3
"""Manage Arr protocol preference and Prowlarr indexer priority bands.

Run this on docker-vm. Dry-run is the default. ``--apply`` requires an existing
Sanoid-backed live rollback path. API keys stay local and are never printed.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


USENET_PRIORITY = 1
SEEDPOOL_PRIORITY = 10
ANIME_SPECIALIST_PRIORITY = 15
PUBLIC_TORRENT_PRIORITY = 25
PREFERRED_PROTOCOL = "usenet"


@dataclass(frozen=True)
class Service:
    name: str
    base_url: str
    config_path: str
    api_version: str


PROWLARR = Service(
    "prowlarr", "http://127.0.0.1:9696", "/opt/media-stack/prowlarr/config.xml", "v1"
)
ARR_SERVICES = (
    Service(
        "sonarr", "http://127.0.0.1:8989", "/opt/media-stack/sonarr/config.xml", "v3"
    ),
    Service(
        "radarr", "http://127.0.0.1:7878", "/opt/media-stack/radarr/config.xml", "v3"
    ),
)


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def request_json(
    service: Service,
    api_key: str,
    method: str,
    path: str,
    body: Any | None = None,
    timeout: int = 90,
) -> Any:
    data = None
    headers = {"X-Api-Key": api_key}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{service.base_url.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            return json.loads(payload.decode("utf-8")) if payload else None
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"{service.name}: {method} {path} failed with HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"{service.name}: {method} {path} failed: {exc.reason}"
        ) from exc


def normalized_name(value: str) -> str:
    name = value.strip().casefold()
    suffix = " (prowlarr)"
    if name.endswith(suffix):
        name = name[: -len(suffix)]
    return "".join(character for character in name if character.isalnum())


def desired_priority(indexer: dict[str, Any]) -> int:
    protocol = str(indexer.get("protocol") or "").casefold()
    if protocol == "usenet":
        return USENET_PRIORITY

    name = normalized_name(str(indexer.get("name") or ""))
    definition = normalized_name(str(indexer.get("definitionName") or ""))
    if "seedpool" in name or "seedpool" in definition:
        return SEEDPOOL_PRIORITY
    if name in {"nyaasi", "animetosho"} or definition in {"nyaasi", "animetosho"}:
        return ANIME_SPECIALIST_PRIORITY
    if protocol == "torrent" and str(indexer.get("privacy") or "").casefold() == "public":
        return PUBLIC_TORRENT_PRIORITY
    return int(indexer.get("priority") or PUBLIC_TORRENT_PRIORITY)


def validate_backup_path(value: str | None) -> Path:
    if not value:
        raise RuntimeError("--apply requires --backup-path")
    path = Path(value).resolve()
    live_root = Path("/srv/live-rollbacks").resolve()
    try:
        path.relative_to(live_root)
    except ValueError as exc:
        raise RuntimeError("--backup-path must be under /srv/live-rollbacks") from exc
    if not path.is_dir() or not (path / ".live-rollback-cache").is_file():
        raise RuntimeError("--backup-path is not a marked live rollback artifact")
    return path


def indexer_summary(indexer: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": indexer.get("id"),
        "name": indexer.get("name"),
        "protocol": indexer.get("protocol"),
        "privacy": indexer.get("privacy"),
        "priority": indexer.get("priority"),
    }


def build_changes(indexers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for indexer in indexers:
        before = int(indexer.get("priority") or PUBLIC_TORRENT_PRIORITY)
        after = desired_priority(indexer)
        if before != after:
            changes.append(
                {
                    "service": "prowlarr",
                    "id": indexer.get("id"),
                    "name": indexer.get("name"),
                    "priority": {"before": before, "after": after},
                }
            )
    return changes


def apply_prowlarr_policy(api_key: str, indexers: list[dict[str, Any]]) -> None:
    for indexer in indexers:
        target = desired_priority(indexer)
        if int(indexer.get("priority") or PUBLIC_TORRENT_PRIORITY) == target:
            continue
        payload = copy.deepcopy(indexer)
        payload["priority"] = target
        indexer_id = payload.get("id")
        if not isinstance(indexer_id, int):
            raise RuntimeError(f"{payload.get('name')}: numeric indexer id missing")
        request_json(
            PROWLARR, api_key, "PUT", f"/api/v1/indexer/{indexer_id}", payload
        )


def delay_profile_changes(
    service: Service, profiles: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    changes = []
    for profile in profiles:
        before = str(profile.get("preferredProtocol") or "").casefold()
        if before != PREFERRED_PROTOCOL:
            changes.append(
                {
                    "service": service.name,
                    "id": profile.get("id"),
                    "preferred_protocol": {
                        "before": before,
                        "after": PREFERRED_PROTOCOL,
                    },
                }
            )
    return changes


def apply_delay_profiles(
    service: Service, api_key: str, profiles: list[dict[str, Any]]
) -> None:
    for profile in profiles:
        if str(profile.get("preferredProtocol") or "").casefold() == PREFERRED_PROTOCOL:
            continue
        payload = copy.deepcopy(profile)
        payload["preferredProtocol"] = PREFERRED_PROTOCOL
        profile_id = payload.get("id")
        if not isinstance(profile_id, int):
            raise RuntimeError(f"{service.name}: delay profile has no numeric id")
        request_json(
            service,
            api_key,
            "PUT",
            f"/api/v3/delayprofile/{profile_id}",
            payload,
        )


def expected_priority_map(indexers: list[dict[str, Any]]) -> dict[str, int]:
    return {
        normalized_name(str(indexer.get("name") or "")): desired_priority(indexer)
        for indexer in indexers
    }


def verify_downstream_indexers(
    service: Service, api_key: str, expected: dict[str, int]
) -> tuple[bool, list[dict[str, Any]]]:
    downstream = request_json(service, api_key, "GET", "/api/v3/indexer") or []
    rows: list[dict[str, Any]] = []
    valid = True
    seen: set[str] = set()
    for indexer in downstream:
        name = normalized_name(str(indexer.get("name") or ""))
        if name not in expected:
            continue
        seen.add(name)
        actual = int(indexer.get("priority") or PUBLIC_TORRENT_PRIORITY)
        wanted = expected[name]
        rows.append(
            {
                "name": indexer.get("name"),
                "priority": actual,
                "expected_priority": wanted,
                "valid": actual == wanted,
            }
        )
        valid = valid and actual == wanted
    # Prowlarr legitimately omits category-incompatible indexers from an app
    # (for example, YTS from Sonarr and EZTV from Radarr). Validate every
    # downstream copy that exists instead of requiring identical inventories.
    valid = valid and bool(seen)
    return valid, sorted(rows, key=lambda row: str(row["name"]).casefold())


def verify_policy(
    prowlarr_key: str, arr_keys: dict[str, str], sync_timeout: int
) -> dict[str, Any]:
    deadline = time.monotonic() + sync_timeout
    while True:
        indexers = request_json(PROWLARR, prowlarr_key, "GET", "/api/v1/indexer") or []
        expected = expected_priority_map(indexers)
        priority_valid = all(
            int(indexer.get("priority") or PUBLIC_TORRENT_PRIORITY)
            == desired_priority(indexer)
            for indexer in indexers
        )

        application_rows: dict[str, Any] = {}
        all_valid = priority_valid
        for service in ARR_SERVICES:
            profiles = request_json(
                service, arr_keys[service.name], "GET", "/api/v3/delayprofile"
            ) or []
            delay_valid = bool(profiles) and all(
                str(profile.get("preferredProtocol") or "").casefold()
                == PREFERRED_PROTOCOL
                for profile in profiles
            )
            downstream_valid, downstream = verify_downstream_indexers(
                service, arr_keys[service.name], expected
            )
            application_rows[service.name] = {
                "delay_profiles": [
                    {
                        "id": profile.get("id"),
                        "preferred_protocol": profile.get("preferredProtocol"),
                        "usenet_delay": profile.get("usenetDelay"),
                        "torrent_delay": profile.get("torrentDelay"),
                    }
                    for profile in profiles
                ],
                "indexers": downstream,
                "valid": delay_valid and downstream_valid,
            }
            all_valid = all_valid and application_rows[service.name]["valid"]

        report = {
            "valid": all_valid,
            "prowlarr": {
                "valid": priority_valid,
                "indexers": sorted(
                    (indexer_summary(indexer) for indexer in indexers),
                    key=lambda row: (
                        str(row["protocol"]),
                        int(row["priority"]),
                        str(row["name"]),
                    ),
                ),
            },
            "applications": application_rows,
        }
        if all_valid or time.monotonic() >= deadline:
            return report
        time.sleep(2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--backup-path",
        help="Existing marked rollback artifact under /srv/live-rollbacks; required with --apply.",
    )
    parser.add_argument("--sync-timeout", type=int, default=60)
    args = parser.parse_args()

    backup_path = validate_backup_path(args.backup_path) if args.apply else None
    prowlarr_key = read_api_key(PROWLARR.config_path)
    arr_keys = {service.name: read_api_key(service.config_path) for service in ARR_SERVICES}

    indexers = request_json(PROWLARR, prowlarr_key, "GET", "/api/v1/indexer") or []
    if not any("seedpool" in normalized_name(str(item.get("name") or "")) for item in indexers):
        raise RuntimeError("Prowlarr has no Seedpool indexer")

    delay_profiles = {
        service.name: request_json(
            service, arr_keys[service.name], "GET", "/api/v3/delayprofile"
        )
        or []
        for service in ARR_SERVICES
    }
    changes = build_changes(indexers)
    for service in ARR_SERVICES:
        changes.extend(delay_profile_changes(service, delay_profiles[service.name]))

    if args.apply:
        apply_prowlarr_policy(prowlarr_key, indexers)
        for service in ARR_SERVICES:
            apply_delay_profiles(
                service, arr_keys[service.name], delay_profiles[service.name]
            )

    verification = verify_policy(
        prowlarr_key, arr_keys, args.sync_timeout if args.apply else 0
    )
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry-run",
                "backup_path": str(backup_path) if backup_path else None,
                "changes": changes,
                "verification": verification,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if not args.apply or verification["valid"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
