#!/usr/bin/env python3
"""Tests for isolated profile Mem0 acceptance and cleanup."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
SOURCE = ROOT / "scripts/agents/hermes-profile-mem0-smoke.py"
SPEC = importlib.util.spec_from_file_location("hermes_profile_mem0_smoke", SOURCE)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class Point:
    def __init__(self, data: str) -> None:
        self.payload = {"data": data}


class Store:
    def __init__(self, memory: "Memory") -> None:
        self.memory = memory

    def list(self, **_kwargs):
        return list(self.memory.values)

    def keyword_search(self, *_args, **_kwargs):
        return list(self.memory.values)


class Memory:
    def __init__(self, values: list[Point] | None = None) -> None:
        self.values = list(values or [])
        self.vector_store = Store(self)

    def add(self, marker, **kwargs):
        self.values.append(Point(marker))

    def search(self, *_args, **_kwargs):
        return list(self.values)

    def delete_all(self, **_kwargs):
        self.values.clear()


class ProfileMem0SmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Path(self.temp.name) / "mem0.json"
        self.config.write_text(json.dumps({"oss": {"vector_store": {}}}), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def args(self, mode: str):
        return types.SimpleNamespace(
            config=self.config, user_id="johnny", agent_id="dubble", mode=mode
        )

    def test_empty_roundtrip_always_cleans_up(self):
        memory = Memory()
        output = MODULE.run(self.args("empty-roundtrip"), lambda _config: memory)
        self.assertEqual(output["status"], "ok")
        self.assertGreater(output["added"], 0)
        self.assertEqual(memory.values, [])

    def test_failed_recall_still_cleans_up(self):
        memory = Memory()
        memory.search = lambda *_args, **_kwargs: []
        with self.assertRaisesRegex(MODULE.SmokeError, "roundtrip-semantic-recall"):
            MODULE.run(self.args("empty-roundtrip"), lambda _config: memory)
        self.assertEqual(memory.values, [])

    def test_existing_mode_is_read_only(self):
        memory = Memory([Point("durable public memory")])
        output = MODULE.run(self.args("existing"), lambda _config: memory)
        self.assertEqual(output["before"], 1)
        self.assertEqual(output["after"], 1)


if __name__ == "__main__":
    unittest.main()
