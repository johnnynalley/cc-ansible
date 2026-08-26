"""Expose a provenance-gated Rigel-to-Astra calendar liaison tool."""

from __future__ import annotations

import json
import os
import re
import socket
import sqlite3
import stat
from pathlib import Path
from typing import Any

POLICY = Path("/etc/hermes/rigel/astra-liaison-policy.json")
STATE_DB = Path("/var/lib/hermes/rigel/.hermes/profiles/rigel/state.db")
SOCKET = Path("/run/hermes-rigel-liaison/broker.sock")
MAX_REQUEST_BYTES = 128 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "eventId": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$"},
        "course": {"type": "string", "minLength": 1, "maxLength": 200},
        "event": {"type": "string", "minLength": 1, "maxLength": 300},
        "startsAt": {"type": "string", "minLength": 20, "maxLength": 64},
        "endsAt": {"type": "string", "minLength": 20, "maxLength": 64},
        "description": {"type": "string", "minLength": 1, "maxLength": 1000},
        "weight": {"type": "string", "minLength": 1, "maxLength": 80},
        "confirmed": {"type": "boolean"},
    },
    "required": ["eventId", "course", "event", "startsAt", "description", "weight"],
    "additionalProperties": False,
}

SCHEMA = {
    "name": "rigel_ask_astra",
    "description": (
        "Ask Astra's credential-isolated calendar broker to check one or more "
        "course events or add owner-confirmed events. The broker sees only the "
        "calendar, never Astra memory, sessions, mail, files, credentials, or "
        "administrator tools. calendar_add requires confirmed=true on every event."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["calendar_check", "calendar_add"]},
            "events": {"type": "array", "minItems": 1, "maxItems": 20, "items": EVENT_SCHEMA},
        },
        "required": ["operation", "events"],
        "additionalProperties": False,
    },
}


def _error(code: str) -> str:
    return json.dumps({"schemaVersion": 1, "status": "error", "code": code}, sort_keys=True, separators=(",", ":"))


def _safe_regular(path: Path, *, owner_uid: int | None = None) -> os.stat_result:
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ValueError("unsafe-file")
    if owner_uid is not None and info.st_uid != owner_uid:
        raise ValueError("unsafe-owner")
    return info


def _load_policy() -> dict[str, Any]:
    info = _safe_regular(POLICY, owner_uid=0)
    if stat.S_IMODE(info.st_mode) not in {0o440, 0o444} or info.st_size > 8192:
        raise ValueError("unsafe-policy")
    value = json.loads(POLICY.read_text(encoding="utf-8"))
    expected = {"schemaVersion", "profile", "allowedSource", "allowedUserIds", "allowedGuildIds", "allowedChannelIds"}
    if not isinstance(value, dict) or set(value) != expected or value.get("schemaVersion") != 1 or value.get("profile") != "rigel" or value.get("allowedSource") != "discord":
        raise ValueError("invalid-policy")
    for key in ("allowedUserIds", "allowedGuildIds", "allowedChannelIds"):
        values = value.get(key)
        if not isinstance(values, list) or not values or any(not isinstance(item, str) or not item.isdigit() for item in values):
            raise ValueError("invalid-policy")
    return value


def _authorize_session(session_id: Any, policy: dict[str, Any]) -> None:
    if not isinstance(session_id, str) or SESSION_ID_RE.fullmatch(session_id) is None:
        raise ValueError("session-unavailable")
    info = _safe_regular(STATE_DB, owner_uid=os.getuid())
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise ValueError("unsafe-state-db")
    database = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True, timeout=2)
    try:
        row = database.execute(
            "SELECT source,user_id,chat_id,chat_type,origin_json FROM sessions WHERE id=? LIMIT 1",
            (session_id,),
        ).fetchone()
    finally:
        database.close()
    if row is None:
        raise ValueError("session-unavailable")
    source, user_id, chat_id, chat_type, origin_json = row
    try:
        origin = json.loads(origin_json or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("session-origin-invalid") from exc
    if (
        source != policy["allowedSource"]
        or user_id not in policy["allowedUserIds"]
        or chat_id not in policy["allowedChannelIds"]
        or chat_type not in {"group", "channel"}
        or not isinstance(origin, dict)
        or origin.get("platform") != source
        or origin.get("user_id") != user_id
        or origin.get("chat_id") != chat_id
        or origin.get("guild_id") not in policy["allowedGuildIds"]
    ):
        raise ValueError("session-denied")


def _call_broker(value: dict[str, Any]) -> str:
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(payload) > MAX_REQUEST_BYTES:
        return _error("request-too-large")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(210)
            client.connect(str(SOCKET))
            client.sendall(payload)
            reader = client.makefile("rb")
            raw = reader.readline(MAX_RESPONSE_BYTES + 1)
    except (OSError, TimeoutError):
        return _error("liaison-unavailable")
    if not raw or len(raw) > MAX_RESPONSE_BYTES or not raw.endswith(b"\n"):
        return _error("liaison-response-invalid")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error("liaison-response-invalid")
    if not isinstance(value, dict) or value.get("schemaVersion") != 1 or value.get("status") not in {"ok", "pending", "error"}:
        return _error("liaison-response-invalid")
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _handler(args: dict[str, Any], *, session_id: str | None = None, **_: Any) -> str:
    if not isinstance(args, dict) or set(args) != {"operation", "events"}:
        return _error("invalid-request")
    operation = args.get("operation")
    events = args.get("events")
    if operation not in {"calendar_check", "calendar_add"} or not isinstance(events, list):
        return _error("invalid-request")
    try:
        policy = _load_policy()
        _authorize_session(session_id, policy)
    except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError):
        return _error("session-denied")
    return _call_broker({"schemaVersion": 1, "operation": operation, "sessionId": session_id, "events": events})


def _check() -> bool:
    try:
        _load_policy()
        info = os.lstat(SOCKET)
        return stat.S_ISSOCK(info.st_mode) and not stat.S_ISLNK(info.st_mode)
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def register(ctx: Any) -> None:
    ctx.register_tool(
        name=SCHEMA["name"],
        toolset="rigel_astra_liaison",
        schema=SCHEMA,
        handler=_handler,
        check_fn=_check,
        is_async=False,
    )
