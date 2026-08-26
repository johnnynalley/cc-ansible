#!/usr/bin/env python3

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = (ROOT / "playbooks/agents/hermes-lcm-native-features.yml").read_text()
VARS = (ROOT / "inventory/group_vars/hermes_hosts/vars.yml").read_text()
DROPIN = (ROOT / "templates/hermes/hermes-gateway-hardening.conf.j2").read_text()


class HermesLcmNativeFeaturesTests(unittest.TestCase):
    def test_mutation_requires_exact_approval(self) -> None:
        self.assertIn("hermes_lcm_native_features_mode != 'apply'", PLAYBOOK)
        self.assertIn("hermes_lcm_native_features_approved | bool", PLAYBOOK)
        self.assertIn("enable-native-hermes-lcm-feature-depth", VARS)

    def test_backup_is_verified_and_precedes_embedding_writes(self) -> None:
        backup = PLAYBOOK.index("Create live SQLite backup")
        publish = PLAYBOOK.index("Publish verified LCM backup atomically")
        warmup = PLAYBOOK.index("Warm and dimension-lock")
        self.assertLess(backup, publish)
        self.assertLess(publish, warmup)
        helper = (
            ROOT / "scripts/agents/hermes-lcm-native-maintenance.py"
        ).read_text()
        self.assertIn("PRAGMA quick_check", helper)
        self.assertIn("Compare local and NFS LCM backup hashes", PLAYBOOK)
        self.assertIn("expected_type: runtime_selector", PLAYBOOK)
        self.assertIn("^/usr/local/share/uv/python/", PLAYBOOK)

    def test_local_current_generation_features_are_explicit(self) -> None:
        for marker in (
            "LCM_EMBEDDINGS_ENABLED=true",
            "LCM_EMBEDDING_PROVIDER={{ hermes_lcm_embedding_provider }}",
            "LCM_EMBEDDING_BINARY_PRESCREEN=",
            "LCM_EMBEDDING_QUERY_TIMEOUT_S=",
            "LCM_RECALL_QUERY_TIMEOUT_S=",
            "LCM_EMBEDDING_BACKFILL_TIMEOUT_S=",
            "LCM_PROACTIVE_RECALL_ENABLED=",
            "LCM_TEMPORAL_ROLLUPS_ENABLED=",
        ):
            self.assertIn(marker, DROPIN)
        self.assertIn("qwen3-embedding:0.6b", VARS)
        self.assertIn("float32", VARS)
        self.assertIn("hermes_lcm_embedding_max_batch_items: 16", VARS)
        self.assertIn("hermes_lcm_embedding_query_timeout_s: 15", VARS)
        self.assertIn("hermes_lcm_recall_query_timeout_s: 20", VARS)
        self.assertIn("hermes_lcm_embedding_backfill_timeout_s: 600", VARS)
        self.assertNotIn("voyage", DROPIN.lower())

    def test_both_corpora_and_archive_recall_are_verified(self) -> None:
        self.assertIn("Populate bounded summary embeddings locally", PLAYBOOK)
        self.assertIn(
            "Populate bounded conversational chunk embeddings locally",
            PLAYBOOK,
        )
        self.assertNotIn("Verify zero remaining embedding debt", PLAYBOOK)
        self.assertIn("embedding_vectors_by_task.summary", PLAYBOOK)
        self.assertIn("chunk_vectors_by_task.chunk", PLAYBOOK)
        self.assertNotIn("tables.lcm_chunk_embeddings", PLAYBOOK)
        self.assertIn("Prove semantic all-time recall", PLAYBOOK)
        self.assertIn("recall-embedded-smoke", PLAYBOOK)
        self.assertIn("result_types.summary", PLAYBOOK)
        self.assertIn("coverage.summary", PLAYBOOK)
        self.assertIn("Prove exact all-session archive search", PLAYBOOK)
        self.assertIn("degraded_to_fts", PLAYBOOK)
        self.assertIn(
            "Audit current-session and imported LCM continuity without content",
            PLAYBOOK,
        )
        self.assertIn(
            "Prove native proactive recall assembly without exposing content",
            PLAYBOOK,
        )
        self.assertIn("recent_lcm_sessions_missing_in_state", PLAYBOOK)
        self.assertIn("tables.lcm_rollups is defined", PLAYBOOK)

    def test_zero_drift_exits_before_backup_and_restart(self) -> None:
        zero_drift = PLAYBOOK.index("Stop zero-drift LCM apply")
        backup = PLAYBOOK.index("Create live SQLite backup")
        restart = PLAYBOOK.index("Restart Astra once")
        self.assertLess(zero_drift, backup)
        self.assertLess(zero_drift, restart)
        self.assertIn("Stop check mode after complete read-only LCM preview", PLAYBOOK)

    def test_rescue_is_gated_on_published_prior_state(self) -> None:
        self.assertGreaterEqual(
            PLAYBOOK.count("hermes_lcm_native_prior_state_published | bool"), 8
        )
        self.assertIn("Verify rollback copy hash", PLAYBOOK)
        self.assertIn("Verify restored LCM database integrity", PLAYBOOK)
        self.assertIn("Inspect failed transaction database before rollback choice", PLAYBOOK)
        self.assertIn("hermes_lcm_native_database_restore_required | bool", PLAYBOOK)
        self.assertIn("Remove stale SQLite sidecars", PLAYBOOK)
        self.assertIn("Restart Astra after configuration-only rollback", PLAYBOOK)


if __name__ == "__main__":
    unittest.main()
