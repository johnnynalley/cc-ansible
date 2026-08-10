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
PROVIDER_ENV_KEY = "OPENROUTER" + "_API_KEY"
FIRST_FIXTURE = "fixture-provider-value-one"
SECOND_FIXTURE = "fixture-provider-value-two"


class DotenvParsingTests(unittest.TestCase):
    def test_reads_only_the_exact_requested_key(self) -> None:
        text = f"OTHER=value\nexport {PROVIDER_ENV_KEY}='{FIRST_FIXTURE}'\n"
        self.assertEqual(
            MODULE.parse_dotenv_key(text, PROVIDER_ENV_KEY),
            FIRST_FIXTURE,
        )

    def test_rejects_duplicate_assignments(self) -> None:
        text = (
            f"{PROVIDER_ENV_KEY}={FIRST_FIXTURE}\n"
            f"{PROVIDER_ENV_KEY}={SECOND_FIXTURE}\n"
        )
        with self.assertRaises(MODULE.SecretBootstrapError):
            MODULE.parse_dotenv_key(text, PROVIDER_ENV_KEY)

    def test_rejects_unquoted_whitespace(self) -> None:
        with self.assertRaises(MODULE.SecretBootstrapError):
            MODULE.parse_dotenv_key(
                f"{PROVIDER_ENV_KEY}={FIRST_FIXTURE} trailing\n",
                PROVIDER_ENV_KEY,
            )


class SecretPayloadTests(unittest.TestCase):
    def test_preserves_gateway_token_and_changes_only_provider_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            output = directory / "secrets.json"
            os.chmod(directory, 0o700)

            changed = MODULE.write_secret_payload(
                output,
                FIRST_FIXTURE,
                os.getuid(),
                os.getgid(),
            )
            self.assertTrue(changed)
            first = json.loads(output.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(first["gateway"]["token"]), 32)
            self.assertEqual(
                first["providers"]["openrouter"]["apiKey"],
                FIRST_FIXTURE,
            )
            self.assertEqual(output.stat().st_mode & 0o777, 0o640)

            unchanged = MODULE.write_secret_payload(
                output,
                FIRST_FIXTURE,
                os.getuid(),
                os.getgid(),
            )
            self.assertFalse(unchanged)

            changed_again = MODULE.write_secret_payload(
                output,
                SECOND_FIXTURE,
                os.getuid(),
                os.getgid(),
            )
            self.assertTrue(changed_again)
            second = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(first["gateway"]["token"], second["gateway"]["token"])
            self.assertEqual(
                second["providers"]["openrouter"]["apiKey"],
                SECOND_FIXTURE,
            )

    def test_rejects_group_readable_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            source = Path(directory_name) / ".env"
            source.write_text(f"{PROVIDER_ENV_KEY}={FIRST_FIXTURE}\n", encoding="utf-8")
            os.chmod(source, 0o640)
            with self.assertRaises(MODULE.SecretBootstrapError):
                MODULE.read_protected_source(source, os.getuid())


if __name__ == "__main__":
    unittest.main()
