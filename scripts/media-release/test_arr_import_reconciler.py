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
            "custom_format_score": 145000,
            "custom_formats": ["Anime Dual Audio", "x265 (HD)", "Tier 1"],
        }

    def candidate(self, episode_id: int, *, has_file: bool = False, rejected: bool = False):
        return {
            "path": f"/downloads/S01E{episode_id}.mkv",
            "series": {"id": 60},
            "episodes": [{"id": episode_id, "monitored": True, "hasFile": has_file}],
            "quality": {"quality": {"id": 9}},
            "customFormatScore": 145000,
            "customFormats": [
                {"name": "Anime Dual Audio"},
                {"name": "x265 (HD)"},
                {"name": "Tier 1"},
            ],
            "rejections": (
                [{"reason": "Not a Custom Format upgrade for existing episode file"}]
                if rejected
                else []
            ),
        }

    def test_selects_only_expected_missing_rejection_free_episode(self) -> None:
        selected = MODULE.select_candidates(
            "sonarr",
            self.context,
            [
                self.candidate(7859),
                self.candidate(7860),
                self.candidate(7859, rejected=True),
            ],
        )
        self.assertEqual([item["path"] for item in selected], ["/downloads/S01E7859.mkv"])

    def test_selects_rejection_free_existing_episode_upgrade(self) -> None:
        selected = MODULE.select_candidates(
            "sonarr",
            self.context,
            [self.candidate(7859, has_file=True)],
        )
        self.assertEqual([item["path"] for item in selected], ["/downloads/S01E7859.mkv"])

    def test_native_current_better_rejection_still_blocks_upgrade(self) -> None:
        self.assertEqual(
            MODULE.select_candidates(
                "sonarr",
                self.context,
                [self.candidate(7859, has_file=True, rejected=True)],
            ),
            [],
        )

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

    def test_radarr_candidate_must_match_exact_movie(self) -> None:
        context = {
            "app": "radarr",
            "identity_conflict": False,
            "media": {"id": 42},
            "expected_episodes": [],
        }
        candidates = [
            {"path": "/downloads/movie.mkv", "movie": {"id": 42, "hasFile": True}},
            {"path": "/downloads/wrong.mkv", "movie": {"id": 43, "hasFile": False}},
        ]
        selected = MODULE.select_candidates("radarr", context, candidates)
        self.assertEqual([item["path"] for item in selected], ["/downloads/movie.mkv"])

    def test_diagnostics_report_grab_to_import_cf_drift(self) -> None:
        candidate = self.candidate(7859, has_file=True)
        candidate["customFormatScore"] = 45000
        candidate["customFormats"] = [{"name": "x265 (HD)"}]
        diagnostics = MODULE.candidate_diagnostics("sonarr", self.context, [candidate])
        self.assertEqual(diagnostics[0]["classification"], "grab_import_cf_drift")
        self.assertEqual(diagnostics[0]["grab_score"], 145000)
        self.assertEqual(diagnostics[0]["import_score"], 45000)
        self.assertEqual(diagnostics[0]["lost_formats"], ["Anime Dual Audio", "Tier 1"])

    def test_equal_score_with_cf_substitution_is_still_eligible(self) -> None:
        candidate = self.candidate(7859, has_file=True)
        candidate["customFormats"] = [
            {"name": "Anime - Dual Audio (Metadata)"},
            {"name": "x265 (HD)"},
        ]
        diagnostics = MODULE.candidate_diagnostics("sonarr", self.context, [candidate])
        self.assertEqual(diagnostics[0]["classification"], "eligible_upgrade")
        self.assertEqual(diagnostics[0]["grab_score"], diagnostics[0]["import_score"])
        self.assertEqual(diagnostics[0]["lost_formats"], ["Anime Dual Audio", "Tier 1"])

    def test_persistent_state_prevents_duplicate_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = MODULE.ReconcileState(path)
            self.assertFalse(state.has("sonarr", "ABC"))
            state.mark("sonarr", "ABC")
            self.assertTrue(MODULE.ReconcileState(path).has("sonarr", "abc"))

    def test_event_log_is_private_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            MODULE.append_event(path, {"result": "imported", "selected": 1})
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            self.assertEqual(
                path.read_text(encoding="utf-8"),
                '{"result":"imported","selected":1}\n',
            )

    def test_import_history_audit_reports_post_grab_score_gain(self) -> None:
        import_record = {
            "eventType": "downloadFolderImported",
            "date": "2026-09-01T01:00:00Z",
            "downloadId": "ABC123",
            "customFormatScore": 145000,
            "customFormats": [
                {"name": "Anime Dual Audio"},
                {"name": "x265"},
                {"name": "Tier 1"},
            ],
        }

        class ArrClient:
            def request(self, method, path, params=None, body=None):
                if method == "GET" and path == "/history":
                    return {"records": [import_record], "totalRecords": 1}
                raise AssertionError((method, path, params, body))

        class LedgerClient:
            def request(self, method, path, params=None, body=None):
                return {
                    "context": {
                        "app": "sonarr",
                        "source_title": "Example S01",
                        "captured_at": "2026-09-01T00:30:00Z",
                        "custom_format_score": 40000,
                        "custom_formats": ["Tier 1"],
                    }
                }

        report = MODULE.audit_import_history(
            "sonarr",
            ArrClient(),
            LedgerClient(),
            MODULE.dt.datetime(2026, 8, 31, tzinfo=MODULE.dt.UTC),
            100,
        )
        self.assertEqual(report["classification_counts"], {"score_drift": 1})
        result = report["results"][0]
        self.assertEqual(result["grab_score"], 40000)
        self.assertEqual(
            result["variants"][0]["gained_formats"],
            ["Anime Dual Audio", "x265"],
        )

    def test_import_history_audit_groups_stable_pack_episodes(self) -> None:
        records = [
            {
                "eventType": "downloadFolderImported",
                "date": f"2026-09-01T01:00:0{episode}Z",
                "downloadId": "PACK123",
                "customFormatScore": 46200,
                "customFormats": [{"name": "x265"}, {"name": "Tier 1"}],
            }
            for episode in range(2)
        ]

        class ArrClient:
            def request(self, method, path, params=None, body=None):
                return {"records": records, "totalRecords": len(records)}

        class LedgerClient:
            def request(self, method, path, params=None, body=None):
                return {
                    "context": {
                        "app": "sonarr",
                        "source_title": "Stable Pack",
                        "captured_at": "2026-09-01T00:30:00Z",
                        "custom_format_score": 46200,
                        "custom_formats": ["Tier 1", "x265"],
                    }
                }

        report = MODULE.audit_import_history(
            "sonarr",
            ArrClient(),
            LedgerClient(),
            MODULE.dt.datetime(2026, 8, 31, tzinfo=MODULE.dt.UTC),
            100,
        )
        self.assertEqual(report["classification_counts"], {"stable": 1})
        self.assertEqual(report["results"][0]["import_count"], 2)
        self.assertEqual(report["results"][0]["variants"][0]["count"], 2)

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
