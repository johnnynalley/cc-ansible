#!/usr/bin/env python3
"""Regression tests for the collection-only FreshRSS Daily Summary input."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/agents/hermes-freshrss-briefing.py"
SPEC = importlib.util.spec_from_file_location("hermes_freshrss_collect", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def raw_item(
    identifier: str,
    title: str,
    *,
    published: datetime | None = None,
    summary: str = "",
) -> dict[str, object]:
    timestamp = (published or datetime.now(timezone.utc)).timestamp()
    return {
        "id": identifier,
        "title": title,
        "published": timestamp,
        "origin": {"title": "Example Feed"},
        "alternate": [{"href": f"https://example.test/{identifier}"}],
        "summary": {"content": summary},
    }


class FreshRssCollectTests(unittest.TestCase):
    def test_selection_preserves_legacy_categories_and_limits(self):
        normalized = MODULE._normalize(
            [
                raw_item("one", "OpenClaw release"),
                raw_item("two", "Hermes agent release"),
                raw_item("three", "Another LLM release"),
                raw_item("four", "Linux kernel update"),
                raw_item(
                    "old",
                    "Docker release",
                    published=datetime.now(timezone.utc) - timedelta(days=3),
                ),
            ]
        )
        selected = MODULE._select(normalized)
        self.assertEqual([item["id"] for item in selected], ["one", "two", "four"])
        self.assertEqual(selected[0]["category"], "OpenClaw / AI")

    def test_collection_writes_canonical_inputs_without_delivery_state(self):
        feed = {
            "items": [
                raw_item(
                    "linux",
                    "Linux security release",
                    summary="<p>Fixes a kernel CVE.</p>",
                )
            ]
        }
        responses = [b"SID=x\nAuth=test-token\n", json.dumps(feed).encode("utf-8")]
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            credential = base / "credential.json"
            root = base / "freshrss"
            section = base / "sections/rss.md"
            credential.write_text(
                json.dumps(
                    {
                        "endpoint": "https://rss.example.test",
                        "username": "astra",
                        "password": "secret",
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(MODULE, "_request", side_effect=responses):
                result = MODULE.collect(credential, root, section)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["candidateCount"], 1)
            self.assertIn("## RSS Candidates", section.read_text(encoding="utf-8"))
            self.assertIn(
                "Linux security release",
                (root / "latest-briefing.md").read_text(encoding="utf-8"),
            )
            payload = json.loads(
                (root / "latest-briefing.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["count"], 1)
            state = json.loads((root / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(set(state), {"lastRun", "matched", "candidateCount"})

    def test_invalid_credential_schema_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            credential = base / "credential.json"
            credential.write_text('{"endpoint":"https://rss.example.test"}')
            with self.assertRaisesRegex(MODULE.BriefingError, "credential-schema"):
                MODULE.collect(credential, base / "root", base / "rss.md")


if __name__ == "__main__":
    unittest.main()
