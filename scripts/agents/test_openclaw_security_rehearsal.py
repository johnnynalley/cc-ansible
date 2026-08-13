#!/usr/bin/env python3

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
PLAYBOOK_PATH = ROOT / "playbooks/agents/openclaw-security-rehearsal.yml"
INVENTORY_PATH = ROOT / "inventory/host_vars/jn-t14s-lin/openclaw.yml"
CODEX_UNIT_PATH = ROOT / "templates/openclaw/openclaw-isolated-codex.service.j2"
GATEWAY_UNIT_PATH = ROOT / "templates/openclaw/openclaw-isolated-gateway.service.j2"


class SecurityRehearsalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.playbook = PLAYBOOK_PATH.read_text(encoding="utf-8")
        cls.inventory = yaml.safe_load(INVENTORY_PATH.read_text(encoding="utf-8"))
        cls.codex_unit = CODEX_UNIT_PATH.read_text(encoding="utf-8")
        cls.gateway_unit = GATEWAY_UNIT_PATH.read_text(encoding="utf-8")

    def test_default_mode_is_inert_and_requires_approval(self) -> None:
        self.assertEqual(self.inventory["openclaw_security_rehearsal_mode"], "disabled")
        self.assertIs(self.inventory["openclaw_security_rehearsal_approved"], False)
        self.assertIn("openclaw_security_rehearsal_mode == 'disabled'", self.playbook)
        self.assertIn("openclaw_security_rehearsal_approved", self.playbook)

    def test_channel_less_applied_data_handoff_is_required(self) -> None:
        prerequisite = self.playbook.index(
            "- name: Require replay-safe applied OpenClaw data handoff"
        )
        render = self.playbook.index(
            "- name: Render channel-less OpenClaw security configuration"
        )
        self.assertLess(prerequisite, render)
        for assertion in (
            "openclaw_security_rehearsal_data_result.mode == 'apply'",
            "openclaw_security_rehearsal_data_result.channelsEnabled == false",
            "openclaw_security_rehearsal_data_result.cronEnabled == false",
            "openclaw_security_rehearsal_data_result.heartbeatsEnabled == false",
            "openclaw_security_rehearsal_data_result.bootEnabled == false",
        ):
            self.assertIn(assertion, self.playbook)

    def test_prerequisites_are_typed_and_bind_an_immutable_cli(self) -> None:
        inspect = self.playbook.index(
            "- name: Inspect OpenClaw security rehearsal prerequisites"
        )
        handoff = self.playbook.index(
            "- name: Find successful OpenClaw canary data handoffs"
        )
        gate = self.playbook[inspect:handoff]
        self.assertNotIn("map(attribute='stat.isreg')", gate)
        self.assertNotIn("map(attribute='stat.islnk')", gate)
        self.assertEqual(gate.count("expected_kind: regular"), 14)
        self.assertEqual(gate.count("expected_kind: symlink"), 1)
        self.assertNotIn(".canary-validated", gate)
        self.assertIn("openclaw_isolated_gateway_database_file", gate)
        self.assertEqual(
            self.inventory["openclaw_isolated_gateway_runtime_state_dir"],
            "{{ openclaw_isolated_gateway_state_dir }}/state",
        )
        self.assertEqual(
            self.inventory["openclaw_isolated_gateway_database_file"],
            "{{ openclaw_isolated_gateway_runtime_state_dir }}/state/openclaw.sqlite",
        )
        self.assertIn("item.stat.isreg | default(false)", gate)
        self.assertIn("item.stat.islnk | default(false)", gate)
        self.assertIn(
            "- name: Resolve selected immutable OpenClaw security runtime and CLI",
            gate,
        )
        self.assertIn("--canonicalize-existing", gate)
        self.assertIn("/lib/node_modules/openclaw/openclaw.mjs", gate)
        self.assertIn(
            "- name: Prove isolated Gateway identity can execute security CLI",
            gate,
        )
        self.assertIn("- --version", gate)

    def test_helper_bundle_loads_before_transaction_state(self) -> None:
        install = self.playbook.index(
            "- name: Install OpenClaw security rehearsal helpers"
        )
        smoke = self.playbook.index(
            "- name: Prove deployed OpenClaw security rehearsal helpers load"
        )
        timestamp = self.playbook.index(
            "- name: Generate OpenClaw security rehearsal timestamp"
        )
        bundle = self.playbook[install:timestamp]
        self.assertLess(install, smoke)
        self.assertLess(smoke, timestamp)
        self.assertIn("- openclaw-native-session-transition.py", bundle)
        self.assertIn("- openclaw-session-transition.py", bundle)
        self.assertIn("- --help", bundle)

    def test_native_archive_uses_resolved_cli_and_exposes_sanitized_failure(
        self,
    ) -> None:
        transition = self.playbook.index(
            "- name: Archive exact synthetic security session through native RPC"
        )
        freeze = self.playbook.index(
            "- name: Freeze native security transition evidence"
        )
        native = self.playbook[transition:freeze]
        self.assertIn(
            "'--openclaw', openclaw_security_rehearsal_runtime_selectors.results[1].stdout",
            native,
        )
        self.assertNotIn(
            "openclaw_isolated_gateway_runtime_dir + '/bin/openclaw'", native
        )
        self.assertNotIn("no_log: true", native)

    def test_plan_stops_before_backup_probe_or_model_activity(self) -> None:
        plan_exit = self.playbook.index(
            "- name: Stop after non-runtime OpenClaw security plan"
        )
        prior_activity = self.playbook.index(
            "- name: Inspect prior isolated service activity"
        )
        backup = self.playbook.index("- name: Back up targeted OpenClaw security state")
        model = self.playbook.index(
            "- name: Run one adversarial OpenClaw security turn"
        )
        self.assertLess(plan_exit, prior_activity)
        self.assertLess(plan_exit, backup)
        self.assertLess(plan_exit, model)

    def test_backup_precedes_config_deploy_probe_and_model(self) -> None:
        stop_gateway = self.playbook.index(
            "- name: Stop isolated Gateway before security backup"
        )
        stop_codex = self.playbook.index(
            "- name: Stop isolated Codex before security backup"
        )
        backup = self.playbook.index("- name: Back up targeted OpenClaw security state")
        backup_ready = self.playbook.index(
            "- name: Record completed OpenClaw security rollback artifact"
        )
        deploy = self.playbook.index(
            "- name: Deploy channel-less OpenClaw security config"
        )
        secret = self.playbook.index("- name: Write Gateway-owned synthetic secret")
        model = self.playbook.index(
            "- name: Run one adversarial OpenClaw security turn"
        )
        self.assertLess(stop_gateway, stop_codex)
        self.assertLess(stop_codex, backup)
        self.assertLess(backup, backup_ready)
        self.assertLess(backup_ready, deploy)
        self.assertLess(deploy, secret)
        self.assertLess(secret, model)
        self.assertIn("rollback.tar", self.playbook)

    def test_native_validation_uses_service_state_not_private_backup_tree(
        self,
    ) -> None:
        stage = self.playbook.index(
            "- name: Stage service-readable security config for native validation"
        )
        validate = self.playbook.index(
            "- name: Validate security config with installed OpenClaw schema"
        )
        cleanup = self.playbook.index(
            "- name: Remove temporary security validation directory"
        )
        block = self.playbook[stage:cleanup]
        self.assertLess(stage, validate)
        self.assertIn("openclaw_security_rehearsal_validation_dir", block)
        self.assertNotIn(
            "OPENCLAW_CONFIG_PATH={{ openclaw_security_rehearsal_evidence_dir }}",
            block,
        )
        self.assertIn(
            "openclaw_security_rehearsal_runtime_selectors.results[1].stdout",
            block,
        )
        self.assertIn("failed_when: false", block)
        self.assertIn(
            "Remove failed temporary security validation directory", self.playbook
        )

    def test_split_service_and_secret_boundaries_are_explicit(self) -> None:
        self.assertIn("User={{ openclaw_isolated_codex_user }}", self.codex_unit)
        self.assertIn("NoNewPrivileges=yes", self.codex_unit)
        self.assertIn("CapabilityBoundingSet=", self.codex_unit)
        self.assertIn(
            "InaccessiblePaths=-{{ openclaw_isolated_gateway_config_dir }}",
            self.codex_unit,
        )
        self.assertIn(
            "TemporaryFileSystem={{ openclaw_isolated_gateway_state_dir }}:ro",
            self.codex_unit,
        )
        self.assertIn(
            "ReadOnlyPaths={{ openclaw_isolated_codex_runtime_dir }}",
            self.codex_unit,
        )
        self.assertNotIn("BindReadOnlyPaths=", self.codex_unit)
        self.assertNotIn(
            "InaccessiblePaths=-{{ openclaw_isolated_gateway_config_dir }} "
            "-{{ openclaw_isolated_gateway_state_dir }}",
            self.codex_unit,
        )
        self.assertIn(
            "InaccessiblePaths=-{{ openclaw_security_rehearsal_root }}",
            self.codex_unit,
        )
        self.assertIn(
            "ReadWritePaths={{ openclaw_isolated_gateway_workspace_dir }}",
            self.codex_unit,
        )
        self.assertIn(
            "ReadOnlyPaths={{ openclaw_isolated_gateway_workspace_dir }}",
            self.gateway_unit,
        )
        self.assertIn(
            "Prove Codex service namespace cannot read Gateway secrets",
            self.playbook,
        )
        self.assertIn(
            "Prove Gateway service namespace cannot read Codex auth", self.playbook
        )
        self.assertIn("/usr/bin/nsenter", self.playbook)
        self.assertIn(
            "Prove both services share only the private native hook relay path",
            self.playbook,
        )
        self.assertIn("'sudo' not in", self.playbook)
        self.assertIn("'docker' not in", self.playbook)

    def test_provider_auth_boundary_precedes_service_activity(self) -> None:
        auth_audit = self.playbook.index(
            "- name: Audit OpenClaw provider authentication separation"
        )
        prior_activity = self.playbook.index(
            "- name: Inspect prior isolated service activity"
        )
        model = self.playbook.index(
            "- name: Run one adversarial OpenClaw security turn"
        )
        self.assertLess(auth_audit, prior_activity)
        self.assertLess(auth_audit, model)
        self.assertIn("openclaw-provider-auth-boundary-audit.py", self.playbook)
        self.assertIn("provider-auth-boundary.json", self.playbook)
        self.assertIn("openaiProfileCount", self.playbook)
        self.assertIn("authProfileStateRows", self.playbook)
        self.assertIn("authProfileStoreRows", self.playbook)

    def test_prompt_is_fixed_and_trajectory_is_authoritative(self) -> None:
        prompt = self.playbook.index(
            "- name: Write private adversarial OpenClaw security prompt"
        )
        model = self.playbook.index(
            "- name: Run one adversarial OpenClaw security turn"
        )
        stop = self.playbook.index(
            "- name: Stop OpenClaw security canary before evidence audit"
        )
        audit = self.playbook.index(
            "- name: Audit persisted OpenClaw security trajectory and filesystem"
        )
        exact_archive = self.playbook.index(
            "- name: Archive exact synthetic security session through native RPC"
        )
        self.assertLess(prompt, model)
        self.assertLess(model, stop)
        self.assertLess(stop, audit)
        self.assertLess(audit, exact_archive)
        for command in (
            "/usr/bin/id -un",
            "/usr/bin/sudo -n /usr/bin/true",
            "/usr/bin/cat --",
            "{{ openclaw_isolated_access_check_path }} -r /var/run/docker.sock",
            "/usr/bin/printf '%s\\n'",
        ):
            self.assertIn(command, self.playbook)
        self.assertIn("--required-archive-key", self.playbook)

    def test_model_input_is_staged_outside_private_backup_tree(self) -> None:
        stage = self.playbook.index(
            "- name: Stage service-readable security prompt input"
        )
        model = self.playbook.index(
            "- name: Run one adversarial OpenClaw security turn"
        )
        cleanup = self.playbook.index("- name: Remove temporary security prompt input")
        block = self.playbook[stage:cleanup]
        self.assertLess(stage, model)
        self.assertIn("openclaw_security_rehearsal_input_dir", block)
        self.assertNotIn(
            '--message-file\n              - "{{ openclaw_security_rehearsal_evidence_dir }}',
            block,
        )
        self.assertIn(
            "openclaw_security_rehearsal_runtime_selectors.results[1].stdout",
            block,
        )
        self.assertIn("Remove failed temporary security prompt input", self.playbook)

    def test_delivery_listener_and_boot_state_are_compared(self) -> None:
        listener_before = self.playbook.index(
            "- name: Capture production Gateway listener before security rehearsal"
        )
        delivery_before = self.playbook.index(
            "- name: Audit replay-capable state before security turn"
        )
        model = self.playbook.index(
            "- name: Run one adversarial OpenClaw security turn"
        )
        delivery_after = self.playbook.index(
            "- name: Audit replay-capable state after security turn"
        )
        listener_after = self.playbook.index(
            "- name: Capture production Gateway listener after security rehearsal"
        )
        self.assertLess(listener_before, delivery_before)
        self.assertLess(delivery_before, model)
        self.assertLess(model, delivery_after)
        self.assertLess(delivery_after, listener_after)
        self.assertIn("['disabled', 'disabled']", self.playbook)
        self.assertIn("productionGatewayChanged': false", self.playbook)

    def test_rescue_stops_both_services_cleans_session_and_restores_backup(
        self,
    ) -> None:
        rescue = self.playbook.index("      rescue:")
        tail = self.playbook[rescue:]
        self.assertIn("Stop failed OpenClaw security canary", tail)
        self.assertIn("Stop failed OpenClaw Codex executor", tail)
        self.assertIn(
            "Archive and remove failed synthetic security session artifacts", tail
        )
        self.assertIn("Restore targeted OpenClaw security rollback artifact", tail)
        self.assertIn("Remove failed synthetic security filesystem probes", tail)
        self.assertIn("Restore prior isolated Codex activity after failure", tail)
        self.assertIn("Restore prior isolated Gateway activity after failure", tail)
        self.assertIn("Fail OpenClaw security rehearsal after rollback", tail)


if __name__ == "__main__":
    unittest.main()
