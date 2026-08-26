"""Expose bounded forced-command host administration to Astra."""

from __future__ import annotations

import json
import os
import re
import socket
import stat
import subprocess
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Any

_ENDPOINTS = Path("/etc/hermes/astra/host-admin-endpoints.json")
_KNOWN_HOSTS = "/etc/hermes/astra/host-admin-known-hosts"
_CREDENTIAL = "agent-host-admin-key"
_ALLOWED_ENDPOINT_NETWORK = ip_network("192.168.1.0/24")
_MAX_MANIFEST = 128 * 1024
_MAX_RESPONSE = 256 * 1024
_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_UNIT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]{0,126}\.(?:service|timer)$")
_PROBE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_TURN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CODE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_SENSITIVE = re.compile(r"api.?key|password|secret|token|authorization|cookie|credential", re.I)

_ACTIONS = [
    "status",
    "health",
    "update",
    "reboot",
    "service-status",
    "service-start",
    "service-stop",
    "service-restart",
]
_READ_ACTIONS = {"status", "health", "service-status"}
_PROBES = [
    "media-stack",
    "media-storage-view",
    "nextcloud-local",
    "plex-corrupt-media",
    "plex-local",
    "storage-status",
    "stream-relay",
]

_HOSTS_SCHEMA = {
    "name": "host_admin_hosts",
    "description": "List currently enrolled managed Linux hosts available through the bounded administration broker.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}

_REQUEST_SCHEMA = {
    "name": "host_admin_request",
    "description": (
        "Read host/update/service/health state or request a managed update, reboot, or "
        "service lifecycle action. Mutations require fresh approval. Updates use "
        "the existing auto-updates service and may reboot under its managed policy."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "host": {"type": "string", "pattern": _HOST.pattern, "maxLength": 128},
            "action": {"type": "string", "enum": _ACTIONS},
            "service": {"type": "string", "pattern": _UNIT.pattern, "maxLength": 128},
            "probe": {"type": "string", "enum": _PROBES},
        },
        "required": ["host", "action"],
        "additionalProperties": False,
    },
}


class HostAdminError(RuntimeError):
    pass


def _error(code: str) -> str:
    return json.dumps({"schemaVersion": 1, "status": "error", "code": code}, sort_keys=True, separators=(",", ":"))


def _credential() -> Path:
    directory = os.environ.get("CREDENTIALS_DIRECTORY", "")
    path = Path(directory) / _CREDENTIAL
    if not directory or not path.is_file():
        raise HostAdminError("credential-unavailable")
    return path


def _validate_host_data(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "hosts"} or value["schemaVersion"] != 1 or not isinstance(value["hosts"], list):
        raise HostAdminError("invalid-endpoints")
    result: dict[str, str] = {}
    for item in value["hosts"]:
        if not isinstance(item, dict) or set(item) != {"name", "address"}:
            raise HostAdminError("invalid-endpoints")
        name, address = item["name"], item["address"]
        if not isinstance(name, str) or _HOST.fullmatch(name) is None or name in result or not isinstance(address, str):
            raise HostAdminError("invalid-endpoints")
        try:
            endpoint = ip_address(address)
        except ValueError as exc:
            raise HostAdminError("invalid-endpoints") from exc
        if endpoint not in _ALLOWED_ENDPOINT_NETWORK:
            raise HostAdminError("invalid-endpoints")
        result[name] = address
    if not result or len(result) > 128:
        raise HostAdminError("invalid-endpoints")
    return result


