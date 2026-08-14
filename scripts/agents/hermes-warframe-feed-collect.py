#!/usr/bin/env python3
"""Stage verified Warframe events and synchronize new calendar rows."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


CT = ZoneInfo("America/Chicago")
MAX_EVENTS = 64
GENERIC_DROPS = {
    "weekly prime time twitch drop",
    "shared weekly warframe twitch drop campaign",
}
KHAL = "/usr/bin/khal"
MAX_CALENDAR_SEARCH_BYTES = 262_144


class FeedError(Exception):
    """Raised when source events cannot be safely published."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def atomic_json(path: Path, value: dict[str, Any], mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def checked_url(value: Any, code: str) -> str:
    if not isinstance(value, str) or len(value) > 500:
        raise FeedError(code)
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise FeedError(code)
    return value


def normalize(raw: Any, now: datetime) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise FeedError("event-not-object")
    required = {
        "event_id",
        "title",
        "kind",
        "starts_at_ct",
        "ends_at_ct",
        "channel_url",
        "drop_summary",
        "source_title",
        "source_link",
        "notes",
    }
    if set(raw) != required:
        raise FeedError("event-schema")
    for key in ("event_id", "title", "kind", "drop_summary", "source_title", "notes"):
        if not isinstance(raw[key], str) or not raw[key].strip() or len(raw[key]) > 500:
            raise FeedError(f"event-{key}")
    if not re.fullmatch(r"[A-Za-z0-9-]{8,220}", raw["event_id"]):
        raise FeedError("event-id")
    try:
        start = datetime.fromisoformat(raw["starts_at_ct"]).astimezone(CT)
        end = datetime.fromisoformat(raw["ends_at_ct"]).astimezone(CT)
    except (TypeError, ValueError) as exc:
        raise FeedError("event-time") from exc
    if not start < end or end - start > timedelta(hours=8):
        raise FeedError("event-range")
    if start < now - timedelta(days=2) or start > now + timedelta(days=45):
        raise FeedError("event-window")
    drop = raw["drop_summary"].strip()
    if drop.casefold() in GENERIC_DROPS:
        raise FeedError(f"generic-drop:{raw['event_id']}")
    return {
        "eventId": raw["event_id"],
        "title": raw["title"].strip(),
        "kind": raw["kind"].strip(),
        "startsAtCt": start.isoformat(),
        "endsAtCt": end.isoformat(),
        "reminderAtUtc": (start - timedelta(hours=1)).astimezone(timezone.utc).isoformat(),
        "channelUrl": checked_url(raw["channel_url"], "event-channel"),
        "dropSummary": drop,
        "sourceTitle": raw["source_title"].strip(),
        "sourceUrl": checked_url(raw["source_link"], "event-source"),
        "notes": raw["notes"].strip(),
    }


def calendar_add(event: dict[str, Any]) -> None:
    start = datetime.fromisoformat(event["startsAtCt"]).astimezone(CT)
    end = datetime.fromisoformat(event["endsAtCt"]).astimezone(CT)
    description = "\n".join(
        (
            f"Channel: {event['channelUrl']}",
            f"Drop: {event['dropSummary']}",
            f"Source: {event['sourceUrl']}",
            f"Notes: {event['notes']}",
            f"Managed-ID: {event['eventId']}",
        )
    )
    subprocess.run(
        [
            KHAL,
            "new",
            "-a",
            "personal",
            start.strftime("%Y-%m-%d %H:%M"),
            end.strftime("%Y-%m-%d %H:%M"),
            "America/Chicago",
            event["title"],
            "::",
            description,
        ],
        check=True,
        timeout=45,
    )


def calendar_contains(event: dict[str, Any]) -> bool:
    marker = f"Managed-ID: {event['eventId']}"
    result = subprocess.run(
        [
            KHAL,
            "search",
            "-a",
            "personal",
            "--format",
            "{description}",
            marker,
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=45,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            result.args,
            output=result.stdout,
            stderr=result.stderr,
        )
    if len(result.stdout.encode("utf-8")) > MAX_CALENDAR_SEARCH_BYTES:
        raise FeedError("calendar-search-too-large")
    return marker in result.stdout


def synchronize_calendars(
    events: list[dict[str, Any]],
    state: dict[str, Any],
    now: datetime,
    state_path: Path,
) -> None:
    records = state["events"]
    for event in events:
        record = records.setdefault(event["eventId"], {})
        if record.get("calendarSyncedAt"):
            continue
        if datetime.fromisoformat(event["startsAtCt"]) <= now:
            continue
        if not calendar_contains(event):
            calendar_add(event)
        record["calendarSyncedAt"] = datetime.now(timezone.utc).isoformat()
        state["events"] = records
        atomic_json(state_path, state, mode=0o600)


def migrated_state(path: Path, legacy_path: Path) -> dict[str, Any]:
    current = load_json(path)
    if current.get("schemaVersion") == 1 and isinstance(current.get("events"), dict):
        return current
    legacy = load_json(legacy_path)
    events: dict[str, Any] = {}
    for key, value in (legacy.get("events") or {}).items():
        if isinstance(key, str) and isinstance(value, dict) and value.get("calendar_synced_at"):
            events[key] = {"calendarSyncedAt": value["calendar_synced_at"]}
    return {"schemaVersion": 1, "events": events}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parser-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--legacy-state", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.parser_root))
    try:
        feed = importlib.import_module("warframe_drops_feed")
        raw_events = [asdict(event) for event in feed.parse_events(feed.fetch_rss())]
        if not raw_events or len(raw_events) > MAX_EVENTS:
            raise FeedError("event-count")
        now = datetime.now(CT)
        events = [normalize(event, now) for event in raw_events]
        if len({event["eventId"] for event in events}) != len(events):
            raise FeedError("duplicate-event")
        state = migrated_state(args.state, args.legacy_state)
        records = state["events"]
        synchronize_calendars(events, state, now, args.state)
        keep_after = now - timedelta(days=14)
        active_ids = {
            event["eventId"]
            for event in events
            if datetime.fromisoformat(event["endsAtCt"]) >= keep_after
        }
        state["events"] = {key: value for key, value in records.items() if key in active_ids}
        state["updatedAt"] = datetime.now(timezone.utc).isoformat()
        atomic_json(args.state, state, mode=0o600)
        payload = {
            "schemaVersion": 1,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "events": events,
        }
        atomic_json(args.output, payload)
        print(json.dumps({"status": "ok", "events": len(events)}, separators=(",", ":")))
        return 0
    except (FeedError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Warframe feed collection failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
