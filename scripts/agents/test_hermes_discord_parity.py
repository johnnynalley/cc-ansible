#!/usr/bin/env python3
"""Regressions for Astra's policy-bounded Discord parity plugin."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[2]
PLUGIN = ROOT / "files/hermes/plugins/discord-parity/__init__.py"
VALIDATOR = ROOT / "scripts/agents/hermes-discord-parity-validate.py"

agent = types.ModuleType("agent")
secret_scope = types.ModuleType("agent.secret_scope")
secret_scope.get_secret = lambda *_args, **_kwargs: "test-token"
agent.secret_scope = secret_scope
sys.modules.setdefault("agent", agent)
sys.modules.setdefault("agent.secret_scope", secret_scope)

SPEC = importlib.util.spec_from_file_location("discord_parity", PLUGIN)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

VALIDATOR_SPEC = importlib.util.spec_from_file_location("discord_parity_validator", VALIDATOR)
VALIDATOR_MODULE = importlib.util.module_from_spec(VALIDATOR_SPEC)
assert VALIDATOR_SPEC and VALIDATOR_SPEC.loader
VALIDATOR_SPEC.loader.exec_module(VALIDATOR_MODULE)


class Context:
    def __init__(self) -> None:
        self.tools = []

    def register_tool(self, **kwargs) -> None:
        self.tools.append(kwargs)


class DiscordParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = {
            "schemaVersion": 1,
            "guilds": ["1209365945882251294"],
            "channels": ["1482585492330381343"],
            "fileRoots": ["/tmp"],
        }

    def test_registers_one_closed_tool_without_source_disabled_actions(self) -> None:
        context = Context()
        MODULE.register(context)
        self.assertEqual(len(context.tools), 1)
        tool = context.tools[0]
        self.assertEqual(tool["name"], "discord_parity")
        self.assertEqual(tool["toolset"], "discord_parity")
        parameters = tool["schema"]["parameters"]
        self.assertFalse(parameters["additionalProperties"])
        actions = parameters["properties"]["action"]["enum"]
        self.assertEqual(actions, VALIDATOR_MODULE.EXPECTED_ACTIONS)
        self.assertFalse({"set_presence", "add_role", "remove_role", "ban"} & set(actions))

    def test_policy_blocks_cross_guild_and_cross_channel_calls(self) -> None:
        with mock.patch.object(MODULE, "_policy", return_value=self.policy):
            with self.assertRaisesRegex(MODULE.ParityError, "guild-not-allowed"):
                MODULE._allowed(
                    {"guild_id": "99999999999999999"}, "event_list"
                )
            with self.assertRaisesRegex(MODULE.ParityError, "channel-not-allowed"):
                MODULE._allowed(
                    {"channel_id": "99999999999999999"}, "send_message"
                )

    def test_send_uses_the_approved_channel_and_silent_flag(self) -> None:
        response = {
            "id": "1501040629025865779",
            "channel_id": "1482585492330381343",
            "content": "hello",
            "timestamp": "2026-08-20T00:00:00Z",
        }
        args = {
            "action": "send_message",
            "channel_id": "1482585492330381343",
            "content": "hello",
            "silent": True,
        }
        with mock.patch.object(MODULE, "_policy", return_value=self.policy), mock.patch.object(
            MODULE, "_request", return_value=response
        ) as request:
            result = json.loads(MODULE._handle(args))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(request.call_args.args[:2], ("POST", "/channels/1482585492330381343/messages"))
        self.assertEqual(request.call_args.kwargs["body"]["flags"], 4096)

    def test_upload_rejects_files_outside_policy_roots(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as temporary:
            path = Path(temporary) / "secret.txt"
            path.write_text("not allowed", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ParityError, "file-not-allowed"):
                MODULE._safe_file(str(path), self.policy)

    def test_search_preserves_every_channel_filter(self) -> None:
        args = {
            "guild_id": "1209365945882251294",
            "channel_ids": ["1482585492330381343"],
            "query": "release notes",
            "limit": 10,
        }
        with mock.patch.object(MODULE, "_request", return_value={}) as request:
            MODULE._dispatch(args, "search_messages", self.policy)
        self.assertEqual(
            request.call_args.kwargs["params"]["channel_id"],
            ["1482585492330381343"],
        )

    def test_missing_action_argument_fails_before_request(self) -> None:
        args = {
            "action": "edit_message",
            "channel_id": "1482585492330381343",
            "content": "updated",
        }
        with mock.patch.object(MODULE, "_policy", return_value=self.policy), mock.patch.object(
            MODULE, "_request"
        ) as request:
            result = json.loads(MODULE._handle(args))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "edit_message-message_id-required")
        request.assert_not_called()

    def test_thread_archive_requires_an_approved_parent(self) -> None:
        args = {
            "action": "thread_edit",
            "guild_id": "1209365945882251294",
            "channel_id": "1509999999999999999",
            "archived": True,
        }
        channel = {
            "id": args["channel_id"],
            "guild_id": args["guild_id"],
            "parent_id": "1482585492330381343",
        }
        with mock.patch.object(MODULE, "_policy", return_value=self.policy), mock.patch.object(
            MODULE, "_request", side_effect=[channel, {**channel, "archived": True}]
        ) as request:
            result = json.loads(MODULE._handle(args))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(request.call_args_list[0].args[:2], ("GET", f"/channels/{args['channel_id']}"))
        self.assertEqual(request.call_args_list[1].args[:2], ("PATCH", f"/channels/{args['channel_id']}"))

    def test_thread_messages_require_an_approved_parent(self) -> None:
        args = {
            "action": "thread_messages",
            "guild_id": "1209365945882251294",
            "channel_id": "1509999999999999999",
            "limit": 25,
        }
        channel = {
            "id": args["channel_id"],
            "guild_id": args["guild_id"],
            "parent_id": "1482585492330381343",
        }
        with mock.patch.object(MODULE, "_policy", return_value=self.policy), mock.patch.object(
            MODULE, "_request", side_effect=[channel, [{"id": "1"}]]
        ) as request:
            result = json.loads(MODULE._handle(args))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["messages"], [{"id": "1"}])
        self.assertEqual(request.call_args_list[1].kwargs["params"], {"limit": 25})

    def test_thread_listing_filters_unapproved_parents(self) -> None:
        active = {
            "threads": [
                {"id": "1", "parent_id": "1482585492330381343"},
                {"id": "2", "parent_id": "1508888888888888888"},
            ]
        }
        with mock.patch.object(MODULE, "_request", return_value=active):
            result = json.loads(
                MODULE._dispatch(
                    {"guild_id": "1209365945882251294"},
                    "list_threads",
                    self.policy,
                )
            )
        self.assertEqual(result["result"]["threads"], [active["threads"][0]])

    def test_channel_mutation_rejects_cross_guild_target(self) -> None:
        args = {
            "action": "channel_delete",
            "guild_id": "1209365945882251294",
            "channel_id": "1509999999999999999",
        }
        with mock.patch.object(MODULE, "_policy", return_value=self.policy), mock.patch.object(
            MODULE,
            "_request",
            return_value={"id": args["channel_id"], "guild_id": "99999999999999999"},
        ) as request:
            result = json.loads(MODULE._handle(args))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "channel-guild-mismatch")
        self.assertEqual(request.call_count, 1)

    def test_voice_event_rejects_channel_outside_approved_scope(self) -> None:
        args = {
            "action": "event_create",
            "guild_id": "1209365945882251294",
            "channel_id": "1509999999999999999",
            "name": "Movie night",
            "start_time": "2026-08-20T22:00:00Z",
        }
        channel = {
            "id": args["channel_id"],
            "guild_id": args["guild_id"],
            "parent_id": "1508888888888888888",
        }
        with mock.patch.object(MODULE, "_policy", return_value=self.policy), mock.patch.object(
            MODULE, "_request", return_value=channel
        ) as request:
            result = json.loads(MODULE._handle(args))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "thread-parent-not-allowed")
        self.assertEqual(request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
