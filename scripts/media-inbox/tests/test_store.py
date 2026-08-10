from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from immich_media_inbox.scoring import Detection, RankedMatch  # noqa: E402
from immich_media_inbox.store import Store  # noqa: E402

ASSET_ID = "12345678-1234-1234-1234-123456789abc"


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(Path(self.temporary.name) / "state.sqlite3")
        self.asset = {
            "id": ASSET_ID,
            "originalFileName": "Screenshot.png",
            "width": 1080,
            "height": 2400,
            "fileCreatedAt": "2026-01-02T03:04:05Z",
            "updatedAt": "2026-01-02T03:05:00Z",
            "visibility": "timeline",
            "checksum": "checksum",
        }

    def insert_asset(self) -> None:
        self.store.upsert_asset(
            self.asset,
            [],
            Detection(0.8, ("test candidate",)),
            {"metadata-crawl"},
            ocr_text="Movie: The Nice Guys",
        )

    def test_asset_queue_match_and_disposition(self) -> None:
        self.insert_asset()
        self.store.replace_matches(
            ASSET_ID,
            [
                RankedMatch(
                    media_type="movie",
                    media_id=290250,
                    title="The Nice Guys",
                    year=2016,
                    score=0.94,
                    reasons=("exact normalized title match",),
                    payload={
                        "id": 290250,
                        "mediaType": "movie",
                        "title": "The Nice Guys",
                    },
                    source_query="The Nice Guys",
                )
            ],
        )
        queued = self.store.queue(status="pending", threshold=0.4)
        self.assertEqual(queued[0]["match_count"], 1)
        self.store.set_status(ASSET_ID, "ignored")
        self.assertEqual(self.store.candidate(ASSET_ID)["review_status"], "ignored")

    def test_empty_replacement_removes_stale_matches(self) -> None:
        self.insert_asset()
        self.store.replace_matches(
            ASSET_ID,
            [
                RankedMatch(
                    "movie",
                    1,
                    "Example",
                    2020,
                    0.8,
                    ("test",),
                    {"id": 1, "mediaType": "movie"},
                    "Example",
                )
            ],
        )
        self.store.replace_matches(ASSET_ID, [])
        self.assertEqual(self.store.candidate(ASSET_ID)["matches"], [])

    def test_pipeline_bump_invalidates_matches_and_retries_errors(self) -> None:
        self.insert_asset()
        self.store.replace_matches(
            ASSET_ID,
            [
                RankedMatch(
                    "movie",
                    1,
                    "Stale Example",
                    2020,
                    0.8,
                    ("test",),
                    {"id": 1, "mediaType": "movie"},
                    "Stale Example",
                )
            ],
        )
        self.assertTrue(self.store.ensure_pipeline_version(2))
        self.assertEqual(self.store.candidate(ASSET_ID)["matches"], [])
        self.assertTrue(self.store.asset_needs_ocr(ASSET_ID, self.asset["updatedAt"]))
        self.assertFalse(self.store.ensure_pipeline_version(2))

        self.store.upsert_asset(
            self.asset,
            [],
            Detection(0.8, ("test candidate",)),
            {"metadata-crawl"},
            ocr_text="Movie: The Nice Guys",
        )
        self.store.record_error(ASSET_ID, "safe upstream error")
        self.assertTrue(self.store.asset_needs_ocr(ASSET_ID, self.asset["updatedAt"]))

    def test_queue_orders_large_ocr_rows_without_grouping_them_for_sort(self) -> None:
        large_ocr = "dialogue " * 131072
        for index in range(24):
            asset = {
                **self.asset,
                "id": f"12345678-1234-1234-1234-{index:012d}",
                "fileCreatedAt": f"2026-01-02T03:{index:02d}:05Z",
                "updatedAt": f"2026-01-02T04:{index:02d}:05Z",
            }
            self.store.upsert_asset(
                asset,
                [{"text": large_ocr, "isVisible": True}],
                Detection(index / 24, ("large OCR fixture",)),
                {"metadata-crawl"},
                ocr_text=large_ocr,
            )

        queued = self.store.queue(status="pending", threshold=0.0, limit=5)

        self.assertEqual(len(queued), 5)
        self.assertEqual(
            [row["asset_id"] for row in queued],
            [
                "12345678-1234-1234-1234-000000000023",
                "12345678-1234-1234-1234-000000000022",
                "12345678-1234-1234-1234-000000000021",
                "12345678-1234-1234-1234-000000000020",
                "12345678-1234-1234-1234-000000000019",
            ],
        )
        self.assertTrue(all(row["match_count"] == 0 for row in queued))


if __name__ == "__main__":
    unittest.main()
