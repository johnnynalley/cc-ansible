#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


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

    def terminal_context(self) -> dict:
        return {
            **self.context,
            "source_title": "Example.S01.1080p.WEBRip.x265.Dual.Audio-GROUP",
            "original_languages": ["jpn"],
            "quality_profile": {"id": 4, "fingerprint": "same"},
            "current_files": [
                {"target_id": 7859, "has_file": True, "file_id": 10}
            ],
        }

    def terminal_probe(self, name: str) -> dict:
        return {
            "name": name,
            "size": 100,
            "inode": 1,
            "links": 2,
            "video_codecs": ["hevc"],
            "video_dimensions": ["1920x1080"],
            "audio_languages": ["eng", "jpn"],
            "subtitle_languages": ["eng"],
            "video_streams": 1,
            "audio_streams": 2,
            "subtitle_streams": 1,
        }

    def classify_in_temp(
        self,
        *,
        context: dict | None = None,
        candidate: dict | None = None,
        probe: dict | None = None,
        current_profile: str | None = "same",
        current_files: list[dict] | None = None,
        include_payload_mapping: bool = True,
        allow_english_original_und_audio: bool = False,
    ) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episode.mkv"
            path.touch()
            selected = candidate or self.candidate(7859, has_file=True, rejected=True)
            selected["path"] = str(path)
            payload_paths = {str(path.resolve()): path} if include_payload_mapping else {}
            return MODULE.classify_terminal_download(
                "sonarr",
                context or self.terminal_context(),
                [selected],
                [probe or self.terminal_probe(path.name)],
                payload_paths,
                current_profile,
                current_files
                if current_files is not None
                else [{"target_id": 7859, "has_file": True, "file_id": 10}],
                allow_english_original_und_audio,
            )

    def test_terminal_current_better_is_actionable_without_blocklist(self) -> None:
        result = self.classify_in_temp()
        self.assertEqual(result["classification"], "current_better")
        self.assertTrue(result["actionable"])
        self.assertFalse(result["blocklist"])

    def test_terminal_eligible_candidate_is_left_for_import(self) -> None:
        result = self.classify_in_temp(candidate=self.candidate(7859, has_file=True))
        self.assertEqual(result["classification"], "accepted")
        self.assertFalse(result["actionable"])

    def test_dual_audio_claim_without_english_is_exact_payload_failure(self) -> None:
        probe = self.terminal_probe("episode.mkv")
        probe["audio_languages"] = ["fra", "jpn"]
        result = self.classify_in_temp(probe=probe)
        self.assertEqual(result["classification"], "payload_misrepresented")
        self.assertTrue(result["blocklist"])
        self.assertEqual(result["contract_failures"][0]["claim"], "dual_audio")

    def test_dual_audio_claim_with_unknown_track_fails_closed(self) -> None:
        probe = self.terminal_probe("episode.mkv")
        probe["audio_languages"] = ["jpn", "und"]
        result = self.classify_in_temp(probe=probe)
        self.assertEqual(result["classification"], "unverifiable")
        self.assertFalse(result["actionable"])

    def test_english_original_requires_english_not_foreign_dual_audio(self) -> None:
        context = self.terminal_context()
        context["original_languages"] = ["eng"]
        probe = self.terminal_probe("episode.mkv")
        probe["audio_languages"] = ["eng", "spa"]
        result = self.classify_in_temp(context=context, probe=probe)
        self.assertEqual(result["classification"], "current_better")

    def test_original_language_is_required_without_dual_audio_claim(self) -> None:
        context = self.terminal_context()
        context["source_title"] = "Example.S01.1080p.WEBRip.x264-GROUP"
        context["custom_formats"] = ["Tier 1"]
        probe = self.terminal_probe("episode.mkv")
        probe["audio_languages"] = ["eng"]
        result = self.classify_in_temp(context=context, probe=probe)
        self.assertEqual(result["classification"], "payload_misrepresented")
        self.assertEqual(result["contract_failures"][0]["claim"], "original_audio")

    def test_metadata_da_match_without_title_claim_does_not_require_english(self) -> None:
        context = self.terminal_context()
        context["source_title"] = "Example.S01.1080p.WEBRip.x264-GROUP"
        context["custom_formats"] = ["Regular Dual Audio", "Tier 1"]
        probe = self.terminal_probe("episode.mkv")
        probe["audio_languages"] = ["jpn"]
        result = self.classify_in_temp(context=context, probe=probe)
        self.assertEqual(result["classification"], "current_better")
        self.assertEqual(result["contract_failures"], [])

    def test_unknown_audio_language_cannot_prove_original_audio_failure(self) -> None:
        context = self.terminal_context()
        context["source_title"] = "Example.S01.1080p.WEBRip.x264-GROUP"
        context["custom_formats"] = ["Tier 1"]
        probe = self.terminal_probe("episode.mkv")
        probe["audio_languages"] = ["eng", "und"]
        result = self.classify_in_temp(context=context, probe=probe)
        self.assertEqual(result["classification"], "unverifiable")
        self.assertEqual(result["contract_unverifiable"][0]["claim"], "original_audio")

    def test_eligible_candidate_with_unknown_original_audio_fails_closed(self) -> None:
        probe = self.terminal_probe("episode.mkv")
        probe["audio_languages"] = ["eng", "und"]
        result = self.classify_in_temp(
            candidate=self.candidate(7859, has_file=True),
            probe=probe,
        )
        self.assertEqual(result["classification"], "unverifiable")
        self.assertFalse(result["actionable"])

    def test_enabled_single_untagged_audio_accepts_english_regular_profile(self) -> None:
        context = self.terminal_context()
        context["source_title"] = "Incredible.Hulk.1982.S01E02.1080p.WEBRip.x264-DB2K9"
        context["original_languages"] = ["eng"]
        context["quality_profile"]["name"] = "shows-regular-efficient"
        probe = self.terminal_probe("episode.avi")
        probe["audio_languages"] = ["und"]
        probe["audio_streams"] = 1
        result = self.classify_in_temp(
            context=context,
            candidate=self.candidate(7859, has_file=True),
            probe=probe,
            allow_english_original_und_audio=True,
        )
        self.assertEqual(result["classification"], "accepted")
        self.assertEqual(
            result["contract_assumptions"][0]["assumption"],
            "single_untagged_audio_is_original_english",
        )

    def test_enabled_single_untagged_audio_accepts_resolved_legacy_profile(self) -> None:
        context = self.terminal_context()
        context["source_title"] = "Incredible.Hulk.1982.S01E02.480p.x264-DB2K9"
        context["original_languages"] = ["eng"]
        context["quality_profile"] = None
        context["current_quality_profile_name"] = "shows-regular-efficient"
        probe = self.terminal_probe("episode.avi")
        probe["audio_languages"] = ["und"]
        probe["audio_streams"] = 1
        result = self.classify_in_temp(
            context=context,
            candidate=self.candidate(7859, has_file=True),
            probe=probe,
            allow_english_original_und_audio=True,
        )
        self.assertEqual(result["classification"], "accepted")
        self.assertEqual(
            result["contract_assumptions"][0]["profile"],
            "shows-regular-efficient",
        )

    def test_current_policy_resolves_profile_for_legacy_context(self) -> None:
        context = {
            "media": {"id": 42},
            "quality_profile": None,
            "expected_episodes": [{"id": 7859}],
        }

        class ArrClient:
            def request(self, method, path, params=None, body=None):
                if path == "/series/42":
                    return {"id": 42, "qualityProfileId": 4}
                if path == "/qualityprofile/4":
                    return {"id": 4, "name": "shows-regular-efficient"}
                if path in {"/episode", "/episodefile"}:
                    return []
                raise AssertionError(path)

        fingerprint, current_files = MODULE.current_policy_state(
            "sonarr", ArrClient(), context
        )
        self.assertIsNotNone(fingerprint)
        self.assertEqual(current_files, [{"target_id": 7859, "has_file": False}])
        self.assertEqual(
            context["current_quality_profile_name"],
            "shows-regular-efficient",
        )

    def test_untagged_english_exception_rejects_ambiguous_release_markers(self) -> None:
        for marker in ("DUAL", "MULTI", "FRENCH"):
            with self.subTest(marker=marker):
                context = self.terminal_context()
                context["source_title"] = f"Example.S01E01.{marker}.WEBRip.x264-GROUP"
                context["original_languages"] = ["eng"]
                context["quality_profile"]["name"] = "shows-regular-efficient"
                probe = self.terminal_probe("episode.avi")
                probe["audio_languages"] = ["und"]
                probe["audio_streams"] = 1
                result = self.classify_in_temp(
                    context=context,
                    probe=probe,
                    allow_english_original_und_audio=True,
                )
                self.assertEqual(result["classification"], "unverifiable")
                self.assertEqual(result["contract_assumptions"], [])

    def test_untagged_english_exception_rejects_anime_profile(self) -> None:
        context = self.terminal_context()
        context["source_title"] = "Example.S01E01.WEBRip.x264-GROUP"
        context["original_languages"] = ["eng"]
        context["quality_profile"]["name"] = "shows-anime-efficient"
        probe = self.terminal_probe("episode.avi")
        probe["audio_languages"] = ["und"]
        probe["audio_streams"] = 1
        result = self.classify_in_temp(
            context=context,
            probe=probe,
            allow_english_original_und_audio=True,
        )
        self.assertEqual(result["classification"], "unverifiable")
        self.assertEqual(result["contract_assumptions"], [])

    def test_claimed_hevc_with_h264_payload_is_exact_failure(self) -> None:
        probe = self.terminal_probe("episode.mkv")
        probe["video_codecs"] = ["h264"]
        result = self.classify_in_temp(probe=probe)
        self.assertEqual(result["classification"], "payload_misrepresented")
        self.assertEqual(result["contract_failures"][0]["claim"], "hevc")

    def test_profile_change_classifies_profile_drift(self) -> None:
        result = self.classify_in_temp(current_profile="changed")
        self.assertEqual(result["classification"], "profile_drift")
        self.assertFalse(result["blocklist"])

    def test_new_current_file_classifies_superseded_in_flight(self) -> None:
        result = self.classify_in_temp(
            current_files=[{"target_id": 7859, "has_file": True, "file_id": 11}]
        )
        self.assertEqual(result["classification"], "superseded_in_flight")
        self.assertFalse(result["blocklist"])

    def test_pack_mapping_must_cover_every_payload_file(self) -> None:
        result = self.classify_in_temp(include_payload_mapping=False)
        self.assertEqual(result["classification"], "unverifiable")
        self.assertFalse(result["actionable"])

    def test_same_series_wrong_episode_target_fails_closed(self) -> None:
        candidate = self.candidate(7858, has_file=True, rejected=True)
        result = self.classify_in_temp(candidate=candidate)
        self.assertEqual(result["classification"], "unverifiable")
        self.assertTrue(result["target_mismatch"])
        self.assertFalse(result["actionable"])
        self.assertFalse(result["blocklist"])

    def test_context_identity_conflict_cannot_become_blocklist_action(self) -> None:
        context = self.terminal_context()
        context["identity_conflict"] = True
        result = self.classify_in_temp(context=context)
        self.assertEqual(result["classification"], "unverifiable")
        self.assertFalse(result["actionable"])
        self.assertFalse(result["blocklist"])

    def test_native_wrong_owner_is_identity_mismatch(self) -> None:
        candidate = self.candidate(7859, has_file=True, rejected=True)
        candidate["series"]["id"] = 61
        result = self.classify_in_temp(candidate=candidate)
        self.assertEqual(result["classification"], "identity_mismatch")
        self.assertTrue(result["actionable"])
        self.assertTrue(result["blocklist"])

    def test_canonical_year_title_collision_can_handoff_current_better(self) -> None:
        context = self.terminal_context()
        context["media"]["year"] = 2011
        context["canonical_title"] = "Blade (2011)"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Blade (2011) - S01E01 - His Name Is Blade.mkv"
            path.touch()
            candidate = self.candidate(19646, has_file=True, rejected=True)
            candidate.update(
                {
                    "path": str(path),
                    "series": {"id": 269, "title": "Blade"},
                    "episodes": [
                        {
                            "id": 19646,
                            "seasonNumber": 1,
                            "episodeNumber": 1,
                            "monitored": True,
                            "hasFile": True,
                        }
                    ],
                    "rejections": [
                        {"reason": "Episode 1x01 was not found in the grabbed release"},
                        {"reason": "Not a Custom Format upgrade for existing episode file(s)."},
                    ],
                }
            )
            result = MODULE.classify_terminal_download(
                "sonarr",
                context,
                [candidate],
                [self.terminal_probe(path.name)],
                {str(path.resolve()): path},
                "same",
                [{"target_id": 7859, "has_file": True, "file_id": 10}],
            )
        self.assertEqual(result["classification"], "current_better")
        self.assertTrue(result["canonical_title_collision"])
        self.assertTrue(result["actionable"])
        self.assertFalse(result["blocklist"])

    def test_incomplete_canonical_title_collision_fails_closed(self) -> None:
        context = self.terminal_context()
        context["media"]["year"] = 2011
        context["canonical_title"] = "Blade (2011)"
        context["expected_episodes"].append(
            {"id": 7860, "season": 1, "episode": 2}
        )
        candidate = self.candidate(19646, has_file=True, rejected=True)
        result = self.classify_in_temp(context=context, candidate=candidate)
        self.assertEqual(result["classification"], "unverifiable")
        self.assertFalse(result["actionable"])
        self.assertFalse(result["blocklist"])

    def test_duplicate_eligible_files_for_one_target_are_identity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / f"episode-{index}.mkv" for index in (1, 2)]
            for path in paths:
                path.touch()
            candidates = [self.candidate(7859, has_file=True) for _ in paths]
            for candidate, path in zip(candidates, paths, strict=True):
                candidate["path"] = str(path)
            result = MODULE.classify_terminal_download(
                "sonarr",
                self.terminal_context(),
                candidates,
                [self.terminal_probe(path.name) for path in paths],
                {str(path.resolve()): path for path in paths},
                "same",
                [{"target_id": 7859, "has_file": True, "file_id": 10}],
            )
        self.assertEqual(result["classification"], "identity_mismatch")
        self.assertEqual(result["duplicate_eligible_targets"], [7859])
        self.assertTrue(result["blocklist"])

    def test_validated_import_submits_exact_native_manual_import(
        self,
    ) -> None:
        class ArrClient:
            calls = []

            def request(self, method, path, params=None, body=None):
                self.calls.append((method, path, params, body))
                return {"id": 77}

        with tempfile.TemporaryDirectory() as directory:
            state = MODULE.HandoffState(Path(directory) / "state.json")
            client = ArrClient()
            result = MODULE.apply_validated_import(
                "sonarr",
                client,
                state,
                [{"downloadId": "ABC123"}],
                self.terminal_context(),
                [self.candidate(7859, has_file=True)],
                {"classification": "accepted", "actionable": False},
            )
            self.assertFalse(state.is_completed("sonarr", "ABC123"))
            self.assertEqual(
                state.pending_import("sonarr", "ABC123")["command_id"], 77
            )
        self.assertEqual(result["result"], "command_pending")
        self.assertEqual(client.calls[0][3]["files"][0]["episodeIds"], [7859])

    def test_validated_import_tracks_native_pending_command(
        self,
    ) -> None:
        class ArrClient:
            def request(self, method, path, params=None, body=None):
                self.body = body
                return {"id": 88}

        with tempfile.TemporaryDirectory() as directory:
            state = MODULE.HandoffState(Path(directory) / "state.json")
            result = MODULE.apply_validated_import(
                "sonarr",
                ArrClient(),
                state,
                [{"downloadId": "ABC123"}],
                self.terminal_context(),
                [self.candidate(7859, has_file=True)],
                {"classification": "accepted", "actionable": False},
            )
            self.assertFalse(state.is_completed("sonarr", "ABC123"))
            self.assertEqual(
                state.pending_import("sonarr", "ABC123")["command_id"], 88
            )
        self.assertEqual(result["result"], "command_pending")

    def test_pending_import_is_reconciled_by_exact_command_id(self) -> None:
        class ArrClient:
            calls = []

            def request(self, method, path, params=None, body=None):
                self.calls.append((method, path, params, body))
                return {"id": 88, "status": "started"}

        with tempfile.TemporaryDirectory() as directory:
            state = MODULE.HandoffState(Path(directory) / "state.json")
            state.mark_pending_import("sonarr", "ABC123", 88)
            client = ArrClient()
            result = MODULE.reconcile_pending_import(
                "sonarr", client, state, "ABC123"
            )
            self.assertIsNotNone(state.pending_import("sonarr", "ABC123"))
        self.assertEqual(result["result"], "native_import_pending")
        self.assertEqual(client.calls, [("GET", "/command/88", None, None)])

    def test_legacy_submitted_import_recovers_matching_native_command(self) -> None:
        class ArrClient:
            def request(self, method, path, params=None, body=None):
                self.path = path
                return [
                    {
                        "id": 88,
                        "name": "ManualImport",
                        "status": "completed",
                        "body": {"files": [{"downloadId": "ABC123"}]},
                    }
                ]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(
                MODULE.json.dumps(
                    {
                        "completed": {
                            "sonarr:abc123": {
                                "at": "2026-09-03T00:00:00Z",
                                "classification": "validated_import_submitted",
                            }
                        }
                    }
                )
            )
            state = MODULE.HandoffState(path)
            result = MODULE.reconcile_pending_import(
                "sonarr", ArrClient(), state, "ABC123"
            )
            self.assertTrue(state.is_completed("sonarr", "ABC123"))
            self.assertIsNone(state.pending_import("sonarr", "ABC123"))
        self.assertEqual(
            result["result"], "native_import_completed_waiting_for_queue_refresh"
        )

    def test_pending_import_state_prunes_downloads_absent_from_queue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = MODULE.HandoffState(Path(directory) / "state.json")
            state.mark_pending_import("sonarr", "KEEP", 1)
            state.mark_pending_import("sonarr", "DROP", 2)
            state.mark_pending_import("radarr", "OTHER", 3)
            state.prune_pending_imports("sonarr", {"keep"})
            self.assertIsNotNone(state.pending_import("sonarr", "KEEP"))
            self.assertIsNone(state.pending_import("sonarr", "DROP"))
            self.assertIsNotNone(state.pending_import("radarr", "OTHER"))

    def test_replacement_search_stays_deferred_while_import_is_pending(self) -> None:
        class ArrClient:
            def request(self, method, path, params=None, body=None):
                raise AssertionError("no Arr request is allowed while an import is pending")

        with tempfile.TemporaryDirectory() as directory:
            state = MODULE.HandoffState(Path(directory) / "state.json")
            key = "sonarr:series:42:season:1"
            state.stage_search(
                "sonarr",
                key,
                {"name": "SeasonSearch", "seriesId": 42, "seasonNumber": 1},
            )
            state.mark_pending_import("sonarr", "ABC123", 88)
            result = MODULE.dispatch_pending_searches(
                "sonarr", ArrClient(), state, {key}
            )
            self.assertEqual(len(state.pending_searches("sonarr")), 1)
            self.assertTrue(state.search_is_allowed(key))
        self.assertEqual(
            result[0]["result"], "replacement_search_deferred_import_pending"
        )

    def test_replacement_search_stays_deferred_for_native_active_import(self) -> None:
        class ArrClient:
            def request(self, method, path, params=None, body=None):
                self.path = path
                return [{"name": "ManualImport", "status": "started"}]

        with tempfile.TemporaryDirectory() as directory:
            state = MODULE.HandoffState(Path(directory) / "state.json")
            key = "radarr:movie:42"
            state.stage_search(
                "radarr", key, {"name": "MoviesSearch", "movieIds": [42]}
            )
            result = MODULE.dispatch_pending_searches(
                "radarr", ArrClient(), state, {key}
            )
            self.assertEqual(len(state.pending_searches("radarr")), 1)
        self.assertEqual(
            result[0]["result"], "replacement_search_deferred_import_pending"
        )

    def test_replacement_search_dispatches_after_imports_drain(self) -> None:
        class ArrClient:
            calls = []

            def request(self, method, path, params=None, body=None):
                self.calls.append((method, path, params, body))
                return [] if method == "GET" else {"id": 99}

        with tempfile.TemporaryDirectory() as directory:
            state = MODULE.HandoffState(Path(directory) / "state.json")
            key = "sonarr:series:42:season:1"
            body = {"name": "SeasonSearch", "seriesId": 42, "seasonNumber": 1}
            state.stage_search("sonarr", key, body)
            client = ArrClient()
            result = MODULE.dispatch_pending_searches(
                "sonarr", client, state, {key}
            )
            self.assertEqual(state.pending_searches("sonarr"), [])
            self.assertFalse(state.search_is_allowed(key))
        self.assertEqual(result[0]["result"], "replacement_search_scheduled")
        self.assertEqual(result[0]["command_id"], 99)
        self.assertEqual(client.calls[-1], ("POST", "/command", None, body))

    def test_unconfirmed_replacement_search_remains_pending_without_cooldown(self) -> None:
        class ArrClient:
            def request(self, method, path, params=None, body=None):
                return [] if method == "GET" else {}

        with tempfile.TemporaryDirectory() as directory:
            state = MODULE.HandoffState(Path(directory) / "state.json")
            key = "radarr:movie:42"
            state.stage_search(
                "radarr", key, {"name": "MoviesSearch", "movieIds": [42]}
            )
            result = MODULE.dispatch_pending_searches(
                "radarr", ArrClient(), state, {key}
            )
            self.assertEqual(len(state.pending_searches("radarr")), 1)
            self.assertTrue(state.search_is_allowed(key))
        self.assertEqual(
            result[0]["result"], "replacement_search_submission_unconfirmed"
        )

    @mock.patch.object(MODULE.time, "sleep")
    def test_wait_for_command_refreshes_heartbeat_while_running(
        self, sleep: mock.Mock
    ) -> None:
        class ArrClient:
            responses = iter(({"status": "started"}, {"status": "completed"}))

            def request(self, method, path, params=None, body=None):
                return next(self.responses)

        with tempfile.TemporaryDirectory() as directory:
            heartbeat = Path(directory) / "heartbeat"
            result = MODULE.wait_for_command(
                ArrClient(), 77, timeout=10, heartbeat=heartbeat
            )
            self.assertTrue(heartbeat.exists())
            self.assertTrue(MODULE.heartbeat_is_fresh(heartbeat, 1))
        self.assertEqual(result["status"], "completed")
        sleep.assert_called_once_with(2)

    def test_share_quota_uses_effective_ratio_or_time(self) -> None:
        self.assertTrue(MODULE.finite_share_quota({"max_ratio": 2.0}))
        self.assertTrue(
            MODULE.share_quota_met({"ratio": 2.1, "max_ratio": 2.0})
        )
        self.assertTrue(
            MODULE.share_quota_met(
                {"seeding_time": 3601, "max_seeding_time": 60}
            )
        )
        self.assertTrue(
            MODULE.share_quota_met(
                {"inactive_seeding_time": 3601, "max_inactive_seeding_time": 60}
            )
        )
        self.assertFalse(
            MODULE.finite_share_quota(
                {
                    "max_ratio": -1,
                    "max_seeding_time": -1,
                    "max_inactive_seeding_time": -1,
                }
            )
        )

    def test_handoff_preserves_limits_and_hides_arr_row(self) -> None:
        torrent = {
            "hash": "ABC123",
            "ratio": 0.5,
            "max_ratio": 5.0,
            "max_seeding_time": 43200,
            "max_inactive_seeding_time": -1,
            "ratio_limit": 5.0,
            "seeding_time_limit": 43200,
            "inactive_seeding_time_limit": -2,
            "share_limit_action": "Default",
        }

        class ArrClient:
            calls = []

            def request(self, method, path, params=None, body=None):
                self.calls.append((method, path, params, body))

        class Qbit:
            def __init__(self):
                self.value = dict(torrent)
                self.calls = []

            def set_share_limits(self, download_id, current, action):
                self.calls.append((download_id, current["ratio_limit"], action))
                self.value["share_limit_action"] = action

            def torrent(self, download_id):
                return dict(self.value)

        evaluation = {
            "classification": "current_better",
            "actionable": True,
            "blocklist": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            state = MODULE.HandoffState(Path(directory) / "handoff.json")
            arr = ArrClient()
            qbit = Qbit()
            result = MODULE.apply_terminal_handoff(
                "sonarr",
                arr,
                qbit,
                state,
                [{"id": 123}],
                self.terminal_context(),
                torrent,
                evaluation,
            )
        self.assertEqual(result["result"], "hidden_from_arr_seeding_until_quota")
        self.assertEqual(qbit.calls, [("abc123", 5.0, "RemoveWithContent")])
        self.assertEqual(arr.calls[0][2]["removeFromClient"], "false")
        self.assertEqual(arr.calls[0][2]["blocklist"], "false")

    def test_import_pending_requires_explicit_current_better_rejection(self) -> None:
        current_better = {
            "status": "completed",
            "trackedDownloadState": "importPending",
            "statusMessages": [
                {"messages": ["Not a Custom Format upgrade for existing episode file(s)."]}
            ],
        }
        xem_hold = {
            "status": "completed",
            "trackedDownloadState": "importPending",
            "statusMessages": [
                {"messages": ["TheXEM needs manual input."]}
            ],
        }
        self.assertTrue(MODULE.terminal_rows_are_eligible([current_better]))
        self.assertFalse(MODULE.terminal_rows_are_eligible([xem_hold]))
        self.assertFalse(MODULE.terminal_rows_are_xem_hold([current_better]))
        self.assertTrue(MODULE.terminal_rows_are_xem_hold([xem_hold]))

    def test_title_confirmed_xem_correction_uses_canonical_number_and_title(self) -> None:
        context = self.terminal_context()
        context["media"] = {"id": 42}
        context["source_title"] = (
            "Marvels.Hulk.S02E20.Days.of.Future.Smash.2.Smashgard.1080p-iVy"
        )
        context["expected_episodes"] = [
            {"id": 19, "season": 2, "episode": 19, "title": "The Dino Era"}
        ]
        candidate = self.candidate(19, has_file=False)
        candidate.update(
            {
                "path": (
                    "/data/Marvels.Hulk.S02E20.Days.of.Future.Smash."
                    "(2).Smashgard.1080p-iVy.mkv"
                ),
                "rejections": [{"reason": "TheXEM needs manual input."}],
                "series": {"id": 42},
            }
        )
        candidate["episodes"] = [{"id": 19}]

        class ArrClient:
            def request(self, method, path, params=None, body=None):
                self.call = (method, path, params, body)
                return [
                    {
                        "id": 19,
                        "seasonNumber": 2,
                        "episodeNumber": 19,
                        "sceneSeasonNumber": 2,
                        "sceneEpisodeNumber": 20,
                        "title": "Days of Future Smash (1): The Dino Era",
                        "monitored": True,
                        "hasFile": False,
                    },
                    {
                        "id": 20,
                        "seasonNumber": 2,
                        "episodeNumber": 20,
                        "sceneSeasonNumber": 2,
                        "sceneEpisodeNumber": 21,
                        "title": "Days of Future Smash (2): Smashgard",
                        "monitored": True,
                        "hasFile": False,
                    },
                ]

        client = ArrClient()
        corrected = MODULE.title_confirmed_xem_correction(
            client, context, [candidate]
        )
        self.assertIsNotNone(corrected)
        corrected_context, corrected_candidates, evidence = corrected
        self.assertEqual(
            corrected_context["expected_episodes"][0]["id"], 20
        )
        self.assertEqual(
            corrected_candidates[0]["episodes"][0]["id"], 20
        )
        self.assertEqual(corrected_candidates[0]["rejections"], [])
        self.assertEqual(evidence["from_target_id"], 19)
        self.assertEqual(evidence["to_target_id"], 20)
        self.assertEqual(client.call[:3], ("GET", "/episode", {"seriesId": 42}))

    def test_title_confirmed_xem_correction_allows_part_word_in_release(self) -> None:
        context = self.terminal_context()
        context["media"] = {"id": 42}
        context["source_title"] = "Marvels.Hulk.S02E26.Planet.Monster.Part.2-iVy"
        context["expected_episodes"] = [
            {"id": 25, "season": 2, "episode": 25, "title": "Planet Monster (1)"}
        ]
        candidate = self.candidate(25, has_file=False)
        candidate.update(
            {
                "path": "/data/Marvels.Hulk.S02E26.Planet.Monster.Part.2-iVy.mkv",
                "rejections": [{"reason": "TheXEM needs manual input."}],
                "series": {"id": 42},
            }
        )
        candidate["episodes"] = [{"id": 25}]

        class ArrClient:
            def request(self, method, path, params=None, body=None):
                return [
                    {
                        "id": 25,
                        "seasonNumber": 2,
                        "episodeNumber": 25,
                        "sceneSeasonNumber": 2,
                        "sceneEpisodeNumber": 26,
                        "title": "Planet Monster (1)",
                        "monitored": True,
                        "hasFile": False,
                    },
                    {
                        "id": 26,
                        "seasonNumber": 2,
                        "episodeNumber": 26,
                        "sceneSeasonNumber": 2,
                        "sceneEpisodeNumber": 27,
                        "title": "Planet Monster (2)",
                        "monitored": True,
                        "hasFile": False,
                    },
                ]

        corrected = MODULE.title_confirmed_xem_correction(
            ArrClient(), context, [candidate]
        )
        self.assertIsNotNone(corrected)
        self.assertEqual(corrected[2]["to_target_id"], 26)

    def test_xem_correction_ignores_technical_numbers_after_episode_title(self) -> None:
        context = self.terminal_context()
        context["media"] = {"id": 42}
        context["source_title"] = (
            "Marvels.Hulk.S02E25.Planet.Monster.Part.1.EAC3.5.1.1080p-iVy"
        )
        context["expected_episodes"] = [
            {"id": 24, "season": 2, "episode": 24, "title": "Spirit of Vengeance"}
        ]
        candidate = self.candidate(24, has_file=False)
        candidate.update(
            {
                "path": (
                    "/data/Marvels.Hulk.S02E25.Planet.Monster.Part.1."
                    "EAC3.5.1.1080p.WEBRip.x265-iVy.mkv"
                ),
                "rejections": [{"reason": "TheXEM needs manual input."}],
                "series": {"id": 42},
            }
        )
        candidate["episodes"] = [{"id": 24}]

        class ArrClient:
            def request(self, method, path, params=None, body=None):
                return [
                    {
                        "id": 24,
                        "seasonNumber": 2,
                        "episodeNumber": 24,
                        "sceneSeasonNumber": 2,
                        "sceneEpisodeNumber": 25,
                        "title": "Spirit of Vengeance",
                        "monitored": True,
                        "hasFile": False,
                    },
                    {
                        "id": 25,
                        "seasonNumber": 2,
                        "episodeNumber": 25,
                        "sceneSeasonNumber": 2,
                        "sceneEpisodeNumber": 26,
                        "title": "Planet Monster (1)",
                        "monitored": True,
                        "hasFile": False,
                    },
                    {
                        "id": 26,
                        "seasonNumber": 2,
                        "episodeNumber": 26,
                        "sceneSeasonNumber": 2,
                        "sceneEpisodeNumber": 27,
                        "title": "Planet Monster (2)",
                        "monitored": True,
                        "hasFile": False,
                    },
                ]

        diagnostics = {}
        corrected = MODULE.title_confirmed_xem_correction(
            ArrClient(), context, [candidate], diagnostics
        )
        self.assertIsNotNone(corrected)
        self.assertEqual(corrected[2]["to_target_id"], 25)
        self.assertEqual(corrected[2]["title_region"], "Planet.Monster.Part.1")
        self.assertEqual(diagnostics, {})

    def test_xem_correction_rejects_title_disagreement(self) -> None:
        context = self.terminal_context()
        context["media"] = {"id": 42}
        context["source_title"] = "Example.S02E20.Wrong.Title.1080p-GROUP"
        context["expected_episodes"] = [
            {"id": 19, "season": 2, "episode": 19, "title": "Old Target"}
        ]
        candidate = self.candidate(19, has_file=False)
        candidate.update(
            {
                "path": "/data/Example.S02E20.Wrong.Title.1080p-GROUP.mkv",
                "rejections": [{"reason": "TheXEM needs manual input."}],
                "series": {"id": 42},
            }
        )
        candidate["episodes"] = [{"id": 19}]

        class ArrClient:
            def request(self, method, path, params=None, body=None):
                return [
                    {
                        "id": 19,
                        "seasonNumber": 2,
                        "episodeNumber": 19,
                        "sceneSeasonNumber": 2,
                        "sceneEpisodeNumber": 20,
                        "title": "Old Target",
                        "monitored": True,
                        "hasFile": False,
                    },
                    {
                        "id": 20,
                        "seasonNumber": 2,
                        "episodeNumber": 20,
                        "sceneSeasonNumber": 2,
                        "sceneEpisodeNumber": 21,
                        "title": "Canonical Target",
                        "monitored": True,
                        "hasFile": False,
                    },
                ]

        diagnostics = {}
        self.assertIsNone(
            MODULE.title_confirmed_xem_correction(
                ArrClient(), context, [candidate], diagnostics
            )
        )
        self.assertEqual(diagnostics["guard"], "canonical_title")

    def test_usenet_current_better_is_removed_without_blocklist(self) -> None:
        class ArrClient:
            calls = []

            def request(self, method, path, params=None, body=None):
                self.calls.append((method, path, params, body))

        evaluation = {
            "classification": "current_better",
            "actionable": True,
            "blocklist": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            state = MODULE.HandoffState(Path(directory) / "handoff.json")
            arr = ArrClient()
            result = MODULE.apply_usenet_terminal_handoff(
                "radarr",
                arr,
                state,
                [{"id": 456, "downloadId": "SAB123"}],
                {"media": {"id": 42}},
                evaluation,
            )
            self.assertTrue(state.is_completed("radarr", "sab123"))
        self.assertEqual(result["result"], "removed_from_arr_and_sab")
        self.assertEqual(arr.calls[0][2]["removeFromClient"], "true")
        self.assertEqual(arr.calls[0][2]["blocklist"], "false")

    def test_handoff_readback_failure_restores_original_action(self) -> None:
        torrent = {
            "hash": "ABC123",
            "ratio": 0.5,
            "max_ratio": 5.0,
            "max_seeding_time": -1,
            "max_inactive_seeding_time": -1,
            "ratio_limit": 5.0,
            "seeding_time_limit": -1,
            "inactive_seeding_time_limit": -1,
            "share_limit_action": "Default",
        }

        class ArrClient:
            def request(self, method, path, params=None, body=None):
                raise AssertionError("Arr must remain untouched after failed qBit readback")

        class Qbit:
            def __init__(self):
                self.actions = []
                self.action = "Default"

            def set_share_limits(self, download_id, current, action):
                self.actions.append(action)
                self.action = action

            def torrent(self, download_id):
                ratio_limit = 4.0 if self.action == "RemoveWithContent" else 5.0
                return {
                    **torrent,
                    "ratio_limit": ratio_limit,
                    "share_limit_action": self.action,
                }

        with tempfile.TemporaryDirectory() as directory:
            qbit = Qbit()
            result = MODULE.apply_terminal_handoff(
                "sonarr",
                ArrClient(),
                qbit,
                MODULE.HandoffState(Path(directory) / "handoff.json"),
                [{"id": 123}],
                self.terminal_context(),
                torrent,
                {
                    "classification": "current_better",
                    "actionable": True,
                    "blocklist": False,
                },
            )
        self.assertEqual(result["result"], "left_untouched_qbit_readback_failed")
        self.assertEqual(qbit.actions, ["RemoveWithContent", "Default"])

    @mock.patch.object(MODULE, "classify_terminal_download")
    @mock.patch.object(MODULE, "current_policy_state")
    @mock.patch.object(MODULE, "payload_probes")
    @mock.patch.object(MODULE, "ledger_context")
    @mock.patch.object(MODULE, "queue_records")
    def test_terminal_manual_import_preserves_native_download_id_case(
        self,
        queue_records: mock.Mock,
        ledger_context: mock.Mock,
        payload_probes: mock.Mock,
        current_policy_state: mock.Mock,
        classify: mock.Mock,
    ) -> None:
        queue_records.return_value = [
            {
                "id": 1,
                "downloadId": "ABCDEF1234",
                "status": "completed",
                "trackedDownloadState": "importBlocked",
                "protocol": "torrent",
            }
        ]
        ledger_context.return_value = self.terminal_context()
        payload_probes.return_value = ([], {})
        current_policy_state.return_value = ("same", [])
        classify.return_value = {
            "classification": "accepted",
            "actionable": False,
            "blocklist": False,
        }

        class ArrClient:
            manual_id = None

            def request(self, method, path, params=None, body=None):
                if path == "/manualimport":
                    self.manual_id = params["downloadId"]
                    return []
                raise AssertionError((method, path, params, body))

        class Qbit:
            def torrent(self, download_id):
                return {"hash": download_id}

            def files(self, download_id):
                return []

        client = ArrClient()
        with tempfile.TemporaryDirectory() as directory:
            MODULE.reconcile_terminal_app(
                "sonarr",
                client,
                object(),
                Qbit(),
                MODULE.HandoffState(Path(directory) / "state.json"),
                "audit",
                set(),
                120,
                30,
                5,
            )
        self.assertEqual(client.manual_id, "ABCDEF1234")

    @mock.patch.object(MODULE, "classify_terminal_download")
    @mock.patch.object(MODULE, "current_policy_state")
    @mock.patch.object(MODULE, "payload_probes")
    @mock.patch.object(MODULE, "ledger_context")
    @mock.patch.object(MODULE, "queue_records")
    def test_terminal_cycle_rotates_past_persistent_unverifiable_rows(
        self,
        queue_records: mock.Mock,
        ledger_context: mock.Mock,
        payload_probes: mock.Mock,
        current_policy_state: mock.Mock,
        classify: mock.Mock,
    ) -> None:
        queue_records.return_value = [
            {
                "id": index,
                "downloadId": download_id,
                "status": "completed",
                "trackedDownloadState": "importBlocked",
                "protocol": "torrent",
            }
            for index, download_id in enumerate(("AAAA", "BBBB"), start=1)
        ]
        ledger_context.return_value = self.terminal_context()
        payload_probes.return_value = ([], {})
        current_policy_state.return_value = ("same", [])
        classify.return_value = {
            "classification": "unverifiable",
            "actionable": False,
            "blocklist": False,
        }

        class ArrClient:
            def request(self, method, path, params=None, body=None):
                if path == "/manualimport":
                    return []
                raise AssertionError((method, path, params, body))

        class Qbit:
            def torrent(self, download_id):
                return {"hash": download_id}

            def files(self, download_id):
                return []

        with tempfile.TemporaryDirectory() as directory:
            state = MODULE.HandoffState(Path(directory) / "state.json")
            for _ in range(2):
                MODULE.reconcile_terminal_app(
                    "sonarr",
                    ArrClient(),
                    object(),
                    Qbit(),
                    state,
                    "audit",
                    set(),
                    120,
                    30,
                    1,
                )
        self.assertEqual(
            [call.args[1] for call in ledger_context.call_args_list],
            ["AAAA", "BBBB"],
        )


if __name__ == "__main__":
    unittest.main()
