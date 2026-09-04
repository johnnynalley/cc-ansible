#!/usr/bin/env python3
"""Static regressions for reviewed Hermes-native profile skills."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml


ROOT = Path(__file__).parents[2]
CONTRACT = ROOT / "files" / "hermes" / "profile-skills-contract.json"
MIGRATION_POLICY = ROOT / "files" / "openclaw" / "workspace-migration-policy.json"
PLAYBOOK = ROOT / "playbooks" / "agents" / "hermes-profile-skills.yml"
VALIDATOR = ROOT / "scripts" / "agents" / "hermes-profile-skills-validate.py"
VARS = ROOT / "inventory" / "group_vars" / "hermes_hosts" / "vars.yml"
SPEC = importlib.util.spec_from_file_location("hermes_profile_skills", VALIDATOR)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def parse_frontmatter(content: str) -> tuple[dict, str]:
    if not content.startswith("---\n"):
        raise AssertionError("frontmatter must start at byte zero")
    _, raw, body = content.split("---", 2)
    return yaml.safe_load(raw), body


class HermesProfileSkillsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def test_contract_replaces_legacy_skills_with_inert_native_content(self) -> None:
        self.assertEqual(self.contract["mode"], "reviewed-native-parity")
        self.assertTrue(self.contract["source"]["rootReviewed"])
        self.assertTrue(self.contract["source"]["declarativeMarkdownOnly"])
        for key in (
            "rawLegacySkillsCopied",
            "legacyExecutablesCopied",
            "rawSessionsCopied",
            "rawTranscriptsCopied",
            "phraseTriggerTablesAllowed",
        ):
            self.assertFalse(self.contract["source"][key], key)
        self.assertTrue(self.contract["execution"]["backupRequired"])
        self.assertTrue(self.contract["execution"]["transactionRollbackRequired"])
        self.assertTrue(
            self.contract["execution"]["nativeProfileOwnershipRequired"]
        )
        self.assertFalse(self.contract["execution"]["managedProjectionActive"])
        self.assertEqual(
            self.contract["nativeOwnership"],
            {
                "canonicalSharedSkill": "self-evolution",
                "writerProfile": "astra",
                "readOnlyProfiles": ["dubble", "rigel"],
            },
        )
        for key, value in self.contract["execution"].items():
            if key not in {
                "backupRequired",
                "transactionRollbackRequired",
                "nativeProfileOwnershipRequired",
            }:
                self.assertFalse(value, key)

        policy = json.loads(MIGRATION_POLICY.read_text(encoding="utf-8"))
        rules = {rule["id"]: rule for rule in policy["rules"]}
        self.assertEqual(rules["legacy-skills"]["disposition"], "replace")
        self.assertEqual(rules["legacy-shared-skills"]["disposition"], "replace")

    def test_skill_inventory_is_profile_isolated_and_exact(self) -> None:
        expected = {
            "astra": {
                "caldav-calendar",
                "clawhub",
                "compute-corner-administration",
                "evidence-led-investigation",
                "consequential-recommendation",
                "daily-summary-thread",
                "diagram-maker",
                "discord",
                "financial-decision-support",
                "guided-operation",
                "guided-software-walkthrough",
                "hardware-inventory",
                "hardware-planning",
                "healthcheck",
                "himalaya",
                "immich-media-inbox",
                "job-application-tracker",
                "live-task-ledger",
                "lossless-claw",
                "meme-maker",
                "node-connect",
                "node-inspect-debugger",
                "operational-heartbeat",
                "price-lookup",
                "python-debugpy",
                "self-evolution",
                "skill-creator",
                "sober-tracker",
                "source-grounded-study",
                "spike",
                "taskflow",
                "taskflow-inbox-triage",
                "tmux",
                "weather",
                "fortnite-tracker",
            },
            "dubble": {"public-support-triage", "self-evolution"},
            "rigel": {"academic", "self-evolution"},
        }
        self.assertEqual(set(self.contract["profiles"]), set(expected))
        all_sources: list[str] = []
        for profile_name, names in expected.items():
            profile = self.contract["profiles"][profile_name]
            self.assertEqual(profile["user"], f"hermes-{profile_name}")
            self.assertEqual(profile["group"], f"hermes-{profile_name}")
            self.assertEqual(
                profile["home"],
                f"/var/lib/hermes/{profile_name}/.hermes/profiles/{profile_name}",
            )
            self.assertNotIn("managedRoot", profile)
            self.assertNotIn("runtimeRoot", profile)
            self.assertEqual(
                profile["nativeRoot"],
                f"/var/lib/hermes/{profile_name}/.hermes/profiles/"
                f"{profile_name}/skills",
            )
            self.assertEqual({skill["name"] for skill in profile["skills"]}, names)
            all_sources.extend(skill["source"] for skill in profile["skills"])
        self.assertEqual(len(all_sources), 39)
        self.assertEqual(len(set(all_sources)), 37)
        playbook = PLAYBOOK.read_text(encoding="utf-8")
        self.assertIn("hermes_native_skill_inventory | length == 39", playbook)
        self.assertIn("hermes_native_skill_support_inventory | length == 13", playbook)
        self.assertIn("profiles.astra.skills | length == 35", playbook)

    def test_compute_corner_skill_routes_to_existing_native_boundaries(self) -> None:
        content = (
            ROOT
            / "files/hermes/profile-skills/astra/compute-corner-administration/SKILL.md"
        ).read_text(encoding="utf-8")
        for tool_name in (
            "docker_inventory",
            "docker_update",
            "compose_hosts",
            "compose_request",
            "host_admin_hosts",
            "host_admin_request",
            "arr_services",
            "arr_api_request",
            "skill_manage",
            "cronjob",
        ):
            self.assertIn(f"`{tool_name}`", content)
        self.assertIn("Astra is its sole writer", content)
        self.assertIn("Dubble and Rigel may send bounded proposals", content)
        self.assertNotIn("Docker group", content)
        self.assertIn("Existing typed tools enforce authority", content)
        self.assertIn("Do not replace them", content)

    def test_each_skill_is_hashed_declarative_and_semantically_described(self) -> None:
        source_root = ROOT / "files" / "hermes" / "profile-skills"
        expected_paths: set[Path] = set()
        for profile_name, profile in self.contract["profiles"].items():
            profile_names = {skill["name"] for skill in profile["skills"]}
            for skill in profile["skills"]:
                path = ROOT / skill["source"]
                expected_paths.add(path.resolve())
                content = path.read_text(encoding="utf-8")
                frontmatter, body = parse_frontmatter(content)
                self.assertEqual(frontmatter["name"], skill["name"])
                self.assertEqual(frontmatter["description"], skill["description"])
                self.assertLessEqual(
                    len(skill["description"]),
                    self.contract["validation"]["descriptionPromptLimit"],
                )
                self.assertRegex(skill["description"], r"^Use (when|for) ")
                self.assertNotIn("keyword", skill["description"].lower())
                self.assertNotIn("phrase", skill["description"].lower())
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertEqual(digest, skill["sha256"])
                self.assertTrue(body.strip())
                for forbidden in (
                    "allowed-tools",
                    "required_environment_variables",
                    "required_credential_files",
                    "blueprint:",
                    "!`",
                ):
                    self.assertNotIn(forbidden, content)
                self.assertNotRegex(
                    content,
                    r"\d{1,3}(?:\.\d{1,3}){3}:\d{2,5}",
                )
                if skill["name"] == "operational-heartbeat":
                    self.assertIn("managed bootstrap contract", content)
                    self.assertIn("Never call `execute_code`", content)
                    self.assertIn(
                        "## Scheduled Final Response Contract", content
                    )
                    self.assertIn(
                        "final response is exactly `[SILENT]`", content
                    )
                    self.assertNotRegex(
                        content,
                        r"AGENTS\.md|CLAUDE\.md|\.cursorrules|\.clinerules",
                    )
                else:
                    self.assertNotRegex(
                        content,
                        r"AGENTS\.md|CLAUDE\.md|\.cursorrules|\.clinerules",
                    )
                if skill["name"] == "self-evolution":
                    normalized_content = " ".join(content.split())
                    self.assertIn("## Unattended Maintenance Contract", content)
                    self.assertIn("## Native Layout And Bounded Probes", content)
                    self.assertIn("memories/USER.md", content)
                    self.assertIn("memories/MEMORY.md", content)
                    self.assertIn('git -c safe.directory="$PWD"', content)
                    self.assertIn("Do not assume the `sqlite3` CLI", content)
                    self.assertIn(
                        "Never recursively search the profile root",
                        normalized_content,
                    )
                    for forbidden_root in (
                        "`managed-data`",
                        "`imported-data`",
                        "`legacy-openclaw`",
                    ):
                        self.assertIn(forbidden_root, content)
                    self.assertIn(
                        "--maintenance-lease acquire --lease-owner self-evolution",
                        content,
                    )
                    self.assertIn(
                        "Never request interactive command",
                        " ".join(content.split()),
                    )
                    self.assertIn("return only `[SILENT]`", content)
                related = (
                    frontmatter.get("metadata", {})
                    .get("hermes", {})
                    .get("related_skills", [])
                )
                self.assertTrue(set(related).issubset(profile_names))
                for support in skill.get("supportingFiles", []):
                    support_path = path.parent / support["path"]
                    expected_paths.add(support_path.resolve())
                    self.assertTrue(support_path.is_file())
                    self.assertFalse(support_path.is_symlink())
                    self.assertIn(
                        support_path.suffix,
                        self.contract["validation"]["supportingFileSuffixes"],
                    )
                    self.assertEqual(
                        hashlib.sha256(support_path.read_bytes()).hexdigest(),
                        support["sha256"],
                    )

        actual_paths = {
            path.resolve() for path in source_root.rglob("*") if path.is_file()
        }
        self.assertEqual(actual_paths, expected_paths)

    def test_runtime_uses_native_skill_root_in_gateway_and_cron_contexts(self) -> None:
        variables = yaml.safe_load(VARS.read_text(encoding="utf-8"))
        self.assertEqual(
            variables["hermes_shared_self_evolution_source"],
            "/var/lib/hermes/astra/.hermes/profiles/astra/skills/self-evolution",
        )
        unit = (
            ROOT / "templates" / "hermes" / "hermes-gateway-hardening.conf.j2"
        ).read_text(encoding="utf-8")
        self.assertNotIn("/skills/managed", unit)
        self.assertNotIn("managed-policy.sha256", unit)
        self.assertIn("hermes_shared_self_evolution_source", unit)
        self.assertIn("hermes_profile.name in ['dubble', 'rigel']", unit)
        validator = VALIDATOR.read_text(encoding="utf-8")
        self.assertIn('"native"', validator)
        self.assertIn('"plan-native"', validator)
        self.assertIn('profile["nativeRoot"]', validator)
        self.assertIn(
            'args.mode in {"native", "plan-native"}',
            validator,
        )

    def test_playbook_is_one_time_native_transaction_without_projection_restore(self) -> None:
        variables = yaml.safe_load(VARS.read_text(encoding="utf-8"))
        playbook = PLAYBOOK.read_text(encoding="utf-8")
        self.assertEqual(variables["hermes_profile_skills_mode"], "disabled")
        self.assertFalse(variables["hermes_profile_skills_approved"])
        self.assertIn("['disabled', 'import-native']", playbook)
        self.assertIn("hermes_profile_skills_approved | bool", playbook)
        self.assertNotIn("Audit retained profile skills", playbook)
        self.assertNotIn("Restore managed Hermes profile skills", playbook)
        self.assertNotIn("managedRoot", playbook)
        self.assertNotIn("runtimeRoot", playbook)
        self.assertIn("UnitFileState=enabled", playbook)
        self.assertIn("systemctl\n              - cat", playbook)
        self.assertIn("Validate reviewed skill source and native import boundary", playbook)
        self.assertIn("/usr/sbin/runuser", playbook)
        self.assertIn("owner: root", playbook)
        self.assertGreaterEqual(playbook.count("check_mode: false"), 4)
        self.assertNotIn("become_user:", playbook)
        self.assertNotIn("state: started", playbook)
        self.assertIn("Back up complete native skill state off-host", playbook)
        self.assertIn("Stop native skill import before mutation in check mode", playbook)
        self.assertIn("Import reviewed skills into profile-owned native roots", playbook)
        self.assertIn("Restart each native skill consumer exactly once", playbook)
        self.assertIn("Prove Astra can revise the canonical shared skill", playbook)
        self.assertIn("Prove reader profiles cannot revise the shared skill", playbook)
        self.assertIn("Restore complete native profile skill trees", playbook)
        self.assertIn("Restore pre-import native skill validator", playbook)
        self.assertIn("Install native bootstrap parity contract", playbook)
        self.assertIn("Restore pre-import bootstrap parity contract", playbook)
        self.assertIn("Wait for restored Gateways to reach readiness", playbook)
        self.assertIn("Validate restored skills through native service namespaces", playbook)
        self.assertIn("hermes_runtime_readers_group", playbook)
        self.assertNotIn("hermes gateway", playbook)

    def test_validator_uses_native_frontmatter_and_threat_scanner(self) -> None:
        script = VALIDATOR.read_text(encoding="utf-8")
        self.assertIn("parse_frontmatter", script)
        self.assertIn("_validate_frontmatter", script)
        self.assertIn("scan_skill", script)
        self.assertIn("skill-native-scan-failed", script)
        self.assertIn("skill-hash-drift", script)
        self.assertIn("native-skill-index-missing", script)
        self.assertIn("native-skill-view-failed", script)
        self.assertIn("skill_view(skill[\"name\"]", script)
        self.assertIn('"native"', script)
        self.assertNotIn('profile["managedRoot"]', script)
        self.assertNotIn('profile["runtimeRoot"]', script)
        self.assertIn("stat.S_ISLNK", script)
        self.assertIn("skill-supporting-file-hash-drift", script)
        self.assertIn("skill-tree-inventory-drift", script)
        self.assertIn("shared-mount-not-empty", script)
        self.assertIn("nativeMetadataEntries", script)
        self.assertIn("native-metadata-entry-invalid", script)
        self.assertIn("unrelatedSkillDirectories", script)
        self.assertIn("--allow-unmounted-shared-readers", script)
        automation = (
            ROOT / "playbooks" / "agents" / "hermes-automation.yml"
        ).read_text(encoding="utf-8")
        self.assertNotIn(
            "Verify profile-owned native skills before Gateway restart",
            automation,
        )
        self.assertNotIn("- --mode\n              - installed", automation)
        profile_skills = PLAYBOOK.read_text(encoding="utf-8")
        self.assertIn("'--mode', 'native', '--profile'", profile_skills)

    def test_native_validation_allows_safe_agent_owned_content_evolution(self) -> None:
        content = "---\nname: example\ndescription: Evolved safely.\n---\n\nBody.\n"
        skill = {
            "name": "example",
            "description": "Original baseline.",
            "sha256": "0" * 64,
        }
        scanner = lambda *_args, **_kwargs: SimpleNamespace(
            verdict="safe", findings=[]
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "example" / "SKILL.md"
            path.parent.mkdir()
            path.write_text(content, encoding="utf-8")
            MODULE.validate_skill(
                path,
                "astra",
                skill,
                parse_frontmatter,
                lambda *_args, **_kwargs: None,
                scanner,
                120,
                False,
            )
            with self.assertRaisesRegex(SystemExit, "skill-hash-drift"):
                MODULE.validate_skill(
                    path,
                    "astra",
                    skill,
                    parse_frontmatter,
                    lambda *_args, **_kwargs: None,
                    scanner,
                    120,
                    True,
                )

    def test_unmounted_shared_reader_target_must_exist_and_remain_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "self-evolution"
            target.mkdir()
            MODULE.validate_unmounted_shared_reader_target(
                target, "dubble", "self-evolution"
            )
            (target / "SKILL.md").write_text("unexpected", encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "shared-mount-not-empty"):
                MODULE.validate_unmounted_shared_reader_target(
                    target, "dubble", "self-evolution"
                )


if __name__ == "__main__":
    unittest.main()
