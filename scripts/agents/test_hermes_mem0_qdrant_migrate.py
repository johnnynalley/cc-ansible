#!/usr/bin/env python3
"""Tests for the source-preserving Mem0 Qdrant migration."""

from __future__ import annotations

import argparse
import copy
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
        self.configs = {
            "source": {
                "vectors": {"size": 3, "distance": "Cosine"},
                "sparse_vectors": None,
            },
        }
        self.payload_schema = {"source": {}}
        if target is not None:
            self.collections["target"] = target
            self.configs["target"] = {
                "vectors": {"size": 3, "distance": "Cosine"},
                "sparse_vectors": None,
            }
            self.payload_schema["target"] = {}
        self.snapshots: list[str] = []

    def collection(self, name: str) -> dict[str, Any] | None:
        if name not in self.collections:
            return None
        return {
            "result": {
                "config": {
                    "params": self.configs[name]
                },
                "payload_schema": self.payload_schema[name],
            }
        }

    def count(self, name: str) -> int:
        return len(self.collections[name])

    def points(self, name: str, batch_size: int, *, with_vector: bool = True):
        rows = copy.deepcopy(self.collections[name])
        if not with_vector:
            for row in rows:
                row.pop("vector", None)
        for index in range(0, len(rows), batch_size):
            yield rows[index : index + batch_size]

    def snapshot(self, name: str) -> str:
        self.snapshots.append(name)
        return "source-snapshot.snapshot"

    def create_collection(
        self,
        name: str,
        vectors: Any,
        sparse_vectors: dict[str, Any] | None = None,
    ) -> None:
        self.collections[name] = []
        self.configs[name] = {
            "vectors": vectors,
            "sparse_vectors": sparse_vectors,
        }
        self.payload_schema[name] = {}

    def create_payload_index(self, name: str, field_name: str) -> None:
        self.payload_schema[name][field_name] = {"data_type": "keyword"}

    def upsert(self, name: str, points: list[dict[str, Any]]) -> None:
        self.collections[name].extend(points)


class FakeOllama:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str], int]] = []

    def embed(self, model: str, texts: list[str], dimensions: int):
        self.calls.append((model, texts, dimensions))
        return [[float(index + 1) / dimensions for index in range(dimensions)] for _ in texts]


class FakeSparse:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]):
        self.calls.append(texts)
        return [
            {"indices": [7, 1], "values": [0.5, 1.0]}
            for _ in texts
        ]


