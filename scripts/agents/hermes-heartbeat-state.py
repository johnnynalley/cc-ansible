#!/usr/bin/env python3
"""Emit content-free Hermes session, delivery, and model-route health."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
METERED_PROVIDERS = {"gemini", "google", "openai", "openrouter"}
SUBSCRIPTION_PROVIDERS = {"ollama-cloud", "openai-codex"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect Hermes heartbeat state without exposing message content."
    )
    parser.add_argument(
        "--profile-home",
        type=Path,
        default=Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")),
    )
    parser.add_argument("--window-hours", type=float, default=6.0)
    parser.add_argument("--stalled-after-seconds", type=float, default=900.0)
    parser.add_argument("--now", type=float, default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--maintenance-lease",
        choices=("acquire", "release"),
        default=None,
    )
    parser.add_argument(
        "--lease-owner",
        choices=("heartbeat", "self-evolution"),
        default=None,
    )
    parser.add_argument("--lease-seconds", type=int, default=3600)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_timestamp(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def age_seconds(value: Any, now: float) -> float | None:
    timestamp = parse_timestamp(value)
    if timestamp is None:
        return None
    return max(0.0, now - timestamp)


def readonly_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _write_private_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            os.chmod(temporary, 0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def maintenance_lease(
    profile_home: Path,
    *,
    action: str,
    owner: str,
    now: float,
    lease_seconds: int,
) -> tuple[int, dict[str, Any]]:
    if owner not in {"heartbeat", "self-evolution"} or not 300 <= lease_seconds <= 7200:
        return 2, {"schemaVersion": 1, "status": "error", "code": "invalid-lease"}
    state = profile_home.resolve() / "state" / "maintenance"
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = state / "semantic-lease.json"
    lock_path = state / "semantic-lease.lock"
    with lock_path.open("a+", encoding="ascii") as lock:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        current: dict[str, Any] | None = None
        if path.exists():
            try:
                raw = load_json(path)
            except (OSError, UnicodeError, json.JSONDecodeError):
                return 2, {
                    "schemaVersion": 1,
                    "status": "error",
                    "code": "lease-state-invalid",
                }
            if not isinstance(raw, dict):
                return 2, {
                    "schemaVersion": 1,
                    "status": "error",
                    "code": "lease-state-invalid",
                }
            current = raw
            try:
                current_expires_at = float(current["expiresAt"])
            except (KeyError, TypeError, ValueError):
                return 2, {
                    "schemaVersion": 1,
                    "status": "error",
                    "code": "lease-state-invalid",
                }
            if (
                current.get("schemaVersion") != 1
                or current.get("owner") not in {"heartbeat", "self-evolution"}
                or current_expires_at < 0
            ):
                return 2, {
                    "schemaVersion": 1,
                    "status": "error",
                    "code": "lease-state-invalid",
                }

        if action == "acquire":
            expires_at = current_expires_at if current else 0
            if current and expires_at > now:
                return 3, {
                    "schemaVersion": 1,
                    "status": "busy",
                    "owner": current.get("owner"),
                    "expiresInSeconds": max(0, int(expires_at - now)),
                }
            lease = {
                "schemaVersion": 1,
                "owner": owner,
                "acquiredAt": now,
                "expiresAt": now + lease_seconds,
            }
            _write_private_json(path, lease)
            return 0, {
                "schemaVersion": 1,
                "status": "acquired",
                "owner": owner,
                "expiresInSeconds": lease_seconds,
            }

        if action != "release":
            return 2, {"schemaVersion": 1, "status": "error", "code": "invalid-lease"}
        if current and current.get("owner") != owner and current_expires_at > now:
            return 3, {
                "schemaVersion": 1,
                "status": "busy",
                "owner": current.get("owner"),
                "expiresInSeconds": max(0, int(current_expires_at - now)),
            }
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return 0, {"schemaVersion": 1, "status": "released", "owner": owner}


def latest_message_metadata(
    connection: sqlite3.Connection, session_id: str
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT role, content, tool_calls, reasoning, reasoning_content,
               finish_reason, timestamp
          FROM messages
         WHERE session_id = ? AND active = 1
           AND role IN ('user', 'assistant')
         ORDER BY id DESC
         LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    if row is None:
        return None

    content_present = bool(str(row["content"] or "").strip())
    tools_present = bool(str(row["tool_calls"] or "").strip())
    reasoning_present = bool(
        str(row["reasoning"] or "").strip()
        or str(row["reasoning_content"] or "").strip()
    )
    return {
        "role": row["role"],
        "contentPresent": content_present,
        "toolCallsPresent": tools_present,
        "reasoningPresent": reasoning_present,
        "finishReason": row["finish_reason"],
        "timestamp": row["timestamp"],
        "empty": not (content_present or tools_present or reasoning_present),
    }


def session_health(
    connection: sqlite3.Connection,
    session_index: dict[str, Any],
    now: float,
    window_seconds: float,
    stalled_after_seconds: float,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, session_key, source, last_activity_at, ended_at, model,
               billing_provider, billing_mode
          FROM sessions
         WHERE source = 'discord' AND last_activity_at >= ?
         ORDER BY last_activity_at DESC
        """,
        (now - window_seconds,),
    ).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        session_key = row["session_key"] or ""
        route = session_index.get(session_key)
        if not isinstance(route, dict):
            route = {}
        latest = latest_message_metadata(connection, row["id"])
        active_age = age_seconds(route.get("active_turn_started_at"), now)
        active_turn = bool(route.get("active_turn_token"))
        latest_role = latest.get("role") if latest else None
        latest_empty = bool(latest and latest["empty"])
        unfinished_tool_turn = bool(
            latest
            and latest_role == "assistant"
            and latest["toolCallsPresent"]
            and not active_turn
        )
        unanswered_user = bool(
            latest and latest_role == "user" and not active_turn
        )
        results.append(
            {
                "sessionId": row["id"],
                "sessionKey": session_key,
                "lastActivityAgeSeconds": age_seconds(row["last_activity_at"], now),
                "activeTurn": active_turn,
                "activeTurnAgeSeconds": active_age,
                "stalledActiveTurn": bool(
                    active_turn
                    and active_age is not None
                    and active_age >= stalled_after_seconds
                ),
                "resumePending": bool(route.get("resume_pending")),
                "suspended": bool(route.get("suspended")),
                "latestRole": latest_role,
                "latestMessageAgeSeconds": (
                    age_seconds(latest.get("timestamp"), now) if latest else None
                ),
                "latestAssistantEmpty": bool(
                    latest_role == "assistant" and latest_empty
                ),
                "unfinishedToolTurn": unfinished_tool_turn,
                "unansweredUserTurn": unanswered_user,
                "model": row["model"],
                "billingProvider": row["billing_provider"],
                "billingMode": row["billing_mode"],
            }
        )
    return results


