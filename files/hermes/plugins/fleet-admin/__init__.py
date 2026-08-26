"""Expose owner-only fleet administration to Astra."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import sqlite3
import stat
import time
from pathlib import Path
from typing import Any

from agent.secret_scope import get_secret

POLICY = Path("/etc/hermes/astra/fleet-admin-policy.json")
STATE_DB = Path("/var/lib/hermes/astra/.hermes/profiles/astra/state.db")
SOCKET = Path("/run/hermes-fleet-admin/broker.sock")
KEY_ENV = "GATEWAY_RELAY_FLEET_ADMIN_KEY"
MAX_REQUEST = 192 * 1024
MAX_RESPONSE = 320 * 1024
SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

OPERATIONS = ["inspect", "logs", "list", "read", "write", "delete", "validate", "restart"]
TARGETS = ["astra", "dubble", "rigel"]
ROOTS = ["workspace", "bootstrap", "skills", "schedules", "config"]

SCHEMA = {
    "name": "fleet_agent_admin",
    "description": (
        "Owner-only direct administration of Astra, Dubble, or Rigel. Inspect, list, or "
        "read a target workspace/runtime surface; back up and atomically write or "
        "quarantine a file; validate runtime; or perform one planned restart. "
        "Ordinary agent work does not use this tool. Secrets and raw memory/session "
        "databases are never exposed."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "target": {"type": "string", "enum": TARGETS},
            "operation": {"type": "string", "enum": OPERATIONS},
            "root": {"type": "string", "enum": ROOTS},
            "path": {"type": "string", "maxLength": 512},
            "content": {"type": "string", "maxLength": 131072},
            "expectedSha256": {
                "type": "string",
                "pattern": "^(?:absent|[a-f0-9]{64})$",
            },
        },
        "required": ["target", "operation"],
        "additionalProperties": False,
    },
}


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _error(code: str) -> str:
    return _json({"schemaVersion": 1, "status": "error", "code": code})


def _safe_regular(path: Path, *, owner_uid: int | None = None) -> os.stat_result:
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ValueError("unsafe-file")
    if owner_uid is not None and info.st_uid != owner_uid:
        raise ValueError("unsafe-owner")
    return info


def _load_policy() -> dict[str, Any]:
    info = _safe_regular(POLICY, owner_uid=0)
    if stat.S_IMODE(info.st_mode) not in {0o440, 0o444} or info.st_size > 16 * 1024:
        raise ValueError("unsafe-policy")
    value = json.loads(POLICY.read_text(encoding="utf-8"))
    expected = {
        "schemaVersion",
        "profile",
        "allowedSource",
        "allowedUserIds",
        "allowedGuildIds",
        "allowedChannelIds",
        "allowedTargets",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("schemaVersion") != 1
        or value.get("profile") != "astra"
        or value.get("allowedSource") != "discord"
        or value.get("allowedTargets") != TARGETS
    ):
        raise ValueError("invalid-policy")
    for key in ("allowedUserIds", "allowedGuildIds", "allowedChannelIds"):
        items = value.get(key)
        if (
            not isinstance(items, list)
            or not items
            or any(not isinstance(item, str) or not item.isdigit() for item in items)
        ):
            raise ValueError("invalid-policy")
    return value


def _authorize_session(session_id: Any, policy: dict[str, Any]) -> None:
    if not isinstance(session_id, str) or SESSION_RE.fullmatch(session_id) is None:
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


def _validate_args(args: Any) -> dict[str, Any]:
    if not isinstance(args, dict) or set(args) - {
        "target",
        "operation",
        "root",
        "path",
        "content",
        "expectedSha256",
    }:
        raise ValueError("invalid-request")
    target, operation = args.get("target"), args.get("operation")
    if target not in TARGETS or operation not in OPERATIONS:
        raise ValueError("invalid-request")
    file_operation = operation in {"list", "read", "write", "delete"}
    if file_operation:
        if args.get("root") not in ROOTS or not isinstance(args.get("path"), str):
            raise ValueError("invalid-request")
    elif any(name in args for name in ("root", "path", "content", "expectedSha256")):
        raise ValueError("invalid-request")
    if operation == "write":
        if not isinstance(args.get("content"), str):
            raise ValueError("invalid-request")
    elif "content" in args:
        raise ValueError("invalid-request")
    expected = args.get("expectedSha256")
    if operation in {"write", "delete"} and (
        not isinstance(expected, str)
        or re.fullmatch(r"(?:absent|[a-f0-9]{64})", expected) is None
    ):
        raise ValueError("invalid-request")
    if operation not in {"write", "delete"} and expected is not None:
        raise ValueError("invalid-request")
    return dict(args)


def _call_broker(request: dict[str, Any], session_id: str) -> str:
    key = (get_secret(KEY_ENV, "") or "").strip()
    if len(key) < 32 or len(key) > 256:
        return _error("fleet-key-unavailable")
    envelope = dict(request)
    envelope.update(
        {
            "schemaVersion": 1,
            "sessionId": session_id,
            "timestamp": int(time.time()),
            "nonce": secrets.token_hex(16),
        }
    )
    canonical = _json(envelope).encode("utf-8")
    envelope["signature"] = hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    payload = (_json(envelope) + "\n").encode("utf-8")
    if len(payload) > MAX_REQUEST:
        return _error("request-too-large")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(180)
            client.connect(str(SOCKET))
            client.sendall(payload)
            reader = client.makefile("rb")
            raw = reader.readline(MAX_RESPONSE + 1)
    except (OSError, TimeoutError):
        return _error("fleet-admin-unavailable")
    if not raw or len(raw) > MAX_RESPONSE or not raw.endswith(b"\n"):
        return _error("fleet-response-invalid")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error("fleet-response-invalid")
    if (
        not isinstance(value, dict)
        or value.get("schemaVersion") != 1
        or value.get("status") not in {"ok", "error"}
    ):
        return _error("fleet-response-invalid")
    return _json(value)


def _handler(args: dict[str, Any], *, session_id: str | None = None, **_: Any) -> str:
    try:
        request = _validate_args(args)
    except ValueError:
        return _error("invalid-request")
    try:
        policy = _load_policy()
        _authorize_session(session_id, policy)
    except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError):
        return _error("session-denied")
    return _call_broker(request, str(session_id))


def _check() -> bool:
    try:
        _load_policy()
        info = os.lstat(SOCKET)
        return (
            stat.S_ISSOCK(info.st_mode)
            and not stat.S_ISLNK(info.st_mode)
            and bool((get_secret(KEY_ENV, "") or "").strip())
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def register(ctx: Any) -> None:
    ctx.register_tool(
        name=SCHEMA["name"],
        toolset="fleet_admin",
        schema=SCHEMA,
        handler=_handler,
        check_fn=_check,
        is_async=False,
    )
