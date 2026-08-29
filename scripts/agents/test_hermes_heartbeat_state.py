#!/usr/bin/env python3
"""Regression tests for the content-free Hermes heartbeat state probe."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "agents" / "hermes-heartbeat-state.py"


def load_module():
    spec = importlib.util.spec_from_file_location("hermes_heartbeat_state", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class HermesHeartbeatStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        (self.home / "sessions").mkdir()
        self.now = 2_000_000_000.0
        self.session_key = "agent:main:discord:group:123:456"
        (self.home / "sessions" / "sessions.json").write_text(
            json.dumps(
                {
                    "_README": "schema",
                    self.session_key: {
                        "session_id": "discord-session",
                        "active_turn_token": None,
                        "active_turn_started_at": None,
                        "model_override": {
                            "model": "gpt-5.4-mini",
                            "provider": "openai-codex",
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        self.create_database()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create_database(self) -> None:
        with closing(sqlite3.connect(self.home / "state.db")) as connection:
            connection.executescript(
                """
                CREATE TABLE sessions (
                  id TEXT, session_key TEXT, source TEXT, last_activity_at REAL,
                  ended_at REAL, model TEXT, billing_provider TEXT,
                  billing_mode TEXT
                );
                CREATE TABLE messages (
                  id INTEGER PRIMARY KEY, session_id TEXT, role TEXT,
                  content TEXT, tool_calls TEXT, reasoning TEXT,
                  reasoning_content TEXT, finish_reason TEXT, timestamp REAL,
                  active INTEGER
                );
                CREATE TABLE delivery_obligations (
                  obligation_id TEXT, session_key TEXT, platform TEXT,
                  state TEXT, attempts INTEGER, created_at REAL, updated_at REAL,
                  owner_pid INTEGER, last_error TEXT
                );
                CREATE TABLE session_model_usage (
                  model TEXT, billing_provider TEXT, billing_mode TEXT,
                  api_call_count INTEGER, last_seen REAL
                );
                """
            )
            connection.execute(
                "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?)",
                (
                    "discord-session",
                    self.session_key,
                    "discord",
                    self.now - 60,
                    None,
                    "gpt-5.6-sol",
                    "openai-codex",
                    "subscription_included",
                ),
            )
            connection.execute(
                "INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    1,
                    "discord-session",
                    "user",
                    "private message not emitted",
                    None,
                    None,
                    None,
                    None,
                    self.now - 60,
                    1,
                ),
            )
            connection.execute(
                "INSERT INTO delivery_obligations VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    "obligation-1",
                    self.session_key,
                    "discord",
                    "failed",
                    2,
                    self.now - 600,
                    self.now - 300,
                    999,
                    "HTTPError: secret detail must not appear",
                ),
            )
            connection.execute(
                "INSERT INTO session_model_usage VALUES (?,?,?,?,?)",
                (
                    "gpt-5.6-sol",
                    "openai-codex",
                    "subscription_included",
                    3,
                    self.now - 30,
                ),
            )
            connection.execute(
                "INSERT INTO session_model_usage VALUES (?,?,?,?,?)",
                (
                    "gemini-2.5-flash",
                    "gemini",
                    "api_key",
                    1,
                    self.now - 20,
                ),
            )
            connection.execute(
                "INSERT INTO session_model_usage VALUES (?,?,?,?,?)",
                (
                    "glm-5.2",
                    "",
                    "",
                    2,
                    self.now - 10,
                ),
            )
            connection.commit()

    def inspect(self):
        args = type(
            "Args",
            (),
            {
                "profile_home": self.home,
                "window_hours": 6.0,
                "stalled_after_seconds": 900.0,
                "now": self.now,
            },
        )()
        return self.module.inspect(args)

    def test_probe_reports_unanswered_turn_delivery_and_metered_route(self) -> None:
        result = self.inspect()
        self.assertEqual(result["schemaVersion"], 1)
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["discordSessions"][0]["unansweredUserTurn"])
        self.assertEqual(result["delivery"]["unresolved"][0]["state"], "failed")
        self.assertEqual(
            result["delivery"]["unresolved"][0]["lastErrorClass"], "HTTPError"
        )
        self.assertEqual(
            result["models"]["unexpectedMeteredRoutes"][0]["billingProvider"],
            "gemini",
        )
        self.assertEqual(
            result["models"]["unknownProvenanceRoutes"][0]["model"],
            "glm-5.2",
        )
        self.assertNotIn(
            "glm-5.2",
            {
                route["model"]
                for route in result["models"]["unexpectedMeteredRoutes"]
            },
        )
        self.assertEqual(
            result["modelOverrides"][0]["provider"], "openai-codex"
        )

    def test_probe_never_emits_message_or_delivery_content(self) -> None:
        output = json.dumps(self.inspect())
        self.assertNotIn("private message not emitted", output)
        self.assertNotIn("secret detail must not appear", output)

    def test_maintenance_lease_serializes_semantic_jobs_and_expires(self) -> None:
        code, acquired = self.module.maintenance_lease(
            self.home,
            action="acquire",
            owner="heartbeat",
            now=self.now,
            lease_seconds=3600,
        )
        self.assertEqual(code, 0)
        self.assertEqual(acquired["status"], "acquired")
        lease = self.home / "state" / "maintenance" / "semantic-lease.json"
        self.assertEqual(lease.stat().st_mode & 0o777, 0o600)

        code, busy = self.module.maintenance_lease(
            self.home,
            action="acquire",
            owner="self-evolution",
            now=self.now + 60,
            lease_seconds=3600,
        )
        self.assertEqual(code, 3)
        self.assertEqual(busy["status"], "busy")
        self.assertEqual(busy["owner"], "heartbeat")

        code, expired = self.module.maintenance_lease(
            self.home,
            action="acquire",
            owner="self-evolution",
            now=self.now + 3601,
            lease_seconds=3600,
        )
        self.assertEqual(code, 0)
        self.assertEqual(expired["owner"], "self-evolution")

        code, released = self.module.maintenance_lease(
            self.home,
            action="release",
            owner="self-evolution",
            now=self.now + 3602,
            lease_seconds=3600,
        )
        self.assertEqual(code, 0)
        self.assertEqual(released["status"], "released")
        self.assertFalse(lease.exists())

    def test_maintenance_lease_rejects_invalid_state(self) -> None:
        state = self.home / "state" / "maintenance"
        state.mkdir(parents=True)
        (state / "semantic-lease.json").write_text("not-json", encoding="utf-8")
        code, result = self.module.maintenance_lease(
            self.home,
            action="acquire",
            owner="heartbeat",
            now=self.now,
            lease_seconds=3600,
        )
        self.assertEqual(code, 2)
        self.assertEqual(result["code"], "lease-state-invalid")


if __name__ == "__main__":
    unittest.main()
