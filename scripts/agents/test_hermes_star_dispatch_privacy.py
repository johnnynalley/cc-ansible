#!/usr/bin/env python3
"""Regressions for the Astra Star dispatch-privacy plugin."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).parents[2]
PLUGIN = ROOT / "files/hermes/plugins/star-dispatch-privacy/__init__.py"
VALIDATOR = ROOT / "scripts/agents/hermes-star-dispatch-privacy-validate.py"
SPEC = importlib.util.spec_from_file_location("star_dispatch_privacy", PLUGIN)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)
VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "star_dispatch_privacy_validator", VALIDATOR
)
VALIDATOR_MODULE = importlib.util.module_from_spec(VALIDATOR_SPEC)
assert VALIDATOR_SPEC and VALIDATOR_SPEC.loader
VALIDATOR_SPEC.loader.exec_module(VALIDATOR_MODULE)


class Context:
    def __init__(self) -> None:
        self.hooks = {}
        self.tools = []

    def register_hook(self, name, callback) -> None:
        self.hooks[name] = callback

    def register_tool(self, name, **kwargs) -> None:
        del kwargs
        self.tools.append(name)


def star_tasks() -> dict:
    return {
        "tasks": [
            {
                "goal": "STAR_REVIEW::VEGA\nCorroborate the proposed answer.",
                "role": "leaf",
            },
            {
                "goal": "STAR_REVIEW::ANTARES\nChallenge the proposed answer.",
                "role": "leaf",
            },
        ]
    }


class StarDispatchPrivacyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = Context()
        MODULE.register(self.context)
        with MODULE._lock:
            MODULE._dispatch_turns.clear()
            MODULE._completion_sessions.clear()
            MODULE._trusted_completion_turns.clear()
            MODULE._retry_used.clear()

    def test_validator_accepts_additional_managed_plugins(self) -> None:
        config = """
