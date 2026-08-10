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
    def test_preserves_gateway_token_and_removes_unexpected_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            output = directory / "secrets.json"
            os.chmod(directory, 0o700)

            changed = MODULE.write_secret_payload(
                output,
                os.getuid(),
                os.getgid(),
            )
            self.assertTrue(changed)
            first = json.loads(output.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(first["gateway"]["token"]), 32)
            self.assertEqual(output.stat().st_mode & 0o777, 0o400)

            unchanged = MODULE.write_secret_payload(
                output,
                os.getuid(),
                os.getgid(),
            )
            self.assertFalse(unchanged)

            os.chmod(output, 0o600)
            output.write_text(
                json.dumps({**first, "unexpected": "remove-me"}),
                encoding="utf-8",
            )
            changed_again = MODULE.write_secret_payload(
                output,
                os.getuid(),
                os.getgid(),
            )
            self.assertTrue(changed_again)
            second = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(first["gateway"]["token"], second["gateway"]["token"])
            self.assertNotIn("unexpected", second)
            self.assertEqual(output.stat().st_mode & 0o777, 0o400)

    def test_rejects_unexpected_output_parent_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            output = Path(directory_name) / "secrets.json"
            with self.assertRaises(MODULE.SecretBootstrapError):
                MODULE.write_secret_payload(
                    output,
                    os.getuid(),
                    os.getgid(),
                    os.getuid() + 1,
                )


if __name__ == "__main__":
    unittest.main()
