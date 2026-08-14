#!/usr/bin/env python3
"""Regression tests for the fixed Docker auto-update trigger."""

from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/docker/agent-docker-update-trigger.py"
SPEC = importlib.util.spec_from_file_location("agent_docker_update_trigger", SOURCE)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BinaryInput:
    def __init__(self, value: bytes) -> None:
        self.buffer = io.BytesIO(value)


def managed_state(service_state: str = "inactive") -> dict[str, object]:
    return {
        "managed": True,
        "serviceState": service_state,
        "timerState": "active",
        "lastResult": "success",
        "exitCode": 0,
    }


class TriggerTests(unittest.TestCase):
    def test_accepts_only_exact_status_or_run_schema(self) -> None:
        self.assertEqual(
            MODULE._read_request(BinaryInput(b'{"schemaVersion":1,"action":"status"}')),
            "status",
        )
        for value in (
            b'{"schemaVersion":1,"action":"shell"}',
            b'{"schemaVersion":1,"action":"run","service":"plex"}',
            b'{"schemaVersion":2,"action":"run"}',
            b'not-json',
        ):
            with self.subTest(value=value), self.assertRaisesRegex(
                MODULE.RequestError, "invalid-request"
            ):
                MODULE._read_request(BinaryInput(value))

    def test_status_is_bounded_and_does_not_start_service(self) -> None:
        with mock.patch.object(MODULE, "_unit_state", return_value=managed_state()):
            value = json.loads(MODULE._status("docker-vm"))
        self.assertEqual(value["outcome"], "ready")
        self.assertEqual(value["host"], "docker-vm")

    def test_run_starts_only_fixed_managed_unit(self) -> None:
        completed = mock.Mock(returncode=0)
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            MODULE, "_unit_state", return_value=managed_state()
        ), mock.patch.object(MODULE.subprocess, "run", return_value=completed) as run:
            value = json.loads(MODULE._run("docker-vm", Path(temporary), 3600))
        self.assertEqual(value["outcome"], "accepted")
        self.assertEqual(
            run.call_args.args[0],
            ["/usr/bin/systemctl", "start", "--no-block", "docker-auto-update.service"],
        )

    def test_cooldown_blocks_repeat_without_starting_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary)
            (state_dir / "last-trigger").write_text("1000\n", encoding="ascii")
            with mock.patch.object(
                MODULE, "_unit_state", return_value=managed_state()
            ), mock.patch.object(MODULE.time, "time", return_value=1100), mock.patch.object(
                MODULE.subprocess, "run"
            ) as run:
                value = json.loads(MODULE._run("docker-vm", state_dir, 3600))
        self.assertEqual(value["outcome"], "cooldown")
        self.assertEqual(value["retryAfterSeconds"], 3500)
        run.assert_not_called()

    def test_unmanaged_host_cannot_start_service(self) -> None:
        state = managed_state()
        state["managed"] = False
        state["timerState"] = "inactive"
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            MODULE, "_unit_state", return_value=state
        ), mock.patch.object(MODULE.subprocess, "run") as run:
            value = json.loads(MODULE._run("jn-t14s-lin", Path(temporary), 3600))
        self.assertEqual(value["outcome"], "unavailable")
        run.assert_not_called()

    def test_source_has_no_docker_or_shell_execution_path(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("/var/run/docker.sock", source)
        self.assertNotIn("docker compose", source)
        self.assertNotIn("shell=True", source)
        self.assertNotIn("SSH_ORIGINAL_COMMAND", source)


if __name__ == "__main__":
    unittest.main()
