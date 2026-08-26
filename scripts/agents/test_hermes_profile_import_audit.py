#!/usr/bin/env python3
"""Regression tests for Hermes profile import ownership and isolation."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
SCRIPT = Path(__file__).with_name("hermes-profile-import-audit.py")
CONTRACT = ROOT / "files" / "hermes" / "profile-import-contract.json"
WORKSPACE_POLICY = ROOT / "files" / "openclaw" / "workspace-migration-policy.json"
STATE_MIGRATION = ROOT / "files" / "hermes" / "openclaw-state-migration-contract.json"
SPEC = importlib.util.spec_from_file_location("hermes_profile_import_audit", SCRIPT)
assert SPEC and SPEC.loader
audit_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit_module
SPEC.loader.exec_module(audit_module)


class HermesProfileImportAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def write_contract(self, root: Path, payload: dict[str, object]) -> Path:
        path = root / "contract.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def validate(self, contract_path: Path) -> dict[str, object]:
        return audit_module.load_and_validate(
            contract_path,
            WORKSPACE_POLICY,
            STATE_MIGRATION,
            ROOT,
        )

    def mapping(self, payload: dict[str, object], rule_id: str) -> dict[str, object]:
        return next(
            row
            for row in payload["workspaceMappings"]
            if row["sourceRuleId"] == rule_id
        )

    def test_canonical_contract_maps_every_retained_source_once(self) -> None:
        result = self.validate(CONTRACT)
        self.assertEqual(result["profiles"], ["astra", "dubble", "rigel"])
        self.assertEqual(result["workspace"]["mappingCount"], 33)
        self.assertEqual(
            result["workspace"]["profiles"],
            {"astra": 24, "dubble": 4, "rigel": 5},
        )
        self.assertEqual(result["stateRoot"]["mappingCount"], 2)

    def test_source_content_classes_are_never_raw_prompt_injected(self) -> None:
        for row in self.contract["workspaceMappings"]:
            self.assertFalse(row["rawPromptInjection"])
        for row in self.contract["stateRootMappings"]:
            self.assertFalse(row["rawPromptInjection"])

    def test_missing_retained_mapping_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = copy.deepcopy(self.contract)
            payload["workspaceMappings"] = payload["workspaceMappings"][:-1]
            with self.assertRaisesRegex(
                audit_module.ProfileImportAuditError,
                "workspace retained mapping mismatch",
            ):
                self.validate(self.write_contract(root, payload))

    def test_duplicate_profile_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = copy.deepcopy(self.contract)
            asset = self.mapping(payload, "assets-data")
            case = self.mapping(payload, "case-data")
            case["targetNamespace"] = asset["targetNamespace"]
            with self.assertRaisesRegex(
                audit_module.ProfileImportAuditError,
                "duplicate profile target namespace",
            ):
                self.validate(self.write_contract(root, payload))

    def test_owner_class_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = copy.deepcopy(self.contract)
            mapping = self.mapping(payload, "legacy-references")
            mapping["ownerClass"] = "executor-writable"
            mapping["importMode"] = "data-stage"
            with self.assertRaisesRegex(
                audit_module.ProfileImportAuditError, "owner-class drift"
            ):
                self.validate(self.write_contract(root, payload))

    def test_dubble_source_cannot_cross_into_astra(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = copy.deepcopy(self.contract)
            mapping = self.mapping(payload, "dubble-memory")
            mapping["profile"] = "astra"
            mapping["targetNamespace"] = "imports/dubble-memory"
            with self.assertRaisesRegex(
                audit_module.ProfileImportAuditError,
                "cross-profile source assignment",
            ):
                self.validate(self.write_contract(root, payload))

    def test_reviewer_memory_must_remain_private_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = copy.deepcopy(self.contract)
            mapping = self.mapping(payload, "antares-memory-data")
            mapping["importMode"] = "memory-curation"
            mapping["exposure"] = "approved-memory"
            with self.assertRaisesRegex(
                audit_module.ProfileImportAuditError,
                "must remain private review evidence",
            ):
                self.validate(self.write_contract(root, payload))

    def test_memory_source_must_require_approved_curation(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = copy.deepcopy(self.contract)
            mapping = self.mapping(payload, "legacy-memory-tree")
            mapping["importMode"] = "data-stage"
            mapping["exposure"] = "on-demand"
            with self.assertRaisesRegex(
                audit_module.ProfileImportAuditError,
                "must use approved curation",
            ):
                self.validate(self.write_contract(root, payload))

    def test_rigel_academic_journal_remains_isolated_course_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = copy.deepcopy(self.contract)
            mapping = self.mapping(payload, "rigel-memory")
            mapping["importMode"] = "memory-curation"
            mapping["exposure"] = "approved-memory"
            with self.assertRaisesRegex(
                audit_module.ProfileImportAuditError,
                "must remain isolated Rigel data",
            ):
                self.validate(self.write_contract(root, payload))

    def test_raw_prompt_injection_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = copy.deepcopy(self.contract)
            self.mapping(payload, "hardware-inventory")["rawPromptInjection"] = True
            with self.assertRaisesRegex(
                audit_module.ProfileImportAuditError,
                "raw prompt injection must be disabled",
            ):
                self.validate(self.write_contract(root, payload))

    def test_any_runtime_or_import_authority_enablement_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = copy.deepcopy(self.contract)
            payload["safety"]["automaticMemoryApprovalAuthorized"] = True
            with self.assertRaisesRegex(
                audit_module.ProfileImportAuditError, "safety contract"
            ):
                self.validate(self.write_contract(root, payload))

    def test_state_root_curated_mapping_must_be_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = copy.deepcopy(self.contract)
            payload["stateRootMappings"] = [payload["stateRootMappings"][0]]
            with self.assertRaisesRegex(
                audit_module.ProfileImportAuditError,
                "state-root curated mapping mismatch",
            ):
                self.validate(self.write_contract(root, payload))

    def test_state_root_curation_cannot_cross_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = copy.deepcopy(self.contract)
            payload["stateRootMappings"][0]["profile"] = "dubble"
            with self.assertRaisesRegex(
                audit_module.ProfileImportAuditError,
                "state-root curation cannot cross",
            ):
                self.validate(self.write_contract(root, payload))

    def test_state_migration_hash_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            payload = copy.deepcopy(self.contract)
            payload["sourceContracts"]["stateMigration"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(
                audit_module.ProfileImportAuditError,
                "state migration source hash drift",
            ):
                self.validate(self.write_contract(root, payload))

    def test_behavior_source_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            target = root / "target.md"
            target.write_text("behavior", encoding="utf-8")
            for profile in audit_module.EXPECTED_PROFILES:
                source = root / "files" / "hermes" / "profiles" / profile / "SOUL.md"
                source.parent.mkdir(parents=True)
                source.write_text("behavior", encoding="utf-8")
            astra = root / "files" / "hermes" / "profiles" / "astra" / "SOUL.md"
            astra.unlink()
            os.symlink(target, astra)
            with self.assertRaisesRegex(
                audit_module.ProfileImportAuditError,
                "regular non-symlink",
            ):
                audit_module._validate_profiles(audit_module.EXPECTED_PROFILES, root)


if __name__ == "__main__":
    unittest.main()
