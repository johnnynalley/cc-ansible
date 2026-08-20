#!/usr/bin/env python3
"""Regressions for isolated Hermes profile-data staging."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[2]
SCRIPT = Path(__file__).with_name("hermes-profile-data-stage.py")
CONTRACT = ROOT / "files" / "hermes" / "profile-data-stage-contract.json"
PROFILE_IMPORT = ROOT / "files" / "hermes" / "profile-import-contract.json"
PLAYBOOK = ROOT / "playbooks" / "agents" / "hermes-profile-data.yml"
VARS = ROOT / "inventory" / "group_vars" / "hermes_hosts" / "vars.yml"
UNIT = ROOT / "templates" / "hermes" / "hermes-gateway-hardening.conf.j2"
SPEC = importlib.util.spec_from_file_location("hermes_profile_data_stage", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class HermesProfileDataStageTests(unittest.TestCase):
    def fixture(self, root: Path) -> dict[str, Path]:
        repository = root / "repository"
        source = root / "source"
        target = root / "target"
        output = root / "output"
        repository.mkdir()
        source.mkdir()
        target.mkdir()
        target.chmod(0o700)
        output.mkdir()

        mappings = []
        rules = []
        profiles = ("astra", "dubble", "rigel")
        for index in range(20):
            rule_id = f"source-{index:02d}"
            source_name = f"tree-{index:02d}"
            profile = profiles[index % len(profiles)]
            mode = "operator-reference" if index in {2, 7, 13, 19} else "data-stage"
            owner = (
                "operator-readonly"
                if mode == "operator-reference"
                else "executor-writable"
            )
            target_name = f"namespace-{index:02d}"
            tree = source / source_name
            tree.mkdir()
            payload = tree / "payload.txt"
            payload.write_text(f"payload-{index}\n", encoding="utf-8")
            if index == 0:
                payload.chmod(0o755)
            rules.append(
                {
                    "id": rule_id,
                    "scope": "tree",
                    "pattern": source_name,
                    "disposition": "retain",
                    "target": source_name,
                    "ownerClass": owner,
                    "reason": "test",
                }
            )
            mappings.append(
                {
                    "sourceRuleId": rule_id,
                    "profile": profile,
                    "targetNamespace": target_name,
                    "ownerClass": owner,
                    "importMode": mode,
                    "exposure": "on-demand",
                    "rawPromptInjection": False,
                }
            )
        rules.append(
            {
                "id": "memory-source",
                "scope": "tree",
                "pattern": "memory",
                "disposition": "retain",
                "target": "memory",
                "ownerClass": "executor-writable",
                "reason": "test ignored memory",
            }
        )
        (source / "memory").mkdir()
        (source / "memory" / "ignored.md").write_text("untrusted\n")
        mappings.append(
            {
                "sourceRuleId": "memory-source",
                "profile": "astra",
                "targetNamespace": "imports/memory",
                "ownerClass": "executor-writable",
                "importMode": "memory-curation",
                "exposure": "approved-memory",
                "rawPromptInjection": False,
            }
        )
        profile_import = {"schemaVersion": 1, "workspaceMappings": mappings}
        policy = {
            "schemaVersion": 1,
            "archiveContract": "test archive",
            "rules": rules,
        }
        profile_import_path = repository / "profile-import.json"
        policy_path = repository / "policy.json"
        profile_import_path.write_text(json.dumps(profile_import), encoding="utf-8")
        policy_path.write_text(json.dumps(policy), encoding="utf-8")

        contract = copy.deepcopy(json.loads(CONTRACT.read_text(encoding="utf-8")))
        contract["sourceRoot"] = str(source)
        contract["sourcePins"] = {
            "profileImport": {
                "path": "profile-import.json",
                "sha256": hashlib.sha256(profile_import_path.read_bytes()).hexdigest(),
            },
            "workspacePolicy": {
                "path": "policy.json",
                "sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
            },
        }
        uid = os.geteuid()
        gid = os.getegid()
        contract["ownership"]["operatorUid"] = uid
        contract["ownership"]["operatorGid"] = gid
        for index, profile in enumerate(profiles):
            contract["profiles"][profile] = {
                "uid": uid,
                "gid": gid,
                "writableRoot": str(root / "active" / profile / "writable"),
                "managedRoot": str(root / "active" / profile / "managed"),
                "writableRuntimeRoot": str(root / "runtime" / profile / "imported-data"),
                "managedRuntimeRoot": str(root / "runtime" / profile / "managed-data"),
            }
        contract_path = root / "contract.json"
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        return {
            "repository": repository,
            "source": source,
            "target": target,
            "output": output,
            "contract": contract_path,
        }

    def test_production_contract_is_inactive_and_exactly_scoped(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(contract["mode"], "inactive-reviewed-profile-data")
        self.assertEqual(
            set(contract["selectedImportModes"]),
            {"data-stage", "operator-reference"},
        )
        self.assertTrue(all(value is False for value in contract["safety"].values()))
        self.assertTrue(all(value is True for value in contract["execution"].values()))
        self.assertEqual(contract["ownership"]["generationRootMode"], "0711")
        for profile, uid in (("astra", 62010), ("dubble", 62011), ("rigel", 62012)):
            row = contract["profiles"][profile]
            self.assertEqual(row["uid"], uid)
            self.assertEqual(row["gid"], uid)
            self.assertTrue(row["writableRoot"].startswith(f"/var/lib/hermes/profile-data/{profile}/"))
            self.assertTrue(row["managedRoot"].startswith(f"/var/lib/hermes/profile-data/{profile}/"))

        profile_import = json.loads(PROFILE_IMPORT.read_text(encoding="utf-8"))
        selected = [
            row
            for row in profile_import["workspaceMappings"]
            if row["importMode"] in set(contract["selectedImportModes"])
        ]
        self.assertEqual(len(selected), 20)

    def test_playbook_is_transactional_disabled_and_never_starts_a_gateway(self) -> None:
        import yaml

        variables = yaml.safe_load(VARS.read_text(encoding="utf-8"))
        playbook = PLAYBOOK.read_text(encoding="utf-8")
        unit = UNIT.read_text(encoding="utf-8")
        self.assertEqual(variables["hermes_profile_data_mode"], "disabled")
        self.assertFalse(variables["hermes_profile_data_approved"])
        self.assertIn("Back up current Hermes profile data", playbook)
        self.assertIn("Restore prior Hermes profile data", playbook)
        self.assertIn("Remove incomplete Hermes profile-data staging root", playbook)
        self.assertIn("partial root-private rollback directory was preserved", playbook)
        self.assertIn(
            "Verify existing Hermes profile-data generation before convergence",
            playbook,
        )
        self.assertIn("Classify existing Hermes profile-data generation", playbook)
        self.assertIn("existing_verify.stdout | from_json", playbook)
        self.assertIn("== 'manifest-contract-invalid'", playbook)
        self.assertIn("existingGenerationStatus", playbook)
        self.assertIn(
            "results[0].stat.exists\n            == hermes_profile_data_targets_before.results[1].stat.exists",
            playbook,
        )
        self.assertIn("Require unchanged production user services", playbook)
        self.assertIn("source-root", playbook)
        self.assertNotIn("state: started", playbook)
        self.assertNotIn("state: restarted", playbook)
        self.assertIn("Read effective Hermes Gateway units", playbook)
        gateway_read = playbook.index(
            "Read effective Hermes Gateway units for profile-data bindings"
        )
        gateway_gate = playbook.index(
            "Require reviewed profile-data bindings and startup gates"
        )
        self.assertIn("check_mode: false", playbook[gateway_read:gateway_gate])
        self.assertIn("HERMES_PROJECTION_PREFLIGHTS_PENDING=1", playbook)
        self.assertIn("HERMES_PROJECTION_PREFLIGHTS_PENDING=1", unit)
        self.assertIn("ExecStartPre=+{{ hermes_profile_data_stager_live }}", unit)
        self.assertIn("--mode runtime --profile {{ hermes_profile.name }}", unit)
        self.assertIn("BindPaths={{ hermes_profile_data_root }}", unit)
        self.assertIn("BindReadOnlyPaths={{ hermes_profile_data_root }}", unit)

    def test_plan_selects_only_data_and_operator_references(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.fixture(Path(directory))
            _, _, mappings, records, _ = MODULE.plan(
                paths["contract"], paths["repository"], paths["source"]
            )
            self.assertEqual(len(mappings), 20)
            self.assertEqual({row["mode"] for row in mappings}, MODULE.SELECTED_MODES)
            self.assertFalse(any("memory" in key for key in records))
            self.assertEqual(MODULE._summary(records)["files"], 20)

    def test_stage_resets_executable_bits_and_verifies_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.fixture(Path(directory))
            manifest = paths["output"] / "manifest.json"
            summary = MODULE.stage(
                paths["contract"],
                paths["repository"],
                paths["source"],
                paths["target"],
                manifest,
            )
            self.assertEqual(summary["files"], 20)
            writable_file = paths["target"] / "astra" / "writable" / "namespace-00" / "payload.txt"
            managed_file = paths["target"] / "rigel" / "managed" / "namespace-02" / "payload.txt"
            self.assertEqual(writable_file.stat().st_mode & 0o777, 0o640)
            self.assertEqual(managed_file.stat().st_mode & 0o777, 0o440)
            self.assertEqual(paths["target"].stat().st_mode & 0o777, 0o711)
            self.assertEqual(
                (paths["target"] / "astra").stat().st_mode & 0o777, 0o750
            )
            result = MODULE.verify(
                paths["contract"],
                paths["repository"],
                paths["target"],
                manifest,
                writable_drift=False,
            )
            self.assertEqual(result["managedFiles"], 4)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertGreater(len(payload["directories"]), 0)

    def test_selected_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.fixture(Path(directory))
            link = paths["source"] / "tree-00" / "link"
            link.symlink_to(paths["source"] / "tree-00" / "payload.txt")
            with self.assertRaisesRegex(MODULE.ProfileDataError, "symlink-rejected"):
                MODULE.plan(paths["contract"], paths["repository"], paths["source"])

    def test_source_change_during_stage_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.fixture(Path(directory))
            manifest = paths["output"] / "manifest.json"
            original = MODULE._copy_regular
            changed = False

            def copy_and_mutate(source: Path, target: Path, expected: object):
                nonlocal changed
                result = original(source, target, expected)
                if not changed:
                    changed = True
                    (paths["source"] / "tree-19" / "payload.txt").write_text("changed\n")
                return result

            with mock.patch.object(MODULE, "_copy_regular", side_effect=copy_and_mutate):
                with self.assertRaisesRegex(
                    MODULE.ProfileDataError,
                    "changed-before-copy|changed-during-stage",
                ):
                    MODULE.stage(
                        paths["contract"],
                        paths["repository"],
                        paths["source"],
                        paths["target"],
                        manifest,
                    )

    def test_writable_drift_is_allowed_but_managed_drift_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.fixture(Path(directory))
            manifest = paths["output"] / "manifest.json"
            MODULE.stage(
                paths["contract"],
                paths["repository"],
                paths["source"],
                paths["target"],
                manifest,
            )
            writable = paths["target"] / "astra" / "writable" / "new.txt"
            writable.write_text("new\n")
            writable.chmod(0o600)
            MODULE.verify(
                paths["contract"], paths["repository"], paths["target"], manifest, True
            )
            managed = paths["target"] / "rigel" / "managed" / "namespace-02" / "payload.txt"
            managed.chmod(0o640)
            with self.assertRaisesRegex(MODULE.ProfileDataError, "hash-drift|mode-drift"):
                MODULE.verify(
                    paths["contract"], paths["repository"], paths["target"], manifest, True
                )

    def test_unexpected_managed_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.fixture(Path(directory))
            manifest = paths["output"] / "manifest.json"
            MODULE.stage(
                paths["contract"],
                paths["repository"],
                paths["source"],
                paths["target"],
                manifest,
            )
            managed_root = paths["target"] / "astra" / "managed"
            managed_root.chmod(0o750)
            unexpected = managed_root / "unexpected"
            unexpected.mkdir(mode=0o550)
            managed_root.chmod(0o550)
            with self.assertRaisesRegex(MODULE.ProfileDataError, "directory-inventory-drift"):
                MODULE.verify(
                    paths["contract"], paths["repository"], paths["target"], manifest, True
                )

    def test_manifest_and_profile_root_drift_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.fixture(Path(directory))
            manifest = paths["output"] / "manifest.json"
            MODULE.stage(
                paths["contract"],
                paths["repository"],
                paths["source"],
                paths["target"],
                manifest,
            )
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["files"][0]["sha256"] = "not-a-hash"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ProfileDataError, "metadata-invalid"):
                MODULE.verify(
                    paths["contract"], paths["repository"], paths["target"], manifest, False
                )

            payload["files"][0]["sha256"] = hashlib.sha256(
                (
                    paths["target"]
                    / payload["files"][0]["profile"]
                    / payload["files"][0]["bucket"]
                    / payload["files"][0]["targetRelative"]
                ).read_bytes()
            ).hexdigest()
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            (paths["target"] / "unexpected").mkdir()
            with self.assertRaisesRegex(MODULE.ProfileDataError, "profile-inventory-drift"):
                MODULE.verify(
                    paths["contract"], paths["repository"], paths["target"], manifest, False
                )

    def test_source_pin_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.fixture(Path(directory))
            (paths["repository"] / "policy.json").write_text("{}\n")
            with self.assertRaisesRegex(MODULE.ProfileDataError, "hash-drift"):
                MODULE.plan(paths["contract"], paths["repository"], paths["source"])

    def test_unknown_contract_authority_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.fixture(Path(directory))
            contract = json.loads(paths["contract"].read_text(encoding="utf-8"))
            contract["activateGateway"] = True
            paths["contract"].write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ProfileDataError, "fields-invalid"):
                MODULE.plan(paths["contract"], paths["repository"], paths["source"])

    def test_runtime_probe_requires_profile_identity_and_exact_bind_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.fixture(root)
            contract = json.loads(paths["contract"].read_text(encoding="utf-8"))
            for key in (
                "writableRoot",
                "managedRoot",
                "writableRuntimeRoot",
                "managedRuntimeRoot",
            ):
                Path(contract["profiles"]["astra"][key]).mkdir(parents=True)
            mount_flags = [mock.Mock(f_flag=0), mock.Mock(f_flag=MODULE.os.ST_RDONLY)]
            with mock.patch.object(MODULE.os.path, "samefile", return_value=True), mock.patch.object(
                MODULE.os, "statvfs", side_effect=mount_flags
            ):
                result = MODULE.verify_runtime(
                    paths["contract"], paths["repository"], "astra"
                )
            self.assertEqual(result["runtimeBinds"], 2)

            with mock.patch.object(MODULE.os.path, "samefile", return_value=True), mock.patch.object(
                MODULE.os,
                "statvfs",
                side_effect=[mock.Mock(f_flag=0), mock.Mock(f_flag=0)],
            ):
                with self.assertRaisesRegex(MODULE.ProfileDataError, "mount-mode-invalid"):
                    MODULE.verify_runtime(
                        paths["contract"], paths["repository"], "astra"
                    )

            with mock.patch.object(MODULE.os, "geteuid", return_value=99999):
                with self.assertRaisesRegex(MODULE.ProfileDataError, "identity-invalid"):
                    MODULE.verify_runtime(
                        paths["contract"], paths["repository"], "astra"
                    )


if __name__ == "__main__":
    unittest.main()
