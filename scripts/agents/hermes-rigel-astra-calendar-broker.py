#!/usr/bin/env python3
"""Serve a narrow Rigel-to-Astra calendar API over a local Unix socket."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import socketserver
import stat
import struct
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

MAX_REQUEST_BYTES = 128 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
MAX_EVENTS = 20
MAX_TEXT = 1000
EVENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
SAFE_TEXT_RE = re.compile(r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$")
LOCAL_ZONE = ZoneInfo("America/Chicago")
MARKER_PREFIX = "Hermes-Rigel:"
CALENDAR_HOME = Path("/var/lib/hermes-rigel-calendar")


class BrokerError(RuntimeError):
    """Expected fixed-code broker failure."""


def compact(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def error(code: str) -> dict[str, Any]:
    return {"schemaVersion": 1, "status": "error", "code": code}


def require_text(value: Any, code: str, *, maximum: int = MAX_TEXT) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or SAFE_TEXT_RE.fullmatch(value) is None
    ):
        raise BrokerError(code)
    return value.strip()


def parse_timestamp(value: Any) -> datetime:
    raw = require_text(value, "invalid-start", maximum=64)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BrokerError("invalid-start") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BrokerError("invalid-start")
    return parsed.astimezone(LOCAL_ZONE)


def validate_event(value: Any, *, adding: bool) -> dict[str, Any]:
    required = {"eventId", "course", "event", "startsAt", "description", "weight"}
    allowed = required | {"endsAt", "confirmed"}
    if not isinstance(value, dict) or set(value) - allowed or not required <= set(value):
        raise BrokerError("invalid-event")
    event_id = require_text(value["eventId"], "invalid-event-id", maximum=128)
    if EVENT_ID_RE.fullmatch(event_id) is None:
        raise BrokerError("invalid-event-id")
    starts_at = parse_timestamp(value["startsAt"])
    ends_at = parse_timestamp(value["endsAt"]) if value.get("endsAt") else starts_at + timedelta(hours=1)
    if ends_at <= starts_at or ends_at - starts_at > timedelta(days=2):
        raise BrokerError("invalid-end")
    if adding and value.get("confirmed") is not True:
        raise BrokerError("confirmation-required")
    if not adding and "confirmed" in value:
        raise BrokerError("invalid-event")
    normalized = {
        "eventId": event_id,
        "course": require_text(value["course"], "invalid-course", maximum=200),
        "event": require_text(value["event"], "invalid-event-title", maximum=300),
        "startsAt": starts_at,
        "endsAt": ends_at,
        "description": require_text(value["description"], "invalid-description"),
        "weight": require_text(value["weight"], "invalid-weight", maximum=80),
    }
    if any(MARKER_PREFIX in item for item in normalized.values() if isinstance(item, str)):
        raise BrokerError("reserved-marker")
    return normalized


def command_environment() -> dict[str, str]:
    return {
        "HOME": str(CALENDAR_HOME),
        "XDG_CONFIG_HOME": str(CALENDAR_HOME / ".config"),
        "XDG_DATA_HOME": str(CALENDAR_HOME / ".local/share"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
    }


def run(
    argv: list[str],
    *,
    timeout: int,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    arguments: dict[str, Any] = {
        "env": command_environment(),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "timeout": timeout,
        "check": False,
    }
    if input_text is None:
        arguments["stdin"] = subprocess.DEVNULL
    else:
        arguments["input"] = input_text
    return subprocess.run(argv, **arguments)


def failure_category(result: subprocess.CompletedProcess[str]) -> str:
    detail = f"{result.stdout}\n{result.stderr}".lower()
    categories = (
        (("401", "403", "unauthorized", "authentication"), "authentication"),
        (("name or service not known", "temporary failure in name resolution", "nodename nor servname"), "dns"),
        (("certificate", "ssl", "tls"), "tls"),
        (("timed out", "timeout"), "timeout"),
        (("connection refused", "network is unreachable", "no route to host"), "network"),
        (("permission denied", "operation not permitted"), "permission"),
        (("no such file or directory", "not found"), "missing-path"),
        (("config", "parse", "invalid value"), "invalid-config"),
    )
    for needles, category in categories:
        if any(needle in detail for needle in needles):
            return category
    return "unclassified"


def sync_calendar() -> None:
    collection_cache = CALENDAR_HOME / ".local/share/vdirsyncer/status/personal.collections"
    collection_root = CALENDAR_HOME / ".local/share/vdirsyncer/calendars"
    if collection_cache.exists() or collection_cache.is_symlink():
        info = os.lstat(collection_cache)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise BrokerError("calendar-state-unsafe")
    else:
        root_info = os.lstat(collection_root)
        if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
            raise BrokerError("calendar-state-unsafe")
        if any(collection_root.iterdir()):
            raise BrokerError("calendar-discovery-manual-review")
        discovered = run(
            ["/usr/bin/vdirsyncer", "discover", "--no-list", "personal"],
            timeout=180,
            input_text="y\n" * 256,
        )
        if discovered.returncode != 0:
            raise BrokerError(f"calendar-discovery-{failure_category(discovered)}")
        if not collection_cache.is_file() or collection_cache.is_symlink():
            raise BrokerError("calendar-discovery-cache-missing")
    result = run(["/usr/bin/vdirsyncer", "sync", "personal"], timeout=180)
    if result.returncode != 0:
        raise BrokerError(f"calendar-sync-{failure_category(result)}")


def list_day(day: datetime) -> list[dict[str, Any]]:
    start = day.date().isoformat()
    end = (day.date() + timedelta(days=1)).isoformat()
    result = run(
        [
            "/usr/bin/khal",
            "list",
            "-a",
            "personal",
            "--json",
            "title,start,end,description",
            start,
            end,
        ],
        timeout=40,
    )
    if result.returncode != 0:
        raise BrokerError("calendar-query-unavailable")
    events: list[dict[str, Any]] = []
    try:
        for line in result.stdout.splitlines():
            value = json.loads(line)
            if not isinstance(value, list):
                raise ValueError("not-list")
            for item in value:
                if isinstance(item, dict):
                    events.append(item)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise BrokerError("calendar-query-invalid") from exc
    return events


def normalized_words(value: str) -> list[str]:
    return [word for word in re.findall(r"[a-z0-9]+", value.lower()) if len(word) > 1]


def calendar_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_ZONE)
    return parsed.astimezone(LOCAL_ZONE)


def event_present(requested: dict[str, Any], existing: list[dict[str, Any]]) -> bool:
    marker = f"[{MARKER_PREFIX}{requested['eventId']}]"
    wanted_title = normalized_words(requested["event"])
    for item in existing:
        title = str(item.get("title") or "")
        description = str(item.get("description") or "")
        if marker in description:
            return True
        observed_start = calendar_timestamp(item.get("start"))
        if (
            wanted_title
            and normalized_words(title) == wanted_title
            and observed_start is not None
            and abs(observed_start - requested["startsAt"]) <= timedelta(minutes=5)
        ):
            return True
    return False


def add_event(event: dict[str, Any]) -> None:
    marker = f"[{MARKER_PREFIX}{event['eventId']}]"
    description = f"{event['description']} | {event['course']} | {event['weight']} | {marker}"
    result = run(
        [
            "/usr/bin/khal",
            "new",
            "-a",
            "personal",
            event["startsAt"].strftime("%Y-%m-%d %H:%M"),
            event["endsAt"].strftime("%Y-%m-%d %H:%M"),
            event["event"],
            "::",
            description,
        ],
        timeout=40,
    )
    if result.returncode != 0:
        raise BrokerError("calendar-add-failed")


def process(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BrokerError("invalid-request")
    allowed = {"schemaVersion", "operation", "sessionId", "events"}
    if set(value) != allowed or value.get("schemaVersion") != 1:
        raise BrokerError("invalid-request")
    operation = value.get("operation")
    if operation not in {"calendar_check", "calendar_add"}:
        raise BrokerError("operation-denied")
    session_id = require_text(value.get("sessionId"), "invalid-session", maximum=128)
    if SESSION_ID_RE.fullmatch(session_id) is None:
        raise BrokerError("invalid-session")
    raw_events = value.get("events")
    if not isinstance(raw_events, list) or not 1 <= len(raw_events) <= MAX_EVENTS:
        raise BrokerError("invalid-events")
    adding = operation == "calendar_add"
    events = [validate_event(item, adding=adding) for item in raw_events]
    if len({item["eventId"] for item in events}) != len(events):
        raise BrokerError("duplicate-event-id")

    sync_calendar()
    by_day: dict[str, list[dict[str, Any]]] = {}
    results = []
    for event in events:
        day = event["startsAt"].date().isoformat()
        existing = by_day.setdefault(day, list_day(event["startsAt"]))
        present = event_present(event, existing)
        if adding and not present:
            add_event(event)
            results.append({"eventId": event["eventId"], "state": "ADDED"})
        else:
            results.append(
                {
                    "eventId": event["eventId"],
                    "state": "ON_CALENDAR" if present else "NOT_ON_CALENDAR",
                }
            )
    if adding and any(item["state"] == "ADDED" for item in results):
        try:
            sync_calendar()
        except BrokerError:
            for item in results:
                if item["state"] == "ADDED":
                    item["state"] = "PENDING_SYNC"
            return {"schemaVersion": 1, "status": "pending", "results": results}
    print(
        json.dumps(
            {
                "event": "rigel-astra-calendar",
                "operation": operation,
                "requests": len(events),
                "states": sorted(item["state"] for item in results),
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        flush=True,
    )
    return {"schemaVersion": 1, "status": "ok", "results": results}


class LiaisonHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        peer = self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _, uid, _ = struct.unpack("3i", peer)
        if uid != self.server.allowed_uid:  # type: ignore[attr-defined]
            self.wfile.write(compact(error("peer-denied")))
            return
        raw = self.rfile.readline(MAX_REQUEST_BYTES + 1)
        if not raw or len(raw) > MAX_REQUEST_BYTES or not raw.endswith(b"\n"):
            self.wfile.write(compact(error("invalid-request")))
            return
        try:
            response = process(json.loads(raw))
        except (BrokerError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            response = error(str(exc) if isinstance(exc, BrokerError) else "invalid-request")
        except Exception:
            response = error("broker-failure")
        if response.get("status") == "error":
            print(
                json.dumps(
                    {
                        "event": "rigel-astra-calendar",
                        "status": "error",
                        "code": response.get("code", "broker-failure"),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                flush=True,
            )
        encoded = compact(response)
        self.wfile.write(encoded if len(encoded) <= MAX_RESPONSE_BYTES else compact(error("response-too-large")))


class LiaisonServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False


def notify_systemd_ready() -> None:
    notify_socket = os.environ.get("NOTIFY_SOCKET", "")
    if not notify_socket:
        return
    address = f"\0{notify_socket[1:]}" if notify_socket.startswith("@") else notify_socket
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
        client.connect(address)
        client.sendall(b"READY=1")


def serve(path: Path, allowed_uid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        info = os.lstat(path)
        if not stat.S_ISSOCK(info.st_mode):
            raise BrokerError("socket-path-unsafe")
        path.unlink()
    with LiaisonServer(str(path), LiaisonHandler) as server:
        server.allowed_uid = allowed_uid  # type: ignore[attr-defined]
        os.chmod(path, 0o660)
        notify_systemd_ready()
        server.serve_forever(poll_interval=0.5)


def main() -> int:
    global CALENDAR_HOME
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--allowed-uid", type=int, required=True)
    parser.add_argument("--home", type=Path, default=CALENDAR_HOME)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if not args.socket.is_absolute() or not args.home.is_absolute() or args.allowed_uid <= 0:
            raise BrokerError("invalid-configuration")
        CALENDAR_HOME = args.home
        for path in (Path("/usr/bin/khal"), Path("/usr/bin/vdirsyncer")):
            if not path.is_file() or path.is_symlink() or not os.access(path, os.X_OK):
                raise BrokerError("dependency-unavailable")
        if args.check:
            print(json.dumps({"status": "ok", "schemaVersion": 1}, sort_keys=True))
            return 0
        serve(args.socket, args.allowed_uid)
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "code": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
