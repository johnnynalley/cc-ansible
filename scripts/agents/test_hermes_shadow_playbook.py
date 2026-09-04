#!/usr/bin/env python3
"""Regression tests for the inert Hermes shadow deployment."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined
from jinja2.nativetypes import NativeEnvironment

ROOT = Path(__file__).parents[2]
PLAYBOOK = ROOT / "playbooks" / "agents" / "hermes-shadow.yml"
VARS = ROOT / "inventory" / "group_vars" / "hermes_hosts" / "vars.yml"
SERVICE = ROOT / "templates" / "hermes" / "hermes-gateway-hardening.conf.j2"
LAUNCHER = ROOT / "templates" / "hermes" / "hermes-launcher.sh.j2"
UPDATE_SERVICE = ROOT / "templates" / "hermes" / "hermes-native-update.service.j2"
UPDATE_TIMER = ROOT / "templates" / "hermes" / "hermes-native-update.timer.j2"
TIRITH_UPDATE_SERVICE = (
    ROOT / "templates" / "hermes" / "hermes-tirith-native-update.service.j2"
)
TIRITH_UPDATE_TIMER = (
    ROOT / "templates" / "hermes" / "hermes-tirith-native-update.timer.j2"
)
UPDATE_SUDOERS = ROOT / "templates" / "hermes" / "hermes-native-update.sudoers.j2"
CONTRACT = ROOT / "files" / "hermes" / "shadow-target.json"
RIGEL_JOB = ROOT / "files" / "hermes" / "jobs" / "rigel-academic-alerts.json"
RIGEL_SCRIPT = ROOT / "scripts" / "agents" / "hermes-rigel-schedule.py"
INVENTORY = ROOT / "inventory" / "hosts.ini"
REHEARSAL_INVENTORY = ROOT / "inventory" / "hermes-replacement-rehearsal.ini"
REHEARSAL_PLAYBOOK = (
    ROOT / "playbooks" / "agents" / "hermes-replacement-node-rehearsal.yml"
)
REHEARSAL_CONTAINERFILE = ROOT / "files" / "hermes" / "rehearsal" / "Containerfile"
SITE = ROOT / "site.yml"
DOCKER_INVENTORY_PLAYBOOK = (
    ROOT / "playbooks" / "agents" / "hermes-docker-inventory.yml"
)
STAR_VALIDATOR = (
    ROOT / "scripts" / "agents" / "hermes-star-dispatch-privacy-validate.py"
)


class HermesShadowPlaybookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.playbook = PLAYBOOK.read_text(encoding="utf-8")
        cls.raw_variables = yaml.safe_load(VARS.read_text(encoding="utf-8"))
        cls.variables = dict(cls.raw_variables)
        cls.service_template = SERVICE.read_text(encoding="utf-8")
        cls.launcher_template = LAUNCHER.read_text(encoding="utf-8")
        cls.update_service_template = UPDATE_SERVICE.read_text(encoding="utf-8")
        cls.update_timer_template = UPDATE_TIMER.read_text(encoding="utf-8")
        cls.tirith_update_service_template = TIRITH_UPDATE_SERVICE.read_text(
            encoding="utf-8"
        )
        cls.tirith_update_timer_template = TIRITH_UPDATE_TIMER.read_text(
            encoding="utf-8"
        )
        cls.update_sudoers_template = UPDATE_SUDOERS.read_text(encoding="utf-8")
        cls.rigel_job = yaml.safe_load(RIGEL_JOB.read_text(encoding="utf-8"))
        cls.rigel_script = RIGEL_SCRIPT.read_text(encoding="utf-8")
        cls.environment = Environment(undefined=StrictUndefined, autoescape=False)
        cls.environment.filters["ternary"] = (
            lambda value, true_value, false_value: true_value if value else false_value
        )
        cls.environment.filters["bool"] = bool
        cls.variables["hermes_shadow_profiles"] = cls.resolved_profiles(False)

    @classmethod
    def resolved_profiles(cls, dedicated_rigel: bool) -> list[dict]:
        environment = NativeEnvironment(
            undefined=StrictUndefined,
            autoescape=False,
        )
        environment.filters["bool"] = bool
        context = dict(cls.raw_variables)
        context["hermes_rigel_dedicated_discord_enabled"] = dedicated_rigel

        def resolve(value):
            if isinstance(value, dict):
                return {key: resolve(item) for key, item in value.items()}
            if isinstance(value, list):
                return [resolve(item) for item in value]
            if isinstance(value, str) and ("{{" in value or "{%" in value):
                return environment.from_string(value).render(**context)
            return value

        return resolve(cls.raw_variables["hermes_shadow_profiles"])

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
        self.assertFalse(self.variables["hermes_shadow_replacement_rehearsal"])
        stop = self.task("Stop Hermes shadow units when disabled")
        self.assertIn("enabled: false", stop)
        self.assertIn("state: stopped", stop)
        timer_stop = self.task("Stop Hermes native update timers when disabled")
        self.assertIn("enabled: false", timer_stop)
        self.assertIn("state: stopped", timer_stop)
        self.assertIn("ansible.builtin.meta: end_host", self.playbook)

    def test_replacement_rehearsal_is_disposable_bootstrap_only(self) -> None:
        rehearsal = REHEARSAL_PLAYBOOK.read_text(encoding="utf-8")
        inventory = REHEARSAL_INVENTORY.read_text(encoding="utf-8")
        containerfile = REHEARSAL_CONTAINERFILE.read_text(encoding="utf-8")
        self.assertIn("[hermes_hosts]\n", inventory)
        self.assertNotIn("jn-t14s-lin", inventory)
        self.assertIn("rebuild-hermes-platform-on-disposable-replacement-node", rehearsal)
        self.assertIn("hermes_shadow_mode: bootstrap", rehearsal)
        self.assertIn("hermes_shadow_start_approved: false", rehearsal)
        self.assertIn("hermes_native_updates_automatic: false", rehearsal)
        self.assertIn("Reject Discord credentials on the replacement bootstrap", rehearsal)
        self.assertIn("Stop before disposable resource creation in check mode", rehearsal)
        self.assertIn("when: ansible_check_mode", rehearsal)
        self.assertGreaterEqual(rehearsal.count("state: absent"), 4)
        self.assertIn("FROM docker.io/library/ubuntu:24.04", containerfile)
        self.assertIn('CMD ["/sbin/init"]', containerfile)

    def test_replacement_rehearsal_cannot_target_production(self) -> None:
        gate = self.task("Require explicit Hermes shadow approval")
        self.assertIn("hermes_shadow_replacement_rehearsal_host", gate)
        self.assertIn("containers.podman.podman", gate)
        self.assertIn("hermes_shadow_mode == 'bootstrap'", gate)
        self.assertIn("not hermes_shadow_start_approved | bool", gate)
        self.assertIn("sourceFilesDirectlyReadableByHermes | bool", gate)
        self.assertIn("sourceStateCopiedWholesale", gate)
        self.assertIn("sourceStateDirectlyMounted", gate)
        capacity = self.task("Require reviewed same-host Hermes capacity")
        self.assertIn(
            "hermes_shadow_replacement_rehearsal_minimum_available_memory_mib",
            capacity,
        )
        self.assertIn("hermes_shadow_replacement_rehearsal_minimum_free_disk_gib", capacity)

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

    def test_profile_identities_have_a_narrow_convergence_tag(self) -> None:
        task = self.task("Seed profile-owned Hermes identities once")
        self.assertIn("backup: true", task)
        self.assertIn("force: false", task)
        self.assertIn('owner: "{{ item.user }}"', task)
        self.assertIn("- hermes_profile_identities", task)
        self.assertNotIn("systemd_service", task)

    def test_profiles_are_distinct_and_execution_authority_is_profile_scoped(self) -> None:
        profiles = self.variables["hermes_shadow_profiles"]
        self.assertEqual(
            [item["name"] for item in profiles], ["astra", "dubble", "rigel"]
        )
        self.assertEqual(len({item["user"] for item in profiles}), 3)
        self.assertEqual(len({item["uid"] for item in profiles}), 3)
        self.assertEqual(len({item["subid_start"] for item in profiles}), 3)
        for profile in profiles:
            self.assertEqual(profile["user"], f"hermes-{profile['name']}")
            self.assertEqual(
                profile["account_home"], f"/var/lib/hermes/{profile['name']}"
            )
            self.assertEqual(
                profile["home"],
                f"/var/lib/hermes/{profile['name']}/.hermes/profiles/"
                f"{profile['name']}",
            )
            self.assertEqual(
                profile["unit"], f"hermes-gateway-{profile['name']}.service"
            )
        self.assertEqual(
            [profile["terminal_backend"] for profile in profiles],
            ["local", "docker", "local"],
        )
        rigel = profiles[2]
        self.assertEqual(
            rigel["terminal_cwd"],
            "/var/lib/hermes/rigel/.hermes/profiles/rigel/imported-data",
        )
        self.assertEqual(
            rigel["gateway_working_directory"], rigel["terminal_cwd"]
        )
        forbidden_native_keys = {
            "model_provider",
            "model_default",
            "model_max_tokens",
            "model_supports_vision",
            "fallback_providers",
            "auxiliary_approval",
            "auxiliary_background_review",
            "image_input_mode",
            "approval_mode",
            "approval_smart_policy",
            "cron_approval_mode",
            "memory_write_approval",
            "memory_nudge_interval",
            "memory_char_limit",
            "user_char_limit",
            "skills_write_approval",
            "skills_creation_nudge_interval",
            "curator",
            "allow_any_attachment",
            "native_messaging_bridge",
            "disabled_toolsets",
            "approval_deny",
            "bot_peers",
            "todo_stop_guard",
            "max_todo_stop_nudges",
            "context_engine",
            "memory_provider",
            "plugins_enabled",
            "toolsets",
        }
        for profile in profiles:
            self.assertTrue(forbidden_native_keys.isdisjoint(profile))
            self.assertFalse(any(key.startswith("discord_") for key in profile))
        for forbidden_reference in (
            "item.model_provider",
            "item.model_default",
            "item.fallback_providers",
            "item.approval_mode",
            "item.cron_approval_mode",
            "item.disabled_toolsets",
            "item.discord_allowed_users",
        ):
            self.assertNotIn(forbidden_reference, self.playbook)
        self.assertEqual(
            self.variables["hermes_native_messaging_tools"],
            [
                "conversations_list",
                "conversation_get",
                "messages_read",
                "attachments_fetch",
                "events_poll",
                "events_wait",
                "messages_send",
                "channels_list",
            ],
        )
        self.assertEqual(
            self.variables["hermes_native_post_setup_keys"],
            ["ddgs", "agent_browser"],
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

    def test_read_only_safety_probes_execute_in_check_mode(self) -> None:
        task_names = (
            "Read Hermes target logical CPU capacity",
            "Read Hermes target available memory",
            "Read Hermes target free root filesystem space",
            "Inspect Hermes source origin",
            "Inspect Hermes source commit",
            "Inspect Hermes source branch",
            "Inspect official Hermes main commit",
            "Inspect reviewed Hermes release tag object",
            "Resolve reviewed Hermes release tag",
            "Inspect tracked Hermes worktree modifications",
            "Inspect staged Hermes source modifications",
            "Inspect untracked Hermes source paths",
            "Validate deployed Hermes shadow contract",
            "Validate deployed Hermes automation contract",
            "Inspect legacy OpenClaw listeners before Hermes start",
        )
        for name in task_names:
            with self.subTest(task=name):
                self.assertIn("check_mode: false", self.task(name))

    def test_established_native_profile_config_is_required_not_rewritten(self) -> None:
        inspect = self.task("Inspect native Hermes profile configuration")
        require = self.task("Require established native Hermes profile configuration")
        seed = self.task("Seed mutable Hermes profile config once")
        self.assertIn("{{ item.home }}/config.yaml", inspect)
        self.assertIn("hermes_shadow_mode != 'bootstrap'", require)
        self.assertIn("Restore native profile state before platform", require)
        self.assertIn("hermes_shadow_mode == 'bootstrap'", seed)
        self.assertIn("force: false", seed)

    def test_every_pinned_profile_data_destination_parent_is_declared(self) -> None:
        directories = self.task("Create Hermes root-owned deployment directories")
        pinned_sources = self.task("Deploy pinned Hermes profile-data source contracts")
        self.assertIn(
            "/usr/local/share/hermes-shadow/repository/files/hermes",
            directories,
        )
        self.assertIn(
            "/usr/local/share/hermes-shadow/repository/files/openclaw",
            directories,
        )
        self.assertIn("files/hermes/profile-import-contract.json", pinned_sources)
        self.assertIn(
            "files/openclaw/workspace-migration-policy.json", pinned_sources
        )

    def test_inventory_does_not_own_native_discord_routes(self) -> None:
        for profile in self.variables["hermes_shadow_profiles"]:
            self.assertFalse(any(key.startswith("discord_") for key in profile))

    def test_star_validation_is_idempotent_during_plugin_promotion(self) -> None:
        validator = STAR_VALIDATOR.read_text(encoding="utf-8")
        promotion = DOCKER_INVENTORY_PLAYBOOK.read_text(encoding="utf-8")
        self.assertIn("sys.dont_write_bytecode = True", validator)
        self.assertIn("Remove stale managed plugin bytecode caches", promotion)
        self.assertIn("hermes_star_privacy_plugin_runtime_root", promotion)

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
            "hermes_shadow_runtime_venv": self.variables[
                "hermes_shadow_runtime_venv"
            ],
            "hermes_shadow_runtime_root": self.variables[
                "hermes_shadow_runtime_root"
            ],
            "hermes_agent_browser_selector_live": self.variables[
                "hermes_agent_browser_selector_live"
            ],
            "hermes_discord_runtime_audit_live": self.variables[
                "hermes_discord_runtime_audit_live"
            ],
            "hermes_runtime_readers_group": self.variables[
                "hermes_runtime_readers_group"
            ],
            "hermes_automation_audit_live": self.variables[
                "hermes_automation_audit_live"
            ],
            "hermes_automation_contract_live": self.variables[
                "hermes_automation_contract_live"
            ],
            "hermes_profile_skills_validator_live": self.variables[
                "hermes_profile_skills_validator_live"
            ],
            "hermes_profile_skills_contract_live": self.variables[
                "hermes_profile_skills_contract_live"
            ],
            "hermes_shared_self_evolution_source": self.variables[
                "hermes_shared_self_evolution_source"
            ],
            "hermes_profile_data_stager_live": self.variables[
                "hermes_profile_data_stager_live"
            ],
            "hermes_profile_data_contract_live": self.variables[
                "hermes_profile_data_contract_live"
            ],
            "hermes_profile_data_root": self.variables[
                "hermes_profile_data_root"
            ],
            "hermes_profile_data_manifest_live": self.variables[
                "hermes_profile_data_manifest_live"
            ],
            "hermes_profile_transformer_live": self.variables[
                "hermes_profile_transformer_live"
            ],
            "hermes_profile_transforms_contract_live": self.variables[
                "hermes_profile_transforms_contract_live"
            ],
            "hermes_profile_transforms_root": self.variables[
                "hermes_profile_transforms_root"
            ],
            "hermes_profile_transforms_manifest_live": self.variables[
                "hermes_profile_transforms_manifest_live"
            ],
            "hermes_star_privacy_validator_live": self.variables[
                "hermes_star_privacy_validator_live"
            ],
            "hermes_star_privacy_plugin_managed_root": self.variables[
                "hermes_star_privacy_plugin_managed_root"
            ],
            "hermes_star_privacy_plugin_runtime_root": self.variables[
                "hermes_star_privacy_plugin_runtime_root"
            ],
            "hermes_docker_inventory_private_key": self.variables[
                "hermes_docker_inventory_private_key"
            ],
            "hermes_docker_update_private_key": self.variables[
                "hermes_docker_update_private_key"
            ],
            "hermes_docker_inventory_validator_live": self.variables[
                "hermes_docker_inventory_validator_live"
            ],
            "hermes_docker_inventory_plugin_managed_root": self.variables[
                "hermes_docker_inventory_plugin_managed_root"
            ],
            "hermes_docker_inventory_plugin_runtime_root": self.variables[
                "hermes_docker_inventory_plugin_runtime_root"
            ],
            "hermes_docker_inventory_known_hosts": self.variables[
                "hermes_docker_inventory_known_hosts"
            ],
            "hermes_docker_inventory_endpoints": self.variables[
                "hermes_docker_inventory_endpoints"
            ],
            "hermes_arr_api_validator_live": self.variables[
                "hermes_arr_api_validator_live"
            ],
            "hermes_arr_api_plugin_managed_root": self.variables[
                "hermes_arr_api_plugin_managed_root"
            ],
            "hermes_arr_api_plugin_runtime_root": self.variables[
                "hermes_arr_api_plugin_runtime_root"
            ],
            "hermes_arr_api_socket": self.variables["hermes_arr_api_socket"],
            "hermes_arr_api_runtime_dir": self.variables[
                "hermes_arr_api_runtime_dir"
            ],
            "hermes_arr_api_group": self.variables["hermes_arr_api_group"],
            "hermes_host_admin_private_key": self.variables[
                "hermes_host_admin_private_key"
            ],
            "hermes_host_admin_validator_live": self.variables[
                "hermes_host_admin_validator_live"
            ],
            "hermes_host_admin_plugin_managed_root": self.variables[
                "hermes_host_admin_plugin_managed_root"
            ],
            "hermes_host_admin_plugin_runtime_root": self.variables[
                "hermes_host_admin_plugin_runtime_root"
            ],
            "hermes_host_admin_endpoints": self.variables[
                "hermes_host_admin_endpoints"
            ],
            "hermes_host_admin_known_hosts": self.variables[
                "hermes_host_admin_known_hosts"
            ],
            "hermes_compose_admin_private_key": self.variables[
                "hermes_compose_admin_private_key"
            ],
            "hermes_compose_admin_validator_live": self.variables[
                "hermes_compose_admin_validator_live"
            ],
            "hermes_compose_admin_plugin_managed_root": self.variables[
                "hermes_compose_admin_plugin_managed_root"
            ],
            "hermes_compose_admin_plugin_runtime_root": self.variables[
                "hermes_compose_admin_plugin_runtime_root"
            ],
            "hermes_compose_admin_endpoints": self.variables[
                "hermes_compose_admin_endpoints"
            ],
            "hermes_compose_admin_known_hosts": self.variables[
                "hermes_compose_admin_known_hosts"
            ],
            "hermes_discord_parity_validator_live": self.variables[
                "hermes_discord_parity_validator_live"
            ],
            "hermes_discord_parity_plugin_managed_root": self.variables[
                "hermes_discord_parity_plugin_managed_root"
            ],
            "hermes_discord_parity_plugin_runtime_root": self.variables[
                "hermes_discord_parity_plugin_runtime_root"
            ],
            "hermes_discord_parity_policy_live": self.variables[
                "hermes_discord_parity_policy_live"
            ],
            "hermes_dubble_discord_parity_plugin_managed_root": self.variables[
                "hermes_dubble_discord_parity_plugin_managed_root"
            ],
            "hermes_dubble_discord_parity_plugin_runtime_root": self.variables[
                "hermes_dubble_discord_parity_plugin_runtime_root"
            ],
            "hermes_dubble_discord_parity_policy_live": self.variables[
                "hermes_dubble_discord_parity_policy_live"
            ],
            "hermes_astra_handoff_validator_live": self.variables[
                "hermes_astra_handoff_validator_live"
            ],
            "hermes_astra_handoff_plugin_managed_root": self.variables[
                "hermes_astra_handoff_plugin_managed_root"
            ],
            "hermes_astra_handoff_plugin_runtime_root": self.variables[
                "hermes_astra_handoff_plugin_runtime_root"
            ],
            "hermes_lcm_plugin_managed_root": self.variables[
                "hermes_lcm_plugin_managed_root"
            ],
            "hermes_astra_workspace_source": self.variables[
                "hermes_astra_workspace_source"
            ],
            "hermes_astra_workspace_live": self.variables[
                "hermes_astra_workspace_live"
            ],
            "hermes_tirith_binary": self.variables["hermes_tirith_binary"],
            "hermes_mem0_fastembed_cache": self.variables[
                "hermes_mem0_fastembed_cache"
            ],
            **{
                key: self.variables[key]
                for key in (
                    "hermes_health_report_group",
                    "hermes_health_receiver_report_dir",
                    "hermes_health_receiver_db",
                    "hermes_health_receiver_config_dir",
                    "hermes_rigel_astra_liaison_group",
                    "hermes_rigel_astra_liaison_plugin_managed_root",
                    "hermes_rigel_astra_liaison_plugin_runtime_root",
                    "hermes_rigel_astra_liaison_policy_live",
                    "hermes_rigel_astra_liaison_runtime_dir",
                    "hermes_rigel_astra_liaison_socket",
                    "hermes_rigel_astra_liaison_validator_live",
                )
            },
            "hermes_gateway_readiness_marker": self.variables[
                "hermes_gateway_readiness_marker"
            ],
        }
        for profile in self.variables["hermes_shadow_profiles"]:
            rendered = template.render(hermes_profile=profile, **common)
            self.assertNotIn("\nUser=", rendered)
            self.assertNotIn("\nGroup=", rendered)
            self.assertNotIn("\nExecStart=", rendered)
            self.assertNotIn("\nExecStop=", rendered)
            self.assertNotIn("\nRestart=", rendered)
            supplementary_groups = self.variables["hermes_runtime_readers_group"]
            if profile["name"] == "astra":
                supplementary_groups += f" {self.variables['hermes_health_report_group']}"
            self.assertIn(
                f"SupplementaryGroups={supplementary_groups}\n"
                f"Environment=HERMES_MANAGED_DIR=/etc/hermes/{profile['name']}",
                rendered,
            )
            self.assertNotIn("HERMES_HOME=", rendered)
            if profile["terminal_backend"] == "docker":
                self.assertIn("HERMES_DOCKER_BINARY=/usr/bin/podman", rendered)
            else:
                self.assertNotIn("HERMES_DOCKER_BINARY=", rendered)
            if profile.get("gateway_working_directory"):
                self.assertIn(
                    f"WorkingDirectory={profile['gateway_working_directory']}",
                    rendered,
                )
                self.assertIn(
                    f"Environment=TERMINAL_CWD={profile['terminal_cwd']}", rendered
                )
            else:
                self.assertNotIn("\nWorkingDirectory=", rendered)
                self.assertNotIn("\nEnvironment=TERMINAL_CWD=", rendered)
            self.assertIn("TIRITH_OFFLINE=1", rendered)
            self.assertIn("NoNewPrivileges=true", rendered)
            self.assertIn("ProtectSystem=strict", rendered)
            if profile["name"] == "astra":
                self.assertIn("MemoryDenyWriteExecute=false", rendered)
                self.assertIn(
                    "RestrictNamespaces=~user mnt pid ipc net uts", rendered
                )
            else:
                self.assertIn("MemoryDenyWriteExecute=true", rendered)
                self.assertIn("RestrictNamespaces=true", rendered)
            self.assertIn("PrivateDevices=true", rendered)
            self.assertNotIn("DeviceAllow=/dev/fuse", rendered)
            self.assertNotIn("Delegate=yes", rendered)
            self.assertIn(
                "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6\n",
                rendered,
            )
            self.assertIn("CapabilityBoundingSet=", rendered)
            self.assertIn(
                f"ExecStartPre={self.variables['hermes_shadow_runtime_venv']}/bin/python "
                f"{self.variables['hermes_discord_runtime_audit_live']} "
                f"--home={profile['home']} --imports-only",
                rendered,
            )
            self.assertIn(
                f"ExecStartPost={self.variables['hermes_shadow_runtime_venv']}/bin/python "
                f"{self.variables['hermes_discord_runtime_audit_live']} "
                f"--home={profile['home']} --pid=${{MAINPID}} --timeout=30",
                rendered,
            )
            self.assertIn(
                f"ConditionPathExists=/etc/hermes/{profile['name']}/"
                f"{self.variables['hermes_gateway_readiness_marker']}",
                rendered,
            )
            self.assertIn(
                "EnvironmentFile="
                + profile.get(
                    "environment_file",
                    f"/etc/hermes/{profile['name']}/.env",
                ),
                rendered,
            )
            self.assertIn(
                f"Environment=LCM_DATABASE_PATH={profile['home']}/lcm.db",
                rendered,
            )
            self.assertIn(
                f"EnvironmentFile=-{profile['home']}/lcm.env",
                rendered,
            )
            self.assertIn(
                f"Environment=MEM0_DIR={profile['home']}/mem0",
                rendered,
            )
            for managed_option in (
                "LCM_EMBEDDINGS_ENABLED=",
                "LCM_EMBEDDING_PROVIDER=",
                "LCM_EMBEDDING_MODEL=",
                "LCM_PROACTIVE_RECALL_ENABLED=",
                "LCM_TEMPORAL_ROLLUPS_ENABLED=",
            ):
                self.assertNotIn(managed_option, rendered)
            self.assertNotIn("hermes-discord-cutover-audit", rendered)
            self.assertNotIn("hermes-automation-contract-audit", rendered)
            self.assertNotIn("managed-policy.sha256", rendered)
            self.assertIn(
                f"ExecStartPre={self.variables['hermes_tirith_binary']} --version",
                rendered,
            )
            self.assertNotIn(
                f"BindReadOnlyPaths=/etc/hermes/{profile['name']}/skills:",
                rendered,
            )
            self.assertIn(
                f"--mode runtime --profile {profile['name']}", rendered
            )
            self.assertIn(
                f"BindPaths=/var/lib/hermes/profile-data/{profile['name']}/writable:"
                f"{profile['home']}/imported-data",
                rendered,
            )
            self.assertIn(
                f"BindReadOnlyPaths=/var/lib/hermes/profile-data/{profile['name']}/managed:"
                f"{profile['home']}/managed-data",
                rendered,
            )

            self.assertIn("hermes-profile-data-stage", rendered)
            self.assertIn("--allow-writable-drift", rendered)
            self.assertIn("ExecStartPre=+/usr/local/libexec/hermes-profile-data-stage", rendered)
            self.assertIn(
                "ExecStartPre=+/usr/local/libexec/hermes-profile-transform",
                rendered,
            )
            self.assertIn(
                f"BindPaths=/var/lib/hermes/profile-transforms/{profile['name']}/writable:"
                f"{profile['home']}/transformed-data",
                rendered,
            )
            self.assertIn(
                f"BindReadOnlyPaths=/var/lib/hermes/profile-transforms/{profile['name']}/managed:"
                f"{profile['home']}/transformed-managed",
                rendered,
            )
            self.assertIn(
                f"--mode runtime --profile {profile['name']}", rendered
            )
            self.assertNotIn("docker.sock", rendered)
            self.assertNotIn("sudo", rendered)
            self.assertNotIn("ListenStream", rendered)
            if profile["name"] == "astra":
                self.assertIn("hermes-star-dispatch-privacy-validate", rendered)
                self.assertIn(
                    "BindPaths=/home/johnny/cc-ansible:"
                    "/var/lib/hermes/astra/workspaces/cc-ansible",
                    rendered,
                )
                self.assertIn(
                    "ReadWritePaths=/var/lib/hermes/astra/workspaces/cc-ansible",
                    rendered,
                )
                self.assertIn(
                    "BindReadOnlyPaths=/etc/hermes/astra/plugins/"
                    "star-dispatch-privacy:"
                    "/var/lib/hermes/astra/.hermes/profiles/astra/plugins/"
                    "star-dispatch-privacy",
                    rendered,
                )
            else:
                self.assertNotIn("hermes-star-dispatch-privacy-validate", rendered)
                self.assertNotIn("star-dispatch-privacy", rendered)
                self.assertNotIn("/home/johnny/cc-ansible", rendered)

    def test_shared_self_evolution_bind_is_the_only_shared_skill_projection(self) -> None:
        self.assertEqual(
            self.variables["hermes_shared_self_evolution_source"],
            "/var/lib/hermes/astra/.hermes/profiles/astra/skills/self-evolution",
        )
        self.assertIn(
            "Create read-only shared self-evolution mountpoints", self.playbook
        )
        self.assertIn(
            "BindReadOnlyPaths={{ hermes_shared_self_evolution_source }}:"
            "{{ hermes_profile.home }}/skills/self-evolution",
            self.service_template,
        )
        self.assertIn("hermes_profile.name in ['dubble', 'rigel']", self.service_template)
        self.assertNotIn("/skills/managed", self.service_template)

    def test_astra_workspace_access_is_acl_scoped_without_home_or_sudo(self) -> None:
        self.assertEqual(
            self.variables["hermes_astra_workspace_source"],
            "/home/johnny/cc-ansible",
        )
        self.assertEqual(
            self.variables["hermes_astra_workspace_live"],
            "/var/lib/hermes/astra/workspaces/cc-ansible",
        )
        access = self.task("Grant Astra access to existing managed workspace content")
        inherited = self.task(
            "Grant Astra inherited access in managed workspace directories"
        )
        self.assertIn("ansible.posix.acl", access)
        self.assertIn("permissions: rwX", access)
        self.assertIn("recursive: true", access)
        self.assertIn("permissions: rwx", inherited)
        self.assertIn("default: true", inherited)
        self.assertNotIn("/home/johnny/.ssh", access + inherited)
        self.assertNotIn("sudoers", access + inherited)

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
        self.assertIn("- messaging", sync)
        self.assertIn("- mem0", sync)
        self.assertIn("UV_CACHE_DIR", sync)
        self.assertIn("hermes_shadow_uv_cache_dir", sync)
        self.assertIn("XDG_CONFIG_HOME", sync)
        self.assertIn("XDG_CONFIG_DIRS", sync)
        self.assertIn("HOME: /var/lib/hermes/bootstrap", sync)
        self.assertIn("UV_NO_ENV_FILE", sync)
        self.assertNotIn("UV_NO_CONFIG", sync)
        self.assertNotIn("pip install", sync)
        self.assertNotIn("community.general.npm", self.playbook)
        self.assertNotIn("npm install", self.playbook)
        self.assertNotIn("npm ci", self.playbook)
        self.assertNotIn("install.sh", self.playbook)
        self.assertIn('content: "git\\n"', install_method)
        self.assertIn("owner: \"{{ hermes_native_update_user }}\"", install_method)
        self.assertIn("group: \"{{ hermes_native_update_group }}\"", install_method)
        launcher = self.task("Install Hermes launcher")
        self.assertIn("hermes-launcher.sh.j2", launcher)
        self.assertNotIn("when: not hermes_shadow_runtime.stat.exists", launcher)
        self.assertIn("unset PYTHONPATH", self.launcher_template)
        self.assertIn("/bin/python", self.launcher_template)
        self.assertIn("/hermes", self.launcher_template)

    def test_tirith_is_native_self_managed_offline_and_supply_chain_verified(self) -> None:
        approval = self.task("Require explicit Hermes shadow approval")
        provenance = self.task("Require reviewed Tirith bootstrap provenance")
        prerequisites = self.task("Install Hermes shadow host prerequisites")
        cosign_install = self.task("Install reviewed Cosign verifier")
        cosign_version = self.task("Require reviewed Cosign verifier version")
        assets = self.task("Download reviewed Tirith release assets")
        verify = self.task("Verify Tirith signed checksum provenance")
        install = self.task("Install Tirith native self-managed bootstrap binary")
        native = self.task("Require Tirith native self-update ownership")
        account_probe = self.task("Inspect realized Tirith native update account")
        update_dirs = self.task("Create Tirith self-managed update directories")
        allow = self.task("Prove Tirith allows a benign command offline")
        block = self.task("Prove Tirith blocks pipe-to-interpreter offline")
        self.assertIn("official-latest", provenance)
        self.assertIn("/var/lib/hermes-updater/.local/bin/tirith", provenance)
        self.assertIn("rootManagedCommandScanner", approval)
        self.assertIn("runtimeLazyInstallsEnabled", approval)
        self.assertIn("scannerRuntimeNetworkEnabled", approval)
        self.assertIn("privateUrlAccess", approval)
        self.assertIn("tirithFailOpen", approval)
        self.assertNotIn("- cosign", prerequisites)
        self.assertIn("hermes_cosign_url", cosign_install)
        self.assertIn("hermes_cosign_sha256", cosign_install)
        self.assertIn('mode: "0755"', cosign_install)
        self.assertIn("hermes_cosign_version", cosign_version)
        self.assertIn("checksum:", assets)
        self.assertIn("- not ansible_check_mode", assets)
        self.assertIn("hermes_tirith_bootstrap_required", assets)
        self.assertIn("hermes_cosign_binary", verify)
        self.assertIn("--certificate-identity-regexp", verify)
        self.assertIn("owner: root", install)
        self.assertIn("group: root", install)
        self.assertIn('mode: "0755"', install)
        self.assertIn("self-managed", native)
        self.assertIn("/usr/bin/getent", account_probe)
        self.assertIn("check_mode: false", account_probe)
        self.assertIn("rc not in [0, 2]", account_probe)
        self.assertIn("owner: root", update_dirs)
        self.assertIn("group: root", update_dirs)
        self.assertIn('TIRITH_OFFLINE: "1"', allow)
        self.assertIn("--no-daemon", allow)
        self.assertIn("failed_when: hermes_tirith_block_probe.rc != 1", block)
        source = self.task("Require clean official Hermes source track")
        self.assertIn("https://github.com/NousResearch/hermes-agent.git", source)
        self.assertIn("hermes_shadow_expected_commit", source)
        self.assertIn("hermes_shadow_origin_main_commit", source)
        self.assertIn("hermes_shadow_installed_branch", source)
        self.assertIn("hermes_shadow_expected_tag_object", source)
        self.assertIn("hermes_shadow_installed_tag_commit", source)
        self.assertIn("hermes_shadow_installed_worktree_diff", source)
        self.assertIn("hermes_shadow_installed_index_diff", source)
        self.assertIn("hermes_shadow_installed_untracked", source)
        self.assertNotIn("when:", source)
        for task_name in (
            "Inspect Hermes source origin",
            "Inspect Hermes source commit",
            "Inspect Hermes source branch",
            "Inspect official Hermes main commit",
            "Inspect reviewed Hermes release tag object",
            "Resolve reviewed Hermes release tag",
            "Inspect tracked Hermes worktree modifications",
            "Inspect staged Hermes source modifications",
            "Inspect untracked Hermes source paths",
        ):
            task = self.task(task_name)
            self.assertIn("- /usr/bin/git", task)
            self.assertIn("safe.directory={{ hermes_shadow_runtime_root }}", task)
            self.assertNotIn("/usr/sbin/runuser", task)
            self.assertNotIn("become_user:", task)
        self.assertIn(
            "--cached", self.task("Inspect staged Hermes source modifications")
        )
        self.assertIn(
            "--exclude-standard", self.task("Inspect untracked Hermes source paths")
        )

    def test_fresh_checkout_normalization_is_exact_and_fail_closed(self) -> None:
        paths = self.variables["hermes_shadow_fresh_checkout_eol_paths"]
        self.assertEqual(
            paths,
            [
                "scripts/ci/test_install_ps1_path_migration.ps1",
                "scripts/tests/test-install-ps1-gitbash-compatibility.ps1",
                "scripts/tests/test-install-ps1-stage-protocol.ps1",
            ],
        )
        probe = self.task("Prove fresh checkout drift is line-ending only")
        bounded = self.task("Require bounded fresh checkout line-ending drift")
        restore = self.task("Restore reviewed fresh checkout line endings")
        clean = self.task("Require clean fresh Hermes checkout")
        self.assertIn("--ignore-space-at-eol", probe)
        self.assertIn("not in [0, 1]", probe)
        self.assertIn("difference(hermes_shadow_fresh_checkout_eol_paths)", bounded)
        self.assertIn(
            "== hermes_shadow_fresh_checkout_changed_paths.stdout_lines | length",
            bounded,
        )
        self.assertIn("--source=HEAD", restore)
        self.assertIn("--worktree", restore)
        self.assertIn("diff", clean)
        self.assertIn("--quiet", clean)
        for task in (probe, bounded, restore, clean):
            self.assertIn("not hermes_shadow_runtime.stat.exists", task)

    def test_final_source_normalization_is_bounded_and_fail_closed(self) -> None:
        inspect = self.task("Inspect final Hermes source content drift")
        probe = self.task(
            "Prove final Hermes source drift is reviewed line endings only"
        )
        bounded = self.task("Require bounded final Hermes source drift")
        restore = self.task("Restore reviewed final Hermes source line endings")
        self.assertIn("diff", inspect)
        self.assertIn("--name-only", inspect)
        self.assertIn("--ignore-space-at-eol", probe)
        self.assertIn("not in [0, 1]", probe)
        self.assertIn("difference(hermes_shadow_fresh_checkout_eol_paths)", bounded)
        self.assertIn("--source=HEAD", restore)
        self.assertIn("--worktree", restore)
        self.assertIn('become_user: "{{ hermes_native_update_user }}"', restore)
        self.assertIn("not ansible_check_mode", restore)

    def test_native_profile_roots_are_agent_owned_before_managed_children(self) -> None:
        inspect = self.task("Inspect native Hermes profile roots")
        reject = self.task("Reject unsafe native Hermes profile roots")
        create = self.task("Create agent-owned native Hermes profile roots")
        plugin = self.task("Inspect Astra Star plugin directories")
        self.assertIn("follow: false", inspect)
        self.assertIn("not item.stat.islnk", reject)
        self.assertIn('owner: "{{ item.user }}"', create)
        self.assertIn('group: "{{ item.group }}"', create)
        self.assertIn('mode: "0700"', create)
        self.assertLess(
            self.playbook.index("Create agent-owned native Hermes profile roots"),
            self.playbook.index("Inspect Astra Star plugin directories"),
        )
        self.assertIn("/var/lib/hermes/astra/.hermes/profiles/astra/plugins", plugin)

    def test_native_update_boundary_uses_only_supported_external_assets(self) -> None:
        browser = self.task("Deploy native Hermes browser selector")
        transaction = self.task("Deploy native Hermes update transaction helper")
        validate = self.task("Validate native Hermes update transaction contract")
        self.assertIn("hermes_agent_browser_selector_source", browser)
        self.assertIn("hermes_agent_browser_selector_live", browser)
        self.assertIn("hermes_native_update_transaction_source", transaction)
        self.assertIn("hermes_native_update_transaction_live", transaction)
        for task in (
            "Deploy native Hermes browser selector",
            "Deploy native Hermes update transaction helper",
        ):
            self.assertLess(
                self.playbook.index(task),
                self.playbook.index("Validate native Hermes update transaction contract"),
            )
        self.assertIn("--validate-config", validate)
        for retired in (
            "hermes_queued_event_patch",
            "hermes_queued_event_validator",
            "hermes_managed_source_patch",
            "hermes_mem0_dependency_updater",
        ):
            self.assertNotIn(retired, self.playbook)

    def test_native_updaters_own_release_selection_and_are_narrowly_triggered(self) -> None:
        values = {
            key: self.variables[key]
            for key in (
                "hermes_native_update_service",
                "hermes_native_update_timer",
                "hermes_native_update_calendar",
                "hermes_native_update_randomized_delay",
                "hermes_native_update_user",
                "hermes_native_update_group",
                "hermes_runtime_readers_group",
                "hermes_native_update_home",
                "hermes_native_update_profile_home",
                "hermes_shadow_runtime_binary",
                "hermes_shadow_runtime_root",
                "hermes_shadow_runtime_venv",
                "hermes_shadow_uv_binary",
                "hermes_shadow_uv_python_root",
                "hermes_native_update_transaction_live",
                "hermes_native_update_transaction_config",
                "hermes_tirith_binary",
                "hermes_tirith_update_service",
                "hermes_tirith_update_timer",
                "hermes_tirith_update_user",
                "hermes_tirith_update_group",
                "hermes_tirith_update_home",
                "hermes_shadow_profiles",
            )
        }
        values["hermes_production_consumer_profiles"] = values[
            "hermes_shadow_profiles"
        ]
        launcher = self.environment.from_string(self.launcher_template).render(**values)
        hermes_service = self.environment.from_string(
            self.update_service_template
        ).render(**values)
        hermes_timer = self.environment.from_string(
            self.update_timer_template
        ).render(**values)
        tirith_service = self.environment.from_string(
            self.tirith_update_service_template
        ).render(**values)
        tirith_timer = self.environment.from_string(
            self.tirith_update_timer_template
        ).render(**values)
        sudoers = self.environment.from_string(self.update_sudoers_template).render(
            **values
        )

        self.assertIn('"$1" == "update"', launcher)
        self.assertIn('"$2" == "--gateway"', launcher)
        self.assertIn('"$(id -un)" != "hermes-astra"', launcher)
        self.assertIn(
            "sudo -n /usr/bin/systemctl start hermes-native-update.service",
            launcher,
        )
        self.assertIn(values["hermes_native_update_transaction_live"], hermes_service)
        self.assertIn(values["hermes_native_update_transaction_config"], hermes_service)
        self.assertIn(
            f"ReadOnlyPaths={values['hermes_native_update_transaction_config']} "
            f"{values['hermes_shadow_uv_binary']} "
            f"{values['hermes_shadow_uv_python_root']}",
            hermes_service,
        )
        self.assertIn("--validate-runtime", hermes_service)
        self.assertLess(
            hermes_service.index("ExecStartPre="),
            hermes_service.index("ExecStart="),
        )
        self.assertIn("ExecStart=/usr/bin/python3", hermes_service)
        self.assertNotIn("--backup", hermes_service)
        self.assertIn(
            "Wants=network-online.target hermes-tirith-native-update.service",
            hermes_service,
        )
        self.assertNotIn("ExecStartPre=-/usr/bin/systemctl", hermes_service)
        self.assertIn("User=root", hermes_service)
        self.assertIn("Group=root", hermes_service)
        self.assertNotIn("SupplementaryGroups=", hermes_service)
        self.assertIn("InaccessiblePaths=/etc/hermes/astra", hermes_service)
        self.assertNotIn("Environment=PYTHONPATH=", hermes_service)
        self.assertNotIn("ExecStartPost=", hermes_service)
        self.assertIn("rigel\nReadOnlyPaths=", hermes_service)
        self.assertNotIn("google-genai", hermes_service)
        self.assertNotIn("openrouter", hermes_service.lower())
        self.assertNotIn("/usr/bin/sudo", hermes_service)
        self.assertNotIn("RestrictSUIDSGID=true", hermes_service)
        self.assertNotIn("HERMES_MANAGED_DIR=", hermes_service)
        self.assertIn("UMask=0022", hermes_service)
        self.assertNotIn("UMask=0077", hermes_service)
        self.assertIn("CapabilityBoundingSet=\n", hermes_service)
        self.assertIn("AmbientCapabilities=\n", hermes_service)
        self.assertNotIn("CAP_DAC", hermes_service)
        self.assertNotIn("CAP_CHOWN", hermes_service)
        self.assertNotIn("curl", hermes_service)
        self.assertNotIn("github.com/NousResearch", hermes_service)
        self.assertIn("tirith update --yes --format json", tirith_service)
        self.assertIn("ConditionFileIsExecutable=", tirith_service)
        self.assertNotIn("ConditionPathIsExecutable=", tirith_service)
        self.assertIn("User=root", tirith_service)
        self.assertIn("Group=root", tirith_service)
        self.assertIn(
            "ReadWritePaths=/var/lib/hermes-updater /usr/local/libexec",
            tirith_service,
        )
        self.assertNotIn(
            "ReadWritePaths=/var/lib/hermes-updater/.local/bin",
            tirith_service,
        )
        self.assertNotIn("RestrictSUIDSGID=true", tirith_service)
        self.assertIn("NoNewPrivileges=true", tirith_service)
        self.assertIn("CapabilityBoundingSet=", tirith_service)
        self.assertIn(
            "Install Tirith root-owned package-approval helper", self.playbook
        )
        self.assertIn("Keep Tirith native updater state root-owned", self.playbook)
        self.assertIn("Keep Tirith native executable tree root-owned", self.playbook)
        self.assertIn("Keep Tirith Sigstore cache root-owned", self.playbook)
        self.assertIn("Require matching Tirith package-approval helper", self.playbook)
        self.assertNotIn("curl", tirith_service)
        self.assertIn("OnCalendar=daily", hermes_timer)
        self.assertIn("OnCalendar=daily", tirith_timer)
        self.assertIn(
            "hermes-astra ALL=(root) NOPASSWD: HERMES_NATIVE_UPDATE", sudoers
        )
        self.assertNotIn("HERMES_NATIVE_GATEWAY_MANAGE", sudoers)
        self.assertNotIn("hermes-gateway-rigel.service", sudoers)
        self.assertNotIn("hermes-native-updater ALL=", sudoers)
        self.assertNotIn("hermes-dubble ALL=", sudoers)
        self.assertNotIn("hermes-rigel ALL=", sudoers)

        checkout = self.task("Normalize Astra-owned Hermes runtime tree")
        checkout_root = self.task("Keep Hermes runtime root traversable")
        update_state = self.task("Keep Astra native update roots private")
        root_state = self.task("Normalize native update root state files")
        obsolete_account = self.task(
            "Remove obsolete separate Hermes updater account"
        )
        self.assertIn("hermes_native_update_user", checkout)
        self.assertIn("recurse: true", checkout)
        self.assertNotIn("mode:", checkout)
        self.assertIn("hermes_runtime_readers_group", checkout)
        self.assertIn('mode: "0750"', checkout_root)
        self.assertEqual(self.variables["hermes_native_update_user"], "hermes-astra")
        self.assertIn("owner: hermes-astra", update_state)
        self.assertIn("mode: u=rwX,go=", update_state)
        self.assertNotIn("recurse: true", update_state)
        self.assertIn("owner: hermes-astra", root_state)
        self.assertIn('mode: "0600"', root_state)
        self.assertIn("name: hermes-native-updater", obsolete_account)
        self.assertIn("state: absent", obsolete_account)
        self.assertNotIn("ansible.posix.acl", checkout + update_state + root_state)
        native_backends = self.task("Install required Hermes native tool backends")
        self.assertIn("/usr/sbin/runuser", native_backends)
        self.assertIn("hermes_native_post_setup_keys", native_backends)
        self.assertIn("tools", native_backends)
        self.assertIn("post-setup", native_backends)
        self.assertIn("not ansible_check_mode", native_backends)

        deploy = self.task("Deploy native Hermes and Tirith update units")
        bridge = self.task("Deploy exact Astra native update sudoers bridge")
        staged = self.task("Keep native update timers staged before cutover")
        automatic = self.task("Enable automatic native updates after cutover")
        self.assertIn("hermes-native-update.service.j2", deploy)
        self.assertIn("hermes-tirith-native-update.service.j2", deploy)
        self.assertIn("visudo -cf %s", bridge)
        self.assertIn("enabled: false", staged)
        self.assertIn("enabled: true", automatic)
        self.assertIn("hermes_native_updates_automatic", automatic)

    def test_profile_config_is_native_mutable_and_managed_scope_is_secrets_only(self) -> None:
        seed = self.task("Seed mutable Hermes profile config once")
        inspect = self.task("Inspect native Hermes profile configuration")
        require = self.task("Require established native Hermes profile configuration")
        native_check = self.task(
            "Validate merged Hermes config as each service identity"
        )
        self.assertIn("hermes_shadow_config_version", seed)
        self.assertIn("force: false", seed)
        self.assertIn("hermes_shadow_mode == 'bootstrap'", seed)
        self.assertIn("{{ item.home }}/config.yaml", inspect)
        self.assertIn("hermes_shadow_mode != 'bootstrap'", require)
        self.assertIn("/usr/bin/systemd-run", native_check)
        self.assertIn("--property=EnvironmentFile=", native_check)
        self.assertIn("item.environment_file", native_check)
        self.assertIn("HERMES_MANAGED_DIR=/etc/hermes/", native_check)
        self.assertIn("- check", native_check)
        self.assertIn("check_mode: false", native_check)
        self.assertIn("no_log: true", native_check)
        for forbidden in (
            "managed-policy.sha256",
            "hermes-managed-config.yaml.j2",
            "/etc/hermes/astra/config.yaml",
            "/etc/hermes/dubble/config.yaml",
            "/etc/hermes/rigel/config.yaml",
            "/skills/managed",
        ):
            self.assertNotIn(forbidden, self.playbook)

    def test_enrolled_runtime_maintenance_is_explicit_and_stays_offline(self) -> None:
        mode = self.task("Validate Hermes shadow mode")
        approval = self.task("Require explicit Hermes shadow approval")
        shadow_reject = self.task(
            "Reject Discord enrollment in Hermes shadow environments"
        )
        enrolled = self.task(
            "Require existing Discord enrollment during Hermes maintenance"
        )
        updates_staged = self.task("Keep native update timers staged before cutover")
        updates_enabled = self.task("Enable automatic native updates after cutover")
        gateways = self.task(
            "Keep Hermes gateways stopped during bootstrap or maintenance"
        )
        self.assertIn("maintenance", mode)
        self.assertIn("hermes_shadow_maintenance_confirmation", approval)
        self.assertIn("hermes_shadow_maintenance_required_confirmation", approval)
        self.assertIn("hermes_shadow_mode != 'maintenance'", shadow_reject)
        self.assertIn("DISCORD_BOT_TOKEN", enrolled)
        self.assertIn("item.item.name in ['astra', 'dubble']", enrolled)
        self.assertIn("item.item.name == 'rigel'", enrolled)
        self.assertIn("hermes_shadow_mode == 'maintenance'", updates_staged)
        self.assertIn("hermes_shadow_mode != 'maintenance'", updates_enabled)
        self.assertIn("['bootstrap', 'maintenance']", gateways)

    def test_contract_and_playbook_forbid_production_authority(self) -> None:
        contract = CONTRACT.read_text(encoding="utf-8")
        self.assertIn('"productionDeliveryEnabled": false', contract)
        self.assertIn('"productionSchedulerEnabled": false', contract)
        self.assertIn('"productionRouteEnabled": false', contract)
        self.assertIn('"dockerGroup": false', contract)
        self.assertIn('"dockerSocket": false', contract)
        self.assertNotIn("line: DISCORD_BOT_TOKEN=", self.playbook)
        self.assertNotIn("GATEWAY_ALLOW_ALL_USERS", self.playbook)
        self.assertNotIn("docker_group", self.playbook)
        self.assertIn(
            "Reject Discord enrollment in Hermes shadow environments",
            self.playbook,
        )
        self.assertIn("is search('(?m)^DISCORD_')", self.playbook)

    def test_bootstrap_removes_markers_and_stops_all_units(self) -> None:
        markers = self.task(
            "Remove Hermes gateway readiness markers during bootstrap"
        )
        stopped = self.task(
            "Keep Hermes gateways stopped during bootstrap or maintenance"
        )
        self.assertIn("state: absent", markers)
        self.assertIn("hermes_shadow_mode == 'bootstrap'", markers)
        self.assertIn("hermes_gateway_readiness_marker", markers)
        self.assertIn("enabled: false", stopped)
        self.assertIn("state: stopped", stopped)
        create = self.task("Create Hermes gateway readiness markers")
        self.assertIn("hermes_gateway_readiness_marker", create)
        self.assertIn("owner: root", create)
        legacy = self.task("Remove legacy profile-writable Hermes readiness markers")
        self.assertIn("hermes_gateway_legacy_readiness_marker", legacy)
        self.assertIn("state: absent", legacy)

    def test_discord_cutover_artifacts_are_not_runtime_dependencies(self) -> None:
        environment = self.task("Seed root-managed Hermes service environment once")
        local_environment = self.task(
            "Remove profile-local environment files from Hermes shadow"
        )
        for historical_dependency in (
            "Deploy Hermes Discord cutover contract",
            "Deploy Hermes Discord contract audit",
            "Deploy pinned Hermes Discord audit sources",
            "Deploy executable OpenClaw delivery cutover audit",
            "Deploy exact delivery-recovery reconciliation tool",
            "Validate deployed Hermes Discord cutover contract",
        ):
            self.assertNotIn(historical_dependency, self.playbook)
        self.assertIn("item.environment_file", environment)
        self.assertIn("/etc/hermes/", environment)
        self.assertIn("owner: root", environment)
        self.assertIn("item.name == 'rigel'", environment)
        self.assertIn("'root' if item.name == 'rigel'", environment)
        self.assertIn("'0400' if item.name == 'rigel'", environment)
        self.assertIn("{{ item.home }}/.env", local_environment)
        self.assertIn("state: absent", local_environment)

    def test_rigel_schedule_is_root_owned_and_not_activated(self) -> None:
        script = self.task("Deploy deterministic Rigel academic schedule")
        declaration = self.task("Deploy paused Rigel academic job declaration")
        self.assertIn("hermes_shadow_profiles[2].home", script)
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
        self.assertIn("hermes-health-receiver.yml", sources)
        self.assertIn("--repository-root", validation)
        self.assertNotIn("hermes cron create", self.playbook)
        self.assertNotIn(
            "systemd_service:\n        name: hermes-automation", self.playbook
        )

    def test_operating_contracts_are_seed_only_and_profile_owned(self) -> None:
        task = self.task("Seed profile-owned Hermes operating contracts once")
        self.assertIn("/AGENTS.md", task)
        self.assertIn('owner: "{{ item.user }}"', task)
        self.assertIn('mode: "0600"', task)
        self.assertIn("force: false", task)
        for profile in self.variables["hermes_shadow_profiles"]:
            source = (
                ROOT / "files" / "hermes" / "profiles" / profile["name"] / "AGENTS.md"
            )
            self.assertTrue(source.is_file())
            self.assertFalse(source.is_symlink())

        rigel_references = self.task(
            "Seed complete profile-owned Rigel bootstrap references once"
        )
        self.assertIn("HEARTBEAT.md", rigel_references)
        self.assertIn("TOOLS.md", rigel_references)
        self.assertIn("USER.md", rigel_references)
        self.assertIn("owner: hermes-rigel", rigel_references)
        self.assertIn('mode: "0600"', rigel_references)
        self.assertIn("force: false", rigel_references)
        self.assertIn("group: hermes-rigel", rigel_references)

    def test_astra_star_plugin_is_root_owned_and_validated(self) -> None:
        directories = self.task("Create root-owned Astra Star plugin directories")
        validator = self.task("Deploy Astra Star dispatch privacy validator")
        plugin = self.task("Deploy root-owned Astra Star dispatch privacy plugin")
        self.assertIn("hermes_star_privacy_plugin_managed_root", directories)
        self.assertIn("hermes_star_privacy_plugin_runtime_root", directories)
        self.assertIn("owner: root", directories)
        self.assertIn("group: hermes-astra", directories)
        self.assertIn("hermes_star_privacy_validator_source", validator)
        self.assertIn('mode: "0555"', validator)
        self.assertIn("hermes_star_privacy_plugin_source", plugin)
        self.assertIn("['__init__.py', 'plugin.yaml']", plugin)
        self.assertIn("owner: root", plugin)
        self.assertIn("group: hermes-astra", plugin)
        self.assertIn('mode: "0440"', plugin)


if __name__ == "__main__":
    unittest.main()
