#!/usr/bin/env python3
"""Regressions for imported vdirsyncer collection-state conversion."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("hermes-vdirsyncer-state-migrate.py")
SPEC = importlib.util.spec_from_file_location("hermes_vdirsyncer_state_migrate", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class VdirsyncerStateMigrationTests(unittest.TestCase):
    def fixture(self, root: Path) -> Path:
        path = root / "personal.collections"
        path.write_text(
            json.dumps(
                {
                    "cache_key": "retained",
                    "collections": [
                        [
                            "personal",
                            [
                                {
                                    "collection": "personal",
                                    "path": "/home/johnny/.local/share/vdirsyncer/calendars/personal",
                                },
                                {
                                    "collection": "personal",
                                    "url": "https://calendar.invalid/personal/",
                                },
                            ],
                        ]
                    ],
                }
            ),
            encoding="utf-8",
        )
        path.chmod(0o600)
        return path

    def test_conversion_changes_only_approved_filesystem_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.fixture(Path(directory))
            value, _ = MODULE.load_state(path)
            replacements = MODULE.convert(
                value,
                Path("/home/johnny/.local/share/vdirsyncer/calendars"),
                Path("/var/lib/hermes/astra/.local/share/vdirsyncer/calendars"),
            )
            self.assertEqual(replacements, 1)
            self.assertEqual(
                value["collections"][0][1][0]["path"],
                "/var/lib/hermes/astra/.local/share/vdirsyncer/calendars/personal",
            )
            self.assertEqual(
                value["collections"][0][1][1]["url"],
                "https://calendar.invalid/personal/",
            )

    def test_apply_is_atomic_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.fixture(Path(directory))
            value, metadata = MODULE.load_state(path)
            self.assertEqual(
                MODULE.convert(
                    value,
                    Path("/home/johnny/.local/share/vdirsyncer/calendars"),
                    Path("/var/lib/hermes/astra/.local/share/vdirsyncer/calendars"),
                ),
                1,
            )
            MODULE.atomic_write(path, value, metadata)
            converted, _ = MODULE.load_state(path)
            self.assertEqual(
                MODULE.convert(
                    converted,
                    Path("/home/johnny/.local/share/vdirsyncer/calendars"),
                    Path("/var/lib/hermes/astra/.local/share/vdirsyncer/calendars"),
                ),
                0,
            )
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_unexpected_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.fixture(Path(directory))
            value, _ = MODULE.load_state(path)
            value["collections"][0][1][0]["path"] = "/tmp/untrusted/personal"
            with self.assertRaisesRegex(
                MODULE.MigrationError, "outside-approved-roots"
            ):
                MODULE.convert(
                    value,
                    Path("/home/johnny/.local/share/vdirsyncer/calendars"),
                    Path("/var/lib/hermes/astra/.local/share/vdirsyncer/calendars"),
                )


if __name__ == "__main__":
    unittest.main()
