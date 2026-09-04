#!/usr/bin/env python3

from __future__ import annotations

import datetime as dt
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("sonarr_large_series_upgrade.py")
SPEC = importlib.util.spec_from_file_location("sonarr_large_series_upgrade", MODULE_PATH)
assert SPEC and SPEC.loader
UPGRADE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPGRADE)


class LargeSeriesUpgradeTests(unittest.TestCase):
    def test_active_workloads_include_search_and_rss(self) -> None:
        commands = [
            {"id": 1, "name": "SeriesSearch", "status": "started"},
            {"id": 2, "name": "RssSync", "status": "queued"},
            {"id": 3, "name": "RefreshSeries", "status": "started"},
            {"id": 4, "name": "SeasonSearch", "status": "completed"},
        ]
        workloads = UPGRADE.active_sonarr_workloads(commands)
        self.assertEqual([item["id"] for item in workloads], [1, 2])

    def test_candidate_split_and_rotation(self) -> None:
        series = [
            {
                "id": 1,
                "title": "Small",
                "monitored": True,
                "statistics": {"episodeCount": 20},
                "seasons": [{"seasonNumber": 1, "monitored": True, "statistics": {"episodeCount": 20}}],
            },
            {
                "id": 2,
                "title": "Large",
                "monitored": True,
                "statistics": {"episodeCount": 100},
                "seasons": [
                    {"seasonNumber": 1, "monitored": True, "statistics": {"episodeCount": 25}},
                    {"seasonNumber": 2, "monitored": True, "statistics": {"episodeCount": 70}},
                    {"seasonNumber": 3, "monitored": False, "statistics": {"episodeCount": 5}},
                ],
            },
            {
                "id": 3,
                "title": "Another",
                "monitored": True,
                "statistics": {"episodeCount": 31},
                "seasons": [{"seasonNumber": 1, "monitored": True, "statistics": {"episodeCount": 12}}],
            },
        ]
        candidates, oversized = UPGRADE.season_candidates(series, 30, 60)
        self.assertEqual([UPGRADE.target_key(item) for item in candidates], ["3:1", "2:1"])
        self.assertEqual([UPGRADE.target_key(item) for item in oversized], ["2:2"])
        self.assertEqual(UPGRADE.target_key(UPGRADE.select_next(candidates, None)), "3:1")
        self.assertEqual(UPGRADE.target_key(UPGRADE.select_next(candidates, "3:1")), "2:1")
        self.assertEqual(UPGRADE.target_key(UPGRADE.select_next(candidates, "2:1")), "3:1")

    def test_window_boundaries(self) -> None:
        window = UPGRADE.parse_window("00:00-07:00")
        self.assertTrue(UPGRADE.inside_window(window, dt.datetime(2026, 9, 3, 6, 59)))
        self.assertFalse(UPGRADE.inside_window(window, dt.datetime(2026, 9, 3, 7, 0)))

    def test_profilarr_gate_reports_active_sonarr_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "profilarr.db"
            conn = sqlite3.connect(db)
            conn.executescript(
                """
                CREATE TABLE arr_instances (id INTEGER, type TEXT, enabled INTEGER);
                CREATE TABLE upgrade_configs (arr_instance_id INTEGER, enabled INTEGER);
                CREATE TABLE job_queue (id INTEGER, job_type TEXT, status TEXT, dedupe_key TEXT);
                INSERT INTO arr_instances VALUES (1, 'sonarr', 1);
                INSERT INTO upgrade_configs VALUES (1, 1);
                INSERT INTO job_queue VALUES (7, 'arr.upgrade', 'running', 'arr.upgrade:1');
                """
            )
            conn.commit()
            conn.close()
            gate = UPGRADE.profilarr_gate(db)
        self.assertTrue(gate["window_open"])
        self.assertEqual(gate["active_jobs"][0]["id"], 7)


if __name__ == "__main__":
    unittest.main()
