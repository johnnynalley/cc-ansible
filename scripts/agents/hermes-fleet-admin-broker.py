#!/usr/bin/env python3
"""Hardened owner-only Astra fleet workspace/runtime broker."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import pwd
import re
import shutil
import socket
import stat
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

SCHEMA_VERSION = 1
MAX_REQUEST = 192 * 1024
MAX_RESPONSE = 320 * 1024
MAX_TEXT = 128 * 1024
MAX_LIST = 256
MAX_SCAN = 20_000
SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
NONCE_RE = re.compile(r"^[a-f0-9]{32}$")
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
SENSITIVE = re.compile(
    r"(?:^|[._-])(env|auth|credentials?|secrets?|tokens?|passwords?|cookies?)(?:$|[._-])",
    re.I,
)
SENSITIVE_PREFIXES = ("state.db", "lcm.db", "mem0.", "auth.", "credentials.", "cookies.")
SECRET_ASSIGNMENT = re.compile(
    r"(?i)(password|token|secret|api[_-]?key|authorization)(\s*[:=]\s*)(\S+)"
)
DISCORD_TOKEN = re.compile(r"\b[A-Za-z0-9_-]{20,30}\.[A-Za-z0-9_-]{5,8}\.[A-Za-z0-9_-]{20,50}\b")
BOOTSTRAP_FILES = {"AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "HEARTBEAT.md", "MEMORY.md"}
MUTATIONS = {"write", "delete", "restart"}
ROLLBACK_MOUNT = Path("/srv/live-rollbacks")

TARGETS = {
    "astra": {
        "user": "hermes-astra",
        "group": "hermes-astra",
        "unit": "hermes-gateway-astra.service",
        "account": Path("/var/lib/hermes/astra"),
        "profile": Path("/var/lib/hermes/astra/.hermes/profiles/astra"),
        "workspace": Path("/var/lib/hermes/profile-data/astra/writable"),
        "config": Path("/var/lib/hermes/astra/.hermes/profiles/astra/config.yaml"),
        "managed": Path("/etc/hermes/astra/config.yaml"),
        "environment": Path("/etc/hermes/astra/.env"),
    },
    "dubble": {
        "user": "hermes-dubble",
        "group": "hermes-dubble",
        "unit": "hermes-gateway-dubble.service",
        "account": Path("/var/lib/hermes/dubble"),
        "profile": Path("/var/lib/hermes/dubble/.hermes/profiles/dubble"),
        "workspace": Path("/var/lib/hermes/profile-data/dubble/writable"),
        "config": Path("/var/lib/hermes/dubble/.hermes/profiles/dubble/config.yaml"),
        "managed": Path("/etc/hermes/dubble/config.yaml"),
        "environment": Path("/etc/hermes/dubble/.env"),
    },
    "rigel": {
        "user": "hermes-rigel",
        "group": "hermes-rigel",
        "unit": "hermes-gateway-rigel.service",
        "account": Path("/var/lib/hermes/rigel"),
        "profile": Path("/var/lib/hermes/rigel/.hermes/profiles/rigel"),
        "workspace": Path("/var/lib/hermes/profile-data/rigel/writable"),
        "config": Path("/var/lib/hermes/rigel/.hermes/profiles/rigel/config.yaml"),
        "managed": Path("/etc/hermes/rigel/config.yaml"),
        "environment": Path("/etc/hermes/private/environments/rigel.env"),
    },
}


class BrokerError(RuntimeError):
    pass


def canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def safe_info(path: Path) -> os.stat_result:
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        raise BrokerError("symlink-denied")
    return info


def profile(target: str) -> dict[str, Any]:
    value = TARGETS.get(target)
    if value is None:
        raise BrokerError("unknown-target")
    return value


def sensitive_name(name: str) -> bool:
    lower = name.lower()
    return lower.startswith(SENSITIVE_PREFIXES) or SENSITIVE.search(name) is not None


def relative_path(raw: Any, *, allow_root: bool = False) -> PurePosixPath:
    if not isinstance(raw, str) or len(raw) > 512 or "\x00" in raw or "\\" in raw:
        raise BrokerError("invalid-path")
    if allow_root and raw in {"", "."}:
        return PurePosixPath(".")
    if not raw:
        raise BrokerError("invalid-path")
    value = PurePosixPath(raw)
    if value.is_absolute() or any(part in {"", ".", ".."} for part in value.parts):
        raise BrokerError("invalid-path")
    if any(sensitive_name(part) for part in value.parts):
        raise BrokerError("sensitive-path-denied")
    return value


def root_path(target: str, root: str, raw: Any, *, mutate: bool, allow_root: bool = False) -> Path:
    item = profile(target)
    relative = relative_path(raw, allow_root=allow_root)
    if root == "workspace":
        base = item["workspace"]
    elif root == "bootstrap":
        base = item["profile"]
        if relative.parts and (len(relative.parts) != 1 or relative.name not in BOOTSTRAP_FILES):
            raise BrokerError("path-not-allowed")
    elif root == "skills":
        base = item["profile"] / "skills"
        if mutate and relative.parts and relative.parts[0] == "self-evolution":
            raise BrokerError("shared-skill-managed-by-astra")
    elif root == "schedules":
        base = item["profile"] / "cron"
        if relative.parts and relative != PurePosixPath("jobs.json"):
            raise BrokerError("path-not-allowed")
    elif root == "config":
        base = item["config"].parent
        if relative.parts and relative != PurePosixPath("config.yaml"):
            raise BrokerError("path-not-allowed")
    else:
        raise BrokerError("unknown-root")
    base_info = safe_info(base)
    if not stat.S_ISDIR(base_info.st_mode):
        raise BrokerError("root-unavailable")
    result = base.joinpath(*relative.parts)
    current = base
    for part in relative.parts[:-1]:
        current = current / part
        if current.exists() or current.is_symlink():
            info = safe_info(current)
            if not stat.S_ISDIR(info.st_mode):
                raise BrokerError("unsafe-parent")
    return result


def current_sha(path: Path) -> str:
    if not path.exists() and not path.is_symlink():
        return "absent"
    info = safe_info(path)
    if not stat.S_ISREG(info.st_mode):
        raise BrokerError("not-a-file")
    return digest(path)


def require_expected(path: Path, expected: Any) -> str:
    actual = current_sha(path)
    if expected is not None and expected != actual:
        raise BrokerError("concurrent-change")
    return actual


def file_metadata(path: Path, base: Path) -> dict[str, Any]:
    info = safe_info(path)
    kind = "directory" if stat.S_ISDIR(info.st_mode) else "file" if stat.S_ISREG(info.st_mode) else "other"
    value: dict[str, Any] = {
        "path": path.relative_to(base).as_posix(),
        "kind": kind,
        "size": info.st_size,
        "mtime": int(info.st_mtime),
    }
    if kind == "file" and info.st_size <= MAX_TEXT:
        value["sha256"] = digest(path)
    return value


def inspect_tree(base: Path) -> dict[str, int]:
    files = directories = total = scanned = 0
    latest = 0
    for root, names, filenames in os.walk(base, followlinks=False):
        names[:] = [name for name in names if not sensitive_name(name) and not (Path(root) / name).is_symlink()]
        directories += len(names)
        for name in filenames:
            scanned += 1
            if scanned > MAX_SCAN:
                raise BrokerError("inventory-too-large")
            path = Path(root) / name
            if sensitive_name(name) or path.is_symlink():
                continue
            try:
                info = safe_info(path)
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode):
                files += 1
                total += info.st_size
                latest = max(latest, int(info.st_mtime))
    return {"files": files, "directories": directories, "bytes": total, "latestMtime": latest}


def service_state(unit: str) -> dict[str, Any]:
    result = subprocess.run(
        ["/usr/bin/systemctl", "show", unit, "--property=ActiveState", "--property=MainPID", "--property=NRestarts"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise BrokerError("service-unavailable")
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    return {
        "active": values.get("ActiveState") == "active",
        "pid": int(values.get("MainPID") or 0),
        "restarts": int(values.get("NRestarts") or 0),
    }


def service_logs(unit: str) -> list[str]:
    result = subprocess.run(
        ["/usr/bin/journalctl", "--unit", unit, "--lines", "200", "--no-pager", "--output", "short-iso"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        raise BrokerError("logs-unavailable")
    lines = result.stdout.splitlines()[-200:]
    redacted = []
    for line in lines:
        line = SECRET_ASSIGNMENT.sub(r"\1\2[REDACTED]", line)
        line = DISCORD_TOKEN.sub("[REDACTED_DISCORD_TOKEN]", line)
        redacted.append(line[:2000])
    return redacted


def audit(path: Path, request: dict[str, Any], status: str, code: str | None = None, backup: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "target": request.get("target"),
        "operation": request.get("operation"),
        "root": request.get("root"),
        "path": request.get("path"),
        "sessionHash": hashlib.sha256(str(request.get("sessionId", "")).encode()).hexdigest()[:20],
        "status": status,
    }
    if code:
        event["code"] = code
    if backup:
        event["backup"] = backup
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        output.flush()
        os.fsync(output.fileno())
    os.chmod(path, 0o600)


def backup_file(backup_root: Path, request: dict[str, Any], path: Path, actual: str) -> Path:
    try:
        backup_root.relative_to(ROLLBACK_MOUNT)
    except ValueError as exc:
        raise BrokerError("rollback-root-invalid") from exc
    if not os.path.ismount(ROLLBACK_MOUNT):
        raise BrokerError("rollback-mount-unavailable")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = backup_root / f"{stamp}-{request['target']}-{request['operation']}-{request['nonce'][:8]}"
    root.mkdir(parents=True, mode=0o700)
    manifest = {
        "schemaVersion": 1,
        "target": request["target"],
        "operation": request["operation"],
        "root": request.get("root"),
        "path": request.get("path"),
        "priorSha256": actual,
    }
    if actual != "absent":
        destination = root / "prior-file"
        with path.open("rb") as source, destination.open("wb") as output:
            shutil.copyfileobj(source, output, 1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        if digest(destination) != actual:
            raise BrokerError("backup-hash-mismatch")
        os.chmod(destination, 0o600)
    manifest_path = root / "manifest.json"
    with manifest_path.open("w", encoding="utf-8") as output:
        output.write(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        output.flush()
        os.fsync(output.fileno())
    os.chmod(manifest_path, 0o600)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return root


def validate_content(root: str, relative: str, content: str) -> None:
    if "\x00" in content or len(content.encode("utf-8")) > MAX_TEXT:
        raise BrokerError("invalid-content")
    if root == "config":
        value = yaml.safe_load(content)
        if not isinstance(value, dict):
            raise BrokerError("invalid-config")
        def walk(item: Any) -> None:
            if isinstance(item, dict):
                for key, child in item.items():
                    if not isinstance(key, str) or re.search(r"password|secret|token|api.?key|credential", key, re.I):
                        raise BrokerError("secret-config-denied")
                    walk(child)
            elif isinstance(item, list):
                for child in item:
                    walk(child)
        walk(value)
    elif root == "schedules":
        value = json.loads(content)
        if not isinstance(value, (dict, list)):
            raise BrokerError("invalid-schedule")
    elif root in {"bootstrap", "skills"} and not content.strip():
        raise BrokerError("empty-runtime-file")
    if root == "skills" and relative.endswith("SKILL.md") and "---" not in content[:512]:
        raise BrokerError("invalid-skill")


def validate_request(request: dict[str, Any]) -> None:
    common = {"schemaVersion", "sessionId", "timestamp", "nonce", "target", "operation"}
    file_fields = {"root", "path"}
    operation = request.get("operation")
    if (
        request.get("schemaVersion") != SCHEMA_VERSION
        or request.get("target") not in TARGETS
        or operation not in {"inspect", "logs", "list", "read", "write", "delete", "validate", "restart"}
    ):
        raise BrokerError("invalid-request")
    expected = set(common)
    if operation in {"list", "read", "write", "delete"}:
        expected |= file_fields
        if request.get("root") not in {"workspace", "bootstrap", "skills", "schedules", "config"}:
            raise BrokerError("invalid-request")
        relative_path(request.get("path"), allow_root=operation == "list")
    if operation == "write":
        expected.add("content")
        if not isinstance(request.get("content"), str):
            raise BrokerError("invalid-request")
    if operation in {"write", "delete"}:
        expected.add("expectedSha256")
        value = request.get("expectedSha256")
        if value != "absent" and (not isinstance(value, str) or SHA_RE.fullmatch(value) is None):
            raise BrokerError("invalid-request")
    if set(request) != expected:
        raise BrokerError("invalid-request")


def ensure_parent(path: Path, target: dict[str, Any], root: str) -> None:
    uid = pwd.getpwnam(target["user"]).pw_uid
    gid = pwd.getpwnam(target["user"]).pw_gid
    missing: list[Path] = []
    current = path.parent
    while not current.exists():
        missing.append(current)
        current = current.parent
    info = safe_info(current)
    if not stat.S_ISDIR(info.st_mode):
        raise BrokerError("unsafe-parent")
    if root not in {"workspace", "skills"} and missing:
        raise BrokerError("parent-missing")
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
        os.chown(directory, uid, gid)


def atomic_write(path: Path, content: str, target: dict[str, Any], root: str) -> None:
    ensure_parent(path, target, root)
    uid = pwd.getpwnam(target["user"]).pw_uid
    gid = pwd.getpwnam(target["user"]).pw_gid
    mode = 0o600
    owner = uid
    group = gid
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chown(temp_path, owner, group)
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def validate_runtime(target_name: str) -> dict[str, Any]:
    target = profile(target_name)
    config = target["config"]
    info = safe_info(config)
    if not stat.S_ISREG(info.st_mode) or info.st_size > 512 * 1024:
        raise BrokerError("invalid-config")
    value = yaml.safe_load(config.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BrokerError("invalid-config")
    command = [
        "/usr/bin/systemd-run", "--quiet", "--wait", "--collect", "--pipe",
        "--service-type=exec", f"--uid={target['user']}", f"--gid={target['group']}",
        "--property=SupplementaryGroups=hermes-runtime-readers",
        f"--property=EnvironmentFile={target['environment']}",
        f"--setenv=HOME={target['account']}", f"--setenv=HERMES_HOME={target['profile']}",
        f"--setenv=HERMES_MANAGED_DIR={target['managed'].parent}", "/usr/local/bin/hermes", "config", "check",
    ]
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45, check=False)
    if result.returncode != 0:
        raise BrokerError("config-check-failed")
    state = service_state(target["unit"])
    return {"configSha256": digest(config), "service": state}


def planned_restart(target_name: str) -> dict[str, Any]:
    target = profile(target_name)
    validated = validate_runtime(target_name)
    pid = validated["service"]["pid"]
    if pid <= 0:
        raise BrokerError("service-inactive")
    marker = subprocess.run(
        [
            "/usr/sbin/runuser", "--user", target["user"], "--", "/usr/bin/env",
            f"HOME={target['account']}", f"HERMES_HOME={target['profile']}",
            f"HERMES_MANAGED_DIR={target['config'].parent}",
            "/usr/local/lib/hermes-agent/venv/bin/python", "-c",
            "import sys; from gateway.status import write_planned_stop_marker; raise SystemExit(0 if write_planned_stop_marker(int(sys.argv[1])) else 1)",
            "1",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=20,
        check=False,
    )
    if marker.returncode != 0:
        raise BrokerError("planned-stop-marker-failed")
    result = subprocess.run(["/usr/bin/systemctl", "restart", target["unit"]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90, check=False)
    if result.returncode != 0:
        subprocess.run(
            ["/usr/bin/systemctl", "start", target["unit"]],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=90,
            check=False,
        )
        raise BrokerError("restart-failed")
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        state = service_state(target["unit"])
        if state["active"] and state["pid"] > 0 and state["pid"] != pid:
            return {"priorPid": pid, "service": state}
        time.sleep(1)
    subprocess.run(
        ["/usr/bin/systemctl", "start", target["unit"]],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=90,
        check=False,
    )
    raise BrokerError("restart-readiness-timeout")


def process(request: dict[str, Any], backup_root: Path) -> tuple[dict[str, Any], str | None]:
    target_name, operation = request.get("target"), request.get("operation")
    target = profile(target_name)
    if operation == "inspect":
        workspace_info = safe_info(target["workspace"])
        config_info = safe_info(target["config"])
        if not stat.S_ISDIR(workspace_info.st_mode) or not stat.S_ISREG(config_info.st_mode):
            raise BrokerError("runtime-shape-invalid")
        bootstrap = {}
        for name in sorted(BOOTSTRAP_FILES):
            path = target["profile"] / name
            if path.is_file() and not path.is_symlink():
                bootstrap[name] = digest(path)
        return {
            "schemaVersion": 1,
            "status": "ok",
            "target": target_name,
            "operation": operation,
            "service": service_state(target["unit"]),
            "workspace": inspect_tree(target["workspace"]),
            "bootstrap": bootstrap,
            "configSha256": digest(target["config"]),
        }, None
    if operation == "logs":
        return {
            "schemaVersion": 1,
            "status": "ok",
            "target": target_name,
            "operation": operation,
            "lines": service_logs(target["unit"]),
        }, None
    if operation == "validate":
        return {"schemaVersion": 1, "status": "ok", "target": target_name, "operation": operation, **validate_runtime(target_name)}, None
    if operation == "restart":
        backup = backup_file(backup_root, request, target["config"], digest(target["config"]))
        return {"schemaVersion": 1, "status": "ok", "target": target_name, "operation": operation, **planned_restart(target_name)}, str(backup)

    root, raw_path = request.get("root"), request.get("path")
    path = root_path(
        target_name,
        root,
        raw_path,
        mutate=operation in MUTATIONS,
        allow_root=operation == "list",
    )
    if root == "workspace":
        base = target["workspace"]
    elif root == "bootstrap":
        base = target["profile"]
    elif root == "skills":
        base = target["profile"] / "skills"
    elif root == "schedules":
        base = target["profile"] / "cron"
    else:
        base = target["config"].parent

    if operation == "list":
        info = safe_info(path)
        if not stat.S_ISDIR(info.st_mode):
            raise BrokerError("not-a-directory")
        entries = []
        allowed_names = None
        if root == "bootstrap":
            allowed_names = BOOTSTRAP_FILES
        elif root == "schedules":
            allowed_names = {"jobs.json"}
        elif root == "config":
            allowed_names = {"config.yaml"}
        for child in sorted(path.iterdir(), key=lambda item: item.name):
            if len(entries) >= MAX_LIST:
                raise BrokerError("list-too-large")
            if (allowed_names is not None and child.name not in allowed_names) or sensitive_name(child.name) or child.is_symlink():
                continue
            entries.append(file_metadata(child, base))
        return {"schemaVersion": 1, "status": "ok", "target": target_name, "operation": operation, "root": root, "path": raw_path, "entries": entries}, None
    if operation == "read":
        info = safe_info(path)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_TEXT:
            raise BrokerError("file-not-readable")
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise BrokerError("non-text-file") from exc
        return {"schemaVersion": 1, "status": "ok", "target": target_name, "operation": operation, "root": root, "path": raw_path, "sha256": digest(path), "content": content}, None

    actual = require_expected(path, request.get("expectedSha256"))
    backup = backup_file(backup_root, request, path, actual)
    if operation == "write":
        content = request["content"]
        validate_content(root, raw_path, content)
        atomic_write(path, content, target, root)
        if root == "config":
            try:
                validate_runtime(target_name)
            except Exception:
                prior = backup / "prior-file"
                if actual == "absent":
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, prior.read_text(encoding="utf-8"), target, root)
                raise
        return {"schemaVersion": 1, "status": "ok", "target": target_name, "operation": operation, "root": root, "path": raw_path, "priorSha256": actual, "sha256": digest(path), "backup": str(backup)}, str(backup)
    if operation == "delete":
        if root not in {"workspace", "skills"}:
            raise BrokerError("delete-not-allowed")
        if actual == "absent":
            raise BrokerError("file-missing")
        path.unlink()
        return {"schemaVersion": 1, "status": "ok", "target": target_name, "operation": operation, "root": root, "path": raw_path, "priorSha256": actual, "backup": str(backup)}, str(backup)
    raise BrokerError("invalid-operation")


class Server:
    def __init__(self, socket_path: Path, socket_gid: int, key: bytes, backup_root: Path, audit_log: Path) -> None:
        self.socket_path = socket_path
        self.socket_gid = socket_gid
        self.key = key
        self.backup_root = backup_root
        self.audit_log = audit_log
        self.nonces: dict[str, int] = {}

    def authenticate(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise BrokerError("invalid-request")
        signature = value.pop("signature", None)
        timestamp, nonce, session_id = value.get("timestamp"), value.get("nonce"), value.get("sessionId")
        if (
            value.get("schemaVersion") != SCHEMA_VERSION
            or not isinstance(signature, str)
            or SHA_RE.fullmatch(signature) is None
            or not isinstance(timestamp, int)
            or abs(int(time.time()) - timestamp) > 300
            or not isinstance(nonce, str)
            or NONCE_RE.fullmatch(nonce) is None
            or not isinstance(session_id, str)
            or SESSION_RE.fullmatch(session_id) is None
        ):
            raise BrokerError("authentication-failed")
        expected = hmac.new(self.key, canonical(value), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise BrokerError("authentication-failed")
        cutoff = int(time.time()) - 600
        self.nonces = {item: seen for item, seen in self.nonces.items() if seen >= cutoff}
        if nonce in self.nonces:
            raise BrokerError("replay-denied")
        self.nonces[nonce] = timestamp
        validate_request(value)
        return value

    def handle(self, connection: socket.socket) -> None:
        raw = connection.makefile("rb").readline(MAX_REQUEST + 1)
        request: dict[str, Any] = {}
        backup = None
        try:
            if not raw or len(raw) > MAX_REQUEST or not raw.endswith(b"\n"):
                raise BrokerError("invalid-request")
            request = self.authenticate(json.loads(raw))
            response, backup = process(request, self.backup_root)
            audit(self.audit_log, request, "ok", backup=backup)
        except (BrokerError, OSError, ValueError, UnicodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
            code = str(exc) if isinstance(exc, BrokerError) and re.fullmatch(r"[a-z0-9-]+", str(exc)) else "operation-failed"
            audit(self.audit_log, request, "error", code=code, backup=backup)
            response = {"schemaVersion": 1, "status": "error", "code": code}
        payload = canonical(response) + b"\n"
        if len(payload) > MAX_RESPONSE:
            payload = canonical({"schemaVersion": 1, "status": "error", "code": "response-too-large"}) + b"\n"
        connection.sendall(payload)

    def run(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        self.socket_path.unlink(missing_ok=True)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(self.socket_path))
            os.chown(self.socket_path, 0, self.socket_gid)
            os.chmod(self.socket_path, 0o660)
            listener.listen(16)
            while True:
                connection, _ = listener.accept()
                with connection:
                    self.handle(connection)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--socket-group", required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--audit-log", type=Path, required=True)
    parser.add_argument("--credential-name", default="fleet-admin-key")
    args = parser.parse_args()
    credential_dir = Path(os.environ.get("CREDENTIALS_DIRECTORY", ""))
    key_path = credential_dir / args.credential_name
    info = safe_info(key_path)
    if not stat.S_ISREG(info.st_mode) or info.st_size < 32 or info.st_size > 256:
        raise SystemExit("invalid-credential")
    key = key_path.read_text(encoding="ascii").strip().encode("ascii")
    group = __import__("grp").getgrnam(args.socket_group)
    Server(args.socket, group.gr_gid, key, args.backup_root, args.audit_log).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
