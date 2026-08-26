#!/usr/bin/env python3
"""Run Hermes's native updater around one planned Gateway outage."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import fcntl
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
import sys
from typing import Any


PROFILE_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
UNIT_RE = re.compile(r"^hermes-gateway-[a-z][a-z0-9-]{0,31}\.service$")
RUNTIME_VALIDATION_COMMAND_TIMEOUT_SECONDS = 30
REQUIRED_KEYS = {
    "version",
    "updateUser",
    "runtimeGroup",
    "runtimeRoot",
    "venvPython",
    "hermesEntry",
    "hermesBinary",
    "uvBinary",
    "basePythonRoot",
    "memoryDependencyUpdater",
    "managedSourcePatcher",
    "queuedEventPatch",
    "queuedEventValidator",
    "sourcePatchBranch",
    "sourcePatchTargetBranch",
    "sourcePatchStagingRoot",
    "browserSelector",
    "rollbackRoot",
    "rollbackKeep",
    "minimumFreeBytes",
    "systemdWaitSeconds",
    "updateAccountHome",
    "updateProfileHome",
    "stableDependencies",
    "spacyModel",
    "postSetupKeys",
    "profiles",
}


class TransactionError(RuntimeError):
    """A bounded update transaction failed."""


def absolute_path(value: Any, field: str, *, require_exists: bool = True) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise ValueError(f"{field} must be an absolute path")
    path = Path(value)
    if require_exists and not path.exists():
        raise ValueError(f"{field} does not exist: {path}")
    return path


def load_config(path: Path, *, require_runtime_paths: bool = True) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("config must be a regular, non-symlink file")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != REQUIRED_KEYS:
        raise ValueError("config keys do not match the transaction contract")
    if data["version"] != 2:
        raise ValueError("unsupported transaction config version")
    if data["updateUser"] != "hermes-astra":
        raise ValueError("updateUser must be hermes-astra")
    if data["runtimeGroup"] != "hermes-runtime-readers":
        raise ValueError("runtimeGroup must be hermes-runtime-readers")
    if not isinstance(data["systemdWaitSeconds"], int) or not 30 <= data["systemdWaitSeconds"] <= 600:
        raise ValueError("systemdWaitSeconds must be between 30 and 600")
    if not isinstance(data["rollbackKeep"], int) or not 1 <= data["rollbackKeep"] <= 10:
        raise ValueError("rollbackKeep must be between 1 and 10")
    if (
        not isinstance(data["minimumFreeBytes"], int)
        or not 536870912 <= data["minimumFreeBytes"] <= 53687091200
    ):
        raise ValueError("minimumFreeBytes must be between 512 MiB and 50 GiB")
    for field in (
        "runtimeRoot",
        "venvPython",
        "hermesEntry",
        "hermesBinary",
        "uvBinary",
        "basePythonRoot",
        "memoryDependencyUpdater",
        "managedSourcePatcher",
        "queuedEventPatch",
        "queuedEventValidator",
        "sourcePatchStagingRoot",
        "browserSelector",
        "rollbackRoot",
        "updateAccountHome",
        "updateProfileHome",
    ):
        absolute_path(data[field], field, require_exists=require_runtime_paths)
    if data["sourcePatchBranch"] != "astra-managed-parity":
        raise ValueError("sourcePatchBranch must be astra-managed-parity")
    if data["sourcePatchTargetBranch"] != "main":
        raise ValueError("sourcePatchTargetBranch must be main")
    if require_runtime_paths:
        runtime_root = Path(data["runtimeRoot"]).resolve(strict=True)
        entry = Path(data["hermesEntry"]).resolve(strict=True)
        if runtime_root not in entry.parents:
            raise ValueError("hermesEntry must remain inside runtimeRoot")
        venv_root = Path(data["venvPython"]).parent.parent.resolve(strict=True)
        if runtime_root not in venv_root.parents:
            raise ValueError("venv root must remain inside runtimeRoot")
        base_python_root = Path(data["basePythonRoot"]).resolve(strict=True)
        interpreter = Path(data["venvPython"]).resolve(strict=True)
        if base_python_root not in interpreter.parents:
            raise ValueError("venv interpreter must resolve inside basePythonRoot")
        rollback_root = Path(data["rollbackRoot"])
        if rollback_root.is_symlink() or not rollback_root.is_dir():
            raise ValueError("rollbackRoot must be a regular directory")
    for field in ("stableDependencies", "postSetupKeys"):
        values = data[field]
        if not isinstance(values, list) or not values or not all(
            isinstance(item, str) and item and "\n" not in item for item in values
        ):
            raise ValueError(f"{field} must be a nonempty string list")
    if not isinstance(data["spacyModel"], str) or not data["spacyModel"]:
        raise ValueError("spacyModel must be nonempty")
    profiles = data["profiles"]
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("profiles must be nonempty")
    names: list[str] = []
    units: list[str] = []
    for profile in profiles:
        expected = {"name", "user", "group", "unit", "accountHome", "home"}
        if not isinstance(profile, dict) or set(profile) != expected:
            raise ValueError("profile keys do not match the transaction contract")
        if not PROFILE_RE.fullmatch(profile["name"]):
            raise ValueError("invalid profile name")
        if profile["user"] != f"hermes-{profile['name']}" or profile["group"] != profile["user"]:
            raise ValueError("profile identity does not match its name")
        if not UNIT_RE.fullmatch(profile["unit"]):
            raise ValueError("invalid Gateway unit")
        if profile["unit"] != f"hermes-gateway-{profile['name']}.service":
            raise ValueError("profile name and unit do not match")
        if require_runtime_paths:
            pwd.getpwnam(profile["user"])
            grp.getgrnam(profile["group"])
        absolute_path(profile["accountHome"], "profile.accountHome", require_exists=require_runtime_paths)
        absolute_path(profile["home"], "profile.home", require_exists=require_runtime_paths)
        names.append(profile["name"])
        units.append(profile["unit"])
    if len(names) != len(set(names)) or len(units) != len(set(units)):
        raise ValueError("profile names and units must be unique")
    return data


class NativeUpdateTransaction:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.active: list[dict[str, str]] = []
        self.stopped: list[dict[str, str]] = []
        self.events: list[str] = []

    def _run_as_user(
        self,
        command: list[str],
        *,
        user: str,
        environment: dict[str, str] | None,
        timeout: int | None,
        capture: bool,
        input_text: str | None,
    ) -> subprocess.CompletedProcess[str]:
        if not command or not command[0].startswith("/"):
            raise OSError("delegated commands require an absolute executable path")
        account = pwd.getpwnam(user)
        group_names = [
            grp.getgrgid(group_id).gr_name
            for group_id in os.getgrouplist(account.pw_name, account.pw_gid)
        ]
        writable_paths = [
            self.config["runtimeRoot"],
            self.config["rollbackRoot"],
            *[
                path
                for profile in self.config["profiles"]
                for path in (profile["accountHome"], profile["home"])
            ],
        ]
        delegated = [
            "/usr/bin/systemd-run",
            "--quiet",
            "--wait",
            "--pipe",
            "--collect",
            "--service-type=exec",
            f"--uid={account.pw_name}",
            f"--gid={grp.getgrgid(account.pw_gid).gr_name}",
            "--property=NoNewPrivileges=yes",
            "--property=CapabilityBoundingSet=",
            "--property=AmbientCapabilities=",
            "--property=ProtectSystem=strict",
            "--property=ProtectHome=yes",
            "--property=PrivateTmp=yes",
            "--property=PrivateDevices=yes",
            "--property=ProtectProc=invisible",
            "--property=LockPersonality=yes",
            "--property=RestrictRealtime=yes",
            "--property=RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK",
            "--property=InaccessiblePaths=/etc/hermes/astra /etc/hermes/dubble /etc/hermes/rigel",
            f"--property=SupplementaryGroups={' '.join(group_names)}",
            f"--property=ReadWritePaths={' '.join(dict.fromkeys(writable_paths))}",
            f"--property=ReadOnlyPaths={self.config['uvBinary']} {self.config['basePythonRoot']}",
        ]
        if timeout is not None:
            delegated.append(f"--property=RuntimeMaxSec={timeout}s")
        for key, value in sorted((environment or {}).items()):
            if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key) or "\n" in value:
                raise OSError("invalid delegated environment")
            delegated.append(f"--setenv={key}={value}")
        delegated.extend(["--", *command])
        return subprocess.run(
            delegated,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=(timeout + 30 if timeout is not None else None),
            capture_output=capture,
            input=input_text,
        )

    def run(
        self,
        argv: list[str],
        *,
        user: str | None = None,
        environment: dict[str, str] | None = None,
        check: bool = True,
        timeout: int | None = None,
        capture: bool = False,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = list(argv)
        try:
            if user is None:
                completed = subprocess.run(
                    command,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                    timeout=timeout,
                    capture_output=capture,
                    input=input_text,
                    env=environment,
                )
            else:
                completed = self._run_as_user(
                    command,
                    user=user,
                    environment=environment,
                    timeout=timeout,
                    capture=capture,
                    input_text=input_text,
                )
        except (OSError, subprocess.SubprocessError) as exc:
            raise TransactionError(
                f"could not start command ({Path(argv[0]).name}): {exc}"
            ) from exc
        if check and completed.returncode != 0:
            detail = ""
            if capture:
                output = (completed.stderr or completed.stdout or "").strip()
                if output:
                    detail = ": " + " | ".join(output.splitlines())[-1000:]
            raise TransactionError(
                f"command failed ({Path(argv[0]).name}): "
                f"{completed.returncode}{detail}"
            )
        return completed

    def updater_environment(self) -> dict[str, str]:
        root = Path(self.config["runtimeRoot"])
        return {
            "HOME": self.config["updateAccountHome"],
            "HERMES_HOME": self.config["updateProfileHome"],
            "PATH": ":".join(
                [
                    str(Path(self.config["updateProfileHome"]) / "bin"),
                    str(Path(self.config["uvBinary"]).parent),
                    str(Path(self.config["venvPython"]).parent),
                    "/usr/local/bin",
                    "/usr/bin",
                    "/bin",
                ]
            ),
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "UV_LINK_MODE": "copy",
            "PYTHONNOUSERSITE": "1",
            "PWD": str(root),
        }

    def git_prefix(self) -> list[str]:
        root = self.config["runtimeRoot"]
        return ["/usr/bin/git", "-c", f"safe.directory={root}", "-C", root]

    def sha256(self, path: Path) -> str:
        completed = self.run(
            ["/usr/bin/sha256sum", str(path)],
            user=self.config["updateUser"],
            environment=self.updater_environment(),
            capture=True,
        )
        digest = (completed.stdout or "").split(maxsplit=1)[0]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise TransactionError(f"invalid rollback digest: {path.name}")
        return digest

    def profile_environment(self, profile: dict[str, str]) -> dict[str, str]:
        return {
            "HOME": profile["accountHome"],
            "HERMES_HOME": profile["home"],
            "PATH": ":".join(
                [
                    str(Path(self.config["venvPython"]).parent),
                    "/usr/local/bin",
                    "/usr/bin",
                    "/bin",
                ]
            ),
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        }

    def profile_config_path(self, profile: dict[str, str]) -> Path:
        home = Path(profile["home"])
        config = home / "config.yaml"
        if config.parent != home:
            raise TransactionError(
                f"profile config escaped its home: {profile['name']}"
            )
        return config

    def read_regular_utf8_file(
        self,
        path: Path,
        *,
        parent: Path,
        user: str,
        environment: dict[str, str],
    ) -> dict[str, Any]:
        """Inspect and read a private file through its owning identity."""
        inspector = """import base64,hashlib,json,stat,sys
