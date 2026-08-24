#!/usr/bin/env python3
"""Regression tests for reconciler events in sonarr_transaction_audit.py."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("sonarr_transaction_audit.py")
SPEC = importlib.util.spec_from_file_location("sonarr_transaction_audit", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SonarrTransactionAuditTests(unittest.TestCase):
    def test_reconciler_events_are_filtered_and_summarized(self) -> None:
        now = dt.datetime.now(dt.UTC)
        recent = {
            "observed_at": now.isoformat().replace("+00:00", "Z"),
            "app": "sonarr",
            "download_id": "abc",
            "result": "imported",
            "selected": 1,
            "candidate_diagnostics": [{"classification": "eligible_upgrade"}],
        }
        old = {
            **recent,
            "observed_at": (now - dt.timedelta(days=2)).isoformat().replace("+00:00", "Z"),
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text(
                json.dumps(old) + "\n" + json.dumps(recent) + "\n",
                encoding="utf-8",
            )
            events = MODULE.reconciler_events(path, now - dt.timedelta(hours=24))
        summary = MODULE.summarize_reconciler_events(events, 10)
        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["results"], {"imported": 1})
        self.assertEqual(summary["classifications"], {"eligible_upgrade": 1})


if __name__ == "__main__":
    unittest.main()