def arguments(
    *,
    apply: bool,
    reembed: bool = False,
    hybrid: bool = False,
    source_normalized: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        source="source",
        target="target",
        user_id="johnny",
        agent_id="astra",
        include_user_id=["johnny", "johnny:agent:main"],
        source_normalized=source_normalized,
        batch_size=2,
        reembed=reembed,
        ollama_url="http://127.0.0.1:11434",
        embedding_model="qwen3-embedding:0.6b",
        embedding_dimensions=4,
        embedding_batch_size=2,
        hybrid=hybrid,
        sparse_model="Qdrant/bm25",
        empty_target=False,
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

    def test_empty_hybrid_target_is_initialized_without_source_content(self) -> None:
        client = FakeClient(self.source)
        args = arguments(apply=True, reembed=True, hybrid=True)
        args.source = None
        args.include_user_id = []
        args.empty_target = True

        result = MODULE.migrate(args, client)

        self.assertEqual(result["status"], "initialized")
        self.assertTrue(result["emptyTarget"])
        self.assertEqual(result["selectedCount"], 0)
        self.assertEqual(client.collections["source"], self.source)
        self.assertEqual(client.collections["target"], [])
        self.assertEqual(client.snapshots, [])
        self.assertEqual(
            set(client.payload_schema["target"]),
            {"user_id", "agent_id", "run_id", "actor_id"},
        )

    def test_empty_target_refuses_content_selection_or_nonempty_target(self) -> None:
        args = arguments(apply=True, reembed=True, hybrid=True)
        args.empty_target = True
        with self.assertRaisesRegex(MODULE.MigrationError, "empty-target-boundary-invalid"):
            MODULE.migrate(args, FakeClient(self.source))

        args.source = None
        args.include_user_id = []
        client = FakeClient(self.source, target=[self.source[0]])
        client.configs["target"] = {
            "vectors": {"size": 4, "distance": "Cosine"},
            "sparse_vectors": {"bm25": {"modifier": "idf"}},
        }
        client.payload_schema["target"] = {
            field: {"data_type": "keyword"}
            for field in ("user_id", "agent_id", "run_id", "actor_id")
        }
        with self.assertRaisesRegex(MODULE.MigrationError, "empty-target-nonempty"):
            MODULE.migrate(args, client)

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

    def test_reembed_dry_run_probes_local_model_without_creating_target(self) -> None:
        client = FakeClient(self.source)
        ollama = FakeOllama()

        result = MODULE.migrate(
            arguments(apply=False, reembed=True), client, ollama
        )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["embeddingDimensions"], 4)
        self.assertEqual(len(ollama.calls), 1)
        self.assertNotIn("target", client.collections)
        self.assertEqual(client.snapshots, [])

    def test_reembed_apply_preserves_payload_and_replaces_vectors(self) -> None:
        client = FakeClient(self.source)
        ollama = FakeOllama()

        result = MODULE.migrate(
            arguments(apply=True, reembed=True), client, ollama
        )

        self.assertEqual(result["status"], "migrated")
        self.assertEqual(client.snapshots, ["source"])
        self.assertEqual(client.collections["source"], self.source)
        target = client.collections["target"][0]
        self.assertEqual(target["payload"]["data"], "remembered fact")
        self.assertEqual(len(target["vector"]), 4)
        self.assertNotEqual(target["vector"], self.source[0]["vector"])

    def test_reembed_rejects_memory_without_text(self) -> None:
        self.source[0]["payload"].pop("data")

        with self.assertRaisesRegex(MODULE.MigrationError, "memory-data-invalid"):
            MODULE.migrate(
                arguments(apply=False, reembed=True),
                FakeClient(self.source),
                FakeOllama(),
            )

    def test_native_hybrid_apply_adds_bm25_without_mutating_source(self) -> None:
        source = copy.deepcopy(self.source)
        source[0]["payload"].pop("userId")
        source[0]["payload"]["user_id"] = "johnny"
        source[0]["payload"]["agent_id"] = "astra"
        client = FakeClient(source)
        sparse = FakeSparse()
        args = arguments(
            apply=True,
            hybrid=True,
            source_normalized=True,
        )
        args.embedding_dimensions = 3

        result = MODULE.migrate(args, client, sparse_encoder=sparse)

        self.assertEqual(result["status"], "migrated")
        self.assertTrue(result["hybrid"])
        self.assertEqual(client.collections["source"], source)
        self.assertEqual(
            client.configs["target"]["sparse_vectors"],
            {"bm25": {"modifier": "idf"}},
        )
        vector = client.collections["target"][0]["vector"]
        self.assertEqual(vector[""], [0.1, 0.2, 0.3])
        self.assertEqual(vector["bm25"]["indices"], [1, 7])
        self.assertEqual(vector["bm25"]["values"], [1.0, 0.5])
        self.assertGreaterEqual(len(sparse.calls), 2)

    def test_sparse_vector_rejects_duplicate_indices(self) -> None:
        with self.assertRaisesRegex(
            MODULE.MigrationError, "sparse-vector-index-invalid"
        ):
            MODULE.canonical_sparse_vector(
                {"indices": [9, 9], "values": [0.25, 0.75]}
            )

    def test_native_hybrid_rejects_target_without_bm25_slot(self) -> None:
        source = copy.deepcopy(self.source)
        source[0]["payload"] = {
            "data": "remembered fact",
            "user_id": "johnny",
            "agent_id": "astra",
        }
        client = FakeClient(source, target=copy.deepcopy(source))
        args = arguments(
            apply=False,
            hybrid=True,
            source_normalized=True,
        )
        args.embedding_dimensions = 3

        with self.assertRaisesRegex(
            MODULE.MigrationError, "hybrid-target-sparse-config-mismatch"
        ):
            MODULE.migrate(args, client, sparse_encoder=FakeSparse())

    def test_native_source_excludes_other_agents(self) -> None:
        source = copy.deepcopy(self.source)
        source[0]["payload"] = {
            "data": "astra fact",
            "user_id": "johnny",
            "agent_id": "astra",
        }
        source.append(
            {
                "id": "point-2",
                "vector": [0.3, 0.2, 0.1],
                "payload": {
                    "data": "other fact",
                    "user_id": "johnny",
                    "agent_id": "rigel",
                },
            }
        )
        client = FakeClient(source)
        args = arguments(
            apply=False,
            hybrid=True,
            source_normalized=True,
        )
        args.embedding_dimensions = 3

        result = MODULE.migrate(args, client, sparse_encoder=FakeSparse())

        self.assertEqual(result["sourceCount"], 2)
        self.assertEqual(result["selectedCount"], 1)
        self.assertEqual(result["excludedCount"], 1)


if __name__ == "__main__":
    unittest.main()
