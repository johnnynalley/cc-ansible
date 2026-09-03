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
        self.assertFalse(
            self.variables["hermes_production_runtime_reinstall_native_units"]
        )

    def test_backup_and_openclaw_absence_precede_mutation(self) -> None:
        source_gate = self.offset("Require OpenClaw delivery to remain offline")
        backup = self.offset("Back up live Hermes systemd units")
        plugin_backup = self.offset("Back up live Astra Star privacy plugin")
        validator_backup = self.offset("Back up live Astra Star privacy validator")
        readers = self.offset("Create credential-free Hermes runtime readers group")
        self.assertLess(source_gate, backup)
        self.assertLess(backup, plugin_backup)
        self.assertLess(plugin_backup, validator_backup)
        self.assertLess(validator_backup, readers)
        self.assertIn("hermes_production_cutover_rollback_root", self.playbook)
        self.assertIn("check_mode: false", self.playbook[source_gate - 1800:source_gate])
        backup_task = self.playbook[backup:readers]
        self.assertIn("when: not ansible_check_mode", backup_task)

    def test_projection_and_platform_support_are_transactional(self) -> None:
        inspect = self.offset(
            "Inspect existing runtime-owned platform support assets"
        )
        backup = self.offset(
            "Back up existing runtime-owned platform support assets"
        )
        deploy = self.offset("Deploy production Hermes platform support assets")
        restart = self.offset(
            "Restart production consumers natively for runtime changes"
        )
        self.assertLess(inspect, backup)
        self.assertLess(backup, deploy)
        self.assertLess(deploy, restart)
        transaction = self.playbook[inspect:restart]
        for required in (
            "hermes_profile_data_stager_source",
            "hermes_profile_data_contract_source",
            "hermes_profile_transformer_source",
            "hermes_profile_transforms_contract_source",
            "scripts/agents/hermes-rigel-academic-smoke.py",
            "scripts/agents/hermes-rigel-workflow-smoke.py",
            "files/hermes/profile-import-contract.json",
            "files/openclaw/workspace-migration-policy.json",
        ):
            self.assertIn(required, self.playbook)
        self.assertIn(
            'path: /usr/local/libexec/hermes-rigel-workflow-smoke',
            self.playbook,
        )
        self.assertIn('mode: "0500"', self.playbook)
        deployment = self.playbook[
            deploy:self.offset("Deploy production Hermes update unit")
        ]
        self.assertNotIn("backup: true", deployment)
        rescue = self.playbook[self.playbook.index("      rescue:"):]
        self.assertIn(
            "Restore prior runtime-owned platform support assets", rescue
        )
        self.assertIn(
            "Remove newly introduced runtime-owned platform support assets",
            rescue,
        )

    def test_profile_guidance_is_not_owned_by_runtime_convergence(self) -> None:
        deploy = self.offset("Deploy production Hermes platform support assets")
        update_unit = self.offset("Deploy production Hermes update unit")
        deployment = self.playbook[deploy:update_unit]
        self.assertIn("item.owner | default('root')", deployment)
        self.assertNotIn("seed_only", self.playbook)
        for path in (
            "/profiles/astra/AGENTS.md",
            "/profiles/astra/SOUL.md",
            "/profiles/dubble/AGENTS.md",
            "/profiles/dubble/SOUL.md",
            "/profiles/rigel/AGENTS.md",
            "/profiles/rigel/SOUL.md",
            "/profiles/rigel/HEARTBEAT.md",
            "/profiles/rigel/TOOLS.md",
            "/profiles/rigel/USER.md",
        ):
            self.assertNotIn(path, self.playbook)

    def test_star_plugin_is_backed_up_validated_and_restarts_only_astra(self) -> None:
        backup = self.offset("Back up live Astra Star privacy plugin")
        deploy = self.offset("Deploy production Astra Star privacy plugin")
        validate = self.offset("Validate production Astra Star privacy plugin")
        restart = self.offset("Restart production consumers natively for runtime changes")
        self.assertLess(backup, deploy)
        self.assertLess(deploy, validate)
        self.assertLess(validate, restart)
        task = self.playbook[deploy:restart]
        self.assertIn("hermes_star_privacy_plugin_source", task)
        self.assertIn("hermes_star_privacy_validator_live", task)
        self.assertIn("/etc/hermes/astra/config.yaml", task)
        self.assertIn("Find generated Astra Star plugin backup files", task)
        self.assertIn("Remove generated Astra Star plugin backup files", task)
        self.assertIn("Deploy production Astra Star privacy validator", task)
        self.assertNotIn("Remove generated Astra Star plugin bytecode caches", task)
        deploy_task = self.playbook[deploy:self.offset(
            "Find generated Astra Star plugin backup files"
        )]
        self.assertNotIn("backup: true", deploy_task)
        selection = self.playbook[self.offset(
            "Select production consumers requiring runtime restart"
        ):self.offset("Record entry into the production consumer restart phase")]
        self.assertIn("item.name == 'astra'", selection)
        self.assertIn("hermes_runtime_star_plugin.changed", selection)
        self.assertIn("item.profile', 'equalto', item.name", selection)

    def test_force_restart_is_bounded_and_inert_by_default(self) -> None:
        self.assertEqual(
            self.variables["hermes_production_runtime_force_restart_profiles"], []
        )
        authorization = self.playbook[
            self.offset("Require exact Hermes production runtime authorization"):
            self.offset("Inspect required live Hermes runtime files")
        ]
        self.assertIn("difference(['astra', 'dubble', 'rigel'])", authorization)
        selection = self.playbook[
            self.offset("Select production consumers requiring runtime restart"):
            self.offset("Record entry into the production consumer restart phase")
        ]
        self.assertIn(
            "item.name in hermes_production_runtime_force_restart_profiles",
            selection,
        )

    def test_runtime_group_is_code_only_and_all_profiles_are_readers(self) -> None:
        self.assertEqual(
            self.variables["hermes_runtime_readers_group"],
            "hermes-runtime-readers",
        )
        self.assertIn("append: true", self.playbook)
        self.assertIn("hermes_runtime_readers_group", self.playbook)
        self.assertNotIn("docker.sock", self.playbook)
        self.assertNotIn("group: docker", self.playbook)

    def test_policy_hash_uses_each_profiles_declared_environment(self) -> None:
        hash_task = self.playbook[
            self.offset("Hash current production Hermes policy and environment"):
            self.offset("Deploy current production Hermes policy checksum manifests")
        ]
        self.assertIn("item.environment_file", hash_task)
        self.assertIn(
            "default('/etc/hermes/' ~ item.name ~ '/.env')", hash_task
        )
        profiles = {
            profile["name"]: profile
            for profile in self.variables["hermes_shadow_profiles"]
        }
        self.assertEqual(
            profiles["rigel"]["environment_file"],
            "/etc/hermes/private/environments/rigel.env",
        )

    def test_all_profiles_can_create_guarded_agent_owned_skills(self) -> None:
        profiles = self.variables["hermes_shadow_profiles"]
        self.assertEqual([profile["name"] for profile in profiles], [
            "astra", "dubble", "rigel"
        ])
        for profile in profiles:
            self.assertFalse(profile["skills_write_approval"], profile["name"])
            self.assertEqual(profile["skills_creation_nudge_interval"], 10)
        template = (
            ROOT / "templates" / "hermes" / "hermes-managed-config.yaml.j2"
        ).read_text(encoding="utf-8")
        self.assertIn("guard_agent_created: true", template)

    def test_native_todo_completion_guard_is_rigel_only(self) -> None:
        profiles = {
            profile["name"]: profile for profile in self.variables["hermes_shadow_profiles"]
        }
        self.assertTrue(profiles["rigel"]["todo_stop_guard"])
        self.assertEqual(profiles["rigel"]["max_todo_stop_nudges"], 6)
        self.assertNotIn("todo_stop_guard", profiles["astra"])
        self.assertNotIn("todo_stop_guard", profiles["dubble"])
        template = (
            ROOT / "templates" / "hermes" / "hermes-managed-config.yaml.j2"
        ).read_text(encoding="utf-8")
        self.assertIn("todo_stop_guard:", template)
        self.assertIn("default(false)", template)
        self.assertIn("max_todo_stop_nudges:", template)

    def test_consumers_restart_natively_after_import_proof(self) -> None:
        imports = self.offset("Validate Discord imports as every isolated identity")
        restart = self.offset(
            "Restart production consumers natively for runtime changes"
        )
        active = self.offset("Ensure production Discord consumers remain active")
        ready = self.offset(
            "Wait for production Discord consumers to reach native readiness"
        )
        self.assertLess(imports, restart)
        self.assertLess(restart, active)
        self.assertLess(active, ready)
        self.assertIn("--imports-only", self.playbook)
        self.assertIn('"{{ item.home }}"', self.playbook[imports:])
        self.assertIn("hermes_shadow_runtime_venv", self.playbook[imports:restart])
        self.assertIn("gateway\n              - restart\n              - --system", self.playbook[restart:active])
        self.assertIn(
            "hermes_production_consumer_profiles",
            self.playbook[restart:active],
        )
        readiness = self.playbook[ready:self.offset(
            "Restore native Hermes update schedule after convergence"
        )]
        self.assertIn("retries: 18", readiness)
        self.assertIn("delay: 5", readiness)
        self.assertIn(
            "until: hermes_runtime_consumer_ready.stdout == 'active'", readiness
        )
        self.assertIn("state: stopped", self.playbook[self.offset(
            "Keep transitional Rigel Gateway stopped and disabled"
        ):restart])
        self.assertIn(
            "not hermes_rigel_dedicated_discord_enabled",
            self.playbook[self.offset(
                "Keep transitional Rigel Gateway stopped and disabled"
            ):restart],
        )
        self.assertIn(
            "hermes_production_consumer_profiles",
            VARS.read_text(encoding="utf-8"),
        )

    def test_native_browser_and_tts_backends_are_installed_and_verified(self) -> None:
        install = self.offset("Install required production Hermes native tool backends")
        verify = self.offset("Validate production browser and TTS backends")
        restart = self.offset("Restart production consumers natively for runtime changes")
        self.assertLess(install, verify)
        self.assertLess(verify, restart)
        task = self.playbook[install:verify]
        self.assertIn("hermes_native_post_setup_keys", task)
        self.assertIn("tools\n              - post-setup", task)
        self.assertIn("HERMES_HOME=/var/lib/hermes/astra/.hermes/profiles/astra", task)
        validation = self.playbook[verify:restart]
        self.assertIn("import edge_tts", validation)
        self.assertIn("_agent_browser_installed", validation)
        self.assertIn("hermes_agent_browser_selector_live", validation)
        self.assertIn("Validate trusted Astra Chromium target", validation)
        self.assertNotIn(
            "or hermes_runtime_native_backends.changed", self.playbook
        )
        self.assertIn(
            "and hermes_runtime_browser_selector.changed",
            self.playbook[self.offset(
                "Select production consumers requiring runtime restart"
            ):restart],
        )

    def test_native_updater_transaction_is_root_owned_and_validated(self) -> None:
        deploy = self.offset("Deploy native Hermes update transaction helper")
        rollback = self.offset("Create native Hermes update rollback root")
        render = self.offset("Render native Hermes update transaction contract")
        validate = self.offset("Validate native Hermes update transaction contract")
        update_unit = self.offset("Deploy production Hermes update unit")
        self.assertLess(deploy, rollback)
        self.assertLess(rollback, render)
        self.assertLess(deploy, render)
        self.assertLess(render, validate)
        self.assertLess(deploy, validate)
        self.assertLess(validate, update_unit)
        task = self.playbook[deploy:validate]
        self.assertIn("hermes_native_update_transaction_source", task)
        self.assertIn("hermes_native_update_transaction_config", task)
        self.assertIn("owner: root", task)
        self.assertIn('mode: "0555"', task)
        rollback_task = self.playbook[rollback:render]
        self.assertIn('owner: "{{ hermes_native_update_user }}"', rollback_task)
        self.assertIn('group: "{{ hermes_native_update_group }}"', rollback_task)
        self.assertIn('mode: "0700"', rollback_task)
        self.assertEqual(
            self.variables["hermes_native_update_rollback_root"],
            "/srv/live-rollbacks/jn-t14s-lin/hermes-native-update",
        )
        self.assertFalse(
            self.variables["hermes_native_update_rollback_root"].startswith(
                self.variables["hermes_production_cutover_rollback_root"] + "/"
            )
        )
        proof = self.playbook[validate:update_unit]
        self.assertIn("--validate-config", proof)

    def test_native_updater_privilege_bridge_is_converged_with_unit(self) -> None:
        unit = self.offset("Deploy production Hermes update unit")
        bridge = self.offset("Deploy exact Astra native update sudoers bridge")
        gateway_units = self.offset("Install native production Hermes Gateway units")
        self.assertLess(unit, bridge)
        self.assertLess(bridge, gateway_units)
        task = self.playbook[bridge:gateway_units]
        self.assertIn("hermes-native-update.sudoers.j2", task)
        self.assertIn("hermes_native_update_sudoers_path", task)
        self.assertIn("validate: /usr/sbin/visudo -cf %s", task)
        self.assertIn("hermes-native-update.sudoers", self.playbook)

    def test_native_update_timer_is_excluded_and_restored(self) -> None:
        record = self.offset("Record native Hermes update worker and timer state")
        pause = self.offset("Pause native Hermes update schedule during convergence")
        idle = self.offset("Require native Hermes update worker idle before convergence")
        restore = self.offset("Restore native Hermes update schedule after convergence")
        active = self.offset(
            "Require native Hermes update timer after convergence when previously active"
        )
        self.assertLess(record, pause)
        self.assertLess(pause, idle)
        self.assertLess(idle, restore)
        self.assertLess(restore, active)
        proof = self.playbook[restore:self.offset(
            "Scan production Hermes consumers for adapter failures"
        )]
        self.assertIn(
            "hermes_runtime_update_state_before.results[1].stdout == 'active'", proof
        )
        self.assertNotIn("hermes_tirith_update_timer", proof)
        self.assertIn("Restore native Hermes update schedule after failure", self.playbook)

    def test_failure_restarts_only_consumers_selected_for_restart(self) -> None:
        select = self.offset("Select production consumers requiring runtime restart")
        phase = self.offset("Record entry into the production consumer restart phase")
        prepare = self.offset("Prepare service-owned markers for runtime restarts")
        self.assertLess(select, phase)
        self.assertLess(phase, prepare)
        selection = self.playbook[select:phase]
        self.assertIn("hermes_runtime_restart_profiles", selection)
        self.assertGreaterEqual(
            self.playbook.count(
                "item.name in (hermes_runtime_restart_profiles | default([]))"
            ),
            4,
        )

    def test_routine_convergence_does_not_rewrite_native_gateway_units(self) -> None:
        install = self.offset("Install native production Hermes Gateway units")
        transitional = self.offset("Install inactive transitional Rigel Gateway unit")
        task = self.playbook[install:transitional]
        self.assertIn(
            "hermes_production_runtime_reinstall_native_units | bool", task
        )
        self.assertIn("not ansible_check_mode", task)

    def test_failure_restores_units_and_consumers(self) -> None:
        rescue = self.playbook.index("      rescue:")
        tail = self.playbook[rescue:]
        self.assertIn(
            "Restore pre-convergence Astra Star privacy validator", tail
        )
        self.assertIn(
            "Restore pre-convergence Astra Star privacy plugin", tail
        )
        self.assertIn("Restore pre-convergence Hermes systemd units", tail)
        self.assertIn(
            "Restore consumers natively after convergence failure", tail
        )
        self.assertGreaterEqual(
            tail.count(
                "hermes_runtime_restart_phase_entered | default(false) | bool"
            ),
            2,
        )
        self.assertIn("ansible.builtin.fail", tail)

    def test_dry_run_uses_real_read_only_service_state(self) -> None:
        active = self.offset(
            "Wait for production Discord consumers to reach native readiness"
        )
        assertion = self.offset("Restore native Hermes update schedule after convergence")
        health = self.offset("Verify Health receiver remains active")
        health_assert = self.offset("Require Health receiver continuity")
        self.assertIn("check_mode: false", self.playbook[active:assertion])
        self.assertIn("check_mode: false", self.playbook[health:health_assert])

    def test_no_match_journal_scan_is_success_not_probe_noise(self) -> None:
        scan = self.offset("Scan production Hermes consumers for adapter failures")
        clean = self.offset("Require clean production Hermes journals")
        task = self.playbook[scan:clean]
        self.assertIn("failed_when: hermes_runtime_failure_scan.rc not in [0, 1]", task)
        self.assertIn("--grep=No adapter", task)
        self.assertIn("check_mode: false", task)


if __name__ == "__main__":
    unittest.main()
