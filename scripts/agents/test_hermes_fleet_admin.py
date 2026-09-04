#!/usr/bin/env python3
"""Focused regressions for Astra's owner-only fleet administration."""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BROKER = load(ROOT / "scripts/agents/hermes-fleet-admin-broker.py", "fleet_admin_broker")
agent = types.ModuleType("agent")
secret_scope = types.ModuleType("agent.secret_scope")
secret_scope.get_secret = lambda name, default=None: default
agent.secret_scope = secret_scope
with mock.patch.dict(sys.modules, {"agent": agent, "agent.secret_scope": secret_scope}):
    PLUGIN = load(ROOT / "files/hermes/plugins/fleet-admin/__init__.py", "fleet_admin_plugin")


class FleetAdminTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_targets = BROKER.TARGETS

    def tearDown(self) -> None:
        BROKER.TARGETS = self.original_targets

    def make_target(self, root: Path) -> dict[str, object]:
        profile = root / "profile"
        workspace = root / "workspace"
        managed_root = root / "etc"
        for path in (profile / "skills", profile / "cron", workspace, managed_root):
            path.mkdir(parents=True, exist_ok=True)
        config = profile / "config.yaml"
        config.write_text("model:\n  default: test\n", encoding="utf-8")
        environment = managed_root / ".env"
        environment.write_text("", encoding="utf-8")
        (profile / "cron/jobs.json").write_text("[]\n", encoding="utf-8")
        return {
            "user": os.getlogin() if os.isatty(0) else "nobody",
            "group": "nogroup",
            "unit": "example.service",
            "account": root,
            "profile": profile,
            "workspace": workspace,
            "config": config,
            "managed_dir": managed_root,
            "environment": environment,
        }

    def test_fleet_targets_include_astra_and_config_is_native(self) -> None:
        self.assertEqual(PLUGIN.TARGETS, ["astra", "dubble", "rigel"])
        for target in BROKER.TARGETS.values():
            self.assertEqual(target["config"], target["profile"] / "config.yaml")
            self.assertEqual(
                target["managed_dir"],
                Path("/etc/hermes") / target["profile"].name,
            )
        smoke = (ROOT / "scripts/agents/hermes-fleet-admin-smoke.py").read_text(encoding="utf-8")
        self.assertIn('choices=["astra", "dubble", "rigel"]', smoke)

    def test_plugin_rejects_model_supplied_session_and_malformed_request(self) -> None:
        result = json.loads(
            PLUGIN._handler(
                {"target": "rigel", "operation": "inspect", "sessionId": "forged"},
                session_id="real",
            )
        )
        self.assertEqual(result["code"], "invalid-request")
        missing_hash = json.loads(
            PLUGIN._handler(
                {
                    "target": "rigel",
                    "operation": "write",
                    "root": "workspace",
                    "path": "courses/test.md",
                    "content": "test\n",
                },
                session_id="real",
            )
        )
        self.assertEqual(missing_hash["code"], "invalid-request")

    def test_plugin_authorizes_only_exact_owner_origin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.db"
            database = sqlite3.connect(state)
            database.execute(
                "CREATE TABLE sessions (id TEXT, source TEXT, user_id TEXT, chat_id TEXT, chat_type TEXT, origin_json TEXT)"
            )
            good_origin = {
                "platform": "discord",
                "user_id": "740687933803331726",
                "chat_id": "1482585492330381343",
                "guild_id": "1209365945882251294",
            }
            database.execute(
                "INSERT INTO sessions VALUES (?,?,?,?,?,?)",
                (
                    "good",
                    "discord",
                    "740687933803331726",
                    "1482585492330381343",
                    "channel",
                    json.dumps(good_origin),
                ),
            )
            database.execute(
                "INSERT INTO sessions VALUES (?,?,?,?,?,?)",
                (
                    "bad",
                    "discord",
                    "1",
                    "1482585492330381343",
                    "channel",
                    json.dumps({**good_origin, "user_id": "1"}),
                ),
            )
            database.commit()
            database.close()
            policy = {
                "allowedSource": "discord",
                "allowedUserIds": ["740687933803331726"],
                "allowedGuildIds": ["1209365945882251294"],
                "allowedChannelIds": ["1482585492330381343"],
            }
            with mock.patch.object(PLUGIN, "STATE_DB", state):
                PLUGIN._authorize_session("good", policy)
                with self.assertRaisesRegex(ValueError, "session-denied"):
                    PLUGIN._authorize_session("bad", policy)

    def test_broker_request_contract_and_hmac_replay(self) -> None:
        key = b"a" * 64
        server = BROKER.Server(Path("/tmp/fleet.sock"), 0, key, Path("/tmp/backups"), Path("/tmp/audit"))
        request = {
            "schemaVersion": 1,
            "sessionId": "session",
            "timestamp": int(time.time()),
            "nonce": "b" * 32,
            "target": "rigel",
            "operation": "inspect",
        }
        signed = dict(request)
        signed["signature"] = hmac.new(key, BROKER.canonical(request), hashlib.sha256).hexdigest()
        self.assertEqual(server.authenticate(dict(signed))["target"], "rigel")
        with self.assertRaisesRegex(BROKER.BrokerError, "replay-denied"):
            server.authenticate(dict(signed))
        invalid = dict(request, nonce="c" * 32, extra="denied")
        invalid["signature"] = hmac.new(key, BROKER.canonical(invalid), hashlib.sha256).hexdigest()
        with self.assertRaisesRegex(BROKER.BrokerError, "invalid-request"):
            server.authenticate(invalid)

    def test_path_boundaries_deny_secrets_symlinks_and_shared_skill_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.make_target(root)
            BROKER.TARGETS = {"rigel": target}
            with self.assertRaisesRegex(BROKER.BrokerError, "invalid-path"):
                BROKER.root_path("rigel", "workspace", "../escape", mutate=False)
            with self.assertRaisesRegex(BROKER.BrokerError, "sensitive-path-denied"):
                BROKER.root_path("rigel", "workspace", ".env", mutate=False)
            with self.assertRaisesRegex(BROKER.BrokerError, "shared-skill-managed-by-astra"):
                BROKER.root_path("rigel", "skills", "self-evolution/SKILL.md", mutate=True)
            (target["workspace"] / "link").symlink_to("/tmp")
            with self.assertRaisesRegex(BROKER.BrokerError, "symlink-denied"):
                BROKER.root_path("rigel", "workspace", "link/file", mutate=False)

    def test_root_listing_is_bounded_by_logical_surface(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.make_target(root)
            (target["profile"] / "AGENTS.md").write_text("agent\n", encoding="utf-8")
            (target["profile"] / "state.db").write_text("secret\n", encoding="utf-8")
            BROKER.TARGETS = {"rigel": target}
            response, _ = BROKER.process(
                {"target": "rigel", "operation": "list", "root": "bootstrap", "path": "."},
                root / "rollbacks",
            )
            self.assertEqual([item["path"] for item in response["entries"]], ["AGENTS.md"])

    def test_mutation_requires_current_hash_and_mounted_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.make_target(root)
            path = target["workspace"] / "notes.txt"
            path.write_text("before\n", encoding="utf-8")
            with self.assertRaisesRegex(BROKER.BrokerError, "concurrent-change"):
                BROKER.require_expected(path, "0" * 64)
            old_mount = BROKER.ROLLBACK_MOUNT
            BROKER.ROLLBACK_MOUNT = root / "rollback-mount"
            backup_root = BROKER.ROLLBACK_MOUNT / "fleet"
            try:
                with mock.patch.object(BROKER.os.path, "ismount", return_value=False):
                    with self.assertRaisesRegex(BROKER.BrokerError, "rollback-mount-unavailable"):
                        BROKER.backup_file(
                            backup_root,
                            {"target": "rigel", "operation": "write", "nonce": "a" * 32},
                            path,
                            BROKER.digest(path),
                        )
            finally:
                BROKER.ROLLBACK_MOUNT = old_mount

    def test_config_rejects_embedded_credentials(self) -> None:
        with self.assertRaisesRegex(BROKER.BrokerError, "secret-config-denied"):
            BROKER.validate_content("config", "config.yaml", "provider:\n  api_key: exposed\n")

    def test_platform_sources_keep_key_root_only_and_gateway_sandboxed(self) -> None:
        service = (ROOT / "templates/hermes/hermes-fleet-admin.service.j2").read_text(encoding="utf-8")
        dropin = (ROOT / "templates/hermes/hermes-gateway-fleet-admin.conf.j2").read_text(encoding="utf-8")
        playbook = (ROOT / "playbooks/agents/hermes-fleet-admin.yml").read_text(encoding="utf-8")
        self.assertIn("LoadCredential=fleet-admin-key:", service)
        self.assertIn("Group={{ hermes_fleet_admin_group }}", service)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", service)
        self.assertIn("IPAddressDeny=any", service)
        self.assertIn("-/etc/hermes/dubble/.env", service)
        self.assertIn("-/etc/hermes/astra/.env", service)
        self.assertIn("/var/lib/hermes/astra/.hermes/profiles/astra", service)
        self.assertNotIn(" /etc/hermes/dubble /etc/hermes/rigel", service)
        self.assertIn("-/var/lib/hermes/rigel/.hermes/profiles/rigel/lcm.db", service)
        self.assertIn("EnvironmentFile=-{{ hermes_fleet_admin_gateway_environment }}", dropin)
        self.assertIn("ExecStartPre=+{{ hermes_shadow_runtime_venv }}/bin/python {{ hermes_fleet_admin_validator_live }}", dropin)
        self.assertIn("hermes-gateway-astra.service.d/40-fleet-admin.conf", playbook)
        self.assertIn("Append fleet plugin through Hermes native configuration", playbook)
        self.assertIn("Append fleet toolset through Hermes native configuration", playbook)
        self.assertIn("Reassert platform traversal after Hermes native configuration", playbook)
        self.assertIn("Prove native fleet append preserved unrelated Astra configuration", playbook)
        self.assertNotIn("hermes-managed-config.yaml.j2", playbook)
        self.assertNotIn("hermes-gateway-hardening.conf.j2", playbook)
        self.assertIn('mode: "0400"', playbook)
        self.assertIn("Verify off-host rollback mount before fleet promotion", playbook)
        self.assertIn("Prepare Astra planned-stop marker for fleet administration", playbook)
        self.assertIn("Prove agent users cannot read root-only fleet key material", playbook)
        self.assertIn("Exercise one owner-provenance fleet mutation round trip as Astra", playbook)
        self.assertIn("hermes_fleet_admin_mutation_acceptance | bool", playbook)
        self.assertIn('path: /etc/hermes/astra\n          kind: directory', playbook)
        self.assertIn('mode: "0750"', playbook)
        self.assertIn("hermes_fleet_admin_current_config_raw", playbook)
        self.assertIn("hermes_fleet_admin_current_plugins", playbook)
        self.assertIn("hermes_fleet_admin_current_toolsets", playbook)


if __name__ == "__main__":
    unittest.main()
