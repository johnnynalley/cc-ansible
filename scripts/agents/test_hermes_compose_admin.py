#!/usr/bin/env python3
"""Focused regressions for Astra's bounded Compose administration boundary."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TARGET_PATH = ROOT / "scripts/docker/agent-compose-transaction.py"
PLUGIN_PATH = ROOT / "files/hermes/plugins/compose-admin/__init__.py"
PLAYBOOK = ROOT / "playbooks/agents/hermes-compose-admin.yml"
HARDENING = ROOT / "templates/hermes/hermes-gateway-hardening.conf.j2"
VARS = ROOT / "inventory/group_vars/hermes_hosts/vars.yml"
SHARED_VARS = ROOT / "inventory/group_vars/all/hermes-compose-admin.yml"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TARGET = load("agent_compose_transaction_tested", TARGET_PATH)
PLUGIN = load("hermes_compose_admin_plugin", PLUGIN_PATH)


def valid_spec() -> dict:
    return {
        "schemaVersion": 1,
        "services": {
            "hello": {
                "image": "docker.io/library/nginx:1.29.1",
                "ports": [{"target": 8080, "published": 18080, "scope": "loopback", "protocol": "tcp"}],
            }
        },
    }


class Context:
    def __init__(self) -> None:
        self.hooks = []
        self.tools = []

    def register_hook(self, name, callback):
        self.hooks.append((name, callback))

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)


class ComposeAdminTests(unittest.TestCase):
    def test_plugin_registers_typed_tools_and_exact_mutation_approval(self) -> None:
        context = Context()
        PLUGIN.register(context)
        self.assertEqual([item["name"] for item in context.tools], ["compose_hosts", "compose_request"])
        self.assertEqual({item["toolset"] for item in context.tools}, {"compose_admin"})
        hook = context.hooks[0][1]
        plan = {"host": "docker-vm", "action": "plan", "stack": "demo", "spec": valid_spec()}
        self.assertIsNone(hook("compose_request", plan, turn_id="turn-1"))
        apply = {**plan, "action": "apply"}
        approval = hook("compose_request", apply, turn_id="turn-1")
        self.assertEqual(approval["action"], "approve")
        self.assertTrue(approval["rule_key"].startswith("compose-admin:turn-1:"))
        changed = valid_spec()
        changed["services"]["hello"]["image"] = "docker.io/library/nginx:1.29.2"
        changed_approval = hook("compose_request", {**apply, "spec": changed}, turn_id="turn-1")
        self.assertNotEqual(approval["rule_key"], changed_approval["rule_key"])
        self.assertEqual(hook("compose_request", apply, turn_id="")["action"], "block")

    def test_plugin_rejects_secret_environment_before_remote_call(self) -> None:
        value = valid_spec()
        value["services"]["hello"]["environment"] = {"API_TOKEN": "nope"}
        result = json.loads(PLUGIN._handle_request({"host": "docker-vm", "action": "plan", "stack": "demo", "spec": value}))
        self.assertEqual(result["code"], "invalid-spec")

    def test_plugin_ssh_is_forced_command_only(self) -> None:
        response = {"schemaVersion": 1, "status": "ok", "host": "docker-vm", "action": "status", "body": {"host": "docker-vm", "stacks": []}}
        with mock.patch.object(PLUGIN, "_load_hosts", return_value={"docker-vm": "192.168.1.153"}), mock.patch.object(PLUGIN, "_credential", return_value=Path("/credential")), mock.patch.object(PLUGIN.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=json.dumps(response).encode())
            PLUGIN._call("docker-vm", {"schemaVersion": 1, "action": "status"})
            command = run.call_args.args[0]
        self.assertIn("ClearAllForwardings=yes", command)
        self.assertEqual(command[-1], "agent-compose@192.168.1.153")
        self.assertNotIn("docker", command)
        self.assertNotIn("sudo", command)

    def test_plugin_rejects_response_from_another_host(self) -> None:
        response = {"schemaVersion": 1, "status": "ok", "host": "media-vm", "action": "status", "body": {}}
        with mock.patch.object(PLUGIN, "_load_hosts", return_value={"docker-vm": "192.168.1.153"}), mock.patch.object(PLUGIN, "_credential", return_value=Path("/credential")), mock.patch.object(PLUGIN.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=json.dumps(response).encode())
            with self.assertRaisesRegex(PLUGIN.ComposePluginError, "invalid-response"):
                PLUGIN._call("docker-vm", {"schemaVersion": 1, "action": "status"})

    def test_target_plan_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "stacks"
            with mock.patch.object(TARGET, "ROOT", root), mock.patch.object(TARGET, "RUNTIME", Path(directory)), mock.patch.object(TARGET, "validate_candidate"):
                result = TARGET.plan("demo", valid_spec(), {"host": "docker-vm", "lanAddress": "192.168.1.153"})
            self.assertEqual(result["outcome"], "create")
            self.assertFalse(root.exists())

    def test_source_contains_no_shell_socket_or_volume_deletion(self) -> None:
        source = TARGET_PATH.read_text(encoding="utf-8") + PLUGIN_PATH.read_text(encoding="utf-8")
        self.assertNotIn("shell=True", source)
        self.assertNotIn("/var/run/docker.sock", source)
        self.assertNotIn('"--volumes"', source)
        self.assertNotIn('"-v"', source)
        self.assertNotIn("OPENAI_API_KEY", source)
        self.assertNotIn("GEMINI_API_KEY", source)

    def test_playbook_and_gateway_contract(self) -> None:
        playbook = PLAYBOOK.read_text(encoding="utf-8")
        hardening = HARDENING.read_text(encoding="utf-8")
        shared = SHARED_VARS.read_text(encoding="utf-8")
        variables = VARS.read_text(encoding="utf-8")
        self.assertIn("hermes_compose_admin_mode: disabled", shared)
        self.assertIn("enable-typed-compose-transactions-for-hermes-astra", shared)
        self.assertNotIn("hermes_compose_admin_mode: disabled", variables)
        self.assertLess(playbook.index("Back up prior Compose target paths"), playbook.index("Deploy root-owned Compose transaction target"))
        self.assertIn("restrict,command=", playbook)
        self.assertIn('NOPASSWD: {{ hermes_compose_admin_target_live }} ""', playbook)
        self.assertNotIn("NOPASSWD: ALL", playbook)
        self.assertIn("LoadCredential=agent-compose-key", hardening)
        self.assertNotIn("docker.sock", hardening)


if __name__ == "__main__":
    unittest.main()
