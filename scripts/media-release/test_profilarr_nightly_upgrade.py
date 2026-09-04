#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("profilarr_nightly_upgrade.py")
SPEC = importlib.util.spec_from_file_location("profilarr_nightly_upgrade", MODULE_PATH)
assert SPEC and SPEC.loader
NIGHTLY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NIGHTLY)


class ProfilarrNightlyUpgradeTests(unittest.TestCase):
    def test_open_uses_per_application_crons(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "profilarr.db"
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            conn.executescript(
                """
                CREATE TABLE arr_instances (
                  id INTEGER, name TEXT, type TEXT, enabled INTEGER
                );
                CREATE TABLE upgrade_configs (
                  id INTEGER, arr_instance_id INTEGER, enabled INTEGER,
                  cron TEXT, next_run_at TEXT, filters TEXT, updated_at TEXT
                );
                INSERT INTO arr_instances VALUES (1, 'Sonarr', 'sonarr', 1);
                INSERT INTO arr_instances VALUES (2, 'Radarr', 'radarr', 1);
                INSERT INTO upgrade_configs VALUES
                  (1, 1, 0, 'old', NULL, '[{"enabled":true}]', NULL),
                  (2, 2, 0, 'old', NULL, '[{"enabled":true}]', NULL);
                """
            )
            conn.commit()
            backup, opened = NIGHTLY.open_upgrade_window(
                conn,
                db,
                root / "backups",
                "0 * * * *",
                "0 18 * * *",
                "0 * * * *",
                False,
            )
            conn.commit()
            rows = dict(conn.execute("SELECT arr_instance_id, cron FROM upgrade_configs"))
            conn.close()
        self.assertIsNotNone(backup)
        self.assertEqual(opened, 2)
        self.assertEqual(rows[1], "0 18 * * *")
        self.assertEqual(rows[2], "0 * * * *")


if __name__ == "__main__":
    unittest.main()
