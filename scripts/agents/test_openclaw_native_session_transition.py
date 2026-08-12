#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("openclaw-native-session-transition.py")
SPEC = importlib.util.spec_from_file_location(
    "openclaw_native_session_transition", MODULE_PATH
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeGateway:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.archived: set[str] = set()
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self, method: str, params: dict[str, object]) -> dict[str, object]:
        self.calls.append((method, params))
        if method == "sessions.list":
            active = [row for row in self.rows if row["key"] not in self.archived]
            return {
                "sessions": active,
                "totalCount": len(active),
                "hasMore": False,
                "nextOffset": None,
            }
        if method == "sessions.patch":
            self.archived.add(str(params["key"]))
            return {"ok": True}
        raise AssertionError(method)


class NativeSessionTransitionTests(unittest.TestCase):
    def rows(self) -> list[dict[str, object]]:
        return [
            {"key": "agent:main:main", "sessionId": "main"},
            {
                "key": "agent:rigel:heartbeat:one",
                "sessionId": "heartbeat",
                "status": "completed",
                "endedAt": 1,
            },
            {
                "key": "agent:main:discord:channel:one",
                "sessionId": "discord",
                "channel": "discord",
            },
        ]

    def test_plan_is_read_only_and_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            output = Path(directory_name) / "evidence"
            gateway = FakeGateway(self.rows())
            report = MODULE.run_transition("plan", output, ["main", "rigel"], gateway)
            self.assertEqual(report["summary"]["archivePlanned"], 1)
            self.assertEqual(report["summary"]["archived"], 0)
            self.assertEqual([call[0] for call in gateway.calls], ["sessions.list"])
            for path in output.iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            private_plan = json.loads(
                (output / "transition-plan.json").read_text(encoding="utf-8")
            )
            self.assertIn("agent:rigel:heartbeat:one", json.dumps(private_plan))

    def test_apply_uses_native_patch_and_proves_clean_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            output = Path(directory_name) / "evidence"
            gateway = FakeGateway(self.rows())
            report = MODULE.run_transition("apply", output, ["main", "rigel"], gateway)
            self.assertEqual(report["summary"]["retain"], 2)
            self.assertEqual(report["summary"]["archived"], 1)
            self.assertEqual(
                [call[0] for call in gateway.calls],
                ["sessions.list", "sessions.patch", "sessions.list"],
            )
            self.assertEqual(gateway.archived, {"agent:rigel:heartbeat:one"})
            clean = json.loads(
                (output / "transition-clean.json").read_text(encoding="utf-8")
            )
            self.assertEqual(clean["summary"]["archive"], 0)

    def test_required_archive_keys_reject_unexpected_synthetic_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            gateway = FakeGateway(self.rows())
            with self.assertRaisesRegex(
                MODULE.NativeSessionTransitionError,
                "does not match",
            ):
                MODULE.run_transition(
                    "apply",
                    Path(directory_name) / "evidence",
                    ["main", "rigel"],
                    gateway,
                    {"agent:main:explicit:security-one"},
                )
            self.assertEqual([call[0] for call in gateway.calls], ["sessions.list"])

    def test_required_archive_keys_accept_exact_security_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            rows = [
                {"key": "agent:main:main", "sessionId": "main"},
                {
                    "key": "agent:main:explicit:security-one",
                    "sessionId": "security",
                    "status": "completed",
                    "endedAt": 1,
                },
            ]
            gateway = FakeGateway(rows)
            report = MODULE.run_transition(
                "apply",
                Path(directory_name) / "evidence",
                ["main"],
                gateway,
                {"agent:main:explicit:security-one"},
            )
            self.assertEqual(report["summary"]["archived"], 1)
            self.assertEqual(gateway.archived, {"agent:main:explicit:security-one"})

    def test_active_work_fails_before_any_patch(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            rows = self.rows()
            rows[1]["hasActiveRun"] = True
            gateway = FakeGateway(rows)
            with self.assertRaisesRegex(
                MODULE.NativeSessionTransitionError,
                "classification failed",
            ):
                MODULE.run_transition(
                    "apply",
                    Path(directory_name) / "evidence",
                    ["main", "rigel"],
                    gateway,
                )
            self.assertEqual([call[0] for call in gateway.calls], ["sessions.list"])

    def test_rejects_reused_evidence_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            output = Path(directory_name) / "evidence"
            output.mkdir()
            with self.assertRaisesRegex(
                MODULE.NativeSessionTransitionError,
                "unavailable",
            ):
                MODULE.run_transition(
                    "plan", output, ["main", "rigel"], FakeGateway(self.rows())
                )


if __name__ == "__main__":
    unittest.main()
