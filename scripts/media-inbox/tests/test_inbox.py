from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from immich_media_inbox.analysis import AnalysisResult, Evidence  # noqa: E402
from immich_media_inbox.cli import decode_query  # noqa: E402
from immich_media_inbox.config import Config  # noqa: E402
from immich_media_inbox.inbox import Inbox  # noqa: E402
from immich_media_inbox.scoring import Detection, RankedMatch  # noqa: E402
from immich_media_inbox.store import Store  # noqa: E402

ASSET_ID = "12345678-1234-1234-1234-123456789abc"


def result(
    *,
    decision: str = "identified",
    certainty: str = "high",
    needs_cloud: bool = False,
) -> AnalysisResult:
    return AnalysisResult(
        decision=decision,
        media_type="movie" if decision != "not_media" else "unknown",
        title="The Nice Guys" if decision != "not_media" else None,
        year=None,
        alternate_titles=(),
        certainty=certainty,
        evidence=(Evidence("comment", "The Nice Guys is the movie"),),
        summary="A comment identifies the referenced movie.",
        needs_cloud=needs_cloud,
        uncertainty_reasons=(
            ("exact version unresolved",) if decision == "ambiguous" else ()
        ),
    )


class FakeScanner:
    def manual_match(self, asset_id: str, query: str) -> list[object]:
        del asset_id, query
        return []

    def canonical_matches(self, analysis: AnalysisResult) -> list[RankedMatch]:
        if not analysis.title:
            return []
        return [
            RankedMatch(
                "movie",
                290250,
                analysis.title,
                2016,
                0.85,
                ("exact_title", "media_type_match"),
                {"id": 290250, "mediaType": "movie", "title": analysis.title},
                analysis.title,
            )
        ]


class FakeImmich:
    def __init__(self) -> None:
        self.visibility = "timeline"

    def get_asset(self, asset_id: str) -> dict[str, str]:
        del asset_id
        return {"visibility": self.visibility}

    def get_preview(self, asset_id: str) -> tuple[bytes, str]:
        del asset_id
        return b"candidate-image", "image/jpeg"


class FakeSeerr:
    def __init__(self) -> None:
        self.media_info: dict[str, Any] | None = None
        self.request_calls = 0

    def details(self, media_type: str, media_id: int) -> dict[str, Any]:
        del media_type, media_id
        return {"mediaInfo": self.media_info, "seasons": []}

    def request_media(
        self, media_type: str, media_id: int, *, seasons: list[int] | None = None
    ) -> dict[str, int]:
        del media_type, media_id, seasons
        self.request_calls += 1
        return {"id": 42}


class InboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.config = Config(
            immich_url="http://immich/api",
            immich_api_key="immich-secret",
            immich_web_url="https://photos.example",
            seerr_url="http://seerr/api/v1",
            seerr_api_key="seerr-secret",
            database_path=Path(self.temporary.name) / "state.sqlite3",
            scan_interval_seconds=300,
            scan_batch_size=10,
            api_request_delay_ms=0,
            candidate_threshold=0.4,
            smart_search_size=10,
            smart_search_interval_hours=24,
            ollama_url="http://ollama:11434",
            ollama_model="qwen3-vl:2b-instruct-q4_K_M",
            analysis_batch_size=5,
            local_analysis_max_attempts=2,
            cloud_analysis_max_attempts=3,
            requests_enabled=False,
            allowed_visibilities=("timeline", "archive"),
        )
        self.store = Store(self.config.database_path)
        self.asset = {
            "id": ASSET_ID,
            "originalFileName": "Screenshot-private-text.png",
            "width": 1080,
            "height": 2400,
            "fileCreatedAt": "2026-01-02T03:04:05Z",
            "updatedAt": "2026-01-02T03:05:00Z",
            "visibility": "timeline",
        }
        self.store.upsert_asset(
            self.asset,
            [],
            Detection(0.8, ("test candidate",)),
            {"metadata-crawl"},
            ocr_text="Movie: The Nice Guys\nraw private screenshot text",
        )
        self.store.enqueue_local_analysis(ASSET_ID)
        self.store.record_analysis(ASSET_ID, result(), provider="local")
        self.store.replace_matches(
            ASSET_ID,
            [
                RankedMatch(
                    media_type="movie",
                    media_id=290250,
                    title="The Nice Guys",
                    year=2016,
                    score=0.85,
                    reasons=("exact_title", "media_type_match"),
                    payload={
                        "id": 290250,
                        "mediaType": "movie",
                        "title": "The Nice Guys",
                        "overview": "untrusted external description",
                    },
                    source_query="raw OCR query",
                )
            ],
        )
        self.immich = FakeImmich()
        self.seerr = FakeSeerr()
        self.scanner = FakeScanner()

    def inbox(self, config: Config | None = None) -> Inbox:
        return Inbox(
            config or self.config,
            self.store,
            self.scanner,
            self.immich,
            self.seerr,
        )

    def make_cloud_pending(self, cloud_result: AnalysisResult) -> None:
        self.store.upsert_asset(
            {**self.asset, "updatedAt": "2026-01-02T03:06:00Z"},
            [],
            Detection(0.8, ("test candidate",)),
            {"metadata-crawl"},
            ocr_text="Movie: The Nice Guys\nraw private screenshot text",
        )
        self.store.enqueue_local_analysis(ASSET_ID)
        local = result(decision="ambiguous", certainty="medium", needs_cloud=True)
        self.store.record_analysis(ASSET_ID, local, provider="local")
        claim = self.inbox().claim_cloud()
        self.assertEqual(claim["candidate"]["candidate_id"], ASSET_ID)
        if not cloud_result.needs_cloud:
            self.inbox().submit_cloud_analysis(ASSET_ID, cloud_result.as_dict())

    def test_result_output_exposes_semantic_evidence_but_omits_source_content(
        self,
    ) -> None:
        payload = self.inbox().list_candidates(status="pending", limit=10)
        encoded = json.dumps(payload)
        self.assertIn("The Nice Guys is the movie", encoded)
        self.assertFalse(payload["candidates"][0]["manual_review_required"])
        self.assertNotIn("year_missing", encoded)
        for forbidden in (
            "raw private screenshot text",
            "Screenshot-private-text.png",
            "raw OCR query",
            "untrusted external description",
            self.config.immich_api_key,
            self.config.seerr_api_key,
            "ocr_text",
            "filename",
            "thumbnail",
            "candidate_confidence",
            '"confidence"',
        ):
            self.assertNotIn(forbidden, encoded)

    def test_search_query_requires_url_safe_base64(self) -> None:
        self.assertEqual(decode_query("VGhlIE5pY2UgR3V5cw"), "The Nice Guys")
        with self.assertRaises(ValueError):
            decode_query("The Nice Guys; cat /etc/passwd")

    def test_locked_asset_is_purged_before_result_output(self) -> None:
        self.immich.visibility = "locked"
        payload = self.inbox().list_candidates(status="pending", limit=10)
        self.assertEqual(payload["candidates"], [])
        self.assertIsNone(self.store.candidate(ASSET_ID))

    def test_cloud_claim_contains_prompt_not_raw_ocr_and_gates_image_export(
        self,
    ) -> None:
        self.store.upsert_asset(
            {**self.asset, "updatedAt": "2026-01-02T03:06:00Z"},
            [],
            Detection(0.8, ("test candidate",)),
            {"metadata-crawl"},
            ocr_text="raw private screenshot text",
        )
        self.store.enqueue_local_analysis(ASSET_ID)
        self.store.record_analysis(
            ASSET_ID,
            result(decision="ambiguous", certainty="medium", needs_cloud=True),
            provider="local",
        )
        with self.assertRaises(KeyError):
            self.inbox().export_cloud_image(ASSET_ID)
        claim = self.inbox().claim_cloud()
        encoded = json.dumps(claim)
        self.assertNotIn("raw private screenshot text", encoded)
        prompt = base64.b64decode(claim["candidate"]["prompt_base64"]).decode()
        self.assertIn("raw private screenshot text", prompt)
        self.assertIn("untrusted", prompt.lower())
        self.assertEqual(self.inbox().export_cloud_image(ASSET_ID), b"candidate-image")

    def test_cloud_result_is_terminal_and_stale_submissions_are_rejected(self) -> None:
        self.store.upsert_asset(
            {**self.asset, "updatedAt": "2026-01-02T03:06:00Z"},
            [],
            Detection(0.8, ("test candidate",)),
            {"metadata-crawl"},
            ocr_text="private OCR",
        )
        self.store.enqueue_local_analysis(ASSET_ID)
        self.store.record_analysis(
            ASSET_ID,
            result(decision="ambiguous", certainty="medium", needs_cloud=True),
            provider="local",
        )
        self.inbox().claim_cloud()
        with self.assertRaisesRegex(ValueError, "must be terminal"):
            self.inbox().submit_cloud_analysis(
                ASSET_ID,
                result(
                    decision="ambiguous", certainty="medium", needs_cloud=True
                ).as_dict(),
            )
        completed = result()
        payload = self.inbox().submit_cloud_analysis(ASSET_ID, completed.as_dict())
        self.assertEqual(payload["candidate"]["analysis"]["provider"], "gpt-5.6-sol")
        with self.assertRaises(KeyError):
            self.inbox().submit_cloud_analysis(ASSET_ID, completed.as_dict())

    def test_cloud_failures_stop_requeueing_at_the_configured_limit(self) -> None:
        self.store.upsert_asset(
            {**self.asset, "updatedAt": "2026-01-02T03:06:00Z"},
            [],
            Detection(0.8, ("test candidate",)),
            {"metadata-crawl"},
            ocr_text="private OCR",
        )
        self.store.enqueue_local_analysis(ASSET_ID)
        self.store.record_analysis(
            ASSET_ID,
            result(decision="ambiguous", certainty="medium", needs_cloud=True),
            provider="local",
        )
        for attempt in range(3):
            self.inbox().claim_cloud()
            outcome = self.inbox().fail_cloud(ASSET_ID, "invalid_output")
            expected = "error" if attempt == 2 else "cloud_pending"
            self.assertEqual(outcome["analysis_state"], expected)
        self.assertIsNone(self.inbox().claim_cloud()["candidate"])

    def test_semantic_ambiguity_requires_explicit_request_confirmation(self) -> None:
        ambiguous = result(decision="ambiguous", certainty="medium", needs_cloud=False)
        self.make_cloud_pending(ambiguous)
        enabled = replace(self.config, requests_enabled=True)
        inbox = self.inbox(enabled)
        with self.assertRaisesRegex(ValueError, "manual review is required"):
            inbox.request(
                ASSET_ID,
                "movie",
                290250,
                seasons=[],
                confirmed=True,
                confirm_ambiguous=False,
            )
        payload = inbox.request(
            ASSET_ID,
            "movie",
            290250,
            seasons=[],
            confirmed=True,
            confirm_ambiguous=True,
        )
        self.assertTrue(payload["request"]["created"])

    def test_existing_processing_media_blocks_duplicate_request(self) -> None:
        enabled = replace(self.config, requests_enabled=True)
        self.seerr.media_info = {"status": 3, "requests": []}
        payload = self.inbox(enabled).request(
            ASSET_ID,
            "movie",
            290250,
            seasons=[],
            confirmed=True,
            confirm_ambiguous=False,
        )
        self.assertFalse(payload["request"]["created"])
        self.assertEqual(payload["request"]["state"], "processing")
        self.assertEqual(self.seerr.request_calls, 0)

    def test_starting_state_cannot_reuse_stale_completion_health(self) -> None:
        self.store.set_meta("scan_completed_at", "2026-08-10T01:00:00+00:00")
        self.store.set_meta("scan_state", "starting")
        payload = self.inbox().status()
        self.assertFalse(payload["healthy"])
        self.assertEqual(payload["pipeline_version"], 0)
        self.assertEqual(payload["expected_pipeline_version"], 4)


if __name__ == "__main__":
    unittest.main()