def delivery_health(
    connection: sqlite3.Connection, now: float
) -> dict[str, Any]:
    counts = {
        row["state"]: row["count"]
        for row in connection.execute(
            "SELECT state, COUNT(*) AS count FROM delivery_obligations GROUP BY state"
        )
    }
    unresolved = []
    for row in connection.execute(
        """
        SELECT obligation_id, session_key, platform, state, attempts,
               created_at, updated_at, owner_pid, last_error
          FROM delivery_obligations
         WHERE state IN ('pending', 'attempting', 'failed', 'abandoned')
         ORDER BY updated_at DESC
         LIMIT 50
        """
    ):
        unresolved.append(
            {
                "id": row["obligation_id"],
                "sessionKey": row["session_key"],
                "platform": row["platform"],
                "state": row["state"],
                "attempts": row["attempts"],
                "createdAgeSeconds": age_seconds(row["created_at"], now),
                "updatedAgeSeconds": age_seconds(row["updated_at"], now),
                "ownerPid": row["owner_pid"],
                "lastErrorClass": (
                    str(row["last_error"] or "").split(":", 1)[0][:120] or None
                ),
            }
        )
    return {"counts": counts, "unresolved": unresolved}


def model_usage(
    connection: sqlite3.Connection, now: float, window_seconds: float
) -> dict[str, Any]:
    recent = []
    unexpected = []
    unknown = []
    for row in connection.execute(
        """
        SELECT model, billing_provider, billing_mode, SUM(api_call_count) AS calls,
               MAX(last_seen) AS last_seen
          FROM session_model_usage
         WHERE last_seen >= ?
         GROUP BY model, billing_provider, billing_mode
         ORDER BY last_seen DESC
        """,
        (now - window_seconds,),
    ):
        item = {
            "model": row["model"],
            "billingProvider": row["billing_provider"],
            "billingMode": row["billing_mode"],
            "apiCalls": row["calls"],
            "lastSeenAgeSeconds": age_seconds(row["last_seen"], now),
        }
        recent.append(item)
        provider = str(row["billing_provider"] or "").lower()
        mode = str(row["billing_mode"] or "").lower()
        if not provider and not mode:
            unknown.append(item)
        elif provider in METERED_PROVIDERS and mode != "subscription_included":
            unexpected.append(item)
        elif provider not in SUBSCRIPTION_PROVIDERS and mode not in {
            "local",
            "subscription_included",
        }:
            unexpected.append(item)
    return {
        "recent": recent,
        "unexpectedMeteredRoutes": unexpected,
        "unknownProvenanceRoutes": unknown,
    }


