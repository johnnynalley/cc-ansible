#!/usr/bin/env python3
"""Regression tests for the Hermes shadow target audit."""

from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("hermes-shadow-target-audit.py")
POLICY = Path(__file__).parents[2] / "files" / "hermes" / "shadow-target.json"
SPEC = importlib.util.spec_from_file_location("hermes_shadow_target_audit", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class HermesShadowTargetAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = json.loads(POLICY.read_text(encoding="utf-8"))

    def write_policy(self, root: Path, data: dict) -> Path:
        path = root / "policy.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def assert_rejected(self, data: dict, reason: str) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = self.write_policy(Path(tempdir), data)
            with self.assertRaisesRegex(MODULE.AuditError, reason):
                MODULE.validate(path.resolve())

    def test_repository_policy_passes(self) -> None:
        MODULE.validate(POLICY.resolve())

    def test_unknown_top_level_key_fails_closed(self) -> None:
        data = copy.deepcopy(self.base)
        data["surprise"] = {}
        self.assert_rejected(data, "policy-top-level-schema")

    def test_production_delivery_is_rejected(self) -> None:
        data = copy.deepcopy(self.base)
        data["deployment"]["productionDeliveryEnabled"] = True
        self.assert_rejected(data, "unsafe-deployment-productionDeliveryEnabled")

    def test_vmid_before_live_gate_is_rejected(self) -> None:
        data = copy.deepcopy(self.base)
        data["deployment"]["vmid"] = 160
        self.assert_rejected(data, "vmid-selected-before-live-gate")

    def test_docker_group_is_rejected(self) -> None:
        data = copy.deepcopy(self.base)
        data["sandbox"]["dockerGroup"] = True
        self.assert_rejected(data, "unsafe-sandbox-dockerGroup")

    def test_local_terminal_fallback_is_rejected(self) -> None:
        data = copy.deepcopy(self.base)
        data["sandbox"]["localTerminalFallback"] = True
        self.assert_rejected(data, "unsafe-sandbox-localTerminalFallback")

    def test_forwarded_secret_is_rejected(self) -> None:
        data = copy.deepcopy(self.base)
        data["sandbox"]["forwardEnvironment"] = ["OPENAI_API_KEY"]
        self.assert_rejected(data, "unsafe-sandbox-forwardEnvironment")

    def test_unreviewed_memory_write_is_rejected(self) -> None:
        data = copy.deepcopy(self.base)
        data["commonPolicy"]["memoryWriteApproval"] = False
        self.assert_rejected(data, "policy-required-memoryWriteApproval")

    def test_duplicate_profile_identity_is_rejected(self) -> None:
        data = copy.deepcopy(self.base)
        data["profiles"][1]["serviceUser"] = "hermes-astra"
        self.assert_rejected(data, "profile-duplicate-serviceUser")

    def test_terminal_enabled_on_dubble_is_rejected(self) -> None:
        data = copy.deepcopy(self.base)
        data["profiles"][1]["terminalEnabled"] = True
        self.assert_rejected(data, "profile-terminal-dubble")

    def test_agent_approval_of_docker_plan_is_rejected(self) -> None:
        data = copy.deepcopy(self.base)
        data["brokers"]["agentCanApprovePlan"] = True
        self.assert_rejected(data, "unsafe-broker-agentCanApprovePlan")

    def test_symlinked_policy_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            target = self.write_policy(root, self.base)
            link = root / "policy-link.json"
            link.symlink_to(target)
            with self.assertRaisesRegex(MODULE.AuditError, "policy-symlink"):
                MODULE.validate(link)


if __name__ == "__main__":
    unittest.main()
