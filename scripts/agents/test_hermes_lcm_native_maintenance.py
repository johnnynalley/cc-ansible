#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest


SCRIPT = Path(__file__).with_name("hermes-lcm-native-maintenance.py")


def load_module():
    spec = importlib.util.spec_from_file_location("hermes_lcm_native_maintenance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class HermesLcmNativeMaintenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def test_mutations_require_exact_approval(self) -> None:
        args = type("Args", (), {"approved": True, "confirmation": "wrong"})()
        with self.assertRaisesRegex(RuntimeError, "mutation refused"):
            self.module.require_mutation_approval(args)

    def test_retrieval_output_drops_content(self) -> None:
        raw = json.dumps(
            {
                "results": [
                    {
                        "session_id": "one",
                        "type": "message",
                        "content": "private source text",
                    },
                    {"session_id": "two", "type": "summary", "snippet": "secret"},
                ],
                "coverage": "full_approx",
                "provenance": {"arms": ["fts", "summary", "chunk"]},
            }
        )
        result = self.module.sanitized_retrieval_result(raw, "canary")
        encoded = json.dumps(result)
        self.assertNotIn("private source text", encoded)
        self.assertNotIn("secret", encoded)
        self.assertEqual(result["result_count"], 2)
        self.assertEqual(result["distinct_result_sessions"], 2)

    def test_recall_output_uses_native_hits_and_nested_coverage(self) -> None:
        raw = json.dumps(
            {
                "hits": [
                    {
                        "session_id": "one",
                        "kind": "summary",
                        "snippet": "private semantic hit",
                    }
                ],
                "total_results": 1,
                "degraded": True,
                "degraded_reason": "full-text arm unavailable",
                "provenance": {
                    "arms_run": ["summary"],
                    "coverage": {
                        "fts": "none",
                        "summary": "full_approx",
                        "chunk": "full",
                    },
                },
            }
        )
        result = self.module.sanitized_retrieval_result(raw, "private query")
        encoded = json.dumps(result)
        self.assertNotIn("private semantic hit", encoded)
        self.assertEqual(result["result_count"], 1)
        self.assertEqual(result["result_types"], {"summary": 1})
        self.assertEqual(result["coverage"]["summary"], "full_approx")
        self.assertTrue(result["degraded"])

    def test_inventory_reports_only_counts_and_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "lcm.db"
            state = root / "state.db"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    "CREATE TABLE messages (session_id TEXT, content TEXT)"
                )
                connection.execute(
                    "INSERT INTO messages VALUES ('one', 'private source text')"
                )
                connection.execute(
                    "CREATE TABLE lcm_embedding_profile ("
                    "identity_hash TEXT, provider TEXT, model_name TEXT, "
                    "dim INTEGER, dtype TEXT, task TEXT, active INTEGER, "
                    "archived_at REAL, registered_at REAL)"
                )
                connection.executemany(
                    "INSERT INTO lcm_embedding_profile VALUES "
                    "(?, 'ollama', 'model', 1024, 'float32', ?, 1, NULL, 1)",
                    [("summary-profile", "summary"), ("chunk-profile", "chunk")],
                )
                connection.execute(
                    "CREATE TABLE lcm_embedding_vectors ("
                    "embedded_id TEXT, identity_hash TEXT, vec BLOB)"
                )
                connection.execute(
                    "INSERT INTO lcm_embedding_vectors VALUES "
                    "('summary-one', 'summary-profile', X'00')"
                )
                connection.execute(
                    "CREATE TABLE summary_nodes ("
                    "node_id TEXT PRIMARY KEY, token_count INTEGER, summary TEXT)"
                )
                connection.execute(
                    "INSERT INTO summary_nodes VALUES "
                    "('summary-one', 100, 'embedded private semantic canary text')"
                )
                connection.execute(
                    "CREATE TABLE lcm_chunk_vectors ("
                    "chunk_id TEXT, identity_hash TEXT, vec BLOB)"
                )
                connection.execute(
                    "INSERT INTO lcm_chunk_vectors VALUES "
                    "('chunk-one', 'chunk-profile', X'00')"
                )
                connection.execute(
                    "CREATE TABLE lcm_embedding_backfill_inflight ("
                    "embedded_id TEXT, state TEXT, last_error TEXT)"
                )
                connection.executemany(
                    "INSERT INTO summary_nodes VALUES (?, ?, ?)",
                    [
                        (1, 120, "private summary one"),
                        (2, 5000, "private summary two"),
                    ],
                )
                connection.executemany(
                    "INSERT INTO lcm_embedding_backfill_inflight VALUES (?, ?, ?)",
                    [
                        ("1", "uncertain", "provider timed out"),
                        ("2", "uncertain", "provider timed out"),
                    ],
                )
                connection.commit()
            with closing(sqlite3.connect(state)) as connection:
                connection.execute("CREATE TABLE sessions (session_id TEXT)")
                connection.execute("INSERT INTO sessions VALUES ('one')")
                connection.commit()
            result = self.module.database_inventory(database, state)
            encoded = json.dumps(result)
            self.assertNotIn("private source text", encoded)
            self.assertEqual(result["tables"]["messages"], 1)
            self.assertEqual(result["distinct_sessions"]["messages"], 1)
            self.assertEqual(result["embedding_profiles"][0]["dim"], 1024)
            self.assertEqual(result["embedding_vectors_by_task"], {"summary": 1})
            self.assertEqual(result["chunk_vectors_by_task"], {"chunk": 1})
            self.assertEqual(
                self.module.embedded_summary_query(database),
                "embedded private semantic canary text",
            )
            self.assertEqual(
                result["backfill_inflight"],
                [
                    {
                        "state": "uncertain",
                        "rows": 2,
                        "last_error": "provider timed out",
                    }
                ],
            )
            self.assertNotIn("private-id-one", encoded)
            self.assertNotIn("private summary one", encoded)
            self.assertEqual(
                result["backfill_inflight_summary_tokens"],
                {
                    "rows": 2,
                    "min_tokens": 120,
                    "max_tokens": 5000,
                    "over_4096": 1,
                },
            )

    def test_backup_is_integrity_checked_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.db"
            destination = root / "backup.db"
            with closing(sqlite3.connect(source)) as connection:
                connection.execute("CREATE TABLE evidence (value TEXT)")
                connection.execute("INSERT INTO evidence VALUES ('retained')")
                connection.commit()
            result = self.module.backup_database(source, destination)
            self.assertEqual(result["quick_check"], "ok")
            self.assertEqual(result["bytes"], destination.stat().st_size)
            self.assertRegex(result["sha256"], r"^[0-9a-f]{64}$")
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                self.module.backup_database(source, destination)

    def test_continuity_audit_reports_counts_without_ids_or_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "lcm.db"
            state = root / "state.db"
            with closing(sqlite3.connect(database)) as connection:
                connection.executescript(
                    "CREATE TABLE messages (session_id TEXT, content TEXT, timestamp REAL);"
                    "CREATE TABLE summary_nodes (session_id TEXT);"
                    "CREATE TABLE lcm_lifecycle_state ("
                    "current_session_id TEXT, last_finalized_session_id TEXT, updated_at REAL);"
                    "CREATE TABLE lcm_rollups (period_kind TEXT, status TEXT);"
                )
                connection.execute(
                    "INSERT INTO messages VALUES ('live-private-id', 'private body', ?)",
                    (self.module.time.time(),),
                )
                connection.execute(
                    "INSERT INTO messages VALUES ('imported-private-id', 'old body', 1)"
                )
                connection.execute(
                    "INSERT INTO lcm_lifecycle_state VALUES ('empty-private-id', NULL, 1)"
                )
                connection.execute("INSERT INTO lcm_rollups VALUES ('day', 'ready')")
                connection.commit()
            with closing(sqlite3.connect(state)) as connection:
                connection.execute("CREATE TABLE sessions (id TEXT)")
                connection.execute("INSERT INTO sessions VALUES ('live-private-id')")
                connection.execute("INSERT INTO sessions VALUES ('state-only-private-id')")
                connection.commit()

            result = self.module.continuity_audit(database, state)
            encoded = json.dumps(result)
            self.assertNotIn("private-id", encoded)
            self.assertNotIn("private body", encoded)
            self.assertEqual(result["state_lcm_overlap"], 1)
            self.assertEqual(result["state_only_sessions"], 1)
            self.assertEqual(result["lcm_only_sessions"], 1)
            self.assertEqual(result["recent_lcm_sessions_present_in_state"], 1)
            self.assertEqual(result["empty_lifecycle_rows"], 1)
            self.assertEqual(result["empty_refs_present_in_state"], 0)
            self.assertEqual(result["temporal_rollups"], {"day": {"ready": 1}})

    def test_backfill_report_parser_ignores_detail_text(self) -> None:
        report = self.module.parse_backfill_report(
            "LCM chunks backfill\n"
            "status: partial\nembedded: 20\nremaining: 5\n"
            "failed_detail: node_id=1 reason=private detail\n"
        )
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["embedded"], "20")
        self.assertEqual(report["remaining"], "5")
        self.assertNotIn("failed_detail", report)

    def test_live_corpus_growth_does_not_mask_embedding_progress(self) -> None:
        self.assertFalse(
            self.module.backfill_progress_stalled(embedded=16, pending=35644)
        )
        self.assertTrue(
            self.module.backfill_progress_stalled(embedded=0, pending=35644)
        )
        self.assertFalse(
            self.module.backfill_progress_stalled(embedded=0, pending=0)
        )

    def test_chunk_metadata_mismatch_inventory_drops_content_and_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "lcm.db"
            with closing(sqlite3.connect(database)) as connection:
                connection.row_factory = sqlite3.Row
                connection.executescript(
                    "CREATE TABLE messages (store_id INTEGER, role TEXT, content TEXT);"
                    "CREATE TABLE lcm_chunk_meta ("
                    "chunk_id TEXT, identity_hash TEXT, store_id INTEGER, "
                    "chunk_index INTEGER, char_start INTEGER, char_end INTEGER, "
                    "token_estimate INTEGER, archived INTEGER);"
                )
                connection.execute(
                    "INSERT INTO messages VALUES (1, 'user', 'private source text')"
                )
                connection.execute(
                    "INSERT INTO lcm_chunk_meta VALUES "
                    "('private-id', 'identity', 1, 0, 0, 19, 99, 0)"
                )
                connection.commit()

                class Chunk:
                    chunk_index = 0
                    char_start = 0
                    char_end = 7
                    token_estimate = 2
                    text = "private"

                mismatches, missing, metrics = self.module.chunk_metadata_mismatches(
                    connection,
                    "identity",
                    lambda *_args, **_kwargs: [Chunk()],
                    "conversational",
                )
            self.assertEqual(len(mismatches), 1)
            self.assertEqual(missing, 0)
            self.assertEqual(metrics["metadata_rows"], 1)
            self.assertEqual(mismatches[0]["char_end"], 7)
            rendered_metrics = json.dumps(metrics)
            self.assertNotIn("private source text", rendered_metrics)
            self.assertNotIn("private-id", rendered_metrics)

    def test_uncertain_retry_uses_native_bounded_flag(self) -> None:
        args = SimpleNamespace(
            operation="backfill",
            corpus="summary",
            limit=64,
            policy=None,
            apply=True,
            retry_uncertain=True,
        )
        self.assertEqual(
            self.module.build_backfill_command(args),
            "embed backfill --corpus summary --limit 64 --apply "
            "--retry-uncertain",
        )
        args.operation = "backfill-bounded"
        args.retry_uncertain = False
        self.assertEqual(
            self.module.build_backfill_command(args),
            "embed backfill --corpus summary --limit 64 --apply",
        )
        args.operation = "backfill-all"
        args.retry_uncertain = True
        self.assertEqual(
            self.module.build_backfill_command(args),
            "embed backfill --corpus summary --limit 64 --apply "
            "--retry-uncertain",
        )

    def test_proactive_smoke_drops_generated_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "lcm.db"
            with closing(sqlite3.connect(database)) as connection:
                connection.executescript(
                    "CREATE TABLE lcm_embedding_profile ("
                    "identity_hash TEXT, task TEXT, active INTEGER, archived_at REAL);"
                    "CREATE TABLE lcm_embedding_vectors ("
                    "embedded_id TEXT, identity_hash TEXT);"
                    "CREATE TABLE summary_nodes ("
                    "node_id TEXT, summary TEXT, token_count INTEGER);"
                )
                connection.execute(
                    "INSERT INTO lcm_embedding_profile VALUES "
                    "('profile', 'summary', 1, NULL)"
                )
                connection.execute(
                    "INSERT INTO lcm_embedding_vectors VALUES ('node', 'profile')"
                )
                connection.execute(
                    "INSERT INTO summary_nodes VALUES "
                    "('node', 'private semantic memory terms for recall', 100)"
                )
                connection.commit()

            class FakeEngine:
                _proactive_recall_injected_count = 0
                _proactive_recall_skipped_count = 0
                _proactive_recall_timeout_count = 0

                def _build_proactive_recall_message(self, tail, role, active):
                    self._proactive_recall_injected_count += 1
                    return {
                        "role": role,
                        "content": "<relevant-memories>private hit</relevant-memories>",
                    }

            result = self.module.proactive_recall_smoke(FakeEngine(), database)
            encoded = json.dumps(result)
            self.assertNotIn("private hit", encoded)
            self.assertTrue(result["generated"])
            self.assertTrue(result["wrapped"])
            self.assertEqual(result["injected"], 1)


if __name__ == "__main__":
    unittest.main()
