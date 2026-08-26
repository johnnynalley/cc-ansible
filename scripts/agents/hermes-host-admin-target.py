#!/usr/bin/env python3
"""Bounded root-side host administration for Astra's forced SSH identity."""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

MAX_REQUEST = 8192
IDENTITY = Path("/etc/agent-host-admin.json")
HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
UNIT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]{0,126}\.(?:service|timer)$")
PROBE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
PROTECTED = re.compile(
    r"^(?:agent-host-admin|dbus|network|NetworkManager|polkit|ssh|sshd|sudo|"
    r"systemd-|tailscaled|hermes-|openclaw-)",
    re.IGNORECASE,
)
HEALTH_PROBES: dict[str, tuple[frozenset[str], list[str], int]] = {
    "media-stack": (
        frozenset({"docker-vm"}),
        ["/usr/local/sbin/media-stack-health", "--status"],
        20,
    ),
    "nextcloud-local": (
        frozenset({"nextcloud-vm"}),
        [
            "/usr/bin/curl",
            "--silent",
            "--show-error",
            "--output",
            "/dev/null",
            "--write-out",
            "%{http_code}",
            "--max-time",
            "10",
            "http://127.0.0.1:11000/",
        ],
        15,
    ),
    "plex-corrupt-media": (
        frozenset({"jn-t14s-lin", "mercury"}),
        [
            "/usr/local/bin/plex-appliance-corrupt-media-report",
            "--since-hours",
            "168",
        ],
        45,
    ),
    "plex-local": (
        frozenset({"media-vm"}),
        [
            "/usr/bin/curl",
            "--silent",
            "--show-error",
            "--output",
            "/dev/null",
            "--write-out",
            "%{http_code}",
            "--max-time",
            "10",
            "http://127.0.0.1:32400/",
        ],
        15,
    ),
    "storage-status": (
        frozenset({"ts440"}),
        ["/usr/local/bin/storage-status"],
        30,
    ),
    "stream-relay": (
        frozenset({"media-vm"}),
        ["/usr/local/sbin/stream-relay-health", "--no-alert"],
        45,
    ),
}


class AdminError(RuntimeError):
    """Expected fixed-code request failure."""


