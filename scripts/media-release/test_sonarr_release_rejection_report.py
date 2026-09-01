#!/usr/bin/env python3
"""Focused regressions for Sonarr release rejection reporting."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/media-release/sonarr_release_rejection_report.py"
SPEC = importlib.util.spec_from_file_location("sonarr_release_rejection_report", SOURCE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to load {SOURCE}")
REPORT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = REPORT
SPEC.loader.exec_module(REPORT)


class SeriesSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.series = [
            {"id": 43, "title": "House", "alternateTitles": []},
            {"id": 185, "title": "The Owl House", "alternateTitles": []},
        ]

    def test_exact_title_precedes_substring_matches(self) -> None:
        self.assertEqual(REPORT.find_series(self.series, "House")["id"], 43)

    def test_numeric_id_selects_exact_series(self) -> None:
        self.assertEqual(REPORT.find_series(self.series, "185")["title"], "The Owl House")


if __name__ == "__main__":
    unittest.main()
