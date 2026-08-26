#!/usr/bin/env python3
"""Focused regressions for the native Fortnite snapshot collector."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("hermes-fortnite-progress-snapshot.py")
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location(
    "hermes_fortnite_progress_snapshot",
    SCRIPT,
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FortniteProgressSnapshotTests(unittest.TestCase):
    def test_load_source_module_accepts_extensionless_managed_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            helper = Path(tmp) / "hermes-fortnite-progress-normalize"
            helper.write_text(
                "def run():\n    return {'status': 'ok', 'source': 'test'}\n",
                encoding="utf-8",
            )

            loaded = MODULE.load_source_module("test_normalizer", helper)

            self.assertEqual(
                loaded.run(),
                {"status": "ok", "source": "test"},
            )


if __name__ == "__main__":
    unittest.main()
