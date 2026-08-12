#!/usr/bin/env python3
"""Tests for legacy OpenClaw workspace classification."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("openclaw-workspace-inventory.py")
SPEC = importlib.util.spec_from_file_location("openclaw_workspace_inventory", SCRIPT)
assert SPEC and SPEC.loader
inventory_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = inventory_module
SPEC.loader.exec_module(inventory_module)


def policy_payload(rules: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "archiveContract": "Preserve the stopped source until parity passes.",
        "rules": rules,
    }


class WorkspaceInventoryTests(unittest.TestCase):
    def write_policy(self, root: Path, payload: dict[str, object]) -> Path:
        path = root / "policy.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_specific_rule_overrides_retained_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source = root / "source"
            (source / "memory").mkdir(parents=True)
            (source / "memory" / "daily.md").write_text("daily", encoding="utf-8")
            (source / "memory" / "old-alerts.json").write_text(
                "{}", encoding="utf-8"
            )
            policy = self.write_policy(
                root,
                policy_payload(
                    [
                        {
                            "id": "memory",
                            "scope": "tree",
                            "pattern": "memory",
                            "disposition": "retain",
                            "target": "memory",
                            "ownerClass": "executor-writable",
                            "reason": "Active data.",
                        },
                        {
                            "id": "alerts",
                            "scope": "glob",
                            "pattern": "memory/*-alerts.json",
                            "disposition": "replace",
                            "reason": "Typed state replaces it.",
                        },
                    ]
                ),
            )
            rules, _ = inventory_module.load_policy(policy)
            result = inventory_module.inventory_workspace(source, rules)
            summaries = {row["id"]: row for row in result["rules"]}
            self.assertEqual(summaries["memory"]["matchedPaths"], 2)
            self.assertEqual(summaries["alerts"]["matchedPaths"], 1)
            self.assertEqual(result["summary"]["bytesByDisposition"]["retain"], 5)

    def test_unknown_path_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source = root / "source"
            source.mkdir()
            (source / "unknown.bin").write_bytes(b"x")
            policy = self.write_policy(
                root,
                policy_payload(
                    [
                        {
                            "id": "known",
                            "scope": "exact",
                            "pattern": "known.txt",
                            "disposition": "archive",
                            "reason": "Known evidence.",
                        }
                    ]
                ),
            )
            rules, _ = inventory_module.load_policy(policy)
            with self.assertRaisesRegex(
                inventory_module.WorkspaceInventoryError, "unclassified path"
            ):
                inventory_module.inventory_workspace(source, rules)

    def test_retained_sensitive_path_requires_explicit_classification(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source = root / "source"
            (source / "credentials").mkdir(parents=True)
            (source / "credentials" / "service.json").write_text(
                "{}", encoding="utf-8"
            )
            policy = self.write_policy(
                root,
                policy_payload(
                    [
                        {
                            "id": "bad",
                            "scope": "tree",
                            "pattern": "credentials",
                            "disposition": "retain",
                            "target": "credentials",
                            "ownerClass": "executor-writable",
                            "reason": "Unsafe test fixture.",
                        }
                    ]
                ),
            )
            rules, _ = inventory_module.load_policy(policy)
            with self.assertRaisesRegex(
                inventory_module.WorkspaceInventoryError,
                "sensitive-looking path lacks classification",
            ):
                inventory_module.inventory_workspace(source, rules)

    def test_explicit_authorization_data_can_be_readonly(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source = root / "source"
            (source / "dubble").mkdir(parents=True)
            (source / "dubble" / "AUTH.yaml").write_text(
                "owners: []\n", encoding="utf-8"
            )
            policy = self.write_policy(
                root,
                policy_payload(
                    [
                        {
                            "id": "dubble",
                            "scope": "tree",
                            "pattern": "dubble",
                            "disposition": "archive",
                            "reason": "Archive legacy role files.",
                        },
                        {
                            "id": "auth",
                            "scope": "exact",
                            "pattern": "dubble/AUTH.yaml",
                            "disposition": "retain",
                            "target": "dubble/AUTH.yaml",
                            "ownerClass": "operator-readonly",
                            "sensitivity": "authorization-policy",
                            "reason": "Retain explicit authorization policy.",
                        },
                    ]
                ),
            )
            rules, _ = inventory_module.load_policy(policy)
            result = inventory_module.inventory_workspace(source, rules)
            self.assertEqual(
                result["summary"]["retainedOwnerClasses"]["operator-readonly"],
                1,
            )

    def test_symlink_is_classified_without_following_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source = root / "source"
            outside = root / "outside"
            source.mkdir()
            outside.mkdir()
            (outside / "secret.token").write_text("secret", encoding="utf-8")
            os.symlink(outside, source / "media")
            policy = self.write_policy(
                root,
                policy_payload(
                    [
                        {
                            "id": "media-link",
                            "scope": "exact",
                            "pattern": "media",
                            "disposition": "retire",
                            "reason": "Use a report broker.",
                        }
                    ]
                ),
            )
            rules, _ = inventory_module.load_policy(policy)
            result = inventory_module.inventory_workspace(source, rules)
            self.assertEqual(result["summary"]["kinds"], {"symlink": 1})
            self.assertEqual(result["summary"]["classifiedPaths"], 1)

    def test_nonretained_rule_cannot_declare_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            policy = self.write_policy(
                root,
                policy_payload(
                    [
                        {
                            "id": "invalid",
                            "scope": "tree",
                            "pattern": "tmp",
                            "disposition": "discard",
                            "target": "tmp",
                            "ownerClass": "executor-writable",
                            "reason": "Invalid fixture.",
                        }
                    ]
                ),
            )
            with self.assertRaisesRegex(
                inventory_module.WorkspaceInventoryError,
                "non-retained rule invalid cannot declare target ownership",
            ):
                inventory_module.load_policy(policy)


if __name__ == "__main__":
    unittest.main()
