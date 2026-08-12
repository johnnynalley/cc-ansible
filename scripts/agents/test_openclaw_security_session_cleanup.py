#!/usr/bin/env python3
"""Tests for failed OpenClaw security-session cleanup."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("openclaw-security-session-cleanup.py")
SPEC = importlib.util.spec_from_file_location(
    "openclaw_security_session_cleanup", MODULE_PATH
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SecuritySessionCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.sessions = self.state / "agents" / "main" / "sessions"
        self.sessions.mkdir(parents=True)
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()
        self.key = "agent:main:explicit:security-test"
        self.session_id = "12345678-1234-1234-1234-123456789abc"
        self.before = self.evidence / "sessions-before.json"
        self.before.write_text(
            json.dumps({"agent:main:main": {"sessionId": "main"}}),
            encoding="utf-8",
        )
        self.transcript = self.sessions / f"{self.session_id}.jsonl"
        self.trajectory = self.sessions / f"{self.session_id}.trajectory.jsonl"
        self.pointer = self.sessions / f"{self.session_id}.trajectory-path.json"
        self.transcript.write_text("{}\n", encoding="utf-8")
        self.trajectory.write_text("{}\n", encoding="utf-8")
        self.pointer.write_text(
            json.dumps(
                {
                    "sessionId": self.session_id,
                    "runtimeFile": str(self.trajectory),
                }
            ),
            encoding="utf-8",
        )
        self.write_current()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_current(self, extra: dict[str, object] | None = None) -> None:
        payload: dict[str, object] = {
            "agent:main:main": {"sessionId": "main"},
            self.key: {
                "sessionId": self.session_id,
                "sessionFile": str(self.transcript),
            },
        }
        if extra:
            payload.update(extra)
        (self.sessions / "sessions.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def cleanup(self, mode: str = "apply") -> dict[str, object]:
        return MODULE.cleanup_security_session(
            mode=mode,
            state_root=self.state,
            before_index=self.before,
            session_key=self.key,
            evidence_root=self.evidence,
        )

    def test_apply_archives_and_removes_only_synthetic_artifacts(self) -> None:
        report = self.cleanup()
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["artifactCount"], 3)
        self.assertEqual(report["artifactsRemoved"], 3)
        self.assertFalse(self.transcript.exists())
        self.assertFalse(self.trajectory.exists())
        self.assertFalse(self.pointer.exists())
        archive = self.evidence / "failed-session-artifacts"
        self.assertEqual(len(list(archive.iterdir())), 3)

    def test_plan_archives_without_removing_artifacts(self) -> None:
        report = self.cleanup("plan")
        self.assertEqual(report["artifactsRemoved"], 0)
        self.assertTrue(self.transcript.exists())
        self.assertTrue(self.trajectory.exists())

    def test_no_new_session_is_idempotent(self) -> None:
        (self.sessions / "sessions.json").write_text(
            self.before.read_text(encoding="utf-8"), encoding="utf-8"
        )
        report = self.cleanup()
        self.assertFalse(report["sessionFound"])
        self.assertEqual(report["artifactCount"], 0)

    def test_rejects_unexpected_concurrent_session(self) -> None:
        self.write_current({"agent:main:explicit:other": {"sessionId": "other"}})
        with self.assertRaisesRegex(
            MODULE.SecuritySessionCleanupError, "unexpected sessions"
        ):
            self.cleanup()

    def test_rejects_non_security_session_key(self) -> None:
        with self.assertRaisesRegex(
            MODULE.SecuritySessionCleanupError, "outside the synthetic"
        ):
            MODULE.cleanup_security_session(
                mode="apply",
                state_root=self.state,
                before_index=self.before,
                session_key="agent:main:explicit:behavior-test",
                evidence_root=self.evidence,
            )

    def test_rejects_trajectory_escape(self) -> None:
        escaped = self.root / f"{self.session_id}.trajectory.jsonl"
        escaped.write_text("{}\n", encoding="utf-8")
        self.pointer.write_text(
            json.dumps({"runtimeFile": str(escaped)}), encoding="utf-8"
        )
        with self.assertRaisesRegex(
            MODULE.SecuritySessionCleanupError, "outside its root"
        ):
            self.cleanup()


if __name__ == "__main__":
    unittest.main()
