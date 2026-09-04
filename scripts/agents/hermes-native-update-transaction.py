#!/usr/bin/env python3
"""Run Hermes's native updater across root-managed Gateway services."""

from __future__ import annotations

import argparse
import fcntl
import grp
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
from typing import Any


PROFILE_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
UNIT_RE = re.compile(r"^hermes-gateway-[a-z][a-z0-9-]{0,31}\.service$")
REQUIRED_KEYS = {
    "version",
    "updateUser",
    "runtimeRoot",
    "venvPython",
    "hermesEntry",
    "updateBranch",
    "systemdWaitSeconds",
    "updateAccountHome",
    "updateProfileHome",
    "profiles",
}


class TransactionError(RuntimeError):
    """A bounded native update transaction failed."""


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
    if data["version"] != 3:
        raise ValueError("unsupported transaction config version")
    if data["updateUser"] != "hermes-astra":
        raise ValueError("updateUser must be hermes-astra")
    if data["updateBranch"] != "main":
        raise ValueError("updateBranch must follow Hermes main")
    if (
        not isinstance(data["systemdWaitSeconds"], int)
        or not 30 <= data["systemdWaitSeconds"] <= 600
    ):
        raise ValueError("systemdWaitSeconds must be between 30 and 600")

    for field in (
        "runtimeRoot",
        "venvPython",
        "hermesEntry",
        "updateAccountHome",
        "updateProfileHome",
    ):
        absolute_path(data[field], field, require_exists=require_runtime_paths)

    if require_runtime_paths:
        runtime_root = Path(data["runtimeRoot"]).resolve(strict=True)
        entry = Path(data["hermesEntry"]).resolve(strict=True)
        venv_root = Path(data["venvPython"]).parent.parent.resolve(strict=True)
        if runtime_root not in entry.parents:
            raise ValueError("hermesEntry must remain inside runtimeRoot")
        if runtime_root not in venv_root.parents:
            raise ValueError("venv root must remain inside runtimeRoot")

    profiles = data["profiles"]
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("profiles must be nonempty")
    names: list[str] = []
    units: list[str] = []
    for profile in profiles:
        expected = {"name", "user", "group", "unit", "accountHome", "home"}
        if not isinstance(profile, dict) or set(profile) != expected:
            raise ValueError("profile keys do not match the transaction contract")
        name = profile["name"]
        if not isinstance(name, str) or not PROFILE_RE.fullmatch(name):
            raise ValueError("invalid profile name")
        if profile["user"] != f"hermes-{name}" or profile["group"] != profile["user"]:
            raise ValueError("profile identity does not match its name")
        if profile["unit"] != f"hermes-gateway-{name}.service" or not UNIT_RE.fullmatch(
            profile["unit"]
        ):
            raise ValueError("profile name and unit do not match")
        if require_runtime_paths:
            pwd.getpwnam(profile["user"])
            grp.getgrnam(profile["group"])
        absolute_path(
            profile["accountHome"],
            "profile.accountHome",
            require_exists=require_runtime_paths,
        )
        absolute_path(
            profile["home"], "profile.home", require_exists=require_runtime_paths
        )
        names.append(name)
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

    def updater_environment(self) -> dict[str, str]:
        return {
            "HOME": self.config["updateAccountHome"],
            "HERMES_HOME": self.config["updateProfileHome"],
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
            "PWD": self.config["runtimeRoot"],
        }

    def profile_environment(self, profile: dict[str, str]) -> dict[str, str]:
        return {
            "HOME": profile["accountHome"],
            "HERMES_HOME": profile["home"],
            "PATH": f"{Path(self.config['venvPython']).parent}:/usr/bin:/bin",
            "PYTHONNOUSERSITE": "1",
        }

    def _run_as_user(
        self,
        command: list[str],
        *,
        user: str,
        environment: dict[str, str] | None,
        writable_paths: list[str],
        timeout: int | None,
        capture: bool,
    ) -> subprocess.CompletedProcess[str]:
        if not command or not command[0].startswith("/"):
            raise OSError("delegated commands require an absolute executable path")
        account = pwd.getpwnam(user)
        groups = [
            grp.getgrgid(group_id).gr_name
            for group_id in os.getgrouplist(account.pw_name, account.pw_gid)
        ]
        if not writable_paths or any(not path.startswith("/") for path in writable_paths):
            raise OSError("delegated writable paths must be nonempty and absolute")
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
            f"--property=SupplementaryGroups={' '.join(groups)}",
            f"--property=ReadWritePaths={' '.join(dict.fromkeys(writable_paths))}",
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
        )

    def run(
        self,
        argv: list[str],
        *,
        user: str | None = None,
        environment: dict[str, str] | None = None,
        writable_paths: list[str] | None = None,
        check: bool = True,
        timeout: int | None = None,
        capture: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        try:
            if user is None:
                completed = subprocess.run(
                    list(argv),
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                    timeout=timeout,
                    capture_output=capture,
                    env=environment,
                )
            else:
                if writable_paths is None:
                    raise TransactionError("delegated command requires explicit writable paths")
                completed = self._run_as_user(
                    list(argv),
                    user=user,
                    environment=environment,
                    writable_paths=writable_paths,
                    timeout=timeout,
                    capture=capture,
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
                f"command failed ({Path(argv[0]).name}): {completed.returncode}{detail}"
            )
        return completed

    def git_prefix(self) -> list[str]:
        root = self.config["runtimeRoot"]
        return ["/usr/bin/git", "-c", f"safe.directory={root}", "-C", root]

    def update_writable_paths(self) -> list[str]:
        return [
            self.config["runtimeRoot"],
            self.config["updateAccountHome"],
            self.config["updateProfileHome"],
        ]

    @staticmethod
    def profile_writable_paths(profile: dict[str, str]) -> list[str]:
        return [profile["accountHome"], profile["home"]]

    def require_native_source(self) -> None:
        environment = self.updater_environment()
        user = self.config["updateUser"]
        status = self.run(
            self.git_prefix() + ["status", "--porcelain"],
            user=user,
            environment=environment,
            writable_paths=self.update_writable_paths(),
            capture=True,
        )
        branch = self.run(
            self.git_prefix() + ["branch", "--show-current"],
            user=user,
            environment=environment,
            writable_paths=self.update_writable_paths(),
            capture=True,
        )
        if (status.stdout or "").strip():
            raise TransactionError("Hermes source checkout is not clean")
        if (branch.stdout or "").strip() != self.config["updateBranch"]:
            raise TransactionError("Hermes source checkout is not on the native update branch")

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
                raise TransactionError(
                    f"Gateway is in transitional state: {profile['unit']}={state}"
                )
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
            "import json,sys; from pathlib import Path; "
            "from gateway.status import write_planned_stop_marker; "
            "paths=[Path(item) for item in sys.argv[2:]]; "
            "[path.unlink(missing_ok=True) for path in paths]; "
            "ok=write_planned_stop_marker(int(sys.argv[1])); "
            "print(json.dumps({'ok':bool(ok)})); "
            "raise SystemExit(0 if ok else 1)"
        )
        self.run(
            [
                self.config["venvPython"],
                "-c",
                code,
                str(pid),
                *[str(path) for path in self.marker_paths(profile)],
            ],
            user=profile["user"],
            environment=self.profile_environment(profile),
            writable_paths=self.profile_writable_paths(profile),
            capture=True,
        )

    def prepare_all_markers(self) -> None:
        for profile in self.active:
            self.prepare_marker(profile, self.main_pid(profile))
        self.events.append("markers-prepared")

    def stop_active_profiles(self) -> None:
        for profile in self.active:
            # Once a stop is attempted, restoration must cover the unit even if
            # systemctl reports failure after partially changing its state.
            self.stopped.append(profile)
            self.run(
                ["/usr/bin/systemctl", "stop", profile["unit"]],
                timeout=self.config["systemdWaitSeconds"],
            )
            state = self.run(
                ["/usr/bin/systemctl", "is-active", profile["unit"]],
                check=False,
                capture=True,
            )
            if (state.stdout or "").strip() not in {"inactive", "failed"}:
                raise TransactionError(f"Gateway did not stop: {profile['unit']}")
        self.events.append("gateways-stopped")

    def run_native_update(self) -> int:
        completed = self.run(
            [
                self.config["venvPython"],
                self.config["hermesEntry"],
                "update",
                "--yes",
                "--backup",
                "--branch",
                self.config["updateBranch"],
                "--switch-branch",
            ],
            user=self.config["updateUser"],
            environment=self.updater_environment(),
            writable_paths=self.update_writable_paths(),
            check=False,
            timeout=3600,
        )
        self.events.append("native-update-finished")
        return completed.returncode

    def migrate_profile_configs(self) -> None:
        code = """import json
from hermes_cli.config import check_config_version, migrate_config

before, latest = check_config_version()
if before < latest:
    migrate_config(interactive=False, quiet=True)
after, expected = check_config_version()
print(json.dumps({"before": before, "after": after, "latest": expected}))
raise SystemExit(0 if after >= expected else 2)
"""
        for profile in self.config["profiles"]:
            self.run(
                [self.config["venvPython"], "-c", code],
                user=profile["user"],
                environment=self.profile_environment(profile),
                writable_paths=self.profile_writable_paths(profile),
                timeout=300,
                capture=True,
            )
        self.events.append("profile-configs-migrated")

    def restore_active_profiles(self) -> list[str]:
        failures: list[str] = []
        for profile in self.stopped:
            self.run(["/usr/bin/systemctl", "reset-failed", profile["unit"]], check=False)
            started = self.run(
                ["/usr/bin/systemctl", "start", profile["unit"]],
                check=False,
                timeout=self.config["systemdWaitSeconds"],
            )
            state = self.run(
                ["/usr/bin/systemctl", "is-active", profile["unit"]],
                check=False,
                capture=True,
            )
            if started.returncode != 0 or (state.stdout or "").strip() != "active":
                failures.append(profile["unit"])
        for profile in self.active:
            self.run(
                ["/usr/bin/rm", "-f", *[str(path) for path in self.marker_paths(profile)]],
                user=profile["user"],
                environment=self.profile_environment(profile),
                writable_paths=self.profile_writable_paths(profile),
                check=False,
            )
        self.events.append("gateways-restored")
        return failures

    def execute(self) -> dict[str, Any]:
        if os.geteuid() != 0:
            raise TransactionError("transaction must run as root")
        self.require_native_source()
        self.active = self.inspect_active_profiles()
        native_returncode = 0
        failure: Exception | None = None
        try:
            self.prepare_all_markers()
            self.stop_active_profiles()
            native_returncode = self.run_native_update()
            if native_returncode != 0:
                raise TransactionError(f"native Hermes updater returned {native_returncode}")
            self.migrate_profile_configs()
            self.require_native_source()
        except Exception as exc:
            failure = exc
        finally:
            restore_failures = self.restore_active_profiles()

        result = {
            "activeProfiles": [profile["name"] for profile in self.active],
            "events": self.events,
            "nativeReturnCode": native_returncode,
            "restoreFailures": restore_failures,
            "status": "ready" if failure is None and not restore_failures else "failed",
        }
        print(json.dumps(result, sort_keys=True))
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
    identity = transaction.run(
        ["/usr/bin/id", "-u"],
        user=user,
        environment=transaction.updater_environment(),
        capture=True,
        timeout=30,
    )
    try:
        observed_uid = int((identity.stdout or "").strip())
    except ValueError as exc:
        raise TransactionError("native updater identity proof is invalid") from exc
    if observed_uid != pwd.getpwnam(user).pw_uid:
        raise TransactionError("native updater identity mismatch")

    for flag, field in (
        ("-d", "runtimeRoot"),
        ("-x", "venvPython"),
        ("-f", "hermesEntry"),
    ):
        transaction.run(
            ["/usr/bin/test", flag, config[field]],
            user=user,
            environment=transaction.updater_environment(),
            timeout=30,
        )
    transaction.require_native_source()
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
        config = load_config(args.config, require_runtime_paths=True)
        if args.validate_config:
            print(
                json.dumps(
                    {
                        "profiles": [item["name"] for item in config["profiles"]],
                        "status": "valid",
                    },
                    sort_keys=True,
                )
            )
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
