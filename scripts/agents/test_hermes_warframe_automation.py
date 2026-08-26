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
PARSER = Path(__file__).with_name("hermes-warframe-drops-feed.py")
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
PARSER_SPEC = importlib.util.spec_from_file_location(
    "hermes_warframe_parser", PARSER
)
PARSER_MODULE = importlib.util.module_from_spec(PARSER_SPEC)
assert PARSER_SPEC and PARSER_SPEC.loader
sys.modules[PARSER_SPEC.name] = PARSER_MODULE
PARSER_SPEC.loader.exec_module(PARSER_MODULE)
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

    def test_multiline_shared_campaign_preserves_each_exact_drop(self):
        text = (
            "Twitch Drop:\n"
            "- Drop 1: Built Forma\n"
            "- Drop 2: Dax Portrait\n"
            "- Drop 3: 15 Steel Essence\n"
            "Claim Time: 30 Minutes"
        )
        self.assertEqual(
            PARSER_MODULE.extract_shared_drop_summary(text),
            "Drop 1: Built Forma; Drop 2: Dax Portrait; "
            "Drop 3: 15 Steel Essence",
        )

    def test_accented_event_kind_produces_collector_safe_id(self):
        event_id = PARSER_MODULE.make_event_id(
            "Emisión Tenno Raid",
            "Secriot_McFly",
            datetime(2026, 8, 26, 15, 0, tzinfo=CT),
        )
        self.assertEqual(
            event_id,
            "20260826T1500-emision-tenno-raid-secriot-mcfly",
        )
        candidate = event()
        candidate["event_id"] = event_id
        candidate["starts_at_ct"] = "2026-08-26T15:00:00-05:00"
        candidate["ends_at_ct"] = "2026-08-26T15:30:00-05:00"
        MODULE.normalize(candidate, datetime(2026, 8, 25, tzinfo=CT))

    def test_warframe_unit_allows_only_required_calendar_databases(self):
        unit = (
            Path(__file__).parents[2]
            / "templates/hermes/hermes-warframe-feed.service.j2"
        ).read_text(encoding="utf-8")
        self.assertIn("ReadWritePaths={{ hermes_astra_calendar_live_root }}", unit)
        self.assertIn(
            "ReadWritePaths=/var/lib/hermes/astra/.local/share/khal", unit
        )
        self.assertIn("NoNewPrivileges=true", unit)
        self.assertIn("CapabilityBoundingSet=\n", unit)

    def test_calendar_marker_is_persisted_in_created_event(self):
        normalized = MODULE.normalize(event(), datetime(2026, 8, 14, tzinfo=CT))
        with mock.patch.object(MODULE.subprocess, "run") as runner:
            MODULE.calendar_add(normalized)
        argv = runner.call_args.args[0]
        self.assertEqual(argv[0], "/usr/bin/khal")
        self.assertIn(f"Managed-ID: {normalized['eventId']}", argv[-1])

    def test_calendar_lookup_handles_khal_line_wrapping(self):
        normalized = MODULE.normalize(event(), datetime(2026, 8, 14, tzinfo=CT))
        marker = normalized["eventId"]
        with mock.patch.object(MODULE.subprocess, "run") as runner:
            runner.return_value.returncode = 0
            runner.return_value.stdout = (
                "Notes: Official event. Managed-ID:\n"
                f"{marker[:-6]}\n{marker[-6:]}\n"
            )
            runner.return_value.stderr = ""
            self.assertTrue(MODULE.calendar_contains(normalized))
        self.assertEqual(runner.call_args.args[0][-1], "20260816T2000")

    def test_existing_calendar_marker_repairs_state_without_duplicate(self):
        normalized = MODULE.normalize(event(), datetime(2026, 8, 14, tzinfo=CT))
        state = {"schemaVersion": 1, "events": {}}
        with (
            mock.patch.object(MODULE, "calendar_contains", return_value=True),
            mock.patch.object(MODULE, "calendar_add") as add,
        ):
            pending = MODULE.synchronize_calendars(
                [normalized],
                state,
                datetime(2026, 8, 14, tzinfo=CT),
                Path("unused"),
            )
        add.assert_not_called()
        self.assertEqual(pending, [normalized["eventId"]])
        self.assertNotIn("calendarSyncedAt", state["events"][normalized["eventId"]])

    def test_stale_synced_state_repairs_missing_calendar_marker(self):
        normalized = MODULE.normalize(event(), datetime(2026, 8, 14, tzinfo=CT))
        state = {
            "schemaVersion": 1,
            "events": {normalized["eventId"]: {"calendarSyncedAt": "stale"}},
        }
        with (
            mock.patch.object(MODULE, "calendar_contains", return_value=False),
            mock.patch.object(MODULE, "calendar_add") as add,
        ):
            pending = MODULE.synchronize_calendars(
                [normalized],
                state,
                datetime(2026, 8, 14, tzinfo=CT),
                Path("unused"),
            )
        add.assert_called_once_with(normalized)
        self.assertEqual(pending, [normalized["eventId"]])

    def test_native_calendar_sync_is_noninteractive_and_bounded(self):
        with mock.patch.object(MODULE.subprocess, "run") as runner:
            runner.return_value.returncode = 0
            runner.return_value.stdout = ""
            runner.return_value.stderr = ""
            MODULE.sync_native_calendar()
        kwargs = runner.call_args.kwargs
        self.assertIs(kwargs["stdin"], MODULE.subprocess.DEVNULL)
        self.assertEqual(kwargs["timeout"], 120)

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
