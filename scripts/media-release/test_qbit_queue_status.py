#!/usr/bin/env python3
"""Regression tests for qbit_queue_status.py."""

from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("qbit_queue_status.py")
SPEC = importlib.util.spec_from_file_location("qbit_queue_status", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class QbitQueueStatusTests(unittest.TestCase):
    def test_explicit_title_seasons_recognizes_common_forms(self) -> None:
        self.assertEqual(
            MODULE.explicit_title_seasons("Example S03E07 2nd Season Season.4"),
            {2, 3, 4},
        )

    def test_correlation_flags_explicit_season_mismatch_first(self) -> None:
        result = MODULE.torrent_arr_correlation(
            {
                "name": "Example 2nd Season - Ep01",
                "state": "stalledDL",
                "progress": 0,
                "num_seeds": 0,
                "added_on": 100,
                "last_activity": 100,
            },
            "sonarr",
            [
                {
                    "series": {"title": "Example"},
                    "episode": {"seasonNumber": 1, "episodeNumber": 1},
                }
            ],
            stale_seconds=3600,
            now_epoch=10_000,
        )

        self.assertEqual(result["classification"], "explicit_season_mismatch")
        self.assertIn("stale_no_peers", result["findings"])
        self.assertEqual(result["arr_labels"], ["Example S01E01"])

    def test_correlation_distinguishes_zero_and_partial_stalls(self) -> None:
        base = {
            "name": "Example S01E01",
            "state": "stalledDL",
            "num_seeds": 0,
            "added_on": 100,
            "last_activity": 100,
        }
        rows = [
            {
                "series": {"title": "Example"},
                "episode": {"seasonNumber": 1, "episodeNumber": 1},
            }
        ]

        zero = MODULE.torrent_arr_correlation(
            {**base, "progress": 0}, "sonarr", rows, 3600, 10_000
        )
        partial = MODULE.torrent_arr_correlation(
            {**base, "progress": 0.5}, "sonarr", rows, 3600, 10_000
        )

        self.assertEqual(zero["classification"], "stale_no_peers")
        self.assertEqual(partial["classification"], "stale_partial_no_peers")

    def test_correlation_keeps_recent_no_peer_stall_in_grace(self) -> None:
        result = MODULE.torrent_arr_correlation(
            {
                "name": "Example S01E01",
                "state": "stalledDL",
                "progress": 0,
                "num_seeds": 0,
                "added_on": 9_900,
                "last_activity": 9_900,
            },
            "sonarr",
            [],
            stale_seconds=3600,
            now_epoch=10_000,
        )

        self.assertEqual(result["classification"], "orphaned_in_download_client")
        self.assertIn("no_peers_within_grace", result["findings"])

    def test_correlation_classifies_missing_payload(self) -> None:
        result = MODULE.torrent_arr_correlation(
            {"name": "Example", "state": "missingFiles", "progress": 0},
            "radarr",
            [{"movie": {"title": "Example"}}],
            stale_seconds=3600,
            now_epoch=10_000,
        )

        self.assertEqual(result["classification"], "missing_payload")

    @mock.patch.object(MODULE, "paged_arr_queue")
    @mock.patch.object(MODULE, "read_arr_api_key")
    def test_correlate_arr_joins_case_insensitive_exact_hash(
        self,
        read_arr_api_key: mock.Mock,
        paged_arr_queue: mock.Mock,
    ) -> None:
        read_arr_api_key.return_value = "private"
        paged_arr_queue.return_value = [
            {
                "downloadId": "ABCDEF1234",
                "series": {"title": "Example"},
                "episode": {"seasonNumber": 1, "episodeNumber": 2},
            }
        ]

        result = MODULE.correlate_arr(
            [
                {
                    "hash": "abcdef1234",
                    "category": "tv-sonarr",
                    "name": "Example S01E02",
                    "state": "stalledDL",
                    "progress": 0,
                    "num_seeds": 0,
                    "added_on": 100,
                    "last_activity": 100,
                }
            ],
            stale_seconds=3600,
            now_epoch=10_000,
        )

        self.assertEqual(result["abcdef1234"]["arr_row_count"], 1)
        self.assertEqual(result["abcdef1234"]["arr_labels"], ["Example S01E02"])

    def test_arr_history_summary_reports_repeated_grabs_and_indexers(self) -> None:
        result = MODULE.arr_history_summary(
            [
                {
                    "eventType": "grabbed",
                    "date": "2026-01-02T00:00:00Z",
                    "sourceTitle": "Example",
                    "data": {"indexer": "Indexer B"},
                },
                {
                    "eventType": "grabbed",
                    "date": "2026-01-01T00:00:00Z",
                    "sourceTitle": "Example",
                    "data": {"indexer": "Indexer A"},
                },
                {"eventType": "downloadIgnored", "date": "2026-01-03T00:00:00Z"},
            ]
        )

        self.assertEqual(result["grab_event_count"], 2)
        self.assertEqual(result["grab_batch_count"], 2)
        self.assertEqual(result["indexers"], ["Indexer A", "Indexer B"])
        self.assertEqual(result["first_grab_at"], "2026-01-01T00:00:00Z")
        self.assertEqual(result["last_grab_at"], "2026-01-02T00:00:00Z")
        self.assertEqual(result["source_title_count"], 1)

    def test_arr_history_summary_does_not_treat_pack_rows_as_repeat_grabs(self) -> None:
        records = [
            {
                "eventType": "grabbed",
                "date": "2026-01-01T00:00:00Z",
                "sourceTitle": "Example S01",
                "data": {"indexer": "Indexer A"},
            }
            for _ in range(12)
        ]

        result = MODULE.arr_history_summary(records)

        self.assertEqual(result["grab_event_count"], 12)
        self.assertEqual(result["grab_batch_count"], 1)

    @mock.patch.object(MODULE, "arr_api_get")
    @mock.patch.object(MODULE, "paged_arr_queue")
    @mock.patch.object(MODULE, "read_arr_api_key")
    def test_history_lookup_uppercases_qbit_hash_for_arr_filter(
        self,
        read_arr_api_key: mock.Mock,
        paged_arr_queue: mock.Mock,
        arr_api_get: mock.Mock,
    ) -> None:
        read_arr_api_key.return_value = "private"
        paged_arr_queue.return_value = []
        arr_api_get.return_value = []

        MODULE.correlate_arr(
            [
                {
                    "hash": "abcdef1234",
                    "category": "tv-sonarr",
                    "name": "Example S01E01",
                    "state": "stalledDL",
                }
            ],
            stale_seconds=3600,
            now_epoch=10_000,
            include_history=True,
        )

        self.assertEqual(
            arr_api_get.call_args.args[3]["downloadId"],
            "ABCDEF1234",
        )

    def test_compact_torrent_retains_activity_timestamps(self) -> None:
        result = MODULE.compact_torrent(
            {
                "name": "Example release",
                "hash": "abcdef1234567890",
                "added_on": 1_700_000_000,
                "last_activity": 1_700_000_100,
                "completion_on": -1,
                "time_active": 3600,
            }
        )

        self.assertEqual(result["added_at"], "2023-11-14T22:13:20Z")
        self.assertEqual(result["last_activity_at"], "2023-11-14T22:15:00Z")
        self.assertIsNone(result["completed_at"])
        self.assertEqual(result["time_active_seconds"], 3600)

    def test_manifest_torrent_retains_full_hash(self) -> None:
        result = MODULE.manifest_torrent(
            {"hash": "abcdef1234567890", "name": "Example"}
        )
        self.assertEqual(result["hash"], "abcdef1234567890")

    def test_write_manifest_is_root_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "manifest.json"
            target.write_text("old", encoding="utf-8")
            target.chmod(0o644)

            MODULE.write_manifest(str(target), {"result": "ok"})

            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                '{\n  "result": "ok"\n}\n',
            )

    def test_filter_arr_classifications_uses_exact_hash_correlation(self) -> None:
        torrents = [
            {"hash": "AAAA", "name": "orphan"},
            {"hash": "BBBB", "name": "mapped"},
        ]
        result = MODULE.filter_arr_classifications(
            torrents,
            {
                "aaaa": {"classification": "orphaned_in_download_client"},
                "bbbb": {"classification": "stale_no_peers"},
            },
            {"orphaned_in_download_client"},
        )
        self.assertEqual([item["name"] for item in result], ["orphan"])

    def test_filter_expected_hashes_is_exact_and_fails_if_missing(self) -> None:
        torrents = [
            {"hash": "AAAA", "name": "first"},
            {"hash": "BBBB", "name": "second"},
        ]
        result = MODULE.filter_expected_hashes(torrents, {"bbbb"})
        self.assertEqual([item["name"] for item in result], ["second"])
        with self.assertRaises(RuntimeError):
            MODULE.filter_expected_hashes(torrents, {"cccc"})

    def test_backup_torrent_metadata_requires_complete_restorable_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rollback = root / "rollback"
            rollback.mkdir(mode=0o700)
            metadata = root / "BT_backup"
            metadata.mkdir()
            (metadata / "ABC.torrent").write_bytes(b"torrent")
            (metadata / "ABC.fastresume").write_bytes(b"resume")

            copied = MODULE.backup_torrent_metadata(
                [{"hash": "abc"}], rollback, metadata
            )

            self.assertEqual(len(copied), 2)
            for path in copied:
                self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_backup_torrent_metadata_fails_before_incomplete_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rollback = root / "rollback"
            rollback.mkdir(mode=0o700)
            metadata = root / "BT_backup"
            metadata.mkdir()
            (metadata / "ABC.torrent").write_bytes(b"torrent")

            with self.assertRaises(RuntimeError):
                MODULE.backup_torrent_metadata(
                    [{"hash": "abc"}], rollback, metadata
                )
            self.assertFalse((rollback / "qbit-metadata").exists())

    def test_backup_selected_metadata_requires_exact_hash_and_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rollback = root / "rollback"
            rollback.mkdir(mode=0o700)
            metadata = root / "BT_backup"
            metadata.mkdir()
            (metadata / "ABC.torrent").write_bytes(b"torrent")
            (metadata / "ABC.fastresume").write_bytes(b"resume")
            manifest = rollback / "manifest.json"

            result = MODULE.backup_selected_metadata(
                [{"hash": "abc"}],
                {"abc"},
                str(rollback),
                str(manifest),
                str(metadata),
                {"total": 1},
            )

            self.assertTrue(result["metadata_backup_only"])
            self.assertEqual(len(result["metadata_backup"]), 2)
            self.assertEqual(manifest.stat().st_mode & 0o777, 0o600)

            with self.assertRaises(RuntimeError):
                MODULE.backup_selected_metadata(
                    [{"hash": "abc"}],
                    set(),
                    str(rollback),
                    str(rollback / "other.json"),
                    str(metadata),
                    {"total": 1},
                )

    def test_tracker_credentials_are_redacted_from_compact_output(self) -> None:
        result = MODULE.compact_torrent(
            {
                "name": "Private tracker release",
                "tracker": "https://tracker.example/announce/private-passkey",
            }
        )

        self.assertEqual(result["tracker"], "https://tracker.example/[redacted]")
        self.assertNotIn("private-passkey", str(result))

    def test_tracker_summary_redacts_url_and_urls_in_message(self) -> None:
        with mock.patch.object(MODULE, "api_get") as api_get:
            api_get.return_value = [
                {
                    "url": "https://tracker.example/announce/private-passkey",
                    "msg": "retry https://tracker.example/announce/private-passkey",
                    "status": 3,
                    "tier": 0,
                    "num_seeds": 0,
                    "num_leeches": 0,
                }
            ]
            result = MODULE.tracker_summary(
                "http://qbit.test", mock.Mock(), "abc123"
            )

        self.assertEqual(result[0]["url"], "https://tracker.example/[redacted]")
        self.assertEqual(
            result[0]["msg"],
            "retry https://tracker.example/[redacted]",
        )
        self.assertNotIn("private-passkey", str(result))

    @mock.patch.object(MODULE.time, "sleep")
    @mock.patch.object(MODULE.urllib.request, "build_opener")
    @mock.patch.object(MODULE, "parse_env")
    def test_login_retries_transient_timeout(
        self,
        parse_env: mock.Mock,
        build_opener: mock.Mock,
        sleep: mock.Mock,
    ) -> None:
        parse_env.return_value = {
            "QBIT_API": "http://qbit.test/api/v2",
            "QBIT_USER": "operator",
            "QBIT_PASS": "private",
        }
        failed_opener = mock.Mock()
        failed_opener.open.side_effect = TimeoutError("temporary timeout")

        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b"Ok."
        successful_opener = mock.Mock()
        successful_opener.open.return_value = response
        build_opener.side_effect = [failed_opener, successful_opener]

        base_url, opener = MODULE.qbit_client(
            "/unused/qbit.env", attempts=2, retry_delay=0.25
        )

        self.assertEqual(base_url, "http://qbit.test/api/v2")
        self.assertIs(opener, successful_opener)
        sleep.assert_called_once_with(0.25)

    @mock.patch.object(MODULE, "tracker_summary")
    def test_tracker_timeout_does_not_discard_torrent(
        self, tracker_summary: mock.Mock
    ) -> None:
        tracker_summary.side_effect = urllib.error.URLError("temporary timeout")
        item = {"name": "Example release"}

        MODULE.attach_tracker_summary(item, "http://qbit.test", mock.Mock(), "abc123")

        self.assertEqual(item["name"], "Example release")
        self.assertNotIn("trackers", item)
        self.assertIn("temporary timeout", item["tracker_error"])

    @mock.patch.object(MODULE, "api_get")
    def test_tracker_lookup_uses_short_timeout(self, api_get: mock.Mock) -> None:
        api_get.return_value = []

        result = MODULE.tracker_summary("http://qbit.test", mock.Mock(), "abc123")

        self.assertEqual(result, [])
        api_get.assert_called_once_with(
            "http://qbit.test",
            mock.ANY,
            "/torrents/trackers",
            {"hash": "abc123"},
            timeout=5,
        )


if __name__ == "__main__":
    unittest.main()
