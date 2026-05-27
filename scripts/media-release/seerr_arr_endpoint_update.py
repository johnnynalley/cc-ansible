#!/usr/bin/env python3
"""Audit or update Seerr's Sonarr/Radarr endpoints.

Run this on docker-vm. The script reads Seerr's local settings for API access,
uses Seerr's own Arr test endpoints to validate the candidate settings, and
only writes live settings after taking a timestamped snapshot.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_SEERR_URL = "http://127.0.0.1:5055/api/v1"
DEFAULT_SEERR_SETTINGS = "/opt/seerr/config/settings.json"
DEFAULT_SNAPSHOT_ROOT = "/opt/media-stack/release-policy-snapshots"


@dataclass(frozen=True)
class SeerrSection:
    name: str
    target_host: str
    target_port: int


def read_seerr_api_key(path: Path) -> str:
    settings = json.loads(path.read_text(encoding="utf-8"))
    key = ((settings.get("main") or {}).get("apiKey") or "").strip()
    if not key:
        raise RuntimeError(f"{path}: main.apiKey was not found")
    return key


def request_json(
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    body: Any | None = None,
) -> Any:
    data = None
    headers = {"X-API-Key": api_key}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.status == 204:
                return None
            payload = response.read()
            if not payload:
                return None
            return json.loads(payload.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {path} failed: {exc.reason}") from exc


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in {"apikey", "api_key", "token", "sessionsecret"}:
                redacted[key] = "REDACTED"
            else:
                redacted[key] = redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def write_snapshot(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def snapshot(
    snapshot_root: Path,
    settings_path: Path,
    api_state: dict[str, Any],
) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_dir = snapshot_root / f"{timestamp}-seerr-arr-endpoint-update"
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    write_snapshot(snapshot_dir / "seerr-settings.json", json.loads(settings_path.read_text(encoding="utf-8")))
    for section, rows in api_state.items():
        write_snapshot(snapshot_dir / f"seerr-{section}-api.json", rows)
    return snapshot_dir


def payload_for_update(item: dict[str, Any], target_host: str, target_port: int) -> dict[str, Any]:
    payload = copy.deepcopy(item)
    payload.pop("id", None)
    payload["hostname"] = target_host
    payload["port"] = target_port
    payload["useSsl"] = False
    payload["baseUrl"] = payload.get("baseUrl") or ""
    return payload


def compact_item(item: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "name",
        "hostname",
        "port",
        "useSsl",
        "baseUrl",
        "activeProfileId",
        "activeProfileName",
        "activeAnimeProfileId",
        "activeAnimeProfileName",
    )
    return {key: item.get(key) for key in keys if key in item}


def test_candidate(
    seerr_url: str,
    api_key: str,
    section: SeerrSection,
    item: dict[str, Any],
) -> dict[str, Any]:
    payload = payload_for_update(item, section.target_host, section.target_port)
    try:
        result = request_json(
            seerr_url,
            api_key,
            "POST",
            f"/settings/{section.name}/test",
            payload,
        )
        return {
            "ok": True,
            "profiles": len((result or {}).get("profiles") or []),
            "rootFolders": len((result or {}).get("rootFolders") or []),
            "tags": len((result or {}).get("tags") or []),
        }
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}


def process_section(
    seerr_url: str,
    api_key: str,
    section: SeerrSection,
    rows: list[dict[str, Any]],
    apply: bool,
) -> dict[str, Any]:
    changes: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []

    for item in rows:
        before = compact_item(item)
        payload = payload_for_update(item, section.target_host, section.target_port)
        after = compact_item({"id": item.get("id"), **payload})
        changed = before != after
        test = test_candidate(seerr_url, api_key, section, item)
        tests.append({"id": item.get("id"), "name": item.get("name"), **test})
        if not test["ok"]:
            raise RuntimeError(
                f"{section.name} id={item.get('id')} target "
                f"{section.target_host}:{section.target_port} failed validation: {test['error']}"
            )
        if changed:
            changes.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "before": before,
                    "after": after,
                }
            )
            if apply:
                request_json(
                    seerr_url,
                    api_key,
                    "PUT",
                    f"/settings/{section.name}/{item['id']}",
                    payload,
                )

    return {"changes": changes, "tests": tests}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the validated endpoint changes")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--seerr-url", default=DEFAULT_SEERR_URL)
    parser.add_argument("--seerr-settings", type=Path, default=Path(DEFAULT_SEERR_SETTINGS))
    parser.add_argument("--snapshot-root", type=Path, default=Path(DEFAULT_SNAPSHOT_ROOT))
    parser.add_argument("--sonarr-host", default="sonarr")
    parser.add_argument("--sonarr-port", type=int, default=8989)
    parser.add_argument("--radarr-host", default="radarr")
    parser.add_argument("--radarr-port", type=int, default=7878)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = read_seerr_api_key(args.seerr_settings)
    sections = (
        SeerrSection("sonarr", args.sonarr_host, args.sonarr_port),
        SeerrSection("radarr", args.radarr_host, args.radarr_port),
    )
    before = {
        section.name: request_json(args.seerr_url, api_key, "GET", f"/settings/{section.name}")
        for section in sections
    }
    snapshot_dir = None
    if args.apply:
        snapshot_dir = str(snapshot(args.snapshot_root, args.seerr_settings, before))

    results = {
        section.name: process_section(
            args.seerr_url,
            api_key,
            section,
            before[section.name],
            apply=args.apply,
        )
        for section in sections
    }
    after = {
        section.name: request_json(args.seerr_url, api_key, "GET", f"/settings/{section.name}")
        for section in sections
    }
    report = {
        "apply": args.apply,
        "snapshot_dir": snapshot_dir,
        "targets": {
            "sonarr": f"{args.sonarr_host}:{args.sonarr_port}",
            "radarr": f"{args.radarr_host}:{args.radarr_port}",
        },
        "results": results,
        "after": redact(after),
    }

    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"{mode}: targets={report['targets']}")
        if snapshot_dir:
            print(f"snapshot={snapshot_dir}")
        for section_name, result in results.items():
            print(f"{section_name}: changes={len(result['changes'])}")
            for test in result["tests"]:
                print(
                    "  test id={id} {name}: ok={ok} profiles={profiles} "
                    "rootFolders={rootFolders} tags={tags}".format(**test)
                )
            for change in result["changes"]:
                print(
                    "  id={id} {name}: {before} -> {after}".format(**change)
                )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
