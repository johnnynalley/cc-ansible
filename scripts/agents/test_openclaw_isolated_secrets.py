#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("openclaw-isolated-secrets.py")
SPEC = importlib.util.spec_from_file_location("openclaw_isolated_secrets", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


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


if __name__ == "__main__":
    unittest.main()
