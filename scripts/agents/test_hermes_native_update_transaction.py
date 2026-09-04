#!/usr/bin/env python3
"""Regression tests for the minimal native Hermes update boundary."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
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
        "version": 3,
        "updateUser": "hermes-astra",
        "runtimeRoot": "/runtime",
        "venvPython": "/runtime/venv/bin/python",
        "hermesEntry": "/runtime/hermes",
        "updateBranch": "main",
        "systemdWaitSeconds": 120,
        "updateAccountHome": "/var/lib/hermes/astra",
        "updateProfileHome": "/var/lib/hermes/astra/profile",
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
    def __init__(self, native_returncode: int = 0, restore_failures=None):
        super().__init__(config())
        self.native_returncode = native_returncode
        self.restore_failures = restore_failures or []
        self.calls: list[str] = []

    def require_native_source(self):
        self.calls.append("source")

    def inspect_active_profiles(self):
        self.calls.append("inspect")
        return self.config["profiles"]

    def prepare_all_markers(self):
        self.calls.append("markers")

    def stop_active_profiles(self):
        self.calls.append("stop")
        self.stopped = list(self.active)

    def run_native_update(self):
        self.calls.append("native")
        return self.native_returncode

    def migrate_profile_configs(self):
        self.calls.append("migrate")

    def restore_active_profiles(self):
        self.calls.append("restore")
        return list(self.restore_failures)


class HermesNativeUpdateTransactionTests(unittest.TestCase):
    def test_contract_contains_only_native_lifecycle_inputs(self) -> None:
        data = config()
        self.assertEqual(set(data), MODULE.REQUIRED_KEYS)
        serialized = json.dumps(data)
        for forbidden in (
            "managedSourcePatcher",
            "queuedEventPatch",
            "queuedEventValidator",
            "memoryDependencyUpdater",
            "stableDependencies",
            "postSetupKeys",
            "rollback",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_load_config_rejects_private_update_extensions(self) -> None:
        data = config()
        data["managedSourcePatcher"] = "/private/patcher"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "contract"):
                MODULE.load_config(path, require_runtime_paths=False)

    def test_user_commands_use_hardened_systemd_delegation(self) -> None:
        transaction = MODULE.NativeUpdateTransaction(config())
        current_user = MODULE.pwd.getpwuid(os.getuid()).pw_name
        completed = MODULE.subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with mock.patch.object(MODULE.subprocess, "run", return_value=completed) as run:
            transaction._run_as_user(
                ["/usr/bin/true"],
                user=current_user,
                environment={"PATH": "/usr/bin:/bin"},
                writable_paths=["/var/lib/test-profile"],
                timeout=60,
                capture=True,
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
        self.assertIn("--property=ReadWritePaths=/var/lib/test-profile", command)
        self.assertEqual(command[-2:], ["--", "/usr/bin/true"])
        self.assertTrue(run.call_args.kwargs["capture_output"])
        self.assertEqual(run.call_args.kwargs["timeout"], 90)

    def test_native_update_is_the_only_update_operation(self) -> None:
        transaction = MODULE.NativeUpdateTransaction(config())
        completed = MODULE.subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with mock.patch.object(transaction, "run", return_value=completed) as run:
            self.assertEqual(transaction.run_native_update(), 0)

        command = run.call_args.args[0]
        self.assertEqual(
            command,
            [
                "/runtime/venv/bin/python",
                "/runtime/hermes",
                "update",
                "--yes",
                "--backup",
                "--branch",
                "main",
                "--switch-branch",
            ],
        )
        self.assertEqual(run.call_args.kwargs["user"], "hermes-astra")
        self.assertEqual(
            run.call_args.kwargs["writable_paths"],
            ["/runtime", "/var/lib/hermes/astra", "/var/lib/hermes/astra/profile"],
        )
        self.assertFalse(run.call_args.kwargs["check"])
        self.assertNotIn("pip", " ".join(command))

    def test_source_gate_requires_clean_main(self) -> None:
        transaction = MODULE.NativeUpdateTransaction(config())
        clean = MODULE.subprocess.CompletedProcess([], 0, stdout="", stderr="")
        private = MODULE.subprocess.CompletedProcess(
            [], 0, stdout="astra-managed-parity\n", stderr=""
        )
        with mock.patch.object(transaction, "run", side_effect=[clean, private]):
            with self.assertRaisesRegex(MODULE.TransactionError, "native update branch"):
                transaction.require_native_source()

    def test_success_uses_native_update_and_restores_gateways(self) -> None:
        transaction = FakeTransaction()
        with mock.patch.object(MODULE.os, "geteuid", return_value=0):
            result = transaction.execute()

        self.assertEqual(result["status"], "ready")
        self.assertEqual(
            transaction.calls,
            [
                "source",
                "inspect",
                "markers",
                "stop",
                "native",
                "migrate",
                "source",
                "restore",
            ],
        )
        self.assertNotIn("rollback", transaction.calls)
        self.assertNotIn("reconcile", transaction.calls)

    def test_native_failure_still_restores_gateways(self) -> None:
        transaction = FakeTransaction(native_returncode=7)
        with (
            mock.patch.object(MODULE.os, "geteuid", return_value=0),
            self.assertRaisesRegex(MODULE.TransactionError, "returned 7"),
        ):
            transaction.execute()
        self.assertEqual(
            transaction.calls,
            ["source", "inspect", "markers", "stop", "native", "restore"],
        )

    def test_each_isolated_profile_uses_native_noninteractive_migration(self) -> None:
        transaction = MODULE.NativeUpdateTransaction(config())
        completed = MODULE.subprocess.CompletedProcess([], 0, stdout="{}", stderr="")
        with mock.patch.object(transaction, "run", return_value=completed) as run:
            transaction.migrate_profile_configs()

        self.assertEqual(run.call_count, 3)
        for call, profile in zip(run.call_args_list, transaction.config["profiles"]):
            command = call.args[0]
            self.assertEqual(command[:2], ["/runtime/venv/bin/python", "-c"])
            self.assertIn("migrate_config(interactive=False, quiet=True)", command[2])
            self.assertIn("after >= expected", command[2])
            self.assertEqual(call.kwargs["user"], profile["user"])
            self.assertEqual(
                call.kwargs["environment"]["HERMES_HOME"], profile["home"]
            )
            self.assertEqual(
                call.kwargs["writable_paths"],
                [profile["accountHome"], profile["home"]],
            )
            other_homes = {
                other["home"]
                for other in transaction.config["profiles"]
                if other["name"] != profile["name"]
            }
            self.assertTrue(other_homes.isdisjoint(call.kwargs["writable_paths"]))
            self.assertTrue(call.kwargs["capture"])

        self.assertEqual(transaction.events, ["profile-configs-migrated"])

    def test_failed_stop_attempt_remains_in_restore_set(self) -> None:
        transaction = MODULE.NativeUpdateTransaction(config())
        transaction.active = [transaction.config["profiles"][0]]
        with (
            mock.patch.object(
                transaction,
                "run",
                side_effect=MODULE.TransactionError("stop command failed"),
            ),
            self.assertRaisesRegex(MODULE.TransactionError, "stop command failed"),
        ):
            transaction.stop_active_profiles()

        self.assertEqual(transaction.stopped, transaction.active)

    def test_restore_failure_is_never_hidden(self) -> None:
        transaction = FakeTransaction(
            restore_failures=["hermes-gateway-rigel.service"]
        )
        with (
            mock.patch.object(MODULE.os, "geteuid", return_value=0),
            self.assertRaisesRegex(MODULE.TransactionError, "rigel"),
        ):
            transaction.execute()


if __name__ == "__main__":
    unittest.main()
