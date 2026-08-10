from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from immich_media_inbox.config import Config  # noqa: E402
from immich_media_inbox.clients import ApiError  # noqa: E402
from immich_media_inbox.scanner import Scanner  # noqa: E402
from immich_media_inbox.store import Store  # noqa: E402

ASSET = {
    "id": "12345678-1234-1234-1234-123456789abc",
    "originalFileName": "Screenshot_1.png",
    "width": 1080,
    "height": 2400,
    "fileCreatedAt": "2026-01-02T03:04:05Z",
    "updatedAt": "2026-01-02T03:05:00Z",
    "visibility": "timeline",
}


class FakeImmich:
    def __init__(self) -> None:
        self.orders: list[str] = []

    def server_features(self) -> dict[str, bool]:
        return {"ocr": True, "search": True, "smartSearch": True}

    def smart_search(
        self, query: str, *, visibility: str, size: int
    ) -> list[dict[str, Any]]:
        return [dict(ASSET)] if visibility == "timeline" else []

    def search_assets(
        self,
        *,
        visibility: str,
        page: int,
        size: int,
        order: str = "asc",
        updated_after: str | None = None,
    ) -> dict[str, Any]:
        del updated_after
        self.orders.append(order)
        items = [dict(ASSET)] if visibility == "timeline" and page == 1 else []
        return {"assets": {"items": items, "nextPage": None}}

    def get_ocr(self, asset_id: str) -> list[dict[str, Any]]:
        return [
            {
                "text": "Movie: The Nice Guys (2016)",
                "textScore": 0.99,
                "isVisible": True,
                "x1": 0,
                "x2": 100,
                "x3": 100,
                "x4": 0,
                "y1": 1500,
                "y2": 1500,
                "y3": 1530,
                "y4": 1530,
            }
        ]


class FakeSeerr:
    def search(self, query: str) -> list[dict[str, Any]]:
        return [
            {
                "id": 290250,
                "mediaType": "movie",
                "title": "The Nice Guys",
                "releaseDate": "2016-05-20",
            }
        ]


class FailingSecondSearchSeerr(FakeSeerr):
    def __init__(self) -> None:
        self.calls = 0

    def search(self, query: str) -> list[dict[str, Any]]:
        self.calls += 1
        if self.calls > 1:
            raise ApiError("GET /search failed with HTTP 400")
        return super().search(query)


class ScannerTests(unittest.TestCase):
    def test_cycle_seeds_recent_and_historical_paths_without_requesting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Config(
                immich_url="http://immich/api",
                immich_api_key="test",
                immich_web_url="https://photos.example",
                seerr_url="http://seerr/api/v1",
                seerr_api_key="test",
                database_path=Path(temporary) / "state.sqlite3",
                scan_interval_seconds=300,
                scan_batch_size=10,
                api_request_delay_ms=0,
                candidate_threshold=0.4,
                auto_match_threshold=0.55,
                smart_search_size=10,
                smart_search_interval_hours=24,
                requests_enabled=False,
                allowed_visibilities=("timeline", "archive"),
            )
            store = Store(config.database_path)
            immich = FakeImmich()
            scanner = Scanner(config, store, immich, FakeSeerr())
            report = scanner.run_cycle()
            self.assertTrue(report["started"])
            self.assertIn("desc", immich.orders)
            self.assertIn("asc", immich.orders)
            candidate = store.candidate(ASSET["id"])
            self.assertIsNotNone(candidate)
            self.assertEqual(candidate["review_status"], "pending")
            self.assertEqual(candidate["matches"][0]["title"], "The Nice Guys")

            scanner._process_asset(
                {**ASSET, "visibility": "locked"}, source="unexpected-result"
            )
            self.assertIsNone(store.candidate(ASSET["id"]))

    def test_failed_match_is_not_published_and_is_eligible_for_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Config(
                immich_url="http://immich/api",
                immich_api_key="test",
                immich_web_url="https://photos.example",
                seerr_url="http://seerr/api/v1",
                seerr_api_key="test",
                database_path=Path(temporary) / "state.sqlite3",
                scan_interval_seconds=300,
                scan_batch_size=10,
                api_request_delay_ms=0,
                candidate_threshold=0.4,
                auto_match_threshold=0.55,
                smart_search_size=10,
                smart_search_interval_hours=24,
                requests_enabled=False,
                allowed_visibilities=("timeline", "archive"),
            )
            store = Store(config.database_path)
            immich = FakeImmich()
            original_get_ocr = immich.get_ocr
            immich.get_ocr = lambda asset_id: original_get_ocr(asset_id) + [
                {
                    "text": "Another plausible title",
                    "textScore": 0.99,
                    "isVisible": True,
                    "x1": 0,
                    "x2": 100,
                    "x3": 100,
                    "x4": 0,
                    "y1": 1600,
                    "y2": 1600,
                    "y3": 1630,
                    "y4": 1630,
                }
            ]
            scanner = Scanner(config, store, immich, FailingSecondSearchSeerr())
            scanner._process_asset(dict(ASSET), source="metadata-crawl")

            candidate = store.candidate(ASSET["id"])
            self.assertEqual(candidate["matches"], [])
            self.assertIsNotNone(candidate["last_error"])
            self.assertTrue(store.asset_needs_ocr(ASSET["id"], ASSET["updatedAt"]))


if __name__ == "__main__":
    unittest.main()
