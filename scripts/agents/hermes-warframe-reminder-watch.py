#!/usr/bin/env python3
"""Emit due Warframe reminders from a bounded staged event feed."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from hermes_cron_delivery import (
    DeliveryStateError,
    load_job_status,
    reconcile,
    stage,
)


SOURCE = Path("/var/lib/hermes-automation/warframe-events.json")
MAX_BYTES = 262_144
MAX_AGE = timedelta(hours=18)
JOB_NAME = "astra-warframe-reminder-watch"
JOB_SCRIPT = "hermes-warframe-reminder-watch.py"


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def record_health(home: Path, now: datetime, *, healthy: bool, status: str) -> None:
    atomic_json(
        home / "state" / "warframe-reminder-health.json",
        {
            "schemaVersion": 1,
            "checkedAt": now.isoformat(),
            "healthy": healthy,
            "status": status,
        },
    )


def run_main() -> int:
    now = datetime.now(timezone.utc)
    home = Path(os.environ.get("HERMES_HOME", Path.home())).resolve()
    try:
        stat = SOURCE.stat()
        if not SOURCE.is_file() or SOURCE.is_symlink() or stat.st_size > MAX_BYTES:
            raise ValueError("source-shape")
        value = json.loads(SOURCE.read_text(encoding="utf-8"))
        generated = datetime.fromisoformat(value["generatedAt"].replace("Z", "+00:00"))
        events = value["events"]
        if value.get("schemaVersion") != 1 or not isinstance(events, list):
            raise ValueError("source-schema")
        age = now - generated.astimezone(timezone.utc)
        if age < timedelta(minutes=-5) or age > MAX_AGE:
            raise ValueError("source-stale")
    except (OSError, UnicodeError, ValueError, KeyError, json.JSONDecodeError):
        record_health(home, now, healthy=False, status="source-unavailable")
        return 0
    state_path = home / "state" / "warframe-reminders.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {"delivered": {}}
    delivered = state.get("delivered") if isinstance(state, dict) else None
    if not isinstance(delivered, dict):
        delivered = {}
    pending = state.get("pending") if isinstance(state, dict) else None
    cutoff = (now - timedelta(days=14)).isoformat()
    delivered = {key: value for key, value in delivered.items() if str(value) >= cutoff}
    try:
        status = load_job_status(home, JOB_NAME, JOB_SCRIPT)
        disposition, pending = reconcile(pending, status)
    except DeliveryStateError:
        record_health(home, now, healthy=False, status="delivery-state-invalid")
        return 0
    if disposition == "delivered" and pending is not None:
        for key in pending["keys"]:
            delivered[key] = now.isoformat()
        pending = None
        atomic_json(state_path, {"delivered": delivered, "pending": pending})
    elif disposition == "retry" and pending is not None:
        atomic_json(state_path, {"delivered": delivered, "pending": pending})
        record_health(home, now, healthy=True, status="delivery-retry")
        print(pending["payload"])
        return 0
    elif disposition == "waiting":
        record_health(home, now, healthy=True, status="delivery-pending")
        return 0
    lines: list[str] = []
    due_keys: list[str] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        try:
            event_id = event["eventId"]
            reminder_at = datetime.fromisoformat(event["reminderAtUtc"].replace("Z", "+00:00")).astimezone(timezone.utc)
            start = datetime.fromisoformat(event["startsAtCt"])
            if not isinstance(event_id, str) or event_id in delivered:
                continue
            if not timedelta(0) <= now - reminder_at < timedelta(minutes=2):
                continue
            lines.append(
                f"<@740687933803331726> **Warframe drop:** {event['title']} "
                f"starts at {start.strftime('%-I:%M %p CT')}. Drop: {event['dropSummary']}. "
                f"Channel: <{event['channelUrl']}>"
            )
            due_keys.append(event_id)
        except (KeyError, TypeError, ValueError):
            continue
    if lines:
        payload = "\n".join(lines)
        try:
            pending = stage(due_keys, payload, status, now)
        except DeliveryStateError:
            record_health(home, now, healthy=False, status="delivery-stage-refused")
            return 0
    state = {"delivered": delivered, "pending": pending}
    atomic_json(state_path, state)
    if lines:
        record_health(home, now, healthy=True, status="alert-staged")
        print(payload)
    else:
        record_health(home, now, healthy=True, status="idle")
    return 0


def main() -> int:
    try:
        return run_main()
    except Exception:
        try:
            home = Path(os.environ.get("HERMES_HOME", Path.home())).resolve()
            record_health(
                home,
                datetime.now(timezone.utc),
                healthy=False,
                status="evaluator-error",
            )
        except Exception:
            pass
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
