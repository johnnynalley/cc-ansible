#!/usr/bin/env python3
"""Regression tests for the OpenClaw-to-Hermes production transaction."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
PLAYBOOK = ROOT / "playbooks" / "agents" / "hermes-production-cutover.yml"
VARS = ROOT / "inventory" / "group_vars" / "hermes_hosts" / "vars.yml"
SERVICE = ROOT / "templates" / "hermes" / "hermes-gateway.service.j2"


class HermesProductionCutoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.playbook = PLAYBOOK.read_text(encoding="utf-8")
        cls.variables = yaml.safe_load(VARS.read_text(encoding="utf-8"))
        cls.service = SERVICE.read_text(encoding="utf-8")

    def task_offset(self, name: str) -> int:
        marker = f"        - name: {name}"
        offset = self.playbook.find(marker)
        if offset < 0:
            marker = f"    - name: {name}"
            offset = self.playbook.find(marker)
        self.assertGreaterEqual(offset, 0, name)
        return offset

    def test_default_is_inert_and_requires_exact_confirmation(self) -> None:
        self.assertEqual(
            self.variables["hermes_production_cutover_mode"], "disabled"
        )
        self.assertFalse(
            self.variables["hermes_production_cutover_approved"]
        )
        self.assertEqual(
            self.variables["hermes_production_cutover_confirmation"], ""
        )
        self.assertIn("ansible.builtin.meta: end_host", self.playbook)
        self.assertIn(
            "hermes_production_cutover_required_confirmation", self.playbook
        )
        self.assertNotIn("hermes-production-cutover.yml", (ROOT / "site.yml").read_text())

    def test_backup_precedes_source_stop_and_enrollment(self) -> None:
        backup = self.task_offset(
            "Back up production source and target state before cutover"
        )
        stop = self.task_offset("Stop and disable production OpenClaw user gateway")
        enroll = self.task_offset(
            "Enroll existing Discord identities only after source stop proof"
        )
        self.assertLess(backup, stop)
        self.assertLess(stop, enroll)
        self.assertIn("openclaw-delivery-cutover-audit.py", self.playbook)
        self.assertIn("--require-clean", self.playbook)

    def test_recovery_reconciliation_is_exact_opt_in_after_source_stop(self) -> None:
        stop = self.task_offset("Prove OpenClaw delivery consumers are absent")
        reconcile = self.task_offset(
            "Reconcile only explicitly reviewed delivery-recovery records"
        )
        audit = self.task_offset(
            "Prove stopped OpenClaw has no replay-capable delivery state"
        )
        self.assertLess(stop, reconcile)
        self.assertLess(reconcile, audit)
        task = self.playbook[reconcile:audit]
        self.assertIn("hermes_production_cutover_recovery_fingerprints", task)
        self.assertIn("hermes_cutover_reconcile_argv", task)
        self.assertEqual(
            self.variables["hermes_production_cutover_recovery_fingerprints"],
            [],
        )

    def test_break_before_make_and_two_consumer_topology(self) -> None:
        source_stop = self.task_offset(
            "Stop and disable production OpenClaw user gateway"
        )
        astra_start = self.task_offset("Start and enable Astra Discord consumer")
        dubble_start = self.task_offset("Start and enable Dubble Discord consumer")
        self.assertLess(source_stop, astra_start)
        self.assertLess(astra_start, dubble_start)
        rigel = self.playbook[self.task_offset(
            "Keep preserved Rigel gateway stopped and disabled"
        ):]
        self.assertIn("hermes-gateway-rigel.service", rigel)
        self.assertIn("state: stopped", rigel)
        self.assertIn("enabled: false", rigel)
        self.assertNotIn("DISCORD_BOT_TOKEN=", self.playbook)

    def test_rigel_uses_native_no_agent_schedule_and_stays_silent(self) -> None:
        self.assertIn("hermes-rigel-schedule.py", self.playbook)
        self.assertIn("- --no-agent", self.playbook)
        self.assertIn("- every 30m", self.playbook)
        self.assertIn("stdout | length == 0", self.playbook)
        self.assertIn("stderr | length == 0", self.playbook)
        self.assertIn("schedule_display", self.playbook)

    def test_health_is_proven_before_after_and_during_rescue(self) -> None:
        self.assertGreaterEqual(
            self.playbook.count("hermes_production_cutover_health_service"), 3
        )
        self.assertIn("hermes_production_cutover_health_port", self.playbook)
        rescue = self.playbook.index("      rescue:")
        self.assertIn(
            "Restore production OpenClaw user gateway", self.playbook[rescue:]
        )
        self.assertIn("Require source and Health recovery", self.playbook[rescue:])

    def test_native_updates_are_automatic_after_promotion(self) -> None:
        task = self.playbook[self.task_offset(
            "Enable Hermes and Tirith native automatic updates"
        ):]
        self.assertIn("hermes_native_update_timer", task)
        self.assertIn("hermes_tirith_update_timer", task)
        self.assertIn("state: started", task)
        self.assertIn("enabled: true", task)

    def test_gateway_active_state_requires_discord_runtime_readiness(self) -> None:
        self.assertIn("hermes_discord_runtime_audit_live", self.service)
        self.assertIn("--home={{ hermes_profile.home }}", self.service)
        self.assertIn("--imports-only", self.service)
        self.assertIn("--pid=${MAINPID} --timeout=30", self.service)
        self.assertIn("hermes_shadow_runtime_venv", self.service)
        self.assertIn("SupplementaryGroups={{ hermes_runtime_readers_group }}", self.service)

    def test_gateway_marker_is_neutral_and_legacy_marker_is_retired(self) -> None:
        self.assertEqual(
            self.variables["hermes_gateway_readiness_marker"], ".gateway-ready"
        )
        self.assertIn("hermes_gateway_readiness_marker", self.service)
        self.assertNotIn(".shadow-ready", self.service)


if __name__ == "__main__":
    unittest.main()
