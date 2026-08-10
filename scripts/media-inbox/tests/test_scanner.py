from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from immich_media_inbox.analysis import (  # noqa: E402
    AnalysisResult,
    Evidence,
)
from immich_media_inbox.clients import (  # noqa: E402
    AnalysisResponseError,
    ApiError,
)
from immich_media_inbox.config import Config  # noqa: E402
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


def config_for(path: Path, *, attempts: int = 2) -> Config:
    return Config(
        immich_url="http://immich/api",
        immich_api_key="test",
        immich_web_url="https://photos.example",
        seerr_url="http://seerr/api/v1",
        seerr_api_key="test",
        database_path=path,
        scan_interval_seconds=300,
        scan_batch_size=10,
        api_request_delay_ms=0,
        candidate_threshold=0.4,
        smart_search_size=10,
        smart_search_interval_hours=24,
        ollama_url="http://ollama:11434",
        ollama_model="qwen3-vl:2b-instruct-q4_K_M",
        analysis_batch_size=10,
        local_analysis_max_attempts=attempts,
        cloud_analysis_max_attempts=3,
        requests_enabled=False,
        allowed_visibilities=("timeline", "archive"),
    )


def analysis(
    title: str | None,
    *,
    media_type: str = "movie",
    year: int | None = None,
    decision: str = "identified",
    certainty: str = "high",
    needs_cloud: bool = False,
) -> AnalysisResult:
    return AnalysisResult(
        decision=decision,
        media_type=media_type,
        title=title,
        year=year,
        alternate_titles=(),
        certainty=certainty,
        evidence=(Evidence("comment", f"{title or 'No title'} evidence"),),
        summary="Semantic screenshot analysis fixture.",
        needs_cloud=needs_cloud,
        uncertainty_reasons=(
            ("exact work unresolved",) if decision == "ambiguous" else ()
        ),
    )


class FakeImmich:
    def __init__(self, ocr_lines: list[str] | None = None) -> None:
        self.orders: list[str] = []
        self.ocr_lines = ocr_lines or ["Movie: The Nice Guys (2016)"]

    def server_features(self) -> dict[str, bool]:
        return {"ocr": True, "search": True, "smartSearch": True}

    def smart_search(
        self, query: str, *, visibility: str, size: int
    ) -> list[dict[str, Any]]:
        del query, size
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
        del size, updated_after
        self.orders.append(order)
        items = [dict(ASSET)] if visibility == "timeline" and page == 1 else []
        return {"assets": {"items": items, "nextPage": None}}

    def get_ocr(self, asset_id: str) -> list[dict[str, Any]]:
        del asset_id
        return [
            {
                "text": line,
                "textScore": 0.99,
                "isVisible": True,
                "x1": 0,
                "x2": 100,
                "x3": 100,
                "x4": 0,
                "y1": 1500 + index * 30,
                "y2": 1500 + index * 30,
                "y3": 1530 + index * 30,
                "y4": 1530 + index * 30,
            }
            for index, line in enumerate(self.ocr_lines)
        ]

    def get_asset(self, asset_id: str) -> dict[str, str]:
        del asset_id
        return {"visibility": "timeline"}

    def get_preview(self, asset_id: str) -> tuple[bytes, str]:
        del asset_id
        return b"synthetic-image", "image/jpeg"


class FakeOllama:
    def __init__(self, result: AnalysisResult | Exception) -> None:
        self.result = result
        self.calls: list[tuple[bytes, str]] = []

    def analyze(self, image: bytes, ocr: str) -> AnalysisResult:
        self.calls.append((image, ocr))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FailingPreviewImmich(FakeImmich):
    def get_preview(self, asset_id: str) -> tuple[bytes, str]:
        del asset_id
        raise ApiError("Immich preview unavailable")


