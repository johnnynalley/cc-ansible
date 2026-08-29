"""Expose the credential-isolated local Arr API broker to Astra."""

from __future__ import annotations

import json
import os
import re
import socket
import stat
from pathlib import Path
from typing import Any

_SOCKET = "/run/hermes-arr-api/broker.sock"
_MAX_REQUEST_BYTES = 256 * 1024
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_TURN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SENSITIVE = re.compile(
    r"(?:api.?key|encryption.?key|private.?key|password|passwd|secret|token|authorization|cookie|credential)",
    re.IGNORECASE,
)
_CODE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_SERVICE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")

_QUERY_VALUE = {
    "oneOf": [
        {"type": "string", "maxLength": 2048},
        {"type": "integer"},
        {"type": "number"},
        {"type": "boolean"},
        {
            "type": "array",
            "maxItems": 128,
            "items": {
                "oneOf": [
                    {"type": "string", "maxLength": 2048},
                    {"type": "integer"},
                    {"type": "number"},
                    {"type": "boolean"},
                ]
            },
        },
    ]
}

_LIST_SCHEMA = {
    "name": "arr_services",
    "description": (
        "List the managed Arr-family API services currently available through "
        "the credential-isolated local broker. This returns service names only."
    ),
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}

_REQUEST_SCHEMA = {
    "name": "arr_api_request",
    "description": (
        "Call a supported API path on a managed Sonarr, Radarr, Prowlarr, Bazarr, "
        "or other enrolled Arr-family service. API credentials remain in a separate "
        "broker service and sensitive response fields are redacted. GET is read-only; "
        "POST, PUT, PATCH, and DELETE require fresh turn-bound approval. Redirects, "
        "non-API paths, binary responses, and secret-bearing mutations are denied."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "pattern": "^[a-z][a-z0-9-]{0,31}$",
                "maxLength": 32,
            },
            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
            "path": {
                "type": "string",
                "pattern": "^/api/",
                "maxLength": 512,
            },
            "query": {
                "type": "object",
                "maxProperties": 64,
                "additionalProperties": _QUERY_VALUE,
            },
            "body": {},
        },
        "required": ["service", "method", "path"],
        "additionalProperties": False,
    },
}

_PROWLARR_SCHEMA_SEARCH = {
    "name": "prowlarr_indexer_schema",
    "description": (
        "Search Prowlarr's current indexer schemas by tracker, implementation, "
        "contract, label, or field name. The broker filters the large schema "
        "catalog before returning it and redacts credential values."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 128},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}

_PROWLARR_INDEXER_APPLY = {
    "name": "prowlarr_indexer_apply",
    "description": (
        "Test, create, or update one Prowlarr indexer using a schema definition. "
        "Keep each schema-declared secret field in definition with value null, "
        "and put its actual credential only in the secrets object keyed by the "
        "exact Prowlarr field name. The isolated broker "
        "injects each secret into exactly one matching field, never logs request "
        "bodies, and redacts sensitive response values. Use POST "
        "/api/v1/indexer/test before POST /api/v1/indexer when possible; use PUT "
        "/api/v1/indexer/<id> only for an existing indexer. A bound owner turn "
        "may run this narrow operation without another approval prompt."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "method": {"type": "string", "enum": ["POST", "PUT"]},
            "path": {
                "type": "string",
                "pattern": "^/api/v1/indexer(?:/test|/[1-9][0-9]{0,9})?$",
                "maxLength": 64,
            },
            "definition": {"type": "object"},
            "secrets": {
                "type": "object",
                "minProperties": 1,
                "maxProperties": 32,
                "additionalProperties": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 16384,
                },
            },
        },
        "required": ["method", "path", "definition", "secrets"],
        "additionalProperties": False,
    },
}


class ArrPluginError(RuntimeError):
    """Expected fixed-code plugin failure."""


def _error(code: str) -> str:
    return json.dumps(
        {"schemaVersion": 1, "status": "error", "code": code},
        sort_keys=True,
        separators=(",", ":"),
    )


def _socket_available() -> bool:
    try:
        info = os.lstat(_SOCKET)
    except OSError:
        return False
    return stat.S_ISSOCK(info.st_mode) and not stat.S_ISLNK(info.st_mode)


