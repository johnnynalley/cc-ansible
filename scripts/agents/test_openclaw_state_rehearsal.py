#!/usr/bin/env python3

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

PLAYBOOK_PATH = (
    Path(__file__).resolve().parents[2]
    / "playbooks"
    / "agents"
    / "openclaw-state-rehearsal.yml"
)


class StateRehearsalPlaybookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        payload = yaml.safe_load(PLAYBOOK_PATH.read_text(encoding="utf-8"))
        cls.tasks = cls._flatten_tasks(payload[0]["tasks"])

    @staticmethod
    def _flatten_tasks(tasks: list[dict]) -> list[dict]:
        flattened: list[dict] = []
        for task in tasks:
            flattened.append(task)
            for section in ("block", "rescue", "always"):
                flattened.extend(
                    StateRehearsalPlaybookTests._flatten_tasks(task.get(section, []))
                )
        return flattened

    def _task(self, name: str) -> dict:
        return next(task for task in self.tasks if task.get("name") == name)

    def test_immutable_capture_options_belong_only_to_verify(self) -> None:
        rewrite = self._task("Rewrite copied OpenClaw session paths")
        verify = self._task("Verify copied OpenClaw session relocation")
        rewrite_argv = rewrite["ansible.builtin.command"]["argv"]
        verify_argv = verify["ansible.builtin.command"]["argv"]

        self.assertIn("'rewrite'", rewrite_argv)
        self.assertNotIn("--source-manifest", rewrite_argv)
        self.assertNotIn("--source-index-root", rewrite_argv)
        self.assertIn("--modernize-derived-snapshots", rewrite_argv)
        self.assertIn("--modernize-active-runtime-state", rewrite_argv)
        self.assertIn("--quarantine-delivery-recovery", rewrite_argv)
        self.assertIn("'verify'", verify_argv)
        self.assertIn("--source-manifest", verify_argv)
        self.assertIn("--source-index-root", verify_argv)
        self.assertIn("--modernize-derived-snapshots", verify_argv)
        self.assertIn("--modernize-active-runtime-state", verify_argv)
        self.assertIn("--quarantine-delivery-recovery", verify_argv)

    def test_source_indexes_are_preserved_before_rewrite(self) -> None:
        names = [task.get("name") for task in self.tasks]
        preserve_index = names.index(
            "Preserve copied OpenClaw indexes before path transformation"
        )
        rewrite = names.index("Rewrite copied OpenClaw session paths")
        verify = names.index("Verify copied OpenClaw session relocation")
        self.assertLess(preserve_index, rewrite)
        self.assertLess(rewrite, verify)

    def test_legacy_workspace_files_are_not_copied(self) -> None:
        names = [task.get("name") for task in self.tasks]
        self.assertNotIn("Copy session-referenced OpenClaw workspace files", names)

    def test_target_manifest_is_created_before_it_is_read(self) -> None:
        names = [task.get("name") for task in self.tasks]
        manifest = names.index("Manifest relocated OpenClaw session generation")
        read = names.index("Read relocated OpenClaw session manifest")
        reject = names.index(
            "Reject legacy prompt cache references in relocated sessions"
        )
        self.assertLess(manifest, read)
        self.assertLess(read, reject)

    def test_rehearsal_rejects_replay_capable_delivery_state(self) -> None:
        task = self._task("Reject delivery recovery state in relocated sessions")
        assertions = task["ansible.builtin.assert"]["that"]
        self.assertIn(
            "openclaw_state_rehearsal_target_manifest.summary.activeDeliveryRecoveryEntries is defined",
            assertions,
        )
        self.assertIn(
            "openclaw_state_rehearsal_target_manifest.summary.activeDeliveryRecoveryEntries | default(-1) | int == 0",
            assertions,
        )

    def test_read_proof_drops_identity_inside_root_module(self) -> None:
        read_proof = self._task(
            "Read frozen OpenClaw rehearsal generation as migration account"
        )
        argv = read_proof["ansible.builtin.command"]["argv"]
        self.assertNotIn("become_user", read_proof)
        self.assertIn("'/usr/sbin/runuser'", argv)
        self.assertIn("'--user', openclaw_state_rehearsal_user", argv)

    def test_generation_containers_allow_only_group_traversal(self) -> None:
        containers = self._task("Create OpenClaw state rehearsal generation containers")
        module = containers["ansible.builtin.file"]
        self.assertEqual(module["owner"], "root")
        self.assertEqual(module["group"], "{{ openclaw_state_rehearsal_group }}")
        self.assertEqual(module["mode"], "0750")

        names = [task.get("name") for task in self.tasks]
        self.assertLess(
            names.index("Create OpenClaw state rehearsal generation containers"),
            names.index("Create root-only OpenClaw state rehearsal generation"),
        )

    def test_workspace_is_staged_before_session_directories(self) -> None:
        names = [task.get("name") for task in self.tasks]
        stage = names.index("Stage retained data and modern OpenClaw workspace")
        ownership_gate = names.index(
            "Reject session references that cross workspace ownership classes"
        )
        session_directories = names.index(
            "Create session-referenced OpenClaw workspace directories"
        )
        self.assertLess(stage, ownership_gate)
        self.assertLess(ownership_gate, session_directories)

        gate = self._task(
            "Reject session references that cross workspace ownership classes"
        )
        assertions = gate["ansible.builtin.assert"]["that"]
        self.assertIn("item.stat.pw_name == 'root'", assertions[0])
        self.assertIn(
            "item.stat.pw_name == openclaw_state_rehearsal_user",
            assertions[0],
        )
        self.assertIn("item.stat.mode == '0750'", assertions[0])

    def test_generation_retention_precedes_new_generation_allocation(self) -> None:
        names = [task.get("name") for task in self.tasks]
        deploy = names.index("Deploy OpenClaw rehearsal generation retention helper")
        plan = names.index("Plan bounded OpenClaw state rehearsal generation retention")
        apply = names.index(
            "Apply bounded OpenClaw state rehearsal generation retention"
        )
        generation = names.index(
            "Create OpenClaw state rehearsal generation containers"
        )
        self.assertLess(deploy, plan)
        self.assertLess(plan, apply)
        self.assertLess(apply, generation)

        existing = self._task("Inspect existing OpenClaw state rehearsal managed paths")
        self.assertEqual(
            existing["loop"][-1], "{{ openclaw_state_rehearsal_retention_tool }}"
        )
        source = PLAYBOOK_PATH.read_text(encoding="utf-8")
        self.assertIn("openclaw-rehearsal-retention.py", source)
        self.assertIn("retention-plan.json", source)
        self.assertIn("retention-result.json", source)

    def test_only_session_state_is_recursively_frozen(self) -> None:
        freeze = self._task("Freeze validated OpenClaw rehearsal session generation")
        argv = freeze["ansible.builtin.command"]["argv"]
        self.assertIn("{{ openclaw_state_rehearsal_generation_state }}", argv)
        self.assertNotIn("{{ openclaw_state_rehearsal_generation_workspace }}", argv)


if __name__ == "__main__":
    unittest.main()
