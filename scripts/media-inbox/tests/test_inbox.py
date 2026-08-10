from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from immich_media_inbox.config import Config  # noqa: E402
from immich_media_inbox.cli import decode_query  # noqa: E402
from immich_media_inbox.inbox import Inbox  # noqa: E402
from immich_media_inbox.scoring import Detection, RankedMatch  # noqa: E402
from immich_media_inbox.store import Store  # noqa: E402

ASSET_ID = "12345678-1234-1234-1234-123456789abc"


class FakeScanner:
    def manual_match(self, asset_id: str, query: str) -> list[object]:
        del asset_id, query
        return []


class FakeImmich:
    def __init__(self) -> None:
        self.visibility = "timeline"

    def get_asset(self, asset_id: str) -> dict[str, str]:
        del asset_id
        return {"visibility": self.visibility}


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
            auto_match_threshold=0.55,
            smart_search_size=10,
            smart_search_interval_hours=24,
            requests_enabled=False,
            allowed_visibilities=("timeline", "archive"),
        )
        self.store = Store(self.config.database_path)
        self.store.upsert_asset(
            {
                "id": ASSET_ID,
                "originalFileName": "Screenshot-private-text.png",
                "width": 1080,
                "height": 2400,
                "fileCreatedAt": "2026-01-02T03:04:05Z",
                "updatedAt": "2026-01-02T03:05:00Z",
                "visibility": "timeline",
            },
            [],
            Detection(0.8, ("test candidate",)),
            {"metadata-crawl"},
            ocr_text="Movie: The Nice Guys\nraw private screenshot text",
        )
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
                        "overview": "untrusted external description",
                    },
                    source_query="raw OCR query",
                )
            ],
        )
        self.immich = FakeImmich()
        self.seerr = FakeSeerr()

    def inbox(self, config: Config | None = None) -> Inbox:
        return Inbox(
            config or self.config,
            self.store,
            FakeScanner(),
            self.immich,
            self.seerr,
        )

    def test_result_only_output_omits_images_raw_ocr_filenames_and_secrets(
        self,
    ) -> None:
        payload = self.inbox().list_candidates(status="pending", limit=10)
        encoded = json.dumps(payload)
        self.assertIn("The Nice Guys", encoded)
        self.assertIn("year_missing", encoded)
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

    def test_yearless_candidate_requires_explicit_ambiguous_confirmation(self) -> None:
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
        self.assertEqual(self.store.candidate(ASSET_ID)["review_status"], "requested")

    def test_existing_processing_media_blocks_duplicate_request(self) -> None:
        enabled = replace(self.config, requests_enabled=True)
        self.seerr.media_info = {"status": 3, "requests": []}
        payload = self.inbox(enabled).request(
            ASSET_ID,
            "movie",
            290250,
            seasons=[],
            confirmed=True,
            confirm_ambiguous=True,
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
        self.assertEqual(payload["expected_pipeline_version"], 2)


if __name__ == "__main__":
    unittest.main()
