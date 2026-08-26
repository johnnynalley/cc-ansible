#!/usr/bin/env python3

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name("restic-snapshot-freshness.py")
PLAYBOOK = Path(__file__).parents[2] / "playbooks/backup-sync/local-restic.yml"
SPEC = importlib.util.spec_from_file_location("restic_snapshot_freshness", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ResticSnapshotFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 25, 3, 0, tzinfo=timezone.utc)
        self.snapshot = {
            "hostname": "jn-t14s-lin",
            "id": "abcdef1234567890",
            "paths": [
                "/etc/hermes",
                "/var/backups/hermes-disaster-recovery/current",
            ],
            "time": (self.now - timedelta(minutes=30)).isoformat(),
        }

    def evaluate(self, snapshots):
        return MODULE.evaluate_snapshots(
            snapshots,
            host="jn-t14s-lin",
            max_age_seconds=10800,
            required_paths=["/var/backups/hermes-disaster-recovery/current"],
            now=self.now,
        )

    def test_accepts_recent_snapshot_with_required_recovery_stage(self):
        result = self.evaluate([self.snapshot])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["snapshotId"], "abcdef12")
        self.assertEqual(result["ageSeconds"], 1800)

    def test_rejects_stale_snapshot(self):
        self.snapshot["time"] = (self.now - timedelta(hours=4)).isoformat()
        with self.assertRaisesRegex(MODULE.FreshnessError, "snapshot-stale"):
            self.evaluate([self.snapshot])

    def test_rejects_snapshot_without_recovery_stage(self):
        self.snapshot["paths"] = ["/etc/hermes"]
        with self.assertRaisesRegex(
            MODULE.FreshnessError, "snapshot-required-path-missing"
        ):
            self.evaluate([self.snapshot])

    def test_rejects_missing_host_snapshot(self):
        self.snapshot["hostname"] = "other-host"
        with self.assertRaisesRegex(MODULE.FreshnessError, "snapshot-host-missing"):
            self.evaluate([self.snapshot])

    def test_rejects_materially_future_snapshot(self):
        self.snapshot["time"] = (self.now + timedelta(minutes=10)).isoformat()
        with self.assertRaisesRegex(
            MODULE.FreshnessError, "snapshot-time-in-future"
        ):
            self.evaluate([self.snapshot])

    def test_reports_restic_command_timeout_without_command_output(self):
        with mock.patch.object(
            MODULE.subprocess,
            "run",
            side_effect=MODULE.subprocess.TimeoutExpired("restic", 120),
        ):
            with self.assertRaisesRegex(
                MODULE.FreshnessError, "restic-command-timeout"
            ):
                MODULE.load_snapshots("/usr/bin/restic", "jn-t14s-lin")

    def test_reads_snapshots_without_repository_write_lock(self):
        completed = MODULE.subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr=""
        )
        with mock.patch.object(MODULE.subprocess, "run", return_value=completed) as run:
            self.assertEqual(
                MODULE.load_snapshots("/usr/bin/restic", "jn-t14s-lin"), []
            )
        self.assertEqual(
            run.call_args.args[0],
            [
                "/usr/bin/restic",
                "--no-lock",
                "snapshots",
                "--json",
                "--latest",
                "1",
                "--host",
                "jn-t14s-lin",
            ],
        )

    def test_playbook_repairs_only_known_legacy_state_markers(self):
        playbook = PLAYBOOK.read_text(encoding="utf-8")
        self.assertIn("local_restic_freshness_state_markers:", playbook)
        self.assertIn("- unhealthy", playbook)
        self.assertIn("- last-alert", playbook)
        self.assertIn(
            "Inspect known Restic freshness monitor state markers", playbook
        )
        self.assertIn(
            "Reject unsafe Restic freshness monitor state markers", playbook
        )
        self.assertIn(
            "Normalize existing Restic freshness monitor state marker ownership",
            playbook,
        )
        self.assertIn("not item.stat.exists or item.stat.isreg | default(false)", playbook)
        self.assertIn("not (item.stat.islnk | default(false))", playbook)
        state_marker_task = playbook.split(
            "- name: Normalize existing Restic freshness monitor state marker ownership",
            1,
        )[1].split("- name: Create private Restic freshness monitor environments", 1)[0]
        self.assertNotIn("recurse:", state_marker_task)

    def test_playbook_safely_normalizes_only_dedicated_restic_cache_trees(self):
        playbook = PLAYBOOK.read_text(encoding="utf-8")
        self.assertIn("Inspect dedicated Restic freshness cache trees", playbook)
        self.assertIn("Reject unsafe Restic freshness cache tree entries", playbook)
        self.assertIn("file_type: any", playbook)
        self.assertIn("not (item.1.islnk | default(false))", playbook)
        self.assertIn("item.1.isreg | default(false) or item.1.isdir | default(false)", playbook)
        cache_task = playbook.split(
            "- name: Normalize dedicated Restic freshness cache ownership", 1
        )[1].split("- name: Inspect known Restic freshness monitor state markers", 1)[0]
        self.assertIn(
            'path: "{{ local_restic_freshness_cache_root }}/{{ item.name }}"',
            cache_task,
        )
        self.assertIn("recurse: true", cache_task)
        self.assertNotIn("state: absent", cache_task)


if __name__ == "__main__":
    unittest.main()