def model_overrides(session_index: dict[str, Any]) -> list[dict[str, Any]]:
    overrides = []
    for key, value in session_index.items():
        if key == "_README" or not isinstance(value, dict):
            continue
        override = value.get("model_override")
        if not isinstance(override, dict) or not override:
            continue
        overrides.append(
            {
                "sessionKey": key,
                "model": override.get("model"),
                "provider": override.get("provider"),
                "baseUrlPresent": bool(override.get("base_url")),
            }
        )
    return overrides


def inspect(args: argparse.Namespace) -> dict[str, Any]:
    now = args.now if args.now is not None else time.time()
    profile_home = args.profile_home.resolve()
    errors: list[str] = []
    session_index: dict[str, Any] = {}

    try:
        raw_index = load_json(profile_home / "sessions" / "sessions.json")
        if isinstance(raw_index, dict):
            session_index = raw_index
        else:
            errors.append("sessions-index-invalid-shape")
    except FileNotFoundError:
        errors.append("sessions-index-missing")
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"sessions-index-unreadable:{type(exc).__name__}")

    result: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "checkedAt": datetime.fromtimestamp(now).astimezone().isoformat(),
        "profileHome": str(profile_home),
        "errors": errors,
        "modelOverrides": model_overrides(session_index),
        "discordSessions": [],
        "delivery": {"counts": {}, "unresolved": []},
        "models": {
            "recent": [],
            "unexpectedMeteredRoutes": [],
            "unknownProvenanceRoutes": [],
        },
    }

    database = profile_home / "state.db"
    try:
        with closing(readonly_connection(database)) as connection:
            window_seconds = args.window_hours * 3600
            result["discordSessions"] = session_health(
                connection,
                session_index,
                now,
                window_seconds,
                args.stalled_after_seconds,
            )
            result["delivery"] = delivery_health(connection, now)
            result["models"] = model_usage(connection, now, window_seconds)
    except (OSError, sqlite3.Error) as exc:
        errors.append(f"state-db-unreadable:{type(exc).__name__}")
    return result


def main() -> int:
    args = parse_args()
    if args.maintenance_lease is not None:
        if args.lease_owner is None:
            print(
                json.dumps(
                    {"schemaVersion": 1, "status": "error", "code": "invalid-lease"},
                    sort_keys=True,
                )
            )
            return 2
        code, result = maintenance_lease(
            args.profile_home,
            action=args.maintenance_lease,
            owner=args.lease_owner,
            now=args.now if args.now is not None else time.time(),
            lease_seconds=args.lease_seconds,
        )
        print(json.dumps(result, sort_keys=True))
        return code
    result = inspect(args)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not result["errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
