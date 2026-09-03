#!/usr/bin/env python3
"""Focused tests for Profilarr tier-candidate comparison."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("profilarr_tier_candidate_compare.py")
SPEC = importlib.util.spec_from_file_location("profilarr_tier_candidate_compare", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class MatchingLiveNameTests(unittest.TestCase):
    def test_matches_unprefixed_live_name(self) -> None:
        live_names = {"WEB-DL Tier 2"}

        self.assertEqual(
            MODULE.matching_live_name("Dictionarry", "WEB-DL Tier 2", live_names),
            "WEB-DL Tier 2",
        )

    def test_matches_managed_source_prefix(self) -> None:
        live_names = {"Dictionarry WEB-DL Tier 2"}

        self.assertEqual(
            MODULE.matching_live_name("Dictionarry", "WEB-DL Tier 2", live_names),
            "Dictionarry WEB-DL Tier 2",
        )

    def test_does_not_match_different_source(self) -> None:
        live_names = {"TRaSH Guides WEB-DL Tier 2"}

        self.assertIsNone(
            MODULE.matching_live_name("Dictionarry", "WEB-DL Tier 2", live_names)
        )


if __name__ == "__main__":
    unittest.main()
