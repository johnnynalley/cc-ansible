#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("openclaw-delivery-cutover-audit.py")
SPEC = importlib.util.spec_from_file_location(
    "openclaw_delivery_cutover_audit", MODULE_PATH
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class DeliveryCutoverAuditTests(unittest.TestCase):
    def _database(self, root: Path) -> Path:
        path = root / "openclaw.sqlite"
        connection = sqlite3.connect(path)
        connection.executescript("""
            CREATE TABLE delivery_queue_entries (
              queue_name TEXT NOT NULL,
              id TEXT NOT NULL,
              status TEXT NOT NULL,
              entry_kind TEXT,
              session_key TEXT,
              channel TEXT,
              target TEXT,
              account_id TEXT,
              retry_count INTEGER NOT NULL DEFAULT 0,
              last_attempt_at INTEGER,
              last_error TEXT,
              recovery_state TEXT,
              platform_send_started_at INTEGER,
              entry_json TEXT NOT NULL,
              enqueued_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              failed_at INTEGER,
              PRIMARY KEY (queue_name, id)
            );
            """)
        connection.commit()
        connection.close()
        return path

    def _index(self, root: Path, payload: dict | None = None) -> Path:
        path = root / "sessions.json"
        path.write_text(json.dumps(payload or {}), encoding="utf-8")
        return path

    def _insert(self, database: Path, status: str, content: str) -> None:
        connection = sqlite3.connect(database)
        connection.execute(
            """
            INSERT INTO delivery_queue_entries (
              queue_name, id, status, entry_json, enqueued_at, updated_at
            ) VALUES ('outbound', ?, ?, ?, 1, 1)
            """,
            (f"id-{status}", status, json.dumps({"text": content})),
        )
        connection.commit()
        connection.close()

    def test_clean_state_retains_failed_history_as_non_replayable(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            database = self._database(root)
            self._insert(database, "failed", "historical private content")
            index = self._index(root)

            report = MODULE.audit_delivery_state(database, {"main": index})

            self.assertEqual(report["status"], "clean")
            self.assertEqual(report["database"]["pending"], 0)
            self.assertEqual(report["database"]["failedHistory"], 1)
            self.assertNotIn("historical private content", json.dumps(report))

    def test_pending_database_and_active_session_state_block_cutover(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            database = self._database(root)
            self._insert(database, "pending", "private queued reply")
            index = self._index(
                root,
                {
                    "agent:main:main": {
                        "sessionId": "one",
                        "pendingFinalDelivery": True,
                        "pendingFinalDeliveryText": "private session reply",
                        "restartRecoveryDeliveryRunId": "run-one",
                    },
                    "agent:main:archived": {
                        "sessionId": "old",
                        "archivedAt": 1,
                        "pendingFinalDelivery": True,
                    },
                },
            )

            report = MODULE.audit_delivery_state(database, {"main": index})

            self.assertEqual(report["status"], "blocked")
            self.assertEqual(
                report["blockers"],
                [
                    "pending-database-delivery",
                    "active-session-delivery-recovery",
                ],
            )
            self.assertEqual(report["database"]["pending"], 1)
            self.assertEqual(report["sessions"]["activeRecoveryEntries"], 1)
            self.assertEqual(
                report["sessions"]["activeRecoveryFields"],
                {
                    "pendingFinalDelivery": 1,
                    "pendingFinalDeliveryText": 1,
                    "restartRecoveryDeliveryRunId": 1,
                },
            )
            encoded = json.dumps(report)
            self.assertNotIn("private queued reply", encoded)
            self.assertNotIn("private session reply", encoded)

    def test_unknown_status_and_schema_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            database = self._database(root)
            index = self._index(root)
            self._insert(database, "sending", "unknown")
            with self.assertRaises(MODULE.DeliveryAuditError):
                MODULE.audit_delivery_state(database, {"main": index})

            connection = sqlite3.connect(database)
            connection.execute("DROP TABLE delivery_queue_entries")
            connection.commit()
            connection.close()
            with self.assertRaises(MODULE.DeliveryAuditError):
                MODULE.audit_delivery_state(database, {"main": index})

    def test_symlinked_session_index_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            database = self._database(root)
            index = self._index(root)
            link = root / "linked-sessions.json"
            link.symlink_to(index)
            with self.assertRaises(MODULE.DeliveryAuditError):
                MODULE.audit_delivery_state(database, {"main": link})

    def test_cli_writes_private_report_and_require_clean_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            database = self._database(root)
            self._insert(database, "pending", "private")
            index = self._index(root)
            output = root / "report.json"

            result = subprocess.run(
                [
                    str(MODULE_PATH),
                    "--database",
                    str(database),
                    "--session-index",
                    f"main={index}",
                    "--output",
                    str(output),
                    "--require-clean",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertEqual(os.stat(output).st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(output.read_text())["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