def _call(value: dict[str, Any]) -> dict[str, Any]:
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    if len(payload) > _MAX_REQUEST_BYTES:
        raise ArrPluginError("invalid-request")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(35)
            client.connect(_SOCKET)
            client.sendall(payload)
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = client.recv(min(65536, _MAX_RESPONSE_BYTES + 2 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > _MAX_RESPONSE_BYTES + 1:
                    raise ArrPluginError("response-too-large")
                if chunk.endswith(b"\n"):
                    break
    except (OSError, TimeoutError) as exc:
        raise ArrPluginError("broker-unavailable") from exc
    raw = b"".join(chunks)
    if not raw.endswith(b"\n") or len(raw) > _MAX_RESPONSE_BYTES + 1:
        raise ArrPluginError("invalid-broker-response")
    try:
        result = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArrPluginError("invalid-broker-response") from exc
    _validate_response(result)
    return result


def _validate_redaction(value: Any, *, depth: int = 0) -> None:
    if depth > 16:
        raise ArrPluginError("invalid-broker-response")
    if isinstance(value, dict):
        if len(value) > 5000:
            raise ArrPluginError("invalid-broker-response")
        named_secret = any(
            isinstance(value.get(marker), str) and _SENSITIVE.search(value[marker])
            for marker in ("name", "key")
        )
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 256:
                raise ArrPluginError("invalid-broker-response")
            if _SENSITIVE.search(key) and item != "[REDACTED]":
                raise ArrPluginError("unredacted-broker-response")
            if (
                named_secret
                and key.lower() in {"value", "defaultvalue"}
                and item != "[REDACTED]"
            ):
                raise ArrPluginError("unredacted-broker-response")
            _validate_redaction(item, depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > 5000:
            raise ArrPluginError("invalid-broker-response")
        for item in value:
            _validate_redaction(item, depth=depth + 1)
    elif not (value is None or isinstance(value, (str, bool, int, float))):
        raise ArrPluginError("invalid-broker-response")


def _validate_response(value: Any) -> None:
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise ArrPluginError("invalid-broker-response")
    if value.get("status") == "error":
        if set(value) != {"schemaVersion", "status", "code"} or not isinstance(
            value.get("code"), str
        ) or _CODE.fullmatch(value["code"]) is None:
            raise ArrPluginError("invalid-broker-response")
        return
    if value.get("status") != "ok":
        raise ArrPluginError("invalid-broker-response")
    if set(value) == {"schemaVersion", "status", "services"}:
        services = value["services"]
        if (
            not isinstance(services, list)
            or not services
            or len(services) > 16
            or services
            != sorted(services, key=lambda item: item.get("name", "") if isinstance(item, dict) else "")
            or any(
                not isinstance(item, dict)
                or set(item) != {"name", "statusPath"}
                or not isinstance(item["name"], str)
                or _SERVICE.fullmatch(item["name"]) is None
                or not isinstance(item["statusPath"], str)
                or not item["statusPath"].startswith("/api/")
                or len(item["statusPath"]) > 512
                for item in services
            )
            or len({item["name"] for item in services}) != len(services)
        ):
            raise ArrPluginError("invalid-broker-response")
        return
    if set(value) != {
        "schemaVersion",
        "status",
        "service",
        "method",
        "path",
        "httpStatus",
        "body",
    }:
        raise ArrPluginError("invalid-broker-response")
    if (
        not isinstance(value["service"], str)
        or value["method"] not in {"GET", "POST", "PUT", "PATCH", "DELETE"}
        or not isinstance(value["path"], str)
        or not value["path"].startswith("/api/")
        or not isinstance(value["httpStatus"], int)
        or isinstance(value["httpStatus"], bool)
        or not 100 <= value["httpStatus"] <= 599
    ):
        raise ArrPluginError("invalid-broker-response")
    _validate_redaction(value["body"])


def _handle_list(args: dict[str, Any], **_: Any) -> str:
    if not isinstance(args, dict) or args:
        return _error("invalid-request")
    try:
        result = _call({"schemaVersion": 1, "action": "list"})
    except ArrPluginError as exc:
        return _error(str(exc))
    return json.dumps(result, sort_keys=True, separators=(",", ":"))


def _handle_request(args: dict[str, Any], **_: Any) -> str:
    if not isinstance(args, dict):
        return _error("invalid-request")
    allowed = {"service", "method", "path", "query", "body"}
    if set(args) - allowed or not {"service", "method", "path"} <= set(args):
        return _error("invalid-request")
    request = {"schemaVersion": 1, "action": "request", **args}
    try:
        result = _call(request)
    except ArrPluginError as exc:
        return _error(str(exc))
    if result.get("status") == "ok" and (
        result.get("service") != args["service"]
        or result.get("method") != args["method"]
        or result.get("path") != args["path"]
    ):
        return _error("invalid-broker-response")
    return json.dumps(result, sort_keys=True, separators=(",", ":"))


def _handle_prowlarr_schema(args: dict[str, Any], **_: Any) -> str:
    if not isinstance(args, dict) or set(args) != {"query"}:
        return _error("invalid-request")
    request = {
        "schemaVersion": 1,
        "action": "prowlarr-schema-search",
        "query": args["query"],
    }
    try:
        result = _call(request)
    except ArrPluginError as exc:
        return _error(str(exc))
    return json.dumps(result, sort_keys=True, separators=(",", ":"))


def _handle_prowlarr_indexer(args: dict[str, Any], **_: Any) -> str:
    if not isinstance(args, dict) or set(args) != {
        "method",
        "path",
        "definition",
        "secrets",
    }:
        return _error("invalid-request")
    request = {
        "schemaVersion": 1,
        "action": "prowlarr-indexer-apply",
        **args,
    }
    try:
        result = _call(request)
    except ArrPluginError as exc:
        return _error(str(exc))
    if result.get("status") == "ok" and (
        result.get("service") != "prowlarr"
        or result.get("method") != args["method"]
        or result.get("path") != args["path"]
    ):
        return _error("invalid-broker-response")
    return json.dumps(result, sort_keys=True, separators=(",", ":"))


def _require_write_approval(
    *, tool_name: str = "", args: Any = None, turn_id: str = "", **_: Any
) -> dict[str, str] | None:
    if tool_name not in {"arr_api_request", "prowlarr_indexer_apply"} or not isinstance(args, dict):
        return None
    method = args.get("method")
    if method == "GET":
        return None
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return {"action": "block", "message": "The Arr API method is invalid."}
    if _TURN_ID.fullmatch(turn_id or "") is None:
        return {
            "action": "block",
            "message": "An Arr API mutation requires a bound user turn.",
        }
    if tool_name == "prowlarr_indexer_apply":
        return None
    service = args.get("service", "prowlarr" if tool_name == "prowlarr_indexer_apply" else "unknown")
    path = args.get("path", "unknown")
    return {
        "action": "approve",
        "message": f"Allow {method} on managed {service} API path {path}?",
        "rule_key": f"arr-api-write:{turn_id}",
    }


def register(ctx: Any) -> None:
    ctx.register_hook("pre_tool_call", _require_write_approval)
    ctx.register_tool(
        name="arr_services",
        toolset="arr_api",
        schema=_LIST_SCHEMA,
        handler=_handle_list,
        check_fn=_socket_available,
        description=_LIST_SCHEMA["description"],
        emoji="",
    )
    ctx.register_tool(
        name="arr_api_request",
        toolset="arr_api",
        schema=_REQUEST_SCHEMA,
        handler=_handle_request,
        check_fn=_socket_available,
        description=_REQUEST_SCHEMA["description"],
        emoji="",
    )
    ctx.register_tool(
        name="prowlarr_indexer_schema",
        toolset="arr_api",
        schema=_PROWLARR_SCHEMA_SEARCH,
        handler=_handle_prowlarr_schema,
        check_fn=_socket_available,
        description=_PROWLARR_SCHEMA_SEARCH["description"],
        emoji="",
    )
    ctx.register_tool(
        name="prowlarr_indexer_apply",
        toolset="arr_api",
        schema=_PROWLARR_INDEXER_APPLY,
        handler=_handle_prowlarr_indexer,
        check_fn=_socket_available,
        description=_PROWLARR_INDEXER_APPLY["description"],
        emoji="",
    )
