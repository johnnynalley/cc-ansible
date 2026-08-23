#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name("arr_indexer_preference_policy.py")
SPEC = importlib.util.spec_from_file_location("arr_indexer_preference_policy", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
POLICY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = POLICY
SPEC.loader.exec_module(POLICY)


class IndexerPreferencePolicyTests(unittest.TestCase):
    def test_priority_bands(self) -> None:
        cases = (
            ({"name": "NZBgeek", "protocol": "usenet", "priority": 25}, 1),
            (
                {
                    "name": "seedpool (API)",
                    "protocol": "torrent",
                    "privacy": "private",
                    "priority": 25,
                },
                10,
            ),
            (
                {
                    "name": "Nyaa.si",
                    "protocol": "torrent",
                    "privacy": "public",
                    "priority": 25,
                },
                15,
            ),
            (
                {
                    "name": "AnimeTosho",
                    "protocol": "torrent",
                    "privacy": "private",
                    "priority": 25,
                },
                15,
            ),
            (
                {
                    "name": "1337x",
                    "protocol": "torrent",
                    "privacy": "public",
                    "priority": 25,
                },
                25,
            ),
        )
        for indexer, expected in cases:
            with self.subTest(indexer=indexer["name"]):
                self.assertEqual(POLICY.desired_priority(indexer), expected)

    def test_unknown_private_tracker_is_preserved(self) -> None:
        indexer = {
            "name": "Future Private Tracker",
            "protocol": "torrent",
            "privacy": "private",
            "priority": 7,
        }
        self.assertEqual(POLICY.desired_priority(indexer), 7)

    def test_prowlarr_suffix_is_normalized(self) -> None:
        self.assertEqual(
            POLICY.normalized_name("seedpool (API) (Prowlarr)"), "seedpoolapi"
        )

    def test_downstream_category_subset_is_valid(self) -> None:
        expected = {"seedpoolapi": 10, "yts": 25}
        response = [{"name": "seedpool (API) (Prowlarr)", "priority": 10}]
        with patch.object(POLICY, "request_json", return_value=response):
            valid, rows = POLICY.verify_downstream_indexers(
                POLICY.ARR_SERVICES[0], "test-key", expected
            )
        self.assertTrue(valid)
        self.assertEqual(len(rows), 1)

    def test_downstream_priority_drift_is_invalid(self) -> None:
        expected = {"seedpoolapi": 10}
        response = [{"name": "seedpool (API) (Prowlarr)", "priority": 25}]
        with patch.object(POLICY, "request_json", return_value=response):
            valid, rows = POLICY.verify_downstream_indexers(
                POLICY.ARR_SERVICES[0], "test-key", expected
            )
        self.assertFalse(valid)
        self.assertFalse(rows[0]["valid"])


if __name__ == "__main__":
    unittest.main()
