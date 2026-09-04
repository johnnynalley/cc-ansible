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

    def test_distinctive_primary_title_before_subtitle_separator_matches(self) -> None:
        result = MODULE.identity_evidence(
            "KonoSuba – God's Blessing on This Wonderful World!!",
            [],
            "[Arid] KonoSuba S2 1080p BluRay Dual Audio x265",
        )
        self.assertTrue(result["identity_match"])
        self.assertEqual(result["matched_alias"], "KonoSuba")

    def test_short_generic_primary_title_is_not_derived(self) -> None:
        result = MODULE.identity_evidence(
            "It: Welcome to Derry",
            [],
            "Welcome.to.Derry.S01E01.1080p.x265-GROUP",
        )
        self.assertFalse(result["identity_match"])

    def test_short_alias_must_be_a_whole_token(self) -> None:
        self.assertTrue(MODULE.alias_matches_source("DBZ", "DBZ S01E01 1080p"))
        self.assertFalse(MODULE.alias_matches_source("DBZ", "SomeDBZLikeTitle S01E01"))

    def test_release_without_disambiguating_year_matches_canonical_title(self) -> None:
        result = MODULE.identity_evidence(
            "Blade (2011)",
            [],
            "Blade.S01.1080p.AMZN.WEB-DL.DDP5.1.H.264-Azkars",
        )
        self.assertTrue(result["identity_match"])
        self.assertEqual(result["matched_alias"], "Blade")

    def test_short_generic_title_does_not_gain_yearless_alias(self) -> None:
        result = MODULE.identity_evidence(
            "It (1990)",
            [],
            "Welcome.to.Derry.S01E01.1080p.x265-GROUP",
        )
        self.assertFalse(result["identity_match"])

    def test_leading_article_can_be_removed_from_distinctive_title(self) -> None:
        result = MODULE.identity_evidence(
            "The Incredible Hulk (1982)",
            [],
            "Incredible Hulk (1982) S1 Ep4 (DB2K9-DCP).avi",
        )
        self.assertTrue(result["identity_match"])
        self.assertEqual(result["matched_alias"], "Incredible Hulk (1982)")

    def test_html_ampersand_and_possessive_normalize_for_identity(self) -> None:
        result = MODULE.identity_evidence(
            "Marvel's Cloak & Dagger",
            [],
            "Marvels.Cloak.&amp;.Dagger.S01E10.1080p.WEB-DL",
        )
        self.assertTrue(result["identity_match"])

    def test_distinctive_episode_title_can_confirm_romanized_series(self) -> None:
        result = MODULE.identity_evidence(
            "Disney Twisted-Wonderland: The Animation",
            [],
            "Dizuni.Tsuisuteddo.Wandarando.za.Animeshon.S01E08."
            "Finale.for.Heartslabyul.1080p.WEB-DL",
            [{"season": 1, "episode": 8, "title": "Finale for Heartslabyul"}],
        )
        self.assertTrue(result["identity_match"])
        self.assertEqual(result["matched_episode_title"], "Finale for Heartslabyul")

    def test_short_multiword_episode_title_can_confirm_romanized_series(self) -> None:
        result = MODULE.identity_evidence(
            "Disney Twisted-Wonderland: The Animation",
            [],
            "Dizuni.Tsuisuteddo.Wandarando.za.Animeshon.S01E06."
            "An.Army.of.One.1080p.WEB-DL",
            [{"season": 1, "episode": 6, "title": "An Army of One"}],
        )
        self.assertTrue(result["identity_match"])
        self.assertEqual(result["matched_episode_title"], "An Army of One")

    def test_generic_episode_title_cannot_override_wrong_series(self) -> None:
        result = MODULE.identity_evidence(
            "She-Hulk: Attorney at Law",
            [],
            "L.A.Law.S01E01.Episode.1.1080p.WEB-DL",
            [{"season": 1, "episode": 1, "title": "Episode 1"}],
        )
        self.assertFalse(result["identity_match"])

    @mock.patch.object(MODULE, "enrich_media")
    @mock.patch.object(MODULE, "capture_policy_state")
    def test_sonarr_context_records_expected_episode_and_language(
        self, capture: mock.Mock, enrich: mock.Mock
    ) -> None:
        capture.return_value = (
            {"id": 3, "name": "shows-anime-efficient", "fingerprint": "abc123"},
            [{"target_id": 99, "has_file": True, "file_id": 700, "custom_format_score": 45000}],
            [],
        )
        enrich.return_value = (
            {
                "id": 7,
                "title": "Dragon Ball Kai",
                "originalLanguage": {"name": "Japanese"},
                "alternateTitles": [{"title": "Dragon Ball Z Kai"}],
                "tvdbId": 88031,
                "qualityProfileId": 3,
            },
            None,
        )
        context = MODULE.build_context(
            {
                "eventType": "Grab",
                "instanceName": "Sonarr",
                "downloadId": "ABC123",
                "series": {"id": 7, "title": "Dragon Ball Kai"},
                "episodes": [
                    {
                        "id": 99,
                        "seasonNumber": 1,
                        "episodeNumber": 1,
                        "absoluteEpisodeNumber": 17,
                        "title": "Prologue",
                    }
                ],
                "release": {
                    "releaseTitle": "Dragon.Ball.Z.Kai.S01E01.1080p.x265-GROUP",
                    "releaseGroup": "GROUP",
                    "protocol": "torrent",
                    "indexerId": 12,
                    "customFormatScore": 140000,
                    "customFormats": [{"name": "Anime Dual Audio"}, {"name": "x265"}],
                },
            }
        )
        self.assertEqual(context["download_id"], "abc123")
        self.assertEqual(context["original_languages"], ["jpn"])
        self.assertTrue(context["identity_match"])
        self.assertEqual(context["expected_episodes"][0]["episode"], 1)
        self.assertEqual(context["expected_episodes"][0]["absolute_episode"], 17)
        self.assertEqual(context["custom_format_score"], 140000)
        self.assertEqual(context["schema_version"], 2)
        self.assertEqual(context["protocol"], "torrent")
        self.assertEqual(context["indexer_id"], 12)
        self.assertEqual(context["quality_profile"]["fingerprint"], "abc123")
        self.assertEqual(context["current_files"][0]["file_id"], 700)

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

    def test_profile_snapshot_changes_when_policy_changes(self) -> None:
        first = MODULE.profile_snapshot(
            {"id": 3, "name": "efficient", "cutoffFormatScore": 200000}
        )
        second = MODULE.profile_snapshot(
            {"id": 3, "name": "efficient", "cutoffFormatScore": 200001}
        )
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])

    def test_current_file_snapshot_preserves_grab_time_score(self) -> None:
        snapshot = MODULE.current_file_snapshot(
            99,
            {
                "id": 700,
                "quality": {"quality": {"name": "Bluray-1080p"}},
                "customFormatScore": 145000,
                "customFormats": [{"name": "Anime Dual Audio"}],
            },
        )
        self.assertEqual(snapshot["target_id"], 99)
        self.assertEqual(snapshot["quality"], "Bluray-1080p")
        self.assertEqual(snapshot["custom_format_score"], 145000)

    def test_existing_context_identity_is_recomputed_on_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MODULE.ContextStore(Path(directory) / "context.db")
            store.upsert(
                {
                    "download_id": "konosuba",
                    "app": "sonarr",
                    "captured_at": MODULE.iso_utc(),
                    "canonical_title": "KonoSuba – God's Blessing on This Wonderful World!!",
                    "aliases": ["KonoSuba – God's Blessing on This Wonderful World!!"],
                    "source_title": "[Arid] KonoSuba S2 1080p Dual Audio x265",
                    "identity_match": False,
                    "identity_conflict": True,
                }
            )
            context = store.get("konosuba")
            self.assertTrue(context["identity_match"])
            self.assertFalse(context["identity_conflict"])
            self.assertEqual(context["matched_alias"], "KonoSuba")


if __name__ == "__main__":
    unittest.main()
