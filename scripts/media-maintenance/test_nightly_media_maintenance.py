#!/usr/bin/env python3

from __future__ import annotations

import argparse
import importlib.util
from importlib.machinery import SourceFileLoader
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("nightly-media-maintenance")
SPEC = importlib.util.spec_from_loader(
    "nightly_media_maintenance",
    SourceFileLoader("nightly_media_maintenance", str(MODULE_PATH)),
)
assert SPEC and SPEC.loader
MAINTENANCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MAINTENANCE)


class RestoreTests(unittest.TestCase):
    def args(self, state_dir: str) -> argparse.Namespace:
        return argparse.Namespace(
            state_dir=state_dir,
            media_stack_command="media-stack",
            profilarr_close_command="profilarr-close",
        )

    def test_profilarr_only_restore_does_not_touch_media_stack(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            MAINTENANCE.save_state(Path(directory), {"version": 1, "mode": "profilarr"})
            with mock.patch.object(MAINTENANCE, "run_shell", return_value=0) as run_shell:
                result = MAINTENANCE.cmd_restore(self.args(directory))
        self.assertEqual(result, 0)
        run_shell.assert_called_once_with("profilarr-close")

    def test_balance_restore_starts_media_stack_then_closes_profilarr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            MAINTENANCE.save_state(Path(directory), {"version": 1, "mode": "balance"})
            with mock.patch.object(MAINTENANCE, "run_shell", return_value=0) as run_shell:
                result = MAINTENANCE.cmd_restore(self.args(directory))
        self.assertEqual(result, 0)
        self.assertEqual(
            run_shell.call_args_list,
            [mock.call("media-stack start"), mock.call("profilarr-close")],
        )


if __name__ == "__main__":
    unittest.main()
