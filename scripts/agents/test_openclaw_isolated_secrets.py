#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

import yaml

MODULE_PATH = Path(__file__).with_name("openclaw-isolated-secrets.py")
SPEC = importlib.util.spec_from_file_location("openclaw_isolated_secrets", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)
REPOSITORY_ROOT = Path(__file__).parents[2]
PLAYBOOK_PATHS = (
    REPOSITORY_ROOT / "playbooks/agents/openclaw-doctor-rehearsal.yml",
    REPOSITORY_ROOT / "playbooks/agents/openclaw-isolated-gateway.yml",
)


def iter_tasks(tasks: list[object]):
    for candidate in tasks:
        if not isinstance(candidate, dict):
            continue
        yield candidate
        for section in ("block", "rescue", "always"):
            nested = candidate.get(section)
            if isinstance(nested, list):
                yield from iter_tasks(nested)


class SecretPayloadTests(unittest.TestCase):
    def _paths(self, root: Path) -> tuple[Path, Path]:
        gateway_dir = root / "gateway"
        codex_dir = root / "codex"
        gateway_dir.mkdir(mode=0o700)
        codex_dir.mkdir(mode=0o700)
        return gateway_dir / "secrets.json", codex_dir / "app-server.token"

    def _bootstrap(self, gateway: Path, codex: Path) -> dict[str, bool]:
        return MODULE.bootstrap_secrets(
            gateway,
            os.getuid(),
            os.getgid(),
            codex,
            os.getuid(),
            os.getgid(),
        )

    def test_creates_matching_separate_tokens_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            gateway, codex = self._paths(Path(directory_name))

            changes = self._bootstrap(gateway, codex)
            self.assertEqual(changes, {"gateway": True, "codex": True})
            payload = json.loads(gateway.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(payload["gateway"]["token"]), 32)
            self.assertEqual(
                payload["codex"]["appServerToken"],
                codex.read_text(encoding="utf-8").strip(),
            )
            self.assertEqual(gateway.stat().st_mode & 0o777, 0o400)
            self.assertEqual(codex.stat().st_mode & 0o777, 0o400)
            self.assertEqual(
                self._bootstrap(gateway, codex),
                {"gateway": False, "codex": False},
            )

    def test_reconstructs_missing_executor_copy_without_rotating(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            gateway, codex = self._paths(Path(directory_name))
            self._bootstrap(gateway, codex)
            expected = codex.read_text(encoding="utf-8")
            codex.unlink()

            changes = self._bootstrap(gateway, codex)

            self.assertEqual(changes, {"gateway": False, "codex": True})
            self.assertEqual(codex.read_text(encoding="utf-8"), expected)

    def test_imports_existing_executor_copy_into_legacy_gateway_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            gateway, codex = self._paths(Path(directory_name))
            gateway_token = "g" * 48
            codex_token = "c" * 48
            gateway.write_text(
                json.dumps(
                    {
                        "gateway": {"token": gateway_token},
                        "unexpected": "remove-me",
                    }
                ),
                encoding="utf-8",
            )
            codex.write_text(f"{codex_token}\n", encoding="utf-8")

            changes = self._bootstrap(gateway, codex)

            self.assertEqual(changes, {"gateway": True, "codex": False})
            payload = json.loads(gateway.read_text(encoding="utf-8"))
            self.assertEqual(payload["gateway"]["token"], gateway_token)
            self.assertEqual(payload["codex"]["appServerToken"], codex_token)
            self.assertNotIn("unexpected", payload)

    def test_rejects_split_brain_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            gateway, codex = self._paths(Path(directory_name))
            gateway.write_text(
                json.dumps(
                    {
                        "gateway": {"token": "g" * 48},
                        "codex": {"appServerToken": "a" * 48},
                    }
                ),
                encoding="utf-8",
            )
            codex.write_text(f"{'b' * 48}\n", encoding="utf-8")

            with self.assertRaisesRegex(
                MODULE.SecretBootstrapError, "token copies disagree"
            ):
                self._bootstrap(gateway, codex)

    def test_rejects_unexpected_output_parent_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            gateway, codex = self._paths(Path(directory_name))
            with self.assertRaises(MODULE.SecretBootstrapError):
                MODULE.bootstrap_secrets(
                    gateway,
                    os.getuid(),
                    os.getgid(),
                    codex,
                    os.getuid(),
                    os.getgid(),
                    os.getuid() + 1,
                )

    def test_every_playbook_consumer_satisfies_required_cli_contract(self) -> None:
        required_options = {
            action.option_strings[0]
            for action in MODULE.build_parser()._actions
            if action.required and action.option_strings
        }
        consumers: list[tuple[Path, str, list[object]]] = []
        for playbook_path in PLAYBOOK_PATHS:
            plays = yaml.safe_load(playbook_path.read_text(encoding="utf-8"))
            for play in plays:
                for task in iter_tasks(play.get("tasks", [])):
                    command = task.get("ansible.builtin.command")
                    if not isinstance(command, dict):
                        continue
                    argv = command.get("argv")
                    if not isinstance(argv, list) or not argv:
                        continue
                    executable = str(argv[0])
                    if (
                        "openclaw-isolated-secrets.py" not in executable
                        and "secret_tool" not in executable
                    ):
                        continue
                    consumers.append(
                        (playbook_path, str(task.get("name", "unnamed")), argv)
                    )

        self.assertTrue(consumers)
        for playbook_path, task_name, argv in consumers:
            with self.subTest(playbook=playbook_path.name, task=task_name):
                self.assertTrue(
                    required_options.issubset({str(argument) for argument in argv})
                )

    def test_doctor_discards_standalone_codex_token_after_bootstrap(self) -> None:
        playbook = PLAYBOOK_PATHS[0].read_text(encoding="utf-8")
        self.assertIn("--codex-token-owner", playbook)
        self.assertIn("--codex-token-group", playbook)
        self.assertIn("Remove ephemeral OpenClaw Doctor Codex token copy", playbook)
        self.assertIn(
            "Require no standalone Codex token in OpenClaw Doctor generation",
            playbook,
        )


if __name__ == "__main__":
    unittest.main()
