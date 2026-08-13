#!/usr/bin/env python3
"""Plan a fail-closed native OpenClaw session modernization transition."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

TERMINAL_EXECUTION_STATUSES = {
    "cancelled",
    "completed",
    "done",
    "failed",
    "killed",
    "succeeded",
    "timeout",
    "timed_out",
}
ACTIVE_EXECUTION_STATUSES = {
    "active",
    "pending",
    "queued",
    "running",
    "starting",
}


class SessionTransitionError(RuntimeError):
    """Raised when a session row cannot be modernized safely."""


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SessionTransitionError("session-list input is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise SessionTransitionError("session-list input must be a JSON object")
    return payload


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise SessionTransitionError(
            "session transition plan could not be replaced atomically"
        ) from exc


def _parse_agent_key(key: str, expected_agents: set[str]) -> tuple[str, list[str]]:
    parts = key.split(":")
    if len(parts) < 3 or parts[0] != "agent" or not parts[1] or not parts[2]:
        raise SessionTransitionError("session row has an unsupported key schema")
    agent_id = parts[1]
    if agent_id not in expected_agents:
        raise SessionTransitionError("session row belongs to an unexpected agent")
    return agent_id, parts[2:]


def _row_is_active(row: dict[str, Any]) -> bool:
    status = row.get("status")
    return (
        row.get("hasActiveRun") is True
        or row.get("hasActiveSubagentRun") is True
        or row.get("subagentRunState") == "active"
        or (isinstance(status, str) and status.lower() in ACTIVE_EXECUTION_STATUSES)
    )


def _classify_row(
    row: dict[str, Any], expected_agents: set[str]
) -> tuple[str, str, str]:
    key = row.get("key")
    if not isinstance(key, str) or not key:
        raise SessionTransitionError("session row has no valid key")
    agent_id, rest = _parse_agent_key(key, expected_agents)
    if row.get("archived") is True or row.get("archivedAt") is not None:
        raise SessionTransitionError("active session list contains an archived row")
    if _row_is_active(row):
        raise SessionTransitionError("session transition found active work")

    if rest == ["main"]:
        return "retain", "durable-main", agent_id
    if rest == ["main", "heartbeat"]:
        return "retain", "durable-native-heartbeat", agent_id
    if "heartbeat" in rest:
        return "archive", "synthetic-heartbeat", agent_id
    if rest[0] == "cron" or "cron" in rest:
        return "archive", "synthetic-cron", agent_id
    if (
        rest[0] == "subagent"
        or row.get("spawnedBy")
        or row.get("spawnDepth") is not None
    ):
        return "archive", "completed-subagent", agent_id
    if rest[0] == "explicit" and any(
        component.startswith("model-run-") for component in rest[1:]
    ):
        return "archive", "synthetic-model-probe", agent_id
    if rest[0] == "explicit" and any(
        component.startswith("behavior-") for component in rest[1:]
    ):
        return "archive", "synthetic-behavior-probe", agent_id
    if rest[0] == "explicit" and any(
        component.startswith("security-") for component in rest[1:]
    ):
        return "archive", "synthetic-security-probe", agent_id

    has_durable_route = (
        row.get("channel") is not None
        or row.get("origin") is not None
        or row.get("deliveryContext") is not None
        or "channel" in rest
        or "group" in rest
        or "thread" in rest
        or "direct" in rest
    )
    if has_durable_route:
        return "retain", "durable-conversation-route", agent_id

    status = row.get("status")
    if (
        isinstance(status, str)
        and status.lower() in TERMINAL_EXECUTION_STATUSES
        and isinstance(row.get("endedAt"), (int, float))
    ):
        return "archive", "completed-execution", agent_id
    if (
        status is None
        and row.get("endedAt") is None
        and isinstance(row.get("sessionId"), str)
        and row["sessionId"]
    ):
        return "retain", "durable-runtime-session", agent_id

    raise SessionTransitionError("session row has an unclassified runtime shape")


def build_transition_plan(
    payload: dict[str, Any], expected_agents: list[str], require_clean: bool = False
) -> dict[str, Any]:
    if not expected_agents or len(expected_agents) != len(set(expected_agents)):
        raise SessionTransitionError("expected agent set is empty or duplicated")
    expected_agent_set = set(expected_agents)
    sessions = payload.get("sessions")
    if not isinstance(sessions, list):
        raise SessionTransitionError("sessions.list response has no sessions array")
    if payload.get("hasMore") is not False:
        raise SessionTransitionError("sessions.list response is incomplete")
    total_count = payload.get("totalCount")
    if not isinstance(total_count, int) or total_count != len(sessions):
        raise SessionTransitionError("sessions.list total does not match returned rows")

    actions: list[dict[str, str]] = []
    classifications: Counter[str] = Counter()
    seen_keys: set[str] = set()
    for index, row in enumerate(sessions):
        if not isinstance(row, dict):
            raise SessionTransitionError(f"session row {index} is not an object")
        key = row.get("key")
        if isinstance(key, str) and key in seen_keys:
            raise SessionTransitionError(
                "sessions.list response contains duplicate keys"
            )
        if isinstance(key, str):
            seen_keys.add(key)
        try:
            action, reason, agent_id = _classify_row(row, expected_agent_set)
        except SessionTransitionError as exc:
            raise SessionTransitionError(
                f"session row {index} cannot be transitioned: {exc}"
            ) from exc
        classifications[f"{action}:{reason}"] += 1
        actions.append(
            {
                "action": action,
                "reason": reason,
                "agentId": agent_id,
                "key": str(key),
            }
        )

    archive_count = sum(1 for action in actions if action["action"] == "archive")
    if require_clean and archive_count:
        raise SessionTransitionError(
            "active session list still contains rows scheduled for archive"
        )
    return {
        "schemaVersion": 1,
        "mode": "native-session-transition",
        "source": {
            "totalCount": total_count,
            "hasMore": False,
        },
        "summary": {
            "retain": len(actions) - archive_count,
            "archive": archive_count,
            "classifications": dict(sorted(classifications.items())),
        },
        "actions": actions,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--agent", action="append", dest="agents", required=True)
    parser.add_argument("--require-clean", action="store_true")
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        plan = build_transition_plan(
            _read_json_object(arguments.input),
            arguments.agents,
            require_clean=arguments.require_clean,
        )
        _write_json_atomic(arguments.output, plan)
    except SessionTransitionError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        return 1
    print(
        json.dumps(
            {"status": "ok", "summary": plan["summary"]},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
