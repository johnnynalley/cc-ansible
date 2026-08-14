#!/usr/bin/env python3
"""Regression tests for safe live Hermes runtime convergence."""

from __future__ import annotations

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).parents[2]
PLAYBOOK = ROOT / "playbooks" / "agents" / "hermes-production-runtime.yml"
VARS = ROOT / "inventory" / "group_vars" / "hermes_hosts" / "vars.yml"


class HermesProductionRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.playbook = PLAYBOOK.read_text(encoding="utf-8")
        cls.variables = yaml.safe_load(VARS.read_text(encoding="utf-8"))

    def offset(self, name: str) -> int:
        marker = f"        - name: {name}"
        offset = self.playbook.find(marker)
        if offset < 0:
            offset = self.playbook.find(f"    - name: {name}")
        self.assertGreaterEqual(offset, 0, name)
        return offset

    def test_default_is_inert_and_host_specific(self) -> None:
        self.assertEqual(self.variables["hermes_production_runtime_mode"], "disabled")
        self.assertFalse(self.variables["hermes_production_runtime_approved"])
        self.assertEqual(self.variables["hermes_production_runtime_confirmation"], "")
        self.assertIn("hermes_production_runtime_required_confirmation", self.playbook)
        self.assertIn("inventory_hostname == 'jn-t14s-lin'", self.playbook)
        self.assertIn("ansible.builtin.meta: end_host", self.playbook)
        self.assertNotIn(
            "hermes-production-runtime.yml",
            (ROOT / "site.yml").read_text(encoding="utf-8"),
        )

    def test_backup_and_openclaw_absence_precede_mutation(self) -> None:
        source_gate = self.offset("Require OpenClaw delivery to remain offline")
        backup = self.offset("Back up live Hermes systemd units")
        readers = self.offset("Create credential-free Hermes runtime readers group")
        self.assertLess(source_gate, backup)
        self.assertLess(backup, readers)
        self.assertIn("hermes_production_cutover_rollback_root", self.playbook)
        self.assertIn("check_mode: false", self.playbook[source_gate - 1800:source_gate])
        backup_task = self.playbook[backup:readers]
        self.assertIn("when: not ansible_check_mode", backup_task)

    def test_runtime_group_is_code_only_and_all_profiles_are_readers(self) -> None:
        self.assertEqual(
            self.variables["hermes_runtime_readers_group"],
            "hermes-runtime-readers",
        )
        self.assertIn("append: true", self.playbook)
        self.assertIn("hermes_runtime_readers_group", self.playbook)
        self.assertNotIn("docker.sock", self.playbook)
        self.assertNotIn("group: docker", self.playbook)

    def test_consumers_restart_one_at_a_time_after_import_proof(self) -> None:
        imports = self.offset("Validate Discord imports as every isolated identity")
        astra = self.offset("Restart and verify Astra Discord consumer")
        dubble = self.offset("Restart and verify Dubble Discord consumer")
        self.assertLess(imports, astra)
        self.assertLess(astra, dubble)
        self.assertIn("--imports-only", self.playbook)
        self.assertIn("hermes_shadow_runtime_venv", self.playbook[imports:astra])
        self.assertIn("state: stopped", self.playbook[self.offset(
            "Keep standalone Rigel Gateway stopped and disabled"
        ):astra])

    def test_failure_restores_units_and_consumers(self) -> None:
        rescue = self.playbook.index("      rescue:")
        tail = self.playbook[rescue:]
        self.assertIn("Restore pre-convergence Hermes systemd units", tail)
        self.assertIn("Restore Astra and Dubble consumers", tail)
        self.assertIn("ansible.builtin.fail", tail)

    def test_dry_run_uses_real_read_only_service_state(self) -> None:
        active = self.offset("Require live Hermes consumers and native update timers")
        assertion = self.offset("Require all production Hermes units active")
        health = self.offset("Verify Health receiver remains active")
        health_assert = self.offset("Require Health receiver continuity")
        self.assertIn("check_mode: false", self.playbook[active:assertion])
        self.assertIn("check_mode: false", self.playbook[health:health_assert])

    def test_no_match_journal_scan_is_success_not_probe_noise(self) -> None:
        scan = self.offset("Scan restarted Hermes consumers for adapter failures")
        clean = self.offset("Require clean post-restart Hermes journals")
        task = self.playbook[scan:clean]
        self.assertIn("failed_when: hermes_runtime_failure_scan.rc not in [0, 1]", task)
        self.assertIn("--grep=No adapter", task)
        self.assertIn("check_mode: false", task)


if __name__ == "__main__":
    unittest.main()
