#!/usr/bin/env python3
"""Validate the managed Hermes source-parity contract."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import sys


REQUIRED_FILES = {
    "agent/agent_runtime_helpers.py": (
        "_ACTION_INTENT_PATTERNS = tuple(",
        "def _contains_exact_intent_marker(",
        "_contains_exact_intent_marker(user_text, workspace_markers)",
    ),
    "agent/conversation_loop.py": (
        "from agent.todo_stop import build_todo_stop_nudge",
        'final_msg["finish_reason"] = "todo_completion_required"',
        'final_msg["_todo_stop_synthetic"] = True',
        "agent._todo_stop_nudges",
    ),
    "agent/todo_stop.py": (
        "def todo_stop_guard_enabled(",
        "def max_todo_stop_nudges(",
        "def build_todo_stop_nudge(",
        '_ACTIVE = frozenset({"pending", "in_progress"})',
        "Continue the actual work now.",
    ),
    "agent/turn_context.py": (
        "agent._todo_stop_nudges = 0",
    ),
    "cron/executions.py": (
        "CREATE TABLE IF NOT EXISTS execution_deliveries",
        "def record_execution_delivery(",
        "def list_execution_deliveries(",
        "DELETE FROM execution_deliveries",
    ),
    "cron/scheduler.py": (
        "def _record_delivery_receipt(",
        'status=("assumed_delivered" if timed_out else "delivered")',
        "message_id=delivered_message_id",
        "standalone_message_id",
    ),
    "gateway/platforms/base.py": (
        "persist_pending: bool = True",
        "clear_pending: bool = True",
        "if persist_pending:",
        "if clear_pending:",
    ),
    "gateway/shutdown_flush.py": (
        'QUEUED_EVENT_BATCH_REASON = "gateway_queued_event_batch_v2"',
        "QUEUED_EVENT_BATCH_SCHEMA = 2",
        "def serialise_queued_message_event(",
        "def deserialise_queued_message_event(",
        "def flush_queued_events_to_file(",
        "def load_queued_event_spool(",
        "def acknowledge_queued_event_spool(",
        "if payload.get(\"reason\") == QUEUED_EVENT_BATCH_REASON:",
        '"role_authorized"',
        '"profile_route_rejected"',
        '"delivered_via_upstream_relay"',
    ),
    "hermes_cli/config_defaults.py": (
        '"todo_stop_guard": False',
        '"max_todo_stop_nudges": 4',
    ),
    "hermes_cli/cron.py": (
        "from cron.executions import list_execution_deliveries, list_executions",
        'f"    delivery={delivery.get(\'status\', \'?\')}  "',
        'f"target={target}  message_id={message_id}"',
    ),
    "plugins/memory/mem0/__init__.py": (
        "_SYNC_SHUTDOWN_WAIT_SECS = 120.0",
        "self._shutdown_lock = threading.Lock()",
        "self._shutdown_requested = False",
        "atexit.register(self.shutdown)",
        "Mem0 shutdown left the backend open because background",
    ),
    "run_agent.py": (
        '"_todo_stop_synthetic"',
        'if self.platform == "cron":',
    ),
    "tests/agent/test_todo_stop.py": (
        "def test_guard_is_opt_in(",
        "def test_no_active_todos_never_nudges(",
        "def test_active_todos_nudge_until_bounded_budget(",
        "def test_env_can_force_guard(",
        "def test_max_budget_is_bounded(",
    ),
    "tests/agent/test_intent_ack_continuation.py": (
        "def test_marker_substrings_do_not_turn_complete_answers_into_acks(",
        "it is already compatible",
        "response report",
    ),
    "tests/cron/test_execution_ledger.py": (
        "test_delivery_receipt_is_content_free_and_cli_visible",
        "test_delivery_receipt_rejects_unknown_execution",
        "test_retention_prunes_delivery_receipts_with_execution",
    ),
    "tests/cron/test_scheduler.py": (
        "test_live_adapter_records_execution_delivery_message_id",
        'message_id="discord-message-9012"',
    ),
    "tests/plugins/memory/test_mem0_shutdown.py": (
        "test_shutdown_waits_for_active_sync_before_close",
        "test_timeout_never_closes_backend_under_active_sync",
        "test_atexit_uses_ordered_provider_shutdown",
    ),
    "tests/run_agent/test_memory_sync_interrupted.py": (
        "test_cron_turn_does_not_sync_or_prefetch",
        "test_interactive_turn_still_syncs_and_prefetches",
    ),
    "gateway/run.py": (
        "def _collect_queued_event_spool_ack(",
        "def _queued_gateway_event_snapshot(",
        "def _flush_shutdown_queued_events(",
        "def _clear_durably_spooled_gateway_events(",
        "async def _stage_shutdown_queued_event_replays(",
        "def _release_shutdown_spool_replay_stage(",
        "persist_pending=False",
        "clear_pending=False",
        "await self._stage_shutdown_queued_event_replays()",
        "acknowledge_queued_event_spool(_spooled_event)",
        "recovery_spool_event=event",
    ),
    "tools/lazy_deps.py": (
        '"tool.doc_extract": ("firecrawl-anydoc",),',
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    return parser.parse_args()


def validate(root: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    if root.is_symlink() or not (root / ".git").exists():
        raise ValueError("source root must be a real Git checkout")
    checked: list[str] = []
    sources: dict[str, str] = {}
    for relative, markers in REQUIRED_FILES.items():
        path = root / relative
        if path.resolve().parent != (root / relative).parent.resolve():
            raise ValueError(f"source path escaped checkout: {relative}")
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"required source is not a regular file: {relative}")
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))
        missing = [marker for marker in markers if marker not in source]
        if missing:
            raise ValueError(f"{relative} is missing {len(missing)} durability markers")
        sources[relative] = source
        checked.append(relative)

    run_source = sources["gateway/run.py"]
    early = run_source.index("self._flush_shutdown_queued_events()")
    teardown = run_source.index("await self._bounded_adapter_teardown(", early)
    final = run_source.index("self._flush_shutdown_queued_events()", teardown)
    clear = run_source.index("self._clear_durably_spooled_gateway_events()", final)
    session_write = run_source.index("self.async_session_store.update_session(")
    acknowledge = run_source.index("acknowledge_queued_event_spool(_spooled_event)")
    if not early < teardown < final < clear:
        raise ValueError("shutdown snapshot ordering is invalid")
    if acknowledge < session_write:
        raise ValueError("queued events are acknowledged before session persistence")
    if "_collect_queued_event_spool_ack(\n                recovery_spool_event," not in run_source:
        raise ValueError("per-event acknowledgement is not tied to the current result")

    lazy_tree = ast.parse(sources["tools/lazy_deps.py"], filename="tools/lazy_deps.py")
    lazy_deps = None
    for node in lazy_tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "LAZY_DEPS" and node.value is not None:
                lazy_deps = ast.literal_eval(node.value)
                break
    if not isinstance(lazy_deps, dict):
        raise ValueError("tools/lazy_deps.py does not define a literal LAZY_DEPS map")
    if lazy_deps.get("tool.doc_extract") != ("firecrawl-anydoc",):
        raise ValueError("document extraction is not tracking firecrawl-anydoc stable")

    todo_source = sources["agent/todo_stop.py"]
    if "max(0, min(parsed, 8))" not in todo_source:
        raise ValueError("todo stop-loop budget is not bounded")
    loop_source = sources["agent/conversation_loop.py"]
    todo_guard = loop_source.index("from agent.todo_stop import build_todo_stop_nudge")
    kanban_guard = loop_source.index("Kanban worker terminal-tool stop guard")
    if todo_guard >= kanban_guard:
        raise ValueError("todo stop-loop guard must run before the Kanban guard")

    mem0_source = sources["plugins/memory/mem0/__init__.py"]
    if "atexit.register(self._shutdown_backend)" in mem0_source:
        raise ValueError("Mem0 atexit still bypasses ordered provider shutdown")
    shutdown_start = mem0_source.index("    def shutdown(self) -> None:")
    shutdown_source = mem0_source[shutdown_start:]
    active_guard = shutdown_source.index("if active:")
    backend_close = shutdown_source.index("self._shutdown_backend()")
    if active_guard >= backend_close:
        raise ValueError("Mem0 backend can close before the active-work guard")

    return {
        "documentExtraction": "firecrawl-anydoc-stable",
        "files": checked,
        "mem0Shutdown": "bounded-fail-closed",
        "schema": 2,
        "status": "valid",
        "todoStopGuard": "opt-in-native",
    }


def main() -> int:
    try:
        result = validate(parse_args().source_root)
    except (OSError, SyntaxError, ValueError) as exc:
        print(f"hermes-queued-event-durability-error:{exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
