#!/usr/bin/python3
"""Approval-gated Docker Compose update broker for an untrusted agent.

The SSH-facing ``request`` command accepts only a target ID or plan ID.  All
paths, services, health checks, and Compose behavior come from a root-owned
manifest.  Root must approve a content-addressed plan before it can execute.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import pwd
import re
import resource
import select
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
MAX_REQUEST_BYTES = 4096
MAX_COMMAND_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_BACKUP_FILE_BYTES = 8 * 1024 * 1024
MAX_BACKUP_TOTAL_BYTES = 32 * 1024 * 1024
MAX_PLAN_FILES = 2048
MAX_PROJECT_ENTRIES = 10_000
REQUEST_READ_TIMEOUT_SECONDS = 10
LOCK_WAIT_SECONDS = 5
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
PLAN_ID_RE = re.compile(r"^[a-f0-9]{64}$")
IMAGE_ID_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
DIGEST_RE = re.compile(r"^[^\s@]+@sha256:[a-f0-9]{64}$")
OPERATOR_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
STATELESS_UPDATE_CLASS = "stateless-image"
SAFE_ENV = {
    "DOCKER_CONFIG": "/etc/openclaw-docker-update/docker-client",
    "HOME": "/root",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
}


class BrokerError(Exception):
    """Expected failure with a stable public error code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def format_time(value: dt.datetime) -> str:
    return (
        value.astimezone(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_time(value: Any) -> dt.datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise BrokerError("invalid-plan")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise BrokerError("invalid-plan") from exc
    return parsed.astimezone(dt.timezone.utc)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def bounded_token(value: Any, limit: int = 160) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    if len(clean) > limit or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+:/@-]*", clean):
        return None
    return clean


def atomic_write_json(path: Path, value: Any, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(canonical_bytes(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def durable_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def load_json(path: Path, error_code: str) -> Any:
    try:
        raw = path.read_bytes()
    except (OSError, ValueError) as exc:
        raise BrokerError(error_code) from exc
    if len(raw) > MAX_COMMAND_OUTPUT_BYTES:
        raise BrokerError(error_code)
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BrokerError(error_code) from exc


def assert_secure_root_file(path: Path) -> None:
    assert_secure_file(path, 0)


def assert_secure_file(path: Path, owner_uid: int) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise BrokerError("insecure-installation") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != owner_uid
        or info.st_mode & 0o022
    ):
        raise BrokerError("insecure-installation")


def assert_secure_root_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise BrokerError("insecure-installation") from exc
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise BrokerError("insecure-installation")


def assert_secure_directory_chain(
    path: Path, boundary: Path, owner_uid: int = 0
) -> None:
    if not path.is_absolute() or not boundary.is_absolute():
        raise BrokerError("insecure-installation")
    try:
        relative = path.relative_to(boundary)
    except ValueError as exc:
        raise BrokerError("insecure-installation") from exc
    current = boundary
    candidates = [current]
    for part in relative.parts:
        current /= part
        candidates.append(current)
    for candidate in candidates:
        try:
            info = candidate.lstat()
        except OSError as exc:
            raise BrokerError("insecure-installation") from exc
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or info.st_uid != owner_uid
            or info.st_mode & 0o022
        ):
            raise BrokerError("insecure-installation")


def operator_identity() -> str:
    sudo_uid = os.environ.get("SUDO_UID")
    sudo_user = os.environ.get("SUDO_USER")
    if (
        sudo_uid
        and sudo_uid.isdecimal()
        and sudo_user
        and OPERATOR_RE.fullmatch(sudo_user)
    ):
        try:
            account = pwd.getpwuid(int(sudo_uid))
        except (KeyError, ValueError):
            account = None
        if account is not None and account.pw_name == sudo_user:
            return f"{sudo_user}:uid-{sudo_uid}"
    return f"uid-{os.getuid()}"


@dataclass(frozen=True)
class Target:
    target_id: str
    project_dir: Path
    compose_files: tuple[Path, ...]
    backup_files: tuple[Path, ...]
    service: str
    recreate_services: tuple[str, ...]
    verify_services: tuple[str, ...]
    required_paths: tuple[Path, ...]
    health_timeout_seconds: int
    update_class: str


@dataclass(frozen=True)
class Settings:
    host: str
    state_dir: Path
    docker_binary: str
    plan_ttl_seconds: int
    approval_ttl_seconds: int
    proposal_cooldown_seconds: int
    command_timeout_seconds: int
    health_poll_seconds: int
    targets: dict[str, Target]


def require_keys(value: dict[str, Any], expected: set[str], code: str) -> None:
    if set(value) != expected:
        raise BrokerError(code)


def require_id(value: Any, code: str = "invalid-request") -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise BrokerError(code)
    return value


def require_plan_id(value: Any) -> str:
    if not isinstance(value, str) or not PLAN_ID_RE.fullmatch(value):
        raise BrokerError("invalid-request")
    return value


def require_int(value: Any, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BrokerError("invalid-manifest")
    if not minimum <= value <= maximum:
        raise BrokerError("invalid-manifest")
    return value


def relative_project_file(project_dir: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise BrokerError("invalid-manifest")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise BrokerError("invalid-manifest")
    return project_dir / relative


def parse_target(target_id: str, value: Any) -> Target:
    require_id(target_id, "invalid-manifest")
    if not isinstance(value, dict):
        raise BrokerError("invalid-manifest")
    require_keys(
        value,
        {
            "projectDir",
            "composeFiles",
            "backupFiles",
            "service",
            "recreateServices",
            "verifyServices",
            "requiredPaths",
            "healthTimeoutSeconds",
            "updateClass",
        },
        "invalid-manifest",
    )
    project_raw = value["projectDir"]
    if not isinstance(project_raw, str) or not project_raw.startswith("/opt/"):
        raise BrokerError("invalid-manifest")
    project_dir = Path(project_raw)
    if (
        project_dir == Path("/opt")
        or "\x00" in project_raw
        or ".." in project_dir.parts
    ):
        raise BrokerError("invalid-manifest")
    try:
        project_dir.relative_to("/opt")
    except ValueError as exc:
        raise BrokerError("invalid-manifest") from exc

    def file_list(name: str, minimum: int) -> tuple[Path, ...]:
        raw = value[name]
        if not isinstance(raw, list) or not minimum <= len(raw) <= 16:
            raise BrokerError("invalid-manifest")
        paths = tuple(relative_project_file(project_dir, item) for item in raw)
        if len(set(paths)) != len(paths):
            raise BrokerError("invalid-manifest")
        return paths

    def service_list(name: str) -> tuple[str, ...]:
        raw = value[name]
        if not isinstance(raw, list) or not 1 <= len(raw) <= 16:
            raise BrokerError("invalid-manifest")
        services = tuple(require_id(item, "invalid-manifest") for item in raw)
        if len(set(services)) != len(services):
            raise BrokerError("invalid-manifest")
        return services

    required_raw = value["requiredPaths"]
    if not isinstance(required_raw, list) or len(required_raw) > 32:
        raise BrokerError("invalid-manifest")
    required_paths: list[Path] = []
    for item in required_raw:
        if not isinstance(item, str) or not item.startswith("/") or "\x00" in item:
            raise BrokerError("invalid-manifest")
        required_paths.append(Path(item))

    service = require_id(value["service"], "invalid-manifest")
    recreate = service_list("recreateServices")
    verify = service_list("verifyServices")
    if recreate != (service,) or verify != (service,):
        raise BrokerError("invalid-manifest")

    compose_files = file_list("composeFiles", 1)
    backup_files = file_list("backupFiles", 0)
    if not set(compose_files).issubset(set(backup_files)):
        raise BrokerError("invalid-manifest")
    update_class = value["updateClass"]
    if update_class != STATELESS_UPDATE_CLASS:
        raise BrokerError("invalid-manifest")

    return Target(
        target_id=target_id,
        project_dir=project_dir,
        compose_files=compose_files,
        backup_files=backup_files,
        service=service,
        recreate_services=recreate,
        verify_services=verify,
        required_paths=tuple(required_paths),
        health_timeout_seconds=require_int(value["healthTimeoutSeconds"], 10, 1800),
        update_class=update_class,
    )


def parse_manifest(value: Any, state_dir_override: Path | None = None) -> Settings:
    if not isinstance(value, dict):
        raise BrokerError("invalid-manifest")
    require_keys(
        value,
        {
            "schemaVersion",
            "host",
            "stateDir",
            "dockerBinary",
            "planTtlSeconds",
            "approvalTtlSeconds",
            "proposalCooldownSeconds",
            "commandTimeoutSeconds",
            "healthPollSeconds",
            "targets",
        },
        "invalid-manifest",
    )
    if value["schemaVersion"] != SCHEMA_VERSION:
        raise BrokerError("invalid-manifest")
    host = require_id(value["host"], "invalid-manifest")
    if host != socket.gethostname().split(".")[0]:
        raise BrokerError("wrong-host")
    state_raw = value["stateDir"]
    if not isinstance(state_raw, str) or not state_raw.startswith("/var/lib/"):
        raise BrokerError("invalid-manifest")
    state_dir = state_dir_override or Path(state_raw)
    docker_binary = value["dockerBinary"]
    if docker_binary != "/usr/bin/docker":
        raise BrokerError("invalid-manifest")
    targets_raw = value["targets"]
    if not isinstance(targets_raw, dict) or len(targets_raw) > 128:
        raise BrokerError("invalid-manifest")
    targets = {
        target_id: parse_target(target_id, target)
        for target_id, target in targets_raw.items()
    }
    return Settings(
        host=host,
        state_dir=state_dir,
        docker_binary=docker_binary,
        plan_ttl_seconds=require_int(value["planTtlSeconds"], 300, 3600),
        approval_ttl_seconds=require_int(value["approvalTtlSeconds"], 60, 1800),
        proposal_cooldown_seconds=require_int(
            value["proposalCooldownSeconds"], 30, 86400
        ),
        command_timeout_seconds=require_int(value["commandTimeoutSeconds"], 30, 1800),
        health_poll_seconds=require_int(value["healthPollSeconds"], 1, 30),
        targets=targets,
    )


class CommandRunner:
    def __init__(self, timeout: int):
        self.timeout = timeout

    def run(self, command: list[str], code: str) -> bytes:
        def limit_output_files() -> None:
            resource.setrlimit(
                resource.RLIMIT_FSIZE,
                (MAX_COMMAND_OUTPUT_BYTES, MAX_COMMAND_OUTPUT_BYTES),
            )

        try:
            with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                result = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=self.timeout,
                    check=False,
                    env=SAFE_ENV,
                    cwd="/",
                    preexec_fn=limit_output_files,
                )
                if result.returncode != 0:
                    raise BrokerError(code)
                if stdout.tell() > MAX_COMMAND_OUTPUT_BYTES:
                    raise BrokerError(code)
                stdout.seek(0)
                output = stdout.read(MAX_COMMAND_OUTPUT_BYTES + 1)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BrokerError(code) from exc
        if len(output) > MAX_COMMAND_OUTPUT_BYTES:
            raise BrokerError(code)
        return output


class Broker:
    def __init__(
        self,
        settings: Settings,
        runner: CommandRunner,
        project_boundary: Path = Path("/opt"),
        trusted_owner_uid: int = 0,
    ):
        self.settings = settings
        self.runner = runner
        self.project_boundary = project_boundary
        self.trusted_owner_uid = trusted_owner_uid
        self.state_dir = settings.state_dir
        self.plans_dir = self.state_dir / "plans"
        self.states_dir = self.state_dir / "states"
        self.approvals_dir = self.state_dir / "approvals"
        self.results_dir = self.state_dir / "results"
        self.rollbacks_dir = self.state_dir / "rollbacks"
        self.rate_dir = self.state_dir / "rate"
        self.lock_path = self.state_dir / "broker.lock"

    def ensure_state(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state_dir, 0o700)
        for directory in (
            self.plans_dir,
            self.states_dir,
            self.approvals_dir,
            self.results_dir,
            self.rollbacks_dir,
            self.rate_dir,
        ):
            directory.mkdir(exist_ok=True, mode=0o700)
            os.chmod(directory, 0o700)

    def lock(self):
        self.ensure_state()
        handle = self.lock_path.open("a+b")
        os.chmod(self.lock_path, 0o600)
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    handle.close()
                    raise BrokerError("broker-busy")
                time.sleep(0.1)
        return handle

    def audit(self, event: str, **fields: Any) -> None:
        record = {
            "at": format_time(utc_now()),
            "event": event,
            **{
                key: value
                for key, value in fields.items()
                if isinstance(value, (str, int, bool)) or value is None
            },
        }
        audit_path = self.state_dir / "audit.jsonl"
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(audit_path, flags, 0o600)
        try:
            os.write(fd, canonical_bytes(record) + b"\n")
            os.fsync(fd)
        finally:
            os.close(fd)

    def compose_base(self, target: Target) -> list[str]:
        command = [
            self.settings.docker_binary,
            "compose",
            "--project-directory",
            str(target.project_dir),
        ]
        for compose_file in target.compose_files:
            command.extend(["-f", str(compose_file)])
        return command

    def compose_config(self, target: Target) -> tuple[dict[str, Any], str]:
        raw = self.runner.run(
            self.compose_base(target) + ["config", "--format", "json"],
            "compose-config-failed",
        )
        try:
            config = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BrokerError("compose-config-failed") from exc
        if not isinstance(config, dict):
            raise BrokerError("compose-config-failed")
        return config, hashlib.sha256(raw).hexdigest()

    @staticmethod
    def configured_image(config: dict[str, Any], target: Target) -> str:
        services = config.get("services")
        if not isinstance(services, dict):
            raise BrokerError("service-not-configured")
        service = services.get(target.service)
        if not isinstance(service, dict):
            raise BrokerError("service-not-configured")
        image = service.get("image")
        if not isinstance(image, str) or not image or len(image) > 512:
            raise BrokerError("service-image-not-pullable")
        if any(ord(ch) < 33 or ord(ch) > 126 for ch in image):
            raise BrokerError("service-image-not-pullable")
        return image

    @staticmethod
    def verify_config_healthchecks(config: dict[str, Any], target: Target) -> None:
        services = config.get("services")
        if not isinstance(services, dict):
            raise BrokerError("compose-config-failed")
        for service_name in target.verify_services:
            service = services.get(service_name)
            if not isinstance(service, dict):
                raise BrokerError("service-not-configured")
            healthcheck = service.get("healthcheck")
            test = healthcheck.get("test") if isinstance(healthcheck, dict) else None
            if (
                not isinstance(test, list)
                or not test
                or not all(isinstance(item, str) and item for item in test)
                or test[0].upper() == "NONE"
            ):
                raise BrokerError("healthcheck-required")

    @staticmethod
    def verify_config_sandbox(config: dict[str, Any], target: Target) -> None:
        services = config.get("services")
        service = services.get(target.service) if isinstance(services, dict) else None
        if not isinstance(service, dict):
            raise BrokerError("service-not-configured")
        user = service.get("user")
        if not isinstance(user, str) or not re.fullmatch(
            r"[1-9][0-9]*(?::[1-9][0-9]*)?", user
        ):
            raise BrokerError("nonroot-user-required")
        security_opt = service.get("security_opt")
        if not isinstance(security_opt, list) or not any(
            isinstance(item, str)
            and item.casefold().replace("=", ":") == "no-new-privileges:true"
            for item in security_opt
        ):
            raise BrokerError("no-new-privileges-required")
        cap_drop = service.get("cap_drop")
        if not isinstance(cap_drop, list) or not any(
            isinstance(item, str) and item.casefold() == "all" for item in cap_drop
        ):
            raise BrokerError("cap-drop-all-required")
        if service.get("read_only") is not True:
            raise BrokerError("readonly-root-required")
        forbidden_nonempty = (
            "build",
            "cap_add",
            "configs",
            "devices",
            "group_add",
            "secrets",
            "volumes",
        )
        if service.get("privileged") is True or any(
            service.get(field) not in (None, [], {}) for field in forbidden_nonempty
        ):
            raise BrokerError("privileged-surface-unsupported")
        for namespace in ("ipc", "network_mode", "pid", "uts"):
            if service.get(namespace) not in (None, ""):
                raise BrokerError("shared-namespace-unsupported")

    def compose_container_id(self, target: Target, service: str) -> str:
        raw = self.runner.run(
            self.compose_base(target) + ["ps", "-q", service],
            "container-inspect-failed",
        )
        ids = [
            line.strip()
            for line in raw.decode("ascii", "strict").splitlines()
            if line.strip()
        ]
        if len(ids) != 1 or not re.fullmatch(r"[a-f0-9]{12,64}", ids[0]):
            raise BrokerError("container-count-unsupported")
        return ids[0]

    def inspect_json(self, command: list[str], code: str) -> dict[str, Any]:
        raw = self.runner.run(command, code)
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BrokerError(code) from exc
        if (
            not isinstance(value, list)
            or len(value) != 1
            or not isinstance(value[0], dict)
        ):
            raise BrokerError(code)
        return value[0]

    def image_details(self, image: str, repository_hint: str | None) -> dict[str, Any]:
        inspected = self.inspect_json(
            [self.settings.docker_binary, "image", "inspect", image],
            "image-inspect-failed",
        )
        image_id = inspected.get("Id")
        if not isinstance(image_id, str) or not IMAGE_ID_RE.fullmatch(image_id):
            raise BrokerError("image-inspect-failed")
        repo_digests = inspected.get("RepoDigests")
        valid_digests = sorted(
            digest
            for digest in repo_digests or []
            if isinstance(digest, str) and DIGEST_RE.fullmatch(digest)
        )
        digest = self.select_digest(valid_digests, repository_hint)
        config = inspected.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        labels = labels if isinstance(labels, dict) else {}
        declared_volumes = config.get("Volumes") if isinstance(config, dict) else None
        if declared_volumes is not None and not isinstance(declared_volumes, dict):
            raise BrokerError("image-inspect-failed")
        return {
            "imageId": image_id,
            "digest": digest,
            "version": bounded_token(labels.get("org.opencontainers.image.version")),
            "revision": bounded_token(labels.get("org.opencontainers.image.revision")),
            "declaredVolumes": bool(declared_volumes),
        }

    @staticmethod
    def repository_name(image_ref: str) -> str:
        without_digest = image_ref.split("@", 1)[0]
        slash = without_digest.rfind("/")
        colon = without_digest.rfind(":")
        if colon > slash:
            return without_digest[:colon]
        return without_digest

    def select_digest(
        self, digests: list[str], repository_hint: str | None
    ) -> str | None:
        if not digests:
            return None
        if repository_hint:
            repository = self.repository_name(repository_hint)
            matches = [item for item in digests if item.split("@", 1)[0] == repository]
            if len(matches) == 1:
                return matches[0]
        if len(digests) == 1:
            return digests[0]
        return None

    def running_image(self, target: Target, repository_hint: str) -> dict[str, Any]:
        container_id = self.compose_container_id(target, target.service)
        container = self.inspect_json(
            [self.settings.docker_binary, "inspect", container_id],
            "container-inspect-failed",
        )
        image_id = container.get("Image")
        if not isinstance(image_id, str) or not IMAGE_ID_RE.fullmatch(image_id):
            raise BrokerError("container-inspect-failed")
        return self.image_details(image_id, repository_hint)

    def rate_path(self, target_id: str) -> Path:
        return self.rate_dir / f"{hashlib.sha256(target_id.encode()).hexdigest()}.json"

    def enforce_rate_limit(self, target_id: str, now: dt.datetime) -> None:
        path = self.rate_path(target_id)
        if path.exists():
            value = load_json(path, "proposal-cooldown")
            if not isinstance(value, dict) or set(value) != {"lastProposalAt"}:
                raise BrokerError("proposal-cooldown")
            last = parse_time(value["lastProposalAt"])
            if (now - last).total_seconds() < self.settings.proposal_cooldown_seconds:
                raise BrokerError("proposal-cooldown")
        atomic_write_json(path, {"lastProposalAt": format_time(now)})

    def plan_path(self, plan_id: str) -> Path:
        return self.plans_dir / f"{plan_id}.json"

    def state_path(self, plan_id: str) -> Path:
        return self.states_dir / f"{plan_id}.json"

    def approval_path(self, plan_id: str) -> Path:
        return self.approvals_dir / f"{plan_id}.json"

    def result_path(self, plan_id: str) -> Path:
        return self.results_dir / f"{plan_id}.json"

    def load_plan(self, plan_id: str) -> dict[str, Any]:
        plan = load_json(self.plan_path(plan_id), "plan-not-found")
        if not isinstance(plan, dict) or plan.get("planId") != plan_id:
            raise BrokerError("invalid-plan")
        body = {key: value for key, value in plan.items() if key != "planId"}
        if hashlib.sha256(canonical_bytes(body)).hexdigest() != plan_id:
            raise BrokerError("invalid-plan")
        return plan

    def load_state(self, plan_id: str) -> dict[str, Any]:
        value = load_json(self.state_path(plan_id), "invalid-plan-state")
        if not isinstance(value, dict) or set(value) != {"status", "updatedAt"}:
            raise BrokerError("invalid-plan-state")
        if value["status"] not in {
            "proposed",
            "executing",
            "failed",
            "succeeded",
            "rolled-back",
            "rollback-failed",
            "rejected",
        }:
            raise BrokerError("invalid-plan-state")
        return value

    def write_state(self, plan_id: str, status_value: str) -> None:
        atomic_write_json(
            self.state_path(plan_id),
            {"status": status_value, "updatedAt": format_time(utc_now())},
        )

    @staticmethod
    def public_plan(plan: dict[str, Any], status_value: str) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "status": status_value,
            "planId": plan["planId"],
            "host": plan["host"],
            "targetId": plan["targetId"],
            "service": plan["service"],
            "createdAt": plan["createdAt"],
            "expiresAt": plan["expiresAt"],
            "current": plan["current"],
            "candidate": plan["candidate"],
        }

    def propose(self, target_id: str) -> dict[str, Any]:
        target = self.settings.targets.get(target_id)
        if target is None:
            raise BrokerError("target-not-allowlisted")
        with self.lock():
            if len(list(self.plans_dir.glob("*.json"))) >= MAX_PLAN_FILES:
                raise BrokerError("plan-capacity-reached")
            now = utc_now()
            self.enforce_rate_limit(target_id, now)
            self.verify_files(target)
            self.verify_stateless_runtime(target)
            config, config_hash = self.compose_config(target)
            self.verify_config_healthchecks(config, target)
            self.verify_config_sandbox(config, target)
            image_ref = self.configured_image(config, target)
            current = self.running_image(target, image_ref)
            self.verify_stateless_image(current)
            self.runner.run(
                self.compose_base(target)
                + ["pull", "--policy", "always", target.service],
                "image-pull-failed",
            )
            candidate = self.image_details(image_ref, image_ref)
            self.verify_stateless_image(candidate)
            if candidate["digest"] is None:
                raise BrokerError("candidate-digest-unavailable")
            if candidate["imageId"] == current["imageId"]:
                self.audit("proposal-no-update", targetId=target_id)
                return {
                    "schemaVersion": SCHEMA_VERSION,
                    "status": "no-update",
                    "host": self.settings.host,
                    "targetId": target_id,
                    "service": target.service,
                    "current": current,
                }

            body = {
                "schemaVersion": SCHEMA_VERSION,
                "host": self.settings.host,
                "targetId": target_id,
                "service": target.service,
                "createdAt": format_time(now),
                "expiresAt": format_time(
                    now + dt.timedelta(seconds=self.settings.plan_ttl_seconds)
                ),
                "configSha256": config_hash,
                "current": current,
                "candidate": candidate,
            }
            plan_id = hashlib.sha256(canonical_bytes(body)).hexdigest()
            plan = {"planId": plan_id, **body}
            atomic_write_json(self.plan_path(plan_id), plan)
            self.write_state(plan_id, "proposed")
            self.audit("proposal-created", planId=plan_id, targetId=target_id)
            return self.public_plan(plan, "approval-required")

    def approval(self, plan_id: str) -> dict[str, Any] | None:
        path = self.approval_path(plan_id)
        if not path.exists():
            return None
        value = load_json(path, "invalid-approval")
        if not isinstance(value, dict):
            raise BrokerError("invalid-approval")
        require_keys(
            value,
            {"planId", "approvedAt", "expiresAt", "approvedBy"},
            "invalid-approval",
        )
        if value["planId"] != plan_id:
            raise BrokerError("invalid-approval")
        if not isinstance(value["approvedBy"], str) or not value["approvedBy"]:
            raise BrokerError("invalid-approval")
        return value

    def status(self, plan_id: str) -> dict[str, Any]:
        with self.lock():
            plan = self.load_plan(plan_id)
            state_value = self.load_state(plan_id)["status"]
            result_path = self.result_path(plan_id)
            if result_path.exists():
                result = load_json(result_path, "invalid-result")
                if not isinstance(result, dict) or result.get("planId") != plan_id:
                    raise BrokerError("invalid-result")
                return result
            if state_value == "proposed":
                if utc_now() > parse_time(plan["expiresAt"]):
                    state_value = "expired"
                elif self.approval(plan_id):
                    state_value = "approved"
            return self.public_plan(plan, state_value)

    def approve(self, plan_id: str) -> dict[str, Any]:
        with self.lock():
            plan = self.load_plan(plan_id)
            if self.load_state(plan_id)["status"] != "proposed":
                raise BrokerError("plan-not-approvable")
            now = utc_now()
            if now > parse_time(plan["expiresAt"]):
                raise BrokerError("plan-expired")
            approval = {
                "planId": plan_id,
                "approvedAt": format_time(now),
                "expiresAt": format_time(
                    min(
                        parse_time(plan["expiresAt"]),
                        now + dt.timedelta(seconds=self.settings.approval_ttl_seconds),
                    )
                ),
                "approvedBy": operator_identity(),
            }
            atomic_write_json(self.approval_path(plan_id), approval)
            self.audit(
                "plan-approved",
                planId=plan_id,
                targetId=plan["targetId"],
                approvedBy=approval["approvedBy"],
            )
            return self.public_plan(plan, "approved")

    def reject(self, plan_id: str) -> dict[str, Any]:
        with self.lock():
            plan = self.load_plan(plan_id)
            if self.load_state(plan_id)["status"] != "proposed":
                raise BrokerError("plan-not-rejectable")
            self.write_state(plan_id, "rejected")
            durable_unlink(self.approval_path(plan_id))
            self.audit(
                "plan-rejected",
                planId=plan_id,
                targetId=plan["targetId"],
                rejectedBy=operator_identity(),
            )
            return self.public_plan(plan, "rejected")

    def verify_files(self, target: Target) -> None:
        assert_secure_directory_chain(
            target.project_dir,
            self.project_boundary,
            self.trusted_owner_uid,
        )
        for path in target.compose_files:
            try:
                info = path.lstat()
            except OSError as exc:
                raise BrokerError("compose-file-unavailable") from exc
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise BrokerError("compose-file-unavailable")
        for path in target.backup_files:
            if path.exists():
                assert_secure_file(path, self.trusted_owner_uid)
        for path in target.required_paths:
            if not path.exists():
                raise BrokerError("required-path-unavailable")
        self.verify_project_tree(target)

    def verify_project_tree(self, target: Target) -> None:
        entries = 0
        for current_root, directories, files in os.walk(
            target.project_dir, topdown=True, followlinks=False
        ):
            for name in [*directories, *files]:
                entries += 1
                if entries > MAX_PROJECT_ENTRIES:
                    raise BrokerError("project-tree-too-large")
                path = Path(current_root) / name
                try:
                    info = path.lstat()
                except OSError as exc:
                    raise BrokerError("insecure-installation") from exc
                if (
                    stat.S_ISLNK(info.st_mode)
                    or info.st_uid != self.trusted_owner_uid
                    or info.st_mode & 0o022
                    or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))
                ):
                    raise BrokerError("insecure-installation")

    def verify_stateless_runtime(self, target: Target) -> None:
        if target.update_class != STATELESS_UPDATE_CLASS:
            raise BrokerError("stateful-target-unsupported")
        for service in target.recreate_services:
            container_id = self.compose_container_id(target, service)
            container = self.inspect_json(
                [self.settings.docker_binary, "inspect", container_id],
                "container-inspect-failed",
            )
            mounts = container.get("Mounts")
            if not isinstance(mounts, list):
                raise BrokerError("container-inspect-failed")
            if mounts:
                raise BrokerError("stateful-target-unsupported")
            config = container.get("Config")
            host_config = container.get("HostConfig")
            if not isinstance(config, dict) or not isinstance(host_config, dict):
                raise BrokerError("container-inspect-failed")
            user = config.get("User")
            if not isinstance(user, str) or not re.fullmatch(
                r"[1-9][0-9]*(?::[1-9][0-9]*)?", user
            ):
                raise BrokerError("nonroot-user-required")
            security_opt = host_config.get("SecurityOpt")
            cap_drop = host_config.get("CapDrop")
            if host_config.get("Privileged") is not False:
                raise BrokerError("privileged-surface-unsupported")
            if host_config.get("ReadonlyRootfs") is not True:
                raise BrokerError("readonly-root-required")
            if host_config.get("CapAdd") not in (None, []):
                raise BrokerError("privileged-surface-unsupported")
            for field in ("Binds", "Devices", "DeviceRequests", "GroupAdd", "Tmpfs"):
                if host_config.get(field) not in (None, [], {}):
                    raise BrokerError("privileged-surface-unsupported")
            for field in ("IpcMode", "PidMode", "UTSMode", "UsernsMode"):
                if host_config.get(field) not in (None, ""):
                    raise BrokerError("shared-namespace-unsupported")
            if not isinstance(cap_drop, list) or not any(
                isinstance(item, str) and item.casefold() == "all" for item in cap_drop
            ):
                raise BrokerError("cap-drop-all-required")
            if not isinstance(security_opt, list) or not any(
                isinstance(item, str)
                and item.casefold().replace("=", ":") == "no-new-privileges:true"
                for item in security_opt
            ):
                raise BrokerError("no-new-privileges-required")

    @staticmethod
    def verify_stateless_image(details: dict[str, Any]) -> None:
        if details.get("declaredVolumes") is not False:
            raise BrokerError("stateful-target-unsupported")

    def capture_backup(self, target: Target, plan_id: str) -> Path:
        transaction_dir = self.rollbacks_dir / plan_id
        try:
            transaction_dir.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise BrokerError("transaction-artifact-exists") from exc
        archive = transaction_dir / "compose-config.tar"
        total_size = 0
        try:
            with tarfile.open(archive, "w", format=tarfile.PAX_FORMAT) as handle:
                for path in target.backup_files:
                    try:
                        info = path.lstat()
                    except FileNotFoundError:
                        continue
                    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                        raise BrokerError("backup-source-invalid")
                    if info.st_size > MAX_BACKUP_FILE_BYTES:
                        raise BrokerError("backup-source-too-large")
                    total_size += info.st_size
                    if total_size > MAX_BACKUP_TOTAL_BYTES:
                        raise BrokerError("backup-source-too-large")
                    handle.add(
                        path,
                        arcname=str(path.relative_to(target.project_dir)),
                        recursive=False,
                    )
        except (OSError, tarfile.TarError) as exc:
            raise BrokerError("backup-failed") from exc
        os.chmod(archive, 0o600)
        return transaction_dir

    def write_override(
        self, directory: Path, name: str, service: str, image: str
    ) -> Path:
        path = directory / name
        atomic_write_json(path, {"services": {service: {"image": image}}})
        return path

    def compose_apply(self, target: Target, override: Path) -> None:
        command = self.compose_base(target) + [
            "-f",
            str(override),
            "up",
            "-d",
            "--no-deps",
            "--pull",
            "never",
            "--force-recreate",
            *target.recreate_services,
        ]
        self.runner.run(command, "compose-apply-failed")

    def verify_health(self, target: Target) -> None:
        deadline = time.monotonic() + target.health_timeout_seconds
        while True:
            all_healthy = True
            for service in target.verify_services:
                container_id = self.compose_container_id(target, service)
                container = self.inspect_json(
                    [self.settings.docker_binary, "inspect", container_id],
                    "health-inspect-failed",
                )
                state_value = container.get("State")
                if not isinstance(state_value, dict):
                    raise BrokerError("health-inspect-failed")
                if state_value.get("Status") in {"dead", "exited"}:
                    raise BrokerError("health-check-failed")
                health = state_value.get("Health")
                if not isinstance(health, dict):
                    raise BrokerError("healthcheck-required")
                health_status = health.get("Status")
                if health_status == "unhealthy":
                    raise BrokerError("health-check-failed")
                if (
                    state_value.get("Status") != "running"
                    or health_status == "starting"
                ):
                    all_healthy = False
            if all_healthy:
                return
            if time.monotonic() >= deadline:
                raise BrokerError("health-check-timeout")
            time.sleep(self.settings.health_poll_seconds)

    def execute(self, plan_id: str) -> dict[str, Any]:
        with self.lock():
            plan = self.load_plan(plan_id)
            target = self.settings.targets.get(plan["targetId"])
            if target is None or target.service != plan["service"]:
                raise BrokerError("target-not-allowlisted")
            if self.load_state(plan_id)["status"] != "proposed":
                raise BrokerError("plan-already-consumed")
            now = utc_now()
            if now > parse_time(plan["expiresAt"]):
                raise BrokerError("plan-expired")
            approval = self.approval(plan_id)
            if approval is None:
                raise BrokerError("approval-required")
            if now > parse_time(approval["expiresAt"]):
                raise BrokerError("approval-expired")

            self.verify_files(target)
            config, config_hash = self.compose_config(target)
            if config_hash != plan["configSha256"]:
                raise BrokerError("compose-config-drift")
            self.verify_config_healthchecks(config, target)
            self.verify_config_sandbox(config, target)
            image_ref = self.configured_image(config, target)
            current = self.running_image(target, image_ref)
            if current["imageId"] != plan["current"]["imageId"]:
                raise BrokerError("runtime-drift")
            self.verify_stateless_image(current)
            self.verify_stateless_runtime(target)
            candidate = self.image_details(image_ref, image_ref)
            if (
                candidate["imageId"] != plan["candidate"]["imageId"]
                or candidate["digest"] != plan["candidate"]["digest"]
            ):
                raise BrokerError("candidate-drift")
            self.verify_stateless_image(candidate)

            self.write_state(plan_id, "executing")
            durable_unlink(self.approval_path(plan_id))
            self.audit("execution-started", planId=plan_id, targetId=target.target_id)
            started_at = format_time(utc_now())
            failure_code: str | None = None
            rollback_status = "not-needed"
            candidate_apply_started = False
            rollback_override: Path | None = None
            rollback_tag = (
                f"openclaw-rollback/{target.target_id.replace('.', '-')}:"
                f"{plan_id[:16]}"
            )
            try:
                transaction_dir = self.capture_backup(target, plan_id)
                self.runner.run(
                    [
                        self.settings.docker_binary,
                        "image",
                        "tag",
                        plan["current"]["imageId"],
                        rollback_tag,
                    ],
                    "rollback-tag-failed",
                )
                candidate_override = self.write_override(
                    transaction_dir,
                    "candidate.json",
                    target.service,
                    plan["candidate"]["digest"],
                )
                rollback_override = self.write_override(
                    transaction_dir, "rollback.json", target.service, rollback_tag
                )
                candidate_apply_started = True
                self.compose_apply(target, candidate_override)
                self.verify_stateless_runtime(target)
                self.verify_health(target)
                terminal_status = "succeeded"
            except BrokerError as exc:
                failure_code = exc.code
                if candidate_apply_started and rollback_override is not None:
                    rollback_status = "attempted"
                    try:
                        self.compose_apply(target, rollback_override)
                        self.verify_stateless_runtime(target)
                        self.verify_health(target)
                        terminal_status = "rolled-back"
                        rollback_status = "succeeded"
                    except BrokerError:
                        terminal_status = "rollback-failed"
                        rollback_status = "failed"
                else:
                    terminal_status = "failed"

            result = {
                "schemaVersion": SCHEMA_VERSION,
                "status": terminal_status,
                "planId": plan_id,
                "host": plan["host"],
                "targetId": plan["targetId"],
                "service": plan["service"],
                "startedAt": started_at,
                "finishedAt": format_time(utc_now()),
                "current": plan["current"],
                "candidate": plan["candidate"],
                "errorCode": failure_code,
                "rollback": rollback_status,
            }
            atomic_write_json(self.result_path(plan_id), result)
            self.write_state(plan_id, terminal_status)
            self.audit(
                "execution-finished",
                planId=plan_id,
                targetId=target.target_id,
                status=terminal_status,
                errorCode=failure_code,
            )
            return result

    def handle_request(self, request: Any) -> dict[str, Any]:
        if (
            not isinstance(request, dict)
            or request.get("schemaVersion") != SCHEMA_VERSION
        ):
            raise BrokerError("invalid-request")
        action = request.get("action")
        if action == "propose":
            require_keys(
                request, {"schemaVersion", "action", "targetId"}, "invalid-request"
            )
            return self.propose(require_id(request["targetId"]))
        if action == "execute":
            require_keys(
                request, {"schemaVersion", "action", "planId"}, "invalid-request"
            )
            return self.execute(require_plan_id(request["planId"]))
        if action == "status":
            require_keys(
                request, {"schemaVersion", "action", "planId"}, "invalid-request"
            )
            return self.status(require_plan_id(request["planId"]))
        raise BrokerError("invalid-request")


