#!/usr/bin/env python3
"""Regression tests for arr_grab_context.py."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("arr_grab_context.py")
SPEC = importlib.util.spec_from_file_location("arr_grab_context", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GrabContextTests(unittest.TestCase):
    def test_canonical_title_match(self) -> None:
        result = MODULE.identity_evidence(
            "Dragon Ball Kai",
            ["Dragon Ball Kai (2009)", "Dragon Ball Z Kai"],
            "[SoM] Dragon Ball Kai (2009) (BD 1080p x264 FLAC) [Dual Audio]",
        )
        self.assertTrue(result["identity_match"])

    def test_alternate_title_match(self) -> None:
        result = MODULE.identity_evidence(
            "Kaiji",
            ["Gyakkyou Burai Kaiji Hakairoku-hen"],
            "Gyakkyou Burai Kaiji Hakairoku-hen 1080p HEVC",
        )
        self.assertTrue(result["identity_match"])
        self.assertEqual(result["matched_alias"], "Gyakkyou Burai Kaiji Hakairoku-hen")

    def test_wrong_series_is_conflict(self) -> None:
        result = MODULE.identity_evidence(
            "She-Hulk: Attorney at Law",
            [],
            "L.A.Law.S01E01.Pilot.1080p.DSNP.WEBRip.x265-iVy",
        )
        self.assertFalse(result["identity_match"])

    def test_short_alias_must_be_a_whole_token(self) -> None:
        self.assertTrue(MODULE.alias_matches_source("DBZ", "DBZ S01E01 1080p"))
        self.assertFalse(MODULE.alias_matches_source("DBZ", "SomeDBZLikeTitle S01E01"))

    @mock.patch.object(MODULE, "enrich_media")
    def test_sonarr_context_records_expected_episode_and_language(self, enrich: mock.Mock) -> None:
        enrich.return_value = (
            {
                "id": 7,
                "title": "Dragon Ball Kai",
                "originalLanguage": {"name": "Japanese"},
                "alternateTitles": [{"title": "Dragon Ball Z Kai"}],
                "tvdbId": 88031,
            },
            None,
        )
        context = MODULE.build_context(
            {
                "eventType": "Grab",
                "instanceName": "Sonarr",
                "downloadId": "ABC123",
                "series": {"id": 7, "title": "Dragon Ball Kai"},
                "episodes": [{"id": 99, "seasonNumber": 1, "episodeNumber": 1, "title": "Prologue"}],
                "release": {
                    "releaseTitle": "Dragon.Ball.Z.Kai.S01E01.1080p.x265-GROUP",
                    "releaseGroup": "GROUP",
                    "customFormatScore": 140000,
                    "customFormats": [{"name": "Anime Dual Audio"}, {"name": "x265"}],
                },
            }
        )
        self.assertEqual(context["download_id"], "abc123")
        self.assertEqual(context["original_languages"], ["jpn"])
        self.assertTrue(context["identity_match"])
        self.assertEqual(context["expected_episodes"][0]["episode"], 1)
        self.assertEqual(context["custom_format_score"], 140000)

    @mock.patch.object(MODULE, "enrich_media")
    def test_wrong_target_context_is_marked_conflict(self, enrich: mock.Mock) -> None:
        enrich.return_value = ({"id": 1, "title": "She-Hulk: Attorney at Law", "alternateTitles": []}, None)
        context = MODULE.build_context(
            {
                "eventType": "Grab",
                "downloadId": "wrong-target",
                "series": {"id": 1, "title": "She-Hulk: Attorney at Law"},
                "episodes": [{"seasonNumber": 1, "episodeNumber": 1}],
                "release": {"releaseTitle": "L.A.Law.S01E01.1080p.x265-iVy"},
            }
        )
        self.assertTrue(context["identity_conflict"])
        self.assertFalse(context["identity_match"])

    @mock.patch.object(MODULE, "enrich_media")
    def test_english_original_language_is_preserved(self, enrich: mock.Mock) -> None:
        enrich.return_value = (
            {
                "id": 2,
                "title": "Family Guy",
                "originalLanguage": {"name": "English"},
                "alternateTitles": [],
            },
            None,
        )
        context = MODULE.build_context(
            {
                "eventType": "Grab",
                "downloadId": "english-original",
                "series": {"id": 2, "title": "Family Guy"},
                "episodes": [{"seasonNumber": 1, "episodeNumber": 1}],
                "release": {"releaseTitle": "Family.Guy.S01E01.1080p.x265-GROUP"},
            }
        )
        self.assertEqual(context["original_languages"], ["eng"])

    def test_store_is_exact_and_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MODULE.ContextStore(Path(directory) / "context.db")
            context = {
                "download_id": "abc123",
                "app": "sonarr",
                "captured_at": MODULE.iso_utc(),
                "canonical_title": "Dragon Ball Kai",
            }
            store.upsert(context)
            self.assertEqual(store.get("ABC123")["canonical_title"], "Dragon Ball Kai")
            self.assertIsNone(store.get("abc12"))


if __name__ == "__main__":
    unittest.main()
