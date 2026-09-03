#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("prowlarr_indexer_app_profile.py")
SPEC = importlib.util.spec_from_file_location("prowlarr_indexer_app_profile", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ProwlarrIndexerAppProfileTests(unittest.TestCase):
    def test_select_exact_is_case_insensitive_and_requires_one(self) -> None:
        records = [{"id": 1, "name": "AnimeTosho"}]
        self.assertEqual(
            MODULE.select_exact(records, "animetosho", "indexer")["id"], 1
        )
        with self.assertRaises(RuntimeError):
            MODULE.select_exact([], "missing", "indexer")

    def test_safe_indexer_excludes_fields_and_urls(self) -> None:
        result = MODULE.safe_indexer(
            {
                "id": 6,
                "name": "AnimeTosho",
                "protocol": "torrent",
                "priority": 15,
                "appProfileId": 1,
                "fields": [{"name": "apiKey", "value": "private"}],
            }
        )
        self.assertEqual(result["app_profile_id"], 1)
        self.assertNotIn("fields", result)

    def test_write_rollback_requires_root_only_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o755)
            with self.assertRaises(RuntimeError):
                MODULE.write_rollback(root, {}, {}, {})

    def test_verify_downstream_requires_exact_profile_flags(self) -> None:
        profile = {
            "enableRss": False,
            "enableAutomaticSearch": False,
            "enableInteractiveSearch": True,
        }
        MODULE.verify_downstream(
            {
                "sonarr": {
                    "enable_rss": False,
                    "enable_automatic_search": False,
                    "enable_interactive_search": True,
                }
            },
            profile,
        )
        with self.assertRaises(RuntimeError):
            MODULE.verify_downstream(
                {
                    "sonarr": {
                        "enable_rss": True,
                        "enable_automatic_search": False,
                        "enable_interactive_search": True,
                    }
                },
                profile,
            )


if __name__ == "__main__":
    unittest.main()
