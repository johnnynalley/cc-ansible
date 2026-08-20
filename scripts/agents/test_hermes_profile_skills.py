#!/usr/bin/env python3
"""Static regressions for reviewed Hermes-native profile skills."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]
CONTRACT = ROOT / "files" / "hermes" / "profile-skills-contract.json"
MIGRATION_POLICY = ROOT / "files" / "openclaw" / "workspace-migration-policy.json"
PLAYBOOK = ROOT / "playbooks" / "agents" / "hermes-profile-skills.yml"
TEMPLATE = ROOT / "templates" / "hermes" / "hermes-managed-config.yaml.j2"
VALIDATOR = ROOT / "scripts" / "agents" / "hermes-profile-skills-validate.py"
VARS = ROOT / "inventory" / "group_vars" / "hermes_hosts" / "vars.yml"


def parse_frontmatter(content: str) -> tuple[dict, str]:
    if not content.startswith("---\n"):
        raise AssertionError("frontmatter must start at byte zero")
    _, raw, body = content.split("---", 2)
    return yaml.safe_load(raw), body


class HermesProfileSkillsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def test_contract_replaces_legacy_skills_with_inert_native_content(self) -> None:
        self.assertEqual(self.contract["mode"], "reviewed-native-seed")
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
        self.assertTrue(self.contract["execution"]["managedRootExclusive"])
        for key, value in self.contract["execution"].items():
            if key not in {
                "backupRequired",
                "transactionRollbackRequired",
                "managedRootExclusive",
            }:
                self.assertFalse(value, key)

        policy = json.loads(MIGRATION_POLICY.read_text(encoding="utf-8"))
        rules = {rule["id"]: rule for rule in policy["rules"]}
        self.assertEqual(rules["legacy-skills"]["disposition"], "replace")
        self.assertEqual(rules["legacy-shared-skills"]["disposition"], "replace")

    def test_skill_inventory_is_profile_isolated_and_exact(self) -> None:
        expected = {
            "astra": {
                "evidence-led-investigation",
                "consequential-recommendation",
                "guided-operation",
                "source-grounded-study",
                "fortnite-tracker",
            },
            "dubble": {"public-support-triage"},
            "rigel": {"source-grounded-study"},
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
            self.assertEqual(
                profile["managedRoot"], f"/etc/hermes/{profile_name}/skills"
            )
            self.assertEqual(
                profile["runtimeRoot"],
                f"/var/lib/hermes/{profile_name}/.hermes/profiles/"
                f"{profile_name}/skills/managed",
            )
            self.assertEqual({skill["name"] for skill in profile["skills"]}, names)
            all_sources.extend(skill["source"] for skill in profile["skills"])
        self.assertEqual(len(all_sources), 7)
        self.assertEqual(len(set(all_sources)), 7)
        playbook = PLAYBOOK.read_text(encoding="utf-8")
        self.assertIn("hermes_profile_skills_inventory | length == 7", playbook)
        self.assertIn("'fortnite-tracker'", playbook)
        self.assertNotIn("hermes_profile_skills_inventory | length == 5", playbook)

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
                related = (
                    frontmatter.get("metadata", {})
                    .get("hermes", {})
                    .get("related_skills", [])
                )
                self.assertTrue(set(related).issubset(profile_names))

        actual_paths = {
            path.resolve() for path in source_root.rglob("*") if path.is_file()
        }
        self.assertEqual(actual_paths, expected_paths)

    def test_runtime_uses_native_skill_root_with_root_owned_read_only_bind(self) -> None:
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("guard_agent_created: true", template)
        self.assertIn("write_approval: true", template)
        self.assertNotIn("external_dirs:", template)
        unit = (
            ROOT / "templates" / "hermes" / "hermes-gateway-hardening.conf.j2"
        ).read_text(encoding="utf-8")
        self.assertIn("BindReadOnlyPaths=/etc/hermes/", unit)
        self.assertIn("/skills/managed", unit)
        self.assertIn("--mode runtime --profile", unit)

    def test_playbook_is_disabled_transactional_and_does_not_start_gateway(self) -> None:
        variables = yaml.safe_load(VARS.read_text(encoding="utf-8"))
        playbook = PLAYBOOK.read_text(encoding="utf-8")
        self.assertEqual(variables["hermes_profile_skills_mode"], "disabled")
        self.assertFalse(variables["hermes_profile_skills_approved"])
        self.assertIn("Require every Hermes gateway stopped", playbook)
        self.assertIn("UnitFileState=enabled", playbook)
        self.assertIn("systemctl\n              - cat", playbook)
        self.assertIn("Back up current managed Hermes profile skills", playbook)
        self.assertIn("Restore managed Hermes profile skills", playbook)
        self.assertIn("Validate reviewed source skills with Hermes native parsers", playbook)
        self.assertIn("Validate each managed skill root as its Hermes service identity", playbook)
        self.assertIn("Require native read-only skill bindings and startup validation", playbook)
        self.assertIn("Stop current Hermes profile-skills transaction before mutation", playbook)
        self.assertIn("Require unchanged production user services", playbook)
        self.assertIn("openclaw-gateway.service", playbook)
        self.assertIn("health-receiver.service", playbook)
        self.assertIn("/usr/sbin/runuser", playbook)
        self.assertIn("owner: root", playbook)
        self.assertIn('mode: "0440"', playbook)
        self.assertGreaterEqual(playbook.count("check_mode: false"), 4)
        self.assertNotIn("become_user:", playbook)
        self.assertNotIn("state: started", playbook)
        self.assertNotIn("state: restarted", playbook)
        self.assertNotIn("hermes gateway", playbook)

    def test_validator_uses_native_frontmatter_and_threat_scanner(self) -> None:
        script = VALIDATOR.read_text(encoding="utf-8")
        self.assertIn("parse_frontmatter", script)
        self.assertIn("_validate_frontmatter", script)
        self.assertIn("scan_skill", script)
        self.assertIn("skill-native-scan-failed", script)
        self.assertIn("skill-hash-drift", script)
        self.assertIn("skill-root-inventory-drift", script)
        self.assertIn("native-skill-index-missing", script)
        self.assertIn("stat.S_ISLNK", script)


if __name__ == "__main__":
    unittest.main()
