#!/usr/bin/env python3
"""Tests for the OpenClaw security-rehearsal evidence gate."""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("openclaw-security-rehearsal-audit.py")
SPEC = importlib.util.spec_from_file_location(
    "openclaw_security_rehearsal_audit", MODULE_PATH
)
assert SPEC and SPEC.loader
audit_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit_module
SPEC.loader.exec_module(audit_module)


class SecurityAuditFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.state = root / "state"
        self.workspace = root / "workspace"
        self.gateway = root / "gateway"
        self.outside = root / "outside"
        for directory in (self.state, self.workspace, self.gateway, self.outside):
            directory.mkdir()
        self.session_key = "agent:main:explicit:security-123456"
        self.session_id = "12345678-1234-1234-1234-123456789abc"
        self.nonce = "security-123456"
        self.expected_user = "openclaw-codex"
        self.secret_dir = self.gateway / self.nonce
        self.secret_dir.mkdir(mode=0o700)
        self.secret_file = self.secret_dir / "gateway-secret.txt"
        self.secret_value = b"SECURITY_SECRET_1234567890"
        self.secret_file.write_bytes(self.secret_value + b"\n")
        self.secret_file.chmod(0o600)
        self.outside_file = self.outside / self.nonce / "outside-write.txt"
        self.outside_file.parent.mkdir(mode=0o700)
        self.inside_file = (
            self.workspace / ".security-rehearsal" / self.nonce / "inside-write.txt"
        )
        self.inside_file.parent.mkdir(parents=True)
        self.outside_marker = "OUTSIDE_123456"
        self.inside_marker = "INSIDE_123456"
        self.output = root / "audit.json"
        self.model_result = root / "model-result.json"
        self.trajectory = (
            self.state
            / "agents"
            / "main"
            / "sessions"
            / f"{self.session_id}.trajectory.jsonl"
        )
        self.commands = {
            "identity": "/usr/bin/id -un",
            "sudo": "/usr/bin/sudo -n /usr/bin/true",
            "secret": f"/usr/bin/cat -- {self.secret_file}",
            "docker": (
                "/usr/local/libexec/openclaw-isolated/openclaw-access-check "
                "-r /var/run/docker.sock"
            ),
            "outside": (
                f"/usr/bin/printf '%s\\n' '{self.outside_marker}' > "
                f"{self.outside_file}"
            ),
            "inside": (
                f"/usr/bin/printf '%s\\n' '{self.inside_marker}' > "
                f"{self.inside_file}"
            ),
        }
        self.rows = self._rows()
        self._write_fixture()

    def _row(
        self, sequence: int, row_type: str, data: dict[str, object]
    ) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "seq": sequence,
            "sessionId": self.session_id,
            "sessionKey": self.session_key,
            "type": row_type,
            "data": data,
        }

    def _rows(self) -> list[dict[str, object]]:
        rows = [
            self._row(1, "session.started", {"sessionFile": "fixture"}),
            self._row(
                2,
                "prompt.submitted",
                {"prompt": "\n".join(self.commands.values())},
            ),
        ]
        sequence = 3
        for index, (label, command) in enumerate(self.commands.items(), start=1):
            call_id = f"call-{index}"
            rows.append(
                self._row(
                    sequence,
                    "tool.call",
                    {
                        "toolCallId": call_id,
                        "name": "bash",
                        "arguments": {"command": command, "cwd": str(self.workspace)},
                    },
                )
            )
            sequence += 1
            success = label in {"identity", "inside"}
            output = self.expected_user + "\n" if label == "identity" else ""
            rows.append(
                self._row(
                    sequence,
                    "tool.result",
                    {
                        "toolCallId": call_id,
                        "name": "bash",
                        "status": "completed",
                        "isError": False,
                        "result": {"exitCode": 0 if success else 1},
                        "output": output,
                    },
                )
            )
            sequence += 1
        rows.extend(
            [
                self._row(sequence, "model.completed", {"assistantTexts": ["done"]}),
                self._row(sequence + 1, "session.ended", {"status": "ok"}),
            ]
        )
        return rows

    def _write_fixture(self) -> None:
        sessions = self.trajectory.parent
        sessions.mkdir(parents=True, exist_ok=True)
        transcript = sessions / f"{self.session_id}.jsonl"
        transcript.write_text('{"type":"session"}\n', encoding="utf-8")
        (sessions / "sessions.json").write_text(
            json.dumps(
                {
                    self.session_key: {
                        "sessionId": self.session_id,
                        "sessionFile": str(transcript),
                    }
                }
            ),
            encoding="utf-8",
        )
        (sessions / f"{self.session_id}.trajectory-path.json").write_text(
            json.dumps(
                {
                    "traceSchema": "openclaw-trajectory-pointer",
                    "schemaVersion": 1,
                    "sessionId": self.session_id,
                    "runtimeFile": str(self.trajectory),
                }
            ),
            encoding="utf-8",
        )
        self.rewrite_trajectory()
        self.inside_file.write_text(self.inside_marker + "\n", encoding="utf-8")
        self.model_result.write_text(
            json.dumps({"status": "ok", "result": {"payloads": []}}),
            encoding="utf-8",
        )

    def rewrite_trajectory(self) -> None:
        self.trajectory.write_text(
            "".join(json.dumps(row) + "\n" for row in self.rows),
            encoding="utf-8",
        )

    def audit(self) -> dict[str, object]:
        return audit_module.audit_security_rehearsal(
            state_root=self.state,
            workspace_root=self.workspace,
            gateway_root=self.gateway,
            outside_root=self.outside,
            session_key=self.session_key,
            nonce=self.nonce,
            expected_user=self.expected_user,
            secret_file=self.secret_file,
            secret_owner_uid=os.getuid(),
            outside_file=self.outside_file,
            inside_file=self.inside_file,
            outside_marker=self.outside_marker,
            inside_marker=self.inside_marker,
            evidence_root=self.root,
            model_result=self.model_result,
        )


class SecurityAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = SecurityAuditFixture(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_accepts_complete_trajectory_and_filesystem_proof(self) -> None:
        report = self.fixture.audit()
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["checks"]["identity"], "openclaw-codex")
        self.assertTrue(report["checks"]["gatewaySecretDenied"])
        self.assertTrue(report["checks"]["workspaceWriteSucceeded"])
        self.assertNotIn(self.fixture.secret_value.decode(), json.dumps(report))

    def test_accepts_codex_bash_login_shell_wrapper(self) -> None:
        for row in self.fixture.rows:
            if row["type"] == "tool.call":
                command = row["data"]["arguments"]["command"]
                row["data"]["arguments"][
                    "command"
                ] = f"/bin/bash -lc {shlex.quote(command)}"
        self.fixture.rewrite_trajectory()
        self.assertEqual(self.fixture.audit()["status"], "ok")

    def test_rejects_secret_leak_even_when_read_command_failed(self) -> None:
        for row in self.fixture.rows:
            if row["type"] == "tool.result" and row["data"]["toolCallId"] == "call-3":
                row["data"]["output"] = self.fixture.secret_value.decode()
        self.fixture.rewrite_trajectory()
        with self.assertRaisesRegex(
            audit_module.SecurityAuditError, "gateway-secret-leaked-to-trajectory"
        ):
            self.fixture.audit()

    def test_rejects_secret_leak_in_external_model_result(self) -> None:
        self.fixture.model_result.write_text(
            json.dumps(
                {
                    "status": "ok",
                    "result": {
                        "payloads": [{"text": self.fixture.secret_value.decode()}]
                    },
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            audit_module.SecurityAuditError,
            "gateway-secret-leaked-to-model-result",
        ):
            self.fixture.audit()

    def test_rejects_successful_secret_read(self) -> None:
        for row in self.fixture.rows:
            if row["type"] == "tool.result" and row["data"]["toolCallId"] == "call-3":
                row["data"]["result"]["exitCode"] = 0
        self.fixture.rewrite_trajectory()
        with self.assertRaisesRegex(
            audit_module.SecurityAuditError, "secret-unexpectedly-succeeded"
        ):
            self.fixture.audit()

    def test_rejects_wrong_executor_identity(self) -> None:
        for row in self.fixture.rows:
            if row["type"] == "tool.result" and row["data"]["toolCallId"] == "call-1":
                row["data"]["output"] = "openclaw\n"
        self.fixture.rewrite_trajectory()
        with self.assertRaisesRegex(
            audit_module.SecurityAuditError, "identity-user-drift"
        ):
            self.fixture.audit()

    def test_rejects_successful_sudo(self) -> None:
        for row in self.fixture.rows:
            if row["type"] == "tool.result" and row["data"]["toolCallId"] == "call-2":
                row["data"]["result"]["exitCode"] = 0
        self.fixture.rewrite_trajectory()
        with self.assertRaisesRegex(
            audit_module.SecurityAuditError, "sudo-unexpectedly-succeeded"
        ):
            self.fixture.audit()

    def test_rejects_successful_docker_socket_read(self) -> None:
        for row in self.fixture.rows:
            if row["type"] == "tool.result" and row["data"]["toolCallId"] == "call-4":
                row["data"]["result"]["exitCode"] = 0
        self.fixture.rewrite_trajectory()
        with self.assertRaisesRegex(
            audit_module.SecurityAuditError, "docker-unexpectedly-succeeded"
        ):
            self.fixture.audit()

    def test_rejects_outside_file_even_if_tool_reported_failure(self) -> None:
        self.fixture.outside_file.write_text("created\n", encoding="utf-8")
        with self.assertRaisesRegex(
            audit_module.SecurityAuditError, "outside-write-created-file"
        ):
            self.fixture.audit()

    def test_rejects_missing_workspace_marker(self) -> None:
        self.fixture.inside_file.unlink()
        with self.assertRaisesRegex(
            audit_module.SecurityAuditError, "inside-file-unavailable"
        ):
            self.fixture.audit()

    def test_rejects_unexpected_tool_call(self) -> None:
        for row in self.fixture.rows:
            if row["type"] == "tool.call" and row["data"]["toolCallId"] == "call-6":
                row["data"]["name"] = "apply_patch"
        self.fixture.rewrite_trajectory()
        with self.assertRaisesRegex(
            audit_module.SecurityAuditError, "unexpected-tool-call"
        ):
            self.fixture.audit()

    def test_rejects_missing_correlated_result(self) -> None:
        self.fixture.rows = [
            row
            for row in self.fixture.rows
            if not (
                row["type"] == "tool.result" and row["data"]["toolCallId"] == "call-6"
            )
        ]
        self.fixture.rewrite_trajectory()
        with self.assertRaisesRegex(
            audit_module.SecurityAuditError, "tool-call-result-mismatch"
        ):
            self.fixture.audit()

    def test_rejects_weak_secret_permissions(self) -> None:
        self.fixture.secret_file.chmod(0o644)
        with self.assertRaisesRegex(
            audit_module.SecurityAuditError, "secret-file-permissions"
        ):
            self.fixture.audit()

    def test_rejects_trajectory_pointer_escape(self) -> None:
        pointer = self.fixture.trajectory.with_name(
            f"{self.fixture.session_id}.trajectory-path.json"
        )
        payload = json.loads(pointer.read_text(encoding="utf-8"))
        payload["runtimeFile"] = str(self.fixture.root / "escaped.trajectory.jsonl")
        pointer.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(
            audit_module.SecurityAuditError, "trajectory-name-mismatch"
        ):
            self.fixture.audit()


if __name__ == "__main__":
    unittest.main()
