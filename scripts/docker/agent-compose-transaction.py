#!/usr/bin/env python3
"""Typed, rollback-backed Docker Compose transactions for Astra."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any
from ipaddress import ip_address, ip_network

MAX_REQUEST = 128 * 1024
MAX_RESPONSE = 256 * 1024
ROOT = Path("/opt/hermes-managed-stacks")
BACKUPS = Path("/var/backups/agent-compose")
IDENTITY = Path("/etc/agent-compose.json")
LOCK = Path("/run/lock/agent-compose.lock")
AUDIT = Path("/var/log/agent-compose-audit.jsonl")
RUNTIME = Path("/run")
NAME = re.compile(r"^[a-z][a-z0-9-]{0,47}$")
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
PATH = re.compile(r"^/(?:[A-Za-z0-9_.-]+/?){1,16}$")
IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@+-]{0,254}$")
SENSITIVE = re.compile(
    r"api.?key|authorization|cookie|credential|pass(word)?|private.?key|secret|token",
    re.IGNORECASE,
)
ALLOWED_REGISTRIES = {
    "docker.io",
    "ghcr.io",
    "lscr.io",
    "mcr.microsoft.com",
    "quay.io",
    "registry.k8s.io",
}
LAN = ip_network("192.168.1.0/24")


class TransactionError(RuntimeError):
    """Expected fixed-code transaction failure."""


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def root_directory(path: Path, *, create: bool = False) -> bool:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        if not create:
            return False
        path.mkdir(mode=0o700)
        info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
        raise TransactionError("state-root-invalid")
    return True


def identity() -> dict[str, str]:
    try:
        info = os.lstat(IDENTITY)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o444 or info.st_size > 2048:
            raise TransactionError("identity-invalid")
        value = json.loads(IDENTITY.read_text(encoding="ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransactionError("identity-invalid") from exc
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "host", "lanAddress"} or value.get("schemaVersion") != 1 or not isinstance(value.get("host"), str) or NAME.fullmatch(value["host"]) is None or not isinstance(value.get("lanAddress"), str):
        raise TransactionError("identity-invalid")
    try:
        endpoint = ip_address(value["lanAddress"])
    except ValueError as exc:
        raise TransactionError("identity-invalid") from exc
    if endpoint not in LAN:
        raise TransactionError("identity-invalid")
    return {"host": value["host"], "lanAddress": value["lanAddress"]}


def validate_image(value: Any) -> str:
    if not isinstance(value, str) or IMAGE.fullmatch(value) is None or "$" in value:
        raise TransactionError("invalid-image")
    first = value.split("/", 1)[0]
    registry = first if "/" in value and ("." in first or ":" in first) else "docker.io"
    if registry not in ALLOWED_REGISTRIES:
        raise TransactionError("registry-denied")
    tail = value.rsplit("/", 1)[-1]
    if "@sha256:" not in value and ":" not in tail:
        raise TransactionError("image-version-required")
    if tail.endswith(":latest"):
        raise TransactionError("latest-tag-denied")
    return value


def validate_path(value: Any) -> str:
    if not isinstance(value, str) or PATH.fullmatch(value) is None or "//" in value or "/../" in f"{value}/":
        raise TransactionError("invalid-container-path")
    return value.rstrip("/") or "/"


def validate_environment(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 64:
        raise TransactionError("invalid-environment")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or ENV_NAME.fullmatch(key) is None or SENSITIVE.search(key):
            raise TransactionError("sensitive-environment-denied")
        if not isinstance(item, (str, int, float, bool)) or isinstance(item, float) and not (-1e12 < item < 1e12):
            raise TransactionError("invalid-environment")
        text = str(item).lower() if isinstance(item, bool) else str(item)
        if len(text) > 256 or any(character in text for character in ("\x00", "\r", "\n", "$")) or re.search(r"://[^/@:]+:[^/@]+@", text):
            raise TransactionError("sensitive-environment-denied")
        result[key] = text
    return result


def validate_ports(value: Any, lan_address: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 32:
        raise TransactionError("invalid-ports")
    result: list[str] = []
    seen: set[tuple[str, int, str]] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"target", "published", "scope", "protocol"}:
            raise TransactionError("invalid-ports")
        target, published = item["target"], item["published"]
        scope, protocol = item["scope"], item["protocol"]
        if not isinstance(target, int) or not 1 <= target <= 65535 or not isinstance(published, int) or not 1024 <= published <= 65535 or scope not in {"loopback", "lan"} or protocol not in {"tcp", "udp"}:
            raise TransactionError("invalid-ports")
        host = "127.0.0.1" if scope == "loopback" else lan_address
        marker = (host, published, protocol)
        if marker in seen:
            raise TransactionError("duplicate-port")
        seen.add(marker)
        result.append(f"{host}:{published}:{target}/{protocol}")
    return result


def validate_volumes(value: Any) -> tuple[list[dict[str, Any]], set[str]]:
    if value is None:
        return [], set()
    if not isinstance(value, list) or len(value) > 32:
        raise TransactionError("invalid-volumes")
    result: list[dict[str, Any]] = []
    names: set[str] = set()
    targets: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"name", "target", "readOnly"} or not isinstance(item.get("name"), str) or NAME.fullmatch(item["name"]) is None or not isinstance(item.get("readOnly"), bool):
            raise TransactionError("invalid-volumes")
        target = validate_path(item.get("target"))
        if target in targets:
            raise TransactionError("duplicate-volume-target")
        targets.add(target)
        names.add(item["name"])
        result.append({"type": "volume", "source": item["name"], "target": target, "read_only": item["readOnly"]})
    return result, names


def validate_tmpfs(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 16:
        raise TransactionError("invalid-tmpfs")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        target = validate_path(item)
        if target in seen:
            raise TransactionError("invalid-tmpfs")
        seen.add(target)
        result.append({"type": "tmpfs", "target": target, "tmpfs": {"size": 67_108_864, "mode": 0o1777}})
    return result


def validate_service(name: str, value: Any, lan_address: str) -> tuple[dict[str, Any], set[str]]:
    allowed = {"image", "restart", "environment", "ports", "volumes", "tmpfs", "readOnly", "cpus", "memoryMb", "pidsLimit"}
    if NAME.fullmatch(name) is None or not isinstance(value, dict) or set(value) - allowed or "image" not in value:
        raise TransactionError("invalid-service")
    restart = value.get("restart", "unless-stopped")
    if restart not in {"no", "always", "on-failure", "unless-stopped"}:
        raise TransactionError("invalid-restart")
    read_only = value.get("readOnly", True)
    cpus = value.get("cpus", 2.0)
    memory = value.get("memoryMb", 1024)
    pids = value.get("pidsLimit", 512)
    if not isinstance(read_only, bool) or not isinstance(cpus, (int, float)) or isinstance(cpus, bool) or not 0.1 <= float(cpus) <= 8.0 or not isinstance(memory, int) or not 64 <= memory <= 32768 or not isinstance(pids, int) or not 32 <= pids <= 4096:
        raise TransactionError("invalid-resources")
    volumes, names = validate_volumes(value.get("volumes"))
    mounts = volumes + validate_tmpfs(value.get("tmpfs"))
    result: dict[str, Any] = {
        "image": validate_image(value["image"]),
        "restart": restart,
        "read_only": read_only,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "cpus": float(cpus),
        "mem_limit": f"{memory}m",
        "pids_limit": pids,
    }
    environment = validate_environment(value.get("environment"))
    ports = validate_ports(value.get("ports"), lan_address)
    if environment:
        result["environment"] = environment
    if ports:
        result["ports"] = ports
    if mounts:
        result["volumes"] = mounts
    return result, names


def render_spec(stack: str, value: Any, lan_address: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "services"} or value.get("schemaVersion") != 1 or not isinstance(value.get("services"), dict) or not 1 <= len(value["services"]) <= 16:
        raise TransactionError("invalid-spec")
    services: dict[str, Any] = {}
    volumes: set[str] = set()
    images: list[str] = []
    published: list[str] = []
    for service_name in sorted(value["services"]):
        service, names = validate_service(service_name, value["services"][service_name], lan_address)
        services[service_name] = service
        volumes.update(names)
        images.append(service["image"])
        published.extend(service.get("ports", []))
    compose: dict[str, Any] = {"services": services}
    if volumes:
        compose["volumes"] = {name: {} for name in sorted(volumes)}
    summary = {
        "stack": stack,
        "services": sorted(services),
        "images": images,
        "publishedPorts": published,
        "desiredDigest": digest(value),
    }
    return compose, summary


def run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=timeout,
            env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TransactionError("compose-operation-failed") from exc


def compose_command(stack: str, path: Path, *args: str) -> list[str]:
    return ["/usr/bin/docker", "compose", "-p", f"hermes-{stack}", "-f", str(path), *args]


def read_spec_directory(directory: Path) -> dict[str, Any]:
    try:
        info = os.lstat(directory)
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700 or {item.name for item in directory.iterdir()} != {"compose.json", "spec.json"}:
            raise TransactionError("stack-state-invalid")
        spec_path = directory / "spec.json"
        compose_path = directory / "compose.json"
        for path in (spec_path, compose_path):
            item = os.lstat(path)
            if not stat.S_ISREG(item.st_mode) or stat.S_ISLNK(item.st_mode) or item.st_uid != 0 or stat.S_IMODE(item.st_mode) != 0o600 or item.st_size > MAX_REQUEST:
                raise TransactionError("stack-state-invalid")
        value = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransactionError("stack-state-invalid") from exc
    return value


def current_spec(stack: str) -> dict[str, Any] | None:
    if not root_directory(ROOT):
        return None
    directory = ROOT / stack
    try:
        os.lstat(directory)
    except FileNotFoundError:
        return None
    return read_spec_directory(directory)


def validate_candidate(stack: str, directory: Path) -> None:
    result = run(compose_command(stack, directory / "compose.json", "config", "--quiet"), 45)
    if result.returncode != 0:
        raise TransactionError("compose-config-invalid")


def backup_stack(host: str, stack: str, directory: Path) -> str:
    root_directory(BACKUPS, create=True)
    root_directory(BACKUPS / host, create=True)
    target = BACKUPS / host / stack
    root_directory(target, create=True)
    name = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{os.getpid()}.tar"
    archive = target / name
    with tarfile.open(archive, "w", format=tarfile.PAX_FORMAT) as output:
        for item in (directory / "compose.json", directory / "spec.json"):
            output.add(item, arcname=item.name, recursive=False)
    os.chmod(archive, 0o600)
    with tarfile.open(archive, "r") as check:
        if sorted(check.getnames()) != ["compose.json", "spec.json"]:
            raise TransactionError("backup-invalid")
    return str(archive)


def audit(host: str, action: str, stack: str, outcome: str, desired_digest: str | None) -> None:
    entry = canonical({
        "schemaVersion": 1,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": host,
        "action": action,
        "stack": stack,
        "outcome": outcome,
        "desiredDigest": desired_digest,
    })
    descriptor = os.open(AUDIT, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
            raise TransactionError("audit-state-invalid")
        os.write(descriptor, entry)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def journal_path(stack: str) -> Path:
    return ROOT / f".{stack}.transaction.json"


def write_journal(stack: str, action: str, had_previous: bool) -> None:
    atomic_write(
        journal_path(stack),
        canonical({
            "schemaVersion": 1,
            "stack": stack,
            "action": action,
            "hadPrevious": had_previous,
        }),
    )


def remove_journal(stack: str) -> None:
    try:
        journal_path(stack).unlink()
    except FileNotFoundError:
        pass


def transient_directories(stack: str) -> list[Path]:
    if not root_directory(ROOT):
        return []
    result: list[Path] = []
    prefixes = (f".{stack}.candidate.", f".{stack}.previous.", f".{stack}.failed.")
    for item in ROOT.iterdir():
        if not item.name.startswith(prefixes):
            continue
        info = os.lstat(item)
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0:
            raise TransactionError("transaction-state-invalid")
        result.append(item)
    return result


def recover_interrupted(stack: str, host: dict[str, str]) -> None:
    path = journal_path(stack)
    if not path.exists():
        if transient_directories(stack):
            raise TransactionError("transaction-state-invalid")
        return
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 4096:
            raise TransactionError("transaction-state-invalid")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransactionError("transaction-state-invalid") from exc
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "stack", "action", "hadPrevious"} or value.get("schemaVersion") != 1 or value.get("stack") != stack or value.get("action") not in {"apply", "remove"} or not isinstance(value.get("hadPrevious"), bool):
        raise TransactionError("transaction-state-invalid")
    target = ROOT / stack
    transients = transient_directories(stack)
    previous = [item for item in transients if item.name.startswith(f".{stack}.previous.")]
    if target.exists():
        read_spec_directory(target)
    for item in previous:
        read_spec_directory(item)
    failed = ROOT / f".{stack}.failed.recovery.{os.getpid()}"
    if value["action"] == "apply":
        if value["hadPrevious"]:
            if len(previous) != 1:
                raise TransactionError("recovery-state-invalid")
            if target.exists():
                os.replace(target, failed)
            os.replace(previous[0], target)
            restored = run(compose_command(stack, target / "compose.json", "up", "-d", "--remove-orphans", "--wait", "--wait-timeout", "180"), 300)
            if restored.returncode != 0:
                raise TransactionError("recovery-failed")
        elif target.exists():
            stopped = run(compose_command(stack, target / "compose.json", "down", "--remove-orphans"), 300)
            if stopped.returncode != 0:
                raise TransactionError("recovery-failed")
            shutil.rmtree(target)
    elif target.exists():
        restored = run(compose_command(stack, target / "compose.json", "up", "-d", "--remove-orphans", "--wait", "--wait-timeout", "180"), 300)
        if restored.returncode != 0:
            raise TransactionError("recovery-failed")
    for item in transient_directories(stack):
        shutil.rmtree(item)
    remove_journal(stack)
    audit(host["host"], value["action"], stack, "recovered-prior", None)


def plan(stack: str, spec: Any, host: dict[str, str]) -> dict[str, Any]:
    compose, summary = render_spec(stack, spec, host["lanAddress"])
    existing = current_spec(stack)
    with tempfile.TemporaryDirectory(prefix="agent-compose-plan-", dir=RUNTIME) as temporary:
        candidate = Path(temporary)
        atomic_write(candidate / "compose.json", canonical(compose))
        validate_candidate(stack, candidate)
    summary["currentDigest"] = digest(existing) if existing is not None else None
    summary["outcome"] = "create" if existing is None else "noop" if summary["desiredDigest"] == summary["currentDigest"] else "change"
    return summary


def apply(stack: str, spec: Any, host: dict[str, str]) -> dict[str, Any]:
    recover_interrupted(stack, host)
    compose, summary = render_spec(stack, spec, host["lanAddress"])
    existing = current_spec(stack)
    if existing is not None and digest(existing) == summary["desiredDigest"]:
        audit(host["host"], "apply", stack, "noop", summary["desiredDigest"])
        return {**summary, "outcome": "noop", "backup": None}
    root_directory(ROOT, create=True)
    target = ROOT / stack
    backup = backup_stack(host["host"], stack, target) if existing is not None else None
    write_journal(stack, "apply", existing is not None)
    candidate = Path(tempfile.mkdtemp(prefix=f".{stack}.candidate.", dir=ROOT))
    previous = ROOT / f".{stack}.previous.{os.getpid()}"
    promoted = False
    try:
        atomic_write(candidate / "compose.json", canonical(compose))
        atomic_write(candidate / "spec.json", canonical(spec))
        validate_candidate(stack, candidate)
        pulled = run(compose_command(stack, candidate / "compose.json", "pull"), 600)
        if pulled.returncode != 0:
            raise TransactionError("compose-pull-failed")
        if target.exists():
            os.replace(target, previous)
        os.replace(candidate, target)
        promoted = True
        accepted = run(compose_command(stack, target / "compose.json", "up", "-d", "--remove-orphans", "--wait", "--wait-timeout", "180"), 300)
        if accepted.returncode != 0:
            raise TransactionError("compose-health-failed")
        shutil.rmtree(previous, ignore_errors=True)
        remove_journal(stack)
        audit(host["host"], "apply", stack, "applied", summary["desiredDigest"])
        return {**summary, "outcome": "applied", "backup": backup}
    except Exception as original:
        try:
            if promoted:
                failed = ROOT / f".{stack}.failed.{os.getpid()}"
                if target.exists():
                    os.replace(target, failed)
                if previous.exists():
                    os.replace(previous, target)
                    restored = run(compose_command(stack, target / "compose.json", "up", "-d", "--remove-orphans", "--wait", "--wait-timeout", "180"), 300)
                    if restored.returncode != 0:
                        raise TransactionError("rollback-failed")
                else:
                    stopped = run(compose_command(stack, failed / "compose.json", "down", "--remove-orphans"), 180)
                    if stopped.returncode != 0:
                        raise TransactionError("rollback-failed")
                shutil.rmtree(failed, ignore_errors=True)
            remove_journal(stack)
            audit(host["host"], "apply", stack, "rolled-back", summary["desiredDigest"])
        except Exception as rollback_error:
            raise TransactionError("rollback-failed") from rollback_error
        raise original
    finally:
        shutil.rmtree(candidate, ignore_errors=True)


def remove(stack: str, host: dict[str, str]) -> dict[str, Any]:
    recover_interrupted(stack, host)
    existing = current_spec(stack)
    if existing is None:
        return {"stack": stack, "outcome": "absent", "backup": None}
    target = ROOT / stack
    backup = backup_stack(host["host"], stack, target)
    write_journal(stack, "remove", True)
    result = run(compose_command(stack, target / "compose.json", "down", "--remove-orphans"), 300)
    if result.returncode != 0:
        restored = run(compose_command(stack, target / "compose.json", "up", "-d", "--remove-orphans", "--wait", "--wait-timeout", "180"), 300)
        if restored.returncode != 0:
            raise TransactionError("rollback-failed")
        remove_journal(stack)
        audit(host["host"], "remove", stack, "failed", digest(existing))
        raise TransactionError("compose-remove-failed")
    shutil.rmtree(target)
    remove_journal(stack)
    audit(host["host"], "remove", stack, "removed", digest(existing))
    return {"stack": stack, "outcome": "removed", "backup": backup, "volumesPreserved": True}


def status(stack: str | None, host: dict[str, str]) -> dict[str, Any]:
    if not root_directory(ROOT):
        return {"host": host["host"], "stacks": []} if stack is None else {"host": host["host"], "stack": stack, "present": False, "desiredDigest": None}
    if stack is None:
        stacks = []
        for item in sorted(ROOT.iterdir(), key=lambda path: path.name):
            if item.name.startswith("."):
                continue
            if NAME.fullmatch(item.name) is None:
                raise TransactionError("stack-state-invalid")
            spec = current_spec(item.name)
            stacks.append({"name": item.name, "desiredDigest": digest(spec)})
        return {"host": host["host"], "stacks": stacks}
    spec = current_spec(stack)
    return {"host": host["host"], "stack": stack, "present": spec is not None, "desiredDigest": digest(spec) if spec is not None else None}


def handle(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict) or request.get("schemaVersion") != 1:
        raise TransactionError("invalid-request")
    action = request.get("action")
    if action not in {"status", "plan", "apply", "remove"}:
        raise TransactionError("invalid-action")
    allowed = {"schemaVersion", "action", "stack", "spec"}
    if set(request) - allowed:
        raise TransactionError("invalid-request")
    stack = request.get("stack")
    if stack is not None and (not isinstance(stack, str) or NAME.fullmatch(stack) is None):
        raise TransactionError("invalid-stack")
    if action == "status":
        if "spec" in request:
            raise TransactionError("invalid-request")
    elif action in {"plan", "apply"}:
        if stack is None or "spec" not in request:
            raise TransactionError("invalid-request")
    elif stack is None or "spec" in request:
        raise TransactionError("invalid-request")
    host = identity()
    if action == "status":
        body = status(stack, host)
    elif action == "plan":
        body = plan(stack, request["spec"], host)
    else:
        descriptor = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "a+") as lock:
            info = os.fstat(lock.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
                raise TransactionError("lock-state-invalid")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise TransactionError("transaction-busy") from exc
            body = apply(stack, request["spec"], host) if action == "apply" else remove(stack, host)
    return {"schemaVersion": 1, "status": "ok", "host": host["host"], "action": action, "body": body}


def main() -> int:
    if os.geteuid() != 0 or len(sys.argv) != 1:
        print(json.dumps({"schemaVersion": 1, "status": "error", "code": "authority-denied"}, sort_keys=True))
        return 1
    raw = sys.stdin.buffer.read(MAX_REQUEST + 1)
    try:
        if not raw or len(raw) > MAX_REQUEST:
            raise TransactionError("invalid-request")
        response = handle(json.loads(raw))
    except (UnicodeDecodeError, json.JSONDecodeError, TransactionError) as exc:
        code = str(exc) if isinstance(exc, TransactionError) else "invalid-request"
        response = {"schemaVersion": 1, "status": "error", "code": code}
    output = canonical(response)
    if len(output) > MAX_RESPONSE:
        output = canonical({"schemaVersion": 1, "status": "error", "code": "response-too-large"})
    sys.stdout.buffer.write(output)
    return 0 if response["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
