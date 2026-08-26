#!/usr/bin/env python3

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = ROOT / "playbooks/backup-sync/local-restic.yml"
HOST_VARS = ROOT / "inventory/host_vars/jn-t14s-lin/backup.yml"
NAS_VARS = ROOT / "inventory/host_vars/ts440/backup.yml"


class DisasterRecoveryPlaybookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playbook = PLAYBOOK.read_text(encoding="utf-8")
        cls.host_vars = yaml.safe_load(HOST_VARS.read_text(encoding="utf-8"))
        cls.nas_vars = yaml.safe_load(NAS_VARS.read_text(encoding="utf-8"))

    def test_jn_t14s_enables_complete_hermes_disaster_recovery_roots(self):
        self.assertTrue(self.host_vars["hermes_disaster_recovery_enabled"])
        paths = set(self.host_vars["local_restic_backup_paths"])
        self.assertTrue(
            {
                "/home/johnny",
                "/opt/cc-ansible",
                "/var/lib/hermes",
                "/var/lib/hermes-automation",
                "/etc/hermes",
                "/var/backups/hermes-disaster-recovery/current",
            }.issubset(paths)
        )
        self.assertNotIn("/opt/qdrant/storage", paths)

    def test_large_rebuildable_and_duplicate_trees_are_excluded(self):
        excludes = set(self.host_vars["local_restic_excludes_extra"])
        self.assertTrue(
            {
                "/var/lib/hermes/openclaw-evidence/merged",
                "/var/lib/hermes/astra/workspaces/cc-ansible",
                "/var/lib/hermes/astra/.local/share/containers",
                "/var/lib/hermes/bootstrap",
            }.issubset(excludes)
        )

    def test_application_consistent_stage_precedes_restic_backup(self):
        stage = self.playbook.index(
            "{{ hermes_disaster_recovery_script }} stage"
        )
        verify = self.playbook.index(
            "{{ hermes_disaster_recovery_script }} verify"
        )
        backup = self.playbook.index("restic --cleanup-cache")
        self.assertLess(stage, verify)
        self.assertLess(verify, backup)
        self.assertIn("--result failed --phase restic", self.playbook)
        self.assertIn("--result ok --phase complete", self.playbook)

    def test_helper_is_root_private_and_only_installed_when_enabled(self):
        self.assertIn(
            "src: ../../scripts/agents/hermes-disaster-recovery-stage.py",
            self.playbook,
        )
        self.assertIn('mode: "0700"', self.playbook)
        self.assertGreaterEqual(
            self.playbook.count(
                "when: hermes_disaster_recovery_enabled | default(false)"
            ),
            2,
        )

    def test_ts440_independently_monitors_complete_hermes_snapshot(self):
        monitors = self.nas_vars["local_restic_freshness_monitors"]
        self.assertEqual(len(monitors), 1)
        monitor = monitors[0]
        self.assertEqual(monitor["source_host"], "jn-t14s-lin")
        self.assertEqual(monitor["max_age_seconds"], 10800)
        self.assertIn(
            "/var/backups/hermes-disaster-recovery/current",
            monitor["required_paths"],
        )
        self.assertIn(
            "src: ../../scripts/storage/restic-snapshot-freshness.py",
            self.playbook,
        )
        self.assertIn("restic-snapshot-freshness@.timer", self.playbook)
        self.assertIn("APPRISE_ENDPOINT={{ apprise_endpoint | quote }}", self.playbook)
        self.assertIn("User=johnny", self.playbook)
        self.assertIn("CapabilityBoundingSet=", self.playbook)
        self.assertIn("Remove obsolete nested Restic freshness config root", self.playbook)


if __name__ == "__main__":
    unittest.main()
