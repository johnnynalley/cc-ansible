"""Restore reviewed OpenClaw Discord actions through a narrow REST tool."""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from agent.secret_scope import get_secret


API = "https://discord.com/api/v10"
POLICY = Path(
    os.environ.get("HERMES_MANAGED_DIR", "/etc/hermes/astra")
) / "discord-parity-policy.json"
MAX_RESPONSE = 4 * 1024 * 1024
MAX_FILE = 10 * 1024 * 1024
SNOWFLAKE = "^[0-9]{17,20}$"

READ_ACTIONS = {
    "search_messages",
    "list_reactions",
    "list_threads",
    "thread_messages",
    "channel_permissions",
    "emoji_list",
    "role_info",
    "voice_status",
    "event_list",
}
CHANNEL_ACTIONS = {
    "send_message",
    "edit_message",
    "add_reaction",
    "remove_reaction",
    "list_reactions",
    "create_poll",
    "search_messages",
    "list_threads",
    "thread_reply",
    "thread_messages",
    "channel_permissions",
    "send_sticker",
    "thread_edit",
}
GUILD_ACTIONS = {
    "search_messages",
    "list_threads",
    "channel_permissions",
    "emoji_list",
    "role_info",
    "voice_status",
    "event_list",
    "event_create",
    "channel_create",
    "category_create",
    "channel_edit",
    "category_edit",
    "channel_delete",
    "category_delete",
    "channel_move",
}


SCHEMA = {
    "name": "discord_parity",
    "description": (
        "Use the profile's reviewed Discord actions that are absent from Hermes' "
        "built-in Discord tools. The tool is restricted to the managed ARK "
        "guild and approved channels. It cannot change roles, moderate users, "
        "or set presence. Prefer built-in discord/discord_admin actions when "
        "they already cover the operation."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "send_message", "edit_message", "add_reaction",
                    "remove_reaction", "list_reactions", "create_poll",
                    "search_messages", "list_threads", "thread_messages", "thread_reply",
                    "channel_permissions", "emoji_list", "send_sticker",
                    "role_info", "voice_status", "event_list", "event_create",
                    "channel_create", "category_create", "channel_edit",
                    "category_edit", "channel_delete", "category_delete",
                    "channel_move", "thread_edit"
                ],
            },
            "guild_id": {"type": "string", "pattern": SNOWFLAKE},
            "channel_id": {"type": "string", "pattern": SNOWFLAKE},
            "channel_ids": {
                "type": "array", "items": {"type": "string", "pattern": SNOWFLAKE},
                "maxItems": 25,
            },
            "message_id": {"type": "string", "pattern": SNOWFLAKE},
            "user_id": {"type": "string", "pattern": SNOWFLAKE},
            "role_id": {"type": "string", "pattern": SNOWFLAKE},
            "sticker_id": {"type": "string", "pattern": SNOWFLAKE},
            "content": {"type": "string", "maxLength": 2000},
            "file_path": {"type": "string", "maxLength": 4096},
            "components": {"type": "array", "items": {"type": "object"}, "maxItems": 10},
            "silent": {"type": "boolean"},
            "emoji": {"type": "string", "maxLength": 100},
            "query": {"type": "string", "maxLength": 256},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            "poll_question": {"type": "string", "maxLength": 300},
            "poll_options": {
                "type": "array", "items": {"type": "string", "maxLength": 55},
                "minItems": 2, "maxItems": 10,
            },
            "poll_duration_hours": {"type": "integer", "minimum": 1, "maximum": 768},
            "poll_multiselect": {"type": "boolean"},
            "name": {"type": "string", "maxLength": 100},
            "topic": {"type": "string", "maxLength": 1024},
            "parent_id": {"type": "string", "pattern": SNOWFLAKE},
            "position": {"type": "integer", "minimum": 0, "maximum": 999},
            "nsfw": {"type": "boolean"},
            "start_time": {"type": "string", "maxLength": 64},
            "end_time": {"type": "string", "maxLength": 64},
            "description": {"type": "string", "maxLength": 1000},
            "location": {"type": "string", "maxLength": 100},
            "archived": {"type": "boolean"},
            "locked": {"type": "boolean"},
            "invitable": {"type": "boolean"},
            "auto_archive_duration": {
                "type": "integer", "enum": [60, 1440, 4320, 10080]
            },
            "rate_limit_per_user": {
                "type": "integer", "minimum": 0, "maximum": 21600
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    },
}


