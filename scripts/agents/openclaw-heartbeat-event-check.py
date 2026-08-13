#!/usr/bin/env python3
"""Wait for one fresh, silent native OpenClaw heartbeat event."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

MAX_OUTPUT_BYTES = 64 * 1024
SUCCESS_STATUSES = {"ok-empty", "ok-token"}
WAIT_STATUSES = {"skipped"}
FORBIDDEN_PREVIEW_TERMS = ("heartbeat_ok", "thinking process", "exec failed")
MIN_UNIX_MILLISECONDS = 946_684_800_000
MAX_START_AGE_MS = 24 * 60 * 60 * 1000
MAX_FUTURE_SKEW_MS = 60 * 1000


class HeartbeatEventError(RuntimeError):
    """Raised when native heartbeat evidence violates the rehearsal contract."""


def _fail(code: str) -> None:
    raise HeartbeatEventError(code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        _fail(code)


def _executable(path: Path) -> Path:
    _require(path.is_absolute(), "openclaw-not-absolute")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise HeartbeatEventError("openclaw-unavailable") from exc
    _require(not path.is_symlink(), "openclaw-symlink")
    _require(stat.S_ISREG(metadata.st_mode), "openclaw-not-regular")
    _require(os.access(path, os.X_OK), "openclaw-not-executable")
    return path


def validate_started_at_ms(started_at_ms: int, *, now_ms: int | None = None) -> int:
    """Reject timestamps in seconds, nanoseconds, or an implausible time range."""
    _require(
        isinstance(started_at_ms, int) and not isinstance(started_at_ms, bool),
        "started-at-invalid",
    )
    current_ms = time.time_ns() // 1_000_000 if now_ms is None else now_ms
    _require(
        MIN_UNIX_MILLISECONDS <= started_at_ms,
        "started-at-not-unix-milliseconds",
    )
    _require(
        current_ms - MAX_START_AGE_MS <= started_at_ms,
        "started-at-too-old",
    )
    _require(
        started_at_ms <= current_ms + MAX_FUTURE_SKEW_MS,
        "started-at-not-unix-milliseconds",
    )
    return started_at_ms


def _query_event(openclaw: Path, timeout_seconds: float) -> Any:
    try:
        result = subprocess.run(
            [str(openclaw), "system", "heartbeat", "last", "--json"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HeartbeatEventError("heartbeat-query-failed") from exc
    _require(result.returncode == 0, "heartbeat-query-nonzero")
    _require(len(result.stdout) <= MAX_OUTPUT_BYTES, "heartbeat-query-too-large")
    try:
        return json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HeartbeatEventError("heartbeat-query-invalid-json") from exc


def validate_event(event: Any, started_at_ms: int) -> dict[str, Any] | None:
    if event is None:
        return None
    _require(isinstance(event, dict), "heartbeat-event-invalid-shape")
    timestamp = event.get("ts")
    _require(isinstance(timestamp, int), "heartbeat-event-invalid-timestamp")
    if timestamp < started_at_ms:
        return None
    status = event.get("status")
    if status in WAIT_STATUSES:
        return None
    _require(status in SUCCESS_STATUSES, "heartbeat-event-unexpected-status")
    _require(event.get("reason") == "interval", "heartbeat-event-not-scheduled")
    _require(event.get("silent") is True, "heartbeat-event-not-silent")
    _require(
        not {"accountId", "channel", "to"}.intersection(event),
        "heartbeat-event-route-present",
    )
    duration = event.get("durationMs")
    _require(
        isinstance(duration, int) and not isinstance(duration, bool) and duration >= 0,
        "heartbeat-event-invalid-duration",
    )
    preview = event.get("preview")
    if status == "ok-empty":
        _require(preview is None, "heartbeat-empty-preview-present")
    elif isinstance(preview, str):
        lowered = preview.casefold()
        for term in FORBIDDEN_PREVIEW_TERMS:
            _require(term not in lowered, "heartbeat-event-forbidden-preview")
    return event


def summarize_event(event: Any) -> str:
    """Return only non-content event metadata suitable for failure output."""
    if event is None:
        return "null"
    if not isinstance(event, dict):
        return f"type={type(event).__name__}"
    return ",".join(
        (
            f"ts={event.get('ts')!r}",
            f"status={event.get('status')!r}",
            f"reason={event.get('reason')!r}",
        )
    )


def wait_for_event(
    openclaw: Path,
    started_at_ms: int,
    *,
    wait_seconds: float,
    poll_seconds: float,
    query_timeout_seconds: float,
    query: Callable[[Path, float], Any] = _query_event,
) -> dict[str, Any]:
    deadline = time.monotonic() + wait_seconds
    query_count = 0
    last_event: Any = None
    while True:
        last_event = query(openclaw, query_timeout_seconds)
        query_count += 1
        accepted = validate_event(last_event, started_at_ms)
        if accepted is not None:
            return accepted
        if time.monotonic() >= deadline:
            _fail(
                "heartbeat-event-timeout:"
                f"queries={query_count}:last={summarize_event(last_event)}"
            )
        time.sleep(poll_seconds)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openclaw", required=True, type=Path)
    parser.add_argument("--started-at-ms", required=True, type=int)
    parser.add_argument("--wait-seconds", type=float, default=720.0)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--query-timeout-seconds", type=float, default=30.0)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        validate_started_at_ms(args.started_at_ms)
        _require(args.wait_seconds > 0, "wait-seconds-invalid")
        _require(args.poll_seconds > 0, "poll-seconds-invalid")
        _require(args.query_timeout_seconds > 0, "query-timeout-invalid")
        event = wait_for_event(
            _executable(args.openclaw),
            args.started_at_ms,
            wait_seconds=args.wait_seconds,
            poll_seconds=args.poll_seconds,
            query_timeout_seconds=args.query_timeout_seconds,
        )
    except HeartbeatEventError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(event, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
