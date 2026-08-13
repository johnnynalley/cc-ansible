#!/usr/bin/env python3
"""Emit only source-backed Rigel academic alerts for Hermes no-agent cron."""

from __future__ import annotations

import fcntl
import hashlib
import json
import errno
import os
import stat
import tempfile
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

SCHEMA_VERSION = 1
TIMEZONE = "America/Chicago"
ALERT_DAYS = {0, 1, 3, 7}
MAX_SOURCE_BYTES = 262_144
MAX_EVENTS = 256
MAX_EMITTED = 512
MAX_DELIVERY_CHARS = 1_800
EVIDENCE_KINDS = {"syllabus", "instructor", "registrar", "user-confirmed"}


class ScheduleError(ValueError):
    """A bounded source or state failure that must stay out of Discord."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ScheduleError(code)


def checked_text(value: Any, code: str, limit: int = 160) -> str:
    require(isinstance(value, str), code)
    text = value.strip()
    require(0 < len(text) <= limit, code)
    require(not any(ord(char) < 32 for char in text), code)
    return text


def read_json(path: Path, *, optional: bool = False) -> dict[str, Any] | None:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
    except FileNotFoundError:
        if optional:
            return None
        raise ScheduleError("source-missing") from None
    except OSError as exc:
        code = "input-symlink" if exc.errno == errno.ELOOP else "input-unreadable"
        raise ScheduleError(code) from exc
    try:
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            metadata = os.fstat(handle.fileno())
            require(stat.S_ISREG(metadata.st_mode), "input-not-regular")
            require(metadata.st_size <= MAX_SOURCE_BYTES, "input-too-large")
            content = handle.read(MAX_SOURCE_BYTES + 1)
            require(len(content.encode("utf-8")) <= MAX_SOURCE_BYTES, "input-too-large")
        value = json.loads(content)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ScheduleError("input-invalid-json") from exc
    require(isinstance(value, dict), "input-not-object")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def schedule_lock(home: Path) -> Iterator[None]:
    lock_path = home / "state" / "rigel-schedule.lock"
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def parse_date(value: Any, code: str) -> date:
    text = checked_text(value, code, 10)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ScheduleError(code) from exc


def parse_timestamp(value: Any, code: str) -> datetime:
    text = checked_text(value, code, 40)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScheduleError(code) from exc
    require(parsed.tzinfo is not None, code)
    return parsed


def validate_evidence(value: Any, code: str) -> dict[str, str]:
    require(isinstance(value, dict), code)
    require(set(value) == {"kind", "reference"}, code)
    kind = checked_text(value["kind"], code, 40)
    require(kind in EVIDENCE_KINDS, code)
    return {
        "kind": kind,
        "reference": checked_text(value["reference"], code, 240),
    }


def validate_study_status(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    require(isinstance(value, dict), "study-status-not-object")
    require(set(value) == {"mastery", "weakAreas"}, "study-status-schema")
    mastery = checked_text(value["mastery"], "study-mastery", 120)
    weak_areas = value["weakAreas"]
    require(isinstance(weak_areas, list), "study-weak-areas")
    require(len(weak_areas) <= 8, "study-weak-areas")
    return {
        "mastery": mastery,
        "weakAreas": [
            checked_text(item, "study-weak-area", 120) for item in weak_areas
        ],
    }


def validate_source(data: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    require(
        set(data)
        == {
            "schemaVersion",
            "timezone",
            "semester",
            "events",
            "calendarRequests",
        },
        "source-schema",
    )
    require(data["schemaVersion"] == SCHEMA_VERSION, "source-version")
    require(data["timezone"] == TIMEZONE, "source-timezone")

    semester = data["semester"]
    require(isinstance(semester, dict), "semester-not-object")
    require(
        set(semester) == {"id", "status", "startsOn", "endsOn"},
        "semester-schema",
    )
    checked_text(semester["id"], "semester-id", 80)
    require(
        semester["status"] in {"active", "completed", "inactive"},
        "semester-status",
    )
    starts_on = parse_date(semester["startsOn"], "semester-start")
    ends_on = parse_date(semester["endsOn"], "semester-end")
    require(starts_on <= ends_on, "semester-range")

    requests = data["calendarRequests"]
    require(isinstance(requests, list), "requests-not-list")
    pending_requests = 0
    request_ids = set()
    for request in requests:
        require(isinstance(request, dict), "request-not-object")
        require(
            set(request) == {"id", "summary", "confirmed", "status", "source"},
            "request-schema",
        )
        request_id = checked_text(request["id"], "request-id", 100)
        require(request_id not in request_ids, "request-id-duplicate")
        request_ids.add(request_id)
        checked_text(request["summary"], "request-summary", 240)
        require(isinstance(request["confirmed"], bool), "request-confirmed")
        require(request["status"] in {"pending", "completed"}, "request-status")
        validate_evidence(request["source"], "request-source")
        if request["confirmed"] and request["status"] == "pending":
            pending_requests += 1

    events = data["events"]
    require(isinstance(events, list), "events-not-list")
    require(len(events) <= MAX_EVENTS, "events-too-many")
    normalized = []
    event_ids = set()
    for event in events:
        require(isinstance(event, dict), "event-not-object")
        require(
            set(event)
            in (
                {"id", "course", "title", "startsAt", "status", "source"},
                {
                    "id",
                    "course",
                    "title",
                    "startsAt",
                    "status",
                    "source",
                    "studyStatus",
                },
            ),
            "event-schema",
        )
        event_id = checked_text(event["id"], "event-id", 100)
        require(event_id not in event_ids, "event-id-duplicate")
        event_ids.add(event_id)
        normalized_event = {
            "id": event_id,
            "course": checked_text(event["course"], "event-course", 100),
            "title": checked_text(event["title"], "event-title", 180),
            "startsAt": parse_timestamp(event["startsAt"], "event-start"),
            "status": event["status"],
            "source": validate_evidence(event["source"], "event-source"),
            "studyStatus": validate_study_status(event.get("studyStatus")),
        }
        require(
            normalized_event["status"] in {"scheduled", "completed", "cancelled"},
            "event-status",
        )
        local_event_date = (
            normalized_event["startsAt"].astimezone(ZoneInfo(TIMEZONE)).date()
        )
        require(starts_on <= local_event_date <= ends_on, "event-semester-range")
        normalized.append(normalized_event)

    if semester["status"] != "active":
        require(
            not any(event["status"] == "scheduled" for event in normalized),
            "inactive-semester-scheduled-event",
        )
    return normalized, pending_requests


def load_ledger(path: Path) -> dict[str, str]:
    data = read_json(path, optional=True)
    if data is None:
        return {}
    require(set(data) == {"schemaVersion", "emitted"}, "ledger-schema")
    require(data["schemaVersion"] == SCHEMA_VERSION, "ledger-version")
    emitted = data["emitted"]
    require(isinstance(emitted, dict), "ledger-emitted")
    require(len(emitted) <= MAX_EMITTED, "ledger-too-large")
    for key, value in emitted.items():
        checked_text(key, "ledger-key", 160)
        parse_timestamp(value, "ledger-timestamp")
    return emitted


def event_fingerprint(event: dict[str, Any]) -> str:
    stable = {
        "id": event["id"],
        "course": event["course"],
        "title": event["title"],
        "startsAt": event["startsAt"].isoformat(),
        "source": event["source"],
    }
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:20]


def safe_output_text(value: str) -> str:
    return value.replace("@", "at ")


def format_event(event: dict[str, Any], days: int, local_start: datetime) -> str:
    when = f"{local_start.strftime('%b')} {local_start.day}"
    if local_start.hour or local_start.minute:
        when += f" at {local_start.strftime('%-I:%M %p')}"
    distance = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
    message = (
        f"{safe_output_text(event['course'])}: "
        f"{safe_output_text(event['title'])} is {distance} ({when})."
    )
    study = event["studyStatus"]
    if study:
        message += f" Mastery: {safe_output_text(study['mastery'])}."
        if study["weakAreas"]:
            areas = ", ".join(safe_output_text(item) for item in study["weakAreas"])
            message += f" Weak areas: {areas}."
    return message


def status_payload(
    now: datetime,
    *,
    healthy: bool,
    status_value: str,
    source_digest: str = "",
    due_alerts: int = 0,
    pending_calendar_requests: int = 0,
    error_code: str = "",
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "checkedAt": now.astimezone(timezone.utc).isoformat(),
        "healthy": healthy,
        "status": status_value,
        "errorCode": error_code,
        "sourceDigest": source_digest,
        "dueAlerts": due_alerts,
        "pendingCalendarRequests": pending_calendar_requests,
    }


def run(home: Path, now: datetime) -> str:
    require(home.is_absolute(), "home-not-absolute")
    source_path = home / "data" / "academic-state.json"
    ledger_path = home / "state" / "rigel-schedule-state.json"
    health_path = home / "state" / "rigel-schedule-health.json"
    zone = ZoneInfo(TIMEZONE)
    local_now = now.astimezone(zone)

    with schedule_lock(home):
        try:
            source = read_json(source_path)
            assert source is not None
            source_digest = hashlib.sha256(
                json.dumps(source, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            events, pending_requests = validate_source(source)
            emitted = load_ledger(ledger_path)
            due = []
            for event in events:
                if event["status"] != "scheduled":
                    continue
                if event["startsAt"] < now:
                    continue
                local_start = event["startsAt"].astimezone(zone)
                days = (local_start.date() - local_now.date()).days
                if days not in ALERT_DAYS:
                    continue
                key = f"{event['id']}:{days}:{event_fingerprint(event)}"
                if key not in emitted:
                    due.append((local_start, days, key, event))
            due.sort(key=lambda item: (item[0], item[3]["id"]))
            require(len(due) <= 10, "too-many-due-alerts")
            if not due:
                atomic_json(
                    health_path,
                    status_payload(
                        now,
                        healthy=True,
                        status_value="idle",
                        source_digest=source_digest,
                        pending_calendar_requests=pending_requests,
                    ),
                )
                return ""

            selected = []
            messages = []
            for candidate in due:
                local_start, days, _, event = candidate
                message = format_event(event, days, local_start)
                proposed = "\n".join([*messages, message])
                if len(proposed) > MAX_DELIVERY_CHARS:
                    break
                selected.append(candidate)
                messages.append(message)
            require(bool(selected), "alert-too-large")

            emitted_at = now.astimezone(timezone.utc).isoformat()
            for _, _, key, _ in selected:
                emitted[key] = emitted_at
            if len(emitted) > MAX_EMITTED:
                ordered = sorted(emitted.items(), key=lambda item: item[1])
                emitted = dict(ordered[-MAX_EMITTED:])
            atomic_json(
                ledger_path,
                {"schemaVersion": SCHEMA_VERSION, "emitted": emitted},
            )
            try:
                atomic_json(
                    health_path,
                    status_payload(
                        now,
                        healthy=True,
                        status_value="alert-emitted",
                        source_digest=source_digest,
                        due_alerts=len(selected),
                        pending_calendar_requests=pending_requests,
                    ),
                )
            except OSError:
                pass
            return "\n".join(messages)
        except ScheduleError as exc:
            atomic_json(
                health_path,
                status_payload(
                    now,
                    healthy=False,
                    status_value="source-error",
                    error_code=str(exc),
                ),
            )
            return ""


def main() -> int:
    home_value = os.environ.get("HERMES_HOME", "")
    home = Path(home_value)
    try:
        output = run(home, datetime.now(timezone.utc))
    except Exception:
        try:
            if home.is_absolute():
                now = datetime.now(timezone.utc)
                atomic_json(
                    home / "state" / "rigel-schedule-health.json",
                    status_payload(
                        now,
                        healthy=False,
                        status_value="evaluator-error",
                        error_code="unhandled-evaluator-error",
                    ),
                )
        except Exception:
            pass
        return 0
    if output:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
