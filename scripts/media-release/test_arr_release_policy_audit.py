#!/usr/bin/env python3
"""Focused regressions for Arr release-policy inventory reporting."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/media-release/arr_release_policy_audit.py"
SPEC = importlib.util.spec_from_file_location("arr_release_policy_audit", SOURCE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to load {SOURCE}")
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


class MatchingDefinitionTests(unittest.TestCase):
    def test_duplicate_signature_ignores_name_id_and_specification_order(self) -> None:
        first = {
            "id": 1,
            "name": "First",
            "specifications": [
                {
                    "name": "Codec",
                    "implementation": "ReleaseTitleSpecification",
                    "negate": False,
                    "required": True,
                    "fields": {"value": "x265"},
                },
                {
                    "name": "Source",
                    "implementation": "SourceSpecification",
                    "negate": False,
                    "required": False,
                    "fields": {"value": 7},
                },
            ],
        }
        second = {
            "id": 2,
            "name": "Second",
            "specifications": list(reversed(first["specifications"])),
        }
        self.assertEqual(
            AUDIT.matching_definition_signature(first),
            AUDIT.matching_definition_signature(second),
        )

    def test_different_matching_fields_are_not_duplicates(self) -> None:
        first = {
            "id": 1,
            "name": "First",
            "specifications": [
                {
                    "implementation": "ReleaseTitleSpecification",
                    "negate": False,
                    "required": True,
                    "fields": {"value": "x265"},
                }
            ],
        }
        second = {
            "id": 2,
            "name": "Second",
            "specifications": [
                {
                    "implementation": "ReleaseTitleSpecification",
                    "negate": False,
                    "required": True,
                    "fields": {"value": "AV1"},
                }
            ],
        }
        groups = AUDIT.matching_definition_duplicates(
            [first, second],
            {1: {"profile"}, 2: {"profile"}},
            {1: {"profile": 5}, 2: {"profile": -5}},
        )
        self.assertEqual(groups, [])

    def test_duplicate_report_preserves_profile_and_rename_differences(self) -> None:
        specification = [
            {
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": False,
                "fields": {"value": "DUAL"},
            }
        ]
        groups = AUDIT.matching_definition_duplicates(
            [
                {"id": 1, "name": "First", "specifications": specification},
                {
                    "id": 2,
                    "name": "Second",
                    "includeCustomFormatWhenRenaming": True,
                    "specifications": specification,
                },
            ],
            {1: {"anime"}, 2: {"regular"}},
            {1: {"anime": 100}, 2: {"regular": 0}},
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["formats"][0]["profiles"], ["anime"])
        self.assertTrue(groups[0]["formats"][1]["include_in_rename"])


if __name__ == "__main__":
    unittest.main()
