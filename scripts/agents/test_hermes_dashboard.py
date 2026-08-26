#!/usr/bin/env python3
"""Regression tests for the authenticated native Hermes dashboard."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


class HermesDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.variables = yaml.safe_load(
            (ROOT / "inventory/group_vars/hermes_hosts/vars.yml").read_text()
        )
        cls.playbook_text = (
            ROOT / "playbooks/agents/hermes-dashboard.yml"
        ).read_text()
        cls.playbook = yaml.safe_load(cls.playbook_text)[0]
        cls.unit = (
            ROOT / "templates/hermes/hermes-dashboard.service.j2"
        ).read_text()
        cls.caddy = (ROOT / "templates/docker/Caddyfile.j2").read_text()

    def task(self, name: str) -> str:
        pending = list(self.playbook["tasks"])
        while pending:
            task = pending.pop(0)
            if task.get("name") == name:
                return yaml.safe_dump(task, sort_keys=False)
            for section in ("block", "rescue", "always"):
                pending.extend(task.get(section, []))
        self.fail(f"task not found: {name}")

    def test_rollout_is_disabled_and_exactly_gated(self) -> None:
        self.assertEqual(self.variables["hermes_dashboard_mode"], "disabled")
        self.assertFalse(self.variables["hermes_dashboard_approved"])
        self.assertEqual(
            self.variables["hermes_dashboard_required_confirmation"],
            "converge-authenticated-hermes-dashboard-on-jn-t14s-lin",
        )
        gate = self.task("Require exact Hermes dashboard authorization")
        self.assertIn("hermes_dashboard_required_confirmation", gate)
        self.assertIn("100.73.46.86", gate)
        self.assertIn("9119", gate)

    def test_service_is_native_non_root_and_tailscale_bound(self) -> None:
        self.assertIn("User=hermes-astra", self.unit)
        self.assertIn("Group=hermes-astra", self.unit)
        self.assertIn(" dashboard --host ", self.unit)
        self.assertIn("--host {{ hermes_dashboard_bind_address }}", self.unit)
        self.assertIn("--no-open", self.unit)
        self.assertIn("NoNewPrivileges=true", self.unit)
        self.assertIn("CapabilityBoundingSet=", self.unit)
        self.assertIn("ProtectSystem=strict", self.unit)
        self.assertIn("InaccessiblePaths=/var/lib/hermes/dubble", self.unit)
        self.assertIn("BindPaths={{ hermes_astra_workspace_source }}", self.unit)
        self.assertNotIn("docker.sock", self.unit)
        self.assertNotIn("sudo", self.unit)
        self.assertNotIn("--insecure", self.unit)

    def test_auth_is_hashed_stable_and_verified(self) -> None:
        environment = self.task("Store hashed dashboard authentication environment")
        self.assertIn("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH", environment)
        self.assertIn("HERMES_DASHBOARD_BASIC_AUTH_SECRET", environment)
        self.assertIn("HERMES_DASHBOARD_PUBLIC_URL", environment)
        self.assertNotIn("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=", environment)
        verification = self.task(
            "Require the remote dashboard to fail closed behind basic auth"
        )
        self.assertIn("auth_required", verification)
        self.assertIn("auth_providers", verification)
        self.assertIn("'basic'", verification)

    def test_change_has_backup_and_automatic_restore(self) -> None:
        self.task("Preserve existing dashboard files")
        self.task("Record dashboard rollback manifest")
        self.task("Remove dashboard files absent before deployment")
        self.task("Restore preserved dashboard files")
        self.task("Restore prior dashboard service activity")

    def test_existing_origin_points_to_authenticated_dashboard(self) -> None:
        block = self.caddy.split("openclaw.jnalley.me {", 1)[1].split("\n}", 1)[0]
        self.assertIn("reverse_proxy 100.73.46.86:9119", block)
        self.assertNotIn("reverse_proxy 100.73.46.86:18789", block)


if __name__ == "__main__":
    unittest.main()
