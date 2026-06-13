#!/usr/bin/env python3
"""List or toggle Sonarr/Radarr download clients by name or implementation."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET


APPS = {
    "radarr": {
        "base_url": "http://127.0.0.1:7878",
        "config": "/opt/media-stack/radarr/config.xml",
    },
    "sonarr": {
        "base_url": "http://127.0.0.1:8989",
        "config": "/opt/media-stack/sonarr/config.xml",
    },
}


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def api_json(
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
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
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code}: {detail}") from exc


def client_summary(app: str, client: dict[str, Any]) -> dict[str, Any]:
    return {
        "app": app,
        "id": client.get("id"),
        "name": client.get("name"),
        "implementation": client.get("implementation"),
        "protocol": client.get("protocol"),
        "enable": client.get("enable"),
        "priority": client.get("priority"),
    }


def matches_client(client: dict[str, Any], pattern: re.Pattern[str]) -> bool:
    values = [
        str(client.get("name") or ""),
        str(client.get("implementation") or ""),
        str(client.get("protocol") or ""),
    ]
    return any(pattern.search(value) for value in values)


def parse_bool(value: str) -> bool:
    lowered = value.casefold()
    if lowered in {"1", "yes", "true", "on", "enabled", "enable"}:
        return True
    if lowered in {"0", "no", "false", "off", "disabled", "disable"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid boolean: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--app",
        action="append",
        choices=sorted(APPS),
        help="Arr app to inspect. May be repeated; default is both.",
    )
    parser.add_argument(
        "--match",
        default=r"(?i)sabnzbd|sab",
        help="Regex matched against client name, implementation, and protocol.",
    )
    parser.add_argument(
        "--enabled",
        type=parse_bool,
        help="Desired enabled state. Omit for read-only listing.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the requested enabled state. Without this, changes are dry-run only.",
    )
    parser.add_argument(
        "--backup-path",
        help="Existing rollback backup path. Required with --apply.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    args = parser.parse_args()

    if args.apply and args.enabled is None:
        raise RuntimeError("--apply requires --enabled")
    if args.apply:
        if not args.backup_path:
            raise RuntimeError("--apply requires --backup-path")
        backup_path = Path(args.backup_path)
        if not backup_path.exists():
            raise RuntimeError(f"backup path does not exist: {backup_path}")

    apps = args.app or sorted(APPS)
    pattern = re.compile(args.match)
    results: list[dict[str, Any]] = []

    for app in apps:
        app_info = APPS[app]
        api_key = read_api_key(app_info["config"])
        clients = api_json(app_info["base_url"], api_key, "GET", "/api/v3/downloadclient")
        for client in clients:
            if not matches_client(client, pattern):
                continue

            before = client_summary(app, client)
            after = dict(before)
            changed = False

            if args.enabled is not None:
                after["enable"] = args.enabled
                changed = before["enable"] != args.enabled
                if args.apply and changed:
                    updated = dict(client)
                    updated["enable"] = args.enabled
                    client_id = updated.get("id")
                    if client_id is None:
                        raise RuntimeError(f"{app}: matched client has no id: {before}")
                    verified = api_json(
                        app_info["base_url"],
                        api_key,
                        "PUT",
                        f"/api/v3/downloadclient/{client_id}",
                        updated,
                    )
                    after = client_summary(app, verified)

            results.append(
                {
                    "app": app,
                    "id": before["id"],
                    "name": before["name"],
                    "implementation": before["implementation"],
                    "protocol": before["protocol"],
                    "before_enable": before["enable"],
                    "after_enable": after["enable"],
                    "changed": changed,
                    "applied": bool(args.apply and changed),
                }
            )

    if args.json:
        print(json.dumps({"results": results}, indent=2, sort_keys=True))
    else:
        for result in results:
            action = "applied" if result["applied"] else "would-change" if result["changed"] else "unchanged"
            print(
                f"{result['app']}: {result['name']} "
                f"({result['implementation']}, {result['protocol']}) "
                f"{result['before_enable']} -> {result['after_enable']} [{action}]"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