def read_request() -> Any:
    deadline = time.monotonic() + REQUEST_READ_TIMEOUT_SECONDS
    chunks: list[bytes] = []
    size = 0
    while size <= MAX_REQUEST_BYTES:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BrokerError("request-timeout")
        try:
            ready, _, _ = select.select([sys.stdin.buffer], [], [], remaining)
        except OSError as exc:
            raise BrokerError("invalid-request") from exc
        if not ready:
            raise BrokerError("request-timeout")
        chunk = os.read(sys.stdin.fileno(), min(1024, MAX_REQUEST_BYTES + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    raw = b"".join(chunks)
    if not raw or len(raw) > MAX_REQUEST_BYTES:
        raise BrokerError("invalid-request")
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BrokerError("invalid-request") from exc


def emit(value: dict[str, Any]) -> None:
    encoded = canonical_bytes(value)
    if len(encoded) > 16384:
        encoded = canonical_bytes(
            {
                "schemaVersion": SCHEMA_VERSION,
                "status": "error",
                "errorCode": "response-too-large",
            }
        )
    sys.stdout.buffer.write(encoded + b"\n")


def load_settings(manifest_path: Path, check_permissions: bool = True) -> Settings:
    if check_permissions:
        assert_secure_root_file(manifest_path)
    manifest = load_json(manifest_path, "invalid-manifest")
    settings = parse_manifest(manifest)
    if check_permissions:
        assert_secure_root_directory(settings.state_dir)
    return settings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        default="/etc/openclaw-docker-update/manifest.json",
        type=Path,
    )
    parser.add_argument(
        "command", choices=("request", "validate", "show", "approve", "reject")
    )
    parser.add_argument("plan_id", nargs="?")
    args = parser.parse_args()

    try:
        if os.geteuid() != 0:
            raise BrokerError("root-required")
        settings = load_settings(args.manifest)
        broker = Broker(settings, CommandRunner(settings.command_timeout_seconds))
        broker.ensure_state()
        if args.command == "validate":
            if args.plan_id is not None:
                raise BrokerError("invalid-request")
            emit(
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "status": "ok",
                    "host": settings.host,
                    "targetCount": len(settings.targets),
                }
            )
            return 0
        if args.command == "request":
            if args.plan_id is not None:
                raise BrokerError("invalid-request")
            emit(broker.handle_request(read_request()))
            return 0
        if args.plan_id is None or not PLAN_ID_RE.fullmatch(args.plan_id):
            raise BrokerError("invalid-request")
        if args.command == "show":
            emit(broker.status(args.plan_id))
        elif args.command == "approve":
            emit(broker.approve(args.plan_id))
        else:
            emit(broker.reject(args.plan_id))
        return 0
    except BrokerError as exc:
        emit(
            {
                "schemaVersion": SCHEMA_VERSION,
                "status": "error",
                "errorCode": exc.code,
            }
        )
        return 1
    except Exception:
        emit(
            {
                "schemaVersion": SCHEMA_VERSION,
                "status": "error",
                "errorCode": "internal-error",
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