from pathlib import Path

parent = Path(sys.argv[1]).resolve(strict=True)
path = Path(sys.argv[2])
if path.parent.resolve(strict=True) != parent:
    raise SystemExit("file escaped its approved parent")
before = path.lstat()
if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
    raise SystemExit("file is not regular")
content = path.read_bytes()
after = path.lstat()
if (
    before.st_dev != after.st_dev
    or before.st_ino != after.st_ino
    or before.st_size != after.st_size
    or before.st_mtime_ns != after.st_mtime_ns
):
    raise SystemExit("file changed while reading")
print(json.dumps({
    "content": base64.b64encode(content).decode("ascii"),
    "gid": before.st_gid,
    "mode": stat.S_IMODE(before.st_mode),
    "sha256": hashlib.sha256(content).hexdigest(),
    "uid": before.st_uid,
}, sort_keys=True))
"""
        completed = self.run(
            ["/usr/bin/python3", "-c", inspector, str(parent), str(path)],
            user=user,
            environment=environment,
            capture=True,
        )
        lines = [line for line in (completed.stdout or "").splitlines() if line.strip()]
        if not lines:
            raise TransactionError(f"private file inspection is absent: {path.name}")
        try:
            proof = json.loads(lines[-1])
            content = base64.b64decode(proof["content"], validate=True)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise TransactionError(
                f"private file inspection is invalid: {path.name}"
            ) from exc
        if (
            not isinstance(proof.get("uid"), int)
            or not isinstance(proof.get("gid"), int)
            or not isinstance(proof.get("mode"), int)
            or not isinstance(proof.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", proof["sha256"])
            or self.content_sha256(content) != proof["sha256"]
        ):
            raise TransactionError(
                f"private file inspection did not verify: {path.name}"
            )
        try:
            proof["text"] = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise TransactionError(f"private file is not UTF-8: {path.name}") from exc
        proof.pop("content", None)
        return proof

    @staticmethod
    def content_sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def backup_profile_configs(self, directory: Path) -> list[dict[str, Any]]:
        backups: list[dict[str, Any]] = []
        update_user = self.config["updateUser"]
        update_environment = self.updater_environment()
        for profile in self.config["profiles"]:
            source = self.profile_config_path(profile)
            inspected = self.read_regular_utf8_file(
                source,
                parent=Path(profile["home"]),
                user=profile["user"],
                environment=self.profile_environment(profile),
            )
            expected_uid = pwd.getpwnam(profile["user"]).pw_uid
            expected_gid = grp.getgrnam(profile["group"]).gr_gid
            if inspected["uid"] != expected_uid or inspected["gid"] != expected_gid:
                raise TransactionError(
                    f"profile config ownership is unsafe: {profile['name']}"
                )
            text = inspected["text"]
            digest = inspected["sha256"]
            backup = directory / f"profile-{profile['name']}-config.yaml"
            partial = Path(str(backup) + ".partial")
            if backup.exists() or backup.is_symlink() or partial.exists() or partial.is_symlink():
                raise TransactionError(
                    f"profile config rollback path already exists: {profile['name']}"
                )
            self.run(
                ["/usr/bin/dd", f"of={partial}", "status=none", "conv=fsync"],
                user=update_user,
                environment=update_environment,
                input_text=text,
            )
            self.run(
                ["/usr/bin/chmod", "0600", str(partial)],
                user=update_user,
                environment=update_environment,
            )
            self.run(
                ["/usr/bin/mv", str(partial), str(backup)],
                user=update_user,
                environment=update_environment,
            )
            if self.sha256(backup) != digest:
                raise TransactionError(
                    f"profile config rollback digest mismatch: {profile['name']}"
                )
            backups.append(
                {
                    "backup": backup.name,
                    "gid": inspected["gid"],
                    "mode": inspected["mode"],
                    "name": profile["name"],
                    "sha256": digest,
                    "source": str(source),
                    "uid": inspected["uid"],
                }
            )
        self.events.append("profile-configs-backed-up")
        return backups

    def prepare_rollback(self) -> dict[str, Any]:
        user = self.config["updateUser"]
        env = self.updater_environment()
        root = Path(self.config["runtimeRoot"])
        rollback_root = Path(self.config["rollbackRoot"])
        free_bytes = shutil.disk_usage(root).free
        if free_bytes < self.config["minimumFreeBytes"]:
            raise TransactionError(
                "insufficient runtime filesystem space: "
                f"{free_bytes} < {self.config['minimumFreeBytes']}"
            )
        status = self.run(
            self.git_prefix() + ["status", "--porcelain"],
            user=user,
            environment=env,
            capture=True,
        )
        if (status.stdout or "").strip():
            raise TransactionError("Hermes source checkout is not clean")
        head = self.run(
            self.git_prefix() + ["rev-parse", "HEAD"],
            user=user,
            environment=env,
            capture=True,
        ).stdout.strip()
        branch = self.run(
            self.git_prefix() + ["branch", "--show-current"],
            user=user,
            environment=env,
            capture=True,
        ).stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{40}", head):
            raise TransactionError("could not capture the pre-update source commit")
        if not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", branch) or branch.startswith("/"):
            raise TransactionError("could not capture a safe pre-update source branch")

        backup_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        directory = rollback_root / backup_id
        self.run(
            ["/usr/bin/mkdir", "-m", "0700", str(directory)],
            user=user,
            environment=env,
        )
        profile_configs = self.backup_profile_configs(directory)
        bundle_partial = directory / "hermes-source.bundle.partial"
        bundle = directory / "hermes-source.bundle"
        archive_partial = directory / "hermes-venv.tar.partial"
        archive = directory / "hermes-venv.tar"
        self.run(
            self.git_prefix() + ["bundle", "create", str(bundle_partial), "--all"],
            user=user,
            environment=env,
            timeout=1800,
        )
        self.run(
            ["/usr/bin/mv", str(bundle_partial), str(bundle)],
            user=user,
            environment=env,
        )
        self.run(
            self.git_prefix() + ["bundle", "verify", str(bundle)],
            user=user,
            environment=env,
            capture=True,
        )
        self.run(
            [
                "/usr/bin/tar",
                "-C",
                str(root),
                "-cf",
                str(archive_partial),
                "venv",
            ],
            user=user,
            environment=env,
            timeout=1800,
        )
        self.run(
            ["/usr/bin/mv", str(archive_partial), str(archive)],
            user=user,
            environment=env,
        )
        self.run(
            ["/usr/bin/tar", "-tf", str(archive)],
            user=user,
            environment=env,
            capture=True,
            timeout=1800,
        )
        freeze = self.run(
            [
                self.config["uvBinary"],
                "pip",
                "freeze",
                "--python",
                self.config["venvPython"],
            ],
            user=user,
            environment=env,
            capture=True,
        ).stdout
        bundle_sha256 = self.sha256(bundle)
        archive_sha256 = self.sha256(archive)
        manifest = {
            "archive": archive.name,
            "archiveSha256": archive_sha256,
            "branch": branch,
            "bundle": bundle.name,
            "bundleSha256": bundle_sha256,
            "head": head,
            "packages": "requirements.freeze",
            "profileConfigs": profile_configs,
            "version": 2,
        }
        for path, content in (
            (directory / "requirements.freeze", freeze),
            (directory / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n"),
        ):
            self.run(
                ["/usr/bin/tee", str(path)],
                user=user,
                environment=env,
                capture=True,
                input_text=content,
            )
            self.run(
                ["/usr/bin/chmod", "0600", str(path)],
                user=user,
                environment=env,
            )
        state = {
            **manifest,
            "directory": str(directory),
            "freeze": freeze,
        }
        self.events.append("rollback-prepared")
        return state

    def normalize_runtime_ownership(self) -> None:
        root = Path(self.config["runtimeRoot"])
        venv = root / "venv"
        if venv.is_symlink() or venv.parent.resolve(strict=True) != root.resolve(strict=True):
            raise TransactionError("refusing to normalize an unsafe venv path")
        user = self.config["updateUser"]
        group = self.config["runtimeGroup"]
        environment = self.updater_environment()

        def ownership_drift() -> str:
            for predicate in (("-user", user), ("-group", group)):
                completed = self.run(
                    [
                        "/usr/bin/find",
                        str(venv),
                        "-xdev",
                        "!",
                        predicate[0],
                        predicate[1],
                        "-print",
                        "-quit",
                    ],
                    user=user,
                    environment=environment,
                    capture=True,
                    timeout=60,
                )
                if (completed.stdout or "").strip():
                    return (completed.stdout or "").strip()
            return ""

        drift = ownership_drift()
        if not drift:
            return
        self.run(
            [
                "/usr/bin/chown",
                "-R",
                "--no-dereference",
                f"{user}:{group}",
                str(venv),
            ],
            timeout=900,
        )
        if ownership_drift():
            raise TransactionError("managed venv ownership normalization failed")
        self.events.append("runtime-ownership-repaired")

    def _rollback_runtime_only(self, state: dict[str, Any]) -> None:
        user = self.config["updateUser"]
        env = self.updater_environment()
        root = Path(self.config["runtimeRoot"])
        directory = Path(state["directory"])
        bundle = directory / state["bundle"]
        archive = directory / state["archive"]
        if self.sha256(bundle) != state["bundleSha256"]:
            raise TransactionError("source rollback bundle digest mismatch")
        if self.sha256(archive) != state["archiveSha256"]:
            raise TransactionError("venv rollback archive digest mismatch")
        self.run(
            self.git_prefix() + ["bundle", "verify", str(bundle)],
            user=user,
            environment=env,
            capture=True,
        )
        self.run(
            self.git_prefix() + ["switch", state["branch"]],
            user=user,
            environment=env,
        )
        self.run(
            self.git_prefix() + ["reset", "--hard", state["head"]],
            user=user,
            environment=env,
        )
        self.run(
            self.git_prefix() + ["clean", "-fd"],
            user=user,
            environment=env,
        )
        venv = root / "venv"
        if venv.is_symlink() or venv.parent.resolve(strict=True) != root.resolve(strict=True):
            raise TransactionError("refusing to replace an unsafe venv path")
        backup_id = directory.name
        if not re.fullmatch(r"\d{8}T\d{6}Z", backup_id):
            raise TransactionError("rollback directory has an unsafe identifier")
        stage = root / f".venv-rollback-{backup_id}"
        failed = root / f".venv-failed-{backup_id}"
        if stage.exists() or stage.is_symlink() or failed.exists() or failed.is_symlink():
            raise TransactionError("rollback venv staging paths already exist")
        self.run(
            ["/usr/bin/mkdir", "-m", "0700", str(stage)],
            user=user,
            environment=env,
        )
        self.run(
            [
                "/usr/bin/tar",
                "--no-same-owner",
                "--no-same-permissions",
                "-C",
                str(stage),
                "-xf",
                str(archive),
            ],
            user=user,
            environment=env,
            timeout=1800,
        )
        staged_venv = stage / "venv"
        staged_python = staged_venv / "bin" / "python"
        for predicate in (
            ["-d", str(staged_venv)],
            ["!", "-L", str(staged_venv)],
            ["-x", str(staged_python)],
        ):
            completed = self.run(
                ["/usr/bin/test", *predicate],
                user=user,
                environment=env,
                check=False,
            )
            if completed.returncode != 0:
                raise TransactionError("staged rollback venv is incomplete")
        staged_freeze = self.run(
            [
                self.config["uvBinary"],
                "pip",
                "freeze",
                "--python",
                str(staged_python),
            ],
            user=user,
            environment=env,
            capture=True,
        ).stdout
        if sorted(staged_freeze.splitlines()) != sorted(state["freeze"].splitlines()):
            raise TransactionError("staged rollback package manifest does not match")
        self.run(
            [
                self.config["uvBinary"],
                "pip",
                "check",
                "--python",
                str(staged_python),
            ],
            user=user,
            environment=env,
        )
        self.run(
            [
                str(staged_python),
                self.config["queuedEventValidator"],
                "--source-root",
                self.config["runtimeRoot"],
            ],
            user=user,
            environment=env,
        )
        self.run(
            ["/usr/bin/mv", "-T", str(venv), str(failed)],
            user=user,
            environment=env,
        )
        try:
            self.run(
                ["/usr/bin/mv", "-T", str(staged_venv), str(venv)],
                user=user,
                environment=env,
            )
        except Exception:
            if not venv.exists() and failed.is_dir() and not failed.is_symlink():
                self.run(
                    ["/usr/bin/mv", "-T", str(failed), str(venv)],
                    user=user,
                    environment=env,
                    check=False,
                )
            raise
        self.run(
            [
                "/usr/bin/chgrp",
                "-R",
                "--no-dereference",
                self.config["runtimeGroup"],
                str(venv),
            ],
            user=user,
            environment=env,
        )
        restored_python = self.run(
            ["/usr/bin/test", "-x", self.config["venvPython"]],
            user=user,
            environment=env,
            check=False,
            timeout=60,
        )
        if restored_python.returncode != 0:
            raise TransactionError("restored venv Python is absent")
        restored_freeze = self.run(
            [
                self.config["uvBinary"],
                "pip",
                "freeze",
                "--python",
                self.config["venvPython"],
            ],
            user=user,
            environment=env,
            capture=True,
        ).stdout
        if sorted(restored_freeze.splitlines()) != sorted(state["freeze"].splitlines()):
            raise TransactionError("restored package manifest does not match")
        self.run(
            [
                self.config["uvBinary"],
                "pip",
                "check",
                "--python",
                self.config["venvPython"],
            ],
            user=user,
            environment=env,
        )
        restored_head = self.run(
            self.git_prefix() + ["rev-parse", "HEAD"],
            user=user,
            environment=env,
            capture=True,
        ).stdout.strip()
        restored_status = self.run(
            self.git_prefix() + ["status", "--porcelain"],
            user=user,
            environment=env,
            capture=True,
        ).stdout.strip()
        if restored_head != state["head"] or restored_status:
            raise TransactionError("restored source checkout does not match")
        self.run(
            [
                self.config["venvPython"],
                self.config["queuedEventValidator"],
                "--source-root",
                self.config["runtimeRoot"],
            ],
            user=user,
            environment=env,
        )
        self.run(
            ["/usr/bin/rm", "-rf", "--", str(failed), str(stage)],
            user=user,
            environment=env,
            timeout=900,
        )
        self.events.append("runtime-rolled-back")

    def restore_profile_configs(self, state: dict[str, Any]) -> None:
        records = state.get("profileConfigs")
        if not isinstance(records, list) or len(records) != len(self.config["profiles"]):
            raise TransactionError("profile config rollback manifest is incomplete")
        by_name = {profile["name"]: profile for profile in self.config["profiles"]}
        if {record.get("name") for record in records} != set(by_name):
            raise TransactionError("profile config rollback identities do not match")
        directory = Path(state["directory"])
        backup_id = directory.name
        if not re.fullmatch(r"\d{8}T\d{6}Z", backup_id):
            raise TransactionError("profile config rollback identifier is unsafe")
        for record in records:
            profile = by_name[record["name"]]
            source = Path(record["source"])
            expected_source = Path(profile["home"]) / "config.yaml"
            if source != expected_source:
                raise TransactionError(
                    f"profile config rollback source drift: {profile['name']}"
                )
            backup = directory / record["backup"]
            if backup.parent != directory:
                raise TransactionError(
                    f"profile config rollback artifact is unsafe: {profile['name']}"
                )
            backup_proof = self.read_regular_utf8_file(
                backup,
                parent=directory,
                user=self.config["updateUser"],
                environment=self.updater_environment(),
            )
            if backup_proof["sha256"] != record["sha256"]:
                raise TransactionError(
                    f"profile config rollback digest mismatch: {profile['name']}"
                )
            text = backup_proof["text"]
            target = Path(profile["home"]) / "config.yaml"
            current = self.read_regular_utf8_file(
                target,
                parent=Path(profile["home"]),
                user=profile["user"],
                environment=self.profile_environment(profile),
            )
            if current["uid"] != record["uid"] or current["gid"] != record["gid"]:
                raise TransactionError(
                    f"profile config target ownership is unsafe: {profile['name']}"
                )
            partial = Path(profile["home"]) / f".config.yaml.rollback-{backup_id}.partial"
            environment = self.profile_environment(profile)
            for predicate in ("-e", "-L"):
                partial_state = self.run(
                    ["/usr/bin/test", predicate, str(partial)],
                    user=profile["user"],
                    environment=environment,
                    check=False,
                )
                if partial_state.returncode == 0:
                    raise TransactionError(
                        f"profile config rollback partial exists: {profile['name']}"
                    )
                if partial_state.returncode != 1:
                    raise TransactionError(
                        f"profile config rollback partial is uninspectable: {profile['name']}"
                    )
            self.run(
                ["/usr/bin/dd", f"of={partial}", "status=none", "conv=fsync"],
                user=profile["user"],
                environment=environment,
                input_text=text,
            )
            self.run(
                ["/usr/bin/chmod", f"{record['mode']:04o}", str(partial)],
                user=profile["user"],
                environment=environment,
            )
            self.run(
                ["/usr/bin/mv", "-T", str(partial), str(target)],
                user=profile["user"],
                environment=environment,
            )
            restored = self.read_regular_utf8_file(
                target,
                parent=Path(profile["home"]),
                user=profile["user"],
                environment=environment,
            )
            if (
                restored["uid"] != record["uid"]
                or restored["gid"] != record["gid"]
                or restored["mode"] != record["mode"]
                or restored["sha256"] != record["sha256"]
            ):
                raise TransactionError(
                    f"profile config rollback verification failed: {profile['name']}"
                )
        self.events.append("profile-configs-rolled-back")

    def rollback_runtime(self, state: dict[str, Any]) -> None:
        failures: list[str] = []
        try:
            self.restore_profile_configs(state)
        except Exception as exc:
            failures.append(f"profile configs: {exc}")
        try:
            self._rollback_runtime_only(state)
        except Exception as exc:
            failures.append(f"runtime: {exc}")
        if failures:
            raise TransactionError("; ".join(failures))

    def prune_rollbacks(self) -> None:
        user = self.config["updateUser"]
        env = self.updater_environment()
        root = Path(self.config["rollbackRoot"])
        completed = self.run(
            [
                "/usr/bin/find",
                str(root),
                "-mindepth",
                "1",
                "-maxdepth",
                "1",
                "-type",
                "d",
                "-printf",
                "%f\\n",
            ],
            user=user,
            environment=env,
            capture=True,
        )
        names = sorted(
            name
            for name in (completed.stdout or "").splitlines()
            if re.fullmatch(r"\d{8}T\d{6}Z", name)
        )
        for name in names[: -self.config["rollbackKeep"]]:
            self.run(
                ["/usr/bin/rm", "-rf", "--", str(root / name)],
                user=user,
                environment=env,
            )
        self.events.append("rollbacks-pruned")

    def inspect_active_profiles(self) -> list[dict[str, str]]:
        active: list[dict[str, str]] = []
        for profile in self.config["profiles"]:
            completed = self.run(
                ["/usr/bin/systemctl", "is-active", profile["unit"]],
                check=False,
                capture=True,
            )
            state = (completed.stdout or "").strip()
            if state == "active":
                active.append(profile)
            elif state in {"activating", "deactivating", "reloading"}:
                raise TransactionError(f"Gateway is in transitional state: {profile['unit']}={state}")
        return active

    def main_pid(self, profile: dict[str, str]) -> int:
        completed = self.run(
            [
                "/usr/bin/systemctl",
                "show",
                profile["unit"],
                "--property=MainPID",
                "--value",
            ],
            capture=True,
        )
        try:
            pid = int((completed.stdout or "0").strip())
        except ValueError as exc:
            raise TransactionError(f"invalid MainPID for {profile['unit']}") from exc
        if pid <= 1:
            raise TransactionError(f"active Gateway has no usable MainPID: {profile['unit']}")
        return pid

    def marker_paths(self, profile: dict[str, str]) -> tuple[Path, Path]:
        return (
            Path(profile["home"]) / ".gateway-planned-stop.json",
            Path(profile["accountHome"]) / ".gateway-planned-stop.json",
        )

    def prepare_marker(self, profile: dict[str, str], pid: int) -> None:
        code = (
            "import json,stat,sys; from pathlib import Path; "
            "from gateway.status import write_planned_stop_marker; "
            "paths=[Path(item) for item in sys.argv[2:]]; "
            "[path.unlink(missing_ok=True) for path in paths]; "
            "ok=write_planned_stop_marker(int(sys.argv[1])); "
            "current=paths[0].lstat(); "
            "print(json.dumps({'ok':bool(ok),'mode':stat.S_IMODE(current.st_mode),"
            "'uid':current.st_uid,'gid':current.st_gid,"
            "'regular':stat.S_ISREG(current.st_mode),'symlink':stat.S_ISLNK(current.st_mode)})); "
            "raise SystemExit(0 if ok else 1)"
        )
        completed = self.run(
            [
                self.config["venvPython"],
                "-c",
                code,
                str(pid),
                *[str(path) for path in self.marker_paths(profile)],
            ],
            user=profile["user"],
            environment={
                "HOME": profile["accountHome"],
                "HERMES_HOME": profile["home"],
                "PATH": f"{Path(self.config['venvPython']).parent}:/usr/bin:/bin",
                "PYTHONNOUSERSITE": "1",
            },
            capture=True,
        )
        lines = [line for line in (completed.stdout or "").splitlines() if line.strip()]
        if not lines:
            raise TransactionError(f"planned-stop marker proof is absent: {profile['name']}")
        marker = json.loads(lines[-1])
        if (
            not marker["ok"]
            or not marker["regular"]
            or marker["symlink"]
            or marker["mode"] != 0o600
            or marker["uid"] != pwd.getpwnam(profile["user"]).pw_uid
            or marker["gid"] != grp.getgrnam(profile["group"]).gr_gid
        ):
            raise TransactionError(f"planned-stop marker has unsafe metadata: {profile['name']}")

    def prepare_all_markers(self) -> None:
        for profile in self.active:
            self.prepare_marker(profile, self.main_pid(profile))
        self.events.append("markers-prepared")

    def stop_active_profiles(self) -> None:
        for profile in self.active:
            self.run(["/usr/bin/systemctl", "stop", profile["unit"]], timeout=self.config["systemdWaitSeconds"])
            completed = self.run(
                ["/usr/bin/systemctl", "is-active", profile["unit"]],
                check=False,
                capture=True,
            )
            if (completed.stdout or "").strip() not in {"inactive", "failed"}:
                raise TransactionError(f"Gateway did not stop: {profile['unit']}")
            self.stopped.append(profile)
        self.events.append("gateways-stopped")

    def run_native_update(self) -> int:
        completed = self.run(
            [
                self.config["venvPython"],
                self.config["hermesEntry"],
                "update",
                "--gateway",
                "--yes",
            ],
            user=self.config["updateUser"],
            environment=self.updater_environment(),
            check=False,
            timeout=3600,
        )
        self.events.append("native-update-finished")
        return completed.returncode

    def reconcile_runtime(self) -> None:
        env = self.updater_environment()
        user = self.config["updateUser"]
        root = self.config["runtimeRoot"]
        python = self.config["venvPython"]
        uv = self.config["uvBinary"]
        self.run(
            [
                python,
                self.config["managedSourcePatcher"],
                "--source-root",
                root,
                "--patch",
                self.config["queuedEventPatch"],
                "--validator",
                self.config["queuedEventValidator"],
                "--branch",
                self.config["sourcePatchBranch"],
                "--target-branch",
                self.config["sourcePatchTargetBranch"],
                "--staging-root",
                self.config["sourcePatchStagingRoot"],
                "--apply",
            ],
            user=user,
            environment=env,
            timeout=1800,
        )
        self.run(
            [python, self.config["queuedEventValidator"], "--source-root", root],
            user=user,
            environment=env,
        )
        self.run(
            [uv, "pip", "install", "--strict", "--python", python, "-e", f"{root}[messaging,mem0,edge-tts]"],
            user=user,
            environment=env,
            timeout=1800,
        )
        dependency_command = [
            python,
            self.config["memoryDependencyUpdater"],
            "--uv",
            uv,
            "--python",
            python,
        ]
        for package in self.config["stableDependencies"]:
            dependency_command.extend(["--package", package])
        self.run(dependency_command, user=user, environment=env, timeout=1800)
        self.run(
            [python, "-c", f"import spacy; spacy.load({self.config['spacyModel']!r})"],
            user=user,
            environment=env,
        )
        self.run([uv, "pip", "check", "--python", python], user=user, environment=env)
        self.run(
            [
                "/usr/bin/chgrp",
                "-R",
                "--no-dereference",
                f"--from={user}",
                self.config["runtimeGroup"],
                root,
            ],
            user=user,
            environment=env,
        )
        for key in self.config["postSetupKeys"]:
            self.run(
                [self.config["hermesBinary"], "tools", "post-setup", key],
                user=user,
                environment=env,
                timeout=900,
            )
        self.run([self.config["browserSelector"], "--check"], user=user, environment=env)
        self.events.append("runtime-reconciled")

    def migrate_profile_configs(self) -> None:
        migration = """import json
