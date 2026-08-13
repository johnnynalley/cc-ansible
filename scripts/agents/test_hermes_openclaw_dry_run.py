#!/usr/bin/env python3
"""Regression tests for the protected Hermes OpenClaw importer inventory."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "agents" / "hermes-openclaw-dry-run.py"
CONTRACT = ROOT / "files" / "hermes" / "openclaw-dry-run-contract.json"
PLAYBOOK = ROOT / "playbooks" / "agents" / "hermes-openclaw-dry-run.yml"
VARS = ROOT / "inventory" / "group_vars" / "hermes_hosts" / "vars.yml"

SPEC = importlib.util.spec_from_file_location("hermes_openclaw_dry_run", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HermesOpenClawDryRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.workspace = self.source / "workspace"
        self.workspace.mkdir(parents=True)
        self.target_config = self.root / "astra-config.yaml"
        self.target_config.write_text(
            yaml.safe_dump({"_config_version": 33, "approvals": {"mode": "manual"}}),
            encoding="utf-8",
        )
        (self.source / "openclaw.json").write_text(
            json.dumps(
                {
                    "env": {"OPENAI_API_KEY": "raw-secret-key"},
                    "channels": {"discord": {"token": "raw-discord-token"}},
                    "agents": {
                        "defaults": {
                            "workspace": "/home/johnny/.openclaw/workspace",
                            "thinkingDefault": "adaptive",
                            "timeoutSeconds": 120,
                            "compaction": {"mode": "auto", "model": "secret-model-route"},
                        },
                        "list": [{"id": "astra"}, {"id": "rigel"}],
                    },
                    "bindings": [{"channel": "private-channel-id"}],
                    "cron": {"jobs": [{"prompt": "raw cron prompt"}]},
                    "session": {"reset": {"mode": "daily", "atHour": 4}},
                    "tools": {"exec": {"timeoutSec": 30}, "web": {"apiKey": "raw-web-key"}},
                    "approvals": {"exec": {"mode": "manual"}, "rules": ["raw-rule"]},
                    "memory": {"backend": "qmd", "path": "/private/path"},
                    "skills": {"entries": {"private-skill-name": {"env": "raw-skill-secret"}}},
                    "ui": {"identity": "private-identity"},
                    "logging": {"path": "/private/log"},
                }
            ),
            encoding="utf-8",
        )
        (self.source / "exec-approvals.json").write_text(
            json.dumps(
                {
                    "agents": {
                        "main": {
                            "allowlist": [
                                {"pattern": "sudo raw-secret-command"},
                                {"pattern": "sudo raw-secret-command"},
                            ]
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        (self.workspace / "SOUL.md").write_text("raw soul prompt injection", encoding="utf-8")
        (self.workspace / "MEMORY.md").write_text("raw private memory", encoding="utf-8")
        (self.workspace / "memory").mkdir()
        (self.workspace / "memory" / "2026-08-13.md").write_text("raw daily memory", encoding="utf-8")
        skill = self.workspace / "skills" / "dangerous-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("run destructive raw command", encoding="utf-8")
        (skill / "payload.sh").write_text("#!/bin/sh\nraw-secret-command\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def local_ownership(path: Path, uid: int, gid: int, mode: int) -> None:
        del uid, gid
        os.chmod(path, mode, follow_symlinks=False)

    def test_real_contract_is_inert_and_shape_only(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        MODULE.validate_contract(contract)
        self.assertEqual(contract["selectedOptions"], sorted(contract["selectedOptions"]))
        self.assertFalse(set(contract["selectedOptions"]) & set(contract["forbiddenOptions"]))
        self.assertFalse(any(contract["sourceShape"].values()))
        self.assertFalse(any(contract["execution"].values()))
        self.assertEqual(contract["runtime"]["python"], "/usr/local/lib/hermes-agent/venv/bin/python")
        self.assertRegex(contract["runtime"]["pythonResolvedSha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(contract["runtime"]["venvConfigSha256"], r"^[0-9a-f]{64}$")

    def test_shape_view_contains_no_raw_source_values_or_code(self) -> None:
        generation = self.root / "generation"
        generation.mkdir()
        with mock.patch.object(MODULE, "ensure_owned", self.local_ownership):
            source_view, target_view, summary = MODULE.stage_shape_view(
                self.source,
                self.workspace,
                self.target_config,
                generation,
                os.getgid(),
            )
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(generation.rglob("*"))
            if path.is_file()
        )
        for forbidden in (
            "raw-secret-key",
            "raw-discord-token",
            "raw cron prompt",
            "raw private memory",
            "raw daily memory",
            "raw soul prompt injection",
            "raw-secret-command",
            "private-channel-id",
            "private-identity",
            "private-skill-name",
        ):
            self.assertNotIn(forbidden, combined)
        self.assertFalse((source_view / "workspace" / "skills" / "skill-0001" / "payload.sh").exists())
        shaped = json.loads((source_view / "openclaw.json").read_text(encoding="utf-8"))
        self.assertEqual(shaped["agents"]["defaults"]["workspace"], str(source_view / "workspace"))
        self.assertNotIn("env", shaped)
        self.assertNotIn("channels", shaped)
        self.assertEqual(len(shaped["agents"]["list"]), 2)
        self.assertEqual(summary["legacyAllowlistPatternCount"], 1)
        self.assertTrue((target_view / "config.yaml").is_file())

    def test_source_symlink_is_rejected(self) -> None:
        (self.workspace / "SOUL.md").unlink()
        (self.workspace / "SOUL.md").symlink_to(self.target_config)
        with self.assertRaisesRegex(MODULE.DryRunError, "regular file"):
            MODULE.collect_source_objects(self.source, self.workspace)

    def test_skill_symlinks_become_anonymous_placeholders_without_target_reads(self) -> None:
        shared = self.source / "skills"
        shared.mkdir()
        internal_target = self.workspace / "skills" / "dangerous-skill"
        external_target = self.root / "external-private-skill"
        external_target.mkdir()
        (external_target / "SKILL.md").write_text("external raw secret", encoding="utf-8")
        (shared / "internal-private-name").symlink_to(internal_target)
        (shared / "external-private-name").symlink_to(external_target)

        generation = self.root / "generation-links"
        generation.mkdir()
        with mock.patch.object(MODULE, "ensure_owned", self.local_ownership):
            source_view, _, summary = MODULE.stage_shape_view(
                self.source,
                self.workspace,
                self.target_config,
                generation,
                os.getgid(),
            )

        rendered = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(generation.rglob("*"))
            if path.is_file()
        )
        self.assertEqual(summary["representedSkillSymlinkCount"], 2)
        self.assertFalse(summary["symlinkTargetsRead"])
        self.assertEqual(summary["stagedSkillPlaceholderCounts"]["shared-skills"], 2)
        self.assertTrue((source_view / "skills" / "skill-0001" / "SKILL.md").is_file())
        self.assertTrue((source_view / "skills" / "skill-0002" / "SKILL.md").is_file())
        self.assertNotIn("external raw secret", rendered)
        self.assertNotIn("internal-private-name", rendered)
        self.assertNotIn("external-private-name", rendered)
        self.assertFalse(any(path.is_symlink() for path in generation.rglob("*")))

    def test_structural_report_discards_details_and_values(self) -> None:
        selected = ["memory", "skills"]
        report = {
            "mode": "dry-run",
            "migrate_secrets": "[redacted]",
            "output_dir": None,
            "workspace_target": None,
            "selection": {"selected": selected},
            "items": [
                {
                    "kind": "memory",
                    "status": "migrated",
                    "source": "/private/source/MEMORY.md",
                    "destination": "/private/target/MEMORY.md",
                    "reason": "Would merge raw private memory",
                    "details": {"overflow_preview": ["raw private memory"]},
                },
                {"kind": "skills", "status": "skipped", "details": {}},
                {"kind": "provider-keys", "status": "archived", "details": {}},
            ],
        }
        structural = MODULE.structural_report(report, selected)
        rendered = json.dumps(structural)
        self.assertEqual(structural["summary"], {"archived": 1, "migrated": 1, "skipped": 1})
        self.assertFalse(structural["secretMigrationArgumentPassed"])
        self.assertFalse(structural["forbiddenOptionsSelected"])
        self.assertEqual(structural["kinds"]["provider-keys"], {"archived": 1})
        self.assertNotIn("private", rendered)
        self.assertNotIn("source", rendered)
        self.assertNotIn("details", rendered)

    def test_unsafe_contract_is_rejected(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract["execution"]["migrateSecretsAllowed"] = True
        with self.assertRaisesRegex(MODULE.DryRunError, "authorizes mutation"):
            MODULE.validate_contract(contract)

    def test_playbook_is_disabled_and_never_passes_mutation_flags(self) -> None:
        variables = yaml.safe_load(VARS.read_text(encoding="utf-8"))
        playbook = PLAYBOOK.read_text(encoding="utf-8")
        self.assertEqual(variables["hermes_openclaw_dry_run_mode"], "disabled")
        self.assertFalse(variables["hermes_openclaw_dry_run_approved"])
        self.assertIn("shape-only Hermes OpenClaw importer inventory", playbook)
        self.assertIn("Require every Hermes gateway stopped", playbook)
        self.assertIn("Require unchanged services", playbook)
        self.assertNotIn("--execute", playbook)
        self.assertNotIn("--migrate-secrets", playbook)
        self.assertNotIn("hermes claw cleanup", playbook)

    def test_importer_command_has_network_and_write_confinement(self) -> None:
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("PrivateNetwork=yes", script)
        self.assertIn("ProtectSystem=strict", script)
        self.assertIn("ProtectHome=yes", script)
        self.assertIn("CapabilityBoundingSet=", script)
        self.assertIn("ReadOnlyPaths=", script)
        self.assertIn("InaccessiblePaths=/var/lib/hermes/astra", script)
        self.assertIn('"--json"', script)
        self.assertIn('"--include"', script)
        self.assertIn('"--execute"', script)
        self.assertIn("forbidden_arguments", script)
        self.assertIn("require_pinned_venv_python(runtime)", script)
        self.assertIn("ensure_owned(work_root, 0, executor_gid, 0o710)", script)
        self.assertIn("ensure_owned(evidence_root, 0, 0, 0o700)", script)


if __name__ == "__main__":
    unittest.main()
