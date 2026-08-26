#!/usr/bin/env python3

import json
import importlib.util
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

SCRIPT = Path(__file__).with_name("health-summary.py")
ASSEMBLER = Path(__file__).with_name("hermes-daily-summary-assemble.py")
REPOSITORY = Path(__file__).resolve().parents[2]
AUTOMATION_UNIT = (
    REPOSITORY / "templates/hermes/hermes-retained-automation@.service.j2"
)


def create_database(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
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
        connection.commit()
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
        connection.commit()


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

    def test_daily_summary_consumes_only_current_aggregate_reports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            report_json = directory / "yesterday.json"
            report_markdown = directory / "yesterday.md"
            report_json.write_text(
                json.dumps({"ok": True, "date": "2026-08-25"}),
                encoding="utf-8",
            )
            report_markdown.write_text(
                "- Yesterday, August 25: 1,000 steps.",
                encoding="utf-8",
            )

            spec = importlib.util.spec_from_file_location(
                "hermes_daily_summary_assemble_test", ASSEMBLER
            )
            module = importlib.util.module_from_spec(spec)
            self.assertIsNotNone(spec.loader)
            spec.loader.exec_module(module)
            module.HEALTH_REPORT_JSON = report_json
            module.HEALTH_REPORT_MARKDOWN = report_markdown

            output = module.deterministic_health_section(
                datetime(2026, 8, 26, 12, tzinfo=timezone.utc)
            )
            self.assertEqual(
                output,
                "## Health\n\n- Yesterday, August 25: 1,000 steps.",
            )

            report_json.write_text(
                json.dumps({"ok": True, "date": "2026-08-24"}),
                encoding="utf-8",
            )
            stale = module.deterministic_health_section(
                datetime(2026, 8, 26, 12, tzinfo=timezone.utc)
            )
            self.assertIn("aggregate report is stale or invalid", stale)

    def test_daily_summary_keeps_health_when_personal_input_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            report_json = directory / "yesterday.json"
            report_markdown = directory / "yesterday.md"
            output = directory / "daily-summary.md"

            spec = importlib.util.spec_from_file_location(
                "hermes_daily_summary_assemble_missing_personal_test", ASSEMBLER
            )
            module = importlib.util.module_from_spec(spec)
            self.assertIsNotNone(spec.loader)
            spec.loader.exec_module(module)
            yesterday = (
                datetime.now(timezone.utc).astimezone(module.LOCAL_TZ).date()
                - module.timedelta(days=1)
            ).isoformat()
            report_json.write_text(
                json.dumps({"ok": True, "date": yesterday}),
                encoding="utf-8",
            )
            report_markdown.write_text(
                "- Aggregate Health report is present.",
                encoding="utf-8",
            )
            module.SECTIONS = directory / "missing-sections"
            module.OUTPUT = output
            module.HEALTH_REPORT_JSON = report_json
            module.HEALTH_REPORT_MARKDOWN = report_markdown

            self.assertEqual(module.main(), 0)
            assembled = output.read_text(encoding="utf-8")
            self.assertIn("## Health", assembled)
            self.assertIn("Aggregate Health report is present", assembled)

    def test_retained_collector_cannot_read_raw_health_state(self):
        unit = AUTOMATION_UNIT.read_text(encoding="utf-8")
        self.assertIn("HERMES_HEALTH_REPORT_JSON=", unit)
        self.assertIn("HERMES_HEALTH_REPORT_MARKDOWN=", unit)
        self.assertIn("InaccessiblePaths={{ hermes_health_receiver_db }}", unit)
        self.assertNotIn("HERMES_HEALTH_DB=", unit)
        self.assertNotIn("HERMES_HEALTH_SUMMARY=", unit)


if __name__ == "__main__":
    unittest.main()
