#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("arr_regular_english_language_guard.py")
SPEC = importlib.util.spec_from_file_location("arr_regular_english_language_guard", MODULE_PATH)
assert SPEC and SPEC.loader
GUARD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = GUARD
SPEC.loader.exec_module(GUARD)


class RegularEnglishLanguageGuardTests(unittest.TestCase):
    def assert_matches(self, title: str) -> None:
        self.assertIsNotNone(re.search(GUARD.GUARD_REGEX, title, re.IGNORECASE))

    def assert_does_not_match(self, title: str) -> None:
        self.assertIsNone(re.search(GUARD.GUARD_REGEX, title, re.IGNORECASE))

    def test_standalone_multi_before_quality_is_guarded(self) -> None:
        self.assert_matches(
            "King.of.the.Hill.S09E01.MULTI.1080p.DSNP.WEB-DL.AAC2.0.H.264-AndreMor"
        )

    def test_existing_explicit_audio_markers_remain_guarded(self) -> None:
        self.assert_matches("Example.S01E01.Multi.Audio.1080p.WEB-DL")
        self.assert_matches("Example.S01E01.German.DL.1080p.WEB-DL")

    def test_multisub_markers_are_not_guarded(self) -> None:
        self.assert_does_not_match("Example.S01E01.MultiSub.1080p.WEB-DL")
        self.assert_does_not_match("Example.S01E01.MULTI.SUBS.1080p.WEB-DL")

    def test_language_words_without_audio_markers_are_not_guarded(self) -> None:
        self.assert_does_not_match("The.French.Dispatch.2021.1080p.BluRay")

    def test_existing_custom_format_payload_is_idempotent(self) -> None:
        existing = {
            "id": 128,
            "name": GUARD.CUSTOM_FORMAT_NAME,
            "includeCustomFormatWhenRenaming": False,
            "specifications": [GUARD.title_spec(GUARD.GUARD_REGEX, "sonarr")],
        }
        self.assertEqual(
            GUARD.custom_format_payload(existing, GUARD.GUARD_REGEX, "sonarr"),
            existing,
        )


if __name__ == "__main__":
    unittest.main()
