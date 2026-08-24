#!/usr/bin/env python3
"""Regression tests for exact-ID context and safe title prefixing."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


QBIT = load_module("qbit_release_stamper", "files/qbit-release-stamper.py")
SAB = load_module("sab_release_stamper", "files/sab-release-stamper.py")


class PrefixSafetyTests(unittest.TestCase):
    def test_qbit_episode_first_file_gets_canonical_prefix(self) -> None:
        result = QBIT.path_with_episode_title_prefix(
            "S01E01 - Prologue.mkv",
            "Dragon Ball Kai",
            ["Dragon Ball Z Kai"],
        )
        self.assertEqual(result, "Dragon Ball Kai - S01E01 - Prologue.mkv")

    def test_sab_episode_first_file_gets_canonical_prefix(self) -> None:
        result = SAB.path_with_episode_title_prefix(
            Path("S01E01 - Prologue.mkv"),
            "Dragon Ball Kai",
            ["Dragon Ball Z Kai"],
        )
        self.assertEqual(result.name, "Dragon Ball Kai - S01E01 - Prologue.mkv")

    def test_known_alternate_title_is_rewritten_to_canonical(self) -> None:
        name = "Dragon.Ball.Z.Kai.S01E01.1080p.x265-GROUP.mkv"
        self.assertEqual(
            QBIT.path_with_episode_title_prefix(name, "Dragon Ball Kai", ["Dragon Ball Z Kai"]),
            "Dragon Ball Kai - S01E01.1080p.x265-GROUP.mkv",
        )

    def test_short_canonical_title_replaces_long_known_alias(self) -> None:
        name = "Gyakkyou.Burai.Kaiji.Hakairoku-hen.S02E01.1080p.HEVC.mkv"
        self.assertEqual(
            QBIT.path_with_episode_title_prefix(name, "Kaiji", ["Gyakkyou Burai Kaiji Hakairoku-hen"]),
            "Kaiji - S02E01.1080p.HEVC.mkv",
        )
        self.assertEqual(
            SAB.path_with_episode_title_prefix(
                Path(name),
                "Kaiji",
                ["Gyakkyou Burai Kaiji Hakairoku-hen"],
            ).name,
            "Kaiji - S02E01.1080p.HEVC.mkv",
        )

    def test_canonical_title_with_release_group_is_left_intact(self) -> None:
        name = "[Judas] Dragon Ball Daima - S01E01v2.mkv"
        self.assertEqual(
            QBIT.path_with_episode_title_prefix(name, "Dragon Ball DAIMA", ["Dragon Ball DAIMA"]),
            name,
        )

    def test_wrong_series_payload_is_never_prefixed(self) -> None:
        name = "L.A.Law.S01E01.Pilot.1080p.x265-iVy.mkv"
        self.assertEqual(
            QBIT.path_with_episode_title_prefix(name, "She-Hulk: Attorney at Law", []),
            name,
        )

    def test_movie_without_episode_token_is_never_prefixed(self) -> None:
        name = "Spider.2002.1080p.BluRay.x265-GROUP.mkv"
        self.assertEqual(QBIT.path_with_episode_title_prefix(name, "Spider-Noir", []), name)

    def test_english_original_never_gets_foreign_dual_audio_tag(self) -> None:
        self.assertIsNone(QBIT.language_combo_tag_from_languages({"eng", "jpn"}, {"eng"}))

    def test_trusted_ledger_group_is_appended_for_ambiguous_payload_suffix(self) -> None:
        qbit_tags, qbit_group, _ = QBIT.wanted_tags(
            "Shelter.2026.1080p.x265.-.DarQ.HONE.mkv",
            None,
            {"eng"},
            "Shelter.2026.1080p.x265.-.DarQ",
            "DarQ",
        )
        sab_tags, sab_group = SAB.wanted_tags(
            "Shelter.2026.1080p.x265.-.DarQ.HONE.mkv",
            Path("/nonexistent/Shelter.mkv"),
            {"eng"},
            "Shelter.2026.1080p.x265.-.DarQ",
            "DarQ",
        )
        self.assertEqual(qbit_tags, [])
        self.assertEqual(sab_tags, [])
        self.assertEqual(qbit_group, "DarQ")
        self.assertEqual(sab_group, "DarQ")

    def test_trusted_ledger_group_is_not_duplicated_when_terminal(self) -> None:
        _, qbit_group, _ = QBIT.wanted_tags(
            "Shelter.2026.1080p.x265-DarQ.mkv",
            None,
            {"eng"},
            "Shelter.2026.1080p.x265-DarQ",
            "DarQ",
        )
        _, sab_group = SAB.wanted_tags(
            "Shelter.2026.1080p.x265-DarQ.mkv",
            Path("/nonexistent/Shelter.mkv"),
            {"eng"},
            "Shelter.2026.1080p.x265-DarQ",
            "DarQ",
        )
        self.assertIsNone(qbit_group)
        self.assertIsNone(sab_group)

    def test_sab_exact_download_id_does_not_accept_partial_match(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"records":[{"downloadId":"nzo_abc123","title":"Dragon Ball"}]}'

        original = SAB.urllib.request.urlopen
        SAB.urllib.request.urlopen = lambda *_args, **_kwargs: Response()
        try:
            self.assertIsNone(SAB.arr_queue_record_by_download_id("http://sonarr/api/v3", "key", "abc123"))
            self.assertEqual(
                SAB.arr_queue_record_by_download_id("http://sonarr/api/v3", "key", "NZO_ABC123")["title"],
                "Dragon Ball",
            )
        finally:
            SAB.urllib.request.urlopen = original


if __name__ == "__main__":
    unittest.main()
