from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from immich_media_inbox.analysis import AnalysisResult, Evidence  # noqa: E402
from immich_media_inbox.scoring import Detection, RankedMatch  # noqa: E402
from immich_media_inbox.store import Store  # noqa: E402

ASSET_ID = "12345678-1234-1234-1234-123456789abc"


def completed_analysis() -> AnalysisResult:
    return AnalysisResult(
        decision="identified",
        media_type="movie",
        title="The Nice Guys",
        year=2016,
        alternate_titles=(),
        certainty="high",
        evidence=(Evidence("comment", "The Nice Guys is the movie"),),
        summary="The comment identifies the movie.",
        needs_cloud=False,
        uncertainty_reasons=(),
    )


def not_media_analysis() -> AnalysisResult:
    return AnalysisResult(
        decision="not_media",
        media_type="unknown",
        title=None,
        year=None,
        alternate_titles=(),
        certainty="high",
        evidence=(
            Evidence("scene", "Only a generic application interface is visible"),
        ),
        summary="The candidate contains no movie or television reference.",
        needs_cloud=False,
        uncertainty_reasons=(),
    )


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

    def complete_asset(self, asset_id: str = ASSET_ID) -> None:
        self.store.enqueue_local_analysis(asset_id)
        self.store.record_analysis(asset_id, completed_analysis(), provider="local")

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
        self.complete_asset()
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
        self.assertFalse(self.store.asset_needs_ocr(ASSET_ID, self.asset["updatedAt"]))
        self.store.prepare_analysis_queue(0.4)
        self.assertEqual(
            self.store.candidate(ASSET_ID)["analysis_state"], "local_pending"
        )
        self.assertFalse(self.store.ensure_pipeline_version(2))

        self.store.record_local_analysis_error(
            ASSET_ID,
            "fixed transport contract",
            maximum_attempts=1,
            escalate=False,
        )
        self.assertEqual(self.store.candidate(ASSET_ID)["analysis_state"], "error")
        self.assertTrue(self.store.ensure_pipeline_version(3))
        self.store.prepare_analysis_queue(0.4)
        retried = self.store.candidate(ASSET_ID)
        self.assertEqual(retried["analysis_state"], "local_pending")
        self.assertEqual(retried["analysis_attempts"], 0)
        self.assertIsNone(retried["analysis_error"])

        self.store.upsert_asset(
            self.asset,
            [],
            Detection(0.8, ("test candidate",)),
            {"metadata-crawl"},
            ocr_text="Movie: The Nice Guys",
        )
        self.store.record_error(ASSET_ID, "safe upstream error")
        self.assertTrue(self.store.asset_needs_ocr(ASSET_ID, self.asset["updatedAt"]))

    def test_pipeline_migration_batches_ocr_heavy_asset_updates(self) -> None:
        large_ocr = "x" * 131072
        with self.store.connect() as connection:
            connection.executemany(
                """
                INSERT INTO assets(
                    asset_id, updated_at, visibility, ocr_text,
                    detection_score, scanned_at
                ) VALUES (?, ?, 'timeline', ?, 0.8, ?)
                """,
                [
                    (
                        f"12345678-1234-1234-1234-{index:012d}",
                        "2026-01-02T03:05:00Z",
                        large_ocr,
                        "2026-01-02T03:06:00Z",
                    )
                    for index in range(205)
                ],
            )
        self.store.set_meta("pipeline_version", "3")

        statements: list[str] = []
        original_connect = self.store.connect

        @contextmanager
        def traced_connect():
            with original_connect() as connection:
                connection.set_trace_callback(statements.append)
                yield connection

        with mock.patch.object(self.store, "connect", traced_connect):
            self.assertTrue(self.store.ensure_pipeline_version(4))

        reset_updates = [
            statement
            for statement in statements
            if statement.lstrip().upper().startswith("UPDATE ASSETS")
        ]
        self.assertEqual(len(reset_updates), 3)

        statements.clear()
        with mock.patch.object(self.store, "connect", traced_connect):
            self.store.prepare_analysis_queue(0.4)
        queue_updates = [
            statement
            for statement in statements
            if statement.lstrip().upper().startswith("UPDATE ASSETS")
        ]
        self.assertEqual(len(queue_updates), 3)
        self.assertEqual(self.store.stats(0.4)["local_pending"], 205)

    def test_pipeline_bump_resets_only_automatic_not_media_dispositions(
        self,
    ) -> None:
        self.insert_asset()
        self.store.enqueue_local_analysis(ASSET_ID)
        self.store.record_analysis(ASSET_ID, not_media_analysis(), provider="local")
        self.assertEqual(self.store.candidate(ASSET_ID)["review_status"], "not_media")

        self.assertTrue(self.store.ensure_pipeline_version(1))
        self.assertEqual(self.store.candidate(ASSET_ID)["review_status"], "pending")

        self.store.prepare_analysis_queue(0.4)
        self.store.record_analysis(ASSET_ID, not_media_analysis(), provider="local")
        self.store.set_status(ASSET_ID, "not_media", {"actor": "manual-review"})
        self.assertTrue(self.store.ensure_pipeline_version(2))
        self.assertEqual(self.store.candidate(ASSET_ID)["review_status"], "not_media")

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
            self.complete_asset(asset["id"])

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
