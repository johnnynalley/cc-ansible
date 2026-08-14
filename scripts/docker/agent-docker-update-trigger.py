#!/usr/bin/env python3
"""Trigger the existing Ansible-managed Docker updater through a fixed API."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MAX_REQUEST_BYTES = 256
SERVICE_UNIT = "docker-auto-update.service"
TIMER_UNIT = "docker-auto-update.timer"
SYSTEMCTL = "/usr/bin/systemctl"
HOST_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
ALLOWED_ACTIONS = {"run", "status"}
ALLOWED_STATES = {
    "active",
    "activating",
    "deactivating",
    "failed",
    "inactive",
    "unknown",
}
ALLOWED_RESULTS = {
    "core-dump",
    "exit-code",
    "resources",
    "signal",
    "success",
    "timeout",
    "unknown",
}


class RequestError(RuntimeError):
    """Expected fixed-code request failure."""


def _response(host: str, action: str, outcome: str, **extra: Any) -> str:
    value = {
        "schemaVersion": SCHEMA_VERSION,
        "host": host,
        "status": "ok",
        "action": action,
        "outcome": outcome,
        **extra,
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _error(code: str) -> str:
    return json.dumps(
        {"schemaVersion": SCHEMA_VERSION, "status": "error", "code": code},
        sort_keys=True,
        separators=(",", ":"),
    )


def _read_request(stream: Any) -> str:
    raw = stream.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        raise RequestError("invalid-request")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RequestError("invalid-request") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"schemaVersion", "action"}
        or value.get("schemaVersion") != SCHEMA_VERSION
        or value.get("action") not in ALLOWED_ACTIONS
    ):
        raise RequestError("invalid-request")
    return value["action"]


def _systemctl_value(unit: str, property_name: str) -> str:
    try:
        result = subprocess.run(
            [SYSTEMCTL, "show", unit, f"--property={property_name}", "--value"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
            text=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0 or len(result.stdout) > 128:
        return ""
    return result.stdout.strip()


def _unit_state() -> dict[str, Any]:
    load_state = _systemctl_value(SERVICE_UNIT, "LoadState")
    service_state = _systemctl_value(SERVICE_UNIT, "ActiveState")
    timer_state = _systemctl_value(TIMER_UNIT, "ActiveState")
    last_result = _systemctl_value(SERVICE_UNIT, "Result")
    raw_exit_code = _systemctl_value(SERVICE_UNIT, "ExecMainStatus")
    if service_state not in ALLOWED_STATES:
        service_state = "unknown"
    if timer_state not in ALLOWED_STATES:
        timer_state = "unknown"
    if last_result not in ALLOWED_RESULTS:
        last_result = "unknown"
    try:
        exit_code = int(raw_exit_code)
    except ValueError:
        exit_code = -1
    return {
        "managed": load_state == "loaded" and timer_state == "active",
        "serviceState": service_state,
        "timerState": timer_state,
        "lastResult": last_result,
        "exitCode": exit_code,
    }


def _status(host: str) -> str:
    state = _unit_state()
    outcome = "ready" if state["managed"] else "unavailable"
    return _response(host, "status", outcome, **state)


def _read_last_trigger(path: Path) -> int:
    try:
        value = path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return 0
    if not value.isdigit():
        raise RequestError("invalid-state")
    return int(value)


def _write_last_trigger(path: Path, timestamp: int) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    try:
        os.write(descriptor, f"{timestamp}\n".encode("ascii"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def _run(host: str, state_dir: Path, cooldown: int) -> str:
    state = _unit_state()
    if not state["managed"]:
        return _response(host, "run", "unavailable", **state)
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = state_dir / "trigger.lock"
    with lock_path.open("a+", encoding="ascii") as lock:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        now = int(time.time())
        last_trigger = _read_last_trigger(state_dir / "last-trigger")
        remaining = max(0, cooldown - (now - last_trigger))
        if remaining:
            return _response(
                host,
                "run",
                "cooldown",
                retryAfterSeconds=remaining,
                **state,
            )
        if state["serviceState"] in {"active", "activating"}:
            return _response(host, "run", "already-running", **state)
        try:
            result = subprocess.run(
                [SYSTEMCTL, "start", "--no-block", SERVICE_UNIT],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return _response(host, "run", "start-failed", **state)
        if result.returncode != 0:
            return _response(host, "run", "start-failed", **state)
        _write_last_trigger(state_dir / "last-trigger", now)
        state["serviceState"] = "activating"
        return _response(host, "run", "accepted", **state)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    request = subparsers.add_parser("request")
    request.add_argument("--host", required=True)
    request.add_argument("--state-dir", type=Path, required=True)
    request.add_argument("--cooldown", type=int, default=3600)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if (
        os.geteuid() != 0
        or args.command != "request"
        or HOST_PATTERN.fullmatch(args.host) is None
        or not args.state_dir.is_absolute()
        or args.cooldown < 300
        or args.cooldown > 86400
    ):
        print(_error("invalid-runtime"))
        return 1
    try:
        action = _read_request(sys.stdin)
        output = (
            _status(args.host)
            if action == "status"
            else _run(args.host, args.state_dir, args.cooldown)
        )
    except RequestError as exc:
        output = _error(str(exc))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
