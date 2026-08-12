#!/usr/bin/python3
"""Tests for the redacted OpenClaw control-plane inventory."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

SCRIPT = Path(__file__).with_name("openclaw-control-plane-inventory.py")
SPEC = importlib.util.spec_from_file_location(
    "openclaw_control_plane_inventory",
    SCRIPT,
)
assert SPEC and SPEC.loader
inventory_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = inventory_module
SPEC.loader.exec_module(inventory_module)

REDACTION_SENTINEL = "DO_NOT_LEAK_CONTROL_PLANE_VALUE"


class ControlPlaneInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "openclaw.sqlite"
        with closing(sqlite3.connect(self.database_path)) as database:
            database.executescript("""
                CREATE TABLE cron_jobs (
                  store_key TEXT NOT NULL,
                  job_id TEXT NOT NULL,
                  name TEXT NOT NULL,
                  enabled INTEGER NOT NULL,
                  agent_id TEXT,
                  owner_agent_id TEXT,
                  schedule_kind TEXT NOT NULL,
                  schedule_expr TEXT,
                  schedule_tz TEXT,
                  every_ms INTEGER,
                  payload_kind TEXT NOT NULL,
                  payload_model TEXT,
                  payload_thinking TEXT,
                  payload_timeout_seconds INTEGER,
                  payload_allow_unsafe_external_content INTEGER,
                  payload_light_context INTEGER,
                  payload_tools_allow_json TEXT,
                  delivery_mode TEXT,
                  delivery_channel TEXT,
                  delivery_to TEXT,
                  delivery_account_id TEXT,
                  last_run_status TEXT,
                  last_delivery_status TEXT,
                  consecutive_errors INTEGER,
                  job_json TEXT NOT NULL,
                  sort_order INTEGER NOT NULL DEFAULT 0
                );
                """)
            job = {
                "payload": {
                    "kind": "command",
                    "argv": [
                        "/usr/bin/python3",
                        "/opt/cc-ansible/scripts/agents/example.py",
                        f"--token={REDACTION_SENTINEL}",
                    ],
                    "cwd": "/home/johnny/.openclaw/workspace",
                    "timeoutSeconds": 30,
                }
            }
            database.execute(
                """
                INSERT INTO cron_jobs VALUES (
                  'default', 'job-secret-id', 'Safe inventory job', 1,
                  'main', 'main', 'cron', '0 1 * * *', 'America/Chicago',
                  NULL, 'command', NULL, NULL, 30, 0, 1, '["exec"]',
                  'none', 'discord', 'private-recipient-id',
                  'private-account-id', 'ok', 'not-requested', 0, ?, 0
                )
                """,
                (json.dumps(job),),
            )
            database.commit()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_inventory_redacts_arguments_and_recipient_ids(self) -> None:
        result = inventory_module.inventory_database(self.database_path)
        encoded = json.dumps(result, sort_keys=True)
        self.assertNotIn(REDACTION_SENTINEL, encoded)
        self.assertNotIn("private-recipient-id", encoded)
        self.assertNotIn("private-account-id", encoded)
        self.assertNotIn("job-secret-id", encoded)
        self.assertEqual(result["summary"]["jobCount"], 1)
        job = result["jobs"][0]
        self.assertEqual(job["payload"]["command"]["argumentCount"], 3)
        self.assertEqual(job["payload"]["command"]["secretLikeArgumentCount"], 1)
        self.assertIn(
            "$REPO/scripts/agents/example.py",
            job["payload"]["command"]["pathArguments"],
        )
        self.assertEqual(
            job["payload"]["command"]["workingDirectory"],
            "$LEGACY_WORKSPACE",
        )
        self.assertTrue(job["delivery"]["hasRecipient"])
        self.assertTrue(job["delivery"]["hasAccount"])

    def test_unknown_schema_fails_closed(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as database:
            database.execute("ALTER TABLE cron_jobs RENAME TO old_cron_jobs")
            database.commit()
        with self.assertRaisesRegex(
            inventory_module.InventoryError,
            "unsupported-cron-schema",
        ):
            inventory_module.inventory_database(self.database_path)


if __name__ == "__main__":
    unittest.main()