def _load_hosts() -> dict[str, str]:
    try:
        info = os.lstat(_ENDPOINTS)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o440 or info.st_size > _MAX_MANIFEST:
            raise HostAdminError("endpoint-unavailable")
        value = json.loads(_ENDPOINTS.read_text(encoding="ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HostAdminError("endpoint-unavailable") from exc
    return _validate_host_data(value)


def _validate_body(value: Any, depth: int = 0) -> None:
    if depth > 10:
        raise HostAdminError("invalid-response")
    if isinstance(value, dict):
        if len(value) > 64:
            raise HostAdminError("invalid-response")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 128 or _SENSITIVE.search(key):
                raise HostAdminError("invalid-response")
            _validate_body(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > 128:
            raise HostAdminError("invalid-response")
        for item in value:
            _validate_body(item, depth + 1)
    elif not (value is None or isinstance(value, (str, bool, int, float))):
        raise HostAdminError("invalid-response")


def _call(
    host: str,
    action: str,
    service: str | None = None,
    probe: str | None = None,
) -> dict[str, Any]:
    hosts = _load_hosts()
    if host not in hosts:
        raise HostAdminError("unknown-host")
    request: dict[str, Any] = {"schemaVersion": 1, "action": action}
    if service is not None:
        request["service"] = service
    if probe is not None:
        request["probe"] = probe
    command = [
        "/usr/bin/ssh", "-F", "/dev/null", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={_KNOWN_HOSTS}",
        "-o", "ConnectTimeout=6", "-o", "ConnectionAttempts=1", "-o", "RequestTTY=no",
        "-o", "ClearAllForwardings=yes", "-i", str(_credential()), f"agent-host-admin@{hosts[host]}",
    ]
    try:
        result = subprocess.run(
            command,
            input=json.dumps(request, sort_keys=True, separators=(",", ":")).encode("ascii"),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=55,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HostAdminError("host-unavailable") from exc
    if len(result.stdout) > _MAX_RESPONSE:
        raise HostAdminError("invalid-response")
    try:
        value = json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HostAdminError("invalid-response") from exc
    if isinstance(value, dict) and value.get("status") == "error":
        if set(value) != {"schemaVersion", "status", "code"} or value.get("schemaVersion") != 1 or not isinstance(value.get("code"), str) or _CODE.fullmatch(value["code"]) is None:
            raise HostAdminError("invalid-response")
        return value
    if result.returncode != 0 or not isinstance(value, dict) or set(value) != {"schemaVersion", "status", "host", "action", "body"} or value.get("schemaVersion") != 1 or value.get("status") != "ok" or value.get("host") != host or value.get("action") != action:
        raise HostAdminError("invalid-response")
    _validate_body(value["body"])
    return value


def _handle_hosts(args: dict[str, Any], **_: Any) -> str:
    if not isinstance(args, dict) or args:
        return _error("invalid-request")
    try:
        hosts = sorted(_load_hosts())
    except HostAdminError as exc:
        return _error(str(exc))
    return json.dumps({"schemaVersion": 1, "status": "ok", "hosts": hosts}, sort_keys=True, separators=(",", ":"))


def _handle_request(args: dict[str, Any], **_: Any) -> str:
    if not isinstance(args, dict) or set(args) - {"host", "action", "service", "probe"} or not {"host", "action"} <= set(args):
        return _error("invalid-request")
    host, action = args.get("host"), args.get("action")
    service = args.get("service")
    probe = args.get("probe")
    if not isinstance(host, str) or _HOST.fullmatch(host) is None or action not in _ACTIONS:
        return _error("invalid-request")
    if action.startswith("service-"):
        if not isinstance(service, str) or _UNIT.fullmatch(service) is None or probe is not None:
            return _error("invalid-request")
    elif action == "health":
        if service is not None or not isinstance(probe, str) or probe not in _PROBES:
            return _error("invalid-request")
    elif service is not None or probe is not None:
        return _error("invalid-request")
    try:
        value = _call(host, action, service, probe)
    except HostAdminError as exc:
        return _error(str(exc))
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _approval(tool_name: str, args: dict[str, Any], **context: Any) -> dict[str, Any] | None:
    if tool_name != "host_admin_request" or args.get("action") in _READ_ACTIONS:
        return None
    turn_id = context.get("turn_id") or context.get("turnId") or ""
    if not isinstance(turn_id, str) or _TURN.fullmatch(turn_id) is None:
        return {"action": "block", "reason": "Host administration mutations require a live turn identity."}
    host = args.get("host", "unknown")
    action = args.get("action", "unknown")
    return {
        "action": "approve",
        "reason": f"Approve managed host action {action} on {host}? Updates may invoke the host's existing reboot policy.",
        "rule_key": f"host-admin:{turn_id}",
    }


def register(context: Any) -> None:
    context.register_hook("pre_tool_call", _approval)
    context.register_tool(name="host_admin_hosts", description=_HOSTS_SCHEMA["description"], schema={"type": "function", "function": _HOSTS_SCHEMA}, handler=_handle_hosts, toolset="host_admin")
    context.register_tool(name="host_admin_request", description=_REQUEST_SCHEMA["description"], schema={"type": "function", "function": _REQUEST_SCHEMA}, handler=_handle_request, toolset="host_admin")
