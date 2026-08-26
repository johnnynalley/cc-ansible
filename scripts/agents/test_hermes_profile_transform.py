#!/usr/bin/env python3
"""Regressions for reviewed OpenClaw-to-Hermes state transforms."""

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
SCRIPT = Path(__file__).with_name("hermes-profile-transform.py")
CONTRACT = ROOT / "files" / "hermes" / "profile-transform-contract.json"
PROFILE_IMPORT = ROOT / "files" / "hermes" / "profile-import-contract.json"
WORKSPACE_POLICY = ROOT / "files" / "openclaw" / "workspace-migration-policy.json"
PLAYBOOK = ROOT / "playbooks" / "agents" / "hermes-profile-transforms.yml"
VARS = ROOT / "inventory" / "group_vars" / "hermes_hosts" / "vars.yml"
UNIT = ROOT / "templates" / "hermes" / "hermes-gateway-hardening.conf.j2"
RIGEL_JOB = ROOT / "files" / "hermes" / "jobs" / "rigel-academic-alerts.json"
SPEC = importlib.util.spec_from_file_location("hermes_profile_transform", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class HermesProfileTransformTests(unittest.TestCase):
    def fixture(self, root: Path) -> dict[str, Path]:
        source = root / "source"
        repository = root / "repository"
        target = root / "target"
        output = root / "output"
        source.mkdir()
        repository.mkdir()
        target.mkdir()
        output.mkdir()

        paths = [
            "dubble/users",
            "freshrss",
            "reddit",
            "rigel/courses",
            "sober-tracking",
            "tasks",
        ]
        for relative in paths:
            (source / relative).mkdir(parents=True, exist_ok=True)
        (source / "freshrss/state.json").write_text(
            json.dumps(
                {
                    "lastRun": "2026-08-13T11:15:15+00:00",
                    "matched": 51,
                    "candidateCount": 10,
                }
            ),
            encoding="utf-8",
        )
        (source / "reddit/sync-state.json").write_text(
            json.dumps(
                {
                    "lastSync": "2026-06-11T22:52:41+00:00",
                    "status": "error",
                    "error": "bounded failure",
                }
            ),
            encoding="utf-8",
        )
        (source / "rigel/courses/semester-context.md").write_text(
            "# Semester Context\n\n"
            "## Current Semester: Spring 2026\n\n"
            "## Active Courses\n\n"
            "_None - Spring 2026 is complete as of 2026-05-15._\n\n"
            "## Upcoming Exams\n\n"
            "_None - Spring 2026 is complete as of 2026-05-15._\n",
            encoding="utf-8",
        )
        (source / "rigel/courses/pending-calendar-requests.md").write_text(
            "# Pending Calendar Requests\n\n"
            "<!-- New entries go below this line -->\n",
            encoding="utf-8",
        )
        (source / "sober-tracking/state.json").write_text(
            json.dumps(
                {
                    "startDate": "2026-06-18",
                    "substance": "private",
                    "dailySpend": None,
                    "checkIns": [],
                    "milestonesHit": ["1 day"],
                    "relapses": [],
                    "silent": True,
                    "vaping": {
                        "startDate": "2026-07-01",
                        "substance": "private",
                        "dailySpend": None,
                    },
                }
            ),
            encoding="utf-8",
        )
        (source / "tasks/nextcloud-tasks.json").write_text(
            json.dumps(
                {
                    "generatedAt": "2026-08-13T12:00:00+00:00",
                    "lists": {
                        "Private": [
                            {
                                "file": "task.ics",
                                "summary": "task",
                                "status": "NEEDS-ACTION",
                                "due": None,
                                "description": None,
                                "percent": None,
                            }
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )

        profile_import = json.loads(PROFILE_IMPORT.read_text(encoding="utf-8"))
        workspace_policy = json.loads(WORKSPACE_POLICY.read_text(encoding="utf-8"))
        profile_import_path = repository / "profile-import.json"
        workspace_policy_path = repository / "workspace-policy.json"
        profile_import_path.write_text(json.dumps(profile_import), encoding="utf-8")
        workspace_policy_path.write_text(json.dumps(workspace_policy), encoding="utf-8")

        contract = copy.deepcopy(json.loads(CONTRACT.read_text(encoding="utf-8")))
        contract["sourceRoot"] = str(source)
        contract["sourcePins"] = {
            "profileImport": {
                "path": "profile-import.json",
                "sha256": hashlib.sha256(profile_import_path.read_bytes()).hexdigest(),
            },
            "workspacePolicy": {
                "path": "workspace-policy.json",
                "sha256": hashlib.sha256(workspace_policy_path.read_bytes()).hexdigest(),
            },
        }
        uid = os.geteuid()
        gid = os.getegid()
        contract["ownership"]["operatorUid"] = uid
        contract["ownership"]["operatorGid"] = gid
        for profile in ("astra", "dubble", "rigel"):
            contract["profiles"][profile] = {
                "uid": uid,
                "gid": gid,
                "writableRoot": str(root / "active" / profile / "writable"),
                "managedRoot": str(root / "active" / profile / "managed"),
                "writableRuntimeRoot": str(root / "runtime" / profile / "transformed-data"),
                "managedRuntimeRoot": str(root / "runtime" / profile / "transformed-managed"),
            }
        contract_path = root / "contract.json"
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        return {
            "source": source,
            "repository": repository,
            "target": target,
            "output": output,
            "contract": contract_path,
        }

    def test_production_contract_is_inactive_and_exactly_scoped(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(contract["mode"], "inactive-reviewed-profile-transforms")
        self.assertEqual({row["id"] for row in contract["transforms"]}, MODULE.EXPECTED_TRANSFORMS)
        self.assertTrue(all(value is False for value in contract["safety"].values()))
        self.assertTrue(all(value is True for value in contract["execution"].values()))
        self.assertEqual(contract["ownership"]["operatorUid"], 0)
        self.assertEqual(contract["ownership"]["generationRootMode"], "0711")

    def test_plan_normalizes_exactly_five_outputs_without_rigel_course_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.fixture(Path(directory))
            _, _, inputs, outputs = MODULE.plan(
                paths["contract"], paths["repository"], paths["source"]
            )
            self.assertEqual(len(inputs), 5)
            self.assertEqual(len(outputs), 5)
            self.assertEqual(
                {item.target_relative for item in outputs},
                {
                    "data/users/index.json",
                    "data/integrations/freshrss/state.json",
                    "data/integrations/reddit/sync-state.json",
                    "data/sober-tracking/state.json",
                    "data/tasks/nextcloud-tasks.json",
                },
            )
            self.assertFalse(any("lecture" in item.relative for item in inputs.values()))

    def test_stage_and_verify_preserve_private_state_in_isolated_outputs(self) -> None:
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
            self.assertEqual(summary["outputs"], 5)
            sobriety = json.loads(
                (
                    paths["target"]
                    / "astra/writable/data/sober-tracking/state.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(sobriety["schemaVersion"], 1)
            self.assertTrue(sobriety["silent"])
            result = MODULE.verify(
                paths["contract"],
                paths["repository"],
                paths["target"],
                manifest,
                allow_writable_drift=False,
            )
            self.assertEqual(result["profiles"]["rigel"]["outputs"], 0)

    def test_symlink_and_nonempty_dubble_registry_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.fixture(Path(directory))
            users = paths["source"] / "dubble/users"
            (users / "raw.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.TransformError, "directory-not-empty"):
                MODULE.plan(paths["contract"], paths["repository"], paths["source"])
        with tempfile.TemporaryDirectory() as directory:
            paths = self.fixture(Path(directory))
            state = paths["source"] / "reddit/sync-state.json"
            target = paths["source"] / "reddit/real.json"
            state.rename(target)
            state.symlink_to(target)
            with self.assertRaisesRegex(MODULE.TransformError, "not-regular"):
                MODULE.plan(paths["contract"], paths["repository"], paths["source"])

    def test_transform_layout_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.fixture(Path(directory))
            contract = json.loads(paths["contract"].read_text(encoding="utf-8"))
            contract["transforms"][0]["output"] = "data/users/raw-source.json"
            paths["contract"].write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.TransformError, "layout-drift"):
                MODULE.plan(paths["contract"], paths["repository"], paths["source"])

    def test_writable_drift_is_bounded_by_explicit_verify_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.fixture(Path(directory))
            manifest = paths["output"] / "manifest.json"
            MODULE.stage(
                paths["contract"], paths["repository"], paths["source"], paths["target"], manifest
            )
            writable = (
                paths["target"]
                / "astra/writable/data/integrations/reddit/sync-state.json"
            )
            writable.write_text("{\"changed\":true}\n", encoding="utf-8")
            writable.chmod(0o640)
            MODULE.verify(
                paths["contract"],
                paths["repository"],
                paths["target"],
                manifest,
                allow_writable_drift=True,
            )
            with self.assertRaisesRegex(MODULE.TransformError, "content-drift"):
                MODULE.verify(
                    paths["contract"],
                    paths["repository"],
                    paths["target"],
                    manifest,
                    allow_writable_drift=False,
                )

    def test_runtime_verifier_rejects_the_wrong_profile_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.fixture(Path(directory))
            contract = json.loads(paths["contract"].read_text(encoding="utf-8"))
            wrong_uid = contract["profiles"]["rigel"]["uid"] + 1
            with mock.patch.object(MODULE.os, "geteuid", return_value=wrong_uid):
                with self.assertRaisesRegex(
                    MODULE.TransformError, "runtime-profile-identity-invalid"
                ):
                    MODULE.verify_runtime(
                        paths["contract"], paths["repository"], "rigel"
                    )

    def test_playbook_and_unit_keep_transforms_disabled_and_isolated(self) -> None:
        import yaml

        variables = yaml.safe_load(VARS.read_text(encoding="utf-8"))
        playbook = PLAYBOOK.read_text(encoding="utf-8")
        unit = UNIT.read_text(encoding="utf-8")
        job = json.loads(RIGEL_JOB.read_text(encoding="utf-8"))
        self.assertEqual(variables["hermes_profile_transforms_mode"], "disabled")
        self.assertFalse(variables["hermes_profile_transforms_approved"])
        self.assertIn("Back up current Hermes profile transforms", playbook)
        self.assertIn("Restore prior Hermes profile transforms", playbook)
        self.assertIn(
            "Classify existing Hermes profile-transform generation", playbook
        )
        self.assertIn("existing_verify.stdout | from_json", playbook)
        self.assertIn("== 'manifest-contract-invalid'", playbook)
        self.assertIn("existingGenerationStatus", playbook)
        self.assertNotIn("state: started", playbook)
        self.assertNotIn("state: restarted", playbook)
        self.assertIn("Read effective Hermes Gateway units", playbook)
        gateway_read = playbook.index(
            "Read effective Hermes Gateway units for profile-transform bindings"
        )
        gateway_gate = playbook.index(
            "Require reviewed transform bindings and startup gates"
        )
        self.assertIn("check_mode: false", playbook[gateway_read:gateway_gate])
        self.assertIn("HERMES_PROJECTION_PREFLIGHTS_PENDING=1", playbook)
        self.assertIn("HERMES_PROJECTION_PREFLIGHTS_PENDING=1", unit)
        self.assertIn("hermes_profile_transformer_live", unit)
        self.assertIn("BindPaths={{ hermes_profile_transforms_root }}", unit)
        self.assertIn("BindReadOnlyPaths={{ hermes_profile_transforms_root }}", unit)
        self.assertEqual(
            job["source"],
            "imported-data/courses/academic-state.json",
        )


if __name__ == "__main__":
    unittest.main()
