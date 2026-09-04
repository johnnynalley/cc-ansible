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
            "Require independent local staging and managed NFS rollback storage",
            "Prepare verified source backups before memory conversion",
            "Create consistent OpenClaw SQLite backups on local ext4",
            "Verify locally staged OpenClaw SQLite backups",
            "Create native backup in Astra-owned storage",
            "Move Astra profile backup into local ext4 staging",
            "Verify locally staged Astra profile backup archive",
            "Require exact source artifact copies before publication",
            "Publish verified source artifacts atomically",
            "Remove incomplete NFS source artifact partials",
            "Prepare service-owned markers for memory conversion stops",
            "Stop active native Gateways once for shared runtime conversion",
            "Reject orphaned LCM externalized-output state",
            "Back up prior LCM target database on local ext4",
            "Verify prior LCM tree archives on local ext4",
            "Require exact prior-state artifact copies before publication",
            "Require exact published prior-state artifacts",
            "Verify published prior LCM database integrity",
            "Mark prior-state artifacts safe for rollback",
            "Discover official Hermes LCM release tags",
            "Select newest production-stable Hermes LCM release",
            "Require a supported stable Hermes LCM release policy",
            "Dry-run OpenClaw LCM conversion",
            "Apply idempotent OpenClaw LCM conversion",
            "Secure imported Hermes LCM externalized outputs",
            "Dry-run Astra-only Mem0 vector conversion",
            "Apply source-preserving Astra Mem0 vector conversion",
            "Install supported Mem0 Ollama client dependency",
            "Validate Mem0 Ollama client dependency before conversion",
            "Pull missing local Mem0 models",
            "Validate local Mem0 model availability",
            "Validate Hermes Python package compatibility before conversion",
            "Validate Astra Mem0 provider recall without exposing results",
            "Reconcile preserved Mem0 v1 collection after local re-embedding",
            "Remove newly created Mem0 target after failed conversion",
            "Remove incomplete NFS prior-state artifact partials",
            "Remove locally added Mem0 models after failed conversion",
            "Remove locally added Mem0 Ollama client after failed conversion",
            "Record failed memory-conversion task privately",
            "Copy published prior-state artifacts into local rollback staging",
            "Require checksum-verified local rollback artifacts",
            "Verify local rollback LCM database integrity",
            "Remove failed LCM externalized-output tree",
            "Restore prior LCM externalized-output tree",
            "Verify restored live LCM database integrity",
            "Restore exact prior production Gateway availability",
            "Restore exact prior timer availability",
            "Remove local memory-continuity staging after transaction",
            "Fail after restoring pre-conversion memory state",
        ):
            self.assertIn(required, self.playbook)
        self.assertNotIn("hermes_openclaw_source_env", self.playbook)
        self.assertNotIn("/home/johnny/.openclaw/.env", self.playbook)
        self.assertNotIn("Enroll Astra provider credentials", self.playbook)
        self.assertIn("gateway\n              - stop\n              - --system", self.playbook)
        self.assertIn(
            'name: "{{ item.item.unit }}"\n            state: started',
            self.playbook,
        )
        self.assertIn("hermes_cli.main", self.playbook)
        self.assertNotIn("--property=ExecStop", self.playbook)
        self.assertIn("no_log: true", self.playbook)
        self.assertIn("source.backup(target)", self.playbook)
        self.assertIn("PRAGMA quick_check", self.playbook)
        self.assertIn("--types\n          - nfs,nfs4", self.playbook)
        self.assertIn("--sparse=always", self.playbook)
        self.assertNotIn("--preserve=mode,timestamps", self.playbook)
        self.assertGreaterEqual(self.playbook.count("/usr/bin/sha256sum"), 7)
        self.assertIn("always:", self.playbook)
        self.assertIn(
            "hermes_memory_continuity_prior_state_published: false",
            self.playbook,
        )
        self.assertEqual(self.variables["hermes_lcm_release_track"], "stable")
        self.assertIn("community.general.version_sort", self.playbook)
        self.assertIn("hermes_lcm_release_track == 'stable'", self.playbook)
        self.assertIn(
            "'refs/tags/(v[0-9]+\\.[0-9]+\\.[0-9]+)$'",
            self.playbook,
        )
        self.assertIn(
            'version: "{{ hermes_memory_continuity_lcm_resolved_release }}"',
            self.playbook,
        )
        self.assertLess(
            self.playbook.index("Mark prior-state artifacts safe for rollback"),
            self.playbook.index("Install or update managed Hermes LCM release track"),
        )
        self.assertLess(
            self.playbook.index("Require checksum-verified local rollback artifacts"),
            self.playbook.index("Remove failed Hermes LCM target"),
        )
        self.assertNotIn(
            'src: "{{ hermes_memory_continuity_backup_dir }}/prior-hermes-lcm.db"',
            self.playbook,
        )
        self.assertIn(
            "hermes_memory_continuity_prior_ollama_dependency is defined",
            self.playbook,
        )
        self.assertNotIn("/usr/bin/sqlite3", self.playbook)
        self.assertNotIn("hermes_memory_continuity_policy_files", self.playbook)
        self.assertNotIn("Deploy current memory-dependent Hermes policy graph", self.playbook)
        self.assertNotIn("Validate deployed Hermes target policy", self.playbook)
        self.assertNotIn("Validate deployed Hermes Discord policy graph", self.playbook)
        self.assertNotIn("Validate deployed Hermes automation policy graph", self.playbook)
        self.assertEqual(
            self.variables["hermes_lcm_externalized_output_root"],
            "/var/lib/hermes/astra/.hermes/profiles/astra/lcm-large-outputs",
        )

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
            4,
        )
        self.assertNotIn("--include-user-id=\\\\1", self.playbook)

    def test_mem0_config_uses_local_ollama_and_new_embedding_space(self) -> None:
        source = (ROOT / "templates/hermes/hermes-mem0.json.j2").read_text()
        rendered = Template(source).render(
            hermes_mem0_user_id="johnny",
            hermes_mem0_agent_id="astra",
            hermes_mem0_render_collection="memories_hermes_astra_v2",
            hermes_mem0_ollama_url="http://127.0.0.1:11434",
            hermes_mem0_ollama_llm_model="qwen3:4b",
            hermes_mem0_ollama_embedding_model="qwen3-embedding:0.6b",
            hermes_mem0_ollama_embedding_dimensions=1024,
        )
        config = json.loads(rendered)
        self.assertEqual(config["mode"], "oss")
        self.assertEqual(config["user_id"], "johnny")
        self.assertEqual(config["agent_id"], "astra")
        self.assertEqual(config["oss"]["llm"]["provider"], "ollama")
        self.assertEqual(
            config["oss"]["llm"]["config"]["model"],
            "qwen3:4b",
        )
        self.assertEqual(config["oss"]["embedder"]["provider"], "ollama")
        self.assertEqual(
            config["oss"]["embedder"]["config"]["model"],
            "qwen3-embedding:0.6b",
        )
        self.assertEqual(
            config["oss"]["embedder"]["config"]["embedding_dims"], 1024
        )
        self.assertEqual(
            config["oss"]["vector_store"]["config"]["collection_name"],
            "memories_hermes_astra_v2",
        )
        self.assertNotIn("gemini", source.lower())
        self.assertNotIn("openrouter", source.lower())

    def test_mem0_dependency_uses_locked_native_extra_and_provider_setup(self) -> None:
        shadow = (ROOT / "playbooks/agents/hermes-shadow.yml").read_text()
        update_transaction = (
            ROOT / "scripts/agents/hermes-native-update-transaction.py"
        ).read_text()
        update_contract = (
            ROOT / "templates/hermes/hermes-native-update-transaction.json.j2"
        ).read_text()
        self.assertIn("- mem0", shadow)
        self.assertEqual(
            self.variables["hermes_mem0_ollama_dependency"],
            "ollama",
        )
        self.assertEqual(
            self.variables["hermes_mem0_ollama_binary"],
            "/usr/local/bin/ollama",
        )
        self.assertIn("hermes_mem0_ollama_binary", self.playbook)
        self.assertNotIn("/usr/bin/ollama", self.playbook)
        self.assertIn("hermes_mem0_ollama_dependency", self.playbook)
        self.assertIn("import ollama", self.playbook)
        self.assertNotIn("hermes_mem0_gemini_dependency", self.playbook)
        self.assertNotIn("hermes_mem0_gemini_dependency", update_contract)
        self.assertNotIn("memoryDependencyUpdater", update_contract)
        self.assertNotIn('"pip", "install"', update_transaction)
        self.assertIn("--locked", self.playbook)
        self.assertIn("- mem0", self.playbook)
        self.assertIn("- edge-tts", self.playbook)
        self.assertNotIn("pip install mem0ai", self.playbook)

    def test_mem0_reembedding_preserves_v1_and_uses_v2(self) -> None:
        self.assertEqual(
            self.variables["hermes_mem0_preserved_collection"],
            "memories_hermes_astra_v1",
        )
        self.assertEqual(
            self.variables["hermes_mem0_target_collection"],
            "memories_hermes_astra_v2",
        )
        self.assertEqual(
            self.variables["hermes_mem0_ollama_embedding_dimensions"], 1024
        )
        self.assertGreaterEqual(self.playbook.count("'--reembed'"), 3)
        self.assertIn("hermes_mem0_preserved_collection", self.playbook)

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
