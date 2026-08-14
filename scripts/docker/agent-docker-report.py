#!/usr/bin/env python3
"""Emit a redacted Docker inventory for an unprivileged consumer.

The process running this script can read the Docker socket, but the report is a
strict allowlist. It never emits environment variables, mounts, ports,
networks, commands, arbitrary labels, logs, or raw Engine API responses.
"""

from __future__ import annotations

import argparse
import grp
import http.client
import json
import os
import re
import socket
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

SCHEMA_VERSION = 2
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_CONTAINERS = 2048
OCI_LABELS = (
    "org.opencontainers.image.version",
    "org.opencontainers.image.revision",
)
COMPOSE_LABELS = (
    "com.docker.compose.project",
    "com.docker.compose.service",
)


class DockerAPIError(RuntimeError):
    """Raised for a failed or invalid Docker Engine API request."""

    def __init__(self, path: str, status: int, message: str) -> None:
        super().__init__(f"Docker API {path} returned {status}: {message}")
        self.path = path
        self.status = status


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.socket_path)
        self.sock = sock


class DockerAPI:
    def __init__(self, socket_path: str, timeout: float = 10.0) -> None:
        self.socket_path = socket_path
        self.timeout = timeout
        version = self.get("/version", versioned=False)
        if not isinstance(version, dict):
            raise DockerAPIError("/version", 200, "expected object")
        api_version = safe_text(version.get("ApiVersion"), 16)
        if not api_version or not re.fullmatch(r"[0-9]+\.[0-9]+", api_version):
            raise DockerAPIError("/version", 200, "invalid ApiVersion")
        self.api_version = api_version
        self.version_payload = version

    def get(self, path: str, *, versioned: bool = True) -> Any:
        request_path = f"/v{self.api_version}{path}" if versioned else path
        connection = UnixHTTPConnection(self.socket_path, self.timeout)
        try:
            connection.request(
                "GET", request_path, headers={"Accept": "application/json"}
            )
            response = connection.getresponse()
            body = response.read(MAX_RESPONSE_BYTES + 1)
        finally:
            connection.close()
        if len(body) > MAX_RESPONSE_BYTES:
            raise DockerAPIError(path, response.status, "response too large")
        if response.status != 200:
            raise DockerAPIError(path, response.status, "request failed")
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise DockerAPIError(path, response.status, "invalid JSON") from exc


def safe_text(value: Any, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = "".join(
        character if character.isprintable() else "?" for character in value
    ).strip()
    if not cleaned:
        return None
    return cleaned[:max_length]


def safe_token(value: Any, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if len(cleaned) > max_length or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._+:/@-]*", cleaned
    ):
        return None
    return cleaned


def safe_identifier(value: Any, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if len(cleaned) > max_length or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]*", cleaned
    ):
        return None
    return cleaned


def normalize_name(names: Any) -> str:
    if not isinstance(names, list) or not names:
        return "unknown"
    raw_name = names[0]
    if not isinstance(raw_name, str):
        return "unknown"
    return safe_identifier(raw_name.lstrip("/"), 128) or "unknown"


def image_update_state(
    api: DockerAPI, image_ref: str | None, running_image_id: str | None
) -> tuple[str, str | None]:
    if not image_ref or not running_image_id:
        return "unknown", None
    if "@sha256:" in image_ref:
        return "pinned-digest", running_image_id
    try:
        tagged_image = api.get(f"/images/{quote(image_ref, safe='')}/json")
    except DockerAPIError as exc:
        if exc.status == 404:
            return "unknown", None
        raise
    if not isinstance(tagged_image, dict):
        raise DockerAPIError("/images/name/json", 200, "expected object")
    tagged_image_id = safe_token(tagged_image.get("Id"), 128)
    if not tagged_image_id:
        return "unknown", None
    state = "current-local" if tagged_image_id == running_image_id else "pending-local"
    return state, tagged_image_id


