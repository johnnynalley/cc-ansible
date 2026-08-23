#!/usr/bin/env python3

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).with_name("arr_queue_remove.py")
SPEC = importlib.util.spec_from_file_location("arr_queue_remove", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ArrQueueRemoveTests(unittest.TestCase):
    def args(self, **overrides):
        values = {
            "status": "completed",
            "tracked_state": "importBlocked",
            "tracked_status": "warning",
            "download_client": None,
            "title_regex": None,
            "message_regex": None,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_requires_exact_terminal_warning_state(self) -> None:
        record = {
            "status": "completed",
            "trackedDownloadState": "importBlocked",
            "trackedDownloadStatus": "warning",
        }
        self.assertTrue(MODULE.matches(record, self.args()))
        record["trackedDownloadStatus"] = "ok"
        self.assertFalse(MODULE.matches(record, self.args()))

    def test_active_download_does_not_match(self) -> None:
        record = {
            "status": "downloading",
            "trackedDownloadState": "downloading",
            "trackedDownloadStatus": "ok",
        }
        self.assertFalse(MODULE.matches(record, self.args()))

    def test_remove_from_client_deduplicates_episode_rows_by_download_id(self) -> None:
        records = [
            {"id": 1, "downloadId": "ABC"},
            {"id": 2, "downloadId": "abc"},
            {"id": 3, "downloadId": "DEF"},
        ]
        selected = MODULE.cleanup_records(records, remove_from_client=True)
        self.assertEqual([record["id"] for record in selected], [1, 3])

    def test_queue_only_cleanup_keeps_every_row(self) -> None:
        records = [
            {"id": 1, "downloadId": "ABC"},
            {"id": 2, "downloadId": "ABC"},
        ]
        self.assertEqual(MODULE.cleanup_records(records, remove_from_client=False), records)


if __name__ == "__main__":
    unittest.main()
