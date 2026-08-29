#!/usr/bin/env python3
"""Broker authenticated Arr API requests without exposing API credentials."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import signal
import socket
import socketserver
import stat
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

MAX_REQUEST_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_SCHEMA_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_SERVICES = 16
MAX_COLLECTION_ITEMS = 5000
MAX_DEPTH = 16
MAX_SCHEMA_MATCHES = 20
MAX_INDEXER_SECRETS = 32
SERVICE_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
PATH_RE = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/-]{1,511}$")
INDEXER_UPDATE_PATH_RE = re.compile(r"^/api/v1/indexer/[1-9][0-9]{0,9}$")
SENSITIVE_KEY_RE = re.compile(
    r"(?:api.?key|encryption.?key|private.?key|password|passwd|secret|token|authorization|cookie|credential)",
    re.IGNORECASE,
)
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
SECRET_PLACEHOLDERS = (None, "", "[REDACTED]", "********")


class BrokerError(RuntimeError):
    """Expected fixed-code broker failure."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise urllib.error.HTTPError(req.full_url, code, "redirect-denied", headers, fp)


def compact(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def error(code: str) -> dict[str, Any]:
    return {"schemaVersion": 1, "status": "error", "code": code}


def require_keys(value: Any, expected: set[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise BrokerError(code)
    return value


def validate_credential(value: Any) -> dict[str, Any]:
    item = require_keys(
        value,
        {
            "schemaVersion",
            "service",
            "baseUrl",
            "apiHeader",
            "apiKey",
            "pathPrefixes",
            "statusPath",
        },
        "invalid-credential",
    )
    service = item["service"]
    api_key = item["apiKey"]
    header = item["apiHeader"]
    prefixes = item["pathPrefixes"]
    parsed = urllib.parse.urlsplit(item["baseUrl"])
    if (
        item["schemaVersion"] != 1
        or not isinstance(service, str)
        or SERVICE_RE.fullmatch(service) is None
        or not isinstance(api_key, str)
        or not 16 <= len(api_key) <= 256
        or any(ord(char) < 33 or ord(char) > 126 for char in api_key)
        or header not in {"X-Api-Key", "X-API-KEY"}
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or not isinstance(prefixes, list)
        or not prefixes
        or len(prefixes) > 8
        or any(
            not isinstance(prefix, str)
            or not prefix.startswith("/api/")
            or not prefix.endswith("/")
            or PATH_RE.fullmatch(prefix) is None
            for prefix in prefixes
        )
        or not isinstance(item["statusPath"], str)
        or PATH_RE.fullmatch(item["statusPath"]) is None
        or not any(item["statusPath"].startswith(prefix) for prefix in prefixes)
    ):
        raise BrokerError("invalid-credential")
    return item


def load_credentials(directory: Path) -> dict[str, dict[str, Any]]:
    if not directory.is_absolute() or not directory.is_dir():
        raise BrokerError("credentials-unavailable")
    result: dict[str, dict[str, Any]] = {}
    entries = sorted(directory.iterdir())
    if not entries or len(entries) > MAX_SERVICES:
        raise BrokerError("credentials-unavailable")
    for path in entries:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_size > 8192:
            raise BrokerError("invalid-credential")
        try:
            value = validate_credential(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BrokerError("invalid-credential") from exc
        service = value["service"]
        if service in result:
            raise BrokerError("invalid-credential")
        result[service] = value
    return result


def validate_json_value(value: Any, *, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise BrokerError("invalid-request")
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        if len(value) > 65536 or "\x00" in value:
            raise BrokerError("invalid-request")
        return
    if isinstance(value, list):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise BrokerError("invalid-request")
        for item in value:
            validate_json_value(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise BrokerError("invalid-request")
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 256 or "\x00" in key:
                raise BrokerError("invalid-request")
            validate_json_value(item, depth=depth + 1)
        return
    raise BrokerError("invalid-request")


def validate_query(value: Any) -> list[tuple[str, str]]:
    if value is None:
        return []
    if not isinstance(value, dict) or len(value) > 64:
        raise BrokerError("invalid-request")
    pairs: list[tuple[str, str]] = []
    for key, raw in value.items():
        if not isinstance(key, str) or not 1 <= len(key) <= 128 or SENSITIVE_KEY_RE.search(key):
            raise BrokerError("invalid-request")
        values = raw if isinstance(raw, list) else [raw]
        if len(values) > 128:
            raise BrokerError("invalid-request")
        for item in values:
            if isinstance(item, bool):
                rendered = "true" if item else "false"
            elif isinstance(item, (str, int, float)) and not isinstance(item, bool):
                rendered = str(item)
            else:
                raise BrokerError("invalid-request")
            if len(rendered) > 2048 or "\x00" in rendered:
                raise BrokerError("invalid-request")
            pairs.append((key, rendered))
    return pairs


def validate_path(path: Any, prefixes: list[str]) -> str:
    if not isinstance(path, str) or PATH_RE.fullmatch(path) is None:
        raise BrokerError("invalid-request")
    parsed = urllib.parse.urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise BrokerError("invalid-request")
    decoded = urllib.parse.unquote(parsed.path)
    if ".." in decoded.split("/") or any(ord(char) < 32 for char in decoded):
        raise BrokerError("invalid-request")
    if not any(path.startswith(prefix) for prefix in prefixes):
        raise BrokerError("path-denied")
    return path


def reject_secret_mutation(value: Any) -> None:
    if isinstance(value, dict):
        if any(
            isinstance(value.get(marker), str) and SENSITIVE_KEY_RE.search(value[marker])
            for marker in ("name", "key")
        ):
            raise BrokerError("secret-mutation-denied")
        for key, item in value.items():
            if SENSITIVE_KEY_RE.search(key):
                raise BrokerError("secret-mutation-denied")
            reject_secret_mutation(item)
    elif isinstance(value, list):
        for item in value:
            reject_secret_mutation(item)


def sanitize_string(value: str) -> str:
    if len(value) > 65536:
        value = value[:65536] + "[TRUNCATED]"
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc and parsed.query:
        pairs = []
        for key, item in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
            pairs.append((key, "[REDACTED]" if SENSITIVE_KEY_RE.search(key) else item))
        value = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(pairs), parsed.fragment)
        )
    return value


def sanitize(value: Any, *, depth: int = 0) -> Any:
    if depth > MAX_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        named_secret = any(
            isinstance(value.get(marker), str) and SENSITIVE_KEY_RE.search(value[marker])
            for marker in ("name", "key")
        )
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_COLLECTION_ITEMS:
                result["[TRUNCATED]"] = True
                break
            rendered_key = str(key)[:256]
            result[rendered_key] = (
                "[REDACTED]"
                if SENSITIVE_KEY_RE.search(rendered_key)
                or (named_secret and rendered_key.lower() in {"value", "defaultvalue"})
                else sanitize(item, depth=depth + 1)
            )
        return result
    if isinstance(value, list):
        return [sanitize(item, depth=depth + 1) for item in value[:MAX_COLLECTION_ITEMS]]
    if isinstance(value, str):
        return sanitize_string(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:1024]


def request_json(
    outbound: urllib.request.Request, *, max_response_bytes: int = MAX_RESPONSE_BYTES
) -> tuple[int, Any]:
    opener = urllib.request.build_opener(NoRedirect())
    try:
        response = opener.open(outbound, timeout=30)
        payload = response.read(max_response_bytes + 1)
        status = response.status
        content_type = response.headers.get_content_type() or ""
    except urllib.error.HTTPError as exc:
        payload = exc.read(max_response_bytes + 1)
        status = exc.code
        content_type = (
            exc.headers.get_content_type() if exc.headers else "application/json"
        ) or ""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise BrokerError("upstream-unavailable") from exc
    if len(payload) > max_response_bytes:
        raise BrokerError("response-too-large")
    if content_type not in {"application/json", "text/json"} and not content_type.endswith(
        "+json"
    ):
        if status in {401, 403}:
            raise BrokerError("upstream-auth-failed")
        raise BrokerError("unsupported-response")
    try:
        parsed_body = json.loads(payload) if payload else None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BrokerError("invalid-upstream-response") from exc
    return status, parsed_body


def outbound_request(
    credential: dict[str, Any],
    method: str,
    path: str,
    body: Any = None,
    query: str = "",
) -> urllib.request.Request:
    data = None
    if body is not None:
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        if len(data) > MAX_REQUEST_BYTES:
            raise BrokerError("invalid-request")
    headers = {
        credential["apiHeader"]: credential["apiKey"],
        "Accept": "application/json",
        "User-Agent": "Hermes-Arr-Broker/1.1",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    return urllib.request.Request(
        credential["baseUrl"].rstrip("/") + path + query,
        data=data,
        headers=headers,
        method=method,
    )


def log_request(service: str, method: str, path: str, status: int) -> None:
    print(
        json.dumps(
            {
                "event": "arr-api-request",
                "service": service,
                "method": method,
                "path": path,
                "httpStatus": status,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        flush=True,
    )


def prowlarr_schema_search(
    credentials: dict[str, dict[str, Any]], request: dict[str, Any]
) -> dict[str, Any]:
    item = require_keys(
        request,
        {"schemaVersion", "action", "query"},
        "invalid-request",
    )
    query = item["query"]
    if (
        item["schemaVersion"] != 1
        or item["action"] != "prowlarr-schema-search"
        or not isinstance(query, str)
        or not 1 <= len(query.strip()) <= 128
        or "\x00" in query
        or "prowlarr" not in credentials
    ):
        raise BrokerError("invalid-request")
    path = "/api/v1/indexer/schema"
    status, body = request_json(
        outbound_request(credentials["prowlarr"], "GET", path),
        max_response_bytes=MAX_SCHEMA_RESPONSE_BYTES,
    )
    if status != 200 or not isinstance(body, list):
        raise BrokerError("invalid-upstream-response")
    needle = query.strip().casefold()
    matches = []
    total = 0
    for schema in body:
        if not isinstance(schema, dict):
            continue
        searchable = [
            schema.get("name"),
            schema.get("implementation"),
            schema.get("configContract"),
            schema.get("infoLink"),
        ]
        fields = schema.get("fields", [])
        if isinstance(fields, list):
            searchable.extend(
                field.get("name")
                for field in fields
                if isinstance(field, dict)
            )
            searchable.extend(
                field.get("label")
                for field in fields
                if isinstance(field, dict)
            )
        if needle not in " ".join(str(value) for value in searchable if value).casefold():
            continue
        total += 1
        if len(matches) < MAX_SCHEMA_MATCHES:
            matches.append(sanitize(schema))
    log_request("prowlarr", "GET", path, status)
    return {
        "schemaVersion": 1,
        "status": "ok",
        "service": "prowlarr",
        "method": "GET",
        "path": path,
        "httpStatus": status,
        "body": {
            "query": query.strip(),
            "totalMatches": total,
            "truncated": total > len(matches),
            "matches": matches,
        },
    }


def inject_indexer_secrets(definition: Any, secrets: Any) -> Any:
    validate_json_value(definition)
    if (
        not isinstance(definition, dict)
        or not isinstance(secrets, dict)
        or not 1 <= len(secrets) <= MAX_INDEXER_SECRETS
    ):
        raise BrokerError("invalid-request")
    normalized: dict[str, str] = {}
    for name, value in secrets.items():
        if (
            not isinstance(name, str)
            or not 1 <= len(name) <= 128
            or SENSITIVE_KEY_RE.search(name) is None
            or not isinstance(value, str)
            or not 1 <= len(value) <= 16384
            or "\x00" in value
        ):
            raise BrokerError("invalid-request")
        normalized[name] = value

    result = copy.deepcopy(definition)
    counts = {name: 0 for name in normalized}

    def visit(value: Any, *, depth: int = 0) -> None:
        if depth > MAX_DEPTH:
            raise BrokerError("invalid-request")
        if isinstance(value, list):
            for child in value:
                visit(child, depth=depth + 1)
            return
        if not isinstance(value, dict):
            return
        field_name = value.get("name")
        named_secret = isinstance(field_name, str) and SENSITIVE_KEY_RE.search(
            field_name
        ) is not None
        if named_secret:
            if "value" not in value or value["value"] not in SECRET_PLACEHOLDERS:
                raise BrokerError("secret-mutation-denied")
            if field_name in normalized:
                value["value"] = normalized[field_name]
                counts[field_name] += 1
            elif value["value"] in {"[REDACTED]", "********"}:
                value["value"] = None
        for key, child in value.items():
            if SENSITIVE_KEY_RE.search(key):
                raise BrokerError("secret-mutation-denied")
            if named_secret and key == "value":
                continue
            visit(child, depth=depth + 1)

    visit(result)
    if any(count != 1 for count in counts.values()):
        raise BrokerError("secret-field-mismatch")
    return result


def prowlarr_indexer_apply(
    credentials: dict[str, dict[str, Any]], request: dict[str, Any]
) -> dict[str, Any]:
    item = require_keys(
        request,
        {"schemaVersion", "action", "method", "path", "definition", "secrets"},
        "invalid-request",
    )
    method = item["method"]
    path = item["path"]
    if not isinstance(method, str) or not isinstance(path, str):
        raise BrokerError("invalid-request")
    valid_path = (
        method == "POST" and path in {"/api/v1/indexer", "/api/v1/indexer/test"}
    ) or (method == "PUT" and INDEXER_UPDATE_PATH_RE.fullmatch(path))
    if (
        item["schemaVersion"] != 1
        or item["action"] != "prowlarr-indexer-apply"
        or "prowlarr" not in credentials
        or not valid_path
    ):
        raise BrokerError("invalid-request")
    body = inject_indexer_secrets(item["definition"], item["secrets"])
    status, response_body = request_json(
        outbound_request(credentials["prowlarr"], method, path, body)
    )
    log_request("prowlarr", method, path, status)
    return {
        "schemaVersion": 1,
        "status": "ok",
        "service": "prowlarr",
        "method": method,
        "path": path,
        "httpStatus": status,
        "body": sanitize(response_body),
    }


def api_request(
    credentials: dict[str, dict[str, Any]], request: dict[str, Any]
) -> dict[str, Any]:
    allowed = {"schemaVersion", "action", "service", "method", "path", "query", "body"}
    if set(request) - allowed or request.get("schemaVersion") != 1 or request.get("action") != "request":
        raise BrokerError("invalid-request")
    service = request.get("service")
    method = request.get("method")
    if service not in credentials or method not in METHODS:
        raise BrokerError("invalid-request")
    credential = credentials[service]
    path = validate_path(request.get("path"), credential["pathPrefixes"])
    pairs = validate_query(request.get("query"))
    body = request.get("body")
    if method == "GET" and "body" in request:
        raise BrokerError("invalid-request")
    data = None
    if "body" in request:
        validate_json_value(body)
        reject_secret_mutation(body)
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        if len(data) > MAX_REQUEST_BYTES:
            raise BrokerError("invalid-request")
    query = urllib.parse.urlencode(pairs, doseq=True)
    outbound = outbound_request(
        credential,
        method,
        path,
        body,
        ("?" + query) if query else "",
    )
    status, parsed_body = request_json(outbound)
    result = {
        "schemaVersion": 1,
        "status": "ok",
        "service": service,
        "method": method,
        "path": path,
        "httpStatus": status,
        "body": sanitize(parsed_body),
    }
    log_request(service, method, path, status)
    return result


def process(credentials: dict[str, dict[str, Any]], value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BrokerError("invalid-request")
    if value == {"schemaVersion": 1, "action": "list"}:
        return {
            "schemaVersion": 1,
            "status": "ok",
            "services": [
                {"name": name, "statusPath": credentials[name]["statusPath"]}
                for name in sorted(credentials)
            ],
        }
    if value.get("action") == "prowlarr-schema-search":
        return prowlarr_schema_search(credentials, value)
    if value.get("action") == "prowlarr-indexer-apply":
        return prowlarr_indexer_apply(credentials, value)
    return api_request(credentials, value)


class ArrHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        peer = self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _, uid, _ = struct.unpack("3i", peer)
        if uid != self.server.allowed_uid:  # type: ignore[attr-defined]
            self.wfile.write(compact(error("peer-denied")))
            return
        raw = self.rfile.readline(MAX_REQUEST_BYTES + 2)
        if not raw.endswith(b"\n") or len(raw) > MAX_REQUEST_BYTES + 1:
            self.wfile.write(compact(error("invalid-request")))
            return
        try:
            value = json.loads(raw)
            result = process(self.server.credentials, value)  # type: ignore[attr-defined]
        except (UnicodeDecodeError, json.JSONDecodeError, BrokerError) as exc:
            code = str(exc) if isinstance(exc, BrokerError) else "invalid-request"
            result = error(code)
        self.wfile.write(compact(result))


class ArrServer(socketserver.UnixStreamServer):
    allow_reuse_address = False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", type=Path, default=Path("/run/hermes-arr-api/broker.sock"))
    parser.add_argument("--allowed-uid", type=int, default=62010)
    args = parser.parse_args()
    credential_raw = os.environ.get("CREDENTIALS_DIRECTORY", "")
    try:
        credentials = load_credentials(Path(credential_raw))
        socket_path = args.socket
        if not socket_path.is_absolute() or not socket_path.parent.is_dir():
            raise BrokerError("socket-unavailable")
        if socket_path.exists() or socket_path.is_symlink():
            info = os.lstat(socket_path)
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                raise BrokerError("unsafe-socket")
            socket_path.unlink()
        with ArrServer(str(socket_path), ArrHandler) as server:
            server.credentials = credentials  # type: ignore[attr-defined]
            server.allowed_uid = args.allowed_uid  # type: ignore[attr-defined]
            os.chmod(socket_path, 0o660)
            signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
            print(
                json.dumps(
                    {"event": "arr-api-broker-ready", "serviceCount": len(credentials)},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                flush=True,
            )
            server.serve_forever(poll_interval=0.5)
    except (OSError, BrokerError) as exc:
        print(f"hermes-arr-api-broker-error:{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
