#!/usr/bin/env python3
"""Run and verify a native Sonarr, Radarr, or Prowlarr backup."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET


APPS = {
    "sonarr": {
        "base_url": "http://127.0.0.1:8989",
        "config": "/opt/media-stack/sonarr/config.xml",
        "backup_dir": "/opt/media-stack/sonarr/Backups/manual",
        "api_prefix": "/api/v3",
    },
    "radarr": {
        "base_url": "http://127.0.0.1:7878",
        "config": "/opt/media-stack/radarr/config.xml",
        "backup_dir": "/opt/media-stack/radarr/Backups/manual",
        "api_prefix": "/api/v3",
    },
    "prowlarr": {
        "base_url": "http://127.0.0.1:9696",
        "config": "/opt/media-stack/prowlarr/config.xml",
        "backup_dir": "/opt/media-stack/prowlarr/Backups/manual",
        "api_prefix": "/api/v1",
    },
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
        data = json.dumps(body).encode()
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


def newest_backup(path: Path, not_before: float) -> Path | None:
    candidates = [
        item
        for item in path.glob("*.zip")
        if item.is_file() and item.stat().st_mtime >= not_before
    ]
    return max(candidates, key=lambda item: item.stat().st_mtime) if candidates else None


def run_backup(app: str, wait_seconds: int, poll_seconds: float) -> dict[str, Any]:
    config = APPS[app]
    base_url = str(config["base_url"])
    api_key = read_api_key(str(config["config"]))
    api_prefix = str(config["api_prefix"])
    started_at = time.time()
    command = request_json(
        base_url,
        api_key,
        "POST",
        f"{api_prefix}/command",
        {"name": "Backup"},
    )
    command_id = command.get("id") if isinstance(command, dict) else None
    if not isinstance(command_id, int):
        raise RuntimeError(f"{app}: backup command returned no numeric id")

    deadline = time.monotonic() + wait_seconds
    status = "unknown"
    while time.monotonic() < deadline:
        current = request_json(
            base_url,
            api_key,
            "GET",
            f"{api_prefix}/command/{command_id}",
        )
        status = str(current.get("status") or "unknown").casefold()
        if status == "completed":
            break
        if status in {"failed", "aborted", "cancelled", "canceled"}:
            raise RuntimeError(f"{app}: backup command {command_id} ended as {status}")
        time.sleep(poll_seconds)
    else:
        raise RuntimeError(
            f"{app}: backup command {command_id} did not finish within {wait_seconds}s"
        )

    backup = newest_backup(Path(str(config["backup_dir"])), started_at - 2)
    if backup is None:
        raise RuntimeError(f"{app}: command completed but no new native backup archive exists")
    return {
        "app": app,
        "command_id": command_id,
        "status": status,
        "backup": str(backup),
        "size_bytes": backup.stat().st_size,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, choices=sorted(APPS))
    parser.add_argument("--wait-seconds", type=int, default=180)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args()
    if args.wait_seconds <= 0 or args.poll_seconds <= 0:
        raise RuntimeError("wait and poll intervals must be positive")
    print(
        json.dumps(
            run_backup(args.app, args.wait_seconds, args.poll_seconds),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
