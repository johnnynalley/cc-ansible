#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPT = Path(__file__).with_name("prowlarr_indexer_policy_audit.py")
SPEC = importlib.util.spec_from_file_location("prowlarr_indexer_policy_audit", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ProwlarrIndexerPolicyAuditTests(unittest.TestCase):
    def test_report_excludes_credentials_and_urls(self) -> None:
        report = MODULE.safe_indexer(
            {
                "id": 1,
                "name": "Private Tracker",
                "protocol": "torrent",
                "priority": 10,
                "enable": True,
                "appProfileId": 1,
                "tags": [2],
                "fields": [
                    {"name": "apiKey", "value": "secret"},
                    {"name": "baseUrl", "value": "https://tracker.invalid/passkey"},
                    {"name": "minimumSeeders", "value": 2},
                    {"name": "seedTime", "value": 43200},
                ],
            }
        )
        self.assertEqual(report["limits"], {"minimumSeeders": 2, "seedTime": 43200})
        self.assertNotIn("fields", report)

    def test_ignores_structured_values(self) -> None:
        self.assertEqual(
            MODULE.safe_field_values(
                [{"name": "queryLimit", "value": {"unexpected": "secret"}}],
                MODULE.PROWLARR_SAFE_FIELD_NAMES,
            ),
            {},
        )

    def test_arr_report_only_includes_synced_policy_fields(self) -> None:
        report = MODULE.safe_arr_indexer(
            {
                "id": 2,
                "name": "Prowlarr",
                "implementation": "Torznab",
                "priority": 10,
                "enableRss": True,
                "enableAutomaticSearch": True,
                "enableInteractiveSearch": True,
                "fields": [
                    {"name": "apiKey", "value": "secret"},
                    {"name": "baseUrl", "value": "https://prowlarr.invalid"},
                    {"name": "minimumSeeders", "value": 1},
                    {"name": "seedCriteria.seedRatio", "value": 5.0},
                ],
            }
        )
        self.assertEqual(
            report["limits"],
            {"minimumSeeders": 1, "seedCriteria.seedRatio": 5.0},
        )


if __name__ == "__main__":
    unittest.main()
