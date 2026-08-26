"""Expose typed, rollback-backed Compose transactions to Astra."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Any

_ENDPOINTS = Path("/etc/hermes/astra/compose-admin-endpoints.json")
_KNOWN_HOSTS = "/etc/hermes/astra/compose-admin-known-hosts"
_CREDENTIAL = "agent-compose-key"
_LAN = ip_network("192.168.1.0/24")
_MAX_REQUEST = 128 * 1024
_MAX_RESPONSE = 256 * 1024
_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_NAME = re.compile(r"^[a-z][a-z0-9-]{0,47}$")
_TURN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CODE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@+-]{0,254}$")
_SENSITIVE = re.compile(
    r"api.?key|authorization|cookie|credential|pass(word)?|private.?key|secret|token",
    re.IGNORECASE,
)
_ACTIONS = {"status", "plan", "apply", "remove"}
_READ_ACTIONS = {"status", "plan"}

_HOSTS_SCHEMA = {
    "name": "compose_hosts",
    "description": "List Docker hosts enrolled in Astra's bounded Compose transaction broker.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}

_REQUEST_SCHEMA = {
    "name": "compose_request",
    "description": (
        "Inspect, validate, deploy, update, or remove a root-managed Docker Compose stack. "
        "Specs support versioned public images, non-secret environment values, named volumes, "
        "tmpfs, bounded ports, restart policy, and resource limits. Host binds, Docker sockets, "
        "privileged access, devices, capabilities, host namespaces, inline secrets, latest tags, "
        "and arbitrary Compose keys are denied. Apply and remove require exact fresh approval."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "host": {"type": "string", "pattern": _HOST.pattern, "maxLength": 128},
            "action": {"type": "string", "enum": sorted(_ACTIONS)},
            "stack": {"type": "string", "pattern": _NAME.pattern, "maxLength": 48},
            "spec": {"type": "object"},
        },
        "required": ["host", "action"],
        "additionalProperties": False,
    },
}


class ComposePluginError(RuntimeError):
    """Expected fixed-code plugin failure."""


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _error(code: str) -> str:
    return json.dumps({"schemaVersion": 1, "status": "error", "code": code}, sort_keys=True, separators=(",", ":"))


def _credential() -> Path:
    directory = os.environ.get("CREDENTIALS_DIRECTORY", "")
    path = Path(directory) / _CREDENTIAL
    if not directory or not path.is_file():
        raise ComposePluginError("credential-unavailable")
    return path


def _load_hosts() -> dict[str, str]:
    try:
        info = os.lstat(_ENDPOINTS)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o440 or info.st_size > _MAX_REQUEST:
            raise ComposePluginError("endpoint-unavailable")
        value = json.loads(_ENDPOINTS.read_text(encoding="ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ComposePluginError("endpoint-unavailable") from exc
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "hosts"} or value.get("schemaVersion") != 1 or not isinstance(value.get("hosts"), list):
        raise ComposePluginError("invalid-endpoints")
    result: dict[str, str] = {}
    for item in value["hosts"]:
        if not isinstance(item, dict) or set(item) != {"name", "address"}:
            raise ComposePluginError("invalid-endpoints")
        name, address = item["name"], item["address"]
        if not isinstance(name, str) or _HOST.fullmatch(name) is None or name in result or not isinstance(address, str):
            raise ComposePluginError("invalid-endpoints")
        try:
            endpoint = ip_address(address)
        except ValueError as exc:
            raise ComposePluginError("invalid-endpoints") from exc
        if endpoint not in _LAN:
            raise ComposePluginError("invalid-endpoints")
        result[name] = address
    if not result or len(result) > 32:
        raise ComposePluginError("invalid-endpoints")
    return result


def _spec_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "services"} or value.get("schemaVersion") != 1 or not isinstance(value.get("services"), dict) or not 1 <= len(value["services"]) <= 16:
        raise ComposePluginError("invalid-spec")
    images: list[str] = []
    ports: list[str] = []
    allowed = {"image", "restart", "environment", "ports", "volumes", "tmpfs", "readOnly", "cpus", "memoryMb", "pidsLimit"}
    for name, service in sorted(value["services"].items()):
        if not isinstance(name, str) or _NAME.fullmatch(name) is None or not isinstance(service, dict) or set(service) - allowed or "image" not in service:
            raise ComposePluginError("invalid-spec")
        image = service["image"]
        if not isinstance(image, str) or _IMAGE.fullmatch(image) is None or "$" in image or image.rsplit("/", 1)[-1].endswith(":latest"):
            raise ComposePluginError("invalid-spec")
        tail = image.rsplit("/", 1)[-1]
        if "@sha256:" not in image and ":" not in tail:
            raise ComposePluginError("invalid-spec")
        environment = service.get("environment", {})
        if not isinstance(environment, dict) or any(not isinstance(key, str) or _SENSITIVE.search(key) for key in environment):
            raise ComposePluginError("invalid-spec")
        published = service.get("ports", [])
        if not isinstance(published, list):
            raise ComposePluginError("invalid-spec")
        for item in published:
            if not isinstance(item, dict) or set(item) != {"target", "published", "scope", "protocol"}:
                raise ComposePluginError("invalid-spec")
            ports.append(f"{item.get('scope')}:{item.get('published')}->{item.get('target')}/{item.get('protocol')}")
        images.append(image)
    return {"services": sorted(value["services"]), "images": images, "publishedPorts": ports}


def _request(args: Any) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if not isinstance(args, dict) or set(args) - {"host", "action", "stack", "spec"} or not {"host", "action"} <= set(args):
        raise ComposePluginError("invalid-request")
    host, action, stack = args.get("host"), args.get("action"), args.get("stack")
    if not isinstance(host, str) or _HOST.fullmatch(host) is None or action not in _ACTIONS:
        raise ComposePluginError("invalid-request")
    if stack is not None and (not isinstance(stack, str) or _NAME.fullmatch(stack) is None):
        raise ComposePluginError("invalid-request")
    summary = None
    if action == "status":
        if "spec" in args:
            raise ComposePluginError("invalid-request")
    elif action in {"plan", "apply"}:
        if stack is None or "spec" not in args:
            raise ComposePluginError("invalid-request")
        summary = _spec_summary(args["spec"])
    elif stack is None or "spec" in args:
        raise ComposePluginError("invalid-request")
    request = {"schemaVersion": 1, "action": action}
    if stack is not None:
        request["stack"] = stack
    if "spec" in args:
        request["spec"] = args["spec"]
    return request, summary


def _validate_body(value: Any, depth: int = 0) -> None:
    if depth > 12:
        raise ComposePluginError("invalid-response")
    if isinstance(value, dict):
        if len(value) > 128:
            raise ComposePluginError("invalid-response")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 128 or _SENSITIVE.search(key):
                raise ComposePluginError("invalid-response")
            _validate_body(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > 256:
            raise ComposePluginError("invalid-response")
        for item in value:
            _validate_body(item, depth + 1)
    elif not (value is None or isinstance(value, (str, bool, int, float))):
        raise ComposePluginError("invalid-response")


def _call(host: str, request: dict[str, Any]) -> dict[str, Any]:
    hosts = _load_hosts()
    if host not in hosts:
        raise ComposePluginError("unknown-host")
    payload = _canonical(request)
    if len(payload) > _MAX_REQUEST:
        raise ComposePluginError("invalid-request")
    command = [
        "/usr/bin/ssh", "-F", "/dev/null", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={_KNOWN_HOSTS}",
        "-o", "ConnectTimeout=6", "-o", "ConnectionAttempts=1", "-o", "RequestTTY=no",
        "-o", "ClearAllForwardings=yes", "-i", str(_credential()), f"agent-compose@{hosts[host]}",
    ]
    timeout = 900 if request["action"] == "apply" else 360 if request["action"] == "remove" else 75
    try:
        result = subprocess.run(command, input=payload, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ComposePluginError("host-unavailable") from exc
    if len(result.stdout) > _MAX_RESPONSE:
        raise ComposePluginError("invalid-response")
    try:
        value = json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ComposePluginError("invalid-response") from exc
    if isinstance(value, dict) and value.get("status") == "error":
        if set(value) != {"schemaVersion", "status", "code"} or value.get("schemaVersion") != 1 or not isinstance(value.get("code"), str) or _CODE.fullmatch(value["code"]) is None:
            raise ComposePluginError("invalid-response")
        return value
    if result.returncode != 0 or not isinstance(value, dict) or set(value) != {"schemaVersion", "status", "host", "action", "body"} or value.get("schemaVersion") != 1 or value.get("status") != "ok" or value.get("host") != host or value.get("action") != request["action"]:
        raise ComposePluginError("invalid-response")
    if request.get("stack") is not None and isinstance(value["body"], dict) and value["body"].get("stack") != request["stack"]:
        raise ComposePluginError("invalid-response")
    _validate_body(value["body"])
    return value


def _handle_hosts(args: dict[str, Any], **_: Any) -> str:
    if not isinstance(args, dict) or args:
        return _error("invalid-request")
    try:
        hosts = sorted(_load_hosts())
    except ComposePluginError as exc:
        return _error(str(exc))
    return json.dumps({"schemaVersion": 1, "status": "ok", "hosts": hosts}, sort_keys=True, separators=(",", ":"))


def _handle_request(args: dict[str, Any], **_: Any) -> str:
    try:
        request, _ = _request(args)
        value = _call(args["host"], request)
    except ComposePluginError as exc:
        return _error(str(exc))
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _approval(tool_name: str = "", args: Any = None, turn_id: str = "", **_: Any) -> dict[str, str] | None:
    if tool_name != "compose_request" or not isinstance(args, dict) or args.get("action") in _READ_ACTIONS:
        return None
    try:
        request, summary = _request(args)
    except ComposePluginError:
        return {"action": "block", "message": "The Compose transaction request is invalid."}
    if _TURN.fullmatch(turn_id or "") is None:
        return {"action": "block", "message": "A Compose mutation requires a bound user turn."}
    marker = hashlib.sha256(_canonical(request)).hexdigest()[:20]
    detail = ""
    if summary is not None:
        detail = f" Services: {', '.join(summary['services'])}. Images: {', '.join(summary['images'])}. Ports: {', '.join(summary['publishedPorts']) or 'none'}."
    return {
        "action": "approve",
        "message": f"Allow managed Compose {request['action']} on {args['host']} stack {request.get('stack', 'unknown')}?{detail}",
        "rule_key": f"compose-admin:{turn_id}:{marker}",
    }


def register(context: Any) -> None:
    context.register_hook("pre_tool_call", _approval)
    context.register_tool(name="compose_hosts", description=_HOSTS_SCHEMA["description"], schema={"type": "function", "function": _HOSTS_SCHEMA}, handler=_handle_hosts, toolset="compose_admin")
    context.register_tool(name="compose_request", description=_REQUEST_SCHEMA["description"], schema={"type": "function", "function": _REQUEST_SCHEMA}, handler=_handle_request, toolset="compose_admin")
