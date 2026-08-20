#!/usr/bin/env python3
"""Static regressions for curated Hermes profile-memory staging."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]
CONTRACT = ROOT / "files" / "hermes" / "profile-memory-contract.json"
TEMPLATE = ROOT / "templates" / "hermes" / "hermes-managed-config.yaml.j2"
PLAYBOOK = ROOT / "playbooks" / "agents" / "hermes-profile-memory.yml"
VALIDATOR = ROOT / "scripts" / "agents" / "hermes-memory-seed-validate.py"
VARS = ROOT / "inventory" / "group_vars" / "hermes_hosts" / "vars.yml"


class HermesProfileMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def test_contract_is_curated_and_inert(self) -> None:
        self.assertEqual(self.contract["mode"], "curated-seed")
        self.assertTrue(self.contract["source"]["vaultEncrypted"])
        self.assertFalse(self.contract["source"]["rawLegacyMemoryCopied"])
        self.assertFalse(self.contract["source"]["rawSessionsCopied"])
        self.assertFalse(self.contract["source"]["rawTranscriptsCopied"])
        self.assertTrue(self.contract["execution"]["backupRequired"])
        self.assertTrue(self.contract["execution"]["transactionRollbackRequired"])
        for key, value in self.contract["execution"].items():
            if key not in {"backupRequired", "transactionRollbackRequired"}:
                self.assertFalse(value, key)

    def test_profiles_are_isolated_and_seed_names_are_bounded(self) -> None:
        expected = {
            "astra": (
                "hermes-astra",
                "/var/lib/hermes/astra/.hermes/profiles/astra",
                2,
            ),
            "dubble": (
                "hermes-dubble",
                "/var/lib/hermes/dubble/.hermes/profiles/dubble",
                0,
            ),
            "rigel": (
                "hermes-rigel",
                "/var/lib/hermes/rigel/.hermes/profiles/rigel",
                2,
            ),
        }
        self.assertEqual(set(self.contract["profiles"]), set(expected))
        self.assertTrue(self.contract["profiles"]["dubble"]["mustRemainEmpty"])
        sources = []
        for name, (user, home, count) in expected.items():
            profile = self.contract["profiles"][name]
            self.assertEqual(profile["user"], user)
            self.assertEqual(profile["group"], user)
            self.assertEqual(profile["home"], home)
            self.assertEqual(len(profile["seeds"]), count)
            for seed in profile["seeds"]:
                self.assertIn(seed["name"], {"MEMORY.md", "USER.md"})
                self.assertIn(seed["charLimit"], {1375, 2200})
                self.assertTrue(seed["source"].endswith(".vault"))
                sources.append(seed["source"])
        self.assertEqual(len(sources), len(set(sources)))

    def test_seed_sources_are_vault_ciphertext(self) -> None:
        for profile in self.contract["profiles"].values():
            for seed in profile["seeds"]:
                content = (ROOT / seed["source"]).read_text(encoding="utf-8")
                self.assertTrue(content.startswith("$ANSIBLE_VAULT;1.1;AES256\n"))
                self.assertNotIn("Johnny", content)
                self.assertNotIn("OpenClaw", content)

    def test_template_uses_documented_compact_limits_and_approval(self) -> None:
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("memory_char_limit: 2200", template)
        self.assertIn("user_char_limit: 1375", template)
        self.assertIn("write_approval: true", template)
        self.assertNotIn("memory_char_limit: 4000", template)
        self.assertNotIn("user_char_limit: 2500", template)

    def test_playbook_is_disabled_transactional_and_does_not_start_gateway(self) -> None:
        variables = yaml.safe_load(VARS.read_text(encoding="utf-8"))
        playbook = PLAYBOOK.read_text(encoding="utf-8")
        self.assertEqual(variables["hermes_profile_memory_mode"], "disabled")
        self.assertFalse(variables["hermes_profile_memory_approved"])
        self.assertIn("Require every Hermes gateway stopped", playbook)
        self.assertIn("Back up current Hermes memory stores", playbook)
        self.assertIn("Restore Hermes memory stores after staging failure", playbook)
        self.assertIn("Validate decrypted Hermes memory seeds", playbook)
        self.assertIn("Require Dubble memory to remain empty", playbook)
        self.assertIn("Require identical staged and installed Hermes memory", playbook)
        self.assertIn("Require unchanged production user services", playbook)
        self.assertIn("openclaw-gateway.service", playbook)
        self.assertIn("health-receiver.service", playbook)
        self.assertGreaterEqual(playbook.count("check_mode: false"), 4)
        self.assertIn("/usr/sbin/runuser", playbook)
        self.assertNotIn("become_user:", playbook)
        self.assertNotIn("state: started", playbook)
        self.assertNotIn("state: restarted", playbook)
        self.assertNotIn("hermes gateway", playbook)

    def test_validator_uses_native_scanner_and_rejects_unsafe_shape(self) -> None:
        script = VALIDATOR.read_text(encoding="utf-8")
        self.assertIn("_scan_memory_content", script)
        self.assertIn("MemoryStore._parse_entries", script)
        self.assertIn("seed-roundtrip-drift", script)
        self.assertIn("seed-over-character-limit", script)
        self.assertIn("seed-threat-pattern", script)
        self.assertIn("stat.S_ISLNK", script)


if __name__ == "__main__":
    unittest.main()
