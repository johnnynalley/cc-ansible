#!/usr/bin/env python3
"""Regression tests for private Hermes Discord enrollment."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).with_name("hermes-discord-enroll.py")
SPEC = importlib.util.spec_from_file_location("hermes_discord_enroll", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class HermesDiscordEnrollTests(unittest.TestCase):
    def fixture(self) -> tuple[dict[str, str], dict]:
        env = {
            "DISCORD_BOT_TOKEN": "a" * 64,
            "DISCORD_DUBBLE_BOT_TOKEN": "b" * 64,
            "ANTHROPIC_API_KEY": "c" * 64,
        }
        owner = "1111111111111111"
        config = {
            "channels": {
                "discord": {
                    "allowFrom": [owner],
                    "guilds": {
                        "guild": {
                            "channels": {
                                "1000000000000001": {"enabled": True},
                                "1000000000000002": {"enabled": True},
                                "1000000000000003": {"enabled": True},
                            }
                        }
                    },
                    "accounts": {
                        "default": {"allowFrom": [owner], "guilds": {}},
                        "dubble": {
                            "guilds": {
                                "guild": {
                                    "channels": {
                                        "1000000000000004": {"enabled": True}
                                    }
                                }
                            }
                        },
                    },
                }
            }
        }
        return env, config

    def discoveries(self):
        return [
            (
                "2000000000000001",
                {
                    "astra": "1000000000000001",
                    "astra-logs": "1000000000000002",
                    "rigel": "1000000000000003",
                },
            ),
            ("2000000000000002", {"dubble": "1000000000000004"}),
        ]

    def test_build_preserves_two_consumers_and_three_logical_roles(self) -> None:
        env, config = self.fixture()
        with mock.patch.object(
            MODULE, "bot_and_channels", side_effect=self.discoveries()
        ):
            enrollment, credentials = MODULE.build_enrollment(env, config)
        self.assertEqual(enrollment["consumerCount"], 2)
        self.assertEqual(enrollment["logicalProfiles"], ["astra", "dubble", "rigel"])
        self.assertEqual(
            enrollment["profiles"]["rigel"]["discordConsumer"], "astra"
        )
        astra = enrollment["profiles"]["astra"]
        self.assertEqual(astra["ignoredChannels"], ["1000000000000002"])
        self.assertEqual(
            astra["channelSkillBindings"],
            [{"id": "1000000000000003", "skills": ["source-grounded-study"]}],
        )
        self.assertIn("DISCORD_BOT_TOKEN=" + "a" * 64, credentials["astra"])
        self.assertIn("DISCORD_BOT_TOKEN=" + "b" * 64, credentials["dubble"])
        self.assertNotIn("DISCORD_BOT_TOKEN", credentials["rigel"])
        self.assertNotIn("ANTHROPIC_API_KEY", credentials["astra"])

    def test_duplicate_bot_identity_is_rejected(self) -> None:
        env, config = self.fixture()
        discoveries = self.discoveries()
        discoveries[1] = (discoveries[0][0], discoveries[1][1])
        with mock.patch.object(MODULE, "bot_and_channels", side_effect=discoveries):
            with self.assertRaisesRegex(
                MODULE.EnrollmentError, "discord-bot-identities-not-distinct"
            ):
                MODULE.build_enrollment(env, config)

    def test_discovered_channel_must_be_enabled_in_source(self) -> None:
        env, config = self.fixture()
        del config["channels"]["discord"]["guilds"]["guild"]["channels"][
            "1000000000000003"
        ]
        with mock.patch.object(
            MODULE, "bot_and_channels", side_effect=self.discoveries()
        ):
            with self.assertRaisesRegex(
                MODULE.EnrollmentError, "source-astra-route-mismatch"
            ):
                MODULE.build_enrollment(env, config)

    def test_source_secret_file_must_not_be_group_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("DISCORD_BOT_TOKEN=value\n", encoding="utf-8")
            os.chmod(path, 0o640)
            with self.assertRaisesRegex(MODULE.EnrollmentError, "permissions"):
                MODULE.read_dotenv(path)

    def test_normal_output_schema_contains_no_private_values(self) -> None:
        result = {"schemaVersion": 1, "status": "ok", "consumers": 2, "profiles": 3, "channels": 4}
        serialized = json.dumps(result)
        self.assertNotRegex(serialized, r"\b\d{16,20}\b")
        for forbidden in ("token", "user", "guild", "channelId"):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
