#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("openclaw-session-relocate.py")
SPEC = importlib.util.spec_from_file_location("openclaw_session_relocate", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class SessionRelocationTests(unittest.TestCase):
    def _fixture(self, root: Path, state_name: str) -> tuple[Path, Path]:
        state = root / state_name
        workspace = state / "workspace"
        sessions = state / "agents" / "main" / "sessions"
        prompt = workspace / "skills" / "demo.md"
        transcript = sessions / "session-one.jsonl"
        trajectory = sessions / "session-one.trajectory.jsonl"
        trajectory_path = sessions / "session-one.trajectory-path.json"
        prompt.parent.mkdir(parents=True)
        sessions.mkdir(parents=True)
        prompt.write_text("prompt\n", encoding="utf-8")
        transcript.write_text('{"type":"session","id":"one"}\n', encoding="utf-8")
        trajectory.write_text('{"event":"start"}\n', encoding="utf-8")
        trajectory_path.write_text('{"path":[]}\n', encoding="utf-8")
        (sessions / "sessions.json").write_text(
            json.dumps(
                {
                    "agent:main:main": {
                        "sessionId": "one",
                        "sessionFile": str(transcript),
                        "workspaceDir": str(workspace),
                        "spawnedWorkspaceDir": str(workspace),
                        "spawnedCwd": str(workspace),
                        "skillsSnapshot": {"prompt": "legacy skill catalog"},
                        "systemPromptReport": {
                            "workspaceDir": str(workspace),
                            "injectedWorkspaceFiles": [
                                {
                                    "name": "demo",
                                    "path": str(prompt),
                                    "missing": False,
                                    "rawChars": 7,
                                    "injectedChars": 7,
                                    "truncated": False,
                                }
                            ],
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        return state, workspace

    def _copy_fixture(self, source: Path, target: Path) -> None:
        shutil.copytree(source, target)

    def _split_target_workspace(self, root: Path, target: Path) -> Path:
        target_workspace = root / "target-workspace"
        (target / "workspace").rename(target_workspace)
        return target_workspace

    def _split_source_workspace(self, root: Path, source: Path) -> Path:
        source_workspace = root / "source-workspace"
        (source / "workspace").rename(source_workspace)
        index = source / "agents" / "main" / "sessions" / "sessions.json"
        payload = json.loads(index.read_text(encoding="utf-8"))
        serialized = json.dumps(payload).replace(
            str(source / "workspace"), str(source_workspace)
        )
        index.write_text(serialized, encoding="utf-8")
        return source_workspace

    def test_rewrite_and_verify_preserve_artifact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, source_workspace = self._fixture(root, "source")
            target = root / "target"
            self._copy_fixture(source, target)
            target_workspace = self._split_target_workspace(root, target)

            before = (
                target / "agents" / "main" / "sessions" / "session-one.jsonl"
            ).read_bytes()
            index = target / "agents" / "main" / "sessions" / "sessions.json"
            index_metadata_before = index.stat()
            result = MODULE.rewrite_session_stores(
                target,
                source,
                source_workspace,
                target_workspace,
                ["main"],
            )
            self.assertEqual(result["changedFiles"], 1)
            self.assertEqual(result["rewrittenReferences"], 6)
            after = (
                target / "agents" / "main" / "sessions" / "session-one.jsonl"
            ).read_bytes()
            self.assertEqual(before, after)
            index_metadata_after = index.stat()
            self.assertEqual(index_metadata_after.st_uid, index_metadata_before.st_uid)
            self.assertEqual(index_metadata_after.st_gid, index_metadata_before.st_gid)
            self.assertEqual(
                index_metadata_after.st_mode & 0o777,
                index_metadata_before.st_mode & 0o777,
            )

            verified = MODULE.verify_relocation(
                source,
                source_workspace,
                target,
                target_workspace,
                ["main"],
            )
            self.assertEqual(verified["status"], "ok")
            self.assertEqual(verified["entries"], 1)

            inspected = MODULE.inspect_session_stores(
                source,
                source_workspace,
                ["main"],
            )
            reference_details = inspected["agents"][0]["referenceDetails"]
            self.assertEqual(len(reference_details), 6)
            self.assertEqual(
                inspected["summary"]["referenceCategories"],
                {"state": 1, "workspace": 5},
            )
            self.assertEqual(
                inspected["summary"]["referenceRoles"],
                {
                    "active-workspace": 1,
                    "derived-bootstrap-path": 1,
                    "derived-bootstrap-root": 1,
                    "session-transcript": 1,
                    "spawned-cwd": 1,
                    "spawned-workspace": 1,
                },
            )
            self.assertTrue(
                any(
                    row["relativePath"] == "skills/demo.md"
                    and row["pathKind"] == "file"
                    for row in reference_details
                )
            )

            second = MODULE.rewrite_session_stores(
                target,
                source,
                source_workspace,
                target_workspace,
                ["main"],
            )
            self.assertEqual(second["changedFiles"], 0)
            self.assertEqual(second["rewrittenReferences"], 0)

    def test_rewrite_supports_modern_split_source_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, _ = self._fixture(root, "source")
            source_workspace = self._split_source_workspace(root, source)
            target = root / "target"
            self._copy_fixture(source, target)
            target_workspace = root / "target-workspace"
            shutil.copytree(source_workspace, target_workspace)

            rewritten = MODULE.rewrite_session_stores(
                target,
                source,
                source_workspace,
                target_workspace,
                ["main"],
            )
            self.assertEqual(rewritten["changedFiles"], 1)
            verified = MODULE.verify_relocation(
                source,
                source_workspace,
                target,
                target_workspace,
                ["main"],
            )
            self.assertEqual(verified["status"], "ok")

    def test_rewrite_rejects_source_target_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, source_workspace = self._fixture(root, "source")
            target = source / "target"
            self._copy_fixture(source / "agents", target / "agents")
            target_workspace = root / "target-workspace"
            target_workspace.mkdir()

            with self.assertRaisesRegex(
                MODULE.SessionRelocationError,
                "source and target roots must not overlap",
            ):
                MODULE.rewrite_session_stores(
                    target,
                    source,
                    source_workspace,
                    target_workspace,
                    ["main"],
                )

    def test_rejects_unapproved_state_root_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, source_workspace = self._fixture(root, "source")
            target = root / "target"
            self._copy_fixture(source, target)
            target_workspace = self._split_target_workspace(root, target)
            index = target / "agents" / "main" / "sessions" / "sessions.json"
            payload = json.loads(index.read_text(encoding="utf-8"))
            payload["agent:main:main"]["message"] = str(source_workspace / "secret")
            index.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(MODULE.SessionRelocationError):
                MODULE.rewrite_session_stores(
                    target,
                    source,
                    source_workspace,
                    target_workspace,
                    ["main"],
                )

    def test_modernization_discards_only_derived_prompt_caches(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, source_workspace = self._fixture(root, "source")
            target = root / "target"
            self._copy_fixture(source, target)
            target_workspace = self._split_target_workspace(root, target)
            shutil.rmtree(target_workspace / "skills")

            result = MODULE.rewrite_session_stores(
                target,
                source,
                source_workspace,
                target_workspace,
                ["main"],
                modernize_derived_snapshots=True,
            )
            self.assertEqual(result["changedFiles"], 1)
            self.assertEqual(result["rewrittenReferences"], 4)
            self.assertEqual(result["clearedDerivedSnapshots"], 2)
            self.assertEqual(
                result["clearedDerivedSnapshotFields"],
                {"skillsSnapshot": 1, "systemPromptReport": 1},
            )

            index = target / "agents" / "main" / "sessions" / "sessions.json"
            entry = json.loads(index.read_text(encoding="utf-8"))["agent:main:main"]
            self.assertNotIn("skillsSnapshot", entry)
            self.assertNotIn("systemPromptReport", entry)
            self.assertEqual(entry["sessionId"], "one")

            verified = MODULE.verify_relocation(
                source,
                source_workspace,
                target,
                target_workspace,
                ["main"],
                modernize_derived_snapshots=True,
            )
            self.assertEqual(verified["status"], "ok")

    def test_modernization_clears_generated_state_and_preserves_preferences(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, source_workspace = self._fixture(root, "source")
            index = source / "agents" / "main" / "sessions" / "sessions.json"
            payload = json.loads(index.read_text(encoding="utf-8"))
            payload["agent:main:main"].update(
                {
                    "authProfileOverride": "legacy-profile",
                    "authProfileOverrideSource": "auto",
                    "authProfileOverrideCompactionCount": 2,
                    "model": "legacy-model",
                    "modelProvider": "legacy-provider",
                    "modelOverride": "fallback-model",
                    "providerOverride": "fallback-provider",
                    "modelOverrideSource": "auto",
                    "modelOverrideFallbackOriginModel": "legacy-model",
                    "modelOverrideFallbackOriginProvider": "legacy-provider",
                    "thinkingLevel": "low",
                    "responseUsage": "tokens",
                    "systemSent": True,
                    "label": "preserved-label",
                }
            )
            payload["agent:main:archived"] = {
                "sessionId": "archived",
                "archivedAt": 1,
                "model": "historical-model",
            }
            index.write_text(json.dumps(payload), encoding="utf-8")

            target = root / "target"
            self._copy_fixture(source, target)
            target_workspace = self._split_target_workspace(root, target)
            result = MODULE.rewrite_session_stores(
                target,
                source,
                source_workspace,
                target_workspace,
                ["main"],
                modernize_derived_snapshots=True,
                modernize_active_runtime_state=True,
            )

            transformed = json.loads(
                (target / "agents" / "main" / "sessions" / "sessions.json").read_text(
                    encoding="utf-8"
                )
            )
            active = transformed["agent:main:main"]
            for field in (
                "authProfileOverride",
                "authProfileOverrideSource",
                "authProfileOverrideCompactionCount",
                "model",
                "modelProvider",
                "modelOverride",
                "providerOverride",
                "modelOverrideSource",
                "modelOverrideFallbackOriginModel",
                "modelOverrideFallbackOriginProvider",
                "systemSent",
            ):
                self.assertNotIn(field, active)
            self.assertEqual(active["thinkingLevel"], "low")
            self.assertEqual(active["responseUsage"], "tokens")
            self.assertEqual(active["label"], "preserved-label")
            self.assertEqual(active["sessionId"], "one")
            self.assertEqual(
                transformed["agent:main:archived"]["model"], "historical-model"
            )
            self.assertGreater(result["clearedActiveRuntimeState"], 0)
            self.assertEqual(result["preservedActiveRuntimeState"], {})

            verified = MODULE.verify_relocation(
                source,
                source_workspace,
                target,
                target_workspace,
                ["main"],
                modernize_derived_snapshots=True,
                modernize_active_runtime_state=True,
            )
            self.assertEqual(verified["status"], "ok")

    def test_modernization_preserves_explicit_user_model_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, source_workspace = self._fixture(root, "source")
            index = source / "agents" / "main" / "sessions" / "sessions.json"
            payload = json.loads(index.read_text(encoding="utf-8"))
            payload["agent:main:main"].update(
                {
                    "model": "resolved-model",
                    "modelProvider": "resolved-provider",
                    "modelOverride": "chosen-model",
                    "providerOverride": "chosen-provider",
                    "modelOverrideSource": "user",
                }
            )
            index.write_text(json.dumps(payload), encoding="utf-8")

            target = root / "target"
            self._copy_fixture(source, target)
            target_workspace = self._split_target_workspace(root, target)
            result = MODULE.rewrite_session_stores(
                target,
                source,
                source_workspace,
                target_workspace,
                ["main"],
                modernize_active_runtime_state=True,
            )

            transformed = json.loads(
                (target / "agents" / "main" / "sessions" / "sessions.json").read_text(
                    encoding="utf-8"
                )
            )["agent:main:main"]
            self.assertNotIn("model", transformed)
            self.assertNotIn("modelProvider", transformed)
            self.assertEqual(transformed["modelOverride"], "chosen-model")
            self.assertEqual(transformed["providerOverride"], "chosen-provider")
            self.assertEqual(transformed["modelOverrideSource"], "user")
            self.assertEqual(
                result["preservedActiveRuntimeState"], {"userModelSelection": 1}
            )

    def test_modernization_rejects_unreviewed_session_authority(self) -> None:
        scenarios = (
            {"authProfileOverride": "profile", "authProfileOverrideSource": "user"},
            {"execSecurity": "full"},
            {"agentRuntimeOverride": "codex"},
        )
        for scenario in scenarios:
            with self.subTest(
                scenario=scenario
            ), tempfile.TemporaryDirectory() as directory_name:
                root = Path(directory_name)
                source, source_workspace = self._fixture(root, "source")
                index = source / "agents" / "main" / "sessions" / "sessions.json"
                payload = json.loads(index.read_text(encoding="utf-8"))
                payload["agent:main:main"].update(scenario)
                index.write_text(json.dumps(payload), encoding="utf-8")

                target = root / "target"
                self._copy_fixture(source, target)
                target_workspace = self._split_target_workspace(root, target)
                with self.assertRaises(MODULE.SessionRelocationError):
                    MODULE.rewrite_session_stores(
                        target,
                        source,
                        source_workspace,
                        target_workspace,
                        ["main"],
                        modernize_active_runtime_state=True,
                    )

    def test_rehearsal_quarantines_delivery_recovery_only_in_active_copy(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, source_workspace = self._fixture(root, "source")
            index = source / "agents" / "main" / "sessions" / "sessions.json"
            payload = json.loads(index.read_text(encoding="utf-8"))
            recovery = {
                "pendingFinalDelivery": True,
                "pendingFinalDeliveryText": "production response",
                "pendingFinalDeliveryContext": {"channel": "discord"},
                "pendingFinalDeliveryIntentId": "intent-one",
                "restartRecoveryDeliveryContext": {"channel": "discord"},
                "restartRecoveryDeliveryRunId": "run-one",
            }
            payload["agent:main:main"].update(recovery)
            payload["agent:main:archived"] = {
                "sessionId": "archived",
                "archivedAt": 1,
                **recovery,
            }
            index.write_text(json.dumps(payload), encoding="utf-8")
            source_index_before = index.read_bytes()

            inspected_source = MODULE.inspect_session_stores(
                source,
                source_workspace,
                ["main"],
            )
            self.assertEqual(
                inspected_source["summary"]["activeDeliveryRecoveryEntries"], 1
            )
            self.assertEqual(
                sum(
                    inspected_source["summary"]["activeDeliveryRecoveryFields"].values()
                ),
                len(recovery),
            )

            target = root / "target"
            self._copy_fixture(source, target)
            target_workspace = self._split_target_workspace(root, target)
            result = MODULE.rewrite_session_stores(
                target,
                source,
                source_workspace,
                target_workspace,
                ["main"],
                quarantine_delivery_recovery=True,
            )

            transformed = json.loads(
                (target / "agents" / "main" / "sessions" / "sessions.json").read_text(
                    encoding="utf-8"
                )
            )
            active = transformed["agent:main:main"]
            for field in recovery:
                self.assertNotIn(field, active)
                self.assertIn(field, transformed["agent:main:archived"])
            self.assertEqual(active["sessionId"], "one")
            self.assertEqual(result["quarantinedDeliveryRecoveryEntries"], 1)
            self.assertEqual(result["quarantinedDeliveryRecoveryFields"], len(recovery))
            self.assertEqual(
                result["targetSummary"]["activeDeliveryRecoveryEntries"], 0
            )
            self.assertEqual(index.read_bytes(), source_index_before)

            verified = MODULE.verify_relocation(
                source,
                source_workspace,
                target,
                target_workspace,
                ["main"],
                quarantine_delivery_recovery=True,
            )
            self.assertEqual(verified["status"], "ok")
            self.assertEqual(verified["quarantinedDeliveryRecoveryEntries"], 1)

            with self.assertRaises(MODULE.SessionRelocationError):
                MODULE.verify_relocation(
                    source,
                    source_workspace,
                    target,
                    target_workspace,
                    ["main"],
                )

    def test_rejects_missing_or_external_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, source_workspace = self._fixture(root, "source")
            index = source / "agents" / "main" / "sessions" / "sessions.json"
            payload = json.loads(index.read_text(encoding="utf-8"))
            payload["agent:main:main"]["sessionFile"] = str(root / "outside.jsonl")
            index.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(MODULE.SessionRelocationError):
                MODULE.inspect_session_stores(source, source_workspace, ["main"])

    def test_verify_detects_changed_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, source_workspace = self._fixture(root, "source")
            target = root / "target"
            self._copy_fixture(source, target)
            target_workspace = self._split_target_workspace(root, target)
            MODULE.rewrite_session_stores(
                target,
                source,
                source_workspace,
                target_workspace,
                ["main"],
            )
            transcript = target / "agents" / "main" / "sessions" / "session-one.jsonl"
            transcript.write_text("changed\n", encoding="utf-8")

            with self.assertRaises(MODULE.SessionRelocationError):
                MODULE.verify_relocation(
                    source,
                    source_workspace,
                    target,
                    target_workspace,
                    ["main"],
                )

    def test_immutable_verification_ignores_later_live_index_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, source_workspace = self._fixture(root, "source")
            target = root / "target"
            self._copy_fixture(source, target)
            target_workspace = self._split_target_workspace(root, target)
            manifest_path = root / "source-manifest.json"
            MODULE._write_json_atomic(
                manifest_path,
                MODULE.inspect_session_stores(source, source_workspace, ["main"]),
            )
            index_snapshots = root / "index-snapshots" / "main"
            index_snapshots.mkdir(parents=True)
            source_index = source / "agents" / "main" / "sessions" / "sessions.json"
            shutil.copy2(source_index, index_snapshots / "sessions.json")

            MODULE.rewrite_session_stores(
                target,
                source,
                source_workspace,
                target_workspace,
                ["main"],
            )
            source_payload = json.loads(source_index.read_text(encoding="utf-8"))
            source_payload["agent:main:main"]["updatedAt"] = 12345
            source_index.write_text(json.dumps(source_payload), encoding="utf-8")

            verified = MODULE.verify_relocation(
                source,
                source_workspace,
                target,
                target_workspace,
                ["main"],
                manifest_path,
                index_snapshots.parent,
            )
            self.assertEqual(verified["status"], "ok")

            with self.assertRaises(MODULE.SessionRelocationError):
                MODULE.verify_relocation(
                    source,
                    source_workspace,
                    target,
                    target_workspace,
                    ["main"],
                )

    def test_rejects_reference_that_traverses_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, source_workspace = self._fixture(root, "source")
            real_directory = source_workspace / "real"
            real_directory.mkdir()
            (real_directory / "prompt.md").write_text("prompt\n", encoding="utf-8")
            (source_workspace / "linked").symlink_to(real_directory)
            index = source / "agents" / "main" / "sessions" / "sessions.json"
            payload = json.loads(index.read_text(encoding="utf-8"))
            payload["agent:main:main"]["systemPromptReport"]["injectedWorkspaceFiles"][
                0
            ]["path"] = str(source_workspace / "linked" / "prompt.md")
            index.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(MODULE.SessionRelocationError):
                MODULE.inspect_session_stores(source, source_workspace, ["main"])

    def test_rejects_lexical_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, source_workspace = self._fixture(root, "source")
            index = source / "agents" / "main" / "sessions" / "sessions.json"
            payload = json.loads(index.read_text(encoding="utf-8"))
            payload["agent:main:main"]["systemPromptReport"]["injectedWorkspaceFiles"][
                0
            ]["path"] = f"{source_workspace}/skills/../skills/demo.md"
            index.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(MODULE.SessionRelocationError):
                MODULE.inspect_session_stores(source, source_workspace, ["main"])

    def test_rejects_generic_nested_path_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, source_workspace = self._fixture(root, "source")
            index = source / "agents" / "main" / "sessions" / "sessions.json"
            payload = json.loads(index.read_text(encoding="utf-8"))
            payload["agent:main:main"]["pluginState"] = {
                "path": str(source_workspace / "skills" / "demo.md")
            }
            index.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(
                MODULE.SessionRelocationError,
                "unapproved metadata location",
            ):
                MODULE.inspect_session_stores(source, source_workspace, ["main"])


if __name__ == "__main__":
    unittest.main()