from hermes_cli.config import check_config_version, get_config_path, migrate_config

before, latest = check_config_version()
if before < latest:
    migrate_config(interactive=False, quiet=True)
after, latest_after = check_config_version()
print(json.dumps({
    "after": after,
    "before": before,
    "config": str(get_config_path()),
    "latest": latest_after,
}, sort_keys=True))
raise SystemExit(0 if after >= latest_after else 1)
"""
        for profile in self.config["profiles"]:
            completed = self.run(
                [self.config["venvPython"], "-c", migration],
                user=profile["user"],
                environment=self.profile_environment(profile),
                timeout=300,
                capture=True,
            )
            lines = [line for line in (completed.stdout or "").splitlines() if line.strip()]
            if not lines:
                raise TransactionError(
                    f"profile config migration proof is absent: {profile['name']}"
                )
            try:
                proof = json.loads(lines[-1])
            except json.JSONDecodeError as exc:
                raise TransactionError(
                    f"profile config migration proof is invalid: {profile['name']}"
                ) from exc
            if (
                proof.get("config") != str(Path(profile["home"]) / "config.yaml")
                or not isinstance(proof.get("before"), int)
                or not isinstance(proof.get("after"), int)
                or not isinstance(proof.get("latest"), int)
                or proof["after"] < proof["before"]
                or proof["after"] != proof["latest"]
            ):
                raise TransactionError(
                    f"profile config migration did not converge: {profile['name']}"
                )
        self.events.append("profile-configs-migrated")

    def restore_active_profiles(self) -> list[str]:
        failures: list[str] = []
        for profile in self.stopped:
            self.run(["/usr/bin/systemctl", "reset-failed", profile["unit"]], check=False)
            completed = self.run(
                ["/usr/bin/systemctl", "start", profile["unit"]],
                check=False,
                timeout=self.config["systemdWaitSeconds"],
            )
            if completed.returncode != 0:
                failures.append(profile["unit"])
                continue
            active = self.run(
                ["/usr/bin/systemctl", "is-active", profile["unit"]],
                check=False,
                capture=True,
            )
            if (active.stdout or "").strip() != "active":
                failures.append(profile["unit"])
        for profile in self.active:
            self.run(
                ["/usr/bin/rm", "-f", *[str(path) for path in self.marker_paths(profile)]],
                user=profile["user"],
                environment={
                    "HOME": profile["accountHome"],
                    "HERMES_HOME": profile["home"],
                    "PATH": "/usr/bin:/bin",
                },
                check=False,
            )
        self.events.append("gateways-restored")
        return failures

    def execute(self) -> dict[str, Any]:
        if os.geteuid() != 0:
            raise TransactionError("transaction must run as root")
        self.active = self.inspect_active_profiles()
        native_returncode = 0
        failure: Exception | None = None
        rollback_failure: Exception | None = None
        rollback_state: dict[str, Any] | None = None
        runtime_mutation_started = False
        restore_failures: list[str] = []
        try:
            self.normalize_runtime_ownership()
            rollback_state = self.prepare_rollback()
            self.prepare_all_markers()
            self.stop_active_profiles()
            runtime_mutation_started = True
            native_returncode = self.run_native_update()
            if native_returncode != 0:
                raise TransactionError(f"native Hermes updater returned {native_returncode}")
            self.reconcile_runtime()
            self.migrate_profile_configs()
        except Exception as exc:  # restoration must run for every failure class
            failure = exc
            if runtime_mutation_started and rollback_state is not None:
                try:
                    self.rollback_runtime(rollback_state)
                except Exception as rollback_exc:
                    rollback_failure = rollback_exc
        finally:
            if rollback_failure is None:
                restore_failures = self.restore_active_profiles()
            else:
                restore_failures = [profile["unit"] for profile in self.stopped]
        if failure is None and not restore_failures:
            try:
                self.prune_rollbacks()
            except Exception:
                self.events.append("rollback-prune-failed")
        result = {
            "activeProfiles": [profile["name"] for profile in self.active],
            "events": self.events,
            "nativeReturnCode": native_returncode,
            "rollbackDirectory": rollback_state["directory"] if rollback_state else None,
            "rollbackFailure": str(rollback_failure) if rollback_failure else None,
            "restoreFailures": restore_failures,
            "status": (
                "ready"
                if failure is None and rollback_failure is None and not restore_failures
                else "failed"
            ),
        }
        print(json.dumps(result, sort_keys=True))
        if rollback_failure is not None:
            raise TransactionError(
                f"runtime rollback failed; Gateways held stopped: {rollback_failure}"
            ) from rollback_failure
        if restore_failures:
            raise TransactionError(f"Gateway restoration failed: {', '.join(restore_failures)}")
        if failure is not None:
            raise TransactionError(str(failure)) from failure
        return result


def validate_runtime(config: dict[str, Any]) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise TransactionError("runtime validation must run as root")
    transaction = NativeUpdateTransaction(config)
    user = config["updateUser"]
    environment = transaction.updater_environment()

    def run_validation(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        return transaction.run(
            command,
            timeout=RUNTIME_VALIDATION_COMMAND_TIMEOUT_SECONDS,
            **kwargs,
        )

    expected_uid = pwd.getpwnam(user).pw_uid
    identity = run_validation(
        ["/usr/bin/id", "-u"],
        user=user,
        environment=environment,
        capture=True,
    )
    try:
        observed_uid = int((identity.stdout or "").strip())
    except ValueError as exc:
        raise TransactionError("native updater identity proof is invalid") from exc
    if observed_uid != expected_uid:
        raise TransactionError(
            f"native updater identity mismatch: {observed_uid} != {expected_uid}"
        )

    security = run_validation(
        ["/usr/bin/cat", "/proc/self/status"],
        user=user,
        environment=environment,
        capture=True,
    )
    status_fields = {
        line.split(":", 1)[0]: line.split(":", 1)[1].strip()
        for line in (security.stdout or "").splitlines()
        if ":" in line
    }
    for field in ("CapInh", "CapPrm", "CapEff", "CapAmb"):
        if status_fields.get(field) != "0000000000000000":
            raise TransactionError(f"delegated child retained capabilities: {field}")
    if status_fields.get("NoNewPrivs") != "1":
        raise TransactionError("delegated child lacks NoNewPrivileges")

    for test_flag, field in (
        ("-d", "runtimeRoot"),
        ("-x", "venvPython"),
        ("-f", "hermesEntry"),
        ("-x", "hermesBinary"),
        ("-x", "uvBinary"),
        ("-d", "basePythonRoot"),
        ("-x", "memoryDependencyUpdater"),
        ("-x", "queuedEventValidator"),
        ("-x", "browserSelector"),
        ("-d", "rollbackRoot"),
        ("-w", "rollbackRoot"),
    ):
        run_validation(
            ["/usr/bin/test", test_flag, config[field]],
            user=user,
            environment=environment,
        )

    path_proof = """from pathlib import Path
