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
CONFIG = ROOT / "templates" / "hermes" / "hermes-managed-config.yaml.j2"
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
        cls.config_template = CONFIG.read_text(encoding="utf-8")
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
            self.assertIn("computer_use", profile["disabled_toolsets"])
        self.assertTrue(
            {
                "terminal",
                "file",
                "code_execution",
                "cronjob",
                "discord",
                "discord_admin",
            }
            <= set(profiles[0]["toolsets"])
        )
        self.assertTrue(
            {"terminal", "file", "code_execution", "cronjob"}.isdisjoint(
                profiles[0]["disabled_toolsets"]
            )
        )
        self.assertEqual(profiles[0]["terminal_backend"], "local")
        self.assertEqual(
            profiles[0]["plugins_enabled"],
            [
                "star-dispatch-privacy",
                "agent-docker-inventory",
                "arr-api",
                "host-admin",
                "compose-admin",
                "discord-parity",
                "fleet-admin",
                "hermes-lcm",
            ],
        )
        self.assertIn("arr_api", profiles[0]["toolsets"])
        self.assertNotIn("arr_api", profiles[1]["toolsets"])
        self.assertNotIn("arr_api", profiles[2]["toolsets"])
        self.assertEqual(profiles[0]["cron_approval_mode"], "approve")
        self.assertNotIn("discord_admin", profiles[0]["disabled_toolsets"])
        self.assertIn("fetch_messages", profiles[0]["discord_server_actions"])
        self.assertIn("pin_message", profiles[0]["discord_server_actions"])
        self.assertIn("create_thread", profiles[0]["discord_server_actions"])
        self.assertNotIn("add_role", profiles[0]["discord_server_actions"])
        self.assertNotIn("remove_role", profiles[0]["discord_server_actions"])
        dubble = profiles[1]
        self.assertTrue(
            {"discord", "discord_admin", "discord_parity", "astra_handoff", "cronjob"}
            <= set(dubble["toolsets"])
        )
        self.assertTrue(
            {"terminal", "file", "code_execution"}
            <= set(dubble["disabled_toolsets"])
        )
        self.assertEqual(dubble["discord_server_actions"], ["fetch_messages"])
        self.assertEqual(dubble["cron_approval_mode"], "approve")
        self.assertEqual(
            dubble["bot_peers"],
            {"astra": {"url": "http://127.0.0.1:8642"}},
        )
        self.assertTrue(
            {"terminal", "file", "code_execution"}
            <= set(dubble["disabled_toolsets"])
        )
        self.assertEqual(dubble["terminal_backend"], "docker")
        self.assertEqual(
            dubble["plugins_enabled"],
            ["discord-parity", "astra-handoff", "hermes-lcm"],
        )
        rigel = profiles[2]
        self.assertIn("file", rigel["toolsets"])
        self.assertIn("terminal", rigel["toolsets"])
        self.assertNotIn("file", rigel["disabled_toolsets"])
        self.assertNotIn("terminal", rigel["disabled_toolsets"])
        self.assertIn("code_execution", rigel["disabled_toolsets"])
        self.assertEqual(rigel["terminal_backend"], "local")
        self.assertEqual(
            rigel["plugins_enabled"],
            ["hermes-lcm", "rigel-astra-liaison"],
        )
        self.assertEqual(rigel["approval_mode"], "smart")
        self.assertIn("approval_smart_policy", rigel)
        self.assertEqual(
            rigel["terminal_cwd"],
            "/var/lib/hermes/rigel/.hermes/profiles/rigel/imported-data",
        )
        self.assertEqual(
            rigel["gateway_working_directory"], rigel["terminal_cwd"]
        )
        self.assertTrue(
            {"cronjob", "discord_admin"}
            <= set(profiles[2]["disabled_toolsets"])
        )
        self.assertEqual(profiles[2]["discord_server_actions"], [])
        self.assertEqual(profiles[2]["cron_approval_mode"], "deny")
        self.assertIn("web", profiles[0]["toolsets"])
        for toolset in ("browser", "vision", "image_gen", "tts"):
            self.assertIn(toolset, profiles[0]["toolsets"])
        self.assertEqual(
            {"browser", "vision", "image_gen", "tts"}
            & set(profiles[1]["toolsets"]),
            set(),
        )
        self.assertNotIn("messaging", profiles[0]["toolsets"])
        self.assertNotIn("messaging", profiles[1]["toolsets"])
        self.assertTrue(profiles[0]["native_messaging_bridge"])
        self.assertTrue(profiles[1]["native_messaging_bridge"])
        self.assertNotIn("native_messaging_bridge", profiles[2])
        self.assertIn(
            "(item.native_messaging_bridge | default(false) | bool)",
            self.playbook,
        )
        self.assertIn("'messaging' not in item.toolsets", self.playbook)
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
        self.assertNotIn("web", profiles[1]["toolsets"])
        self.assertNotIn("web", profiles[2]["toolsets"])
        expected_fallbacks = [
            {"provider": "ollama-cloud", "model": "glm-5.2"},
            {"provider": "ollama-cloud", "model": "kimi-k2.7-code"},
            {"provider": "ollama-cloud", "model": "deepseek-v4-pro"},
        ]
        for profile in profiles:
            self.assertEqual(profile["model_provider"], "openai-codex")
            self.assertEqual(profile["model_default"], "gpt-5.6-sol")
            self.assertEqual(profile["model_max_tokens"], 8192)
            self.assertEqual(profile["fallback_providers"], expected_fallbacks)
            self.assertEqual(profile["auxiliary_approval"]["provider"], "auto")
            self.assertEqual(
                profile["auxiliary_approval"]["model"], ""
            )
            self.assertEqual(
                profile["auxiliary_background_review"]["provider"],
                "auto",
            )
            self.assertEqual(
                profile["auxiliary_background_review"]["model"],
                "",
            )
        self.assertTrue(profiles[0]["model_supports_vision"])
        self.assertEqual(profiles[0]["image_input_mode"], "auto")
        self.assertEqual(profiles[0]["terminal_cwd"], profiles[0]["home"])
        self.assertFalse(profiles[0]["memory_write_approval"])
        self.assertFalse(profiles[0]["skills_write_approval"])
        self.assertFalse(profiles[0]["curator"]["prune_builtins"])
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
            "Validate deployed Hermes Discord cutover contract",
            "Validate deployed Hermes automation contract",
            "Hash root-managed Hermes policy and environment",
            "Inspect legacy OpenClaw listeners before Hermes start",
        )
        for name in task_names:
            with self.subTest(task=name):
                self.assertIn("check_mode: false", self.task(name))

    def test_astra_codex_schema_migration_is_exact_and_fail_closed(self) -> None:
        task = self.task("Migrate reviewed Astra Codex route one schema forward")
        self.assertIn("item.item.name == 'astra'", task)
        self.assertIn("hermes_existing_mutable_config | length == 2", task)
        self.assertIn("['base_url', 'default', 'provider']", task)
        self.assertIn("openai-codex", task)
        self.assertIn("gpt-5.6-sol", task)
        self.assertIn("https://chatgpt.com/backend-api/codex", task)
        self.assertIn("no_log: true", task)

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

    def test_every_managed_config_renders_with_fail_closed_policy(self) -> None:
        template = self.environment.from_string(self.config_template)
        for profile in self.variables["hermes_shadow_profiles"]:
            rendered = template.render(
                hermes_profile=profile,
                hermes_shadow_config_version=self.variables[
                    "hermes_shadow_config_version"
                ],
                hermes_shadow_runtime_binary=self.variables[
                    "hermes_shadow_runtime_binary"
                ],
                hermes_native_messaging_tools=self.variables[
                    "hermes_native_messaging_tools"
                ],
                hermes_tirith_binary=self.variables["hermes_tirith_binary"],
            )
            config = yaml.safe_load(rendered)
            self.assertEqual(
                config["_config_version"],
                self.variables["hermes_shadow_config_version"],
            )
            self.assertEqual(config["model"]["provider"], profile["model_provider"])
            self.assertEqual(config["model"]["default"], profile["model_default"])
            self.assertEqual(
                config.get("fallback_providers", []),
                profile.get("fallback_providers", []),
            )
            self.assertEqual(
                config["approvals"]["mode"], profile["approval_mode"]
            )
            self.assertEqual(
                config["approvals"]["cron_mode"], profile["cron_approval_mode"]
            )
            if profile["name"] == "astra":
                self.assertEqual(config["web"]["search_backend"], "ddgs")
            else:
                self.assertNotIn("web", config)
            self.assertFalse(config["security"]["allow_lazy_installs"])
            self.assertFalse(config["security"]["allow_private_urls"])
            self.assertEqual(
                config["security"]["tirith_path"],
                self.variables["hermes_tirith_binary"],
            )
            self.assertFalse(config["security"]["tirith_fail_open"])
            self.assertNotIn("pre_update_backup", config["updates"])
            self.assertEqual(
                config["updates"]["non_interactive_local_changes"], "discard"
            )
            self.assertEqual(
                config["memory"]["write_approval"],
                profile.get("memory_write_approval", True),
            )
            self.assertEqual(
                config["skills"]["write_approval"],
                profile.get("skills_write_approval", True),
            )
            self.assertEqual(config["memory"]["nudge_interval"], 10)
            self.assertEqual(config["skills"]["creation_nudge_interval"], 10)
            self.assertEqual(
                config["auxiliary"]["approval"], profile["auxiliary_approval"]
            )
            self.assertEqual(
                config["auxiliary"]["background_review"],
                profile["auxiliary_background_review"],
            )
            self.assertNotIn("vision", config["auxiliary"])
            self.assertEqual(
                config["terminal"]["backend"], profile["terminal_backend"]
            )
            if profile["name"] in {"astra", "rigel"}:
                self.assertTrue(config["model"]["supports_vision"])
                self.assertEqual(config["agent"]["image_input_mode"], "auto")
            else:
                self.assertNotIn("supports_vision", config["model"])
                self.assertNotIn("image_input_mode", config["agent"])
            if profile["name"] in {"astra", "rigel"}:
                self.assertEqual(config["terminal"]["cwd"], profile["terminal_cwd"])
            if profile["name"] == "astra":
                self.assertEqual(config["model"]["max_tokens"], 8192)
                self.assertEqual(config["memory"]["provider"], "mem0")
                self.assertEqual(config["context"]["engine"], "lcm")
                self.assertEqual(
                    config["curator"], profile["curator"]
                )
                self.assertEqual(
                    config["approvals"]["smart_policy"],
                    profile["approval_smart_policy"],
                )
                self.assertEqual(config["approvals"]["mode"], "smart")
                self.assertIn("*sudo*", config["approvals"]["deny"])
                self.assertIn("*docker*", config["approvals"]["deny"])
                self.assertNotIn("docker_network", config["terminal"])
            else:
                self.assertNotIn("curator", config)
                if profile["name"] == "rigel":
                    self.assertEqual(
                        config["approvals"]["smart_policy"],
                        profile["approval_smart_policy"],
                    )
                    self.assertEqual(config["approvals"]["mode"], "smart")
                else:
                    self.assertNotIn("smart_policy", config["approvals"])
                    self.assertEqual(config["approvals"]["mode"], "manual")
                if profile["terminal_backend"] == "docker":
                    self.assertFalse(config["terminal"]["docker_network"])
                    self.assertFalse(
                        config["terminal"]["docker_mount_cwd_to_workspace"]
                    )
                    self.assertFalse(config["terminal"]["docker_run_as_host_user"])
                    self.assertEqual(config["terminal"]["docker_forward_env"], [])
                    self.assertEqual(config["terminal"]["docker_volumes"], [])
                else:
                    for key in (
                        "docker_network",
                        "docker_mount_cwd_to_workspace",
                        "docker_run_as_host_user",
                        "docker_forward_env",
                        "docker_volumes",
                    ):
                        self.assertNotIn(key, config["terminal"])
            self.assertEqual(config["delegation"]["max_iterations"], 12)
            self.assertEqual(config["delegation"]["max_concurrent_children"], 2)
            self.assertEqual(config["delegation"]["max_spawn_depth"], 1)
            self.assertFalse(config["delegation"]["orchestrator_enabled"])
            self.assertEqual(
                config["plugins"]["enabled"],
                profile.get("plugins_enabled", []),
            )
            self.assertEqual(config["plugins"]["disabled"], [])
            self.assertEqual(config["display"]["tool_progress"], "off")
            self.assertEqual(config["display"]["busy_input_mode"], "queue")
            self.assertFalse(config["display"]["busy_ack_enabled"])
            self.assertEqual(config["display"]["memory_notifications"], "off")
            self.assertEqual(config["onboarding"]["profile_build"], "off")
            self.assertEqual(config["unauthorized_dm_behavior"], "ignore")
            self.assertTrue(config["group_sessions_per_user"])
            self.assertTrue(config["discord"]["require_mention"])
            self.assertTrue(config["discord"]["thread_require_mention"])
            self.assertEqual(config["discord"]["allow_bots"], "none")
            self.assertEqual(
                {
                    key: value.rstrip("\n")
                    for key, value in config["discord"]["channel_prompts"].items()
                },
                profile["discord_channel_prompts"],
            )
            self.assertEqual(
                config["discord"]["channel_skill_bindings"],
                profile["discord_channel_skill_bindings"],
            )
            self.assertFalse(config["discord"]["history_backfill"])
            self.assertFalse(config["discord"]["missed_message_backfill"]["enabled"])
            self.assertFalse(config["discord"]["reactions"])
            self.assertFalse(
                config["gateway"]["platforms"]["discord"]["extra"]["slash_commands"]
            )
            if profile.get("native_messaging_bridge"):
                bridge = config["mcp_servers"]["hermes_messaging"]
                self.assertEqual(
                    bridge["command"], self.variables["hermes_shadow_runtime_binary"]
                )
                self.assertEqual(bridge["args"], ["mcp", "serve"])
                self.assertEqual(
                    bridge["tools"]["include"],
                    self.variables["hermes_native_messaging_tools"],
                )
                self.assertFalse(bridge["tools"]["resources"])
                self.assertFalse(bridge["tools"]["prompts"])
                self.assertEqual(
                    bridge["env"]["DISCORD_BOT_TOKEN"], "${DISCORD_BOT_TOKEN}"
                )
                self.assertEqual(
                    bridge["env"]["HERMES_MANAGED_DIR"],
                    f"/etc/hermes/{profile['name']}/mcp-server",
                )
                self.assertNotIn("permissions_list_open", str(bridge))
                self.assertNotIn("permissions_respond", str(bridge))
            else:
                self.assertNotIn("mcp_servers", config)

        isolated_scope = self.task(
            "Create isolated native MCP server managed scopes"
        )
        self.assertIn("/etc/hermes/{{ item.name }}/mcp-server", isolated_scope)
        self.assertIn('mode: "0750"', isolated_scope)

    def test_managed_profiles_preserve_production_discord_routes(self) -> None:
        profiles = {
            profile["name"]: profile
            for profile in self.variables["hermes_shadow_profiles"]
        }
        owner = "740687933803331726"
        self.assertEqual(profiles["astra"]["discord_allowed_users"], [owner])
        self.assertEqual(profiles["astra"]["discord_admin_users"], [owner])
        self.assertEqual(
            profiles["astra"]["discord_allowed_channels"],
            ["1482585492330381343", "1488752822466904256"],
        )
        self.assertEqual(
            profiles["astra"]["discord_free_response_channels"],
            profiles["astra"]["discord_allowed_channels"],
        )
        self.assertEqual(
            profiles["astra"]["discord_ignored_channels"],
            ["1482589440663617638"],
        )
        self.assertEqual(
            profiles["astra"]["discord_channel_skill_bindings"],
            [
                {
                    "id": "1488752822466904256",
                    "skills": ["source-grounded-study"],
                }
            ],
        )
        self.assertEqual(profiles["dubble"]["discord_allowed_users"], [])
        self.assertEqual(
            profiles["dubble"]["discord_allowed_roles"],
            ["1209365945882251294"],
        )
        self.assertEqual(profiles["dubble"]["discord_admin_users"], [owner])
        self.assertEqual(
            profiles["dubble"]["discord_allowed_channels"],
            ["1483229851350728784"],
        )
        self.assertEqual(
            profiles["dubble"]["discord_free_response_channels"],
            profiles["dubble"]["discord_allowed_channels"],
        )
        dedicated = {
            profile["name"]: profile
            for profile in self.resolved_profiles(True)
        }
        self.assertEqual(
            dedicated["astra"]["discord_allowed_channels"],
            ["1482585492330381343"],
        )
        self.assertEqual(
            dedicated["rigel"]["discord_allowed_channels"],
            ["1488752822466904256"],
        )
        self.assertEqual(
            dedicated["rigel"]["discord_free_response_channels"],
            dedicated["rigel"]["discord_allowed_channels"],
        )
        self.assertEqual(
            profiles["dubble"]["discord_ignored_channels"],
            ["1483229869079920741"],
        )
        self.assertEqual(profiles["rigel"]["discord_allowed_users"], [])
        self.assertEqual(profiles["rigel"].get("discord_allowed_roles", []), [])
        self.assertEqual(profiles["rigel"]["discord_allowed_channels"], [])
        self.assertEqual(profiles["rigel"]["discord_admin_users"], [])

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
            "hermes_discord_audit_live": self.variables["hermes_discord_audit_live"],
            "hermes_discord_contract_live": self.variables[
                "hermes_discord_contract_live"
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
            "hermes_native_profile_skills_enabled": self.variables[
                "hermes_native_profile_skills_enabled"
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
                    "hermes_lcm_embedding_provider",
                    "hermes_lcm_embedding_model",
                    "hermes_lcm_ollama_base_url",
                    "hermes_lcm_embedding_storage_dtype",
                    "hermes_lcm_embedding_store_dim",
                    "hermes_lcm_embedding_binary_prescreen",
                    "hermes_lcm_embedding_content_policy",
                    "hermes_lcm_embedding_max_batch_items",
                    "hermes_lcm_embedding_query_timeout_s",
                    "hermes_lcm_recall_query_timeout_s",
                    "hermes_lcm_embedding_backfill_timeout_s",
                    "hermes_lcm_proactive_recall_enabled",
                    "hermes_lcm_temporal_rollups_enabled",
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
            self.assertIn(
                f"SupplementaryGroups={self.variables['hermes_runtime_readers_group']}",
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
            self.assertIn("hermes-discord-cutover-audit", rendered)
            self.assertNotIn("hermes-automation-contract-audit", rendered)
            self.assertIn(
                "ExecStartPre=+/usr/bin/sha256sum --check --status --strict",
                rendered,
            )
            self.assertIn("managed-policy.sha256", rendered)
            self.assertIn(
                f"ExecStartPre={self.variables['hermes_tirith_binary']} --version",
                rendered,
            )
            managed_skills_bind = (
                f"BindReadOnlyPaths=/etc/hermes/{profile['name']}/skills:"
                f"{profile['home']}/skills/managed"
            )
            if self.variables["hermes_native_profile_skills_enabled"]:
                self.assertNotIn(managed_skills_bind, rendered)
            else:
                self.assertIn(managed_skills_bind, rendered)
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

    def test_native_skill_ownership_bind_is_narrow_and_enabled(self) -> None:
        self.assertTrue(self.variables["hermes_native_profile_skills_enabled"])
        self.assertEqual(
            self.variables["hermes_shared_self_evolution_source"],
            "/var/lib/hermes/astra/.hermes/profiles/astra/skills/self-evolution",
        )
        self.assertIn(
            "Create read-only shared self-evolution mountpoints", self.playbook
        )
        self.assertIn(
            "{% if hermes_native_profile_skills_enabled | bool %}",
            self.service_template,
        )
        self.assertIn(
            "BindReadOnlyPaths={{ hermes_shared_self_evolution_source }}:"
            "{{ hermes_profile.home }}/skills/self-evolution",
            self.service_template,
        )

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

    def test_native_update_dependencies_are_bootstrapped_before_validation(self) -> None:
        directories = self.task("Create native Hermes update dependency directories")
        queued = self.task("Deploy native Hermes queued-event update assets")
        browser = self.task("Deploy native Hermes browser selector")
        resolver = self.task("Deploy native Hermes memory dependency resolver")
        patcher = self.task("Deploy managed Hermes source patcher")
        validate = self.task("Validate native Hermes update transaction contract")
        self.assertIn("hermes_queued_event_patch_live | dirname", directories)
        self.assertIn("hermes_managed_source_patch_staging_root", directories)
        self.assertIn("hermes_queued_event_patch_source", queued)
        self.assertIn("hermes_queued_event_patch_live", queued)
        self.assertIn("hermes_queued_event_validator_source", queued)
        self.assertIn("hermes_queued_event_validator_live", queued)
        self.assertIn("hermes_runtime_readers_group", queued)
        self.assertIn('mode: "0440"', queued)
        self.assertIn("hermes_agent_browser_selector_source", browser)
        self.assertIn("hermes_agent_browser_selector_live", browser)
        self.assertIn("hermes_mem0_dependency_updater_source", resolver)
        self.assertIn("hermes_mem0_dependency_updater_live", resolver)
        self.assertIn('owner: root', resolver)
        self.assertIn('group: root', resolver)
        self.assertIn('mode: "0755"', resolver)
        self.assertIn("hermes_managed_source_patch_source", patcher)
        self.assertIn("hermes_managed_source_patch_live", patcher)
        self.assertIn('owner: root', patcher)
        self.assertIn('group: root', patcher)
        self.assertIn('mode: "0555"', patcher)
        for task in (
            "Create native Hermes update dependency directories",
            "Deploy native Hermes queued-event update assets",
            "Deploy native Hermes browser selector",
            "Deploy native Hermes memory dependency resolver",
            "Deploy managed Hermes source patcher",
        ):
            self.assertLess(
                self.playbook.index(task),
                self.playbook.index("Validate native Hermes update transaction contract"),
            )
        self.assertIn("--validate-config", validate)

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
                "hermes_shadow_uv_bin_dir",
                "hermes_shadow_uv_binary",
                "hermes_shadow_uv_python_root",
                "hermes_mem0_ollama_dependency",
                "hermes_mem0_dependency_updater_live",
                "hermes_mem0_stable_dependencies",
                "hermes_mem0_spacy_model",
                "hermes_native_post_setup_keys",
                "hermes_agent_browser_selector_live",
                "hermes_queued_event_validator_live",
                "hermes_native_update_transaction_live",
                "hermes_native_update_transaction_config",
                "hermes_native_update_rollback_root",
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
        self.assertIn(values["hermes_native_update_rollback_root"], hermes_service)
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
        rollback = self.task("Create native Hermes update rollback root")
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
        self.assertIn("hermes_native_update_user", rollback)
        self.assertIn("hermes_native_update_group", rollback)
        self.assertIn('mode: "0700"', rollback)
        self.assertEqual(
            self.variables["hermes_native_update_rollback_root"],
            "/srv/live-rollbacks/jn-t14s-lin/hermes-native-update",
        )

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

    def test_profile_config_schema_and_managed_scope_are_fail_closed(self) -> None:
        seed = self.task("Seed mutable Hermes profile config once")
        repair = self.task("Stamp only newly seeded empty Hermes profile configs")
        migrate = self.task("Migrate reviewed Hermes profile configs one schema forward")
        schema = self.task("Require current mutable Hermes config schema")
        native_check = self.task(
            "Validate merged Hermes config as each service identity"
        )
        hashes = self.task("Hash root-managed Hermes policy and environment")
        manifests = self.task("Deploy root-owned Hermes policy checksum manifests")
        self.assertIn("hermes_shadow_config_version", seed)
        self.assertIn("force: false", seed)
        self.assertIn("from_yaml) == {}", repair)
        self.assertIn("hermes_shadow_version_only_migration_from", migrate)
        self.assertIn("item.item.name in ['dubble', 'rigel']", migrate)
        self.assertIn("item.item.name == 'astra'", migrate)
        self.assertIn("reasoning_effort", migrate)
        self.assertIn("show_reasoning", migrate)
        self.assertIn("backup: true", migrate)
        self.assertIn("+ 1", migrate)
        self.assertIn("no_log: true", migrate)
        self.assertIn("hermes_shadow_config_version", schema)
        self.assertIn("ansible_check_mode", schema)
        self.assertIn("item.item.name in ['dubble', 'rigel']", schema)
        self.assertIn("from_yaml) | length == 1", schema)
        self.assertIn("item.item.name == 'astra'", schema)
        self.assertIn("from_yaml) | length == 2", schema)
        self.assertIn("reasoning_effort", schema)
        self.assertIn("show_reasoning", schema)
        self.assertIn("['base_url', 'default', 'provider']", schema)
        self.assertIn("hermes_shadow_version_only_migration_from", schema)
        self.assertIn("/usr/bin/systemd-run", native_check)
        self.assertIn("--property=EnvironmentFile=", native_check)
        self.assertIn("item.environment_file", native_check)
        self.assertIn("HERMES_MANAGED_DIR=/etc/hermes/", native_check)
        self.assertIn("- check", native_check)
        self.assertIn("check_mode: false", native_check)
        self.assertIn("no_log: true", native_check)
        self.assertIn("sha256sum", hashes)
        self.assertIn("config.yaml", hashes)
        self.assertIn(".env", hashes)
        self.assertIn("managed-policy.sha256", manifests)
        self.assertIn("owner: root", manifests)
        self.assertIn('mode: "0440"', manifests)

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

    def test_discord_contract_is_deployed_and_validated_without_secrets(self) -> None:
        contract = self.task("Deploy Hermes Discord cutover contract")
        audit = self.task("Deploy Hermes Discord contract audit")
        sources = self.task("Deploy pinned Hermes Discord audit sources")
        live_delivery_audit = self.task(
            "Deploy executable OpenClaw delivery cutover audit"
        )
        reconciliation = self.task(
            "Deploy exact delivery-recovery reconciliation tool"
        )
        validation = self.task("Validate deployed Hermes Discord cutover contract")
        environment = self.task("Seed root-managed Hermes service environment once")
        local_environment = self.task(
            "Remove profile-local environment files from Hermes shadow"
        )
        self.assertIn("hermes_discord_contract_source", contract)
        self.assertIn("hermes_discord_audit_source", audit)
        self.assertIn("discord-regressions.json", sources)
        self.assertIn("openclaw-delivery-cutover-audit.py", sources)
        self.assertIn(
            "/usr/local/libexec/openclaw-delivery-cutover-audit.py",
            live_delivery_audit,
        )
        self.assertIn('mode: "0755"', live_delivery_audit)
        self.assertIn("hermes_delivery_reconcile_source", reconciliation)
        self.assertIn("hermes_delivery_reconcile_live", reconciliation)
        self.assertIn('mode: "0755"', reconciliation)
        self.assertIn("--repository-root", validation)
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
        self.assertIn("openclaw-health-receiver.yml", sources)
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
