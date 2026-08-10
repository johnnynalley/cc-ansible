from __future__ import annotations

import sys
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from immich_media_inbox.clients import SeerrClient  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