class ParityError(RuntimeError):
    """Expected fixed-code boundary error."""


def _error(code: str) -> str:
    return json.dumps({"schemaVersion": 1, "status": "error", "code": code})


def _policy() -> dict[str, Any]:
    try:
        value = json.loads(POLICY.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ParityError("policy-unavailable") from exc
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise ParityError("policy-invalid")
    return value


def _token() -> str:
    token = (get_secret("DISCORD_BOT_TOKEN", "") or "").strip()
    if not token:
        raise ParityError("token-unavailable")
    return token


def _read_body(source: Any, limit: int = MAX_RESPONSE) -> bytes:
    body = source.read(limit + 1)
    if len(body) > limit:
        raise ParityError("response-too-large")
    return body


def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    raw: bytes | None = None,
    content_type: str = "application/json",
) -> Any:
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    data = raw if raw is not None else (
        json.dumps(body, separators=(",", ":")).encode("utf-8")
        if body is not None else None
    )
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bot {_token()}",
            "Content-Type": content_type,
            "User-Agent": "Hermes-Astra-Discord-Parity/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status == 204:
                return None
            payload = _read_body(response)
            return json.loads(payload.decode("utf-8")) if payload else None
    except urllib.error.HTTPError as exc:
        try:
            detail = _read_body(exc, 64 * 1024).decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        raise ParityError(f"discord-http-{exc.code}:{detail[:240]}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ParityError("discord-request-failed") from exc


def _allowed(args: dict[str, Any], action: str) -> dict[str, Any]:
    policy = _policy()
    guilds = set(policy.get("guilds", []))
    channels = set(policy.get("channels", []))
    guild_id = args.get("guild_id")
    channel_id = args.get("channel_id")
    channel_ids = args.get("channel_ids", [])
    if action in GUILD_ACTIONS and guild_id not in guilds:
        raise ParityError("guild-not-allowed")
    if (
        action in CHANNEL_ACTIONS
        and channel_id is not None
        and channel_id not in channels
        and action not in {"thread_edit", "thread_reply", "thread_messages"}
    ):
        raise ParityError("channel-not-allowed")
    if action == "search_messages":
        if not isinstance(channel_ids, list) or not channel_ids:
            raise ParityError("channel-ids-required")
        if any(item not in channels for item in channel_ids):
            raise ParityError("channel-not-allowed")
    if action == "list_threads" and args.get("parent_id") not in channels:
        raise ParityError("channel-not-allowed")
    return policy


def _require(args: dict[str, Any], action: str, *names: str) -> None:
    for name in names:
        value = args.get(name)
        if value is None or value == "" or value == []:
            raise ParityError(f"{action}-{name}-required")


def _validate_args(args: dict[str, Any], action: str) -> None:
    requirements = {
        "send_message": ("channel_id",),
        "thread_reply": ("channel_id",),
        "edit_message": ("channel_id", "message_id"),
        "add_reaction": ("channel_id", "message_id", "emoji"),
        "remove_reaction": ("channel_id", "message_id", "emoji"),
        "list_reactions": ("channel_id", "message_id", "emoji"),
        "create_poll": ("channel_id", "poll_question", "poll_options"),
        "search_messages": ("guild_id", "channel_ids", "query"),
        "list_threads": ("guild_id", "parent_id"),
        "thread_messages": ("guild_id", "channel_id"),
        "channel_permissions": ("guild_id", "channel_id"),
        "emoji_list": ("guild_id",),
        "send_sticker": ("channel_id", "sticker_id"),
        "role_info": ("guild_id", "role_id"),
        "voice_status": ("guild_id", "user_id"),
        "event_list": ("guild_id",),
        "event_create": ("guild_id", "name", "start_time"),
        "channel_create": ("guild_id", "name"),
        "category_create": ("guild_id", "name"),
        "channel_edit": ("guild_id", "channel_id"),
        "category_edit": ("guild_id", "channel_id"),
        "channel_delete": ("guild_id", "channel_id"),
        "category_delete": ("guild_id", "channel_id"),
        "channel_move": ("guild_id", "channel_id", "position"),
        "thread_edit": ("guild_id", "channel_id"),
    }
    _require(args, action, *requirements[action])
    if action == "event_create":
        if args.get("location"):
            _require(args, action, "end_time")
        else:
            _require(args, action, "channel_id")
    if action in {"channel_edit", "category_edit"} and not any(
        name in args for name in ("name", "topic", "parent_id", "position", "nsfw")
    ):
        raise ParityError(f"{action}-changes-required")
    if action == "thread_edit" and not any(
        name in args
        for name in (
            "name", "archived", "locked", "invitable",
            "auto_archive_duration", "rate_limit_per_user",
        )
    ):
        raise ParityError("thread_edit-changes-required")


def _channel_info(channel_id: str) -> dict[str, Any]:
    value = _request("GET", f"/channels/{channel_id}")
    if not isinstance(value, dict):
        raise ParityError("channel-lookup-invalid")
    return value


def _verify_channel_guild(channel_id: str, guild_id: str) -> dict[str, Any]:
    value = _channel_info(channel_id)
    if value.get("guild_id") != guild_id:
        raise ParityError("channel-guild-mismatch")
    return value


def _verify_thread_scope(
    channel_id: str, guild_id: str, policy: dict[str, Any]
) -> dict[str, Any]:
    value = _verify_channel_guild(channel_id, guild_id)
    channels = set(policy.get("channels", []))
    if channel_id not in channels and value.get("parent_id") not in channels:
        raise ParityError("thread-parent-not-allowed")
    return value


def _safe_file(raw_path: Any, policy: dict[str, Any]) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise ParityError("file-path-required")
    path = Path(raw_path)
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ParityError("file-unavailable") from exc
    if path.is_symlink() or not path.is_file() or info.st_size > MAX_FILE:
        raise ParityError("file-not-allowed")
    roots = [Path(item).resolve(strict=True) for item in policy.get("fileRoots", [])]
    if not any(resolved == root or root in resolved.parents for root in roots):
        raise ParityError("file-not-allowed")
    return resolved


def _multipart(payload: dict[str, Any], path: Path) -> tuple[bytes, str]:
    boundary = f"hermes-{secrets.token_hex(16)}"
    filename = path.name.replace('"', "")
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    chunks = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
        "Content-Type: application/json\r\n\r\n".encode("ascii")
        + json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\r\n",
        (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[0]\"; "
            f"filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n"
        ).encode("utf-8") + path.read_bytes() + b"\r\n",
        f"--{boundary}--\r\n".encode("ascii"),
    ]
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _message_body(args: dict[str, Any], policy: dict[str, Any]) -> tuple[dict[str, Any], bytes | None, str]:
    body: dict[str, Any] = {}
    content = args.get("content")
    components = args.get("components")
    if isinstance(content, str):
        body["content"] = content
    if isinstance(components, list):
        if len(json.dumps(components)) > 32 * 1024:
            raise ParityError("components-too-large")
        body["components"] = components
    if args.get("silent") is True:
        body["flags"] = 4096
    if "file_path" not in args:
        if not body:
            raise ParityError("message-content-required")
        return body, None, "application/json"
    path = _safe_file(args.get("file_path"), policy)
    body["attachments"] = [{"id": 0, "filename": path.name}]
    raw, content_type = _multipart(body, path)
    return body, raw, content_type