class FakeSeerr:
    def __init__(self, results: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.results = results or {
            "The Nice Guys": [
                {
                    "id": 290250,
                    "mediaType": "movie",
                    "title": "The Nice Guys",
                    "releaseDate": "2016-05-20",
                }
            ]
        }
        self.queries: list[str] = []

    def search(self, query: str) -> list[dict[str, Any]]:
        self.queries.append(query)
        return self.results.get(query, [])


class ScannerTests(unittest.TestCase):
    def scanner(
        self,
        temporary: str,
        result: AnalysisResult | Exception,
        *,
        immich: FakeImmich | None = None,
        seerr: FakeSeerr | None = None,
        attempts: int = 2,
    ) -> tuple[Scanner, Store, FakeImmich, FakeSeerr, FakeOllama]:
        config = config_for(Path(temporary) / "state.sqlite3", attempts=attempts)
        store = Store(config.database_path)
        immich = immich or FakeImmich()
        seerr = seerr or FakeSeerr()
        ollama = FakeOllama(result)
        return (
            Scanner(config, store, immich, seerr, ollama),
            store,
            immich,
            seerr,
            ollama,
        )

    def test_cycle_uses_local_vision_and_canonicalizes_only_model_title(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scanner, store, immich, seerr, ollama = self.scanner(
                temporary,
                analysis("The Nice Guys", year=2016),
            )
            report = scanner.run_cycle()
            self.assertTrue(report["started"])
            self.assertIn("desc", immich.orders)
            self.assertIn("asc", immich.orders)
            self.assertEqual(seerr.queries, ["The Nice Guys"])
            self.assertIn("Movie: The Nice Guys", ollama.calls[0][1])
            candidate = store.candidate(ASSET["id"])
            self.assertEqual(candidate["analysis_state"], "complete")
            self.assertEqual(candidate["matches"][0]["title"], "The Nice Guys")

            scanner._process_asset(
                {**ASSET, "visibility": "locked"}, source="unexpected-result"
            )
            self.assertIsNone(store.candidate(ASSET["id"]))

    def test_brightburn_comment_after_noisy_ui_drives_the_only_search(self) -> None:
        noisy = [
            "YouTube Shorts",
            "Give",
            "Reply",
            "Promoted",
            "Refresh",
            "Plex",
            '"BRIGHTBURN" IS THE MOVIE',
        ]
        seerr = FakeSeerr(
            {
                "Brightburn": [
                    {
                        "id": 531309,
                        "mediaType": "movie",
                        "title": "Brightburn",
                        "releaseDate": "2019-05-24",
                    }
                ]
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            scanner, store, _immich, seerr, _ollama = self.scanner(
                temporary,
                analysis("Brightburn", year=2019),
                immich=FakeImmich(noisy),
                seerr=seerr,
            )
            scanner._process_asset(dict(ASSET), source="metadata-crawl")
            scanner._analyze_batch()
            self.assertEqual(seerr.queries, ["Brightburn"])
            self.assertEqual(
                store.candidate(ASSET["id"])["matches"][0]["title"], "Brightburn"
            )

    def test_brothers_movie_context_filters_same_named_tv_series(self) -> None:
        seerr = FakeSeerr(
            {
                "Brothers": [
                    {
                        "id": 7445,
                        "mediaType": "movie",
                        "title": "Brothers",
                        "releaseDate": "2009-12-02",
                    },
                    {
                        "id": 61389,
                        "mediaType": "tv",
                        "name": "Brothers",
                        "firstAirDate": "2009-09-25",
                    },
                ]
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            scanner, store, _immich, _seerr, _ollama = self.scanner(
                temporary,
                analysis("Brothers", year=2009, media_type="movie"),
                seerr=seerr,
            )
            scanner._process_asset(dict(ASSET), source="metadata-crawl")
            scanner._analyze_batch()
            matches = store.candidate(ASSET["id"])["matches"]
            self.assertEqual(
                [(item["media_type"], item["title"]) for item in matches],
                [("movie", "Brothers")],
            )

    def test_uncertain_local_result_automatically_enters_cloud_queue(self) -> None:
        uncertain = analysis(
            None,
            media_type="unknown",
            decision="ambiguous",
            certainty="medium",
            needs_cloud=True,
        )
        with tempfile.TemporaryDirectory() as temporary:
            scanner, store, _immich, seerr, _ollama = self.scanner(temporary, uncertain)
            scanner._process_asset(dict(ASSET), source="metadata-crawl")
            report = scanner._analyze_batch()
            self.assertEqual(report["escalated"], 1)
            self.assertEqual(
                store.candidate(ASSET["id"])["analysis_state"], "cloud_pending"
            )
            self.assertEqual(store.queue(status="pending", threshold=0.4), [])
            self.assertEqual(seerr.queries, [])

    def test_invalid_output_and_exhausted_model_transport_escalate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scanner, store, _immich, _seerr, _ollama = self.scanner(
                temporary,
                AnalysisResponseError("invalid structured output"),
            )
            scanner._process_asset(dict(ASSET), source="metadata-crawl")
            scanner._analyze_batch()
            self.assertEqual(
                store.candidate(ASSET["id"])["analysis_state"], "cloud_pending"
            )

        with tempfile.TemporaryDirectory() as temporary:
            scanner, store, _immich, _seerr, _ollama = self.scanner(
                temporary,
                ApiError("Ollama unavailable"),
                attempts=2,
            )
            scanner._process_asset(dict(ASSET), source="metadata-crawl")
            scanner._analyze_batch()
            self.assertEqual(
                store.candidate(ASSET["id"])["analysis_state"], "local_pending"
            )
            report = scanner._analyze_batch()
            self.assertEqual(
                store.candidate(ASSET["id"])["analysis_state"], "cloud_pending"
            )
            self.assertEqual(report["escalated"], 1)

    def test_immich_source_failure_does_not_escalate_to_cloud(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scanner, store, _immich, _seerr, _ollama = self.scanner(
                temporary,
                analysis("Unused"),
                immich=FailingPreviewImmich(),
                attempts=2,
            )
            scanner._process_asset(dict(ASSET), source="metadata-crawl")
            scanner._analyze_batch()
            self.assertEqual(
                store.candidate(ASSET["id"])["analysis_state"], "local_pending"
            )
            scanner._analyze_batch()
            self.assertEqual(store.candidate(ASSET["id"])["analysis_state"], "error")


if __name__ == "__main__":
    unittest.main()
