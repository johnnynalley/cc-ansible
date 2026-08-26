#!/usr/bin/env python3
"""Regression tests for the bounded native Hermes update transaction."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name("hermes-native-update-transaction.py")
SPEC = importlib.util.spec_from_file_location("hermes_native_update_transaction", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def config() -> dict:
    return {
        "version": 2,
        "updateUser": "hermes-astra",
        "runtimeGroup": "hermes-runtime-readers",
        "runtimeRoot": "/runtime",
        "venvPython": "/runtime/venv/bin/python",
        "hermesEntry": "/runtime/hermes",
        "hermesBinary": "/usr/local/bin/hermes",
        "uvBinary": "/bootstrap/uv",
        "basePythonRoot": "/usr/local/share/uv/python",
        "memoryDependencyUpdater": "/libexec/memory-update",
        "managedSourcePatcher": "/libexec/source-patch",
        "queuedEventPatch": "/patches/queued-event.patch",
        "queuedEventValidator": "/libexec/queued-validate",
        "sourcePatchBranch": "astra-managed-parity",
        "sourcePatchTargetBranch": "main",
        "sourcePatchStagingRoot": "/var/lib/hermes/astra/staging",
        "browserSelector": "/libexec/browser",
        "rollbackRoot": "/rollback",
        "rollbackKeep": 2,
        "minimumFreeBytes": 2147483648,
        "systemdWaitSeconds": 120,
        "updateAccountHome": "/var/lib/hermes/astra",
        "updateProfileHome": "/var/lib/hermes/astra/profile",
        "stableDependencies": ["mem0ai[nlp]", "fastembed", "ollama"],
        "spacyModel": "en_core_web_sm",
        "postSetupKeys": ["ddgs", "agent_browser"],
        "profiles": [
            {
                "name": "astra",
                "user": "hermes-astra",
                "group": "hermes-astra",
                "unit": "hermes-gateway-astra.service",
                "accountHome": "/var/lib/hermes/astra",
                "home": "/var/lib/hermes/astra/profile",
            },
            {
                "name": "dubble",
                "user": "hermes-dubble",
                "group": "hermes-dubble",
                "unit": "hermes-gateway-dubble.service",
                "accountHome": "/var/lib/hermes/dubble",
                "home": "/var/lib/hermes/dubble/profile",
            },
            {
                "name": "rigel",
                "user": "hermes-rigel",
                "group": "hermes-rigel",
                "unit": "hermes-gateway-rigel.service",
                "accountHome": "/var/lib/hermes/rigel",
                "home": "/var/lib/hermes/rigel/profile",
            },
        ],
    }


class FakeTransaction(MODULE.NativeUpdateTransaction):
    def __init__(
        self,
        native_returncode: int = 0,
        reconcile_failure: bool = False,
        rollback_failure: bool = False,
    ):
        super().__init__(config())
        self.native_returncode = native_returncode
        self.reconcile_failure = reconcile_failure
        self.rollback_failure = rollback_failure
        self.calls: list[str] = []

    def inspect_active_profiles(self):
        self.calls.append("inspect")
        return self.config["profiles"]

    def prepare_all_markers(self):
        self.calls.append("markers")

    def prepare_rollback(self):
        self.calls.append("backup")
        return {"directory": "/rollback/now"}

    def normalize_runtime_ownership(self):
        self.calls.append("ownership")

    def stop_active_profiles(self):
        self.calls.append("stop")
        self.stopped = list(self.active)

    def run_native_update(self):
        self.calls.append("native")
        return self.native_returncode

    def reconcile_runtime(self):
        self.calls.append("reconcile")
        if self.reconcile_failure:
            raise MODULE.TransactionError("reconcile failed")

    def migrate_profile_configs(self):
        self.calls.append("migrate-configs")

    def rollback_runtime(self, state):
        self.calls.append("rollback")
        if self.rollback_failure:
            raise MODULE.TransactionError("rollback failed")

    def restore_active_profiles(self):
        self.calls.append("restore")
        return []

    def prune_rollbacks(self):
        self.calls.append("prune")


class HermesNativeUpdateTransactionTests(unittest.TestCase):
    def test_user_commands_use_hardened_systemd_delegation(self) -> None:
        transaction = MODULE.NativeUpdateTransaction(config())
        current_user = MODULE.pwd.getpwuid(os.getuid()).pw_name
        completed = MODULE.subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with mock.patch.object(MODULE.subprocess, "run", return_value=completed) as run:
            transaction._run_as_user(
                ["/usr/bin/true"],
                user=current_user,
                environment={"PATH": "/usr/bin:/bin"},
                timeout=60,
                capture=True,
                input_text=None,
            )

        command = run.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/systemd-run")
        self.assertIn(f"--uid={current_user}", command)
        self.assertIn("--property=NoNewPrivileges=yes", command)
        self.assertIn("--property=CapabilityBoundingSet=", command)
        self.assertIn("--property=AmbientCapabilities=", command)
        self.assertIn("--property=ProtectSystem=strict", command)
        self.assertNotIn("--property=RestrictSUIDSGID=yes", command)
        self.assertIn("--property=RuntimeMaxSec=60s", command)
        self.assertIn("--setenv=PATH=/usr/bin:/bin", command)
        self.assertEqual(command[-2:], ["--", "/usr/bin/true"])
        self.assertFalse(any("CAP_SETUID" in item for item in command))
        self.assertFalse(any("CAP_SETGID" in item for item in command))
        self.assertNotIn("/usr/bin/setpriv", command)
        self.assertNotIn("/usr/sbin/runuser", command)
        self.assertTrue(run.call_args.kwargs["capture_output"])
        self.assertEqual(run.call_args.kwargs["timeout"], 90)

    def test_captured_command_failure_includes_bounded_detail(self) -> None:
        transaction = MODULE.NativeUpdateTransaction(config())
        completed = MODULE.subprocess.CompletedProcess(
            [], 7, stdout="", stderr="specific failure\n"
        )
        with (
            mock.patch.object(MODULE.subprocess, "run", return_value=completed),
            self.assertRaisesRegex(
                MODULE.TransactionError, "command failed .* specific failure"
            ),
        ):
            transaction.run(["/usr/bin/false"], capture=True)

    def test_reconciliation_promotes_patch_before_validation(self) -> None:
        transaction = MODULE.NativeUpdateTransaction(config())
        completed = MODULE.subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with mock.patch.object(transaction, "run", return_value=completed) as run:
            transaction.reconcile_runtime()

        commands = [call.args[0] for call in run.call_args_list]
        promotion = next(
            index
            for index, command in enumerate(commands)
            if config()["managedSourcePatcher"] in command
        )
        validation = next(
            index
            for index, command in enumerate(commands)
            if config()["queuedEventValidator"] in command
            and config()["managedSourcePatcher"] not in command
        )
        self.assertLess(promotion, validation)
        self.assertIn("--apply", commands[promotion])

    def test_runtime_ownership_drift_is_repaired_before_outage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            (root / "venv").mkdir(parents=True)
            data = config()
            data["runtimeRoot"] = str(root)
            transaction = MODULE.NativeUpdateTransaction(data)
            completed = [
                MODULE.subprocess.CompletedProcess(
                    [], 0, stdout=str(root / "venv" / "drifted"), stderr=""
                ),
                MODULE.subprocess.CompletedProcess([], 0, stdout="", stderr=""),
                MODULE.subprocess.CompletedProcess([], 0, stdout="", stderr=""),
                MODULE.subprocess.CompletedProcess([], 0, stdout="", stderr=""),
            ]
            with mock.patch.object(
                transaction, "run", side_effect=completed
            ) as run:
                transaction.normalize_runtime_ownership()

            self.assertEqual(transaction.events, ["runtime-ownership-repaired"])
            self.assertEqual(
                run.call_args_list[1],
                mock.call(
                    [
                        "/usr/bin/chown",
                        "-R",
                        "--no-dereference",
                        "hermes-astra:hermes-runtime-readers",
                        str(root / "venv"),
                    ],
                    timeout=900,
                ),
            )

    def test_rollback_validates_staged_venv_before_live_swap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            runtime = temporary / "runtime"
            live_python = runtime / "venv" / "bin" / "python"
            live_python.parent.mkdir(parents=True)
            live_python.write_text("mutated", encoding="utf-8")
            rollback = temporary / "rollback" / "20260824T163820Z"
            rollback.mkdir(parents=True)
            bundle = rollback / "hermes-source.bundle"
            archive = rollback / "hermes-venv.tar"
            bundle.touch()
            archive.touch()
            data = config()
            data["runtimeRoot"] = str(runtime)
            data["venvPython"] = str(live_python)
            data["rollbackRoot"] = str(temporary / "rollback")
            transaction = MODULE.NativeUpdateTransaction(data)
            calls: list[list[str]] = []

            def run(command, **kwargs):
                command = list(command)
                calls.append(command)
                if command[0] == "/usr/bin/mkdir":
                    Path(command[-1]).mkdir(mode=0o700)
                elif command[0] == "/usr/bin/tar" and "-xf" in command:
                    stage = Path(command[command.index("-C") + 1])
                    staged_python = stage / "venv" / "bin" / "python"
                    staged_python.parent.mkdir(parents=True)
                    staged_python.write_text("restored", encoding="utf-8")
                elif command[0] == "/usr/bin/mv":
                    shutil.move(command[-2], command[-1])
                elif command[0] == "/usr/bin/rm":
                    for value in command[4:]:
                        shutil.rmtree(value, ignore_errors=True)

                stdout = ""
                if command[0] == data["uvBinary"] and "freeze" in command:
                    stdout = "example==1\n"
                elif "rev-parse" in command:
                    stdout = "a" * 40 + "\n"
                return MODULE.subprocess.CompletedProcess(
                    command, 0, stdout=stdout, stderr=""
                )

            state = {
                "archive": archive.name,
                "archiveSha256": "b" * 64,
                "branch": "astra-managed-parity",
                "bundle": bundle.name,
                "bundleSha256": "c" * 64,
                "directory": str(rollback),
                "freeze": "example==1\n",
                "head": "a" * 40,
            }
            with (
                mock.patch.object(transaction, "run", side_effect=run),
                mock.patch.object(
                    transaction, "restore_profile_configs"
                ) as restore_profile_configs,
                mock.patch.object(
                    transaction,
                    "sha256",
                    side_effect=lambda path: (
                        state["bundleSha256"]
                        if path.name == bundle.name
                        else state["archiveSha256"]
                    ),
                ),
            ):
                transaction.rollback_runtime(state)

            restore_profile_configs.assert_called_once_with(state)

            self.assertEqual(live_python.read_text(encoding="utf-8"), "restored")
            tar_index = next(i for i, command in enumerate(calls) if command[0] == "/usr/bin/tar")
            swap_index = next(
                i
                for i, command in enumerate(calls)
                if command[:3] == ["/usr/bin/mv", "-T", str(runtime / "venv")]
            )
            self.assertLess(tar_index, swap_index)
            self.assertIn("--no-same-permissions", calls[tar_index])
            self.assertIn(
                ["/usr/bin/test", "-d", str(runtime / ".venv-rollback-20260824T163820Z" / "venv")],
                calls,
            )
            self.assertIn(
                ["/usr/bin/test", "!", "-L", str(runtime / ".venv-rollback-20260824T163820Z" / "venv")],
                calls,
            )
            self.assertIn(
                ["/usr/bin/test", "-x", str(runtime / ".venv-rollback-20260824T163820Z" / "venv" / "bin" / "python")],
                calls,
            )
            self.assertGreaterEqual(
                calls.count(["/usr/bin/test", "-x", str(runtime / "venv" / "bin" / "python")]),
                1,
            )
            self.assertFalse(
                any(
                    command[:4] == ["/usr/bin/rm", "-rf", "--", str(runtime / "venv")]
                    for command in calls[:swap_index]
                )
            )

    def test_profile_configs_are_backed_up_and_restored_by_owning_identities(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            rollback = temporary / "rollback" / "20260825T203000Z"
            rollback.mkdir(parents=True)
            data = config()
            current_uid = os.getuid()
            current_gid = os.getgid()
            originals: dict[str, str] = {}
            for profile in data["profiles"]:
                account = temporary / profile["name"]
                home = account / "profile"
                home.mkdir(parents=True)
                profile["accountHome"] = str(account)
                profile["home"] = str(home)
                content = f"_config_version: 38\nprofile: {profile['name']}\n"
                (home / "config.yaml").write_text(content, encoding="utf-8")
                (home / "config.yaml").chmod(0o600)
                originals[profile["name"]] = content
            transaction = MODULE.NativeUpdateTransaction(data)

            def inspect(path, **kwargs):
                metadata = path.lstat()
                content = path.read_bytes()
                return {
                    "gid": metadata.st_gid,
                    "mode": metadata.st_mode & 0o777,
                    "sha256": MODULE.hashlib.sha256(content).hexdigest(),
                    "text": content.decode("utf-8"),
                    "uid": metadata.st_uid,
                }

            def run(command, **kwargs):
                command = list(command)
                if command[0] == "/usr/bin/dd":
                    target = Path(command[1].removeprefix("of="))
                    target.write_text(kwargs["input_text"], encoding="utf-8")
                elif command[0] == "/usr/bin/chmod":
                    Path(command[-1]).chmod(int(command[1], 8))
                elif command[0] == "/usr/bin/mv":
                    shutil.move(command[-2], command[-1])
                elif command[:2] == ["/usr/bin/test", "-e"]:
                    return MODULE.subprocess.CompletedProcess(
                        command, 0 if Path(command[-1]).exists() else 1,
                        stdout="", stderr=""
                    )
                elif command[:2] == ["/usr/bin/test", "-L"]:
                    return MODULE.subprocess.CompletedProcess(
                        command, 0 if Path(command[-1]).is_symlink() else 1,
                        stdout="", stderr=""
                    )
                return MODULE.subprocess.CompletedProcess(
                    command, 0, stdout="", stderr=""
                )

            account = mock.Mock(pw_uid=current_uid)
            group = mock.Mock(gr_gid=current_gid)
            with (
                mock.patch.object(transaction, "run", side_effect=run),
                mock.patch.object(
                    transaction,
                    "sha256",
                    side_effect=lambda path: MODULE.hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest(),
                ),
                mock.patch.object(MODULE.pwd, "getpwnam", return_value=account),
                mock.patch.object(MODULE.grp, "getgrnam", return_value=group),
                mock.patch.object(
                    transaction,
                    "read_regular_utf8_file",
                    side_effect=inspect,
                ) as inspect_file,
            ):
                records = transaction.backup_profile_configs(rollback)
                for profile in data["profiles"]:
                    (Path(profile["home"]) / "config.yaml").write_text(
                        "_config_version: 39\nmutated: true\n",
                        encoding="utf-8",
                    )
                transaction.restore_profile_configs(
                    {"directory": str(rollback), "profileConfigs": records}
                )

            self.assertEqual(len(records), 3)
            for profile in data["profiles"]:
                config_path = Path(profile["home"]) / "config.yaml"
                self.assertEqual(
                    config_path.read_text(encoding="utf-8"),
                    originals[profile["name"]],
                )
                self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)
            self.assertIn("profile-configs-backed-up", transaction.events)
            self.assertIn("profile-configs-rolled-back", transaction.events)
            inspection_users = [call.kwargs["user"] for call in inspect_file.call_args_list]
            for profile in data["profiles"]:
                self.assertIn(profile["user"], inspection_users)
            self.assertIn(data["updateUser"], inspection_users)

    def test_native_config_migration_runs_under_each_profile_identity(self) -> None:
        transaction = MODULE.NativeUpdateTransaction(config())

        def run(command, **kwargs):
            profile_home = kwargs["environment"]["HERMES_HOME"]
            proof = {
                "after": 39,
                "before": 38,
                "config": str(Path(profile_home) / "config.yaml"),
                "latest": 39,
            }
            return MODULE.subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(proof) + "\n",
                stderr="",
            )

        with mock.patch.object(transaction, "run", side_effect=run) as runner:
            transaction.migrate_profile_configs()

        self.assertEqual(runner.call_count, 3)
        for profile, call in zip(config()["profiles"], runner.call_args_list):
            self.assertEqual(call.kwargs["user"], profile["user"])
            self.assertEqual(
                call.kwargs["environment"]["HERMES_HOME"], profile["home"]
            )
            self.assertIn(
                "migrate_config(interactive=False, quiet=True)",
                call.args[0][2],
            )
        self.assertEqual(transaction.events, ["profile-configs-migrated"])

    def test_config_restore_failure_still_attempts_runtime_rollback(self) -> None:
        transaction = MODULE.NativeUpdateTransaction(config())
        state = {"profileConfigs": [], "directory": "/rollback/20260825T203000Z"}
        with (
            mock.patch.object(
                transaction,
                "restore_profile_configs",
                side_effect=MODULE.TransactionError("config restore failed"),
            ),
            mock.patch.object(transaction, "_rollback_runtime_only") as runtime,
            self.assertRaisesRegex(MODULE.TransactionError, "config restore failed"),
        ):
            transaction.rollback_runtime(state)
        runtime.assert_called_once_with(state)

    def test_runtime_validation_proves_identity_write_scope_and_clean_source(self) -> None:
        transaction = mock.Mock()
        transaction.updater_environment.return_value = {"PATH": "/usr/bin:/bin"}
        transaction.git_prefix.return_value = ["/usr/bin/git", "-C", "/runtime"]
        def run(argv, **kwargs):
            if argv[:2] == ["/usr/bin/id", "-u"]:
                stdout = "62010\n"
            elif argv == ["/usr/bin/cat", "/proc/self/status"]:
                stdout = (
                    "CapInh:\t0000000000000000\n"
                    "CapPrm:\t0000000000000000\n"
                    "CapEff:\t0000000000000000\n"
                    "CapAmb:\t0000000000000000\n"
                    "NoNewPrivs:\t1\n"
                )
            else:
                stdout = ""
            return MODULE.subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")

        transaction.run.side_effect = run
        account = mock.Mock(pw_uid=62010)
        with (
            mock.patch.object(MODULE.os, "geteuid", return_value=0),
            mock.patch.object(MODULE.pwd, "getpwnam", return_value=account),
            mock.patch.object(
                MODULE, "NativeUpdateTransaction", return_value=transaction
            ),
        ):
            result = MODULE.validate_runtime(config())

        self.assertEqual(result["status"], "runtime-valid")
        self.assertEqual(result["updateUid"], 62010)
        self.assertGreaterEqual(transaction.run.call_count, 20)
        for call in transaction.run.call_args_list:
            self.assertEqual(
                call.kwargs["timeout"],
                MODULE.RUNTIME_VALIDATION_COMMAND_TIMEOUT_SECONDS,
            )
        for profile in config()["profiles"]:
            self.assertIn(
                mock.call(
                    ["/usr/bin/test", "-w", profile["home"]],
                    user=profile["user"],
                    environment={"PATH": "/usr/bin:/bin"},
                    timeout=MODULE.RUNTIME_VALIDATION_COMMAND_TIMEOUT_SECONDS,
                ),
                transaction.run.call_args_list,
            )

    def test_runtime_validation_rejects_dirty_source(self) -> None:
        transaction = mock.Mock()
        transaction.updater_environment.return_value = {"PATH": "/usr/bin:/bin"}
        transaction.git_prefix.return_value = ["/usr/bin/git", "-C", "/runtime"]
        def run(argv, **kwargs):
            if argv[:2] == ["/usr/bin/id", "-u"]:
                stdout = "62010\n"
            elif argv == ["/usr/bin/cat", "/proc/self/status"]:
                stdout = (
                    "CapInh:\t0000000000000000\n"
                    "CapPrm:\t0000000000000000\n"
                    "CapEff:\t0000000000000000\n"
                    "CapAmb:\t0000000000000000\n"
                    "NoNewPrivs:\t1\n"
                )
            elif argv[:3] == ["/usr/bin/git", "-C", "/runtime"]:
                stdout = " M file\n"
            else:
                stdout = ""
            return MODULE.subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")

        transaction.run.side_effect = run
        account = mock.Mock(pw_uid=62010)
        with (
            mock.patch.object(MODULE.os, "geteuid", return_value=0),
            mock.patch.object(MODULE.pwd, "getpwnam", return_value=account),
            mock.patch.object(
                MODULE, "NativeUpdateTransaction", return_value=transaction
            ),
            self.assertRaisesRegex(MODULE.TransactionError, "not clean"),
        ):
            MODULE.validate_runtime(config())

    def test_all_profiles_share_one_planned_outage_and_restore(self) -> None:
        transaction = FakeTransaction()
        with mock.patch.object(MODULE.os, "geteuid", return_value=0):
            result = transaction.execute()
        self.assertEqual(
            transaction.calls,
            [
                "inspect",
                "ownership",
                "backup",
                "markers",
                "stop",
                "native",
                "reconcile",
                "migrate-configs",
                "restore",
                "prune",
            ],
        )
        self.assertEqual(result["activeProfiles"], ["astra", "dubble", "rigel"])
        self.assertEqual(result["status"], "ready")

    def test_native_failure_rolls_back_without_reconciliation_and_restores(self) -> None:
        transaction = FakeTransaction(native_returncode=1)
        with (
            mock.patch.object(MODULE.os, "geteuid", return_value=0),
            self.assertRaisesRegex(MODULE.TransactionError, "native Hermes updater returned 1"),
        ):
            transaction.execute()
        self.assertNotIn("reconcile", transaction.calls)
        self.assertEqual(transaction.calls[-2:], ["rollback", "restore"])

    def test_reconciliation_failure_still_restores(self) -> None:
        transaction = FakeTransaction(reconcile_failure=True)
        with (
            mock.patch.object(MODULE.os, "geteuid", return_value=0),
            self.assertRaisesRegex(MODULE.TransactionError, "reconcile failed"),
        ):
            transaction.execute()
        self.assertEqual(transaction.calls[-2:], ["rollback", "restore"])

    def test_failed_rollback_holds_stopped_gateways(self) -> None:
        transaction = FakeTransaction(
            reconcile_failure=True,
            rollback_failure=True,
        )
        with (
            mock.patch.object(MODULE.os, "geteuid", return_value=0),
            self.assertRaisesRegex(MODULE.TransactionError, "Gateways held stopped"),
        ):
            transaction.execute()
        self.assertNotIn("restore", transaction.calls)
        self.assertEqual(transaction.calls[-1], "rollback")

    def test_config_rejects_profile_unit_mismatch(self) -> None:
        data = config()
        data["profiles"][2]["unit"] = "hermes-gateway-astra.service"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "profile name and unit"):
                MODULE.load_config(path, require_runtime_paths=False)

    def test_config_rejects_delegated_identity_drift(self) -> None:
        for field, value, message in (
            ("updateUser", "root", "updateUser must be hermes-astra"),
            ("runtimeGroup", "root", "runtimeGroup must be hermes-runtime-readers"),
        ):
            with self.subTest(field=field):
                data = config()
                data[field] = value
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "config.json"
                    path.write_text(json.dumps(data), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, message):
                        MODULE.load_config(path, require_runtime_paths=False)

    def test_config_rejects_prerelease_wait_shape_and_unknown_keys(self) -> None:
        data = config()
        data["unexpected"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "config keys"):
                MODULE.load_config(path, require_runtime_paths=False)


if __name__ == "__main__":
    unittest.main()
