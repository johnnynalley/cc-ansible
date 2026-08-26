#!/usr/bin/env python3
"""Tests for compatibility-safe Hermes memory dependency updates."""

from __future__ import annotations

import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest import mock


PATH = Path(__file__).with_name("hermes-memory-dependencies-update.py")
SPEC = importlib.util.spec_from_file_location("hermes_memory_dependencies_update", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HermesMemoryDependenciesUpdateTests(unittest.TestCase):
    def test_active_requirements_exclude_optional_extras_and_wrong_platforms(self) -> None:
        requirements = [
            "openai==2.24.0",
            'mem0ai==2.0.10; extra == "mem0"',
            'tzdata==2025.3; sys_platform == "win32"',
            "urllib3<3,>=2.7.0",
        ]
        with mock.patch.object(
            MODULE.importlib.metadata, "requires", return_value=requirements
        ):
            active = MODULE.active_base_requirements("hermes-agent")

        self.assertIn("openai==2.24.0", active)
        self.assertIn("urllib3<3,>=2.7.0", active)
        self.assertFalse(any("mem0ai" in item for item in active))
        self.assertFalse(any("tzdata" in item for item in active))

    def test_main_uses_argument_array_and_current_base_requirements(self) -> None:
        completed = subprocess.CompletedProcess([], 0)
        argv = [
            "resolver",
            "--uv",
            "/uv",
            "--python",
            "/venv/bin/python",
            "--package",
            "mem0ai[nlp]",
            "--package",
            "fastembed",
            "--dry-run",
        ]
        with (
            mock.patch.object(MODULE, "parse_args") as parse,
            mock.patch.object(
                MODULE,
                "active_base_requirements",
                return_value=["openai==2.24.0", "rich==14.3.3"],
            ),
            mock.patch.object(MODULE.subprocess, "run", return_value=completed) as run,
        ):
            parse.return_value = MODULE.argparse.Namespace(
                uv="/uv",
                python="/venv/bin/python",
                distribution="hermes-agent",
                package=["mem0ai[nlp]", "fastembed"],
                dry_run=True,
            )
            self.assertEqual(MODULE.main(), 0)

        command = run.call_args.args[0]
        self.assertEqual(command[0], "/uv")
        self.assertIn("--dry-run", command)
        self.assertIn("mem0ai[nlp]", command)
        self.assertIn("openai==2.24.0", command)
        self.assertNotIn(" ".join(argv), command)
        run.assert_called_once_with(command, check=False)


if __name__ == "__main__":
    unittest.main()
