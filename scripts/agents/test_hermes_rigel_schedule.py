#!/usr/bin/env python3
"""Regression tests for the deterministic Hermes Rigel schedule."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT = Path(__file__).with_name("hermes-rigel-schedule.py")
SPEC = importlib.util.spec_from_file_location("hermes_rigel_schedule", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

NOW = datetime(2026, 8, 12, 15, 0, tzinfo=timezone.utc)


def source(*, status: str = "active", events: list | None = None) -> dict:
    return {
        "schemaVersion": 1,
        "timezone": "America/Chicago",
        "semester": {
            "id": "example-term",
            "status": status,
            "startsOn": "2026-08-01",
            "endsOn": "2026-12-20",
        },
        "events": events or [],
        "calendarRequests": [],
    }


def event(starts_at: str = "2026-08-15T10:00:00-05:00") -> dict:
    return {
        "id": "course-exam-1",
        "course": "COURSE 1000",
        "title": "First exam",
        "startsAt": starts_at,
        "status": "scheduled",
        "source": {"kind": "syllabus", "reference": "course/syllabus"},
    }


class HermesRigelScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.source_root = (
            self.home / "transformed-managed" / "imports" / "courses"
        )
        self.source_root.mkdir(parents=True)
        (self.home / "state").mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_source(self, value: dict) -> None:
        (self.source_root / "academic-state.json").write_text(
            json.dumps(value),
            encoding="utf-8",
        )

    def health(self) -> dict:
        return json.loads(
            (self.home / "state" / "rigel-schedule-health.json").read_text(
                encoding="utf-8"
            )
        )

    def write_job_status(
        self,
        *,
        last_run_at: str | None = None,
        last_status: str | None = None,
        delivery_error: str | None = None,
    ) -> None:
        cron = self.home / "cron"
        cron.mkdir(exist_ok=True)
        (cron / "jobs.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "jobs": [
                        {
                            "id": "rigel-job",
                            "name": MODULE.JOB_NAME,
                            "no_agent": True,
                            "script": MODULE.JOB_SCRIPT,
                            "last_run_at": last_run_at,
                            "last_status": last_status,
                            "last_delivery_error": delivery_error,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def ledger(self) -> dict:
        return json.loads(
            (self.home / "state" / "rigel-schedule-state.json").read_text(
                encoding="utf-8"
            )
        )

    def test_missing_source_is_silent_and_records_health_error(self) -> None:
        self.assertEqual(MODULE.run(self.home, NOW), "")
        self.assertFalse(self.health()["healthy"])
        self.assertEqual(self.health()["errorCode"], "source-missing")

    def test_empty_active_semester_is_silent(self) -> None:
        self.write_source(source())
        self.assertEqual(MODULE.run(self.home, NOW), "")
        self.assertEqual(self.health()["status"], "idle")

    def test_completed_semester_is_silent(self) -> None:
        completed = event()
        completed["status"] = "completed"
        self.write_source(source(status="completed", events=[completed]))
        self.assertEqual(MODULE.run(self.home, NOW), "")
        self.assertTrue(self.health()["healthy"])

    def test_due_event_emits_one_source_backed_message(self) -> None:
        self.write_source(source(events=[event()]))
        output = MODULE.run(self.home, NOW)
        self.assertEqual(
            output,
            "COURSE 1000: First exam is in 3 days (Aug 15 at 10:00 AM).",
        )
        self.assertNotIn("HEARTBEAT", output)
        self.assertNotIn("syllabus", output)
        self.assertEqual(self.health()["dueAlerts"], 1)

    def test_duplicate_tick_is_silent(self) -> None:
        self.write_source(source(events=[event()]))
        self.assertTrue(MODULE.run(self.home, NOW))
        self.assertEqual(MODULE.run(self.home, NOW), "")
        self.assertEqual(self.health()["status"], "delivery-pending")

    def test_malformed_source_is_silent_and_never_bootstraps_an_alert(self) -> None:
        malformed = source(events=[event()])
        malformed["events"][0].pop("source")
        self.write_source(malformed)
        self.assertEqual(MODULE.run(self.home, NOW), "")
        self.assertFalse(self.health()["healthy"])
        self.assertEqual(self.health()["errorCode"], "event-schema")

    def test_restart_uses_persistent_dedupe_ledger(self) -> None:
        self.write_source(source(events=[event()]))
        self.assertTrue(MODULE.run(self.home, NOW))
        ledger = self.home / "state" / "rigel-schedule-state.json"
        self.assertEqual(stat.S_IMODE(ledger.stat().st_mode), 0o600)
        self.assertEqual(MODULE.run(self.home, NOW), "")

    def test_delivery_is_not_committed_before_native_confirmation(self) -> None:
        self.write_job_status()
        self.write_source(source(events=[event()]))
        self.assertTrue(MODULE.run(self.home, NOW))
        self.assertEqual(self.ledger()["emitted"], {})
        self.assertIsNotNone(self.ledger()["pending"])

        completed = (NOW + timedelta(minutes=1)).isoformat()
        self.write_job_status(last_run_at=completed, last_status="ok")
        self.assertEqual(MODULE.run(self.home, NOW + timedelta(minutes=30)), "")
        self.assertEqual(len(self.ledger()["emitted"]), 1)
        self.assertIsNone(self.ledger()["pending"])

    def test_failed_native_delivery_is_retried(self) -> None:
        self.write_job_status()
        self.write_source(source(events=[event()]))
        first = MODULE.run(self.home, NOW)
        self.assertTrue(first)

        completed = (NOW + timedelta(minutes=1)).isoformat()
        self.write_job_status(
            last_run_at=completed,
            last_status="ok",
            delivery_error="temporary Discord failure",
        )
        retried = MODULE.run(self.home, NOW + timedelta(minutes=30))
        self.assertEqual(retried, first)
        self.assertEqual(self.ledger()["emitted"], {})

    def test_inactive_semester_with_scheduled_event_fails_silent(self) -> None:
        self.write_source(source(status="inactive", events=[event()]))
        self.assertEqual(MODULE.run(self.home, NOW), "")
        self.assertEqual(
            self.health()["errorCode"],
            "inactive-semester-scheduled-event",
        )

    def test_confirmed_pending_calendar_request_is_counted_not_delivered(self) -> None:
        value = source()
        value["calendarRequests"] = [
            {
                "id": "request-1",
                "summary": "Add the verified exam date",
                "confirmed": True,
                "status": "pending",
                "source": {
                    "kind": "user-confirmed",
                    "reference": "confirmed request",
                },
            }
        ]
        self.write_source(value)
        self.assertEqual(MODULE.run(self.home, NOW), "")
        self.assertEqual(self.health()["pendingCalendarRequests"], 1)

    def test_discord_mentions_are_neutralized(self) -> None:
        mentioned = event()
        mentioned["course"] = "@everyone"
        self.write_source(source(events=[mentioned]))
        output = MODULE.run(self.home, NOW)
        self.assertNotIn("@", output)
        self.assertIn("at everyone", output)

    def test_symlinked_source_is_silent(self) -> None:
        target = self.home / "target.json"
        target.write_text(json.dumps(source()), encoding="utf-8")
        (self.source_root / "academic-state.json").symlink_to(target)
        self.assertEqual(MODULE.run(self.home, NOW), "")
        self.assertFalse(self.health()["healthy"])

    def test_cli_missing_source_exits_cleanly_with_no_output(self) -> None:
        environment = os.environ.copy()
        environment["HERMES_HOME"] = str(self.home)
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_delivery_stays_bounded_without_deduping_unsent_events(self) -> None:
        events = []
        for index in range(3):
            item = event()
            item["id"] = f"exam-{index}"
            item["title"] = f"Exam {index} " + ("x" * 170)
            item["studyStatus"] = {
                "mastery": "not started",
                "weakAreas": ["y" * 120 for _ in range(4)],
            }
            events.append(item)
        self.write_source(source(events=events))
        self.write_job_status()
        first = MODULE.run(self.home, NOW)
        self.write_job_status(
            last_run_at=(NOW + timedelta(minutes=1)).isoformat(),
            last_status="ok",
        )
        second = MODULE.run(self.home, NOW + timedelta(minutes=30))
        self.assertLessEqual(len(first), MODULE.MAX_DELIVERY_CHARS)
        self.assertTrue(first)
        self.assertTrue(second)
        self.assertNotEqual(first, second)

    def test_prior_alert_is_not_accepted_as_event_evidence(self) -> None:
        unsupported = event()
        unsupported["source"]["kind"] = "prior-alert"
        self.write_source(source(events=[unsupported]))
        self.assertEqual(MODULE.run(self.home, NOW), "")
        self.assertEqual(self.health()["errorCode"], "event-source")

    def test_event_outside_semester_is_silent_source_error(self) -> None:
        self.write_source(source(events=[event("2027-08-15T10:00:00-05:00")]))
        self.assertEqual(MODULE.run(self.home, NOW), "")
        self.assertEqual(self.health()["errorCode"], "event-semester-range")

    def test_passed_same_day_event_is_silent(self) -> None:
        self.write_source(source(events=[event("2026-08-12T09:00:00-05:00")]))
        self.assertEqual(MODULE.run(self.home, NOW), "")
        self.assertTrue(self.health()["healthy"])


if __name__ == "__main__":
    unittest.main()
