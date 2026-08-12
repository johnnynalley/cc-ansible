#!/usr/bin/env python3
"""Tests for the modern OpenClaw bootstrap audit."""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("openclaw-bootstrap-audit.py")
SOURCE = Path(__file__).parents[2] / "files/openclaw/workspace"
SPEC = importlib.util.spec_from_file_location("openclaw_bootstrap_audit", SCRIPT)
assert SPEC and SPEC.loader
audit_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit_module
SPEC.loader.exec_module(audit_module)


class BootstrapAuditTests(unittest.TestCase):
    def copy_source(self, directory_name: str) -> Path:
        target = Path(directory_name) / "workspace"
        shutil.copytree(SOURCE, target)
        return target

    def test_repo_bundle_passes_with_compact_role_profiles(self) -> None:
        result = audit_module.audit_bundle(SOURCE)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["fileCount"], 20)
        self.assertLess(result["totalChars"], result["totalMaxChars"])

    def test_legacy_human_home_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = self.copy_source(directory_name)
            path = root / "AGENTS.md"
            path.write_text(
                path.read_text(encoding="ascii")
                + "Legacy: /home/johnny/.openclaw/workspace\n",
                encoding="ascii",
            )
            with self.assertRaisesRegex(
                audit_module.AuditError, "forbidden-fragment"
            ):
                audit_module.audit_bundle(root)

    def test_opaque_platform_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = self.copy_source(directory_name)
            path = root / "dubble/TOOLS.md"
            path.write_text(
                path.read_text(encoding="ascii") + "Channel 123456789012345678\n",
                encoding="ascii",
            )
            with self.assertRaisesRegex(
                audit_module.AuditError, "opaque-platform-id"
            ):
                audit_module.audit_bundle(root)

    def test_heartbeat_control_token_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = self.copy_source(directory_name)
            path = root / "rigel/HEARTBEAT.md"
            path.write_text(
                path.read_text(encoding="ascii") + "Fallback: HEARTBEAT_OK\n",
                encoding="ascii",
            )
            with self.assertRaisesRegex(
                audit_module.AuditError, "forbidden-fragment"
            ):
                audit_module.audit_bundle(root)

    def test_dubble_transcript_polling_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = self.copy_source(directory_name)
            path = root / "dubble/AGENTS.md"
            path.write_text(
                path.read_text(encoding="ascii") + "Call sessions_history often.\n",
                encoding="ascii",
            )
            with self.assertRaisesRegex(
                audit_module.AuditError, "role-forbidden-fragment"
            ):
                audit_module.audit_bundle(root)

    def test_missing_native_heartbeat_outcome_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = self.copy_source(directory_name)
            path = root / "HEARTBEAT.md"
            text = path.read_text(encoding="ascii").replace(
                "heartbeat_respond", "structured outcome"
            )
            path.write_text(text, encoding="ascii")
            with self.assertRaisesRegex(
                audit_module.AuditError, "missing-required-fragment"
            ):
                audit_module.audit_bundle(root)

    def test_unknown_or_linked_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = self.copy_source(directory_name)
            (root / "legacy.md").symlink_to(root / "AGENTS.md")
            with self.assertRaisesRegex(
                audit_module.AuditError, "bundle-layout-mismatch"
            ):
                audit_module.audit_bundle(root)


if __name__ == "__main__":
    unittest.main()
