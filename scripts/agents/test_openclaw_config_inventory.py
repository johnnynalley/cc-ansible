#!/usr/bin/python3
"""Tests for the redacted OpenClaw configuration inventory."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("openclaw-config-inventory.py")
SPEC = importlib.util.spec_from_file_location("openclaw_config_inventory", SCRIPT)
assert SPEC and SPEC.loader
inventory_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = inventory_module
SPEC.loader.exec_module(inventory_module)

REDACTION_SENTINEL = "DO_NOT_LEAK_CONFIG_VALUE"
RECIPIENT_SENTINEL = "123456789012345678"


def source_config() -> dict:
    return {
        "agents": {
            "defaults": {
                "model": {"primary": "openai/gpt-5.6-sol", "fallbacks": []},
                "heartbeat": {
                    "every": "30m",
                    "directPolicy": "block",
                    "includeReasoning": False,
                },
                "subagents": {
                    "model": {
                        "primary": "openai/gpt-5.6-sol",
                        "fallbacks": ["ollama-cloud/glm-5.2"],
                    },
                    "maxConcurrent": 8,
                    "runTimeoutSeconds": 900,
                    "archiveAfterMinutes": 1440,
                },
            },
            "list": [
                {
                    "id": "main",
                    "default": True,
                    "name": "Private name",
                    "identity": {"theme": REDACTION_SENTINEL},
                    "workspace": "/home/johnny/.openclaw/workspace",
                    "model": {
                        "primary": "openai/gpt-5.6-sol",
                        "fallbacks": [],
                    },
                    "models": {"openai/gpt-5.6-sol": {"agentRuntime": {"id": "codex"}}},
                    "subagents": {"allowAgents": ["vega", "antares"]},
                    "heartbeat": {
                        "every": "30m",
                        "target": "none",
                        "directPolicy": "block",
                        "includeReasoning": False,
                        "isolatedSession": True,
                        "lightContext": True,
                        "skipWhenBusy": True,
                        "suppressToolErrorWarnings": True,
                    },
                },
                {
                    "id": "rigel",
                    "workspace": "/home/johnny/.openclaw/workspace/rigel",
                    "model": {
                        "primary": "openai/gpt-5.6-sol",
                        "fallbacks": [],
                    },
                    "heartbeat": {
                        "every": "30m",
                        "target": "discord",
                        "directPolicy": "block",
                        "includeReasoning": False,
                        "isolatedSession": True,
                        "lightContext": True,
                        "skipWhenBusy": True,
                        "suppressToolErrorWarnings": True,
                        "accountId": "default",
                        "to": RECIPIENT_SENTINEL,
                    },
                },
            ],
        },
        "bindings": [
            {
                "agentId": "rigel",
                "match": {
                    "channel": "discord",
                    "accountId": "default",
                    "peer": {"kind": "channel", "id": RECIPIENT_SENTINEL},
                },
            }
        ],
        "channels": {
            "discord": {
                "enabled": True,
                "token": REDACTION_SENTINEL,
                "allowFrom": [RECIPIENT_SENTINEL],
                "guilds": {RECIPIENT_SENTINEL: {"enabled": True}},
                "accounts": {
                    "default": {
                        "token": {
                            "source": "file",
                            "provider": "isolated",
                            "id": f"/{REDACTION_SENTINEL}",
                        },
                        "allowFrom": [RECIPIENT_SENTINEL],
                        "guilds": {},
                    }
                },
            }
        },
        "plugins": {
            "allow": ["codex", "discord"],
            "entries": {
                "codex": {"enabled": True},
                "discord": {
                    "enabled": True,
                    "config": {"token": REDACTION_SENTINEL},
                },
            },
            "slots": {"contextEngine": "codex"},
        },
        "hooks": {
            "internal": {
                "enabled": True,
                "entries": {"cognitive-stack": {"enabled": True}},
            }
        },
        "gateway": {
            "mode": "local",
            "bind": "tailnet",
            "port": 18789,
            "auth": {"mode": "token", "token": REDACTION_SENTINEL},
            "tailscale": {"mode": "off"},
            "trustedProxies": ["100.64.0.1"],
            "controlUi": {"enabled": True},
        },
        "auth": {
            "profiles": {
                f"openai:{RECIPIENT_SENTINEL}": {
                    "provider": "openai",
                    "mode": "oauth",
                }
            },
            "order": {"openai": [f"openai:{RECIPIENT_SENTINEL}"]},
        },
        "models": {"providers": {}},
        "env": {"PRIVATE_API_KEY": REDACTION_SENTINEL},
        "skills": {"entries": {"1password": {"enabled": True}}},
    }


class ConfigInventoryTests(unittest.TestCase):
    def write_config(self, root: Path, config: dict) -> Path:
        path = root / "openclaw.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        path.chmod(0o600)
        return path

    def test_inventory_omits_secrets_and_opaque_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            path = self.write_config(Path(directory_name), source_config())
            result = inventory_module.inventory_config(path)

        encoded = json.dumps(result, sort_keys=True)
        self.assertNotIn(REDACTION_SENTINEL, encoded)
        self.assertNotIn(RECIPIENT_SENTINEL, encoded)
        self.assertNotIn("Private name", encoded)
        self.assertEqual(result["summary"]["agentCount"], 2)
        self.assertEqual(result["summary"]["bindingCount"], 1)
        self.assertEqual(result["channels"]["discord"]["token"], "plaintext")
        self.assertEqual(
            result["channels"]["discord"]["accounts"][0]["token"],
            "secret-ref:file",
        )
        self.assertTrue(result["bindings"][0]["hasPeer"])
        self.assertTrue(result["agents"][0]["hasIdentity"])
        self.assertEqual(result["agents"][0]["workspace"], "$LEGACY_WORKSPACE")
        self.assertEqual(
            result["auth"]["profiles"],
            [{"provider": "openai", "mode": "oauth", "count": 1}],
        )
        self.assertEqual(
            result["agentDefaults"]["subagents"]["model"],
            {
                "primary": "openai/gpt-5.6-sol",
                "fallbacks": ["ollama-cloud/glm-5.2"],
                "unknownKeys": [],
            },
        )
        self.assertEqual(result["agentDefaults"]["subagents"]["runTimeoutSeconds"], 900)
        self.assertEqual(
            result["agentDefaults"]["subagents"]["archiveAfterMinutes"], 1440
        )
        self.assertNotIn("skills", result["credentialSurfacesByRoot"])

    def test_unknown_agent_shape_is_reported_without_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            config = source_config()
            config["agents"]["list"][0]["futurePolicy"] = REDACTION_SENTINEL
            path = self.write_config(Path(directory_name), config)
            result = inventory_module.inventory_config(path)

        encoded = json.dumps(result, sort_keys=True)
        self.assertNotIn(REDACTION_SENTINEL, encoded)
        self.assertEqual(result["agents"][0]["unknownKeys"], ["futurePolicy"])

    def test_malformed_binding_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            config = source_config()
            config["bindings"] = [{"agentId": "main", "match": "invalid"}]
            path = self.write_config(Path(directory_name), config)
            with self.assertRaisesRegex(
                inventory_module.InventoryError, "invalid-binding-match"
            ):
                inventory_module.inventory_config(path)

    def test_symlink_config_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source = self.write_config(root, source_config())
            linked = root / "linked.json"
            linked.symlink_to(source)
            with self.assertRaisesRegex(
                inventory_module.InventoryError, "config-not-regular-file"
            ):
                inventory_module.inventory_config(linked)


if __name__ == "__main__":
    unittest.main()
