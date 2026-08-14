#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts" / "agents" / "hermes-discord-runtime-audit.py"
SPEC = importlib.util.spec_from_file_location("hermes_discord_runtime_audit", SOURCE)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class HermesDiscordRuntimeAuditTests(unittest.TestCase):
    def make_proc(self, root: Path, *, state: str = "01", port: str = "01BB") -> int:
        pid = 4242
        process = root / str(pid)
        (process / "fd").mkdir(parents=True)
        (process / "net").mkdir()
        os.symlink("socket:[98765]", process / "fd" / "7")
        (process / "net" / "tcp").write_text(
            "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
            f"   0: 0100007F:C001 0100007F:{port} {state} 00000000:00000000 00:00000000 00000000 "
            f"{os.geteuid()} 0 98765 1 0000000000000000\n",
            encoding="ascii",
        )
        (process / "net" / "tcp6").write_text("header\n", encoding="ascii")
        return pid

    def test_accepts_owned_established_https_socket(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pid = self.make_proc(root)
            self.assertTrue(AUDIT.has_established_tls(pid, root))

    def test_rejects_non_https_socket(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pid = self.make_proc(root, port="1F90")
            self.assertFalse(AUDIT.has_established_tls(pid, root))

    def test_rejects_non_established_socket(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pid = self.make_proc(root, state="02")
            self.assertFalse(AUDIT.has_established_tls(pid, root))

    def test_rejects_process_owned_by_another_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pid = self.make_proc(root)
            with mock.patch.object(AUDIT.os, "geteuid", return_value=os.geteuid() + 1):
                with self.assertRaises(PermissionError):
                    AUDIT.socket_inodes(pid, root)

    def test_import_gate_uses_exact_discord_runtime_modules(self) -> None:
        with mock.patch.object(AUDIT.importlib, "import_module") as import_module:
            AUDIT.require_imports()
        self.assertEqual(
            [call.args[0] for call in import_module.call_args_list],
            ["discord", "aiohttp", "brotlicffi"],
        )

    def test_allows_absent_or_empty_pairing_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            AUDIT.require_no_discord_pairing_grants(home)
            pairing = home / "platforms/pairing"
            pairing.mkdir(parents=True)
            (pairing / "discord-approved.json").write_text("{}\n", encoding="utf-8")
            AUDIT.require_no_discord_pairing_grants(home)

    def test_rejects_discord_pairing_grant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            pairing = home / "pairing"
            pairing.mkdir()
            (pairing / "discord-approved.json").write_text(
                json.dumps({"unauthorized-user": {"user_name": "bad"}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(PermissionError, "not allowed"):
                AUDIT.require_no_discord_pairing_grants(home)


if __name__ == "__main__":
    unittest.main()
