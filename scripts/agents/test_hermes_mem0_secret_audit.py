#!/usr/bin/env python3
"""Regression tests for the content-free Mem0 secret audit."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SOURCE = Path(__file__).with_name("hermes-mem0-secret-audit.py")
SPEC = importlib.util.spec_from_file_location("hermes_mem0_secret_audit", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class Mem0SecretAuditTests(unittest.TestCase):
    def test_high_confidence_secret_shapes_are_detected(self):
        bearer = "Bearer " + "".join(("abcdefghijklmnop", "qrstuvwxyz012345"))
        github = "gh" + "p_" + "".join(("abcdefghijklmnop", "qrstuvwxyz1234567890"))
        payload = {
            "data": f"Authorization: {bearer} and token {github}"
        }
        self.assertEqual(
            MODULE.finding_classes(payload),
            ["bearer-token", "github-token"],
        )

    def test_normal_operational_memory_is_clean(self):
        payload = {
            "data": "The Health receiver uses a bearer token stored outside memory.",
            "metadata": {"channel": "discord"},
        }
        self.assertEqual(MODULE.finding_classes(payload), [])

    def test_report_never_contains_secret_text(self):
        secret = "Bearer " + "".join(("abcdefghijklmnop", "qrstuvwxyz012345"))
        report = MODULE.build_report(
            "memories_test",
            [
                {"id": "point-1", "payload": {"data": secret}},
                {"id": "point-2", "payload": {"data": "ordinary memory"}},
            ],
        )
        encoded = json.dumps(report)
        self.assertNotIn(secret, encoded)
        self.assertEqual(report["scannedPoints"], 2)
        self.assertEqual(len(report["findings"]), 1)
        self.assertEqual(report["findings"][0]["pointId"], "point-1")
        self.assertEqual(report["findings"][0]["classes"], ["bearer-token"])

    def test_atomic_report_is_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.json"
            MODULE.atomic_json(path, {"schemaVersion": 1})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
