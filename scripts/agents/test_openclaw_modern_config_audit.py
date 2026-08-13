#!/usr/bin/env python3
"""Tests for the rendered modern OpenClaw config promotion gate."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined

SCRIPT = Path(__file__).with_name("openclaw-modern-config-audit.py")
TEMPLATE = Path(__file__).parents[2] / "templates/openclaw/openclaw-modern.json.j2"
OPENCLAW = Path("/opt/openclaw-isolated/current/bin/openclaw")
PLUGIN_PROJECTS = Path("/var/lib/openclaw-isolated/state/npm/projects")


def _readable_plugin_root(legacy: str, project_pattern: str) -> Path | None:
    candidates = [Path(legacy), *sorted(PLUGIN_PROJECTS.glob(project_pattern))]
    return next(
        (
            path
            for path in candidates
            if path.is_dir() and os.access(path, os.R_OK | os.X_OK)
        ),
        None,
    )


PLUGIN_ROOTS = [
    _readable_plugin_root(
        "/opt/openclaw-isolated/current/plugins/codex/node_modules/@openclaw/codex",
        "openclaw-codex-*/node_modules/@openclaw/codex",
    ),
    _readable_plugin_root(
        "/opt/openclaw-isolated/current/plugins/discord/node_modules/@openclaw/discord",
        "openclaw-discord-*/node_modules/@openclaw/discord",
    ),
    _readable_plugin_root(
        "/opt/openclaw-isolated/current/plugins/lossless-claw/node_modules/"
        "@martian-engineering/lossless-claw",
        "martian-engineering-lossless-claw-*/node_modules/"
        "@martian-engineering/lossless-claw",
    ),
    _readable_plugin_root(
        "/opt/openclaw-isolated/current/plugins/openclaw-mem0/node_modules/"
        "@mem0/openclaw-mem0",
        "mem0-openclaw-mem0-*/node_modules/@mem0/openclaw-mem0",
    ),
]
NATIVE_OPENCLAW_AVAILABLE = OPENCLAW.exists() and os.access(OPENCLAW, os.X_OK)
NATIVE_CODEX_FIXTURE_AVAILABLE = (
    NATIVE_OPENCLAW_AVAILABLE and PLUGIN_ROOTS[0] is not None
)
NATIVE_FULL_FIXTURE_AVAILABLE = NATIVE_OPENCLAW_AVAILABLE and all(
    path is not None for path in PLUGIN_ROOTS
)
SPEC = importlib.util.spec_from_file_location("openclaw_modern_config_audit", SCRIPT)
assert SPEC and SPEC.loader
audit_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit_module
SPEC.loader.exec_module(audit_module)


def render_config(
    heartbeats_enabled: bool = True,
    deployment_mode: str = "production",
    behavior_rigel_heartbeat_every: str = "0m",
) -> dict[str, object]:
    environment = Environment(undefined=StrictUndefined, autoescape=False)
    environment.filters["to_json"] = lambda value: json.dumps(value)
    template = environment.from_string(TEMPLATE.read_text(encoding="utf-8"))
    values = {
        "openclaw_modern_secret_file": "/etc/openclaw/secrets.json",
        "openclaw_modern_workspace_dir": "/var/lib/openclaw/workspace",
        "openclaw_modern_primary_model": "codex/gpt-5.6-sol",
        "openclaw_modern_default_fallbacks": [
            "ollama-cloud/deepseek-v4-pro",
            "ollama-cloud/glm-5.2",
            "ollama-cloud/kimi-k2.7-code",
        ],
        "openclaw_modern_image_fallbacks": [
            "ollama-cloud/kimi-k2.7-code",
        ],
        "openclaw_modern_antares_model": "ollama-cloud/deepseek-v4-pro",
        "openclaw_modern_antares_fallbacks": [
            "ollama-cloud/glm-5.2",
            "ollama-cloud/kimi-k2.7-code",
            "codex/gpt-5.6-sol",
        ],
        "openclaw_modern_timezone": "America/Chicago",
        "openclaw_modern_heartbeats_enabled": heartbeats_enabled,
        "openclaw_modern_deployment_mode": deployment_mode,
        "openclaw_modern_behavior_rigel_heartbeat_every": (
            behavior_rigel_heartbeat_every
        ),
        "openclaw_modern_main_heartbeat_recipient": "channel:111111111111111111",
        "openclaw_modern_dubble_heartbeat_recipient": "channel:222222222222222222",
        "openclaw_modern_rigel_heartbeat_recipient": "channel:333333333333333333",
        "openclaw_modern_discord_application_id": "444444444444444444",
        "openclaw_modern_dubble_discord_application_id": "555555555555555555",
        "openclaw_modern_discord_allow_from": ["666666666666666666"],
        "openclaw_modern_dubble_discord_allow_from": ["666666666666666666"],
        "openclaw_modern_discord_exec_approvers": ["666666666666666666"],
        "openclaw_modern_discord_guilds": {
            "777777777777777777": {
                "requireMention": False,
                "users": ["666666666666666666"],
                "channels": {
                    "111111111111111111": {"enabled": True},
                    "333333333333333333": {"enabled": True},
                },
            }
        },
        "openclaw_modern_dubble_discord_guilds": {
            "777777777777777777": {
                "requireMention": False,
                "users": ["666666666666666666"],
                "channels": {"222222222222222222": {"enabled": True}},
            }
        },
        "openclaw_modern_rigel_discord_peer_id": "333333333333333333",
        "openclaw_modern_command_owner_allow_from": ["discord:666666666666666666"],
        "openclaw_modern_cron_failure_recipient": "channel:111111111111111111",
        "openclaw_modern_gateway_port": 18789,
        "openclaw_modern_codex_port": 19790,
        "openclaw_modern_control_ui_allowed_origins": ["https://openclaw.example.test"],
        "openclaw_modern_public_url": "wss://openclaw.example.test",
        "openclaw_modern_lossless_database": "/var/lib/openclaw/state/lcm.db",
        "openclaw_modern_lossless_large_files_dir": "/var/lib/openclaw/state/lcm-files",
        "openclaw_modern_mem0_user_id": "johnny",
        "openclaw_modern_mem0_collection": "memories-production",
        "openclaw_modern_mem0_history_database": "/var/lib/openclaw/state/mem0/history.db",
        "openclaw_modern_mem0_custom_prompt": (
            "Store only explicit durable facts. Never store credentials or inferred facts."
        ),
    }
    return json.loads(template.render(**values))


class ModernConfigAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = render_config()

    def assert_rejected(self, config: dict[str, object], pattern: str) -> None:
        with self.assertRaisesRegex(audit_module.AuditError, pattern):
            audit_module.audit_config(config)

    def test_rendered_config_passes(self) -> None:
        result = audit_module.audit_config(self.config)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["agentCount"], 5)
        self.assertEqual(result["bindingCount"], 3)
        self.assertEqual(result["deploymentMode"], "production")
        self.assertEqual(result["pluginCount"], 8)
        self.assertEqual(result["heartbeatMode"], "production")
        self.assertNotIn("openai", self.config["auth"]["order"])
        self.assertFalse(
            any(
                profile.get("provider") == "openai"
                for profile in self.config["auth"]["profiles"].values()
            )
        )
        self.assertEqual(
            self.config["agents"]["defaults"]["model"]["primary"],
            "codex/gpt-5.6-sol",
        )

    def test_gateway_openai_primary_model_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["agents"]["defaults"]["model"]["primary"] = "openai/gpt-5.6-sol"
        self.assert_rejected(config, "primary-model-bypasses-codex-provider")

    def test_disabled_codex_model_discovery_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["plugins"]["entries"]["codex"]["config"]["discovery"]["enabled"] = False
        self.assert_rejected(config, "codex-model-discovery-disabled")

    def test_gateway_openai_auth_profile_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["auth"]["profiles"]["openai:default"] = {
            "provider": "openai",
            "mode": "oauth",
        }
        config["auth"]["order"]["openai"] = ["openai:default"]
        self.assert_rejected(config, "gateway-provider-auth-boundary")

    def test_runtime_config_does_not_hide_native_security_findings(self) -> None:
        self.assertNotIn("security", self.config)

    def test_canary_render_disables_every_heartbeat(self) -> None:
        config = render_config(heartbeats_enabled=False)
        result = audit_module.audit_config(config, heartbeat_mode="canary")
        self.assertEqual(result["heartbeatMode"], "canary")
        for agent in config["agents"]["list"]:
            if agent["id"] in {"main", "dubble", "rigel"}:
                self.assertEqual(agent["heartbeat"]["every"], "0m")
        self.assert_rejected(config, "heartbeat-cadence:main")

    def test_canary_audit_rejects_enabled_heartbeats(self) -> None:
        with self.assertRaisesRegex(audit_module.AuditError, "heartbeat-cadence:main"):
            audit_module.audit_config(self.config, heartbeat_mode="canary")

    def test_behavior_canary_render_is_fail_closed(self) -> None:
        config = render_config(
            heartbeats_enabled=False, deployment_mode="behavior-canary"
        )
        result = audit_module.audit_config(
            config,
            heartbeat_mode="canary",
            deployment_mode="behavior-canary",
        )
        self.assertEqual(result["deploymentMode"], "behavior-canary")
        self.assertEqual(result["bindingCount"], 0)
        self.assertEqual(result["pluginCount"], 3)
        self.assertNotIn("channels", config)
        self.assertNotIn("bindings", config)
        self.assertNotIn("cron", config)
        self.assertNotIn("slots", config["plugins"])
        self.assertEqual(config["commands"]["ownerAllowFrom"], [])
        self.assertEqual(config["gateway"]["controlUi"], {"enabled": False})
        for agent in config["agents"]["list"]:
            if agent["id"] in {"main", "dubble", "rigel"}:
                self.assertEqual(agent["heartbeat"]["every"], "0m")
                self.assertEqual(agent["heartbeat"]["target"], "none")
                self.assertNotIn("to", agent["heartbeat"])
                self.assertNotIn("accountId", agent["heartbeat"])

    def test_security_canary_uses_only_remote_executor_tools(self) -> None:
        config = render_config(
            heartbeats_enabled=False, deployment_mode="security-canary"
        )
        result = audit_module.audit_config(
            config,
            heartbeat_mode="canary",
            deployment_mode="security-canary",
        )
        self.assertEqual(result["deploymentMode"], "security-canary")
        self.assertEqual(result["bindingCount"], 0)
        self.assertNotIn("channels", config)
        self.assertNotIn("bindings", config)
        self.assertNotIn("cron", config)
        self.assertEqual(config["tools"]["profile"], "minimal")
        self.assertIn("group:fs", config["tools"]["deny"])
        self.assertIn("exec", config["tools"]["deny"])
        app_server = config["plugins"]["entries"]["codex"]["config"]["appServer"]
        self.assertEqual(app_server["transport"], "websocket")
        self.assertEqual(app_server["sandbox"], "workspace-write")
        self.assertEqual(app_server["approvalPolicy"], "never")

    def test_controlled_rigel_heartbeat_is_behavior_canary_only(self) -> None:
        config = render_config(
            heartbeats_enabled=False,
            deployment_mode="behavior-canary",
            behavior_rigel_heartbeat_every="1m",
        )
        result = audit_module.audit_config(
            config,
            heartbeat_mode="controlled-rigel",
            deployment_mode="behavior-canary",
        )
        self.assertEqual(result["heartbeatMode"], "controlled-rigel")
        heartbeats = {
            agent["id"]: agent.get("heartbeat")
            for agent in config["agents"]["list"]
            if agent["id"] in {"main", "dubble", "rigel"}
        }
        self.assertEqual(heartbeats["main"]["every"], "0m")
        self.assertEqual(heartbeats["dubble"]["every"], "0m")
        self.assertEqual(heartbeats["rigel"]["every"], "1m")
        self.assertEqual(heartbeats["rigel"]["target"], "none")
        with self.assertRaisesRegex(
            audit_module.AuditError, "controlled-rigel-outside-behavior-canary"
        ):
            audit_module.audit_config(
                render_config(),
                heartbeat_mode="controlled-rigel",
                deployment_mode="production",
            )

    def test_controlled_rigel_heartbeat_rejects_other_cadence(self) -> None:
        config = render_config(
            heartbeats_enabled=False,
            deployment_mode="behavior-canary",
            behavior_rigel_heartbeat_every="30m",
        )
        with self.assertRaisesRegex(audit_module.AuditError, "heartbeat-cadence:rigel"):
            audit_module.audit_config(
                config,
                heartbeat_mode="controlled-rigel",
                deployment_mode="behavior-canary",
            )

    def test_behavior_canary_rejects_channel_surface(self) -> None:
        config = render_config(
            heartbeats_enabled=False, deployment_mode="behavior-canary"
        )
        config["channels"] = {}
        with self.assertRaisesRegex(audit_module.AuditError, "top-level-config-drift"):
            audit_module.audit_config(
                config,
                heartbeat_mode="canary",
                deployment_mode="behavior-canary",
            )

    def test_behavior_canary_rejects_missing_mutation_deny(self) -> None:
        config = render_config(
            heartbeats_enabled=False, deployment_mode="behavior-canary"
        )
        config["tools"]["deny"].remove("message")
        with self.assertRaisesRegex(
            audit_module.AuditError, "canary-tool-denylist-incomplete"
        ):
            audit_module.audit_config(
                config,
                heartbeat_mode="canary",
                deployment_mode="behavior-canary",
            )

    @unittest.skipUnless(
        NATIVE_FULL_FIXTURE_AVAILABLE,
        "readable managed OpenClaw runtime/plugin fixtures unavailable",
    )
    def test_rendered_config_passes_native_schema_in_isolated_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            state = root / "state"
            home = root / "home"
            state.mkdir()
            home.mkdir()
            secret_path = root / "secrets.json"
            config_path = root / "openclaw.json"
            plugin_fixture_root = root / "plugins"

            config = copy.deepcopy(self.config)
            config["secrets"]["providers"]["production"]["path"] = str(secret_path)
            # Schema validation needs plugin manifests, while deployment separately
            # proves native npm ownership, integrity, trust, and frozen code.
            plugin_fixture_root.mkdir()
            plugin_fixtures = []
            for source in PLUGIN_ROOTS:
                assert source is not None
                destination = plugin_fixture_root / source.name
                shutil.copytree(
                    source,
                    destination,
                    ignore=shutil.ignore_patterns("node_modules"),
                )
                plugin_fixtures.append(destination)
            config["plugins"]["load"] = {
                "paths": [str(path) for path in plugin_fixtures]
            }
            secret_path.write_text(
                json.dumps(
                    {
                        "codex": {"appServerToken": "test-codex-token"},
                        "gateway": {"token": "test-gateway-token"},
                        "channels": {
                            "discord": {
                                "default": {"token": "test-discord-token"},
                                "dubble": {"token": "test-dubble-token"},
                            }
                        },
                        "providers": {"google": {"apiKey": "test-google-key"}},
                    }
                ),
                encoding="utf-8",
            )
            secret_path.chmod(0o400)
            config_path.write_text(json.dumps(config), encoding="utf-8")
            config_path.chmod(0o400)

            environment = os.environ.copy()
            environment.update(
                {
                    "HOME": str(home),
                    "OPENCLAW_CONFIG_PATH": str(config_path),
                    "OPENCLAW_SKIP_CRON": "1",
                    "OPENCLAW_STATE_DIR": str(state),
                    "MEM0_TELEMETRY": "false",
                }
            )
            result = subprocess.run(
                [str(OPENCLAW), "config", "validate", "--json"],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            inspection = ""
            if result.returncode != 0:
                inspect_result = subprocess.run(
                    [str(OPENCLAW), "plugins", "inspect", "openclaw-mem0", "--json"],
                    cwd=root,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
                inspection = (
                    f"\ninspect_stdout={inspect_result.stdout}"
                    f"\ninspect_stderr={inspect_result.stderr}"
                )
            self.assertEqual(
                result.returncode,
                0,
                msg=f"stdout={result.stdout}\nstderr={result.stderr}{inspection}",
            )
            payload = json.loads(result.stdout)
            self.assertTrue(payload.get("valid"), payload)

    @unittest.skipUnless(
        NATIVE_CODEX_FIXTURE_AVAILABLE,
        "readable managed OpenClaw runtime/Codex fixture unavailable",
    )
    def test_behavior_canary_passes_native_schema_in_isolated_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            state = root / "state"
            home = root / "home"
            state.mkdir()
            home.mkdir()
            secret_path = root / "secrets.json"
            config_path = root / "openclaw.json"
            plugin_fixture_root = root / "plugins"

            config = render_config(
                heartbeats_enabled=False, deployment_mode="behavior-canary"
            )
            audit_module.audit_config(
                config,
                heartbeat_mode="canary",
                deployment_mode="behavior-canary",
            )
            config["secrets"]["providers"]["production"]["path"] = str(secret_path)
            codex_source = PLUGIN_ROOTS[0]
            assert codex_source is not None
            plugin_fixture_root.mkdir()
            codex_fixture = plugin_fixture_root / codex_source.name
            shutil.copytree(
                codex_source,
                codex_fixture,
                ignore=shutil.ignore_patterns("node_modules"),
            )
            config["plugins"]["load"] = {"paths": [str(codex_fixture)]}
            secret_path.write_text(
                json.dumps(
                    {
                        "codex": {"appServerToken": "test-codex-token"},
                        "gateway": {"token": "test-gateway-token"},
                    }
                ),
                encoding="utf-8",
            )
            secret_path.chmod(0o400)
            config_path.write_text(json.dumps(config), encoding="utf-8")
            config_path.chmod(0o400)

            environment = os.environ.copy()
            environment.update(
                {
                    "HOME": str(home),
                    "OPENCLAW_CONFIG_PATH": str(config_path),
                    "OPENCLAW_SKIP_CHANNELS": "1",
                    "OPENCLAW_SKIP_CRON": "1",
                    "OPENCLAW_STATE_DIR": str(state),
                    "MEM0_TELEMETRY": "false",
                }
            )
            result = subprocess.run(
                [str(OPENCLAW), "config", "validate", "--json"],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            inspection = ""
            if result.returncode != 0:
                inspect_result = subprocess.run(
                    [str(OPENCLAW), "plugins", "inspect", "codex", "--json"],
                    cwd=root,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
                inspection = (
                    f"\ninspect_stdout={inspect_result.stdout}"
                    f"\ninspect_stderr={inspect_result.stderr}"
                )
            self.assertEqual(
                result.returncode,
                0,
                msg=f"stdout={result.stdout}\nstderr={result.stderr}{inspection}",
            )
            payload = json.loads(result.stdout)
            self.assertTrue(payload.get("valid"), payload)

    def test_plaintext_channel_token_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["channels"]["discord"]["token"] = "plaintext"
        self.assert_rejected(config, "credential-not-file-secret-ref")

    def test_retired_provider_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["plugins"]["allow"].append("openrouter")
        self.assert_rejected(config, "retired-fragment")

    def test_human_home_path_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["agents"]["defaults"]["workspace"] = "/home/johnny/.openclaw"
        self.assert_rejected(config, "retired-fragment")

    def test_global_subagent_model_override_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["agents"]["defaults"]["subagents"]["model"] = {
            "primary": "codex/gpt-5.6-sol"
        }
        self.assert_rejected(config, "global-subagent-model-override")

    def test_star_uses_one_nested_review_route(self) -> None:
        defaults = self.config["agents"]["defaults"]["subagents"]
        agents = {agent["id"]: agent for agent in self.config["agents"]["list"]}
        self.assertEqual(defaults["maxSpawnDepth"], 2)
        self.assertEqual(defaults["allowAgents"], ["rigel", "vega"])
        self.assertEqual(agents["main"]["subagents"]["allowAgents"], ["rigel", "vega"])
        self.assertEqual(agents["vega"]["subagents"]["allowAgents"], ["antares"])
        self.assertNotIn("antares", agents["main"]["subagents"]["allowAgents"])
        self.assertTrue(
            {"sessions_spawn", "sessions_yield", "subagents"}
            <= set(agents["vega"]["tools"]["allow"])
        )

    def test_direct_main_to_antares_star_route_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        main = next(
            agent for agent in config["agents"]["list"] if agent["id"] == "main"
        )
        main["subagents"]["allowAgents"].insert(0, "antares")
        self.assert_rejected(config, "main-subagent-route-drift")

    def test_vega_without_antares_route_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        vega = next(
            agent for agent in config["agents"]["list"] if agent["id"] == "vega"
        )
        vega["subagents"]["allowAgents"] = []
        self.assert_rejected(config, "vega-reviewer-route-drift")

    def test_rigel_message_tool_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        rigel = next(
            agent for agent in config["agents"]["list"] if agent["id"] == "rigel"
        )
        rigel["tools"]["allow"].append("message")
        self.assert_rejected(config, "rigel-message-tool-present")

    def test_rigel_active_hours_are_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        rigel = next(
            agent for agent in config["agents"]["list"] if agent["id"] == "rigel"
        )
        rigel["heartbeat"]["activeHours"] = {
            "start": "08:00",
            "end": "23:00",
            "timezone": "America/Chicago",
        }
        self.assert_rejected(config, "rigel-heartbeat-not-always-on")

    def test_legacy_exec_policy_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["tools"]["exec"].pop("mode")
        config["tools"]["exec"]["security"] = "full"
        config["tools"]["exec"]["ask"] = "off"
        self.assert_rejected(config, "exec-not-guardian-reviewed")

    def test_mem0_ollama_llm_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["plugins"]["entries"]["openclaw-mem0"]["config"]["oss"]["llm"][
            "provider"
        ] = "ollama"
        self.assert_rejected(config, "mem0-llm-not-native-google")

    def test_dubble_message_tool_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        dubble = next(
            agent for agent in config["agents"]["list"] if agent["id"] == "dubble"
        )
        dubble["tools"]["allow"].append("message")
        self.assert_rejected(config, "dubble-message-tool-present")

    def test_chat_control_plane_tools_are_rejected(self) -> None:
        for tool in ("apply_patch", "cron", "exec", "gateway", "message", "write"):
            with self.subTest(tool=tool):
                config = copy.deepcopy(self.config)
                config["tools"]["deny"].remove(tool)
                self.assert_rejected(
                    config, "production-control-tool-denylist-incomplete"
                )

    def test_rigel_binding_must_precede_default_route(self) -> None:
        config = copy.deepcopy(self.config)
        config["bindings"][0], config["bindings"][1] = (
            config["bindings"][1],
            config["bindings"][0],
        )
        self.assert_rejected(config, "binding-order-mismatch")


if __name__ == "__main__":
    unittest.main()
