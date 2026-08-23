#!/usr/bin/env python3
"""Configure exact Sonarr/Radarr OnGrab webhooks for arr-grab-context."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import urllib.request
from pathlib import Path
from typing import Any


APPS = {
    "sonarr": ("http://127.0.0.1:8989/api/v3", Path("/opt/media-stack/sonarr/config.xml")),
    "radarr": ("http://127.0.0.1:7878/api/v3", Path("/opt/media-stack/radarr/config.xml")),
}


def api_key(config_path: Path) -> str:
    match = re.search(r"<ApiKey>([^<]+)</ApiKey>", config_path.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError(f"API key not found in {config_path}")
    return match.group(1)


def request_json(
    base_url: str,
    key: str,
    path: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> Any:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        base_url.rstrip("/") + "/" + path.lstrip("/"),
        data=body,
        method=method,
        headers={"X-Api-Key": key, "Accept": "application/json", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        content = response.read()
    return json.loads(content.decode("utf-8")) if content else None


def desired_notification(schema: dict[str, Any], name: str, webhook_url: str) -> dict[str, Any]:
    desired = {key: value for key, value in schema.items() if key != "presets"}
    desired["name"] = name
    for key in list(desired):
        if key.startswith("on") and isinstance(desired[key], bool):
            desired[key] = False
    desired["onGrab"] = True
    desired["tags"] = []
    field_values = {
        "url": webhook_url,
        "method": 1,
        "username": "",
        "password": "",
        "headers": [],
    }
    for field in desired.get("fields", []):
        if field.get("name") in field_values:
            field["value"] = field_values[field["name"]]
    return desired


def comparable(notification: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": notification.get("name"),
        "implementation": notification.get("implementation"),
        "configContract": notification.get("configContract"),
        "onGrab": notification.get("onGrab"),
        "events": {
            key: value
            for key, value in notification.items()
            if key.startswith("on") and isinstance(value, bool)
        },
        "fields": {
            field.get("name"): field.get("value")
            for field in notification.get("fields", [])
            if field.get("name") in {"url", "method", "username", "password", "headers"}
        },
        "tags": notification.get("tags") or [],
    }


def timestamp() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def configure(args: argparse.Namespace) -> dict[str, Any]:
    state: dict[str, Any] = {"changed": False, "apps": {}}
    pending: list[tuple[str, str, str, list[dict[str, Any]], dict[str, Any], dict[str, Any] | None]] = []
    for app, (default_url, default_config) in APPS.items():
        base_url = getattr(args, f"{app}_api") or default_url
        config_path = getattr(args, f"{app}_config") or default_config
        key = api_key(config_path)
        schemas = request_json(base_url, key, "notification/schema")
        schema = next(item for item in schemas if item.get("implementation") == "Webhook")
        notifications = request_json(base_url, key, "notification")
        current = next((item for item in notifications if item.get("name") == args.name), None)
        desired = desired_notification(schema, args.name, args.webhook_url)
        changed = current is None or comparable(current) != comparable(desired)
        state["apps"][app] = {"changed": changed, "action": "create" if current is None else "update"}
        if changed:
            pending.append((app, base_url, key, notifications, desired, current))

    state["needs_change"] = bool(pending)
    if not pending or not args.apply:
        return state

    backup_dir = args.backup_root / f"{timestamp()}-arr-grab-context-notifications"
    backup_dir.mkdir(parents=True, exist_ok=False)
    for app, _base_url, _key, notifications, _desired, _current in pending:
        (backup_dir / f"{app}-notifications.json").write_text(
            json.dumps(notifications, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    for app, base_url, key, _notifications, desired, current in pending:
        if current is None:
            request_json(base_url, key, "notification", method="POST", payload=desired)
        else:
            desired["id"] = current["id"]
            request_json(base_url, key, f"notification/{current['id']}", method="PUT", payload=desired)
        state["apps"][app]["applied"] = True
    state["changed"] = True
    state["backup_dir"] = str(backup_dir)
    return state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--name", default="Arr Grab Context")
    parser.add_argument("--webhook-url", default="http://arr-grab-context:9899/v1/events")
    parser.add_argument("--backup-root", type=Path, default=Path("/srv/live-rollbacks/docker-vm/media-release"))
    for app, (default_url, default_config) in APPS.items():
        parser.add_argument(f"--{app}-api", default=default_url)
        parser.add_argument(f"--{app}-config", type=Path, default=default_config)
    return parser.parse_args()


def main() -> int:
    state = configure(parse_args())
    print(json.dumps(state, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
