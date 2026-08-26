#!/usr/bin/env python3
"""Structural regression tests for ZFS-backed live rollback exports."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]


class NfsLiveRollbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.variables = yaml.safe_load(
            (ROOT / "inventory/group_vars/nas_server/nfs.yml").read_text()
        )
        self.tasks = (ROOT / "tasks/nfs-server.yml").read_text()
        self.client_tasks = (ROOT / "tasks/nfs-client.yml").read_text()
        self.backup = (
            ROOT / "scripts/storage/live-rollback-backup"
        ).read_text()

    def test_live_rollback_export_requires_zfs_before_bind(self) -> None:
        export = next(
            item
            for item in self.variables["nfs_exports"]
            if item["name"] == "live-rollbacks"
        )
        self.assertEqual(
            export["bind_source"],
            "/srv/nas-zfs/backups/live-rollbacks",
        )
        self.assertEqual(
            export["bind_source_name"],
            "nas_zfs/backups/live-rollbacks",
        )
        self.assertEqual(export["bind_source_fstype"], "zfs")
        self.assertEqual(export["bind_requires_unit"], "zfs-mount.service")
        self.assertIn("x-systemd.after=zfs-mount.service", export["bind_opts"])
        self.assertIn("x-systemd.requires=zfs-mount.service", export["bind_opts"])
        self.assertEqual(export["bind_source_marker"], ".live-rollback-origin")

    def test_server_rejects_wrong_backing_and_missing_exports(self) -> None:
        for required in (
            "Require intended NFS export source filesystems",
            "Reject stale NFS export bind mounts",
            "ExecStartPre=/usr/bin/test",
            "Reconcile active NFS exports",
            "Require every configured NFS export to be active",
        ):
            self.assertIn(required, self.tasks)

    def test_backup_helper_fails_closed_without_origin_marker(self) -> None:
        self.assertIn(
            "findmnt -n --types nfs,nfs4 -o FSTYPE --target",
            self.backup,
        )
        self.assertIn(".live-rollback-origin", self.backup)
        self.assertIn(
            "dataset=nas_zfs/backups/live-rollbacks",
            self.backup,
        )

    def test_clients_reconnect_stale_mounts_before_directory_management(self) -> None:
        for required in (
            "Probe NFS mount point readability",
            "Resolve generated units for stale NFS mounts",
            "Reconnect stale NFS mounts",
            "Verify recovered NFS mount points",
            "Create missing mount point directories",
        ):
            self.assertIn(required, self.client_tasks)
        self.assertIn("'Stale file handle' in item.stderr", self.client_tasks)
        self.assertLess(
            self.client_tasks.index("Reconnect stale NFS mounts"),
            self.client_tasks.index("Create missing mount point directories"),
        )


if __name__ == "__main__":
    unittest.main()
