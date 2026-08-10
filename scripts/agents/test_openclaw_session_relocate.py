#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("openclaw-session-relocate.py")
SPEC = importlib.util.spec_from_file_location("openclaw_session_relocate", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class SessionRelocationTests(unittest.TestCase):
    def _fixture(self, root: Path, state_name: str) -> tuple[Path, Path]:
        state = root / state_name
        workspace = state / "workspace"
        sessions = state / "agents" / "main" / "sessions"
        prompt = workspace / "skills" / "demo.md"
        transcript = sessions / "session-one.jsonl"
        trajectory = sessions / "session-one.trajectory.jsonl"
        trajectory_path = sessions / "session-one.trajectory-path.json"
        prompt.parent.mkdir(parents=True)
        sessions.mkdir(parents=True)
        prompt.write_text("prompt\n", encoding="utf-8")
        transcript.write_text('{"type":"session","id":"one"}\n', encoding="utf-8")
        trajectory.write_text('{"event":"start"}\n', encoding="utf-8")
        trajectory_path.write_text('{"path":[]}\n', encoding="utf-8")
        (sessions / "sessions.json").write_text(
            json.dumps(
                {
                    "agent:main:main": {
                        "sessionId": "one",
                        "sessionFile": str(transcript),
                        "workspaceDir": str(workspace),
                        "spawnedWorkspaceDir": str(workspace),
                        "spawnedCwd": str(workspace),
                        "skillSnapshot": {"path": str(prompt)},
                    }
                }
            ),
            encoding="utf-8",
        )
        return state, workspace

    def _copy_fixture(self, source: Path, target: Path) -> None:
        import shutil

        shutil.copytree(source, target)

    def _split_target_workspace(self, root: Path, target: Path) -> Path:
        target_workspace = root / "target-workspace"
        (target / "workspace").rename(target_workspace)
        return target_workspace

    def test_rewrite_and_verify_preserve_artifact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, source_workspace = self._fixture(root, "source")
            target = root / "target"
            self._copy_fixture(source, target)
            target_workspace = self._split_target_workspace(root, target)

            before = (
                target / "agents" / "main" / "sessions" / "session-one.jsonl"
            ).read_bytes()
            result = MODULE.rewrite_session_stores(
                target,
                source,
                source_workspace,
                target_workspace,
                ["main"],
            )
            self.assertEqual(result["changedFiles"], 1)
            self.assertEqual(result["rewrittenReferences"], 5)
            after = (
                target / "agents" / "main" / "sessions" / "session-one.jsonl"
            ).read_bytes()
            self.assertEqual(before, after)

            verified = MODULE.verify_relocation(
                source,
                source_workspace,
                target,
                target_workspace,
                ["main"],
            )
            self.assertEqual(verified["status"], "ok")
            self.assertEqual(verified["entries"], 1)

            second = MODULE.rewrite_session_stores(
                target,
                source,
                source_workspace,
                target_workspace,
                ["main"],
            )
            self.assertEqual(second["changedFiles"], 0)
            self.assertEqual(second["rewrittenReferences"], 0)

    def test_rejects_unapproved_state_root_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, source_workspace = self._fixture(root, "source")
            target = root / "target"
            self._copy_fixture(source, target)
            target_workspace = self._split_target_workspace(root, target)
            index = target / "agents" / "main" / "sessions" / "sessions.json"
            payload = json.loads(index.read_text(encoding="utf-8"))
            payload["agent:main:main"]["message"] = str(source_workspace / "secret")
            index.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(MODULE.SessionRelocationError):
                MODULE.rewrite_session_stores(
                    target,
                    source,
                    source_workspace,
                    target_workspace,
                    ["main"],
                )

    def test_rejects_missing_or_external_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, source_workspace = self._fixture(root, "source")
            index = source / "agents" / "main" / "sessions" / "sessions.json"
            payload = json.loads(index.read_text(encoding="utf-8"))
            payload["agent:main:main"]["sessionFile"] = str(root / "outside.jsonl")
            index.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(MODULE.SessionRelocationError):
                MODULE.inspect_session_stores(source, source_workspace, ["main"])

    def test_verify_detects_changed_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, source_workspace = self._fixture(root, "source")
            target = root / "target"
            self._copy_fixture(source, target)
            target_workspace = self._split_target_workspace(root, target)
            MODULE.rewrite_session_stores(
                target,
                source,
                source_workspace,
                target_workspace,
                ["main"],
            )
            transcript = target / "agents" / "main" / "sessions" / "session-one.jsonl"
            transcript.write_text("changed\n", encoding="utf-8")

            with self.assertRaises(MODULE.SessionRelocationError):
                MODULE.verify_relocation(
                    source,
                    source_workspace,
                    target,
                    target_workspace,
                    ["main"],
                )


if __name__ == "__main__":
    unittest.main()
