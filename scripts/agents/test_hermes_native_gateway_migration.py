#!/usr/bin/env python3
"""Regression tests for native Hermes Gateway service ownership."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]
MIGRATION = ROOT / "playbooks/agents/hermes-native-gateway-migration.yml"
RUNTIME = ROOT / "playbooks/agents/hermes-production-runtime.yml"
AUTOMATION = ROOT / "playbooks/agents/hermes-automation.yml"
DOCKER = ROOT / "playbooks/agents/hermes-docker-inventory.yml"
MEMORY = ROOT / "playbooks/agents/hermes-memory-continuity.yml"
SHADOW = ROOT / "playbooks/agents/hermes-shadow.yml"
PLANNED_STOP = ROOT / "tasks/hermes-planned-stop-marker.yml"
HARDENING = ROOT / "templates/hermes/hermes-gateway-hardening.conf.j2"
VARS = ROOT / "inventory/group_vars/hermes_hosts/vars.yml"


class NativeGatewayMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.migration = MIGRATION.read_text(encoding="utf-8")
        cls.runtime = RUNTIME.read_text(encoding="utf-8")
        cls.automation = AUTOMATION.read_text(encoding="utf-8")
        cls.docker = DOCKER.read_text(encoding="utf-8")
        cls.memory = MEMORY.read_text(encoding="utf-8")
        cls.shadow = SHADOW.read_text(encoding="utf-8")
        cls.planned_stop = PLANNED_STOP.read_text(encoding="utf-8")
        cls.hardening = HARDENING.read_text(encoding="utf-8")
        cls.variables = yaml.safe_load(VARS.read_text(encoding="utf-8"))

    def test_native_profiles_keep_separate_account_homes(self) -> None:
        for profile in self.variables["hermes_shadow_profiles"]:
            account_home = f"/var/lib/hermes/{profile['name']}"
            self.assertEqual(profile["account_home"], account_home)
            self.assertEqual(
                profile["home"],
                f"{account_home}/.hermes/profiles/{profile['name']}",
            )

    def test_migration_is_inert_and_owner_gated(self) -> None:
        self.assertEqual(
            self.variables["hermes_native_gateway_migration_mode"],
            "disabled",
        )
        self.assertFalse(
            self.variables["hermes_native_gateway_migration_approved"]
        )
        self.assertIn("exact native Gateway migration authorization", self.migration)

    def test_migration_retains_old_state_and_has_rollback(self) -> None:
        self.assertIn("Copy stopped Hermes state into native profile roots", self.migration)
        self.assertNotIn("Move stopped Hermes state", self.migration)
        self.assertIn("Back up stopped legacy profile state", self.migration)
        self.assertIn("Restore handwritten Gateway base units", self.migration)
        self.assertIn("Remove copied native profile roots", self.migration)
        self.assertIn("Resume pre-migration Hermes timers", self.migration)
        self.assertIn("Back up current managed profile-skill state", self.migration)
        self.assertIn("Restore pre-migration managed profile-skill state", self.migration)
        self.assertIn("Back up existing native policy files", self.migration)
        self.assertIn("Restore pre-migration native policy files", self.migration)
        self.assertIn("Capture failed native Gateway startup journals", self.migration)
        self.assertIn("Preserve failed native Gateway startup journals", self.migration)
        self.assertIn(
            "hermes_gateway_bootstrap_skip_projection_preflights: true",
            self.migration,
        )
        self.assertIn(
            "Environment=HERMES_PROJECTION_PREFLIGHTS_PENDING=1",
            self.hardening,
        )
        stage = self.migration.index(
            "Stage reviewed profile skills required by native startup"
        )
        start = self.migration.index(
            "Start production Gateways through native Hermes lifecycle"
        )
        self.assertLess(stage, start)
        stop = self.migration.index("Stop handwritten production Gateways once")
        refresh = self.migration.index(
            "Refresh stopped legacy profile top-level entries"
        )
        archive = self.migration.index("Back up stopped legacy profile state")
        self.assertLess(stop, refresh)
        self.assertLess(refresh, archive)

    def test_native_cli_owns_install_and_lifecycle(self) -> None:
        for text in (self.migration, self.runtime, self.shadow):
            self.assertIn("gateway\n", text)
            self.assertIn("install\n", text)
            self.assertIn("--system", text)
            self.assertIn("--run-as-user", text)
        self.assertIn("gateway\n", self.automation)
        self.assertIn("stop\n", self.automation)
        self.assertIn("start\n", self.automation)
        self.assertIn("restart\n", self.docker)

    def test_hardening_dropin_does_not_replace_native_lifecycle(self) -> None:
        for forbidden in (
            "ExecStart=",
            "ExecStop=",
            "Restart=",
            "RestartSec=",
            "RestartForceExitStatus=",
            "RestartPreventExitStatus=",
            "KillSignal=",
            "KillMode=",
            "WatchdogSec=",
            "Type=",
            "User=",
            "Group=",
            "Environment=HOME=",
            "Environment=HERMES_HOME=",
        ):
            self.assertNotIn(forbidden, self.hardening)
        self.assertEqual(self.hardening.count("WorkingDirectory="), 1)
        self.assertIn("SuccessExitStatus=75", self.hardening)
        self.assertIn(
            "{% if hermes_profile.gateway_working_directory is defined %}",
            self.hardening,
        )
        self.assertIn(
            "Environment=TERMINAL_CWD={{ hermes_profile.terminal_cwd }}",
            self.hardening,
        )
        self.assertIn(
            "ReadWritePaths={{ hermes_profile.account_home }}",
            self.hardening,
        )

    def test_root_lifecycle_calls_prepare_service_owned_stop_markers(self) -> None:
        for text in (
            self.migration,
            self.runtime,
            self.automation,
            self.docker,
            self.memory,
        ):
            self.assertIn("hermes-planned-stop-marker.yml", text)
        for required in (
            "/usr/sbin/runuser",
            "write_planned_stop_marker",
            '- "1"',
            "hermes_planned_stop_profile.user",
            "hermes_planned_stop_profile.group",
            "hermes_planned_stop_marker.stat.mode == '0600'",
        ):
            self.assertIn(required, self.planned_stop)
        self.assertNotIn("become_user:", self.planned_stop)

    def test_check_mode_skips_future_profile_runtime_validation(self) -> None:
        start = self.migration.index(
            "Verify Discord sessions from native profile roots"
        )
        end = self.migration.index(
            "Record paused-timer handoff for automation convergence"
        )
        self.assertIn("when: not ansible_check_mode", self.migration[start:end])

    def test_production_paths_do_not_render_handwritten_base_unit(self) -> None:
        for text in (self.runtime, self.automation, self.docker, self.shadow):
            self.assertNotIn("hermes-gateway.service.j2", text)
        self.assertIn("hermes-gateway-hardening.conf.j2", self.runtime)
        self.assertIn("hermes-gateway-hardening.conf.j2", self.shadow)


if __name__ == "__main__":
    unittest.main()
