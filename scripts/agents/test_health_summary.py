#!/usr/bin/env python3

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("health-summary.py")


def create_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE health_metrics (
                metric_name TEXT NOT NULL,
                value REAL,
                unit TEXT,
                date_start TEXT,
                date_end TEXT,
                source TEXT,
                raw_json TEXT
            );
            CREATE TABLE workouts (
                workout_type TEXT,
                duration_minutes REAL,
                calories REAL,
                distance REAL,
                distance_unit TEXT,
                date_start TEXT,
                date_end TEXT,
                source TEXT,
                raw_json TEXT
            );
            CREATE TABLE sleep (
                sleep_state TEXT,
                date_start TEXT,
                date_end TEXT,
                duration_minutes REAL,
                source TEXT,
                raw_json TEXT
            );
            """)
        row = (
            "step_count",
            100,
            "count",
            "2026-08-08 12:00:00 -0500",
            "2026-08-08 12:01:00 -0500",
            "private-device-name",
            '{"secret":"must-not-appear"}',
        )
        connection.executemany(
            "INSERT INTO health_metrics VALUES (?, ?, ?, ?, ?, ?, ?)",
            [row, row],
        )


class HealthSummaryTests(unittest.TestCase):
    def test_report_is_aggregate_only_and_atomic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            database = directory / "health.db"
            output = directory / "summary.json"
            create_database(database)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--date",
                    "2026-08-08",
                    "--db-path",
                    str(database),
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.stat().st_mode & 0o777, 0o640)

            report_text = output.read_text(encoding="utf-8")
            report = json.loads(report_text)
            steps = report["totals"]["step_count"]
            self.assertEqual(report["schemaVersion"], 1)
            self.assertEqual(steps["total"], 100)
            self.assertEqual(steps["rawTotal"], 200)
            self.assertEqual(steps["rows"], 1)
            self.assertEqual(steps["rawRows"], 2)
            self.assertNotIn("database", report)
            self.assertNotIn("private-device-name", report_text)
            self.assertNotIn("must-not-appear", report_text)

    def test_missing_database_error_does_not_disclose_path(self):
        missing = Path("/tmp/private-health-location/missing.db")
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--db-path",
                str(missing),
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(str(missing), result.stdout)
        self.assertEqual(
            json.loads(result.stdout)["error"], "health database is unavailable"
        )


if __name__ == "__main__":
    unittest.main()
