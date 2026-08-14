#!/usr/bin/env python3
"""Regression tests for the bounded Hermes Warframe feed."""

from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo


SCRIPT = Path(__file__).with_name("hermes-warframe-feed-collect.py")
REMINDER = Path(__file__).with_name("hermes-warframe-reminder-watch.py")
sys.path.insert(0, str(REMINDER.parent))
REMINDER_SPEC = importlib.util.spec_from_file_location(
    "hermes_warframe_reminder", REMINDER
)
REMINDER_MODULE = importlib.util.module_from_spec(REMINDER_SPEC)
assert REMINDER_SPEC and REMINDER_SPEC.loader
REMINDER_SPEC.loader.exec_module(REMINDER_MODULE)
SPEC = importlib.util.spec_from_file_location("hermes_warframe_feed", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)
CT = ZoneInfo("America/Chicago")


def event(drop="Agkani Stone"):
    return {
        "event_id": "20260816T2000-weekend-drop-snootydeath",
        "title": "Warframe Weekend Drop - SnootyDeath",
        "kind": "weekend",
        "starts_at_ct": "2026-08-16T20:00:00-05:00",
        "ends_at_ct": "2026-08-16T21:00:00-05:00",
        "channel_url": "https://twitch.tv/example",
        "drop_summary": drop,
        "source_title": "Official schedule",
        "source_link": "https://forums.warframe.com/example",
        "notes": "Official event.",
    }


class WarframeAutomationTests(unittest.TestCase):
    def test_parser_style_uppercase_timestamp_id_is_accepted(self):
        value = MODULE.normalize(event(), datetime(2026, 8, 14, tzinfo=CT))
        self.assertEqual(
            value["eventId"],
            "20260816T2000-weekend-drop-snootydeath",
        )
        self.assertEqual(value["dropSummary"], "Agkani Stone")

    def test_generic_reward_is_rejected(self):
        with self.assertRaisesRegex(MODULE.FeedError, "generic-drop"):
            MODULE.normalize(
                event("Weekly Prime Time Twitch Drop"),
                datetime(2026, 8, 14, tzinfo=CT),
            )

    def test_calendar_marker_is_persisted_in_created_event(self):
        normalized = MODULE.normalize(event(), datetime(2026, 8, 14, tzinfo=CT))
        with mock.patch.object(MODULE.subprocess, "run") as runner:
            MODULE.calendar_add(normalized)
        argv = runner.call_args.args[0]
        self.assertEqual(argv[0], "/usr/bin/khal")
        self.assertIn(f"Managed-ID: {normalized['eventId']}", argv[-1])

    def test_existing_calendar_marker_repairs_state_without_duplicate(self):
        normalized = MODULE.normalize(event(), datetime(2026, 8, 14, tzinfo=CT))
        state = {"schemaVersion": 1, "events": {}}
        with (
            tempfile.TemporaryDirectory() as temporary,
            mock.patch.object(MODULE, "calendar_contains", return_value=True),
            mock.patch.object(MODULE, "calendar_add") as add,
        ):
            state_path = Path(temporary) / "state.json"
            MODULE.synchronize_calendars(
                [normalized], state, datetime(2026, 8, 14, tzinfo=CT), state_path
            )
            stored = json.loads(state_path.read_text(encoding="utf-8"))
        add.assert_not_called()
        self.assertIn(
            "calendarSyncedAt",
            stored["events"][normalized["eventId"]],
        )

    def test_missing_reminder_source_is_private_and_silent(self):
        with tempfile.TemporaryDirectory() as temporary:
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.dict(
                    os.environ,
                    {"HERMES_HOME": temporary, "HOME": temporary},
                ),
                mock.patch.object(
                    REMINDER_MODULE,
                    "SOURCE",
                    Path(temporary) / "missing.json",
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                result = REMINDER_MODULE.main()
            health = json.loads(
                (Path(temporary) / "state" / "warframe-reminder-health.json")
                .read_text(encoding="utf-8")
            )
        self.assertEqual(result, 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        self.assertFalse(health["healthy"])
        self.assertEqual(health["status"], "source-unavailable")


if __name__ == "__main__":
    unittest.main()
