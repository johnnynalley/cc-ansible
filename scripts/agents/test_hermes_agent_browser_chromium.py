#!/usr/bin/env python3
"""Regression tests for the managed Astra Chromium selector."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "agents" / "hermes-agent-browser-chromium.py"
SPEC = importlib.util.spec_from_file_location("browser_selector", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HermesAgentBrowserChromiumTests(unittest.TestCase):
    def create_browser(self, root: Path, version: str, mode: int = 0o755) -> Path:
        directory = root / f"chrome-{version}"
        directory.mkdir()
        browser = directory / "chrome"
        browser.write_text("browser", encoding="utf-8")
        browser.chmod(mode)
        return browser

    def test_selects_newest_owned_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.create_browser(root, "151.0.1.9")
            expected = self.create_browser(root, "152.0.7977.54")
            self.assertEqual(MODULE.select_browser(root, os.getuid()), expected)

    def test_rejects_symlink_and_non_executable_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            trusted = self.create_browser(root, "150.0.1", mode=0o755)
            self.create_browser(root, "151.0.1", mode=0o644)
            linked_dir = root / "chrome-999.0.0"
            linked_dir.symlink_to(trusted.parent, target_is_directory=True)
            self.assertEqual(MODULE.select_browser(root, os.getuid()), trusted)

    def test_rejects_wrong_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.create_browser(root, "152.0.1")
            with self.assertRaises(FileNotFoundError):
                MODULE.select_browser(root, os.getuid() + 1)

    def test_production_contract_is_fixed_and_execs_selected_binary(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn(
            '/var/lib/hermes/astra/.agent-browser/browsers', source
        )
        self.assertIn('EXPECTED_OWNER = "hermes-astra"', source)
        self.assertIn("os.execv(browser", source)


if __name__ == "__main__":
    unittest.main()
