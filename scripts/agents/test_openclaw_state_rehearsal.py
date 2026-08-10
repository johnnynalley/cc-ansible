#!/usr/bin/env python3

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

PLAYBOOK_PATH = (
    Path(__file__).resolve().parents[2]
    / "playbooks"
    / "agents"
    / "openclaw-state-rehearsal.yml"
)


class StateRehearsalPlaybookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        payload = yaml.safe_load(PLAYBOOK_PATH.read_text(encoding="utf-8"))
        cls.tasks = payload[0]["tasks"]

    def _task(self, name: str) -> dict:
        return next(task for task in self.tasks if task.get("name") == name)

    def test_immutable_capture_options_belong_only_to_verify(self) -> None:
        rewrite = self._task("Rewrite copied OpenClaw session paths")
        verify = self._task("Verify copied OpenClaw session relocation")
        rewrite_argv = rewrite["ansible.builtin.command"]["argv"]
        verify_argv = verify["ansible.builtin.command"]["argv"]

        self.assertIn("'rewrite'", rewrite_argv)
        self.assertNotIn("--source-manifest", rewrite_argv)
        self.assertNotIn("--source-index-root", rewrite_argv)
        self.assertIn("'verify'", verify_argv)
        self.assertIn("--source-manifest", verify_argv)
        self.assertIn("--source-index-root", verify_argv)

    def test_source_indexes_are_preserved_before_rewrite(self) -> None:
        names = [task.get("name") for task in self.tasks]
        preserve_index = names.index(
            "Preserve copied OpenClaw indexes before path transformation"
        )
        rewrite = names.index("Rewrite copied OpenClaw session paths")
        verify = names.index("Verify copied OpenClaw session relocation")
        self.assertLess(preserve_index, rewrite)
        self.assertLess(rewrite, verify)


if __name__ == "__main__":
    unittest.main()
