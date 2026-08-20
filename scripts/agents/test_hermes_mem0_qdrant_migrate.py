#!/usr/bin/env python3
"""Tests for the source-preserving Mem0 Qdrant migration."""

from __future__ import annotations

import argparse
import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any


MODULE_PATH = Path(__file__).with_name("hermes-mem0-qdrant-migrate.py")
SPEC = importlib.util.spec_from_file_location("hermes_mem0_qdrant_migrate", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeClient:
    def __init__(
        self,
        source: list[dict[str, Any]],
        target: list[dict[str, Any]] | None = None,
    ):
        self.collections = {"source": source}
        if target is not None:
            self.collections["target"] = target
        self.snapshots: list[str] = []

    def collection(self, name: str) -> dict[str, Any] | None:
        if name not in self.collections:
            return None
        return {
            "result": {
                "config": {
                    "params": {"vectors": {"size": 3, "distance": "Cosine"}}
                }
            }
        }

    def count(self, name: str) -> int:
        return len(self.collections[name])

    def points(self, name: str, batch_size: int):
        rows = self.collections[name]
        for index in range(0, len(rows), batch_size):
            yield rows[index : index + batch_size]

    def snapshot(self, name: str) -> str:
        self.snapshots.append(name)
        return "source-snapshot.snapshot"

    def create_collection(self, name: str, vectors: Any) -> None:
        self.collections[name] = []

    def upsert(self, name: str, points: list[dict[str, Any]]) -> None:
        self.collections[name].extend(points)


def arguments(*, apply: bool) -> argparse.Namespace:
    return argparse.Namespace(
        source="source",
        target="target",
        user_id="johnny",
        agent_id="astra",
        include_user_id=["johnny", "johnny:agent:main"],
        batch_size=2,
        apply=apply,
    )


class Mem0MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = [
            {
                "id": "point-1",
                "vector": [0.1, 0.2, 0.3],
                "payload": {
                    "data": "remembered fact",
                    "hash": "abc",
                    "userId": "johnny",
                    "runId": "discord",
                    "createdAt": "2026-04-08T00:00:00Z",
                },
            }
        ]

    def test_payload_maps_identity_without_touching_content(self) -> None:
        migrated = MODULE.transformed_point(self.source[0], "johnny", "astra")
        self.assertEqual(migrated["id"], "point-1")
        self.assertEqual(migrated["vector"], [0.1, 0.2, 0.3])
        self.assertEqual(migrated["payload"]["data"], "remembered fact")
        self.assertEqual(migrated["payload"]["hash"], "abc")
        self.assertEqual(migrated["payload"]["user_id"], "johnny")
        self.assertEqual(migrated["payload"]["agent_id"], "astra")
        self.assertEqual(migrated["payload"]["run_id"], "discord")
        self.assertNotIn("userId", migrated["payload"])

    def test_main_scope_is_normalized_and_preserved_as_provenance(self) -> None:
        self.source[0]["payload"]["userId"] = "johnny:agent:main"

        migrated = MODULE.transformed_point(self.source[0], "johnny", "astra")

        self.assertEqual(migrated["payload"]["user_id"], "johnny")
        self.assertEqual(
            migrated["payload"]["openclaw_user_id"], "johnny:agent:main"
        )

    def test_dry_run_does_not_create_snapshot_or_target(self) -> None:
        client = FakeClient(self.source)

        result = MODULE.migrate(arguments(apply=False), client)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["sourceCount"], 1)
        self.assertNotIn("target", client.collections)
        self.assertEqual(client.snapshots, [])

    def test_apply_snapshots_source_and_verifies_target(self) -> None:
        client = FakeClient(self.source)

        result = MODULE.migrate(arguments(apply=True), client)

        self.assertEqual(result["status"], "migrated")
        self.assertEqual(result["sourceCount"], result["targetCount"])
        self.assertEqual(client.snapshots, ["source"])
        self.assertEqual(client.collections["source"], self.source)
        self.assertEqual(client.collections["target"][0]["id"], "point-1")

    def test_other_agent_scopes_are_left_out_of_astra_target(self) -> None:
        other = {
            "id": "point-2",
            "vector": [0.3, 0.2, 0.1],
            "payload": {"data": "rigel memory", "userId": "johnny:agent:rigel"},
        }
        client = FakeClient([self.source[0], other])

        result = MODULE.migrate(arguments(apply=True), client)

        self.assertEqual(result["sourceCount"], 2)
        self.assertEqual(result["selectedCount"], 1)
        self.assertEqual(result["excludedCount"], 1)
        self.assertEqual([row["id"] for row in client.collections["target"]], ["point-1"])

    def test_nonempty_inconsistent_target_is_refused(self) -> None:
        client = FakeClient(
            self.source,
            target=[{"id": "different", "vector": [0, 0, 0], "payload": {}}],
        )

        with self.assertRaisesRegex(
            MODULE.MigrationError, "nonempty-target-does-not-match-source"
        ):
            MODULE.migrate(arguments(apply=True), client)

        self.assertEqual(client.snapshots, [])


if __name__ == "__main__":
    unittest.main()
