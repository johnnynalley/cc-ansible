#!/usr/bin/env python3
"""Regression tests for the bounded Hermes parity maintenance window."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]
PLAYBOOK = ROOT / "playbooks/agents/hermes-parity-offline-window.yml"
VARS = ROOT / "inventory/group_vars/hermes_hosts/vars.yml"


class HermesParityOfflineWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.playbook = PLAYBOOK.read_text(encoding="utf-8")
        cls.variables = yaml.safe_load(VARS.read_text(encoding="utf-8"))

    def test_default_is_inert_and_exactly_gated(self) -> None:
        self.assertEqual(self.variables["hermes_parity_offline_mode"], "disabled")
        self.assertFalse(self.variables["hermes_parity_offline_approved"])
        self.assertIn("hermes_parity_offline_required_confirmation", self.playbook)
        self.assertIn("inventory_hostname == 'jn-t14s-lin'", self.playbook)
        self.assertIn("ansible.builtin.meta: end_host", self.playbook)

    def test_stop_is_native_planned_and_recorded(self) -> None:
        self.assertIn("hermes-planned-stop-marker.yml", self.playbook)
        self.assertIn("gateway\n          - stop\n          - --system", self.playbook)
        self.assertIn("Clear stopped Gateway failure state for maintenance", self.playbook)
        self.assertIn("- reset-failed", self.playbook)
        self.assertIn("service-state.json", self.playbook)
        self.assertIn("hermes_parity_offline_rollback_root", self.playbook)
        self.assertIn("hermes_production_consumer_profiles", self.playbook)

    def test_resume_validates_config_and_uses_native_lifecycle(self) -> None:
        self.assertIn("Validate merged production configs before recovery", self.playbook)
        self.assertIn("gateway\n          - start\n          - --system", self.playbook)
        self.assertIn("item.stdout == 'active'", self.playbook)
        self.assertNotIn("systemctl\n          - restart", self.playbook)


if __name__ == "__main__":
    unittest.main()