def container_record(api: DockerAPI, summary: dict[str, Any]) -> dict[str, Any]:
    container_id = safe_token(summary.get("Id"), 128)
    if not container_id:
        raise DockerAPIError("/containers/json", 200, "container missing Id")

    detail = api.get(f"/containers/{quote(container_id, safe='')}/json")
    if not isinstance(detail, dict):
        raise DockerAPIError("/containers/id/json", 200, "expected object")
    config = detail.get("Config") if isinstance(detail.get("Config"), dict) else {}
    state = detail.get("State") if isinstance(detail.get("State"), dict) else {}
    labels = config.get("Labels") if isinstance(config.get("Labels"), dict) else {}
    image_ref = safe_token(config.get("Image") or summary.get("Image"), 512)
    running_image_id = safe_token(detail.get("Image") or summary.get("ImageID"), 128)

    try:
        image = (
            api.get(f"/images/{quote(running_image_id, safe='')}/json")
            if running_image_id
            else {}
        )
    except DockerAPIError as exc:
        if exc.status != 404:
            raise
        # A stopped container can outlive a pruned image. Preserve the
        # container record and mark image metadata unavailable.
        image = {}
    if not isinstance(image, dict):
        raise DockerAPIError("/images/id/json", 200, "expected object")
    image_config = image.get("Config") if isinstance(image.get("Config"), dict) else {}
    image_labels = (
        image_config.get("Labels")
        if isinstance(image_config.get("Labels"), dict)
        else {}
    )
    raw_repo_digests = image.get("RepoDigests")
    if not isinstance(raw_repo_digests, list):
        raw_repo_digests = []
    repo_digests = [
        value
        for value in (safe_token(item, 512) for item in raw_repo_digests)
        if value is not None
    ][:16]
    update_state, tagged_image_id = image_update_state(api, image_ref, running_image_id)

    health = None
    if isinstance(state.get("Health"), dict):
        health = safe_identifier(state["Health"].get("Status"), 32)

    restart_count = detail.get("RestartCount")
    if not isinstance(restart_count, int) or isinstance(restart_count, bool):
        restart_count = None
    exit_code = state.get("ExitCode")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        exit_code = None

    return {
        "containerId": container_id[:12],
        "name": normalize_name(summary.get("Names")),
        "state": safe_identifier(state.get("Status") or summary.get("State"), 32)
        or "unknown",
        "health": health,
        "restartCount": restart_count,
        "exitCode": exit_code,
        "startedAt": safe_token(state.get("StartedAt"), 64),
        "finishedAt": safe_token(state.get("FinishedAt"), 64),
        "compose": {
            "project": safe_identifier(labels.get(COMPOSE_LABELS[0]), 128),
            "service": safe_identifier(labels.get(COMPOSE_LABELS[1]), 128),
        },
        "image": {
            "reference": image_ref,
            "runningId": running_image_id,
            "taggedLocalId": tagged_image_id,
            "repoDigests": repo_digests,
            "created": safe_token(image.get("Created"), 64),
            "version": safe_token(image_labels.get(OCI_LABELS[0]), 128),
            "revision": safe_token(image_labels.get(OCI_LABELS[1]), 128),
            "updateState": update_state,
        },
    }


def build_report(api: DockerAPI, hostname: str) -> dict[str, Any]:
    summaries = api.get("/containers/json?all=1")
    if not isinstance(summaries, list):
        raise DockerAPIError("/containers/json", 200, "expected array")
    if any(not isinstance(item, dict) for item in summaries):
        raise DockerAPIError("/containers/json", 200, "array contained a non-object")
    if len(summaries) > MAX_CONTAINERS:
        raise DockerAPIError("/containers/json", 200, "too many containers")
    containers = [container_record(api, item) for item in summaries]
    containers.sort(key=lambda item: item["name"].casefold())
    version = api.version_payload
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "host": safe_identifier(hostname, 255) or "unknown",
        "updateSemantics": "local-tag-comparison-only",
        "engine": {
            "version": safe_token(version.get("Version"), 64),
            "apiVersion": safe_text(version.get("ApiVersion"), 16),
            "os": safe_identifier(version.get("Os"), 32),
            "arch": safe_identifier(version.get("Arch"), 32),
        },
        "containers": containers,
    }


def write_atomic(path: Path, payload: dict[str, Any], group_name: str | None) -> None:
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise RuntimeError(f"unsafe report directory: {parent}")
    if path.is_symlink():
        raise RuntimeError(f"refusing symlink output: {path}")

    group_id = -1 if not group_name else grp.getgrnam(group_name).gr_gid
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(encoded) > MAX_REPORT_BYTES:
        raise RuntimeError("report too large")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    try:
        os.fchmod(fd, 0o640)
        if group_id != -1:
            os.fchown(fd, 0, group_id)
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        directory_fd = os.open(parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if fd != -1:
            os.close(fd)
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--socket", default="/var/run/docker.sock")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--group")
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    hostname = safe_identifier(args.host, 255)
    if hostname != args.host:
        raise SystemExit("invalid managed host identity")
    api = DockerAPI(args.socket, args.timeout)
    report = build_report(api, hostname)
    write_atomic(args.output, report, args.group)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