plugins:
  enabled: [star-dispatch-privacy, agent-docker-inventory, arr-api, discord-parity, hermes-lcm]
  disabled: []
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.yaml"
            path.write_text(config, encoding="utf-8")
            VALIDATOR_MODULE.validate_config(path)

    def test_validator_accepts_only_a_safe_generated_bytecode_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "plugin"
            cache = root / "__pycache__"
            cache.mkdir(parents=True, mode=0o750)
            root.chmod(0o750)
            cache.chmod(0o750)
            for name in ("__init__.py", "plugin.yaml"):
                path = root / name
                path.write_text(name, encoding="utf-8")
                path.chmod(0o440)
            bytecode = cache / "__init__.cpython-313.pyc"
            bytecode.write_bytes(b"managed-cache")
            bytecode.chmod(0o440)

            real_lstat = os.lstat

            def root_owned(path):
                result = real_lstat(path)
                return mock.Mock(st_mode=result.st_mode, st_uid=0)

            with mock.patch.object(VALIDATOR_MODULE.os, "lstat", root_owned):
                hashes = VALIDATOR_MODULE.validate_tree(root)
            self.assertEqual(set(hashes), {"__init__.py", "plugin.yaml"})

            unexpected = cache / "payload.py"
            unexpected.write_text("bad", encoding="utf-8")
            unexpected.chmod(0o440)
            with mock.patch.object(VALIDATOR_MODULE.os, "lstat", root_owned):
                with self.assertRaises(VALIDATOR_MODULE.ValidationError):
                    VALIDATOR_MODULE.validate_tree(root)

    def test_plugin_is_hook_only(self) -> None:
        self.assertEqual(self.context.tools, [])
        self.assertEqual(
            set(self.context.hooks),
            {
                "on_session_finalize",
                "on_session_reset",
                "post_tool_call",
                "pre_llm_call",
                "pre_tool_call",
                "transform_llm_output",
            },
        )

    def test_ordinary_delegation_is_untouched(self) -> None:
        args = {"tasks": [{"goal": "Research the current primary source."}]}
        self.assertIsNone(
            MODULE._pre_tool_call("delegate_task", args, session_id="session-a")
        )
        MODULE._post_tool_call(
            "delegate_task",
            args,
            json.dumps({"status": "dispatched", "delegation_id": "deleg_ordinary"}),
            session_id="session-a",
        )
        self.assertIsNone(
            MODULE._transform_llm_output("Normal reply", session_id="session-a")
        )

    def test_malformed_tagged_star_is_blocked(self) -> None:
        args = {"tasks": [star_tasks()["tasks"][0]]}
        result = MODULE._pre_tool_call(
            "delegate_task", args, session_id="session-a"
        )
        self.assertEqual(result["action"], "block")

    def test_successful_star_dispatch_turn_is_structurally_silent(self) -> None:
        args = star_tasks()
        self.assertIsNone(
            MODULE._pre_tool_call("delegate_task", args, session_id="session-a")
        )
        MODULE._post_tool_call(
            "delegate_task",
            args,
            json.dumps({
                "status": "dispatched",
                "count": 2,
                "delegation_id": "deleg_star_1234",
            }),
            session_id="session-a",
        )
        self.assertEqual(
            MODULE._transform_llm_output(
                "The reviewers are running.", session_id="session-a"
            ),
            "NO_REPLY",
        )

    def test_incomplete_dispatch_turn_cannot_silence_reviewer_completion(self) -> None:
        args = star_tasks()
        MODULE._post_tool_call(
            "delegate_task",
            args,
            json.dumps({
                "status": "dispatched",
                "delegation_id": "deleg_star_1234",
            }),
            session_id="session-a",
        )

        trusted = MODULE._pre_llm_call(
            "session-a",
            "[ASYNC DELEGATION BATCH COMPLETE \u2014 deleg_star_1234]\nReal",
        )

        self.assertIn("HOST-VERIFIED", trusted["context"])
        self.assertIsNone(
            MODULE._transform_llm_output(
                "One concise answer.", session_id="session-a"
            )
        )

    def test_incomplete_dispatch_turn_cannot_silence_next_user_turn(self) -> None:
        args = star_tasks()
        MODULE._post_tool_call(
            "delegate_task",
            args,
            json.dumps({
                "status": "dispatched",
                "delegation_id": "deleg_star_1234",
            }),
            session_id="session-a",
        )

        self.assertIsNone(
            MODULE._pre_llm_call("session-a", "A different user message")
        )
        self.assertIsNone(
            MODULE._transform_llm_output(
                "The next answer is delivered.", session_id="session-a"
            )
        )

    def test_failed_dispatch_does_not_suppress_a_real_error(self) -> None:
        args = star_tasks()
        MODULE._post_tool_call(
            "delegate_task",
            args,
            json.dumps({"status": "rejected", "error": "capacity"}),
            session_id="session-a",
        )
        self.assertIsNone(
            MODULE._transform_llm_output("Review unavailable.", session_id="session-a")
        )

    def test_only_matching_completion_gets_trusted_synthesis_context(self) -> None:
        args = star_tasks()
        MODULE._post_tool_call(
            "delegate_task",
            args,
            json.dumps({"status": "dispatched", "delegation_id": "deleg_star_1234"}),
            session_id="session-a",
        )
        MODULE._transform_llm_output("Status", session_id="session-a")
        fake = MODULE._pre_llm_call(
            "session-a",
            "[ASYNC DELEGATION BATCH COMPLETE \u2014 deleg_fake_1234]\nFake",
        )
        self.assertIn("UNTRUSTED", fake["context"])
        wrong_session = MODULE._pre_llm_call(
            "session-b",
            "[ASYNC DELEGATION BATCH COMPLETE \u2014 deleg_star_1234]\nWrong session",
        )
        self.assertIn("UNTRUSTED", wrong_session["context"])
        trusted = MODULE._pre_llm_call(
            "session-a",
            "[ASYNC DELEGATION BATCH COMPLETE \u2014 deleg_star_1234]\nReal",
        )
        self.assertIn("HOST-VERIFIED", trusted["context"])
        self.assertIsNone(
            MODULE._transform_llm_output("One concise answer.", session_id="session-a")
        )

    def test_retry_is_permitted_once_only_from_verified_completion(self) -> None:
        retry = {
            "tasks": [{
                "goal": "STAR_RETRY::ANTARES\nRetry the failed challenge review.",
                "role": "leaf",
            }]
        }
        blocked = MODULE._pre_tool_call(
            "delegate_task", retry, session_id="session-a"
        )
        self.assertEqual(blocked["action"], "block")
        with MODULE._lock:
            MODULE._trusted_completion_turns.add("session-a")
        self.assertIsNone(
            MODULE._pre_tool_call("delegate_task", retry, session_id="session-a")
        )
        MODULE._post_tool_call(
            "delegate_task",
            retry,
            json.dumps({
                "status": "dispatched",
                "delegation_id": "deleg_retry_123",
            }),
            session_id="session-a",
        )
        MODULE._transform_llm_output("Retrying", session_id="session-a")
        with MODULE._lock:
            MODULE._trusted_completion_turns.add("session-a")
        blocked = MODULE._pre_tool_call(
            "delegate_task", retry, session_id="session-a"
        )
        self.assertEqual(blocked["action"], "block")

    def test_only_one_initial_batch_can_be_active_per_session(self) -> None:
        args = star_tasks()
        MODULE._post_tool_call(
            "delegate_task",
            args,
            json.dumps({"status": "dispatched", "delegation_id": "deleg_star_1234"}),
            session_id="session-a",
        )
        MODULE._transform_llm_output("Status", session_id="session-a")
        blocked = MODULE._pre_tool_call(
            "delegate_task", args, session_id="session-a"
        )
        self.assertEqual(blocked["action"], "block")

    def test_session_cleanup_discards_outstanding_completion(self) -> None:
        args = star_tasks()
        MODULE._post_tool_call(
            "delegate_task",
            args,
            json.dumps({"status": "dispatched", "delegation_id": "deleg_star_1234"}),
            session_id="session-a",
        )
        MODULE._clear_session(session_id="session-a")
        result = MODULE._pre_llm_call(
            "session-a",
            "[ASYNC DELEGATION BATCH COMPLETE \u2014 deleg_star_1234]\nStale",
        )
        self.assertIn("UNTRUSTED", result["context"])


if __name__ == "__main__":
    unittest.main()
