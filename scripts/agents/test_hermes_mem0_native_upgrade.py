#!/usr/bin/env python3
"""Structural tests for the native stable Mem0 v3 upgrade."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]


class HermesMem0NativeUpgradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.playbook = (
            ROOT / "playbooks/agents/hermes-mem0-native-upgrade.yml"
        ).read_text()
        cls.variables = yaml.safe_load(
            (ROOT / "inventory/group_vars/hermes_hosts/vars.yml").read_text()
        )
        cls.migrator = (
            ROOT / "scripts/agents/hermes-mem0-qdrant-migrate.py"
        ).read_text()
        cls.hardening = (
            ROOT / "templates/hermes/hermes-gateway-hardening.conf.j2"
        ).read_text()
        cls.updater = (
            ROOT / "templates/hermes/hermes-native-update.service.j2"
        ).read_text()
        cls.update_transaction = (
            ROOT / "scripts/agents/hermes-native-update-transaction.py"
        ).read_text()
        cls.update_contract = (
            ROOT / "templates/hermes/hermes-native-update-transaction.json.j2"
        ).read_text()
        cls.mem0_config = (
            ROOT / "templates/hermes/hermes-mem0.json.j2"
        ).read_text()

    def test_upgrade_is_exactly_approved_and_native_only(self) -> None:
        self.assertEqual(
            self.variables["hermes_mem0_native_source_collection"],
            "{{ hermes_mem0_target_collection }}",
        )
        self.assertEqual(
            self.variables["hermes_mem0_native_target_collection"],
            "memories_hermes_astra_v3",
        )
        self.assertIn("Require exact native Mem0 v3 authorization", self.playbook)
        self.assertIn(
            "hermes_mem0_native_upgrade_required_confirmation", self.playbook
        )
        self.assertIn("--source-normalized", self.playbook)
        self.assertNotIn("/home/johnny/.openclaw", self.playbook)

    def test_latest_stable_dependencies_are_reasserted_after_updates(self) -> None:
        self.assertEqual(
            self.variables["hermes_mem0_stable_dependencies"],
            ["mem0ai[nlp]", "fastembed", "ollama", "firecrawl-anydoc"],
        )
        self.assertIn("Resolve newest stable Python memory package releases", self.playbook)
        self.assertIn("--prerelease', 'disallow'", self.playbook)
        self.assertIn("Require exact newest stable package versions", self.playbook)
        self.assertIn("Read active stable Hermes base requirements", self.playbook)
        self.assertIn("Require a nonempty base compatibility contract", self.playbook)
        self.assertIn("community.general.version_sort", self.playbook)
        self.assertIn("'/usr/sbin/runuser', '--user', 'hermes-astra'", self.playbook)
        self.assertNotIn("become_user: hermes-astra", self.playbook)
        self.assertGreaterEqual(self.playbook.count("chdir: /var/lib/hermes/astra"), 2)
        self.assertIn("hermes_mem0_dependency_updater_live", self.update_contract)
        self.assertIn("hermes_mem0_stable_dependencies", self.update_contract)
        self.assertIn("spacy.load", self.update_transaction)

    def test_transaction_has_independent_and_automatic_rollback(self) -> None:
        for required in (
            "Back up exact native Mem0 runtime before mutation",
            "Create exact local virtual-environment rollback copy",
            "Mark local virtual-environment rollback copy usable",
            "Normalize shared virtual-environment ownership for native updater",
            "Prepare shared virtual environment for both Gateways",
            "Inspect shared-reader access before Gateway restart",
            "Require shared-reader access before Gateway restart",
            "Finalize shared virtual-environment ownership after validation",
            "Require native updater ownership after final runtime validation",
            "Preserve current small runtime files for automatic rescue",
            "Deploy compatibility-safe memory dependency resolver",
            "Restore prior managed memory dependency resolver",
            "Remove newly introduced dependency resolver after rollback",
            "Preserve failed virtual environment for diagnosis",
            "Restore exact prior virtual environment",
            "Restore prior native Mem0 runtime files",
            "Remove newly created v3 target after failed activation",
            "Restore previously active shared-runtime Gateways",
            "Restore previously active timers after rollback",
            "Require supplied rollback artifact under managed storage",
            "Require complete explicitly supplied native Mem0 rollback contents",
            "Require exact native Mem0 sources in supplied rollback manifest",
        ):
            self.assertIn(required, self.playbook)
        self.assertIn("/usr/local/sbin/live-rollback-backup", self.playbook)
        self.assertIn("--reflink=auto", self.playbook)
        self.assertIn("follow: true", self.playbook)
        self.assertIn(
            "local_venv_backup_stat.stat.executable", self.playbook
        )
        self.assertIn("local_backup_ready | default(false)", self.playbook)
        self.assertIn("realpath\n          - --canonicalize-existing", self.playbook)
        self.assertIn("hermes_mem0_native_upgrade_backup_path", self.playbook)
        self.assertEqual(
            self.variables["hermes_mem0_native_upgrade_existing_backup"], ""
        )
        self.assertLess(
            self.playbook.index("Prepare shared virtual environment for both Gateways"),
            self.playbook.index("Start previously active shared-runtime Gateways"),
        )
        self.assertGreaterEqual(self.playbook.count('mode: "g+rX"'), 2)

    def test_v3_schema_and_exact_count_are_required(self) -> None:
        for required in (
            "--hybrid",
            "Qdrant/bm25",
            "sourceCount",
            "selectedCount",
            "excludedCount",
            "points_count == 4148",
            "sparse_vectors.bm25.modifier",
            "payload_schema.user_id.data_type",
            "payload_schema.agent_id.data_type",
            "keyword_search",
            "Require complete native v3 entity schema",
            "_entities",
        ):
            self.assertIn(required, self.playbook)
        self.assertIn("embedding_model_dims", self.mem0_config)
        self.assertIn("sparse_vectors", self.migrator)
        self.assertIn("create_payload_index", self.migrator)
        self.assertIn("client.snapshot(args.source)", self.migrator)
        self.assertNotIn('request("DELETE"', self.migrator)

    def test_local_memory_privacy_and_nlp_are_enforced(self) -> None:
        self.assertIn("Environment=MEM0_TELEMETRY=false", self.hardening)
        self.assertIn("Environment=FASTEMBED_CACHE_PATH=", self.hardening)
        self.assertIn("MEM0_TELEMETRY=false", self.playbook)
        self.assertIn("spacy-models/master/compatibility.json", self.playbook)
        self.assertIn("spacy_compatibility.content\n                 | from_json", self.playbook)
        self.assertNotIn("spacy_compatibility.json.spacy", self.playbook)
        self.assertIn("mem0-native-nlp-ok", self.playbook)
        self.assertNotIn("GEMINI_API_KEY", self.playbook)
        self.assertNotIn("OPENAI_API_KEY", self.playbook)
        self.assertNotIn("OPENROUTER_API_KEY", self.playbook)


if __name__ == "__main__":
    unittest.main()
