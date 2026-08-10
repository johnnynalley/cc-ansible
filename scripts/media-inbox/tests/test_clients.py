from __future__ import annotations

import sys
import unittest
import urllib.parse
import json
from base64 import b64encode
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from immich_media_inbox.clients import (  # noqa: E402
    ImmichClient,
    OllamaClient,
    SeerrClient,
)


class ClientTests(unittest.TestCase):
    def test_seerr_search_uses_regioned_tmdb_locale(self) -> None:
        client = SeerrClient("http://seerr/api/v1", "test-key")
        with patch.object(
            client.http, "request", return_value={"results": []}
        ) as request:
            client.search("The Nice Guys")
        path = request.call_args.args[1]
        self.assertIn("query=The%20Nice%20Guys", path)
        self.assertNotIn("+", path)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
        self.assertEqual(query["language"], ["en-US"])
        self.assertEqual(query["query"], ["The Nice Guys"])

    def test_immich_preview_uses_scoped_stable_thumbnail_endpoint(self) -> None:
        client = ImmichClient("http://immich/api", "test-key")
        with patch.object(
            client.http,
            "request_bytes",
            return_value=(b"image", "image/jpeg"),
        ) as request:
            self.assertEqual(client.get_preview("asset-id"), (b"image", "image/jpeg"))
        self.assertEqual(
            request.call_args.args, ("GET", "/assets/asset-id/thumbnail?size=preview")
        )
        self.assertEqual(request.call_args.kwargs["maximum_bytes"], 8 * 1024 * 1024)

    def test_ollama_analysis_is_structured_cpu_worker_input_and_unloads_model(
        self,
    ) -> None:
        client = OllamaClient("http://ollama:11434", "qwen3-vl:2b-instruct-q4_K_M")
        response = {
            "decision": "identified",
            "media_type": "movie",
            "title": "Brightburn",
            "year": 2019,
            "alternate_titles": [],
            "certainty": "high",
            "evidence": [{"source": "comment", "text": "Brightburn is the movie"}],
            "summary": "A direct comment identifies the movie.",
            "needs_cloud": False,
            "uncertainty_reasons": [],
        }
        with patch.object(
            client.http,
            "request",
            return_value={"message": {"content": json.dumps(response)}},
        ) as request:
            result = client.analyze(b"candidate-image", "Brightburn is the movie")
        self.assertEqual(result.title, "Brightburn")
        body = request.call_args.args[2]
        self.assertEqual(
            body["messages"][1]["images"], [b64encode(b"candidate-image").decode()]
        )
        self.assertEqual(body["keep_alive"], 0)
        self.assertFalse(body["think"])
        self.assertFalse(body["format"]["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