def _message_result(message: Any) -> str:
    if not isinstance(message, dict):
        return json.dumps({"schemaVersion": 1, "status": "ok"})
    return json.dumps({
        "schemaVersion": 1,
        "status": "ok",
        "message": {
            "id": message.get("id"),
            "channel_id": message.get("channel_id"),
            "content": message.get("content", ""),
            "timestamp": message.get("timestamp"),
        },
    }, separators=(",", ":"))


def _dispatch(args: dict[str, Any], action: str, policy: dict[str, Any]) -> str:
    channel = args.get("channel_id")
    guild = args.get("guild_id")
    message = args.get("message_id")
    if action in {
        "channel_edit", "category_edit", "channel_delete", "category_delete",
        "channel_move",
    }:
        _verify_channel_guild(channel, guild)
    if action in {"thread_edit", "thread_reply", "thread_messages"}:
        _verify_thread_scope(channel, guild, policy)
    if action == "event_create" and not args.get("location"):
        _verify_thread_scope(channel, guild, policy)
    parent = args.get("parent_id")
    if parent is not None and action in {
        "channel_create", "channel_edit", "category_edit", "channel_move",
    }:
        _verify_channel_guild(parent, guild)
    if action in {"send_message", "thread_reply"}:
        body, raw, content_type = _message_body(args, policy)
        result = _request("POST", f"/channels/{channel}/messages", body=body, raw=raw, content_type=content_type)
        return _message_result(result)
    if action == "edit_message":
        body, raw, _ = _message_body(args, policy)
        if raw is not None:
            raise ParityError("edit-file-not-supported")
        return _message_result(_request("PATCH", f"/channels/{channel}/messages/{message}", body=body))
    if action in {"add_reaction", "remove_reaction"}:
        emoji = urllib.parse.quote(str(args.get("emoji", "")), safe="")
        if not emoji:
            raise ParityError("emoji-required")
        method = "PUT" if action == "add_reaction" else "DELETE"
        _request(method, f"/channels/{channel}/messages/{message}/reactions/{emoji}/@me")
        return json.dumps({"schemaVersion": 1, "status": "ok"})
    if action == "list_reactions":
        emoji = urllib.parse.quote(str(args.get("emoji", "")), safe="")
        if not emoji:
            raise ParityError("emoji-required")
        users = _request("GET", f"/channels/{channel}/messages/{message}/reactions/{emoji}", params={"limit": args.get("limit", 25)})
        return json.dumps({"schemaVersion": 1, "status": "ok", "users": users}, separators=(",", ":"))
    if action == "create_poll":
        options = args.get("poll_options")
        question = args.get("poll_question")
        if not isinstance(question, str) or not isinstance(options, list) or not 2 <= len(options) <= 10:
            raise ParityError("poll-invalid")
        body = {
            "content": args.get("content", ""),
            "poll": {
                "question": {"text": question},
                "answers": [{"poll_media": {"text": item}} for item in options],
                "duration": args.get("poll_duration_hours", 24),
                "allow_multiselect": args.get("poll_multiselect", False),
            },
        }
        return _message_result(_request("POST", f"/channels/{channel}/messages", body=body))
    if action == "search_messages":
        params = {
            "content": args.get("query", ""),
            "limit": args.get("limit", 25),
            "channel_id": args.get("channel_ids", []),
        }
        result = _request("GET", f"/guilds/{guild}/messages/search", params=params)
        return json.dumps({"schemaVersion": 1, "status": "ok", "result": result}, separators=(",", ":"))
    if action == "list_threads":
        _verify_channel_guild(parent, guild)
        active = _request("GET", f"/guilds/{guild}/threads/active")
        if isinstance(active, dict) and isinstance(active.get("threads"), list):
            active = dict(active)
            active["threads"] = [
                thread
                for thread in active["threads"]
                if isinstance(thread, dict) and thread.get("parent_id") == parent
            ]
        return json.dumps({"schemaVersion": 1, "status": "ok", "result": active}, separators=(",", ":"))
    if action == "thread_messages":
        result = _request(
            "GET",
            f"/channels/{channel}/messages",
            params={"limit": args.get("limit", 50)},
        )
        return json.dumps(
            {"schemaVersion": 1, "status": "ok", "messages": result},
            separators=(",", ":"),
        )
    if action == "channel_permissions":
        value = _request("GET", f"/channels/{channel}")
        return json.dumps({"schemaVersion": 1, "status": "ok", "permission_overwrites": value.get("permission_overwrites", [])}, separators=(",", ":"))
    if action == "emoji_list":
        return json.dumps({"schemaVersion": 1, "status": "ok", "emojis": _request("GET", f"/guilds/{guild}/emojis")}, separators=(",", ":"))
    if action == "send_sticker":
        return _message_result(_request("POST", f"/channels/{channel}/messages", body={"content": args.get("content", ""), "sticker_ids": [args.get("sticker_id")] }))
    if action == "role_info":
        roles = _request("GET", f"/guilds/{guild}/roles")
        role = next((item for item in roles if item.get("id") == args.get("role_id")), None)
        if role is None:
            raise ParityError("role-not-found")
        return json.dumps({"schemaVersion": 1, "status": "ok", "role": role}, separators=(",", ":"))
    if action == "voice_status":
        value = _request("GET", f"/guilds/{guild}/voice-states/{args.get('user_id')}")
        return json.dumps({"schemaVersion": 1, "status": "ok", "voice_state": value}, separators=(",", ":"))
    if action == "event_list":
        return json.dumps({"schemaVersion": 1, "status": "ok", "events": _request("GET", f"/guilds/{guild}/scheduled-events", params={"with_user_count": "true"})}, separators=(",", ":"))
    if action == "event_create":
        location = args.get("location")
        event_body: dict[str, Any] = {
            "name": args.get("name"), "description": args.get("description"),
            "scheduled_start_time": args.get("start_time"), "privacy_level": 2,
        }
        if location:
            event_body.update({"entity_type": 3, "entity_metadata": {"location": location}, "scheduled_end_time": args.get("end_time")})
        else:
            event_body.update({"entity_type": 2, "channel_id": channel})
        return json.dumps({"schemaVersion": 1, "status": "ok", "event": _request("POST", f"/guilds/{guild}/scheduled-events", body=event_body)}, separators=(",", ":"))
    if action in {"channel_create", "category_create"}:
        body = {"name": args.get("name"), "type": 4 if action == "category_create" else 0}
        for key in ("topic", "parent_id", "position", "nsfw"):
            if key in args:
                body[key] = args[key]
        return json.dumps({"schemaVersion": 1, "status": "ok", "channel": _request("POST", f"/guilds/{guild}/channels", body=body)}, separators=(",", ":"))
    if action in {"channel_edit", "category_edit"}:
        body = {key: args[key] for key in ("name", "topic", "parent_id", "position", "nsfw") if key in args}
        return json.dumps({"schemaVersion": 1, "status": "ok", "channel": _request("PATCH", f"/channels/{channel}", body=body)}, separators=(",", ":"))
    if action in {"channel_delete", "category_delete"}:
        _request("DELETE", f"/channels/{channel}")
        return json.dumps({"schemaVersion": 1, "status": "ok"})
    if action == "channel_move":
        body = [{"id": channel, "position": args.get("position"), "parent_id": args.get("parent_id")}]
        return json.dumps({"schemaVersion": 1, "status": "ok", "channels": _request("PATCH", f"/guilds/{guild}/channels", body=body)}, separators=(",", ":"))
    if action == "thread_edit":
        body = {
            key: args[key]
            for key in (
                "name", "archived", "locked", "invitable",
                "auto_archive_duration", "rate_limit_per_user",
            )
            if key in args
        }
        value = _request("PATCH", f"/channels/{channel}", body=body)
        return json.dumps(
            {"schemaVersion": 1, "status": "ok", "thread": value},
            separators=(",", ":"),
        )
    raise ParityError("action-not-supported")


def _handle(args: dict[str, Any], **_: Any) -> str:
    if not isinstance(args, dict):
        return _error("invalid-request")
    action = args.get("action")
    if action not in set(SCHEMA["parameters"]["properties"]["action"]["enum"]):
        return _error("invalid-action")
    try:
        _validate_args(args, action)
        policy = _allowed(args, action)
        return _dispatch(args, action, policy)
    except ParityError as exc:
        return _error(str(exc))


def _check() -> bool:
    try:
        _policy()
        return bool((get_secret("DISCORD_BOT_TOKEN", "") or "").strip())
    except Exception:
        return False


def register(ctx: Any) -> None:
    """Register the policy-bounded Discord parity tool."""

    ctx.register_tool(
        name="discord_parity",
        toolset="discord_parity",
        schema=SCHEMA,
        handler=_handle,
        check_fn=_check,
        description=SCHEMA["description"],
        emoji="",
    )
