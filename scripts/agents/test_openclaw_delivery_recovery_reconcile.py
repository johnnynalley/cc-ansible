#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name(
    "openclaw-delivery-recovery-reconcile.py"
)
SPEC = importlib.util.spec_from_file_location(
    "openclaw_delivery_recovery_reconcile", MODULE_PATH
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class DeliveryRecoveryReconcileTests(unittest.TestCase):
    def _index(self, root: Path) -> Path:
        path = root / "sessions.json"
        path.write_text(
            json.dumps(
                {
                    "active": {
                        "sessionId": "one",
                        "pendingFinalDelivery": True,
                        "pendingFinalDeliveryText": "private",
                    },
                    "clean": {"sessionId": "two"},
                    "archived": {
                        "archivedAt": 1,
                        "pendingFinalDelivery": True,
                    },
                }
            ),
            encoding="utf-8",
        )
        path.chmod(0o600)
        return path

    def test_inventory_is_content_free_and_ignores_archived_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            path = self._index(Path(directory_name))
            payload = json.loads(path.read_text(encoding="utf-8"))
            records = MODULE.inventory(payload)
            self.assertEqual(len(records), 1)
            self.assertEqual(
                records[0]["fields"],
                ["pendingFinalDelivery", "pendingFinalDeliveryText"],
            )
            self.assertNotIn("private", json.dumps(records))

    def test_exact_fingerprint_reconciles_with_private_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            path = self._index(root)
            original = path.read_bytes()
            payload = json.loads(original)
            fingerprint = MODULE.inventory(payload)[0]["fingerprint"]
            backup = root / "before.json"

            report = MODULE.reconcile(path, {fingerprint}, backup)

            self.assertEqual(report["status"], "reconciled")
            self.assertEqual(report["entries"], 1)
            self.assertEqual(backup.read_bytes(), original)
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            updated = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("pendingFinalDelivery", updated["active"])
            self.assertNotIn("pendingFinalDeliveryText", updated["active"])
            self.assertIn("pendingFinalDelivery", updated["archived"])

    def test_mismatch_fails_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            path = self._index(root)
            original = path.read_bytes()
            with self.assertRaises(MODULE.ReconciliationError):
                MODULE.reconcile(path, {"0" * 64}, root / "before.json")
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse((root / "before.json").exists())

    def test_cli_inspect_writes_no_message_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            path = self._index(root)
            output = root / "inspection.json"
            result = subprocess.run(
                [
                    str(MODULE_PATH),
                    "--mode",
                    "inspect",
                    "--session-index",
                    str(path),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("private", result.stdout)
            self.assertNotIn("private", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
