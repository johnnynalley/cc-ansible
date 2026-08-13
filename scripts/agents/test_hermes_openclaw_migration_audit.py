#!/usr/bin/env python3
"""Regression tests for the OpenClaw-to-Hermes migration contract audit."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
SCRIPT = Path(__file__).with_name("hermes-openclaw-migration-audit.py")
CONTRACT = ROOT / "files" / "hermes" / "openclaw-state-migration-contract.json"
WORKSPACE_POLICY = ROOT / "files" / "openclaw" / "workspace-migration-policy.json"
SPEC = importlib.util.spec_from_file_location("hermes_openclaw_migration_audit", SCRIPT)
assert SPEC and SPEC.loader
audit_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit_module
SPEC.loader.exec_module(audit_module)


class HermesOpenClawMigrationAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def write_contract(self, root: Path, payload: dict[str, object]) -> Path:
        path = root / "contract.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def load(self, path: Path) -> tuple[list[object], dict[str, object]]:
        return audit_module.load_contract(path, WORKSPACE_POLICY)

    def test_canonical_contract_covers_all_workspace_dispositions(self) -> None:
        rules, summary = self.load(CONTRACT)
        self.assertEqual(
            summary["policyDispositions"],
            ["archive", "discard", "replace", "retain", "retire"],
        )
        self.assertEqual(summary["handlerCount"], 5)
        self.assertGreater(summary["policyRules"], 100)
        self.assertGreater(len(rules), 50)

    def test_metadata_inventory_reports_categories_without_file_contents(self) -> None:
        rules, _ = self.load(CONTRACT)
        with tempfile.TemporaryDirectory() as directory_name:
            source = Path(directory_name) / "state"
            source.mkdir()
            (source / ".env").write_text("do-not-read", encoding="utf-8")
            (source / "workspace").mkdir()
            (source / "tmp-probe.out").write_text("private", encoding="utf-8")
            result = audit_module.inventory_state_root(source, rules)
        self.assertEqual(result["mode"], "metadata-only")
        self.assertEqual(result["summary"]["classifiedEntries"], 3)
        self.assertEqual(result["summary"]["kinds"], {"directory": 1, "file": 2})
        serialized = json.dumps(result)
        self.assertNotIn("do-not-read", serialized)
        self.assertNotIn("private", serialized)

    def test_unknown_state_entry_fails_closed(self) -> None:
        rules, _ = self.load(CONTRACT)
        with tempfile.TemporaryDirectory() as directory_name:
            source = Path(directory_name) / "state"
            source.mkdir()
            (source / "new-unreviewed-authority").mkdir()
            with self.assertRaisesRegex(
                audit_module.MigrationAuditError, "unclassified state-root entry"
            ):
                audit_module.inventory_state_root(source, rules)

    def test_kind_drift_fails_closed(self) -> None:
        rules, _ = self.load(CONTRACT)
        with tempfile.TemporaryDirectory() as directory_name:
            source = Path(directory_name) / "state"
            source.mkdir()
            (source / "cron").write_text("not a directory", encoding="utf-8")
            with self.assertRaisesRegex(
                audit_module.MigrationAuditError, "state-root kind drift"
            ):
                audit_module.inventory_state_root(source, rules)

    def test_top_level_symlink_is_rejected(self) -> None:
        rules, _ = self.load(CONTRACT)
        with tempfile.TemporaryDirectory() as directory_name:
            source = Path(directory_name) / "state"
            outside = Path(directory_name) / "outside"
            source.mkdir()
            outside.mkdir()
            os.symlink(outside, source / "workspace")
            with self.assertRaisesRegex(
                audit_module.MigrationAuditError, "unsupported symlink"
            ):
                audit_module.inventory_state_root(source, rules)

    def test_any_source_authority_enablement_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = copy.deepcopy(self.contract)
            payload["sourceProtection"]["liveMigrationAuthorized"] = True
            with self.assertRaisesRegex(
                audit_module.MigrationAuditError, "source protection"
            ):
                self.load(self.write_contract(root, payload))

    def test_workspace_policy_hash_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = copy.deepcopy(self.contract)
            payload["workspace"]["policySha256"] = "0" * 64
            with self.assertRaisesRegex(
                audit_module.MigrationAuditError, "workspace policy hash drift"
            ):
                self.load(self.write_contract(root, payload))

    def test_missing_workspace_disposition_handler_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = copy.deepcopy(self.contract)
            del payload["workspace"]["dispositionHandlers"]["replace"]
            with self.assertRaisesRegex(
                audit_module.MigrationAuditError, "cover every disposition"
            ):
                self.load(self.write_contract(root, payload))

    def test_health_must_remain_externally_owned(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = copy.deepcopy(self.contract)
            payload["workspace"]["ruleOverrides"]["health-database"][
                "action"
            ] = "curated-import"
            with self.assertRaisesRegex(
                audit_module.MigrationAuditError, "externally owned"
            ):
                self.load(self.write_contract(root, payload))

    def test_secret_rule_cannot_become_curated_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = copy.deepcopy(self.contract)
            credential_rule = next(
                row
                for row in payload["stateRoot"]["rules"]
                if row["id"] == "credential-store"
            )
            credential_rule["action"] = "curated-import"
            credential_rule["activation"] = "post-parity"
            with self.assertRaisesRegex(
                audit_module.MigrationAuditError, "secret rule.*unsafe handling"
            ):
                self.load(self.write_contract(root, payload))

    def test_cron_must_be_rebuilt_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = copy.deepcopy(self.contract)
            cron_rule = next(
                row
                for row in payload["stateRoot"]["rules"]
                if row["id"] == "cron-state"
            )
            cron_rule["action"] = "sealed-archive"
            cron_rule["activation"] = "offline-only"
            with self.assertRaisesRegex(
                audit_module.MigrationAuditError, "cron-state must use rebuild-disabled"
            ):
                self.load(self.write_contract(root, payload))

    def test_delivery_queue_must_drain_without_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = copy.deepcopy(self.contract)
            queue_rule = next(
                row
                for row in payload["stateRoot"]["rules"]
                if row["id"] == "delivery-queue"
            )
            queue_rule["action"] = "sealed-archive"
            queue_rule["activation"] = "offline-only"
            with self.assertRaisesRegex(
                audit_module.MigrationAuditError,
                "delivery-queue must use drain-and-archive",
            ):
                self.load(self.write_contract(root, payload))

    def test_sqlite_sources_require_consistent_stopped_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = copy.deepcopy(self.contract)
            state_db = next(
                row
                for row in payload["stateRoot"]["rules"]
                if row["id"] == "state-database"
            )
            del state_db["backupMethod"]
            with self.assertRaisesRegex(
                audit_module.MigrationAuditError, "lacks consistent backup method"
            ):
                self.load(self.write_contract(root, payload))


if __name__ == "__main__":
    unittest.main()
