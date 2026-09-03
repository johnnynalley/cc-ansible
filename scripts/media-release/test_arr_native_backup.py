#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name("arr_native_backup.py")
SPEC = importlib.util.spec_from_file_location("arr_native_backup", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ArrNativeBackupTests(unittest.TestCase):
    def test_newest_backup_ignores_old_and_non_zip_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "old.zip"
            old.write_bytes(b"old")
            cutoff = old.stat().st_mtime + 1
            new = root / "new.zip"
            new.write_bytes(b"new")
            non_zip = root / "new.txt"
            non_zip.write_text("ignored", encoding="utf-8")
            old_mtime = cutoff - 2
            os.utime(old, (old_mtime, old_mtime))
            new_mtime = cutoff + 2
            os.utime(new, (new_mtime, new_mtime))

            self.assertEqual(MODULE.newest_backup(root, cutoff), new)

    def test_newest_backup_returns_none_without_new_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(MODULE.newest_backup(Path(directory), 0))

    def test_prowlarr_uses_v1_command_api(self) -> None:
        self.assertEqual(MODULE.APPS["prowlarr"]["api_prefix"], "/api/v1")

    @mock.patch.object(MODULE, "newest_backup")
    @mock.patch.object(MODULE.time, "sleep")
    @mock.patch.object(MODULE, "request_json")
    @mock.patch.object(MODULE, "read_api_key")
    def test_run_backup_uses_per_app_api_prefix(
        self,
        read_api_key: mock.Mock,
        request_json: mock.Mock,
        sleep: mock.Mock,
        newest_backup: mock.Mock,
    ) -> None:
        read_api_key.return_value = "private"
        request_json.side_effect = [{"id": 7}, {"status": "completed"}]
        backup = mock.Mock()
        backup.__str__ = mock.Mock(return_value="/backup/prowlarr.zip")
        backup.stat.return_value.st_size = 123
        newest_backup.return_value = backup

        result = MODULE.run_backup("prowlarr", 10, 0.1)

        self.assertEqual(result["command_id"], 7)
        self.assertEqual(request_json.call_args_list[0].args[3], "/api/v1/command")
        self.assertEqual(request_json.call_args_list[1].args[3], "/api/v1/command/7")
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
