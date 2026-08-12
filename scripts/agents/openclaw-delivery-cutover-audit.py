#!/usr/bin/env python3
"""Audit replay-capable OpenClaw delivery state without exposing message data."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import stat
import tempfile
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import quote

SCHEMA_VERSION = 1
SAFE_AGENT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
KNOWN_QUEUE_STATUSES = {"pending", "failed"}
REQUIRED_QUEUE_COLUMNS = {
    "queue_name",
    "id",
    "status",
    "entry_kind",
    "session_key",
    "channel",
    "target",
    "account_id",
    "retry_count",
    "last_attempt_at",
    "last_error",
    "recovery_state",
    "platform_send_started_at",
    "entry_json",
    "enqueued_at",
    "updated_at",
    "failed_at",
}
DELIVERY_RECOVERY_FIELDS = {
    "pendingFinalDelivery",
    "pendingFinalDeliveryAttemptCount",
    "pendingFinalDeliveryContext",
    "pendingFinalDeliveryCreatedAt",
    "pendingFinalDeliveryIntentId",
    "pendingFinalDeliveryLastAttemptAt",
    "pendingFinalDeliveryLastError",
    "pendingFinalDeliveryText",
    "restartRecoveryDeliveryContext",
    "restartRecoveryDeliveryRunId",
}


class DeliveryAuditError(RuntimeError):
    """Raised when delivery state cannot be classified safely."""


def _regular_file(path: Path, label: str) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise DeliveryAuditError(f"{label}-unavailable") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise DeliveryAuditError(f"{label}-not-regular-file")
    return path.resolve()


def _open_database(path: Path) -> sqlite3.Connection:
    resolved = _regular_file(path, "database")
    database = sqlite3.connect(
        f"file:{quote(str(resolved))}?mode=ro",
        uri=True,
    )
    database.row_factory = sqlite3.Row
    database.execute("PRAGMA query_only = ON")
    return database


def _database_inventory(path: Path) -> dict[str, Any]:
    with closing(_open_database(path)) as database:
        quick_check = database.execute("PRAGMA quick_check").fetchone()[0]
        if quick_check != "ok":
            raise DeliveryAuditError("database-quick-check-failed")
        table = database.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'delivery_queue_entries'"
        ).fetchone()
        if table is None:
            raise DeliveryAuditError("delivery-queue-table-missing")
        columns = {
            str(row[1])
            for row in database.execute(
                "PRAGMA table_info(delivery_queue_entries)"
            ).fetchall()
        }
        if not REQUIRED_QUEUE_COLUMNS.issubset(columns):
            raise DeliveryAuditError("unsupported-delivery-queue-schema")
        rows = database.execute(
            "SELECT status, COUNT(*) AS entry_count "
            "FROM delivery_queue_entries GROUP BY status ORDER BY status"
        ).fetchall()

    status_counts = {str(row["status"]): int(row["entry_count"]) for row in rows}
    unknown_statuses = sorted(set(status_counts) - KNOWN_QUEUE_STATUSES)
    if unknown_statuses:
        raise DeliveryAuditError("unknown-delivery-queue-status")
    return {
        "quickCheck": quick_check,
        "entries": sum(status_counts.values()),
        "statusCounts": status_counts,
        "pending": status_counts.get("pending", 0),
        "failedHistory": status_counts.get("failed", 0),
    }


def _read_session_index(path: Path) -> dict[str, Any]:
    resolved = _regular_file(path, "session-index")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeliveryAuditError("session-index-invalid-json") from exc
    if not isinstance(payload, dict):
        raise DeliveryAuditError("session-index-invalid-shape")
    return payload


def _session_inventory(indexes: dict[str, Path]) -> dict[str, Any]:
    agents: list[dict[str, Any]] = []
    aggregate_fields: Counter[str] = Counter()
    aggregate_entries = 0
    for agent, path in sorted(indexes.items()):
        payload = _read_session_index(path)
        fields: Counter[str] = Counter()
        entries = 0
        for entry in payload.values():
            if not isinstance(entry, dict) or entry.get("archivedAt") is not None:
                continue
            present = DELIVERY_RECOVERY_FIELDS.intersection(entry)
            if present:
                entries += 1
                fields.update(present)
        aggregate_entries += entries
        aggregate_fields.update(fields)
        agents.append(
            {
                "agent": agent,
                "activeRecoveryEntries": entries,
                "activeRecoveryFields": dict(sorted(fields.items())),
            }
        )
    return {
        "agents": agents,
        "activeRecoveryEntries": aggregate_entries,
        "activeRecoveryFields": dict(sorted(aggregate_fields.items())),
    }


def audit_delivery_state(database: Path, indexes: dict[str, Path]) -> dict[str, Any]:
    if not indexes:
        raise DeliveryAuditError("session-index-set-empty")
    queue = _database_inventory(database)
    sessions = _session_inventory(indexes)
    blockers = []
    if queue["pending"]:
        blockers.append("pending-database-delivery")
    if sessions["activeRecoveryEntries"]:
        blockers.append("active-session-delivery-recovery")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "clean" if not blockers else "blocked",
        "blockers": blockers,
        "database": queue,
        "sessions": sessions,
    }


def _parse_session_index(value: str) -> tuple[str, Path]:
    agent, separator, path = value.partition("=")
    if not separator or not SAFE_AGENT_RE.fullmatch(agent) or not path:
        raise argparse.ArgumentTypeError("expected AGENT=/absolute/sessions.json")
    candidate = Path(path)
    if not candidate.is_absolute():
        raise argparse.ArgumentTypeError("session index path must be absolute")
    return agent, candidate


def _write_json_atomic(path: Path, payload: Any) -> None:
    parent = path.parent.resolve(strict=True)
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise DeliveryAuditError("output-not-regular-file")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise DeliveryAuditError("output-write-failed") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument(
        "--session-index",
        required=True,
        action="append",
        type=_parse_session_index,
        dest="session_indexes",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--require-clean", action="store_true")
    arguments = parser.parse_args()
    indexes = dict(arguments.session_indexes)
    if len(indexes) != len(arguments.session_indexes):
        print(json.dumps({"status": "error", "errorCode": "duplicate-agent"}))
        return 1
    try:
        report = audit_delivery_state(arguments.database, indexes)
        _write_json_atomic(arguments.output, report)
    except (DeliveryAuditError, OSError, sqlite3.Error):
        print(
            json.dumps(
                {"status": "error", "errorCode": "delivery-audit-failed"},
                sort_keys=True,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "status": report["status"],
                "blockers": report["blockers"],
                "pendingDatabaseDeliveries": report["database"]["pending"],
                "activeSessionRecoveryEntries": report["sessions"][
                    "activeRecoveryEntries"
                ],
            },
            sort_keys=True,
        )
    )
    if arguments.require_clean and report["status"] != "clean":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
