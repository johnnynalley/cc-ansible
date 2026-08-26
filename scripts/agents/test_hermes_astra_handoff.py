#!/usr/bin/env python3
"""Static and behavioral tests for Dubble's bounded Astra handoff."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[2]
SOURCE = ROOT / "files/hermes/plugins/astra-handoff/__init__.py"
VALIDATOR_SOURCE = ROOT / "scripts/agents/hermes-astra-handoff-validate.py"

agent = types.ModuleType("agent")
secret_scope = types.ModuleType("agent.secret_scope")
secret_scope.get_secret = lambda *_args, **_kwargs: "test-key"
agent.secret_scope = secret_scope
sys.modules.setdefault("agent", agent)
sys.modules.setdefault("agent.secret_scope", secret_scope)

SPEC = importlib.util.spec_from_file_location("astra_handoff", SOURCE)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "astra_handoff_validator", VALIDATOR_SOURCE
)
assert VALIDATOR_SPEC and VALIDATOR_SPEC.loader
VALIDATOR = importlib.util.module_from_spec(VALIDATOR_SPEC)
VALIDATOR_SPEC.loader.exec_module(VALIDATOR)


class Context:
    def __init__(self):
        self.tools = []

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)


class AstraHandoffTests(unittest.TestCase):
    def test_registers_one_fixed_target_tool(self):
        context = Context()
        MODULE.register(context)
        self.assertEqual(len(context.tools), 1)
        self.assertEqual(context.tools[0]["name"], "astra_handoff")
        self.assertEqual(context.tools[0]["toolset"], "astra_handoff")

    def test_invokes_native_peer_without_shell(self):
        completed = mock.Mock(returncode=0, stdout="Astra response\n", stderr="")
        with mock.patch.object(MODULE, "get_secret", return_value="key"), mock.patch.object(
            MODULE.subprocess, "run", return_value=completed
        ) as runner:
            result = MODULE._handler({"message": "Need guidance"})
        argv = runner.call_args.args[0]
        self.assertEqual(argv, ["/usr/local/bin/hermes", "peer", "dm", "astra", "Need guidance"])
        self.assertNotIn("shell", runner.call_args.kwargs)
        self.assertIn('"status": "ok"', result)

    def test_rejects_open_or_oversized_requests(self):
        self.assertIn("invalid-request", MODULE._handler({"message": "x", "peer": "rigel"}))
        self.assertIn("invalid-message", MODULE._handler({"message": "x" * 4001}))

    def test_validator_accepts_only_reviewed_memory_plugin_state(self):
        base = {
            "plugins": {"enabled": ["discord-parity", "astra-handoff"]},
            "toolsets": ["astra_handoff"],
            "bot_peers": {"astra": {"url": "http://127.0.0.1:8642"}},
            "agent": {"disabled_toolsets": ["terminal"]},
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.yaml"
            import yaml

            path.write_text(yaml.safe_dump(base), encoding="utf-8")
            VALIDATOR.validate_config(path)

            memory = dict(base)
            memory["plugins"] = {
                "enabled": ["discord-parity", "astra-handoff", "hermes-lcm"]
            }
            memory["context"] = {"engine": "lcm"}
            memory["memory"] = {"provider": "mem0"}
            path.write_text(yaml.safe_dump(memory), encoding="utf-8")
            VALIDATOR.validate_config(path)

            memory["plugins"]["enabled"].append("unexpected")
            path.write_text(yaml.safe_dump(memory), encoding="utf-8")
            with self.assertRaises(VALIDATOR.ValidationError):
                VALIDATOR.validate_config(path)


if __name__ == "__main__":
    unittest.main()
