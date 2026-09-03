#!/usr/bin/env python3

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import tempfile
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
            "download_id": [],
            "title_regex": None,
            "message_regex": None,
            "limit": None,
            "remove_from_client": False,
            "blocklist": False,
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

    def test_download_id_match_is_exact_and_case_insensitive(self) -> None:
        record = {
            "downloadId": "ABC123",
            "status": "completed",
            "trackedDownloadState": "importBlocked",
            "trackedDownloadStatus": "warning",
        }
        self.assertTrue(
            MODULE.matches(record, self.args(download_id=["abc123"]))
        )
        self.assertFalse(
            MODULE.matches(record, self.args(download_id=["abc124"]))
        )

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

    def test_apply_manifest_records_exact_selected_rows_and_filters(self) -> None:
        selected = [{"id": 1, "title": "Example.MULTI.1080p"}]
        with tempfile.TemporaryDirectory() as directory:
            manifest = MODULE.write_backup_manifest(
                Path(directory),
                "sonarr",
                selected,
                selected,
                self.args(status="delay", title_regex="MULTI"),
            )
            payload = MODULE.json.loads(manifest.read_text(encoding="utf-8"))
            manifest_mode = manifest.stat().st_mode & 0o777

        self.assertEqual(payload["app"], "sonarr")
        self.assertEqual(payload["filters"]["status"], "delay")
        self.assertEqual(payload["filters"]["title_regex"], "MULTI")
        self.assertEqual(payload["matched_rows"], selected)
        self.assertEqual(payload["operation_rows"], selected)
        self.assertEqual(manifest_mode, 0o600)

    def test_require_root_only_directory_rejects_group_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rollback"
            target.mkdir(mode=0o750)
            target.chmod(0o750)
            with self.assertRaises(RuntimeError):
                MODULE.require_root_only_directory(target)


if __name__ == "__main__":
    unittest.main()
