#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("arr_import_reconciler.py")
SPEC = importlib.util.spec_from_file_location("arr_import_reconciler", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ArrImportReconcilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = {
            "app": "sonarr",
            "identity_conflict": False,
            "media": {"id": 60},
            "expected_episodes": [{"id": 7859, "season": 1, "episode": 1}],
        }

    def candidate(self, episode_id: int, *, has_file: bool = False, rejected: bool = False):
        return {
            "path": f"/downloads/S01E{episode_id}.mkv",
            "series": {"id": 60},
            "episodes": [{"id": episode_id, "monitored": True, "hasFile": has_file}],
            "quality": {"quality": {"id": 9}},
            "rejections": [{"reason": "Not an upgrade"}] if rejected else [],
        }

    def test_selects_only_expected_missing_rejection_free_episode(self) -> None:
        selected = MODULE.select_candidates(
            "sonarr",
            self.context,
            [
                self.candidate(7859),
                self.candidate(7860),
                self.candidate(7859, has_file=True),
                self.candidate(7859, rejected=True),
            ],
        )
        self.assertEqual([item["path"] for item in selected], ["/downloads/S01E7859.mkv"])

    def test_identity_conflict_disables_reconciliation(self) -> None:
        self.context["identity_conflict"] = True
        self.assertEqual(
            MODULE.select_candidates("sonarr", self.context, [self.candidate(7859)]),
            [],
        )

    def test_duplicate_candidates_for_one_expected_episode_are_ambiguous(self) -> None:
        self.assertEqual(
            MODULE.select_candidates(
                "sonarr",
                self.context,
                [self.candidate(7859), self.candidate(7859)],
            ),
            [],
        )

    def test_requires_completed_import_blocked_id_match_reason(self) -> None:
        row = {
            "status": "completed",
            "trackedDownloadState": "importBlocked",
            "statusMessages": [
                {
                    "messages": [
                        "Found matching series via grab history, but release was matched "
                        "to series by ID. Automatic import is not possible."
                    ]
                }
            ],
        }
        self.assertTrue(MODULE.is_exact_id_match_block(row, "sonarr"))
        row["trackedDownloadState"] = "downloading"
        self.assertFalse(MODULE.is_exact_id_match_block(row, "sonarr"))

    def test_radarr_candidate_must_match_exact_movie_and_be_missing(self) -> None:
        context = {
            "app": "radarr",
            "identity_conflict": False,
            "media": {"id": 42},
            "expected_episodes": [],
        }
        candidates = [
            {"path": "/downloads/movie.mkv", "movie": {"id": 42, "hasFile": False}},
            {"path": "/downloads/wrong.mkv", "movie": {"id": 43, "hasFile": False}},
            {"path": "/downloads/existing.mkv", "movie": {"id": 42, "hasFile": True}},
        ]
        selected = MODULE.select_candidates("radarr", context, candidates)
        self.assertEqual([item["path"] for item in selected], ["/downloads/movie.mkv"])

    def test_persistent_state_prevents_duplicate_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = MODULE.ReconcileState(path)
            self.assertFalse(state.has("sonarr", "ABC"))
            state.mark("sonarr", "ABC")
            self.assertTrue(MODULE.ReconcileState(path).has("sonarr", "abc"))

    def test_duplicate_queue_rows_for_one_download_are_evaluated_once(self) -> None:
        row = {
            "status": "completed",
            "trackedDownloadState": "importBlocked",
            "downloadId": "ABC123",
            "statusMessages": [
                {"messages": ["Release was matched to series by ID."]}
            ],
        }
        candidate = self.candidate(7859)

        class ArrClient:
            manual_import_calls = 0

            def request(self, method, path, params=None, body=None):
                if method == "GET" and path == "/queue":
                    return {"records": [row, dict(row)], "totalRecords": 2}
                if method == "GET" and path == "/manualimport":
                    self.manual_import_calls += 1
                    return [candidate]
                raise AssertionError((method, path, params, body))

        class LedgerClient:
            def request(self, method, path, params=None, body=None):
                return {"context": self_context}

        self_context = self.context
        client = ArrClient()
        with tempfile.TemporaryDirectory() as directory:
            results = MODULE.reconcile_app(
                "sonarr",
                client,
                LedgerClient(),
                MODULE.ReconcileState(Path(directory) / "state.json"),
                dry_run=True,
            )
        self.assertEqual(client.manual_import_calls, 1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["result"], "would_import")

    def test_lost_command_response_is_still_suppressed(self) -> None:
        row = {
            "status": "completed",
            "trackedDownloadState": "importBlocked",
            "downloadId": "ABC123",
            "statusMessages": [
                {"messages": ["Release was matched to series by ID."]}
            ],
        }
        candidate = self.candidate(7859)
        context = self.context

        class ArrClient:
            def request(self, method, path, params=None, body=None):
                if method == "GET" and path == "/queue":
                    return {"records": [row], "totalRecords": 1}
                if method == "GET" and path == "/manualimport":
                    return [candidate]
                if method == "POST" and path == "/command":
                    raise OSError("response lost after request")
                raise AssertionError((method, path, params, body))

        class LedgerClient:
            def request(self, method, path, params=None, body=None):
                return {"context": context}

        with tempfile.TemporaryDirectory() as directory:
            state = MODULE.ReconcileState(Path(directory) / "state.json")
            with self.assertRaisesRegex(OSError, "response lost"):
                MODULE.reconcile_app(
                    "sonarr",
                    ArrClient(),
                    LedgerClient(),
                    state,
                    dry_run=False,
                )
            self.assertTrue(MODULE.ReconcileState(state.path).has("sonarr", "abc123"))


if __name__ == "__main__":
    unittest.main()
