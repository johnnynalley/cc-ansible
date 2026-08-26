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
            result["modelOverrides"][0]["provider"], "openai-codex"
        )

    def test_probe_never_emits_message_or_delivery_content(self) -> None:
        output = json.dumps(self.inspect())
        self.assertNotIn("private message not emitted", output)
        self.assertNotIn("secret detail must not appear", output)


if __name__ == "__main__":
    unittest.main()
