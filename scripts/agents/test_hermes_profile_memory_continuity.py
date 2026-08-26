#!/usr/bin/env python3
"""Structural tests for isolated non-Astra Hermes memory activation."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]
PLAYBOOK = (ROOT / "playbooks/agents/hermes-profile-memory-continuity.yml").read_text()
VARS = yaml.safe_load(
    (ROOT / "inventory/group_vars/hermes_hosts/vars.yml").read_text()
)
HARDENING = (ROOT / "templates/hermes/hermes-gateway-hardening.conf.j2").read_text()
PARSED_PLAYBOOK = yaml.safe_load(PLAYBOOK)


class ProfileMemoryContinuityTests(unittest.TestCase):
    def test_rigel_and_dubble_have_isolated_stable_native_memory(self):
        rigel = next(
            profile
            for profile in VARS["hermes_shadow_profiles"]
            if profile["name"] == "rigel"
        )
        dubble = next(
            profile
            for profile in VARS["hermes_shadow_profiles"]
            if profile["name"] == "dubble"
        )
        self.assertEqual(rigel["context_engine"], "lcm")
        self.assertEqual(rigel["memory_provider"], "mem0")
        self.assertFalse(rigel["memory_write_approval"])
        self.assertIn("hermes-lcm", rigel["plugins_enabled"])
        self.assertEqual(dubble["context_engine"], "lcm")
        self.assertEqual(dubble["memory_provider"], "mem0")
        self.assertFalse(dubble["memory_write_approval"])
        self.assertIn("hermes-lcm", dubble["plugins_enabled"])

    def test_exact_source_and_profile_isolation_are_required(self):
        contract = VARS["hermes_profile_memory_continuity_profiles"]["rigel"]
        self.assertEqual(contract["expected_source_files"], 2995)
        self.assertEqual(contract["expected_eligible"], 22741)
        self.assertEqual(contract["expected_mem0_selected"], 111)
        self.assertEqual(contract["mem0_source_user_ids"], ["johnny:agent:rigel"])
        self.assertEqual(contract["mem0_target_collection"], "memories_hermes_rigel_v3")
        self.assertNotIn("johnny:agent:main", str(contract))
        self.assertNotIn("memories_hermes_astra", str(contract))

        dubble = VARS["hermes_profile_memory_continuity_profiles"]["dubble"]
        self.assertEqual(dubble["expected_source_files"], 3228)
        self.assertEqual(dubble["expected_selected_files"], 1)
        self.assertEqual(dubble["expected_eligible"], 11)
        self.assertTrue(dubble["mem0_empty_target"])
        self.assertEqual(dubble["mem0_source_user_ids"], [])
        self.assertEqual(dubble["expected_mem0_selected"], 0)
        self.assertEqual(dubble["mem0_target_collection"], "memories_hermes_dubble_v3")
        self.assertEqual(dubble["expected_privacy_classes"]["direct"], 0)
        self.assertEqual(dubble["expected_privacy_classes"]["other-channel"], 0)
        self.assertEqual(
            dubble["expected_privacy_classes"]["conflicting-route-evidence"], 0
        )

    def test_transaction_is_dry_run_first_and_rollback_protected(self):
        for required in (
            "Reject profile migration while OpenClaw can write source sessions",
            "Verify current profile managed-policy integrity",
            "Derive public-only profile LCM selection from retained route evidence",
            "Require exact public-only profile LCM selection boundary",
            "Dry-run canonical profile LCM import",
            "Require exact clean profile LCM import boundary",
            "Dry-run isolated profile Mem0 v3 migration",
            "Back up exact prior profile-memory files on local ext4",
            "Require hash-equal profile-memory rollback archive",
            "Apply canonical profile LCM import",
            "Apply isolated profile Mem0 v3 migration",
            "Hash isolated profile managed policy and environment",
            "Publish isolated profile managed-policy checksum",
            "Stop active profile Gateway through native planned lifecycle",
            "Validate profile Mem0 recall without exposing memory text",
            "Validate profile LCM database inventory",
            "Verify imported OpenClaw sources remained unchanged",
            "Remove newly created profile Mem0 collections",
            "Restore exact prior profile-memory files",
            "Restore prior profile Gateway availability",
            "Deploy isolated profile memory helpers",
            "hermes_astra_handoff_validator_live",
            "Inspect prior profile-memory runtime directories",
            "Remove newly created profile-memory runtime directories",
        ):
            self.assertIn(required, PLAYBOOK)
        self.assertLess(
            PLAYBOOK.index("Require hash-equal profile-memory rollback archive"),
            PLAYBOOK.index("Deploy isolated profile memory helpers"),
        )
        self.assertLess(
            PLAYBOOK.index("Deploy isolated profile memory helpers"),
            PLAYBOOK.index("Apply canonical profile LCM import"),
        )
        self.assertIn("rejectattr('item', 'equalto'", PLAYBOOK)
        self.assertIn("when: not (item.stat.exists | default(false))", PLAYBOOK)
        self.assertIn("managed-policy.sha256", PLAYBOOK)
        self.assertIn(
            ").tables.messages >= hermes_profile_memory_continuity_profile_contract.expected_eligible",
            PLAYBOOK,
        )
        self.assertNotIn(").counts.messages", PLAYBOOK)
        self.assertIn("gateway\n              - stop\n              - --system", PLAYBOOK)
        stop = PLAYBOOK.split(
            "Stop active profile Gateway through native planned lifecycle", 1
        )[1].split("Mark profile Gateway stopped", 1)[0]
        self.assertNotIn("runuser", stop)
        self.assertIn("HERMES_MANAGED_DIR", stop)
        self.assertIn("hermes_profile_memory_continuity_fastembed_cache", PLAYBOOK)
        self.assertNotIn("GEMINI_API_KEY", PLAYBOOK)
        self.assertNotIn("OPENAI_API_KEY", PLAYBOOK)
        self.assertIn("--include-manifest", PLAYBOOK)
        self.assertIn("--empty-target", PLAYBOOK)
        self.assertIn("hermes_profile_mem0_smoke_live", PLAYBOOK)
        self.assertIn("hermes_profile_memory_continuity_environment_file", PLAYBOOK)

    def test_memory_mounts_are_capability_driven(self):
        self.assertIn(
            "hermes_profile.memory_provider | default('') == 'mem0'",
            HARDENING,
        )
        self.assertIn(
            "hermes_profile.context_engine | default('') == 'lcm'",
            HARDENING,
        )
        self.assertIn("hermes_profile.home }}/lcm.db", HARDENING)
        self.assertIn("hermes_profile.home }}/mem0/fastembed-cache", HARDENING)

    def test_native_stop_environment_is_a_task_keyword(self):
        transaction = next(
            task
            for task in PARSED_PLAYBOOK[0]["tasks"]
            if task.get("name") == "Apply isolated profile-memory transaction"
        )
        stop = next(
            task
            for task in transaction["block"]
            if task.get("name")
            == "Stop active profile Gateway through native planned lifecycle"
        )
        self.assertIn("environment", stop)
        self.assertNotIn("environment", stop["ansible.builtin.command"])
        self.assertEqual(
            stop["ansible.builtin.command"]["argv"][-3:],
            ["gateway", "stop", "--system"],
        )


if __name__ == "__main__":
    unittest.main()
