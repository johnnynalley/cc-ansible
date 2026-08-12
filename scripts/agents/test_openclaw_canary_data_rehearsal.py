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
            "openclaw_canary_data_source_manifest.summary.activeDeliveryRecoveryEntries is defined",
            self.playbook,
        )
        self.assertIn(
            "openclaw_canary_data_source_manifest.summary.activeDeliveryRecoveryEntries | default(-1) | int == 0",
            self.playbook,
        )
        self.assertIn(
            "Require canary workspace parity with promoted rehearsal",
            self.playbook,
        )
        self.assertIn("workspace-stage.json", self.playbook)
        native = self.playbook.index(
            "- name: Plan or apply native OpenClaw session transition"
        )
        preserve = self.playbook.index(
            "- name: Verify native archival preserved canary session artifacts"
        )
        freeze = self.playbook.index("- name: Freeze native transition evidence")
        preservation_gate = self.playbook[preserve:freeze]
        self.assertLess(native, preserve)
        self.assertLess(preserve, freeze)
        self.assertIn("'verify-artifacts'", preservation_gate)
        self.assertIn("artifact-preservation.json", preservation_gate)

    def test_native_transition_uses_service_identity_without_cli_credentials(
        self,
    ) -> None:
        self.assertIn("openclaw-native-session-transition.py", self.playbook)
        self.assertIn("'/usr/sbin/runuser'", self.playbook)
        self.assertIn("'-u', openclaw_isolated_gateway_user", self.playbook)
        self.assertNotIn("'--token'", self.playbook)
        self.assertNotIn("'--password'", self.playbook)
        self.assertIn("openclaw_canary_data_mode == 'apply'", self.playbook)
        transition = self.playbook.index(
            "- name: Plan or apply native OpenClaw session transition"
        )
        transition_assertion = self.playbook.index(
            "- name: Require successful native OpenClaw session transition"
        )
        native_call = self.playbook[transition:transition_assertion]
        self.assertIn(
            "'--openclaw', openclaw_canary_data_runtime_selectors.results[1].stdout",
            native_call,
        )
        self.assertNotIn(
            "'--openclaw', openclaw_isolated_gateway_runtime_dir + '/bin/openclaw'",
            native_call,
        )
        self.assertNotIn("no_log: true", native_call)

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

    def test_runtime_preflight_requires_canonical_cli_and_service_execution(
        self,
    ) -> None:
        resolve = self.playbook.index(
            "- name: Resolve selected immutable OpenClaw runtime and CLI"
        )
        execute = self.playbook.index(
            "- name: Prove isolated Gateway identity can execute selected OpenClaw CLI"
        )
        stage = self.playbook.index(
            "- name: Stage retained data and modern behavior for canary"
        )
        runtime_preflight = self.playbook[resolve:stage]
        self.assertIn("/lib/node_modules/openclaw/openclaw.mjs", self.playbook)
        self.assertIn("- /usr/sbin/runuser", runtime_preflight)
        self.assertIn("- --version", runtime_preflight)
        self.assertLess(resolve, execute)
        self.assertLess(execute, stage)

    def test_deployed_helpers_include_local_import_dependencies(self) -> None:
        install = self.playbook.index(
            "- name: Install OpenClaw canary data migration helpers"
        )
        smoke = self.playbook.index(
            "- name: Prove deployed OpenClaw canary data helpers load"
        )
        inputs = self.playbook.index(
            "- name: Create protected OpenClaw migration input paths"
        )
        deployed_helpers = self.playbook[install:inputs]
        self.assertIn("- openclaw-workspace-stage.py", deployed_helpers)
        self.assertIn("- openclaw-workspace-inventory.py", deployed_helpers)
        self.assertIn("- openclaw-workspace-manifest-parity.py", deployed_helpers)
        self.assertIn("- openclaw-native-session-transition.py", deployed_helpers)
        self.assertIn("- openclaw-session-transition.py", deployed_helpers)
        self.assertIn("- --help", deployed_helpers)
        self.assertLess(install, smoke)
        self.assertLess(smoke, inputs)

    def test_workspace_parity_allows_only_classified_mutable_drift(self) -> None:
        parity = self.playbook.index(
            "- name: Require canary workspace parity with promoted rehearsal"
        )
        ownership = self.playbook.index(
            "- name: Set staged canary workspace root access"
        )
        parity_gate = self.playbook[parity:ownership]
        self.assertIn("openclaw-workspace-manifest-parity.py", self.playbook)
        self.assertIn("- --baseline", parity_gate)
        self.assertIn("- --candidate", parity_gate)
        self.assertIn("workspace-parity.json", parity_gate)
        self.assertNotIn("/usr/bin/cmp", parity_gate)

    def test_workspace_ownership_preserves_behavior_and_data_classes(self) -> None:
        self.assertEqual(
            self.inventory["openclaw_isolated_workspace_group"],
            "openclaw-workspace",
        )
        self.assertEqual(
            self.inventory["openclaw_isolated_gateway_supplementary_groups"],
            ["openclaw-workspace"],
        )
        self.assertEqual(
            self.inventory["openclaw_isolated_codex_supplementary_groups"],
            ["openclaw-workspace"],
        )
        self.assertIn("Set staged canary workspace root access", self.playbook)
        self.assertIn(
            "item.stat.pw_name in ['root', openclaw_isolated_codex_user]", self.playbook
        )
        self.assertIn(
            "operator-read-only or Executor-writable ownership classes",
            self.playbook,
        )

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
