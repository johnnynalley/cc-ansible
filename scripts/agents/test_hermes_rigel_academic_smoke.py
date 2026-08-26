#!/usr/bin/env python3
"""Regressions for the content-free Rigel academic file smoke."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("hermes-rigel-academic-smoke.py")
VARS = Path(__file__).parents[2] / "inventory/group_vars/hermes_hosts/vars.yml"
SPEC = importlib.util.spec_from_file_location("hermes_rigel_academic_smoke", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class HermesRigelAcademicSmokeTests(unittest.TestCase):
    def test_sample_parser_is_exact_and_traversal_free(self) -> None:
        self.assertEqual(
            MODULE.parse_sample("pdf=courses/syllabus.pdf"),
            ("pdf", Path("courses/syllabus.pdf")),
        )
        for invalid in (
            "pdf=/tmp/file.pdf",
            "pdf=../file.pdf",
            "pdf=file.docx",
            "txt=file.txt",
            "missing-separator",
        ):
            with self.assertRaises(Exception):
                MODULE.parse_sample(invalid)

    def test_input_validation_requires_all_document_types_and_native_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "courses").mkdir()
            (root / "memory").mkdir()
            samples = []
            for kind, suffix in MODULE.SUPPORTED_SAMPLE_TYPES.items():
                path = Path("courses") / f"sample{suffix}"
                (root / path).write_bytes(b"fixture")
                samples.append((kind, path))
            self.assertEqual(MODULE.validate_inputs(root, samples), root)
            with self.assertRaisesRegex(MODULE.SmokeError, "exactly-one"):
                MODULE.validate_inputs(root, samples[:-1])

    def test_tool_result_decoder_rejects_protocol_errors(self) -> None:
        self.assertEqual(
            MODULE.decode_tool_result('{"content":"x"}', "read"),
            {"content": "x"},
        )
        with self.assertRaisesRegex(MODULE.SmokeError, "non-json"):
            MODULE.decode_tool_result("not-json", "read")
        with self.assertRaisesRegex(MODULE.SmokeError, "write-failed"):
            MODULE.require_success({"error": "denied"}, "write")

    def test_runtime_dependency_policy_tracks_latest_stable_anydoc(self) -> None:
        import yaml

        variables = yaml.safe_load(VARS.read_text(encoding="utf-8"))
        dependencies = variables["hermes_mem0_stable_dependencies"]
        self.assertIn("firecrawl-anydoc", dependencies)
        self.assertFalse(any("firecrawl-anydoc==" in item for item in dependencies))

    def test_smoke_output_contract_never_includes_document_content(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("os.initgroups(user, account.pw_gid)", source)
        self.assertIn('"documents": extracted', source)
        self.assertIn('"outsideWriteDenied": True', source)
        self.assertNotIn('"content": result["content"]', source)


if __name__ == "__main__":
    unittest.main()
