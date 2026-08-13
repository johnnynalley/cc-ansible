#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).with_name("openclaw-star-gateway-rehearsal.py")
SPEC = importlib.util.spec_from_file_location(
    "openclaw_star_gateway_rehearsal", SCRIPT_PATH
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load Star Gateway rehearsal module")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def yielded_response() -> dict[str, Any]:
    return {
        "status": "ok",
        "result": {
            "payloads": [],
            "meta": {"yielded": True, "livenessState": "paused"},
        },
    }


def sessions(active: int) -> dict[str, Any]:
    rows = [
        {"key": f"agent:vega:subagent:{index}", "hasActiveRun": True}
        for index in range(active)
    ]
    return {"sessions": rows, "totalCount": len(rows), "hasMore": False}


def history(*texts: str) -> dict[str, Any]:
    return {
        "messages": [
            {"role": "assistant", "content": [{"type": "text", "text": text}]}
            for text in texts
        ]
    }


class FakeRpc:
    def __init__(self, responses: list[tuple[str, dict[str, Any]]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any], bool]] = []

    def __call__(
        self, method: str, params: dict[str, Any], expect_final: bool
    ) -> dict[str, Any]:
        self.calls.append((method, params, expect_final))
        expected_method, response = self.responses.pop(0)
        if method != expected_method:
            raise AssertionError(f"expected {expected_method}, got {method}")
        return response


class StarGatewayRehearsalTests(unittest.TestCase):
    def test_prompt_accepts_normal_trailing_newline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "prompt.txt"
            path.write_text("star prompt\n", encoding="utf-8")
            self.assertEqual(MODULE._read_prompt(path), "star prompt\n")

    def test_waits_for_gateway_followup_after_terminal_yield(self) -> None:
        rpc = FakeRpc(
            [
                ("agent", yielded_response()),
                ("sessions.list", sessions(1)),
                ("chat.history", history()),
                ("sessions.list", sessions(0)),
                (
                    "chat.history",
                    history("Use Cedar for $24 under the $30 cap with MFA and IMAP."),
                ),
            ]
        )
        ticks = iter([0.0, 0.0, 0.5, 1.0])
        report = MODULE.run_rehearsal(
            rpc=rpc,
            prompt="star prompt",
            agent="main",
            session_key="agent:main:explicit:behavior-star-test",
            wait_seconds=30,
            poll_seconds=0.1,
            sleep=lambda _: None,
            monotonic=lambda: next(ticks),
        )
        self.assertEqual(report["status"], "ok")
        self.assertEqual(len(report["result"]["payloads"]), 1)
        first_method, first_params, expect_final = rpc.calls[0]
        self.assertEqual(first_method, "agent")
        self.assertIs(expect_final, True)
        self.assertIs(first_params["cleanupBundleMcpOnRunEnd"], False)
        self.assertIs(first_params["deliver"], False)
        self.assertEqual(report["result"]["meta"]["activeRunCount"], 0)

    def test_rejects_one_shot_visible_result_without_yield(self) -> None:
        rpc = FakeRpc(
            [
                (
                    "agent",
                    {
                        "status": "ok",
                        "result": {
                            "payloads": [{"text": "premature"}],
                            "meta": {"yielded": False, "livenessState": "idle"},
                        },
                    },
                )
            ]
        )
        with self.assertRaisesRegex(
            MODULE.StarGatewayRehearsalError, "star-initial-visible-payload"
        ):
            MODULE.run_rehearsal(
                rpc=rpc,
                prompt="star prompt",
                agent="main",
                session_key="agent:main:explicit:behavior-star-test",
                wait_seconds=30,
                poll_seconds=0.1,
            )

    def test_rejects_multiple_visible_followup_answers(self) -> None:
        rpc = FakeRpc(
            [
                ("agent", yielded_response()),
                ("sessions.list", sessions(0)),
                ("chat.history", history("first", "second")),
            ]
        )
        with self.assertRaisesRegex(
            MODULE.StarGatewayRehearsalError, "star-visible-answer-count"
        ):
            MODULE.run_rehearsal(
                rpc=rpc,
                prompt="star prompt",
                agent="main",
                session_key="agent:main:explicit:behavior-star-test",
                wait_seconds=30,
                poll_seconds=0.1,
            )

    def test_rejects_incomplete_session_inventory(self) -> None:
        rpc = FakeRpc(
            [
                ("agent", yielded_response()),
                (
                    "sessions.list",
                    {"sessions": [], "totalCount": 1, "hasMore": False},
                ),
                ("chat.history", history()),
            ]
        )
        with self.assertRaisesRegex(
            MODULE.StarGatewayRehearsalError, "sessions-list-count"
        ):
            MODULE.run_rehearsal(
                rpc=rpc,
                prompt="star prompt",
                agent="main",
                session_key="agent:main:explicit:behavior-star-test",
                wait_seconds=30,
                poll_seconds=0.1,
            )


if __name__ == "__main__":
    unittest.main()
