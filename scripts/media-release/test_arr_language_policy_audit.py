#!/usr/bin/env python3
"""Focused regressions for the Arr language and embedded-subtitle audit."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/media-release/arr_language_policy_audit.py"
SPEC = importlib.util.spec_from_file_location("arr_language_policy_audit", SOURCE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to load {SOURCE}")
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


def row(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "original_key": "en",
        "profile_class": "regular",
        "custom_formats": [],
        "source_title": "Example.S01E01.1080p.WEB-DL-GROUP",
        "arr_languages": ["en"],
        "probe_languages": [],
        "arr_subtitle_languages": [],
        "arr_subtitle_count": 0,
        "probe_subtitle_languages": [],
        "probe_subtitle_count": 0,
        "probe_enabled": False,
        "probe_errors": [],
    }
    value.update(overrides)
    return value


class SubtitleAuditTests(unittest.TestCase):
    def test_subtitle_metadata_normalizes_arr_codes(self) -> None:
        languages, count = AUDIT.subtitle_metadata({"subtitles": "eng/spa/Unknown"})
        self.assertEqual(languages, {"en", "es"})
        self.assertEqual(count, 3)

    def test_no_embedded_subtitles_is_flagged_for_english_original_media(self) -> None:
        self.assertIn("no_embedded_subtitles", AUDIT.classify_flags(row()))

    def test_non_english_embedded_subtitles_without_english_are_flagged(self) -> None:
        flags = AUDIT.classify_flags(
            row(arr_subtitle_languages=["ja"], arr_subtitle_count=1)
        )
        self.assertIn("embedded_subtitles_missing_english", flags)
        self.assertNotIn("embedded_english_subtitle_ok", flags)

    def test_probe_success_with_zero_subtitles_overrides_stale_arr_metadata(self) -> None:
        flags = AUDIT.classify_flags(
            row(
                arr_subtitle_languages=["en"],
                arr_subtitle_count=1,
                probe_enabled=True,
                probe_subtitle_languages=[],
                probe_subtitle_count=0,
            )
        )
        self.assertIn("no_embedded_subtitles", flags)

    def test_embedded_english_subtitle_is_accepted(self) -> None:
        flags = AUDIT.classify_flags(
            row(arr_subtitle_languages=["en"], arr_subtitle_count=1)
        )
        self.assertIn("embedded_english_subtitle_ok", flags)
        self.assertNotIn("no_embedded_subtitles", flags)
        self.assertNotIn("embedded_subtitles_missing_english", flags)

    def test_subtitle_gap_summaries_group_actionable_dimensions(self) -> None:
        rows = [
            {
                "app": "sonarr",
                "profile_name": "shows-regular-efficient",
                "original_language": "English",
                "release_group": "iVy",
            },
            {
                "app": "sonarr",
                "profile_name": "shows-regular-efficient",
                "original_language": "English",
                "release_group": "",
            },
            {
                "app": "radarr",
                "profile_name": "movies-anime-efficient",
                "original_language": "Japanese",
                "release_group": "iVy",
            },
        ]
        summary = AUDIT.subtitle_gap_summaries(rows)
        self.assertEqual(summary["app"], {"sonarr": 2, "radarr": 1})
        self.assertEqual(summary["profile"]["shows-regular-efficient"], 2)
        self.assertEqual(summary["original_language"], {"English": 2, "Japanese": 1})
        self.assertEqual(summary["release_group"], {"iVy": 2, "Unknown": 1})


if __name__ == "__main__":
    unittest.main()
