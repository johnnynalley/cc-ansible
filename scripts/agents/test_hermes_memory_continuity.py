#!/usr/bin/env python3
"""Structural acceptance tests for Astra memory continuity."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml
from jinja2 import Template


ROOT = Path(__file__).parents[2]


class HermesMemoryContinuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.playbook = (
            ROOT / "playbooks/agents/hermes-memory-continuity.yml"
        ).read_text()
        self.variables = yaml.safe_load(
            (ROOT / "inventory/group_vars/hermes_hosts/vars.yml").read_text()
        )

    def test_transaction_has_native_lifecycle_backup_and_rollback_gates(self) -> None:
        for required in (
            "Require exact Astra memory-continuity authorization",
            "Require official native Hermes lifecycle units",
            "Reject memory migration while OpenClaw can write source state",
            "Create consistent OpenClaw LCM source backup",
            "Create consistent OpenClaw Mem0 history backup",
            "Create native Astra profile backup before memory conversion",
            "Create native backup in Astra-owned storage",
            "Move Astra profile backup into root-private rollback storage",
            "Prepare service-owned markers for memory conversion stops",
            "Stop native production Gateways once for shared runtime conversion",
            "Reject orphaned LCM externalized-output state",
            "Dry-run OpenClaw LCM conversion",
            "Apply idempotent OpenClaw LCM conversion",
            "Secure imported Hermes LCM externalized outputs",
            "Dry-run Astra-only Mem0 vector conversion",
            "Apply source-preserving Astra Mem0 vector conversion",
            "Install supported Mem0 Gemini provider dependency",
            "Validate Mem0 Gemini provider dependency before conversion",
            "Validate Hermes Python package compatibility before conversion",
            "Deploy current memory-dependent Hermes policy graph",
            "Validate deployed Hermes target policy",
            "Validate deployed Hermes Discord policy graph",
            "Validate deployed Hermes automation policy graph",
            "Validate Astra Mem0 provider recall without exposing results",
            "Remove newly created Mem0 target after failed conversion",
            "Record failed memory-conversion task privately",
            "Remove failed LCM externalized-output tree",
            "Restore prior LCM externalized-output tree",
            "Fail after restoring pre-conversion memory state",
        ):
            self.assertIn(required, self.playbook)
        self.assertIn("gateway\n          - stop\n          - --system", self.playbook)
        self.assertIn("gateway\n              - start\n              - --system", self.playbook)
        self.assertIn("hermes_cli.main", self.playbook)
        self.assertNotIn("--property=ExecStop", self.playbook)
        self.assertIn("no_log: true", self.playbook)
        self.assertIn("source.backup(target)", self.playbook)
        self.assertIn("PRAGMA quick_check", self.playbook)
        self.assertNotIn("/usr/bin/sqlite3", self.playbook)
        self.assertIn("hermes_memory_continuity_policy_files", self.playbook)
        self.assertEqual(
            self.variables["hermes_lcm_externalized_output_root"],
            "/var/lib/hermes/astra/.hermes/profiles/astra/lcm-large-outputs",
        )
        policy_sources = {
            item["source"]
            for item in self.variables["hermes_memory_continuity_policy_files"]
        }
        policy_destinations = {
            item["destination"]
            for item in self.variables["hermes_memory_continuity_policy_files"]
        }
        for source in (
            "{{ hermes_star_privacy_validator_source }}",
            "{{ hermes_docker_inventory_validator_source }}",
            "{{ hermes_shadow_contract_source }}",
            "files/hermes/openclaw-state-migration-contract.json",
            "{{ hermes_discord_contract_source }}",
            "{{ hermes_automation_contract_source }}",
            "files/hermes/profile-import-contract.json",
            "{{ hermes_profile_data_contract_source }}",
            "{{ hermes_profile_transforms_contract_source }}",
        ):
            self.assertIn(source, policy_sources)
        for destination in (
            "{{ hermes_star_privacy_validator_live }}",
            "{{ hermes_docker_inventory_validator_live }}",
        ):
            self.assertIn(destination, policy_destinations)
            self.assertIn(destination, self.playbook)

    def test_mem0_scope_excludes_other_agents(self) -> None:
        self.assertEqual(
            self.variables["hermes_mem0_source_user_ids"],
            ["johnny", "johnny:agent:main", "740687933803331726"],
        )
        self.assertIn(".selectedCount == 4148", self.playbook)
        self.assertIn(".excludedCount == 287", self.playbook)
        for excluded in (
            "johnny:agent:dubble",
            "johnny:agent:rigel",
            "johnny:agent:antares",
            "johnny:agent:vega",
        ):
            self.assertNotIn(excluded, self.variables["hermes_mem0_source_user_ids"])
        self.assertEqual(
            self.playbook.count(
                "map('regex_replace', '^', '--include-user-id=')"
            ),
            3,
        )
        self.assertNotIn("--include-user-id=\\\\1", self.playbook)

    def test_mem0_config_uses_existing_embedding_space_and_supported_backends(self) -> None:
        source = (ROOT / "templates/hermes/hermes-mem0.json.j2").read_text()
        rendered = Template(source).render(
            hermes_mem0_user_id="johnny",
            hermes_mem0_agent_id="astra",
            hermes_mem0_target_collection="memories_hermes_astra_v1",
        )
        config = json.loads(rendered)
        self.assertEqual(config["mode"], "oss")
        self.assertEqual(config["user_id"], "johnny")
        self.assertEqual(config["agent_id"], "astra")
        self.assertEqual(config["oss"]["llm"]["provider"], "openai")
        self.assertEqual(
            config["oss"]["llm"]["config"]["openai_base_url"],
            "https://openrouter.ai/api/v1",
        )
        self.assertEqual(config["oss"]["embedder"]["provider"], "gemini")
        self.assertEqual(
            config["oss"]["embedder"]["config"]["embedding_dims"], 3072
        )
        self.assertEqual(
            config["oss"]["vector_store"]["config"]["collection_name"],
            "memories_hermes_astra_v1",
        )

    def test_mem0_dependency_uses_hermes_locked_extra(self) -> None:
        shadow = (ROOT / "playbooks/agents/hermes-shadow.yml").read_text()
        updater = (
            ROOT / "templates/hermes/hermes-native-update.service.j2"
        ).read_text()
        self.assertIn("- mem0", shadow)
        self.assertIn("[messaging,mem0]", updater)
        self.assertEqual(
            self.variables["hermes_mem0_gemini_dependency"],
            "google-genai>=1.0.0,<2.13.0",
        )
        self.assertIn("hermes_mem0_gemini_dependency", self.playbook)
        self.assertIn("hermes_mem0_gemini_dependency", updater)
        self.assertIn("from google import genai", self.playbook)
        self.assertGreaterEqual(self.playbook.count("--no-deps"), 1)
        self.assertIn("pip install --strict --no-deps", updater)
        self.assertIn("pip check --python", updater)
        self.assertIn("--locked", self.playbook)
        self.assertIn("- mem0", self.playbook)
        self.assertNotIn("pip install mem0ai", self.playbook)

    def test_migrator_never_deletes_or_mutates_source(self) -> None:
        script = (
            ROOT / "scripts/agents/hermes-mem0-qdrant-migrate.py"
        ).read_text()
        self.assertNotIn('request("DELETE"', script)
        self.assertIn("client.snapshot(args.source)", script)
        self.assertIn("source-and-target-must-differ", script)
        self.assertIn("nonempty-target-does-not-match-source", script)
        self.assertIn("openclaw_user_id", script)


if __name__ == "__main__":
    unittest.main()
