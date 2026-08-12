#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("openclaw-session-transition.py")
SPEC = importlib.util.spec_from_file_location(
    "openclaw_session_transition", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SessionTransitionTests(unittest.TestCase):
    def _payload(self, sessions: list[dict]) -> dict:
        return {
            "totalCount": len(sessions),
            "hasMore": False,
            "sessions": sessions,
        }

    def test_retains_main_and_external_conversation_routes(self) -> None:
        plan = MODULE.build_transition_plan(
            self._payload(
                [
                    {"key": "agent:main:main", "hasActiveRun": False},
                    {
                        "key": "agent:main:discord:channel:123",
                        "channel": "discord",
                        "hasActiveRun": False,
                    },
                ]
            ),
            ["main"],
        )
        self.assertEqual(plan["summary"]["retain"], 2)
        self.assertEqual(plan["summary"]["archive"], 0)

    def test_archives_known_synthetic_and_completed_execution_rows(self) -> None:
        sessions = [
            {"key": "agent:main:main:heartbeat", "hasActiveRun": False},
            {"key": "agent:main:cron:job", "hasActiveRun": False},
            {
                "key": "agent:main:subagent:child",
                "status": "done",
                "endedAt": 1,
                "hasActiveRun": False,
            },
            {
                "key": "agent:main:explicit:model-run-test",
                "status": "done",
                "endedAt": 1,
                "hasActiveRun": False,
            },
            {
                "key": "agent:main:explicit:behavior-star-test",
                "status": "done",
                "endedAt": 1,
                "hasActiveRun": False,
            },
            {
                "key": "agent:main:explicit:security-boundary-test",
                "status": "done",
                "endedAt": 1,
                "hasActiveRun": False,
            },
            {
                "key": "agent:main:opaque-run",
                "status": "failed",
                "endedAt": 1,
                "hasActiveRun": False,
            },
        ]
        plan = MODULE.build_transition_plan(self._payload(sessions), ["main"])
        self.assertEqual(plan["summary"]["archive"], 7)
        self.assertEqual(plan["summary"]["retain"], 0)

    def test_retains_dormant_runtime_session_with_identity(self) -> None:
        plan = MODULE.build_transition_plan(
            self._payload(
                [
                    {
                        "key": "agent:main:opaque-runtime",
                        "sessionId": "session-id",
                        "hasActiveRun": False,
                    }
                ]
            ),
            ["main"],
        )
        self.assertEqual(
            plan["summary"]["classifications"],
            {"retain:durable-runtime-session": 1},
        )

    def test_active_work_blocks_transition(self) -> None:
        with self.assertRaisesRegex(MODULE.SessionTransitionError, "active work"):
            MODULE.build_transition_plan(
                self._payload(
                    [{"key": "agent:main:subagent:child", "hasActiveRun": True}]
                ),
                ["main"],
            )

    def test_unknown_shape_blocks_without_echoing_key(self) -> None:
        private_session_key = "agent:main:private-sensitive-name"
        with self.assertRaises(MODULE.SessionTransitionError) as raised:
            MODULE.build_transition_plan(
                self._payload([{"key": private_session_key, "hasActiveRun": False}]),
                ["main"],
            )
        self.assertNotIn(private_session_key, str(raised.exception))

    def test_incomplete_or_duplicate_response_is_rejected(self) -> None:
        with self.assertRaisesRegex(MODULE.SessionTransitionError, "incomplete"):
            MODULE.build_transition_plan(
                {"totalCount": 1, "hasMore": True, "sessions": []}, ["main"]
            )
        with self.assertRaisesRegex(MODULE.SessionTransitionError, "duplicate"):
            MODULE.build_transition_plan(
                self._payload(
                    [
                        {"key": "agent:main:main"},
                        {"key": "agent:main:main"},
                    ]
                ),
                ["main"],
            )

    def test_require_clean_rejects_pending_archive_actions(self) -> None:
        with self.assertRaisesRegex(MODULE.SessionTransitionError, "still contains"):
            MODULE.build_transition_plan(
                self._payload([{"key": "agent:main:main:heartbeat"}]),
                ["main"],
                require_clean=True,
            )

    def test_plan_file_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            MODULE._write_json_atomic(path, {"schemaVersion": 1})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
