#!/usr/bin/env python3
"""Regression tests for the split Hermes Fortnite calendar transaction."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("hermes-fortnite-calendar-compat.py")
SPEC = importlib.util.spec_from_file_location("hermes_fortnite_calendar_compat", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

FETCH_SCRIPT = Path(__file__).with_name("hermes-fortnite-calendar-fetch.py")
FETCH_SPEC = importlib.util.spec_from_file_location(
    "hermes_fortnite_calendar_fetch", FETCH_SCRIPT
)
FETCH_MODULE = importlib.util.module_from_spec(FETCH_SPEC)
assert FETCH_SPEC and FETCH_SPEC.loader
FETCH_SPEC.loader.exec_module(FETCH_MODULE)


def artifact(generated_at: datetime | None = None) -> dict[str, object]:
    body: dict[str, object] = {
        "schemaVersion": 1,
        "generatedAt": (generated_at or datetime.now(timezone.utc))
        .replace(microsecond=0)
        .isoformat(),
        "source": MODULE.SOURCE_URL,
        "activeRegion": "NAC",
        "scheduleDays": [{"date": "2026-08-15", "events": []}],
    }
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {**body, "digest": digest}


class FortniteCalendarAutomationTests(unittest.TestCase):
    def write(self, payload: dict[str, object]) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "schedule.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_fresh_validated_artifact_is_accepted(self):
        days = MODULE.load_schedule(self.write(artifact()))
        self.assertEqual(days[0]["date"], "2026-08-15")

    def test_tampered_artifact_is_rejected(self):
        payload = artifact()
        payload["activeRegion"] = "EU"
        with self.assertRaisesRegex(RuntimeError, "schedule-digest"):
            MODULE.load_schedule(self.write(payload))

    def test_stale_artifact_is_rejected(self):
        payload = artifact(datetime.now(timezone.utc) - timedelta(hours=1))
        with self.assertRaisesRegex(RuntimeError, "schedule-stale"):
            MODULE.load_schedule(self.write(payload))

    def test_fetch_requires_explicit_managed_browser_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing-geckodriver"
            with self.assertRaisesRegex(
                FETCH_MODULE.FetchError, "geckodriver-missing"
            ):
                FETCH_MODULE.fetch(missing, Path(directory) / "firefox")

    def test_fetcher_has_no_snap_geckodriver_dependency(self):
        source = FETCH_SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("/snap/bin/geckodriver", source)
        self.assertIn('"binary": str(firefox_binary)', source)
        self.assertIn('parser.add_argument("--geckodriver"', source)
        self.assertIn('parser.add_argument("--firefox-binary"', source)

    def test_native_loader_accepts_managed_extensionless_script(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "calendar-sync"
            script.write_text("VALUE = 42\n", encoding="utf-8")
            loaded = MODULE.load_native(script)
        self.assertEqual(loaded.VALUE, 42)

    def test_native_credential_reader_requires_one_exact_value(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "OTHER=value\nNEXTCLOUD_CALDAV_APP_PASSWORD=secret\n",
                encoding="utf-8",
            )
            self.assertEqual(
                MODULE.read_env_value(path, "NEXTCLOUD_CALDAV_APP_PASSWORD"),
                "secret",
            )
            path.write_text(
                "NEXTCLOUD_CALDAV_APP_PASSWORD=one\n"
                "NEXTCLOUD_CALDAV_APP_PASSWORD=two\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "credential-value"):
                MODULE.read_env_value(path, "NEXTCLOUD_CALDAV_APP_PASSWORD")

    def test_native_vdirsyncer_is_noninteractive_and_bounded(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            MODULE.subprocess, "run"
        ) as runner:
            runner.return_value.returncode = 0
            runner.return_value.stdout = ""
            runner.return_value.stderr = ""
            MODULE.native_vdirsyncer_sync(Path(directory) / "calendar")
        kwargs = runner.call_args.kwargs
        self.assertIs(kwargs["stdin"], MODULE.subprocess.DEVNULL)
        self.assertEqual(kwargs["timeout"], 240)


if __name__ == "__main__":
    unittest.main()
