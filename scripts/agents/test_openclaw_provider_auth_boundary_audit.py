#!/usr/bin/env python3

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sqlite3
import stat
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("openclaw-provider-auth-boundary-audit.py")
SPEC = importlib.util.spec_from_file_location(
    "openclaw_provider_auth_boundary_audit", SCRIPT
)
assert SPEC and SPEC.loader
audit_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit_module
SPEC.loader.exec_module(audit_module)


class ProviderAuthBoundaryAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = self.root / "openclaw.json"
        self.state = self.root / "state"
        self.executor_auth = self.root / "codex-home" / "auth.json"
        self.agents = ["main", "dubble", "rigel", "vega", "antares"]
        self.config.write_text(
            json.dumps(
                {
                    "auth": {
                        "profiles": {
                            "ollama-cloud:default": {
                                "provider": "ollama-cloud",
                                "mode": "token",
                            }
                        },
                        "order": {"ollama-cloud": ["ollama-cloud:default"]},
                    }
                }
            ),
            encoding="utf-8",
        )
        (self.state / "agents").mkdir(parents=True)
        for agent in self.agents:
            agent_root = self.state / "agents" / agent / "agent"
            agent_root.mkdir(parents=True)
            connection = sqlite3.connect(agent_root / "openclaw-agent.sqlite")
            with connection:
                connection.execute(
                    "CREATE TABLE auth_profile_state (id TEXT PRIMARY KEY, value TEXT)"
                )
                connection.execute(
                    "CREATE TABLE auth_profile_store (id TEXT PRIMARY KEY, value TEXT)"
                )
            connection.close()
        self.executor_auth.parent.mkdir(parents=True)
        self.executor_auth.write_text(
            '{"tokens":"redacted-fixture"}\n', encoding="utf-8"
        )
        self.executor_auth.chmod(0o600)
        self.args = argparse.Namespace(
            gateway_config=self.config,
            gateway_state=self.state,
            executor_auth=self.executor_auth,
            executor_owner=str(os.getuid()),
            executor_group=str(os.getgid()),
            agent=self.agents,
            output=None,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_clean_boundary_passes_without_exposing_auth_content(self) -> None:
        result = audit_module.audit(self.args)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["gatewayConfig"]["openaiProfileCount"], 0)
        self.assertNotIn("tokens", json.dumps(result))
        self.assertTrue(result["executorAuth"]["present"])

    def test_gateway_openai_profile_is_rejected(self) -> None:
        config = json.loads(self.config.read_text(encoding="utf-8"))
        config["auth"]["profiles"]["openai:default"] = {
            "provider": "openai",
            "mode": "oauth",
        }
        self.config.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(
            audit_module.AuthBoundaryError, "gateway-openai-auth-profile-present"
        ):
            audit_module.audit(self.args)

    def test_nonempty_gateway_auth_table_is_rejected(self) -> None:
        database = self.state / "agents" / "main" / "agent" / "openclaw-agent.sqlite"
        connection = sqlite3.connect(database)
        with connection:
            connection.execute(
                "INSERT INTO auth_profile_store VALUES ('openai:default', 'secret')"
            )
        connection.close()
        with self.assertRaisesRegex(
            audit_module.AuthBoundaryError,
            "gateway-agent-auth-not-empty:auth_profile_store",
        ):
            audit_module.audit(self.args)

    def test_legacy_gateway_auth_file_is_rejected(self) -> None:
        legacy = self.state / "agents" / "main" / "agent" / "auth-profiles.json"
        legacy.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(
            audit_module.AuthBoundaryError, "legacy-auth-file-present:main"
        ):
            audit_module.audit(self.args)

    def test_missing_executor_auth_is_rejected(self) -> None:
        self.executor_auth.unlink()
        with self.assertRaisesRegex(
            audit_module.AuthBoundaryError, "executor-auth-unavailable"
        ):
            audit_module.audit(self.args)

    def test_weak_executor_auth_mode_is_rejected(self) -> None:
        self.executor_auth.chmod(0o640)
        self.assertEqual(stat.S_IMODE(self.executor_auth.stat().st_mode), 0o640)
        with self.assertRaisesRegex(
            audit_module.AuthBoundaryError, "executor-auth-mode"
        ):
            audit_module.audit(self.args)

    def test_unexpected_agent_state_is_rejected(self) -> None:
        (self.state / "agents" / "legacy").mkdir()
        with self.assertRaisesRegex(
            audit_module.AuthBoundaryError, "unexpected-gateway-agent-state:legacy"
        ):
            audit_module.audit(self.args)


if __name__ == "__main__":
    unittest.main()
