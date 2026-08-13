#!/usr/bin/env python3
"""Regression tests for the inert Hermes shadow deployment."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).parents[2]
PLAYBOOK = ROOT / "playbooks" / "agents" / "hermes-shadow.yml"
VARS = ROOT / "inventory" / "group_vars" / "hermes_hosts" / "vars.yml"
CONFIG = ROOT / "templates" / "hermes" / "hermes-managed-config.yaml.j2"
SERVICE = ROOT / "templates" / "hermes" / "hermes-gateway.service.j2"
CONTRACT = ROOT / "files" / "hermes" / "shadow-target.json"
RIGEL_JOB = ROOT / "files" / "hermes" / "jobs" / "rigel-academic-alerts.json"
RIGEL_SCRIPT = ROOT / "scripts" / "agents" / "hermes-rigel-schedule.py"
INVENTORY = ROOT / "inventory" / "hosts.ini"
SITE = ROOT / "site.yml"


class HermesShadowPlaybookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.playbook = PLAYBOOK.read_text(encoding="utf-8")
        cls.variables = yaml.safe_load(VARS.read_text(encoding="utf-8"))
        cls.config_template = CONFIG.read_text(encoding="utf-8")
        cls.service_template = SERVICE.read_text(encoding="utf-8")
        cls.rigel_job = yaml.safe_load(RIGEL_JOB.read_text(encoding="utf-8"))
        cls.rigel_script = RIGEL_SCRIPT.read_text(encoding="utf-8")
        cls.environment = Environment(undefined=StrictUndefined, autoescape=False)

    def task(self, name: str) -> str:
        marker = f"    - name: {name}"
        start = self.playbook.index(marker)
        end = self.playbook.find("\n    - name:", start + len(marker))
        if end == -1:
            end = len(self.playbook)
        return self.playbook[start:end]

    def test_default_mode_is_inert(self) -> None:
        self.assertEqual(self.variables["hermes_shadow_mode"], "disabled")
        self.assertFalse(self.variables["hermes_shadow_change_approved"])
        self.assertFalse(self.variables["hermes_shadow_install_approved"])
        self.assertFalse(self.variables["hermes_shadow_start_approved"])
        stop = self.task("Stop Hermes shadow units when disabled")
        self.assertIn("enabled: false", stop)
        self.assertIn("state: stopped", stop)
        self.assertIn("ansible.builtin.meta: end_host", self.playbook)

    def test_shadow_targets_existing_host_but_not_normal_convergence(self) -> None:
        lines = INVENTORY.read_text(encoding="utf-8").splitlines()
        start = lines.index("[hermes_hosts]") + 1
        members = []
        for line in lines[start:]:
            stripped = line.strip()
            if stripped.startswith("["):
                break
            if stripped and not stripped.startswith("#"):
                members.append(stripped)
        self.assertEqual(members, ["jn-t14s-lin"])
        self.assertNotIn("hermes-shadow.yml", SITE.read_text(encoding="utf-8"))

    def test_profiles_are_distinct_and_have_no_host_execution(self) -> None:
        profiles = self.variables["hermes_shadow_profiles"]
        self.assertEqual(
            [item["name"] for item in profiles], ["astra", "dubble", "rigel"]
        )
        self.assertEqual(len({item["user"] for item in profiles}), 3)
        self.assertEqual(len({item["uid"] for item in profiles}), 3)
        self.assertEqual(len({item["subid_start"] for item in profiles}), 3)
        for profile in profiles:
            self.assertEqual(profile["user"], f"hermes-{profile['name']}")
            self.assertEqual(profile["home"], f"/var/lib/hermes/{profile['name']}")
            self.assertTrue(
                {"terminal", "file", "code_execution", "discord_admin"}
                <= set(profile["disabled_toolsets"])
            )

    def test_same_host_capacity_is_checked_before_install(self) -> None:
        cpu = self.task("Read Hermes target logical CPU capacity")
        memory = self.task("Read Hermes target available memory")
        disk = self.task("Read Hermes target free root filesystem space")
        gate = self.task("Require reviewed same-host Hermes capacity")
        self.assertIn("_NPROCESSORS_ONLN", cpu)
        self.assertIn("/proc/meminfo", memory)
        self.assertIn("--output=avail", disk)
        self.assertIn("minimumLogicalCpus", gate)
        self.assertIn("minimumAvailableMemoryMiB", gate)
        self.assertIn("minimumFreeDiskGiB", gate)

    def test_every_managed_config_renders_with_fail_closed_policy(self) -> None:
        template = self.environment.from_string(self.config_template)
        for profile in self.variables["hermes_shadow_profiles"]:
            rendered = template.render(hermes_profile=profile)
            config = yaml.safe_load(rendered)
            self.assertEqual(config["approvals"]["mode"], "manual")
            self.assertEqual(config["approvals"]["cron_mode"], "deny")
            self.assertFalse(config["security"]["tirith_fail_open"])
            self.assertTrue(config["memory"]["write_approval"])
            self.assertTrue(config["skills"]["write_approval"])
            self.assertFalse(config["terminal"]["docker_network"])
            self.assertFalse(config["terminal"]["docker_mount_cwd_to_workspace"])
            self.assertFalse(config["terminal"]["docker_run_as_host_user"])
            self.assertEqual(config["terminal"]["docker_forward_env"], [])
            self.assertEqual(config["terminal"]["docker_volumes"], [])
            self.assertEqual(config["delegation"]["max_iterations"], 12)
            self.assertEqual(config["delegation"]["max_concurrent_children"], 2)
            self.assertEqual(config["delegation"]["max_spawn_depth"], 1)
            self.assertFalse(config["delegation"]["orchestrator_enabled"])
            self.assertEqual(config["display"]["tool_progress"], "off")
            self.assertFalse(config["display"]["busy_ack_enabled"])
            self.assertEqual(config["display"]["memory_notifications"], "off")
            self.assertEqual(config["onboarding"]["profile_build"], "off")
            self.assertEqual(config["unauthorized_dm_behavior"], "ignore")
            self.assertTrue(config["group_sessions_per_user"])
            self.assertTrue(config["discord"]["require_mention"])
            self.assertTrue(config["discord"]["thread_require_mention"])
            self.assertEqual(config["discord"]["allow_bots"], "none")
            self.assertFalse(config["discord"]["history_backfill"])
            self.assertFalse(config["discord"]["missed_message_backfill"]["enabled"])
            self.assertFalse(config["discord"]["reactions"])
            self.assertFalse(
                config["gateway"]["platforms"]["discord"]["extra"]["slash_commands"]
            )

    def test_every_service_is_scoped_and_boot_disabled(self) -> None:
        template = self.environment.from_string(self.service_template)
        common = {
            "hermes_shadow_audit_live": self.variables["hermes_shadow_audit_live"],
            "hermes_shadow_contract_live": self.variables[
                "hermes_shadow_contract_live"
            ],
            "hermes_shadow_runtime_binary": self.variables[
                "hermes_shadow_runtime_binary"
            ],
            "hermes_discord_audit_live": self.variables["hermes_discord_audit_live"],
            "hermes_discord_contract_live": self.variables[
                "hermes_discord_contract_live"
            ],
            "hermes_automation_audit_live": self.variables[
                "hermes_automation_audit_live"
            ],
            "hermes_automation_contract_live": self.variables[
                "hermes_automation_contract_live"
            ],
        }
        for profile in self.variables["hermes_shadow_profiles"]:
            rendered = template.render(hermes_profile=profile, **common)
            self.assertIn(f"User={profile['user']}", rendered)
            self.assertIn(f"Group={profile['group']}", rendered)
            self.assertIn(f"HERMES_HOME={profile['home']}", rendered)
            self.assertIn("HERMES_DOCKER_BINARY=/usr/bin/podman", rendered)
            self.assertIn("NoNewPrivileges=true", rendered)
            self.assertIn("ProtectSystem=strict", rendered)
            self.assertIn("CapabilityBoundingSet=", rendered)
            self.assertIn(
                f"ConditionPathExists=/etc/hermes/{profile['name']}/.shadow-ready",
                rendered,
            )
            self.assertIn(
                f"EnvironmentFile=/etc/hermes/{profile['name']}/.env",
                rendered,
            )
            self.assertIn("hermes-discord-cutover-audit", rendered)
            self.assertIn("hermes-automation-contract-audit", rendered)
            self.assertNotIn("docker.sock", rendered)
            self.assertNotIn("sudo", rendered)
            self.assertNotIn("ListenStream", rendered)

        start = self.task("Start boot-disabled Hermes shadow gateways")
        self.assertIn("enabled: false", start)
        self.assertIn("state: started", start)
        self.assertIn("hermes_shadow_mode == 'shadow'", start)

        inspect = self.task("Inspect legacy OpenClaw listeners before Hermes start")
        reject = self.task("Reject concurrent OpenClaw and Hermes gateways")
        self.assertIn("- ss", inspect)
        for port in ("18789", "19789", "19790"):
            self.assertIn(port, reject)
        self.assertIn("break-before-make", reject)

    def test_new_runtime_uses_only_locked_reviewed_artifacts(self) -> None:
        provenance = self.task("Require reviewed Hermes release provenance")
        gate = self.task("Require reviewed locked artifacts for a new runtime")
        uv_download = self.task("Download reviewed uv release archive")
        uv_verify = self.task("Require exact Hermes-managed uv version")
        checkout = self.task("Check out exact official Hermes source")
        sync = self.task("Synchronize only locked Hermes dependencies")
        install_method = self.task("Record native Hermes Git install method")
        self.assertIn("hermes_shadow_install_ref", provenance)
        self.assertIn("hermes_shadow_expected_commit", provenance)
        self.assertIn("hermes_shadow_expected_tag_object", provenance)
        self.assertIn("hermes_shadow_install_approved", gate)
        self.assertIn("^[0-9a-f]{64}$", gate)
        self.assertIn("when: not hermes_shadow_runtime.stat.exists", gate)
        self.assertIn("hermes_shadow_uv_archive_sha256", uv_download)
        self.assertIn("hermes_shadow_uv_version", uv_verify)
        self.assertIn("(?:\\\\s|$)", uv_verify)
        self.assertIn("Expected reviewed uv", uv_verify)
        self.assertIn("hermes_shadow_expected_commit", checkout)
        self.assertIn("--locked", sync)
        self.assertIn("--extra", sync)
        self.assertIn("UV_CACHE_DIR", sync)
        self.assertIn("hermes_shadow_uv_cache_dir", sync)
        self.assertIn("XDG_CONFIG_HOME", sync)
        self.assertIn("XDG_CONFIG_DIRS", sync)
        self.assertIn("HOME: /var/lib/hermes/bootstrap", sync)
        self.assertIn("UV_NO_ENV_FILE", sync)
        self.assertNotIn("UV_NO_CONFIG", sync)
        self.assertNotIn("pip install", sync)
        self.assertNotIn("npm", self.playbook)
        self.assertNotIn("install.sh", self.playbook)
        self.assertIn('content: "git\\n"', install_method)
        launcher = self.task("Install Hermes launcher")
        self.assertIn("unset PYTHONPATH", launcher)
        self.assertIn("/bin/python", launcher)
        self.assertIn("/hermes", launcher)
        source = self.task("Require exact Hermes source")
        self.assertIn("https://github.com/NousResearch/hermes-agent.git", source)
        self.assertIn("hermes_shadow_expected_commit", source)
        self.assertIn("hermes_shadow_expected_tag_object", source)
        self.assertIn("hermes_shadow_installed_tag_commit", source)
        self.assertIn("hermes_shadow_installed_status", source)
        self.assertNotIn("when:", source)

    def test_contract_and_playbook_forbid_production_authority(self) -> None:
        contract = CONTRACT.read_text(encoding="utf-8")
        self.assertIn('"productionDeliveryEnabled": false', contract)
        self.assertIn('"productionSchedulerEnabled": false', contract)
        self.assertIn('"productionRouteEnabled": false', contract)
        self.assertIn('"dockerGroup": false', contract)
        self.assertIn('"dockerSocket": false', contract)
        self.assertNotIn("DISCORD_BOT_TOKEN", self.playbook)
        self.assertNotIn("GATEWAY_ALLOW_ALL_USERS", self.playbook)
        self.assertNotIn("docker_group", self.playbook)
        self.assertIn(
            "Reject Discord enrollment in Hermes shadow environments",
            self.playbook,
        )
        self.assertIn("is search('(?m)^DISCORD_')", self.playbook)

    def test_bootstrap_removes_markers_and_stops_all_units(self) -> None:
        markers = self.task("Remove Hermes readiness markers during bootstrap")
        stopped = self.task("Keep Hermes gateways stopped during bootstrap")
        self.assertIn("state: absent", markers)
        self.assertIn("hermes_shadow_mode == 'bootstrap'", markers)
        self.assertIn("/etc/hermes/{{ item.name }}/.shadow-ready", markers)
        self.assertIn("enabled: false", stopped)
        self.assertIn("state: stopped", stopped)
        create = self.task("Create Hermes shadow readiness markers")
        self.assertIn("/etc/hermes/{{ item.name }}/.shadow-ready", create)
        self.assertIn("owner: root", create)
        legacy = self.task("Remove legacy profile-writable Hermes readiness markers")
        self.assertIn("{{ item.home }}/.shadow-ready", legacy)
        self.assertIn("state: absent", legacy)

    def test_discord_contract_is_deployed_and_validated_without_secrets(self) -> None:
        contract = self.task("Deploy Hermes Discord cutover contract")
        audit = self.task("Deploy Hermes Discord contract audit")
        sources = self.task("Deploy pinned Hermes Discord audit sources")
        validation = self.task("Validate deployed Hermes Discord cutover contract")
        environment = self.task("Seed root-managed Hermes service environment once")
        local_environment = self.task(
            "Remove profile-local environment files from Hermes shadow"
        )
        self.assertIn("hermes_discord_contract_source", contract)
        self.assertIn("hermes_discord_audit_source", audit)
        self.assertIn("discord-regressions.json", sources)
        self.assertIn("openclaw-delivery-cutover-audit.py", sources)
        self.assertIn("--repository-root", validation)
        self.assertIn("/etc/hermes/{{ item.name }}/.env", environment)
        self.assertIn("owner: root", environment)
        self.assertIn('group: "{{ item.group }}"', environment)
        self.assertIn('mode: "0440"', environment)
        self.assertIn("{{ item.home }}/.env", local_environment)
        self.assertIn("state: absent", local_environment)

    def test_rigel_schedule_is_root_owned_and_not_activated(self) -> None:
        script = self.task("Deploy deterministic Rigel academic schedule")
        declaration = self.task("Deploy paused Rigel academic job declaration")
        self.assertIn("/var/lib/hermes/rigel/scripts", script)
        self.assertIn("owner: root", script)
        self.assertIn('mode: "0550"', script)
        self.assertIn("/etc/hermes/rigel", declaration)
        self.assertNotIn("hermes cron create", self.playbook)
        self.assertNotIn("jobs.json", self.playbook)
        self.assertEqual(self.rigel_job["schedule"], "every 30m")
        self.assertTrue(self.rigel_job["no_agent"])
        self.assertEqual(self.rigel_job["deliver"], "discord")
        self.assertEqual(self.rigel_job["expected_idle_stdout"], "")
        self.assertEqual(self.rigel_job["expected_idle_model_calls"], 0)
        self.assertEqual(
            self.rigel_job["desired_state"],
            "paused-until-cutover",
        )
        self.assertNotIn("HEARTBEAT_OK", self.rigel_script)
        self.assertNotIn("[SILENT]", self.rigel_script)
        self.assertNotIn("subprocess", self.rigel_script)
        self.assertNotIn("provider", self.rigel_job)
        self.assertNotIn("model", self.rigel_job)

    def test_automation_contract_is_deployed_without_activation(self) -> None:
        contract = self.task("Deploy Hermes automation contract")
        audit = self.task("Deploy Hermes automation contract audit")
        sources = self.task("Deploy pinned Hermes automation audit sources")
        validation = self.task("Validate deployed Hermes automation contract")
        self.assertIn("hermes_automation_contract_source", contract)
        self.assertIn("hermes_automation_audit_source", audit)
        self.assertIn("automation-regressions.json", sources)
        self.assertIn("openclaw-control-plane-inventory.py", sources)
        self.assertIn("openclaw-health-receiver.yml", sources)
        self.assertIn("--repository-root", validation)
        self.assertNotIn("hermes cron create", self.playbook)
        self.assertNotIn(
            "systemd_service:\n        name: hermes-automation", self.playbook
        )

    def test_operating_contracts_are_root_owned(self) -> None:
        task = self.task("Deploy root-owned Hermes operating contracts")
        self.assertIn("/AGENTS.md", task)
        self.assertIn("owner: root", task)
        self.assertIn('mode: "0440"', task)
        for profile in self.variables["hermes_shadow_profiles"]:
            source = (
                ROOT / "files" / "hermes" / "profiles" / profile["name"] / "AGENTS.md"
            )
            self.assertTrue(source.is_file())
            self.assertFalse(source.is_symlink())


if __name__ == "__main__":
    unittest.main()
