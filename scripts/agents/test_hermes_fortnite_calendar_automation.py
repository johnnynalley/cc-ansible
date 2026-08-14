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


SCRIPT = Path(__file__).with_name("hermes-fortnite-calendar-compat.py")
SPEC = importlib.util.spec_from_file_location("hermes_fortnite_calendar_compat", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


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


if __name__ == "__main__":
    unittest.main()
