"""Expose redacted Docker inventory and the managed updater trigger."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

_HOSTS = {
    "docker-vm": "192.168.1.153",
    "media-vm": "192.168.1.136",
    "nextcloud-vm": "192.168.1.78",
    "jn-t14s-lin": "192.168.1.31",
}
_UPDATE_HOSTS = {
    host: address for host, address in _HOSTS.items() if host != "jn-t14s-lin"
}
_SSH = "/usr/bin/ssh"
_KNOWN_HOSTS = "/etc/hermes/astra/docker-known-hosts"
_CREDENTIAL = "agent-docker-report-key"
_UPDATE_CREDENTIAL = "agent-docker-update-key"
_MAX_REPORT_BYTES = 16 * 1024 * 1024
_MAX_UPDATE_BYTES = 4096
_MAX_CONTAINERS = 2048
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+:/@-]*$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_TURN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

_SCHEMA = {
    "name": "docker_inventory",
    "description": (
        "Read the current redacted Docker container and image inventory from "
        "one managed host or all managed Docker hosts. This tool cannot read "
        "container logs, environment variables, mounts, ports, commands, "
        "networks, secrets, or the Docker socket."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "host": {
                "type": "string",
                "enum": ["all", *_HOSTS],
                "description": "Managed Docker host to inspect.",
            }
        },
        "required": ["host"],
        "additionalProperties": False,
    },
}

_UPDATE_SCHEMA = {
    "name": "docker_update",
    "description": (
        "Read the status of, or trigger, the existing Ansible-managed Docker "
        "auto-updater on one managed host or all eligible hosts. The target "
        "stacks, services, update policy, and major-version guard are fixed by "
        "Ansible; this tool cannot select a container, image, path, command, "
        "or Compose option."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "host": {
                "type": "string",
                "enum": ["all", *_UPDATE_HOSTS],
                "description": "Managed Docker update host.",
            },
            "action": {
                "type": "string",
                "enum": ["status", "run"],
                "description": "Read updater status or request an immediate run.",
            },
        },
        "required": ["host", "action"],
        "additionalProperties": False,
    },
}


class InventoryError(RuntimeError):
    """Expected fixed-code failure at the report boundary."""


def _error(code: str) -> str:
    return json.dumps(
        {"schemaVersion": 1, "status": "error", "code": code},
        sort_keys=True,
        separators=(",", ":"),
    )


def _credentials_directory() -> Path:
    raw = os.environ.get("CREDENTIALS_DIRECTORY", "")
    path = Path(raw)
    if not raw or not path.is_absolute():
        raise InventoryError("credential-unavailable")
    return path


def _safe_token(value: Any, limit: int) -> bool:
    return (
        value is None
        or (
            isinstance(value, str)
            and 0 < len(value) <= limit
            and _TOKEN.fullmatch(value) is not None
        )
    )


def _safe_identifier(value: Any, limit: int) -> bool:
    return (
        value is None
        or (
            isinstance(value, str)
            and 0 < len(value) <= limit
            and _IDENTIFIER.fullmatch(value) is not None
        )
    )


def _safe_integer(value: Any) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool))


def _require_keys(value: Any, expected: set[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise InventoryError(code)
    return value


def _validate_report(value: Any, expected_host: str) -> dict[str, Any]:
    report = _require_keys(
        value,
        {
            "schemaVersion",
            "generatedAt",
            "host",
            "updateSemantics",
            "engine",
            "containers",
        },
        "invalid-report",
    )
    if (
        report["schemaVersion"] != 2
        or report["host"] != expected_host
        or report["updateSemantics"] != "local-tag-comparison-only"
        or not _safe_token(report["generatedAt"], 64)
    ):
        raise InventoryError("invalid-report")
    engine = _require_keys(
        report["engine"], {"version", "apiVersion", "os", "arch"}, "invalid-report"
    )
    if not (
        _safe_token(engine["version"], 64)
        and _safe_token(engine["apiVersion"], 16)
        and _safe_identifier(engine["os"], 32)
        and _safe_identifier(engine["arch"], 32)
    ):
        raise InventoryError("invalid-report")
    containers = report["containers"]
    if not isinstance(containers, list) or len(containers) > _MAX_CONTAINERS:
        raise InventoryError("invalid-report")
    for item in containers:
        container = _require_keys(
            item,
            {
                "containerId",
                "name",
                "state",
                "health",
                "restartCount",
                "exitCode",
                "startedAt",
                "finishedAt",
                "compose",
                "image",
            },
            "invalid-report",
        )
        compose = _require_keys(
            container["compose"], {"project", "service"}, "invalid-report"
        )
        image = _require_keys(
            container["image"],
            {
                "reference",
                "runningId",
                "taggedLocalId",
                "repoDigests",
                "created",
                "version",
                "revision",
                "updateState",
            },
            "invalid-report",
        )
        if not (
            _safe_token(container["containerId"], 12)
            and _safe_identifier(container["name"], 128)
            and _safe_identifier(container["state"], 32)
            and _safe_identifier(container["health"], 32)
            and _safe_integer(container["restartCount"])
            and _safe_integer(container["exitCode"])
            and _safe_token(container["startedAt"], 64)
            and _safe_token(container["finishedAt"], 64)
            and _safe_identifier(compose["project"], 128)
            and _safe_identifier(compose["service"], 128)
            and _safe_token(image["reference"], 512)
            and _safe_token(image["runningId"], 128)
            and _safe_token(image["taggedLocalId"], 128)
            and _safe_token(image["created"], 64)
            and _safe_token(image["version"], 128)
            and _safe_token(image["revision"], 128)
            and image["updateState"]
            in {"unknown", "pinned-digest", "current-local", "pending-local"}
            and isinstance(image["repoDigests"], list)
            and len(image["repoDigests"]) <= 16
            and all(_safe_token(item, 512) for item in image["repoDigests"])
        ):
            raise InventoryError("invalid-report")
    return report


def _read_host(host: str) -> dict[str, Any]:
    credential = _credentials_directory() / _CREDENTIAL
    if not credential.is_file() or not Path(_KNOWN_HOSTS).is_file():
        raise InventoryError("credential-unavailable")
    command = [
        _SSH,
        "-F",
        "/dev/null",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={_KNOWN_HOSTS}",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "RequestTTY=no",
        "-o",
        "ClearAllForwardings=yes",
        "-i",
        str(credential),
        f"agent-report@{_HOSTS[host]}",
    ]
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=12,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InventoryError("report-unavailable") from exc
    if result.returncode != 0 or len(result.stdout) > _MAX_REPORT_BYTES:
        raise InventoryError("report-unavailable")
    try:
        value = json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InventoryError("invalid-report") from exc
    return _validate_report(value, host)


def _validate_update_response(
    value: Any, expected_host: str, expected_action: str
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InventoryError("invalid-update-response")
    if value.get("status") == "error":
        if (
            set(value) != {"schemaVersion", "status", "code"}
            or value.get("schemaVersion") != 1
            or not _safe_identifier(value.get("code"), 64)
        ):
            raise InventoryError("invalid-update-response")
        return value
    required = {
        "schemaVersion",
        "host",
        "status",
        "action",
        "outcome",
        "managed",
        "serviceState",
        "timerState",
        "lastResult",
        "exitCode",
    }
    allowed = required | {"retryAfterSeconds"}
    if frozenset(value) not in {frozenset(required), frozenset(allowed)}:
        raise InventoryError("invalid-update-response")
    if (
        value.get("schemaVersion") != 1
        or value.get("host") != expected_host
        or value.get("status") != "ok"
        or value.get("action") != expected_action
        or value.get("outcome")
        not in {
            "accepted",
            "already-running",
            "cooldown",
            "ready",
            "start-failed",
            "unavailable",
        }
        or not isinstance(value.get("managed"), bool)
        or value.get("serviceState")
        not in {
            "active",
            "activating",
            "deactivating",
            "failed",
            "inactive",
            "unknown",
        }
        or value.get("timerState")
        not in {
            "active",
            "activating",
            "deactivating",
            "failed",
            "inactive",
            "unknown",
        }
        or value.get("lastResult")
        not in {
            "core-dump",
            "exit-code",
            "resources",
            "signal",
            "success",
            "timeout",
            "unknown",
        }
        or not isinstance(value.get("exitCode"), int)
        or isinstance(value.get("exitCode"), bool)
    ):
        raise InventoryError("invalid-update-response")
    retry = value.get("retryAfterSeconds")
    if retry is not None and (
        not isinstance(retry, int) or isinstance(retry, bool) or retry < 0 or retry > 86400
    ):
        raise InventoryError("invalid-update-response")
    return value


def _update_host(host: str, action: str) -> dict[str, Any]:
    credential = _credentials_directory() / _UPDATE_CREDENTIAL
    if not credential.is_file() or not Path(_KNOWN_HOSTS).is_file():
        raise InventoryError("credential-unavailable")
    command = [
        _SSH,
        "-F",
        "/dev/null",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={_KNOWN_HOSTS}",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "RequestTTY=no",
        "-o",
        "ClearAllForwardings=yes",
        "-i",
        str(credential),
        f"agent-auto-update@{_UPDATE_HOSTS[host]}",
    ]
    request = json.dumps(
        {"schemaVersion": 1, "action": action},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    try:
        result = subprocess.run(
            command,
            input=request,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=12,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InventoryError("update-unavailable") from exc
    if result.returncode != 0 or len(result.stdout) > _MAX_UPDATE_BYTES:
        raise InventoryError("update-unavailable")
    try:
        value = json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InventoryError("invalid-update-response") from exc
    return _validate_update_response(value, host, action)


def _handle_inventory(args: dict[str, Any], **_: Any) -> str:
    host = args.get("host") if isinstance(args, dict) else None
    if not isinstance(args, dict) or set(args) != {"host"} or host not in {
        "all",
        *_HOSTS,
    }:
        return _error("invalid-request")
    selected = list(_HOSTS) if host == "all" else [host]
    try:
        reports = [_read_host(item) for item in selected]
    except InventoryError as exc:
        return _error(str(exc))
    return json.dumps(
        {"schemaVersion": 1, "status": "ok", "reports": reports},
        sort_keys=True,
        separators=(",", ":"),
    )


def _handle_update(args: dict[str, Any], **_: Any) -> str:
    host = args.get("host") if isinstance(args, dict) else None
    action = args.get("action") if isinstance(args, dict) else None
    if (
        not isinstance(args, dict)
        or set(args) != {"host", "action"}
        or host not in {"all", *_UPDATE_HOSTS}
        or action not in {"status", "run"}
    ):
        return _error("invalid-request")
    selected = list(_UPDATE_HOSTS) if host == "all" else [host]
    try:
        results = [_update_host(item, action) for item in selected]
    except InventoryError as exc:
        return _error(str(exc))
    return json.dumps(
        {"schemaVersion": 1, "status": "ok", "results": results},
        sort_keys=True,
        separators=(",", ":"),
    )


def _check_available() -> bool:
    try:
        credential = _credentials_directory() / _CREDENTIAL
    except InventoryError:
        return False
    return (
        Path(_SSH).is_file()
        and Path(_KNOWN_HOSTS).is_file()
        and credential.is_file()
    )


def _check_update_available() -> bool:
    try:
        credential = _credentials_directory() / _UPDATE_CREDENTIAL
    except InventoryError:
        return False
    return (
        Path(_SSH).is_file()
        and Path(_KNOWN_HOSTS).is_file()
        and credential.is_file()
    )


def _require_update_approval(
    *,
    tool_name: str = "",
    args: Any = None,
    turn_id: str = "",
    **_: Any,
) -> dict[str, str] | None:
    """Escalate only an immediate updater run to Hermes's native approval UI."""

    if tool_name != "docker_update" or not isinstance(args, dict):
        return None
    if args.get("action") != "run":
        return None
    if _TURN_ID.fullmatch(turn_id or "") is None:
        return {
            "action": "block",
            "message": "An immediate Docker update requires a bound user turn.",
        }
    host = args.get("host")
    if host not in {"all", *_UPDATE_HOSTS}:
        return {
            "action": "block",
            "message": "The Docker update target is outside managed policy.",
        }
    return {
        "action": "approve",
        "message": (
            "Start the existing Ansible-managed Docker auto-updater now for "
            f"{host}. Scheduled updates remain automatic."
        ),
        # A turn-bound key prevents a persistent approval from authorizing a
        # later injected request. Session/always choices therefore apply only
        # to this exact user turn.
        "rule_key": f"docker-update:{turn_id}",
    }


def register(ctx: Any) -> None:
    """Register the two fixed Docker boundary tools."""

    ctx.register_hook("pre_tool_call", _require_update_approval)

    ctx.register_tool(
        name="docker_inventory",
        toolset="agent_docker",
        schema=_SCHEMA,
        handler=_handle_inventory,
        check_fn=_check_available,
        description=_SCHEMA["description"],
        emoji="",
    )
    ctx.register_tool(
        name="docker_update",
        toolset="agent_docker",
        schema=_UPDATE_SCHEMA,
        handler=_handle_update,
        check_fn=_check_update_available,
        description=_UPDATE_SCHEMA["description"],
        emoji="",
    )
