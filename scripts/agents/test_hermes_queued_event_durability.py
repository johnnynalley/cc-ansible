#!/usr/bin/env python3
"""Regression checks for managed Hermes queued-turn durability."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[2]
PATCH = ROOT / "files/hermes/patches/queued-event-shutdown-replay.patch"
VALIDATOR = ROOT / "scripts/agents/hermes-queued-event-durability-validate.py"
PROMOTER = ROOT / "scripts/agents/hermes-managed-source-patch.py"
PLAYBOOK = ROOT / "playbooks/agents/hermes-production-runtime.yml"
CONFIG = ROOT / "templates/hermes/hermes-managed-config.yaml.j2"
UPDATE_UNIT = ROOT / "templates/hermes/hermes-native-update.service.j2"
UPDATE_TRANSACTION_CONFIG = ROOT / "templates/hermes/hermes-native-update-transaction.json.j2"
INVENTORY = ROOT / "inventory/group_vars/hermes_hosts/vars.yml"


def load_validator():
    spec = importlib.util.spec_from_file_location("queued_event_validator", VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class QueuedEventDurabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patch = PATCH.read_text(encoding="utf-8")
        cls.promoter = PROMOTER.read_text(encoding="utf-8")
        cls.playbook = PLAYBOOK.read_text(encoding="utf-8")
        cls.config = CONFIG.read_text(encoding="utf-8")
        cls.update_unit = UPDATE_UNIT.read_text(encoding="utf-8")
        cls.update_transaction_config = UPDATE_TRANSACTION_CONFIG.read_text(encoding="utf-8")
        cls.inventory = INVENTORY.read_text(encoding="utf-8")

    def test_patch_contains_full_event_fifo_and_ack_contract(self) -> None:
        for marker in (
            "gateway_queued_event_batch_v2",
            "def serialise_queued_message_event(",
            "def deserialise_queued_message_event(",
            "def _queued_gateway_event_snapshot(",
            "def _stage_shutdown_queued_event_replays(",
            "def _collect_queued_event_spool_ack(",
            "acknowledge_queued_event_spool(_spooled_event)",
            "test_spool_ack_eligibility_uses_each_events_own_result",
            '"tool.doc_extract": ("firecrawl-anydoc",),',
            "_SYNC_SHUTDOWN_WAIT_SECS = 120.0",
            "test_timeout_never_closes_backend_under_active_sync",
            'if self.platform == "cron":',
            "test_cron_turn_does_not_sync_or_prefetch",
            "test_interactive_turn_still_syncs_and_prefetches",
            "CREATE TABLE IF NOT EXISTS execution_deliveries",
            "def _record_delivery_receipt(",
            "test_live_adapter_records_execution_delivery_message_id",
            "test_marker_substrings_do_not_turn_complete_answers_into_acks",
        ):
            self.assertIn(marker, self.patch)
        self.assertNotIn('+    "tool.doc_extract": ("firecrawl-anydoc==', self.patch)

    def test_promoter_is_official_origin_scoped_and_worktree_first(self) -> None:
        self.assertIn("OFFICIAL_ORIGINS", self.promoter)
        self.assertIn("git(worktree, \"apply\", \"--check\"", self.promoter)
        self.assertIn("git(root, \"branch\", \"-f\"", self.promoter)
        self.assertIn("git(root, \"switch\", args.branch)", self.promoter)
        self.assertNotIn("managed branch already exists but is not checked out", self.promoter)
        self.assertLess(
            self.promoter.index("run([sys.executable, str(validator)"),
            self.promoter.index("git(root, \"switch\", args.branch)"),
        )
        self.assertNotIn("git reset", self.promoter)
        self.assertIn('"tests/agent/test_todo_stop.py"', self.promoter)
        self.assertIn('"tests/agent/test_intent_ack_continuation.py"', self.promoter)
        self.assertIn('"tests/plugins/memory/test_mem0_shutdown.py"', self.promoter)
        self.assertIn('"tests/run_agent/test_memory_sync_interrupted.py"', self.promoter)
        self.assertNotIn('"-m",\n                "pytest"', self.promoter)
        self.assertIn("import runpy", self.promoter)
        self.assertIn("patched Hermes regression failed", self.promoter)
        self.assertIn('" | ".join(detail[-12:])', self.promoter)

    def test_inventory_normalizes_every_cron_receipt_patch_path(self) -> None:
        for path in (
            "cron/executions.py",
            "cron/scheduler.py",
            "hermes_cli/cron.py",
            "tests/cron/test_execution_ledger.py",
            "tests/cron/test_scheduler.py",
        ):
            self.assertIn(f"  - {path}\n", self.inventory)

    def test_promoter_rebuilds_existing_managed_branch_on_updated_main(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "hermes"
            staging = Path(directory) / "staging"
            root.mkdir()

            def git(*args: str, capture: bool = False) -> str:
                completed = subprocess.run(
                    ["git", *args],
                    cwd=root,
                    check=True,
                    text=True,
                    capture_output=capture,
                )
                return completed.stdout

            git("init", "-b", "main")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.invalid")
            git("remote", "add", "origin", "https://github.com/NousResearch/hermes-agent.git")
            paths = sorted(
                {
                    "agent/conversation_loop.py",
                    "agent/agent_runtime_helpers.py",
                    "agent/todo_stop.py",
                    "agent/turn_context.py",
                    "cron/executions.py",
                    "cron/scheduler.py",
                    "gateway/platforms/base.py",
                    "gateway/run.py",
                    "gateway/shutdown_flush.py",
                    "hermes_cli/cron.py",
                    "hermes_cli/config_defaults.py",
                    "plugins/memory/mem0/__init__.py",
                    "run_agent.py",
                    "tests/agent/test_todo_stop.py",
                    "tests/agent/test_intent_ack_continuation.py",
                    "tests/cron/test_execution_ledger.py",
                    "tests/cron/test_scheduler.py",
                    "tests/gateway/test_queued_event_shutdown_replay.py",
                    "tests/plugins/memory/test_mem0_shutdown.py",
                    "tests/run_agent/test_memory_sync_interrupted.py",
                    "tools/lazy_deps.py",
                }
            )
            for relative in paths:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                if relative == "tests/agent/test_intent_ack_continuation.py":
                    source = (
                        "def test_all_path_drops_workspace_requirement(): pass\n"
                        "def test_multipart_user_message_does_not_crash_on_workspace_path(): pass\n"
                        "def test_marker_substrings_do_not_turn_complete_answers_into_acks(): pass\n"
                    )
                elif relative.startswith("tests/"):
                    source = "if __name__ == '__main__':\n    pass\n"
                else:
                    source = "VALUE = 1\n"
                path.write_text(source, encoding="utf-8")
            git("add", ".")
            git("commit", "-m", "base")
            for relative in paths:
                with (root / relative).open("a", encoding="utf-8") as handle:
                    handle.write("PATCHED = True\n")
            patch = Path(directory) / "managed.patch"
            patch.write_text(git("diff", capture=True), encoding="utf-8")
            (root / "tools/lazy_deps.py").write_text("VALUE = 1\n", encoding="utf-8")
            git("switch", "-c", "astra-managed-parity")
            git("add", "gateway", "tests")
            git("commit", "-m", "old managed patch")
            old_managed = git("rev-parse", "HEAD", capture=True).strip()
            git("switch", "main")
            git("restore", ".")
            (root / "upstream.py").write_text("UPDATED = True\n", encoding="utf-8")
            git("add", "upstream.py")
            git("commit", "-m", "upstream update")
            main_head = git("rev-parse", "HEAD", capture=True).strip()
            git("switch", "astra-managed-parity")
            validator = Path(directory) / "validator.py"
            validator.write_text(
                "from pathlib import Path\n"
                "import sys\n"
                "root = Path(sys.argv[sys.argv.index('--source-root') + 1])\n"
                f"paths = {paths!r}\n"
                "raise SystemExit(0 if all('PATCHED = True' in (root / path).read_text() for path in paths) else 1)\n",
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(PROMOTER),
                    "--source-root",
                    str(root),
                    "--patch",
                    str(patch),
                    "--validator",
                    str(validator),
                    "--staging-root",
                    str(staging),
                    "--apply",
                ],
                check=False,
                text=True,
                capture_output=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn('"status": "applied"', completed.stdout)
            self.assertEqual(git("branch", "--show-current", capture=True).strip(), "astra-managed-parity")
            self.assertEqual(git("rev-parse", "HEAD^", capture=True).strip(), main_head)
            self.assertNotEqual(git("rev-parse", "HEAD", capture=True).strip(), old_managed)
            for relative in paths:
                self.assertIn("PATCHED = True", (root / relative).read_text(encoding="utf-8"))

    def test_validator_requires_shutdown_and_persistence_ordering(self) -> None:
        validator = VALIDATOR.read_text(encoding="utf-8")
        self.assertIn("early < teardown < final < clear", validator)
        self.assertIn("if acknowledge < session_write", validator)
        self.assertIn("per-event acknowledgement", validator)
        self.assertIn('lazy_deps.get("tool.doc_extract") != ("firecrawl-anydoc",)', validator)
        self.assertIn('"todoStopGuard": "opt-in-native"', validator)
        self.assertIn("todo stop-loop guard must run before the Kanban guard", validator)

    def test_native_update_and_production_runtime_are_gated(self) -> None:
        self.assertIn("parked_branch_strategy: update_in_place", self.config)
        self.assertIn("hermes_native_update_transaction_live", self.update_unit)
        self.assertIn("hermes_queued_event_validator_live", self.update_transaction_config)
        for marker in (
            "Back up clean Hermes source checkout",
            "Promote reviewed Hermes source-parity patch",
            "Validate managed Hermes source parity",
            "hermes_runtime_source_patch.changed",
        ):
            self.assertIn(marker, self.playbook)

    def test_validator_module_has_expected_contract(self) -> None:
        module = load_validator()
        self.assertEqual(module.REQUIRED_FILES["gateway/shutdown_flush.py"][1], "QUEUED_EVENT_BATCH_SCHEMA = 2")
        self.assertIn("agent/todo_stop.py", module.REQUIRED_FILES)
        self.assertIn("agent/agent_runtime_helpers.py", module.REQUIRED_FILES)
        self.assertIn(
            "tests/agent/test_intent_ack_continuation.py", module.REQUIRED_FILES
        )
        self.assertIn("plugins/memory/mem0/__init__.py", module.REQUIRED_FILES)
        self.assertIn("cron/executions.py", module.REQUIRED_FILES)
        self.assertIn("cron/scheduler.py", module.REQUIRED_FILES)
        self.assertIn("hermes_cli/cron.py", module.REQUIRED_FILES)
        self.assertIn("tests/cron/test_execution_ledger.py", module.REQUIRED_FILES)
        self.assertIn("tests/cron/test_scheduler.py", module.REQUIRED_FILES)
        self.assertIn("tests/plugins/memory/test_mem0_shutdown.py", module.REQUIRED_FILES)
        self.assertIn("tests/run_agent/test_memory_sync_interrupted.py", module.REQUIRED_FILES)


if __name__ == "__main__":
    unittest.main()
