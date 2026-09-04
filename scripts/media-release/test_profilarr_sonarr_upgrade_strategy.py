#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("profilarr_sonarr_upgrade_strategy.py")
SPEC = importlib.util.spec_from_file_location("profilarr_sonarr_upgrade_strategy", MODULE_PATH)
assert SPEC and SPEC.loader
STRATEGY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STRATEGY)


def filters() -> list[dict]:
    return [
        {
            "id": "sonarr-cutoff-unmet",
            "selector": "oldest",
            "group": {
                "type": "group",
                "match": "all",
                "children": [
                    {"type": "rule", "field": "monitored", "operator": "is", "value": True},
                    {"type": "rule", "field": "cutoff_met", "operator": "is", "value": False},
                ],
            },
        }
    ]


class UpgradeStrategyTests(unittest.TestCase):
    def test_adds_episode_ceiling_and_selector(self) -> None:
        updated, changes = STRATEGY.update_filters(
            filters(), "sonarr-cutoff-unmet", "random", 30
        )
        self.assertEqual(updated[0]["selector"], "random")
        self.assertIn(
            {"type": "rule", "field": "episode_count", "operator": "lte", "value": 30},
            updated[0]["group"]["children"],
        )
        self.assertEqual(len(changes), 2)

    def test_episode_ceiling_is_idempotent(self) -> None:
        updated, _ = STRATEGY.update_filters(
            filters(), "sonarr-cutoff-unmet", "random", 30
        )
        second, changes = STRATEGY.update_filters(
            updated, "sonarr-cutoff-unmet", "random", 30
        )
        self.assertEqual(second, updated)
        self.assertEqual(changes, [])

    def test_replaces_wrong_episode_rule(self) -> None:
        data = filters()
        data[0]["group"]["children"].append(
            {"type": "rule", "field": "episode_count", "operator": "gt", "value": 100}
        )
        updated, changes = STRATEGY.update_filters(
            data, "sonarr-cutoff-unmet", "oldest", 30
        )
        rule = updated[0]["group"]["children"][-1]
        self.assertEqual(rule["operator"], "lte")
        self.assertEqual(rule["value"], 30)
        self.assertEqual(len(changes), 1)

    def test_rejects_multiple_episode_rules(self) -> None:
        data = filters()
        data[0]["group"]["children"].extend(
            [
                {"type": "rule", "field": "episode_count", "operator": "lte", "value": 30},
                {"type": "rule", "field": "episode_count", "operator": "gte", "value": 1},
            ]
        )
        with self.assertRaisesRegex(RuntimeError, "multiple episode_count"):
            STRATEGY.update_filters(data, "sonarr-cutoff-unmet", "random", 30)


if __name__ == "__main__":
    unittest.main()
