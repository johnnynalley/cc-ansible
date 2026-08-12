#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("openclaw-workspace-manifest-parity.py")
SPEC = importlib.util.spec_from_file_location(
    "openclaw_workspace_manifest_parity", MODULE_PATH
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _record(
    target: str,
    content: bytes,
    *,
    origin: str = "retained",
    owner_class: str = "executor-writable",
) -> dict:
    return {
        "sourceRelative": target,
        "targetRelative": target,
        "origin": origin,
        "ownerClass": owner_class,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _manifest(records: list[dict]) -> dict:
    origins: dict[str, int] = {}
    owners: dict[str, int] = {}
    for row in records:
        origins[row["origin"]] = origins.get(row["origin"], 0) + 1
        owners[row["ownerClass"]] = owners.get(row["ownerClass"], 0) + 1
    return {
        "schemaVersion": 1,
        "status": "ok",
        "archiveContract": "preserve source",
        "summary": {
            "sourceObjects": len(records),
            "targetObjects": len(records),
            "files": len(records),
            "bytes": sum(row["bytes"] for row in records),
            "filesByOrigin": origins,
            "filesByOwnerClass": owners,
        },
        "files": records,
    }


class WorkspaceManifestParityTests(unittest.TestCase):
    def _write(self, root: Path, name: str, payload: dict) -> Path:
        path = root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_exact_manifests_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = _manifest([_record("memory/state.json", b"one")])
            report = MODULE.compare_manifests(
                self._write(root, "baseline.json", payload),
                self._write(root, "candidate.json", payload),
            )
            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["parity"], "exact")

    def test_executor_writable_retained_content_drift_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            baseline = _manifest([_record("memory/state.json", b"one")])
            candidate = _manifest([_record("memory/state.json", b"seven")])
            report = MODULE.compare_manifests(
                self._write(root, "baseline.json", baseline),
                self._write(root, "candidate.json", candidate),
            )
            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["parity"], "approved-mutable-drift")
            self.assertEqual(report["summary"]["mutableContentChangedFiles"], 1)
            self.assertEqual(report["summary"]["mutableByteDelta"], 2)

    def test_modern_overlay_content_drift_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            baseline = _manifest(
                [
                    _record(
                        "AGENTS.md",
                        b"one",
                        origin="modern-overlay",
                        owner_class="operator-readonly",
                    )
                ]
            )
            candidate = _manifest(
                [
                    _record(
                        "AGENTS.md",
                        b"two",
                        origin="modern-overlay",
                        owner_class="operator-readonly",
                    )
                ]
            )
            report = MODULE.compare_manifests(
                self._write(root, "baseline.json", baseline),
                self._write(root, "candidate.json", candidate),
            )
            self.assertEqual(report["status"], "error")
            self.assertEqual(report["summary"]["immutableContentChangedFiles"], 1)

    def test_path_set_and_ownership_drift_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            baseline = _manifest([_record("memory/state.json", b"one")])
            candidate = _manifest(
                [
                    _record(
                        "memory/other.json",
                        b"one",
                        owner_class="operator-readonly",
                    )
                ]
            )
            report = MODULE.compare_manifests(
                self._write(root, "baseline.json", baseline),
                self._write(root, "candidate.json", candidate),
            )
            self.assertEqual(report["status"], "error")
            self.assertEqual(report["summary"]["addedFiles"], 1)
            self.assertEqual(report["summary"]["removedFiles"], 1)

    def test_invalid_summary_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = _manifest([_record("memory/state.json", b"one")])
            payload["summary"]["bytes"] += 1
            path = self._write(root, "manifest.json", payload)
            with self.assertRaises(MODULE.ManifestParityError):
                MODULE.compare_manifests(path, path)

    def test_symlink_manifest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = _manifest([_record("memory/state.json", b"one")])
            real = self._write(root, "real.json", payload)
            linked = root / "linked.json"
            linked.symlink_to(real)
            with self.assertRaises(MODULE.ManifestParityError):
                MODULE.compare_manifests(linked, real)


if __name__ == "__main__":
    unittest.main()
