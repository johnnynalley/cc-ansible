#!/usr/bin/env python3

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name("arr_zero_score_cf_cleanup.py")
SPEC = importlib.util.spec_from_file_location("arr_zero_score_cf_cleanup", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ZeroScoreCustomFormatCleanupTests(unittest.TestCase):
    def test_allows_named_zero_score_non_rename_format(self) -> None:
        plan = MODULE.cleanup_plan(
            [{"id": 2, "name": "H.265", "includeCustomFormatWhenRenaming": False}],
            [{"id": 1, "name": "movies", "formatItems": [{"format": 2, "score": 0}]}],
            ["H.265"],
        )
        self.assertEqual(plan[0]["id"], 2)

    def test_rejects_nonzero_score(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "refusing scored"):
            MODULE.cleanup_plan(
                [{"id": 2, "name": "H.265", "includeCustomFormatWhenRenaming": False}],
                [{"id": 1, "name": "movies", "formatItems": [{"format": 2, "score": 1}]}],
                ["H.265"],
            )

    def test_rejects_rename_format(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "refusing rename"):
            MODULE.cleanup_plan(
                [{"id": 2, "name": "H.265", "includeCustomFormatWhenRenaming": True}],
                [],
                ["H.265"],
            )

    def test_verifies_native_delete_removed_definition_and_profile_reference(self) -> None:
        MODULE.verify_removed(
            [{"id": 24, "name": "x265 (HD)"}],
            [{"id": 1, "name": "movies", "formatItems": [{"format": 24, "score": 5000}]}],
            {2},
            {"H.265"},
        )

    def test_rejects_lingering_deleted_format_definition(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "did not converge"):
            MODULE.verify_removed(
                [{"id": 2, "name": "H.265"}],
                [],
                {2},
                {"H.265"},
            )

    def test_rejects_lingering_profile_reference(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "remains in profiles"):
            MODULE.verify_removed(
                [],
                [{"id": 1, "name": "movies", "formatItems": [{"format": 2, "score": 0}]}],
                {2},
                {"H.265"},
            )

    def test_apply_requires_nfs_live_rollback_mount(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            mounts = Path(directory) / "mounts"
            mounts.write_text(
                "nas-zfs:/backups /srv/live-rollbacks nfs4 rw 0 0\n",
                encoding="utf-8",
            )
            MODULE.ensure_offhost_backup_root(
                Path("/srv/live-rollbacks/docker-vm/arr-policy"),
                mounts_path=mounts,
            )
            mounts.write_text(
                "/dev/sda2 /srv/live-rollbacks ext4 rw 0 0\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "not an NFS mount"):
                MODULE.ensure_offhost_backup_root(
                    Path("/srv/live-rollbacks/docker-vm/arr-policy"),
                    mounts_path=mounts,
                )

    def test_backup_root_rejects_path_traversal(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "without traversal"):
            MODULE.ensure_offhost_backup_root(
                Path("/srv/live-rollbacks/../local-disk"),
            )

    def test_backup_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            backup_dir = Path(directory) / "backup"
            MODULE.write_backup(backup_dir, [{"id": 2}], [{"id": 1}])
            self.assertEqual(os.stat(backup_dir).st_mode & 0o777, 0o700)
            self.assertEqual(
                os.stat(backup_dir / "custom-formats.json").st_mode & 0o777,
                0o600,
            )
            self.assertEqual(
                os.stat(backup_dir / "quality-profiles.json").st_mode & 0o777,
                0o600,
            )

    def test_dry_run_does_not_create_backup(self) -> None:
        custom_formats = [
            {"id": 2, "name": "H.265", "includeCustomFormatWhenRenaming": False}
        ]
        profiles = [{"id": 1, "name": "movies", "formatItems": []}]
        output = io.StringIO()
        with (
            mock.patch.object(sys, "argv", [str(SCRIPT), "--app", "radarr", "--name", "H.265"]),
            mock.patch.object(MODULE, "read_api_key", return_value="secret"),
            mock.patch.object(
                MODULE,
                "request_json",
                side_effect=[custom_formats, profiles],
            ),
            mock.patch.object(MODULE, "write_backup") as write_backup,
            mock.patch.object(MODULE, "ensure_offhost_backup_root") as ensure_backup,
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(MODULE.main(), 0)

        write_backup.assert_not_called()
        ensure_backup.assert_not_called()
        self.assertIsNone(json.loads(output.getvalue())["backup_dir"])


if __name__ == "__main__":
    unittest.main()