def run(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            text=True,
            timeout=timeout,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AdminError("operation-failed") from exc


def error(code: str) -> dict[str, Any]:
    return {"schemaVersion": 1, "status": "error", "code": code}


def canonical_host() -> str:
    try:
        info = os.lstat(IDENTITY)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o444 or info.st_size > 1024:
            raise AdminError("identity-invalid")
        value = json.loads(IDENTITY.read_text(encoding="ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdminError("identity-invalid") from exc
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "host"} or value.get("schemaVersion") != 1 or not isinstance(value.get("host"), str) or HOST.fullmatch(value["host"]) is None:
        raise AdminError("identity-invalid")
    return value["host"]


def systemctl_state(unit: str) -> dict[str, str]:
    result = run(
        [
            "/usr/bin/systemctl",
            "show",
            unit,
            "--property=LoadState,ActiveState,SubState",
            "--value",
            "--no-pager",
        ]
    )
    values = result.stdout.splitlines()
    if result.returncode != 0 or len(values) != 3:
        raise AdminError("service-unavailable")
    load, active, sub = values
    if load == "not-found":
        raise AdminError("service-not-found")
    return {"loadState": load, "activeState": active, "subState": sub}


def os_release() -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key in {"ID", "VERSION_ID"}:
                values[key] = value.strip().strip('"')[:64]
    except OSError:
        pass
    return {"id": values.get("ID", "unknown"), "version": values.get("VERSION_ID", "unknown")}


def status_body() -> dict[str, Any]:
    update = systemctl_state("auto-updates.service")
    return {
        "hostname": socket.gethostname()[:128],
        "os": os_release(),
        "uptimeSeconds": int(float(Path("/proc/uptime").read_text().split()[0])),
        "rebootRequired": Path("/run/reboot-required").exists(),
        "updateService": update,
    }


def validate_unit(request: dict[str, Any]) -> str:
    unit = request.get("service")
    if not isinstance(unit, str) or UNIT.fullmatch(unit) is None:
        raise AdminError("invalid-service")
    if PROTECTED.match(unit):
        raise AdminError("protected-service")
    return unit


def _mount_fstype(path: str) -> str:
    result = run(
        [
            "/usr/bin/findmnt",
            "--noheadings",
            "--output",
            "FSTYPE",
            "--target",
            path,
        ],
        timeout=10,
    )
    fstype = result.stdout.strip()
    if result.returncode != 0 or not fstype:
        raise AdminError("storage-view-unavailable")
    return fstype


def _probe_directory(path: str, *, require_entry: bool) -> None:
    result = run(
        [
            "/usr/bin/find",
            path,
            "-mindepth",
            "1",
            "-maxdepth",
            "1",
            "-print",
            "-quit",
        ],
        timeout=10,
    )
    if result.returncode != 0 or (require_entry and not result.stdout.strip()):
        raise AdminError("storage-view-unavailable")


def media_storage_view_probe() -> dict[str, Any]:
    host = canonical_host()
    if host == "ts440":
        media_fstype = _mount_fstype("/srv/media")
        if media_fstype != "fuse.mergerfs":
            raise AdminError("storage-view-unhealthy")
        _probe_directory("/srv/media/plex/Movies", require_entry=True)
        output = [
            "OK: media storage view healthy",
            f"/srv/media={media_fstype}",
            "/srv/media/plex/Movies=readable-nonempty",
        ]
    elif host == "docker-vm":
        media_fstype = _mount_fstype("/srv/media")
        incomplete_fstype = _mount_fstype("/srv/incomplete_downloads")
        if media_fstype not in {"nfs", "nfs4"} or incomplete_fstype not in {
            "nfs",
            "nfs4",
        }:
            raise AdminError("storage-view-unhealthy")
        _probe_directory("/srv/media/plex/Movies", require_entry=True)
        _probe_directory("/srv/incomplete_downloads", require_entry=False)
        output = [
            "OK: media storage view healthy",
            f"/srv/media={media_fstype}",
            f"/srv/incomplete_downloads={incomplete_fstype}",
            "/srv/media/plex/Movies=readable-nonempty",
            "/srv/incomplete_downloads=readable",
        ]
    else:
        raise AdminError("probe-unavailable")
    return {
        "probe": "media-storage-view",
        "exitCode": 0,
        "output": output,
        "truncated": False,
    }


def health_probe(request: dict[str, Any]) -> dict[str, Any]:
    probe = request.get("probe")
    if not isinstance(probe, str) or PROBE.fullmatch(probe) is None:
        raise AdminError("invalid-probe")
    if probe == "media-storage-view":
        return media_storage_view_probe()
    spec = HEALTH_PROBES.get(probe)
    if spec is None:
        raise AdminError("invalid-probe")
    allowed_hosts, command, timeout = spec
    if canonical_host() not in allowed_hosts:
        raise AdminError("probe-unavailable")
    if not Path(command[0]).is_file():
        raise AdminError("probe-unavailable")
    result = run(command, timeout=timeout)
    output = []
    for raw in result.stdout.splitlines()[:256]:
        line = "".join(character for character in raw if character == "\t" or ord(character) >= 32)
        output.append(line[:2048])
    return {
        "probe": probe,
        "exitCode": result.returncode,
        "output": output,
        "truncated": len(result.stdout.splitlines()) > 256,
    }


def update() -> dict[str, Any]:
    current = systemctl_state("auto-updates.service")
    if current["activeState"] == "active":
        return {"outcome": "already-running", "service": current}
    result = run(
        [
            "/usr/bin/systemctl",
            "start",
            "--no-block",
            "auto-updates.service",
        ]
    )
    if result.returncode != 0:
        raise AdminError("update-start-failed")
    return {"outcome": "accepted", "service": systemctl_state("auto-updates.service")}


def proxmox_reboot_guard() -> None:
    if shutil.which("pvecm") is None:
        return
    result = run(["/usr/bin/pvecm", "status"])
    if result.returncode != 0:
        raise AdminError("quorum-unavailable")
    fields: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().split()[0]
    try:
        total = int(fields["Total votes"])
        quorum = int(fields["Quorum"])
    except (KeyError, ValueError) as exc:
        raise AdminError("quorum-invalid") from exc
    if fields.get("Quorate") != "Yes" or total - 1 < quorum:
        raise AdminError("quorum-blocked")

    lock = Path("/etc/pve/priv/auto-updates-reboot.lock.d")
    now = int(time.time())
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError:
        state = lock / "state"
        created = 0
        try:
            for line in state.read_text(encoding="ascii").splitlines():
                if line.startswith("created_at="):
                    created = int(line.split("=", 1)[1])
        except (OSError, ValueError):
            pass
        if created <= 0 or now - created <= 1800:
            raise AdminError("reboot-slot-busy")
        shutil.rmtree(lock)
        try:
            lock.mkdir(mode=0o700)
        except OSError as exc:
            raise AdminError("reboot-slot-busy") from exc
    (lock / "state").write_text(
        f"host={socket.gethostname()}\ncreated_at={now}\nmax_age=1800\n",
        encoding="ascii",
    )


def reboot() -> dict[str, Any]:
    update_state = systemctl_state("auto-updates.service")
    if update_state["activeState"] == "active":
        raise AdminError("update-in-progress")
    proxmox_reboot_guard()
    result = run(
        [
            "/usr/sbin/shutdown",
            "-r",
            "+1",
            "Hermes approved host administration reboot",
        ]
    )
    if result.returncode != 0:
        raise AdminError("reboot-schedule-failed")
    return {"outcome": "scheduled", "delaySeconds": 60}


def service_action(action: str, request: dict[str, Any]) -> dict[str, Any]:
    unit = validate_unit(request)
    if action == "service-status":
        return {"service": unit, **systemctl_state(unit)}
    state = {
        "service-start": "start",
        "service-stop": "stop",
        "service-restart": "restart",
    }[action]
    result = run(["/usr/bin/systemctl", state, unit], timeout=45)
    if result.returncode != 0:
        raise AdminError("service-operation-failed")
    return {"service": unit, "outcome": state, **systemctl_state(unit)}


def handle(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise AdminError("invalid-request")
    allowed = {"schemaVersion", "action", "service", "probe"}
    if set(request) - allowed or request.get("schemaVersion") != 1:
        raise AdminError("invalid-request")
    action = request.get("action")
    actions = {
        "status",
        "health",
        "update",
        "reboot",
        "service-status",
        "service-start",
        "service-stop",
        "service-restart",
    }
    if action not in actions:
        raise AdminError("invalid-action")
    if action.startswith("service-"):
        body = service_action(action, request)
    elif action == "health":
        if "service" in request:
            raise AdminError("invalid-request")
        body = health_probe(request)
    else:
        if "service" in request or "probe" in request:
            raise AdminError("invalid-request")
        body = status_body() if action == "status" else update() if action == "update" else reboot()
    return {
        "schemaVersion": 1,
        "status": "ok",
        "host": canonical_host(),
        "action": action,
        "body": body,
    }


def main() -> int:
    if os.geteuid() != 0 or len(sys.argv) != 1:
        print(json.dumps(error("authority-denied"), sort_keys=True))
        return 1
    raw = sys.stdin.buffer.read(MAX_REQUEST + 1)
    try:
        if not raw or len(raw) > MAX_REQUEST:
            raise AdminError("invalid-request")
        request = json.loads(raw)
        response = handle(request)
    except (UnicodeDecodeError, json.JSONDecodeError, AdminError) as exc:
        code = str(exc) if isinstance(exc, AdminError) else "invalid-request"
        response = error(code)
    print(json.dumps(response, sort_keys=True, separators=(",", ":")))
    return 0 if response["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
