#!/usr/bin/env python3

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
PLAYBOOK_PATH = ROOT / "playbooks/agents/openclaw-canary-data-rehearsal.yml"
INVENTORY_PATH = ROOT / "inventory/host_vars/jn-t14s-lin/openclaw.yml"


class CanaryDataRehearsalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.playbook = PLAYBOOK_PATH.read_text(encoding="utf-8")
        cls.inventory = yaml.safe_load(INVENTORY_PATH.read_text(encoding="utf-8"))

    def test_default_mode_is_inert_and_requires_approval(self) -> None:
        self.assertEqual(self.inventory["openclaw_canary_data_mode"], "disabled")
        self.assertIs(self.inventory["openclaw_canary_data_approved"], False)
        self.assertIn("openclaw_canary_data_mode == 'disabled'", self.playbook)
        self.assertIn("openclaw_canary_data_approved", self.playbook)

    def test_handoff_never_controls_production_gateway(self) -> None:
        self.assertNotIn("name: openclaw-gateway.service", self.playbook)
        self.assertNotIn("OPENCLAW_SKIP_CHANNELS=0", self.playbook)
        self.assertNotIn("OPENCLAW_SKIP_CRON=0", self.playbook)
        self.assertIn("productionGatewayChanged': false", self.playbook)

    def test_candidate_build_precedes_canary_stop_and_atomic_swap(self) -> None:
        stage = self.playbook.index(
            "- name: Stage retained data and modern behavior for canary"
        )
        copy_sessions = self.playbook.index(
            "- name: Copy verified OpenClaw sessions into canary candidates"
        )
        stop = self.playbook.index(
            "- name: Stop isolated Gateway before canary data promotion"
        )
        backup = self.playbook.index("- name: Back up existing isolated canary data")
        move_workspace = self.playbook.index(
            "- name: Move current canary workspace to rollback path"
        )
        rewrite = self.playbook.index("- name: Rewrite promoted canary session paths")
        start = self.playbook.index(
            "- name: Start silent isolated Gateway with promoted data"
        )
        transition = self.playbook.index(
            "- name: Plan or apply native OpenClaw session transition"
        )
        self.assertLess(stage, copy_sessions)
        self.assertLess(copy_sessions, stop)
        self.assertLess(stop, backup)
        self.assertLess(backup, move_workspace)
        self.assertLess(move_workspace, rewrite)
        self.assertLess(rewrite, start)
        self.assertLess(start, transition)

    def test_relocation_is_hash_verified_and_replay_quarantined(self) -> None:
        self.assertIn("--source-manifest", self.playbook)
        self.assertIn("--source-index-root", self.playbook)
        self.assertIn("--modernize-derived-snapshots", self.playbook)
        self.assertIn("--modernize-active-runtime-state", self.playbook)
        self.assertIn("--quarantine-delivery-recovery", self.playbook)
        self.assertIn("activeDeliveryRecoveryEntries", self.playbook)
        self.assertIn(
            "Require canary workspace parity with promoted rehearsal",
            self.playbook,
        )
        self.assertIn("workspace-stage.json", self.playbook)

    def test_native_transition_uses_service_identity_without_cli_credentials(
        self,
    ) -> None:
        self.assertIn("openclaw-native-session-transition.py", self.playbook)
        self.assertIn("'/usr/sbin/runuser'", self.playbook)
        self.assertIn("'-u', openclaw_isolated_gateway_user", self.playbook)
        self.assertNotIn("'--token'", self.playbook)
        self.assertNotIn("'--password'", self.playbook)
        self.assertIn("openclaw_canary_data_mode == 'apply'", self.playbook)

    def test_silent_canary_gates_are_checked_before_staging(self) -> None:
        silent = self.playbook.index(
            "- name: Require silent five-agent canary configuration"
        )
        check_boundary = self.playbook.index(
            "- name: Stop OpenClaw canary data rehearsal before mutation in check mode"
        )
        stage = self.playbook.index(
            "- name: Stage retained data and modern behavior for canary"
        )
        self.assertLess(silent, check_boundary)
        self.assertLess(check_boundary, stage)
        self.assertIn("heartbeat.every == '0m'", self.playbook)
        self.assertIn("config.channels is not defined", self.playbook)
        self.assertIn("OPENCLAW_SKIP_CHANNELS=1", self.playbook)
        self.assertIn("OPENCLAW_SKIP_CRON=1", self.playbook)

    def test_rescue_restores_both_prior_data_roots(self) -> None:
        rescue = self.playbook.index("      rescue:")
        tail = self.playbook[rescue:]
        self.assertIn("Restore prior canary sessions from rollback path", tail)
        self.assertIn("Restore prior canary workspace from rollback path", tail)
        self.assertIn("Restore prior isolated canary activity", tail)
        self.assertIn("canary-data-before.tar", self.playbook)

    def test_capacity_gate_includes_state_workspace_and_rollback(self) -> None:
        capacity = self.playbook.index(
            "- name: Require capacity for canary data and rollback"
        )
        stage = self.playbook.index(
            "- name: Stage retained data and modern behavior for canary"
        )
        self.assertLess(capacity, stage)
        self.assertIn("openclaw_canary_data_session_bytes", self.playbook)
        self.assertIn("openclaw_canary_data_workspace_bytes", self.playbook)
        self.assertIn("openclaw_canary_data_rollback_bytes", self.playbook)


if __name__ == "__main__":
    unittest.main()
