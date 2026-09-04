#!/usr/bin/env python3
"""Focused contract tests for Astra's typed read-only Arr reports."""

from __future__ import annotations

import importlib.util
import json
import stat
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PLUGIN = load_module(
    "hermes_host_admin_arr_plugin",
    ROOT / "files/hermes/plugins/host-admin/__init__.py",
)
TARGET = load_module(
    "hermes_host_admin_arr_target",
    ROOT / "scripts/agents/hermes-host-admin-target.py",
)


class ArrReadonlyReportContractTests(unittest.TestCase):
    def test_plugin_exposes_only_fixed_arr_health_probes(self) -> None:
        self.assertEqual(
            sorted(probe for probe in PLUGIN._PROBES if probe.startswith("arr-")),
            ["arr-policy", "arr-queue", "arr-storage", "arr-transactions"],
        )
        self.assertFalse(any(action.startswith("arr-") for action in PLUGIN._ACTIONS))

    @mock.patch.object(TARGET, "canonical_host", return_value="docker-vm")
    @mock.patch.object(TARGET.os, "lstat")
    @mock.patch.object(TARGET, "run")
    def test_target_returns_validated_report_body(
        self, run: mock.Mock, lstat: mock.Mock, _host: mock.Mock
    ) -> None:
        lstat.return_value = SimpleNamespace(st_mode=stat.S_IFREG | 0o555, st_uid=0)
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "schemaVersion": 1,
                    "status": "ok",
                    "body": {"report": "arr-queue", "liveQueue": {"queue_count": 2}},
                }
            ),
        )

        body = TARGET.arr_report_probe("arr-queue")

        self.assertEqual(body["report"], "arr-queue")
        run.assert_called_once_with(
            [str(TARGET.ARR_REPORTER), "--report", "queue"], timeout=130
        )

    @mock.patch.object(TARGET, "canonical_host", return_value="docker-vm")
    @mock.patch.object(TARGET.os, "lstat")
    @mock.patch.object(TARGET, "run")
    def test_target_rejects_report_name_mismatch(
        self, run: mock.Mock, lstat: mock.Mock, _host: mock.Mock
    ) -> None:
        lstat.return_value = SimpleNamespace(st_mode=stat.S_IFREG | 0o555, st_uid=0)
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "schemaVersion": 1,
                    "status": "ok",
                    "body": {"report": "arr-storage"},
                }
            ),
        )

        with self.assertRaisesRegex(TARGET.AdminError, "invalid-response"):
            TARGET.arr_report_probe("arr-queue")

    def test_playbook_deploys_both_docker_vm_helpers(self) -> None:
        playbook = (ROOT / "playbooks/agents/hermes-host-admin.yml").read_text()
        variables = (ROOT / "inventory/group_vars/all/hermes-host-admin.yml").read_text()

        for name in (
            "hermes_host_admin_arr_reporter_live",
            "hermes_host_admin_transaction_audit_live",
        ):
            self.assertIn(name, playbook)
            self.assertIn(name, variables)


if __name__ == "__main__":
    unittest.main()