import sys

runtime = Path(sys.argv[1]).resolve(strict=True)
venv_root = Path(sys.argv[2]).parent.parent.resolve(strict=True)
interpreter = Path(sys.argv[2]).resolve(strict=True)
entry = Path(sys.argv[3]).resolve(strict=True)
base_python = Path(sys.argv[4]).resolve(strict=True)
rollback = Path(sys.argv[5])
if runtime not in venv_root.parents:
    raise SystemExit("venv root escaped runtime root")
if runtime not in entry.parents:
    raise SystemExit("Hermes entry escaped runtime root")
if base_python not in interpreter.parents:
    raise SystemExit("venv interpreter escaped managed Python root")
if rollback.is_symlink():
    raise SystemExit("rollback root must not be a symlink")
print("runtime-paths-valid")
"""
    run_validation(
        [
            "/usr/bin/python3",
            "-c",
            path_proof,
            config["runtimeRoot"],
            config["venvPython"],
            config["hermesEntry"],
            config["basePythonRoot"],
            config["rollbackRoot"],
        ],
        user=user,
        environment=environment,
        capture=True,
    )

    for profile in config["profiles"]:
        profile_uid = pwd.getpwnam(profile["user"]).pw_uid
        profile_identity = run_validation(
            ["/usr/bin/id", "-u"],
            user=profile["user"],
            environment={"PATH": "/usr/bin:/bin"},
            capture=True,
        )
        try:
            observed_profile_uid = int((profile_identity.stdout or "").strip())
        except ValueError as exc:
            raise TransactionError(
                f"profile identity proof is invalid: {profile['name']}"
            ) from exc
        if observed_profile_uid != profile_uid:
            raise TransactionError(
                f"profile identity mismatch: {profile['name']}"
            )
        for path in (profile["accountHome"], profile["home"]):
            for test_flag in ("-d", "-w"):
                run_validation(
                    ["/usr/bin/test", test_flag, path],
                    user=profile["user"],
                    environment={"PATH": "/usr/bin:/bin"},
                )
        run_validation(
            ["/usr/bin/test", "-f", str(Path(profile["home"]) / "config.yaml")],
            user=profile["user"],
            environment={"PATH": "/usr/bin:/bin"},
        )

    status = run_validation(
        transaction.git_prefix() + ["status", "--porcelain"],
        user=user,
        environment=environment,
        capture=True,
    )
    if (status.stdout or "").strip():
        raise TransactionError("Hermes source checkout is not clean")
    result = {"status": "runtime-valid", "updateUid": observed_uid}
    print(json.dumps(result, sort_keys=True))
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-config", action="store_true")
    mode.add_argument("--validate-runtime", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = load_config(
            args.config,
            require_runtime_paths=args.validate_config,
        )
        if args.validate_config:
            print(json.dumps({"profiles": [item["name"] for item in config["profiles"]], "status": "valid"}, sort_keys=True))
            return 0
        if args.validate_runtime:
            validate_runtime(config)
            return 0
        lock_root = Path("/run/hermes-native-update")
        lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (lock_root / "transaction.lock").open("w", encoding="utf-8") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise TransactionError("another native update transaction is active") from exc
            NativeUpdateTransaction(config).execute()
        return 0
    except (OSError, ValueError, TransactionError, json.JSONDecodeError) as exc:
        print(f"hermes-native-update-transaction-error:{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
