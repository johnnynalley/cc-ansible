#!/usr/bin/env python3
"""Tests for content-free profile transcript route privacy auditing."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
SOURCE = ROOT / "scripts/agents/hermes-profile-memory-privacy-audit.py"
SPEC = importlib.util.spec_from_file_location("hermes_profile_memory_privacy_audit", SOURCE)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ProfileMemoryPrivacyAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.sessions = self.root / "sessions"
        self.sessions.mkdir()
        self.guild = "1209365945882251294"
        self.channel = "1483229851350728784"
        self.policy = self.root / "policy.json"
        self.policy.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "guilds": [self.guild],
                    "channels": [self.channel],
                    "fileRoots": [],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp.cleanup()

    def source(self, name: str) -> Path:
        path = self.sessions / f"{name}.jsonl"
        path.write_text(f'{{"private":"{name}-secret"}}\n', encoding="utf-8")
        return path

    def entry(self, path: Path, **overrides):
        row = {
            "sessionFile": str(path),
            "channel": "discord",
            "chatType": "channel",
            "groupId": self.guild,
            "route": {"channel": "discord", "target": self.channel},
        }
        row.update(overrides)
        return row

    def args(self, *indexes: Path):
        return types.SimpleNamespace(
            source_dir=self.sessions,
            session_index=list(indexes),
            policy=self.policy,
            approved_manifest=None,
        )

    def write_index(self, name: str, payload: dict) -> Path:
        path = self.root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_approves_only_complete_exact_public_route_evidence(self):
        one = self.source("one")
        two = self.source("two")
        index = self.write_index(
            "sessions.json",
            {"one": self.entry(one), "two": self.entry(two)},
        )
        output = MODULE.audit(self.args(index))
        self.assertEqual(output["status"], "approved")
        self.assertEqual(output["sourceClassifications"]["approved-public"], 2)
        self.assertEqual(output["blockers"], [])

    def test_blocks_unindexed_direct_thread_unknown_and_conflicting_sources(self):
        approved = self.source("approved")
        thread = self.source("thread")
        direct = self.source("direct")
        unknown = self.source("unknown")
        conflict = self.source("conflict")
        self.source("unindexed")
        first = self.write_index(
            "sessions.json",
            {
                "approved": self.entry(approved),
                "thread": self.entry(
                    thread,
                    route={"channel": "discord", "thread": "1999999999999999999"},
                    lastThreadId="1999999999999999999",
                ),
                "direct": self.entry(
                    direct,
                    chatType="direct",
                    groupId=None,
                    route={"channel": "discord", "target": "1888888888888888888"},
                ),
                "unknown": {"sessionFile": str(unknown)},
                "conflict": self.entry(conflict),
                "route-only": {"channel": "discord", "chatType": "channel"},
            },
        )
        second = self.write_index(
            "backup.json",
            {
                "conflict": self.entry(
                    conflict,
                    chatType="direct",
                    groupId=None,
                    route={"channel": "discord", "target": "1777777777777777777"},
                )
            },
        )
        output = MODULE.audit(self.args(first, second))
        counts = output["sourceClassifications"]
        self.assertEqual(output["status"], "blocked")
        self.assertEqual(counts["approved-public"], 1)
        self.assertEqual(counts["unresolved-thread-parent"], 1)
        self.assertEqual(counts["direct"], 1)
        self.assertEqual(counts["unknown-route"], 1)
        self.assertEqual(counts["conflicting-route-evidence"], 1)
        self.assertEqual(counts["unindexed"], 1)
        self.assertEqual(output["sessionEntriesWithoutFilePointers"], 1)

    def test_output_never_contains_ids_paths_filenames_or_source_text(self):
        source = self.source("private-session-name")
        index = self.write_index("private-index-name.json", {"one": self.entry(source)})
        encoded = json.dumps(MODULE.audit(self.args(index)))
        for forbidden in (
            self.guild,
            self.channel,
            str(self.root),
            source.name,
            index.name,
            "private-session-name-secret",
        ):
            self.assertNotIn(forbidden, encoded)

    def test_stale_pointer_cannot_authorize_an_unindexed_canonical_source(self):
        self.source("canonical")
        outside = self.root / "outside.jsonl"
        outside.write_text("{}\n", encoding="utf-8")
        index = self.write_index("sessions.json", {"outside": self.entry(outside)})
        output = MODULE.audit(self.args(index))
        self.assertEqual(output["status"], "blocked")
        self.assertEqual(output["staleSessionFilePointers"], 1)
        self.assertEqual(output["sourceClassifications"]["unindexed"], 1)

    def test_relocated_pointer_joins_only_to_existing_canonical_basename(self):
        canonical = self.source("relocated")
        old_path = self.root / "old-root" / canonical.name
        index = self.write_index(
            "sessions.json", {"relocated": self.entry(old_path)}
        )
        output = MODULE.audit(self.args(index))
        self.assertEqual(output["status"], "approved")
        self.assertEqual(output["relocatedSessionFilePointers"], 1)

    def test_writes_private_public_subset_without_exposing_names(self):
        approved = self.source("approved-private-name")
        self.source("unindexed-private-name")
        index = self.write_index("sessions.json", {"approved": self.entry(approved)})
        manifest = self.root / "approved.json"
        args = self.args(index)
        args.approved_manifest = manifest
        output = MODULE.audit(args)
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(output["status"], "blocked")
        self.assertEqual(payload["status"], "approved-public-subset")
        self.assertEqual(payload["approvedFiles"], [approved.name])
        self.assertEqual(manifest.stat().st_mode & 0o777, 0o600)
        encoded = json.dumps(output)
        self.assertNotIn(approved.name, encoded)
        self.assertNotIn("unindexed-private-name", encoded)

    def test_refuses_empty_approved_subset_manifest(self):
        self.source("unindexed")
        index = self.write_index("sessions.json", {})
        args = self.args(index)
        args.approved_manifest = self.root / "approved.json"
        with self.assertRaisesRegex(MODULE.PrivacyAuditError, "approved-manifest-empty"):
            MODULE.audit(args)


if __name__ == "__main__":
    unittest.main()
