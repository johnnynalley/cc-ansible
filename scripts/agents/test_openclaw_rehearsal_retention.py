#!/usr/bin/env python3
"""Tests for bounded OpenClaw rehearsal-generation retention."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).with_name("openclaw-rehearsal-retention.py")
SPEC = importlib.util.spec_from_file_location(
    "openclaw_rehearsal_retention", MODULE_PATH
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RehearsalRetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state_root = self.root / "state"
        self.workspace_root = self.root / "workspace"
        self.backup_root = self.root / "backups"
        self.state_generations = self.state_root / "generations"
        self.workspace_generations = self.workspace_root / "generations"
        self.state_generations.mkdir(parents=True)
        self.workspace_generations.mkdir(parents=True)
        self.backup_root.mkdir()
        for path in (
            self.state_root,
            self.workspace_root,
            self.state_generations,
            self.workspace_generations,
        ):
            path.chmod(0o750)
        self.backup_root.chmod(0o700)
        self.current_stamp = "20260812T190549Z"
        self.previous_stamp = "20260810T083108Z"
        self.old_stamp = "20260810T082537Z"
        self.partial_stamp = "20260812T181233Z"
        for stamp in (self.current_stamp, self.previous_stamp, self.old_stamp):
            self.create_generation(self.state_generations, stamp, "state")
            self.create_generation(self.workspace_generations, stamp, "workspace")
        self.create_generation(
            self.workspace_generations, self.partial_stamp, "workspace"
        )
        (self.state_root / "current").symlink_to(
            self.state_generations / self.current_stamp / "state"
        )
        (self.workspace_root / "current").symlink_to(
            self.workspace_generations / self.current_stamp / "workspace"
        )
        self.write_rollback_archive()
        uid = os.getuid()
        self.policy = MODULE.FamilyPolicy(
            name="test",
            roots=(
                MODULE.RootSpec(
                    "state",
                    self.state_generations,
                    self.state_root / "current",
                    ("state",),
                ),
                MODULE.RootSpec(
                    "workspace",
                    self.workspace_generations,
                    self.workspace_root / "current",
                    ("workspace",),
                ),
            ),
            backup_root=self.backup_root,
            control_uid=uid,
            content_uids=(uid,),
            content_gids=(os.getgid(),),
            quiescent_uids=(),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def create_generation(root: Path, stamp: str, suffix: str) -> None:
        generation = root / stamp
        content = generation / suffix
        content.mkdir(parents=True)
        generation.chmod(0o750)
        content.chmod(0o750)
        evidence = content / "evidence.txt"
        evidence.write_text(stamp + "\n", encoding="utf-8")
        evidence.chmod(0o640)

    def write_rollback_archive(self, target_stamp: str | None = None) -> None:
        target_stamp = target_stamp or self.previous_stamp
        backup = self.backup_root / self.current_stamp
        backup.mkdir(exist_ok=True)
        backup.chmod(0o700)
        with tarfile.open(backup / "rollback.tar.gz", mode="w:gz") as archive:
            for selector, target in (
                (
                    self.state_root / "current",
                    self.state_generations / target_stamp / "state",
                ),
                (
                    self.workspace_root / "current",
                    self.workspace_generations / target_stamp / "workspace",
                ),
            ):
                member = tarfile.TarInfo(selector.as_posix().lstrip("/"))
                member.type = tarfile.SYMTYPE
                member.linkname = str(target)
                member.mode = 0o777
                archive.addfile(member)
        # Historic rehearsal archives are 0644 but remain confidential because
        # both enclosing backup directories are root-only 0700.
        (backup / "rollback.tar.gz").chmod(0o644)

    def test_plan_keeps_selected_and_current_rollback_target(self) -> None:
        plan = MODULE.build_plan(self.policy)
        self.assertEqual(plan["selectedStamp"], self.current_stamp)
        self.assertEqual(plan["rollbackStamp"], self.previous_stamp)
        self.assertEqual(plan["keepStamps"], [self.previous_stamp, self.current_stamp])
        self.assertEqual(plan["deleteStamps"], [self.old_stamp, self.partial_stamp])
        self.assertGreater(plan["estimatedReclaimBytes"], 0)
        partial = next(
            candidate
            for candidate in plan["candidates"]
            if candidate["stamp"] == self.partial_stamp
        )
        self.assertEqual([path["label"] for path in partial["paths"]], ["workspace"])

    def test_apply_requires_exact_plan_and_removes_only_superseded_data(self) -> None:
        plan = MODULE.build_plan(self.policy)
        plan_path = self.root / "retention-plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        plan_path.chmod(0o600)
        result = MODULE.apply_plan(self.policy, plan_path)
        self.assertEqual(result["removedGenerationCount"], 2)
        self.assertEqual(result["removedPathCount"], 3)
        for stamp in (self.current_stamp, self.previous_stamp):
            self.assertTrue((self.state_generations / stamp).is_dir())
            self.assertTrue((self.workspace_generations / stamp).is_dir())
        self.assertFalse((self.state_generations / self.old_stamp).exists())
        self.assertFalse((self.workspace_generations / self.old_stamp).exists())
        self.assertFalse((self.workspace_generations / self.partial_stamp).exists())
        self.assertTrue((self.backup_root / self.current_stamp).is_dir())

    def test_apply_rejects_metadata_drift(self) -> None:
        plan = MODULE.build_plan(self.policy)
        plan_path = self.root / "retention-plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        plan_path.chmod(0o600)
        drift = self.state_generations / self.old_stamp / "state" / "new.txt"
        drift.write_text("drift\n", encoding="utf-8")
        drift.chmod(0o640)
        with self.assertRaisesRegex(
            MODULE.RehearsalRetentionError, "no longer matches"
        ):
            MODULE.apply_plan(self.policy, plan_path)

    def test_plan_accepts_trusted_group_writable_failed_generation(self) -> None:
        writable = self.state_generations / self.old_stamp / "state" / "writable"
        writable.mkdir()
        writable.chmod(0o770)
        plan = MODULE.build_plan(self.policy)
        candidate = next(
            candidate
            for candidate in plan["candidates"]
            if candidate["stamp"] == self.old_stamp
        )
        state = next(path for path in candidate["paths"] if path["label"] == "state")
        self.assertEqual(state["groupWritableEntryCount"], 1)

    def test_plan_rejects_world_writable_generation_content(self) -> None:
        writable = self.state_generations / self.old_stamp / "state" / "writable"
        writable.mkdir()
        writable.chmod(0o777)
        with self.assertRaisesRegex(MODULE.RehearsalRetentionError, "world writable"):
            MODULE.build_plan(self.policy)

    def test_plan_rejects_live_generation_writer_identity(self) -> None:
        policy = MODULE.FamilyPolicy(
            name=self.policy.name,
            roots=self.policy.roots,
            backup_root=self.policy.backup_root,
            control_uid=self.policy.control_uid,
            content_uids=self.policy.content_uids,
            content_gids=self.policy.content_gids,
            quiescent_uids=(os.getuid(),),
        )
        with self.assertRaisesRegex(
            MODULE.RehearsalRetentionError, "writer identity has a live process"
        ):
            MODULE.build_plan(policy)

    def test_plan_requires_control_owner_for_retained_generation(self) -> None:
        selected = self.state_generations / self.current_stamp
        original_lstat = Path.lstat
        alternate_uid = os.getuid() + 1

        def lstat_with_alternate_selected_owner(path: Path) -> os.stat_result:
            metadata = original_lstat(path)
            if path == selected:
                values = list(metadata)
                values[4] = alternate_uid
                return os.stat_result(values)
            return metadata

        policy = MODULE.FamilyPolicy(
            name=self.policy.name,
            roots=self.policy.roots,
            backup_root=self.policy.backup_root,
            control_uid=self.policy.control_uid,
            content_uids=(*self.policy.content_uids, alternate_uid),
            content_gids=self.policy.content_gids,
            quiescent_uids=(),
        )
        with mock.patch.object(Path, "lstat", lstat_with_alternate_selected_owner):
            with self.assertRaisesRegex(
                MODULE.RehearsalRetentionError,
                "state retained generation has an unexpected owner",
            ):
                MODULE.build_plan(policy)

    def test_rejects_selector_disagreement(self) -> None:
        (self.workspace_root / "current").unlink()
        (self.workspace_root / "current").symlink_to(
            self.workspace_generations / self.previous_stamp / "workspace"
        )
        with self.assertRaisesRegex(
            MODULE.RehearsalRetentionError, "selectors disagree"
        ):
            MODULE.build_plan(self.policy)

    def test_apply_removes_symlink_without_following_external_target(self) -> None:
        outside = self.root / "outside.txt"
        outside.write_text("preserve\n", encoding="utf-8")
        link = self.state_generations / self.old_stamp / "state" / "external-link"
        link.symlink_to(outside)
        plan = MODULE.build_plan(self.policy)
        plan_path = self.root / "retention-plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        plan_path.chmod(0o600)
        MODULE.apply_plan(self.policy, plan_path)
        self.assertTrue(outside.is_file())
        self.assertEqual(outside.read_text(encoding="utf-8"), "preserve\n")
        self.assertFalse(link.exists())

    def test_plan_requires_symlink_safe_recursive_removal(self) -> None:
        with mock.patch.object(MODULE.shutil.rmtree, "avoids_symlink_attacks", False):
            with self.assertRaisesRegex(
                MODULE.RehearsalRetentionError, "lacks symlink-safe"
            ):
                MODULE.build_plan(self.policy)

    def test_rejects_additional_generation_selector(self) -> None:
        (self.state_root / ".current-stale").symlink_to(
            self.state_generations / self.old_stamp / "state"
        )
        with self.assertRaisesRegex(
            MODULE.RehearsalRetentionError, "additional generation selector"
        ):
            MODULE.build_plan(self.policy)

    def test_rejects_unclassified_generation_entry(self) -> None:
        (self.state_generations / "manual-copy").mkdir()
        with self.assertRaisesRegex(
            MODULE.RehearsalRetentionError, "unclassified entry"
        ):
            MODULE.build_plan(self.policy)

    def test_rejects_readable_backup_parent_even_for_root_owned_archive(self) -> None:
        self.backup_root.chmod(0o750)
        with self.assertRaisesRegex(
            MODULE.RehearsalRetentionError, "backup root must be owner-only"
        ):
            MODULE.build_plan(self.policy)

    def test_rejects_rollback_target_outside_generation_root(self) -> None:
        archive = self.backup_root / self.current_stamp / "rollback.tar.gz"
        archive.unlink()
        self.write_rollback_archive(target_stamp="../../escape")
        with self.assertRaisesRegex(
            MODULE.RehearsalRetentionError, "outside its generation root"
        ):
            MODULE.build_plan(self.policy)


if __name__ == "__main__":
    unittest.main()
