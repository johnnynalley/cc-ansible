#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("openclaw-workspace-stage.py")
SPEC = importlib.util.spec_from_file_location("openclaw_workspace_stage", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class WorkspaceStageTests(unittest.TestCase):
    def _policy(self, root: Path, extra_rules: list[dict] | None = None) -> Path:
        path = root / "policy.json"
        rules = [
            {
                "id": "retain-data",
                "scope": "tree",
                "pattern": "data",
                "disposition": "retain",
                "target": "data",
                "ownerClass": "executor-writable",
                "reason": "test data",
            },
            {
                "id": "retain-policy",
                "scope": "exact",
                "pattern": "AUTH.yaml",
                "disposition": "retain",
                "target": "dubble/AUTH.yaml",
                "ownerClass": "operator-readonly",
                "sensitivity": "authorization-policy",
                "reason": "test policy",
            },
            {
                "id": "replace-bootstrap",
                "scope": "exact",
                "pattern": "AGENTS.md",
                "disposition": "replace",
                "reason": "modern overlay",
            },
            {
                "id": "archive-other",
                "scope": "tree",
                "pattern": "archive",
                "disposition": "archive",
                "reason": "archive only",
            },
        ]
        rules.extend(extra_rules or [])
        path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "archiveContract": "keep the complete source archive",
                    "rules": rules,
                }
            ),
            encoding="utf-8",
        )
        return path

    def _fixture(self, root: Path) -> tuple[Path, Path, Path]:
        source = root / "source"
        overlay = root / "overlay"
        target = root / "target"
        (source / "data").mkdir(parents=True)
        (source / "archive").mkdir()
        overlay.mkdir()
        target.mkdir()
        (source / "data" / "state.json").write_text("retained\n", encoding="utf-8")
        (source / "archive" / "old.txt").write_text("old\n", encoding="utf-8")
        (source / "AUTH.yaml").write_text("allow: owner\n", encoding="utf-8")
        (source / "AGENTS.md").write_text("legacy\n", encoding="utf-8")
        (overlay / "AGENTS.md").write_text("modern\n", encoding="utf-8")
        return source, overlay, target

    def test_stage_copies_only_retained_data_and_modern_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, overlay, target = self._fixture(root)
            policy = self._policy(root)
            uid = os.getuid()
            gid = os.getgid()

            report = MODULE.stage_workspace(
                source,
                overlay,
                target,
                policy,
                uid,
                gid,
                uid,
                gid,
            )

            self.assertEqual((target / "AGENTS.md").read_text(), "modern\n")
            self.assertEqual((target / "data" / "state.json").read_text(), "retained\n")
            self.assertEqual(
                (target / "dubble" / "AUTH.yaml").read_text(), "allow: owner\n"
            )
            self.assertFalse((target / "archive").exists())
            self.assertEqual(report["summary"]["files"], 3)
            self.assertEqual(
                report["summary"]["filesByOrigin"],
                {"modern-overlay": 1, "retained": 2},
            )
            self.assertTrue(all(len(row["sha256"]) == 64 for row in report["files"]))
            self.assertEqual((target / "AGENTS.md").stat().st_mode & 0o777, 0o640)
            self.assertEqual(
                (target / "data" / "state.json").stat().st_mode & 0o777,
                0o640,
            )

    def test_plan_is_metadata_only_and_does_not_require_a_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, overlay, target = self._fixture(root)
            target.rmdir()

            report = MODULE.plan_workspace(source, overlay, self._policy(root))

            self.assertEqual(report["mode"], "plan")
            self.assertEqual(report["summary"]["plannedFiles"], 3)
            self.assertFalse(target.exists())

    def test_overlay_file_collision_with_retained_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, overlay, target = self._fixture(root)
            (overlay / "data").mkdir()
            (overlay / "data" / "state.json").write_text("collision\n")
            with self.assertRaises(MODULE.WorkspaceStageError):
                MODULE.stage_workspace(
                    source,
                    overlay,
                    target,
                    self._policy(root),
                    os.getuid(),
                    os.getgid(),
                    os.getuid(),
                    os.getgid(),
                )

    def test_readonly_overlay_under_writable_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, overlay, target = self._fixture(root)
            (overlay / "data").mkdir()
            (overlay / "data" / "policy.md").write_text("policy\n")
            with self.assertRaises(MODULE.WorkspaceStageError):
                MODULE.stage_workspace(
                    source,
                    overlay,
                    target,
                    self._policy(root),
                    os.getuid(),
                    os.getgid(),
                    os.getuid(),
                    os.getgid(),
                )

    def test_retained_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, overlay, target = self._fixture(root)
            (source / "data" / "link").symlink_to(source / "archive" / "old.txt")
            with self.assertRaises(MODULE.WorkspaceStageError):
                MODULE.stage_workspace(
                    source,
                    overlay,
                    target,
                    self._policy(root),
                    os.getuid(),
                    os.getgid(),
                    os.getuid(),
                    os.getgid(),
                )

    def test_nonempty_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, overlay, target = self._fixture(root)
            (target / "unexpected").write_text("existing\n")
            with self.assertRaises(MODULE.WorkspaceStageError):
                MODULE.stage_workspace(
                    source,
                    overlay,
                    target,
                    self._policy(root),
                    os.getuid(),
                    os.getgid(),
                    os.getuid(),
                    os.getgid(),
                )

    def test_retained_glob_mapping_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source = root / "source"
            overlay = root / "overlay"
            target = root / "target"
            source.mkdir()
            overlay.mkdir()
            target.mkdir()
            (source / "state.json").write_text("state\n")
            policy = self._policy(
                root,
                [
                    {
                        "id": "retain-glob",
                        "scope": "top-level-glob",
                        "pattern": "*.json",
                        "disposition": "retain",
                        "target": "json",
                        "ownerClass": "executor-writable",
                        "reason": "ambiguous remap",
                    }
                ],
            )
            with self.assertRaises(MODULE.WorkspaceStageError):
                MODULE.stage_workspace(
                    source,
                    overlay,
                    target,
                    policy,
                    os.getuid(),
                    os.getgid(),
                    os.getuid(),
                    os.getgid(),
                )


if __name__ == "__main__":
    unittest.main()
