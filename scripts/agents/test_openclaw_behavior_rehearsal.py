#!/usr/bin/env python3

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
PLAYBOOK_PATH = ROOT / "playbooks/agents/openclaw-behavior-rehearsal.yml"
INVENTORY_PATH = ROOT / "inventory/host_vars/jn-t14s-lin/openclaw.yml"


class BehaviorRehearsalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.playbook = PLAYBOOK_PATH.read_text(encoding="utf-8")
        cls.inventory = yaml.safe_load(INVENTORY_PATH.read_text(encoding="utf-8"))

    def test_default_mode_is_inert_and_requires_owner_approval(self) -> None:
        self.assertEqual(self.inventory["openclaw_behavior_rehearsal_mode"], "disabled")
        self.assertIs(self.inventory["openclaw_behavior_rehearsal_approved"], False)
        self.assertIn("openclaw_behavior_rehearsal_mode == 'disabled'", self.playbook)
        self.assertIn("openclaw_behavior_rehearsal_approved", self.playbook)

    def test_primary_model_routes_through_the_codex_provider(self) -> None:
        self.assertEqual(
            self.inventory["openclaw_isolated_gateway_model"],
            "codex/gpt-5.6-sol",
        )
        self.assertIn(
            "openclaw_behavior_rehearsal_primary_model is match('^codex/')",
            self.playbook,
        )

    def test_applied_silent_data_handoff_is_a_hard_prerequisite(self) -> None:
        prerequisite = self.playbook.index(
            "- name: Require replay-safe applied OpenClaw data handoff"
        )
        render = self.playbook.index(
            "- name: Render channel-less OpenClaw behavior configurations"
        )
        self.assertLess(prerequisite, render)
        self.assertIn(
            "openclaw_behavior_rehearsal_data_result.mode == 'apply'", self.playbook
        )
        self.assertIn(
            "openclaw_behavior_rehearsal_data_result.channelsEnabled == false",
            self.playbook,
        )
        self.assertIn(
            "openclaw_behavior_rehearsal_data_result.cronEnabled == false",
            self.playbook,
        )
        self.assertIn(
            "openclaw_behavior_rehearsal_data_result.heartbeatsEnabled == false",
            self.playbook,
        )
        self.assertIn(
            "openclaw_behavior_rehearsal_data_result.bootEnabled == false",
            self.playbook,
        )

    def test_prerequisites_are_typed_and_bind_an_immutable_cli(self) -> None:
        inspect = self.playbook.index(
            "- name: Inspect OpenClaw behavior rehearsal prerequisites"
        )
        handoff = self.playbook.index(
            "- name: Find successful OpenClaw canary data handoffs"
        )
        gate = self.playbook[inspect:handoff]
        self.assertNotIn("map(attribute='stat.isreg')", gate)
        self.assertNotIn("map(attribute='stat.islnk')", gate)
        self.assertEqual(gate.count("expected_kind: regular"), 20)
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
            "- name: Resolve selected immutable OpenClaw behavior runtime and CLI",
            gate,
        )
        self.assertIn("--canonicalize-existing", gate)
        self.assertIn("/lib/node_modules/openclaw/openclaw.mjs", gate)
        self.assertIn(
            "- name: Prove isolated Gateway identity can execute behavior CLI",
            gate,
        )
        self.assertIn("- --version", gate)
        self.assertIn("codex-home/auth.json", gate)
        self.assertIn("stat.mode == '0600'", gate)

    def test_helper_bundle_loads_before_transaction_state(self) -> None:
        install = self.playbook.index(
            "- name: Install OpenClaw behavior rehearsal helpers"
        )
        smoke = self.playbook.index(
            "- name: Prove deployed OpenClaw behavior rehearsal helpers load"
        )
        timestamp = self.playbook.index(
            "- name: Generate OpenClaw behavior rehearsal timestamp"
        )
        bundle = self.playbook[install:timestamp]
        self.assertLess(install, smoke)
        self.assertLess(smoke, timestamp)
        self.assertIn("- openclaw-native-session-transition.py", bundle)
        self.assertIn("- openclaw-session-transition.py", bundle)
        self.assertIn("- openclaw-heartbeat-event-check.py", bundle)
        self.assertIn("- openclaw-star-gateway-rehearsal.py", bundle)
        self.assertIn("- --help", bundle)

    def test_native_archive_uses_resolved_cli_and_exposes_sanitized_failure(
        self,
    ) -> None:
        transition = self.playbook.index(
            "- name: Archive synthetic behavior sessions through native OpenClaw RPC"
        )
        freeze = self.playbook.index(
            "- name: Freeze native behavior transition evidence"
        )
        native = self.playbook[transition:freeze]
        self.assertIn(
            "'--openclaw', openclaw_behavior_rehearsal_runtime_selectors.results[1].stdout",
            native,
        )
        self.assertNotIn(
            "openclaw_isolated_gateway_runtime_dir + '/bin/openclaw'", native
        )
        self.assertNotIn("no_log: true", native)

    def test_plan_mode_exits_before_gateway_or_model_activity(self) -> None:
        plan_exit = self.playbook.index(
            "- name: Stop after non-mutating OpenClaw behavior plan"
        )
        prior_activity = self.playbook.index(
            "- name: Inspect prior isolated service activity"
        )
        dubble = self.playbook.index("- name: Run Dubble behavior probe")
        self.assertLess(plan_exit, prior_activity)
        self.assertLess(plan_exit, dubble)

    def test_backup_precedes_native_validation_and_behavior_turns(self) -> None:
        stop = self.playbook.index(
            "- name: Stop isolated Gateway before behavior backup"
        )
        backup = self.playbook.index("- name: Back up targeted OpenClaw behavior state")
        backup_ready = self.playbook.index(
            "- name: Record completed OpenClaw behavior rollback artifact"
        )
        native_validation = self.playbook.index(
            "- name: Validate behavior configs with the installed OpenClaw schema"
        )
        start = self.playbook.index("- name: Start baseline OpenClaw behavior canary")
        dubble = self.playbook.index("- name: Run Dubble behavior probe")
        self.assertLess(stop, backup)
        self.assertLess(backup, backup_ready)
        self.assertLess(backup_ready, native_validation)
        self.assertLess(native_validation, start)
        self.assertLess(start, dubble)
        self.assertIn("rollback.tar", self.playbook)
        self.assertIn("codex-state.tar", self.playbook)

    def test_executor_restarts_after_oauth_before_gateway_and_is_restored(self) -> None:
        stop_executor = self.playbook.index(
            "- name: Stop isolated Codex executor before behavior backup"
        )
        backup_executor = self.playbook.index(
            "- name: Back up current executor state before restart"
        )
        start_executor = self.playbook.index(
            "- name: Start freshly authorized isolated Codex executor"
        )
        start_gateway = self.playbook.index(
            "- name: Start baseline OpenClaw behavior canary"
        )
        self.assertLess(stop_executor, backup_executor)
        self.assertLess(backup_executor, start_executor)
        self.assertLess(start_executor, start_gateway)
        self.assertIn(
            "Restore prior isolated Codex executor activity after failure",
            self.playbook,
        )

    def test_native_validation_uses_service_state_not_private_backup_tree(
        self,
    ) -> None:
        stage = self.playbook.index(
            "- name: Stage service-readable behavior configs for native validation"
        )
        validate = self.playbook.index(
            "- name: Validate behavior configs with the installed OpenClaw schema"
        )
        cleanup = self.playbook.index(
            "- name: Remove temporary behavior validation directory"
        )
        block = self.playbook[stage:cleanup]
        self.assertLess(stage, validate)
        self.assertIn("openclaw_behavior_rehearsal_validation_dir", block)
        self.assertNotIn(
            "OPENCLAW_CONFIG_PATH={{ openclaw_behavior_rehearsal_evidence_dir }}",
            block,
        )
        self.assertIn(
            "openclaw_behavior_rehearsal_runtime_selectors.results[1].stdout",
            block,
        )
        self.assertIn("failed_when: false", block)
        self.assertIn(
            "Remove failed temporary behavior validation directory", self.playbook
        )

    def test_channel_and_schedule_suppression_is_enforced(self) -> None:
        self.assertIn("Environment=OPENCLAW_SKIP_CHANNELS=1", self.playbook)
        self.assertIn("Environment=OPENCLAW_SKIP_CRON=1", self.playbook)
        self.assertIn(
            "InaccessiblePaths=-/run/docker.sock -/var/run/docker.sock", self.playbook
        )
        self.assertIn("cadence: 0m", self.playbook)
        self.assertIn("cadence: 1m", self.playbook)
        self.assertIn("audit_mode: controlled-rigel", self.playbook)
        self.assertIn("enabled: false", self.playbook)

    def test_behavior_probes_and_native_evidence_gate_are_ordered(self) -> None:
        dubble = self.playbook.index("- name: Run Dubble behavior probe")
        reasoning = self.playbook.index("- name: Run semantic reasoning probes")
        star = self.playbook.index(
            "- name: Run persistent-Gateway Star delegation behavior probe"
        )
        star_gate = self.playbook.index(
            "- name: Require complete persistent-Gateway Star follow-up"
        )
        restore = self.playbook.index(
            "- name: Restore durable native Rigel heartbeat session"
        )
        controlled = self.playbook.index(
            "- name: Deploy controlled Rigel heartbeat config"
        )
        heartbeat_start = self.playbook.index(
            "- name: Record controlled Rigel heartbeat start time"
        )
        heartbeat = self.playbook.index(
            "- name: Restart canary for native controlled Rigel heartbeat"
        )
        audit = self.playbook.index(
            "- name: Audit persisted OpenClaw behavior evidence"
        )
        baseline = self.playbook.index(
            "- name: Restore baseline channel-less behavior config immediately"
        )
        archive = self.playbook.index(
            "- name: Archive synthetic behavior sessions through native OpenClaw RPC"
        )
        self.assertLess(dubble, reasoning)
        self.assertLess(reasoning, star)
        self.assertLess(star, star_gate)
        self.assertLess(star_gate, restore)
        self.assertLess(star, restore)
        self.assertLess(restore, controlled)
        self.assertLess(star, controlled)
        self.assertLess(controlled, heartbeat_start)
        self.assertLess(heartbeat_start, heartbeat)
        self.assertLess(controlled, heartbeat)
        self.assertLess(heartbeat, audit)
        self.assertLess(audit, baseline)
        self.assertLess(baseline, archive)
        self.assertIn("cleanup keep", self.playbook)
        self.assertIn("Spawn only Vega from this Astra session", self.playbook)
        self.assertIn("Vega's actual preliminary evidence", self.playbook)
        self.assertIn("Do not spawn Antares directly", self.playbook)
        self.assertIn("--infeasible-result", self.playbook)
        self.assertIn("--owned-result", self.playbook)
        self.assertIn("reasoningCaseCount", self.playbook)
        self.assertIn("agent:rigel:main:heartbeat", self.playbook)
        self.assertIn(
            "--restore-native-heartbeat-key=agent:rigel:main:heartbeat",
            self.playbook,
        )
        self.assertIn(
            "Preserve failed native Rigel heartbeat restoration evidence",
            self.playbook,
        )
        star_block = self.playbook[star:restore]
        self.assertIn("openclaw_behavior_rehearsal_star_tool", star_block)
        self.assertIn("--wait-seconds", star_block)
        self.assertIn("initialYielded", star_block)
        self.assertIn("payloadCount", star_block)
        self.assertIn("activeRunCount", star_block)
        self.assertIn(
            '"{{ openclaw_behavior_rehearsal_input_dir }}/star-result.json"',
            star_block,
        )
        self.assertIn("Preserve private completed Star behavior result", star_block)
        self.assertNotIn(
            '--output\n              - "{{ openclaw_behavior_rehearsal_evidence_dir }}',
            star_block,
        )
        self.assertNotIn("- agent\n", star_block)
        self.assertNotIn("system\n              - event", self.playbook)
        self.assertIn(
            "- name: Wait for validated native silent Rigel heartbeat evidence",
            self.playbook,
        )
        self.assertIn("openclaw_behavior_rehearsal_heartbeat_event_tool", self.playbook)
        self.assertNotIn("retries: 90", self.playbook)

    def test_semantic_cases_cover_full_intersection_and_owned_state(self) -> None:
        self.assertIn("Lumen costs $18", self.playbook)
        self.assertIn("Vale costs $26", self.playbook)
        self.assertIn("If neither plan is feasible", self.playbook)
        self.assertIn("Do not provide setup steps", self.playbook)
        self.assertIn("already bought Quartz for $49", self.playbook)
        self.assertIn("Mica now appears for $39", self.playbook)
        self.assertIn("Preserve the valid prior purchase", self.playbook)
        self.assertIn("reasoningCasesValidated': 2", self.playbook)
        self.assertIn("summary.archivePlanned | int >= 6", self.playbook)

    def test_model_inputs_are_staged_outside_private_backup_tree(self) -> None:
        stage = self.playbook.index(
            "- name: Stage service-readable behavior prompt inputs"
        )
        dubble = self.playbook.index("- name: Run Dubble behavior probe")
        cleanup = self.playbook.index("- name: Remove temporary behavior prompt inputs")
        block = self.playbook[stage:cleanup]
        self.assertLess(stage, dubble)
        self.assertIn("openclaw_behavior_rehearsal_input_dir", block)
        self.assertNotIn(
            '--message-file\n              - "{{ openclaw_behavior_rehearsal_evidence_dir }}',
            block,
        )
        self.assertEqual(
            block.count(
                "openclaw_behavior_rehearsal_runtime_selectors.results[1].stdout"
            ),
            3,
        )
        self.assertIn("Remove failed temporary behavior prompt inputs", self.playbook)

    def test_delivery_and_production_gateway_are_compared_before_and_after(
        self,
    ) -> None:
        listener_before = self.playbook.index(
            "- name: Capture production Gateway listener before behavior rehearsal"
        )
        delivery_before = self.playbook.index(
            "- name: Audit replay-capable canary delivery state before behavior turns"
        )
        start = self.playbook.index("- name: Start baseline OpenClaw behavior canary")
        delivery_after = self.playbook.index(
            "- name: Audit replay-capable canary delivery state after behavior turns"
        )
        listener_after = self.playbook.index(
            "- name: Capture production Gateway listener after behavior rehearsal"
        )
        self.assertLess(listener_before, delivery_before)
        self.assertLess(delivery_before, start)
        self.assertLess(start, delivery_after)
        self.assertLess(delivery_after, listener_after)
        self.assertIn("/usr/bin/ss", self.playbook)
        self.assertNotIn("/usr/sbin/ss", self.playbook)
        self.assertIn("productionGatewayChanged': false", self.playbook)

    def test_rescue_restores_targeted_state_and_prior_activity(self) -> None:
        rescue = self.playbook.index("      rescue:")
        tail = self.playbook[rescue:]
        self.assertIn("Restore targeted OpenClaw behavior rollback artifact", tail)
        self.assertIn("--absolute-names", tail)
        self.assertIn("Restore prior isolated Gateway activity after failure", tail)
        self.assertIn("enabled: false", tail)
        self.assertIn("Fail OpenClaw behavior rehearsal after rollback", tail)


if __name__ == "__main__":
    unittest.main()
