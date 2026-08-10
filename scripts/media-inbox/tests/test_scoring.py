from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from immich_media_inbox.scoring import (  # noqa: E402
    detect_candidate,
    extract_title_phrases,
    extract_year,
    ocr_text,
    rank_seerr_results,
)


def ocr_row(text: str, y: float, *, score: float = 0.95) -> dict[str, object]:
    return {
        "text": text,
        "textScore": score,
        "isVisible": True,
        "x1": 20,
        "x2": 400,
        "x3": 400,
        "x4": 20,
        "y1": y,
        "y2": y,
        "y3": y + 30,
        "y4": y + 30,
    }


class ScoringTests(unittest.TestCase):
    def test_orders_ocr_and_detects_social_movie_screenshot(self) -> None:
        rows = [
            ocr_row("Movie: The Fall Guy (2024)", 1500),
            ocr_row("YouTube Shorts", 50),
        ]
        asset = {
            "originalFileName": "Screenshot_20240810.png",
            "width": 1080,
            "height": 2400,
        }
        self.assertEqual(ocr_text(rows).splitlines()[0], "YouTube Shorts")
        detection = detect_candidate(asset, rows)
        self.assertEqual(detection.score, 1.0)
        self.assertIn("filename identifies a screenshot", detection.reasons)
        self.assertIn(
            "OCR resembles lower-third dialogue or a short caption", detection.reasons
        )

    def test_smart_search_source_is_a_review_candidate(self) -> None:
        detection = detect_candidate(
            {"originalFileName": "IMG_1234.jpg", "width": 1920, "height": 1080},
            [],
            {"smart:2"},
        )
        self.assertGreaterEqual(detection.score, 0.5)

    def test_extracts_labeled_title_hashtag_and_year(self) -> None:
        text = "Movie name: The Nice Guys\n#TheNiceGuys\n2016\nLike Share"
        phrases = extract_title_phrases(text)
        self.assertIn("The Nice Guys", phrases)
        self.assertEqual(extract_year(text), 2016)

    def test_exact_seerr_match_beats_conflicting_year(self) -> None:
        results = [
            {
                "id": 1,
                "mediaType": "movie",
                "title": "The Nice Guys",
                "releaseDate": "2016-05-20",
            },
            {
                "id": 2,
                "mediaType": "movie",
                "title": "The Nice Guys",
                "releaseDate": "2025-01-01",
            },
        ]
        ranked = rank_seerr_results("The Nice Guys", results, hinted_year=2016)
        self.assertEqual(ranked[0].media_id, 1)
        self.assertGreater(ranked[0].score, ranked[1].score)


if __name__ == "__main__":
    unittest.main()
