#!/usr/bin/env python3

from __future__ import annotations

import contextlib
import importlib.util
import io
import sqlite3
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("profilarr_cf_definition_sync.py")
SPEC = importlib.util.spec_from_file_location("profilarr_cf_definition_sync", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SyncTargetTests(unittest.TestCase):
    def test_dictionarry_tv_target_is_prefixed_and_sonarr_only(self) -> None:
        target = next(
            item
            for item in MODULE.DEFAULT_SYNC_TARGETS
            if item.target_name == "Dictionarry 1080p Efficient TV Bluray Tier 1"
        )

        self.assertEqual(target.targets, ("sonarr",))
        self.assertEqual(
            target.sources,
            (MODULE.SourceOption("Dictionarry", "1080p Efficient TV Bluray Tier 1"),),
        )

    def test_dictionarry_movie_target_is_prefixed_and_radarr_only(self) -> None:
        target = next(
            item
            for item in MODULE.DEFAULT_SYNC_TARGETS
            if item.target_name == "Dictionarry 1080p Compact Movie WEB Tier 4"
        )

        self.assertEqual(target.targets, ("radarr",))
        self.assertEqual(target.sources[0].database_name, "Dictionarry")

    def test_shared_dictionarry_formats_target_both_arrs(self) -> None:
        target = next(
            item
            for item in MODULE.DEFAULT_SYNC_TARGETS
            if item.target_name == "Dictionarry WEB-DL Tier 5"
        )

        self.assertEqual(target.targets, ("sonarr", "radarr"))

    def test_sonarr_release_type_is_translated_to_native_schema(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE condition_release_types (
                custom_format_name TEXT,
                condition_name TEXT,
                release_type TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO condition_release_types VALUES (?, ?, ?)",
            ("Tier", "Season Pack", "season_pack"),
        )
        condition = {
            "custom_format_name": "Tier",
            "name": "Season Pack",
            "type": "release_type",
            "negate": 0,
            "required": 1,
        }

        payload = MODULE.condition_payload(conn, "sonarr", condition)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["implementation"], "ReleaseTypeSpecification")
        self.assertEqual(payload["fields"][0]["value"], 3)
        self.assertTrue(payload["required"])

    def test_spec_deltas_detect_changed_value(self) -> None:
        live = {
            "specifications": [
                MODULE.spec_payload(
                    "sonarr",
                    {"name": "Group", "negate": 0, "required": 0},
                    "ReleaseGroupSpecification",
                    "Release Group",
                    "old",
                )
            ]
        }
        desired = {
            "specifications": [
                MODULE.spec_payload(
                    "sonarr",
                    {"name": "Group", "negate": 0, "required": 0},
                    "ReleaseGroupSpecification",
                    "Release Group",
                    "new",
                )
            ]
        }

        added, removed = MODULE.spec_deltas(live, desired)

        self.assertEqual(added[0]["fields"][0]["value"], "new")
        self.assertEqual(removed[0]["fields"][0]["value"], "old")


class ArgumentTests(unittest.TestCase):
    def test_audit_is_default(self) -> None:
        with mock.patch.object(sys, "argv", ["profilarr_cf_definition_sync.py"]):
            args = MODULE.parse_args()

        self.assertFalse(args.apply)

    def test_apply_requires_explicit_flag(self) -> None:
        with mock.patch.object(
            sys,
            "argv",
            ["profilarr_cf_definition_sync.py", "--apply"],
        ):
            args = MODULE.parse_args()

        self.assertTrue(args.apply)

    def test_apply_and_dry_run_are_mutually_exclusive(self) -> None:
        with mock.patch.object(
            sys,
            "argv",
            ["profilarr_cf_definition_sync.py", "--apply", "--dry-run"],
        ):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    MODULE.parse_args()


class SourceFreshnessTests(unittest.TestCase):
    def source(self, *, synced: str, enabled: bool = True, auto_pull: bool = True) -> dict:
        return {
            "metadata": {
                "enabled": enabled,
                "auto_pull": auto_pull,
                "last_synced_at": synced,
            }
        }

    def test_recent_required_sources_pass(self) -> None:
        databases = {
            "Dictionarry": self.source(synced="2026-09-03 08:00:00"),
            "TRaSH Guides": self.source(synced="2026-09-03T08:30:00Z"),
        }

        MODULE.validate_source_freshness(
            databases,
            26,
            now=datetime(2026, 9, 3, 9, 0, tzinfo=timezone.utc),
        )

    def test_stale_source_fails_closed(self) -> None:
        databases = {
            "Dictionarry": self.source(synced="2026-09-01 08:00:00"),
            "TRaSH Guides": self.source(synced="2026-09-03 08:30:00"),
        }

        with self.assertRaisesRegex(RuntimeError, "Dictionarry source database is stale"):
            MODULE.validate_source_freshness(
                databases,
                26,
                now=datetime(2026, 9, 3, 9, 0, tzinfo=timezone.utc),
            )

    def test_disabled_auto_pull_fails_closed(self) -> None:
        databases = {
            "Dictionarry": self.source(
                synced="2026-09-03 08:00:00",
                auto_pull=False,
            ),
            "TRaSH Guides": self.source(synced="2026-09-03 08:30:00"),
        }

        with self.assertRaisesRegex(RuntimeError, "auto-pull is disabled"):
            MODULE.validate_source_freshness(
                databases,
                26,
                now=datetime(2026, 9, 3, 9, 0, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
