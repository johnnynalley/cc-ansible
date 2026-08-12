#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

ACCESS_CHECK = Path(__file__).with_name("openclaw-access-check")


class OpenClawAccessCheckTests(unittest.TestCase):
    def run_check(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(ACCESS_CHECK), *args],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_accepts_only_supported_predicates(self) -> None:
        for args in ((), ("-e", "/tmp"), ("!", "-e", "/tmp"), ("-r",)):
            with self.subTest(args=args):
                result = self.run_check(*args)
                self.assertEqual(result.returncode, 64)
                self.assertIn("usage:", result.stderr)

    def test_reports_effective_read_write_and_traverse_access(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_path = root / "payload"
            file_path.write_text("test\n", encoding="utf-8")
            file_path.chmod(0o600)

            self.assertEqual(self.run_check("-r", str(file_path)).returncode, 0)
            self.assertEqual(self.run_check("-w", str(file_path)).returncode, 0)
            self.assertEqual(self.run_check("-x", str(root)).returncode, 0)

            file_path.chmod(0)
            self.assertEqual(self.run_check("!", "-r", str(file_path)).returncode, 0)
            self.assertEqual(self.run_check("!", "-w", str(file_path)).returncode, 0)


if __name__ == "__main__":
    unittest.main()
