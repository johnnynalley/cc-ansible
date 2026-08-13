#!/usr/bin/python3
"""Emit a redacted migration inventory from an OpenClaw state database."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import quote

SCHEMA_VERSION = 1
EXPECTED_COLUMNS = {
    "store_key",
    "job_id",
    "name",
    "enabled",
    "agent_id",
    "owner_agent_id",
    "schedule_kind",
    "schedule_expr",
    "schedule_tz",
    "every_ms",
    "payload_kind",
    "payload_model",
    "payload_thinking",
    "payload_timeout_seconds",
    "payload_allow_unsafe_external_content",
    "payload_light_context",
    "payload_tools_allow_json",
    "delivery_mode",
    "delivery_channel",
    "delivery_to",
    "delivery_account_id",
    "last_run_status",
    "last_delivery_status",
    "consecutive_errors",
    "job_json",
}
SAFE_AGENT_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
SAFE_MODEL_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")
SAFE_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
PAYLOAD_KINDS = {"agentTurn", "command", "systemEvent"}
SECRET_HINT_RE = re.compile(
    r"(?:authorization|bearer|cookie|credential|password|secret|token)",
    re.IGNORECASE,
)
KNOWN_ROOTS = (
    (Path("/home/johnny/.openclaw/workspace"), "$LEGACY_WORKSPACE"),
    (Path("/opt/cc-ansible"), "$REPO"),
)
SAFE_SYSTEM_ROOTS = (Path("/bin"), Path("/sbin"), Path("/usr/bin"), Path("/usr/sbin"))
SAFE_EXECUTABLES = {"bash", "git", "node", "python3", "sh"}


class InventoryError(Exception):
    """Raised when the source database does not match the expected contract."""


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def safe_enum(value: Any, pattern: re.Pattern[str]) -> str | None:
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def normalized_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value.startswith("/") or "\x00" in value:
        return None
    path = Path(value)
    for root, label in KNOWN_ROOTS:
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        return label if not relative.parts else f"{label}/{relative.as_posix()}"
    for root in SAFE_SYSTEM_ROOTS:
        try:
            path.relative_to(root)
        except ValueError:
            continue
        return path.as_posix()
    return f"$OTHER/{fingerprint(value)}"


def parse_tools(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, str):
        raise InventoryError("invalid-tools-json")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise InventoryError("invalid-tools-json") from exc
    if not isinstance(parsed, list) or not all(
        isinstance(item, str) and SAFE_AGENT_RE.fullmatch(item) for item in parsed
    ):
        raise InventoryError("invalid-tools-json")
    return sorted(set(parsed))


def command_shape(job_json: Any) -> dict[str, Any] | None:
    if not isinstance(job_json, str):
        raise InventoryError("invalid-job-json")
    try:
        job = json.loads(job_json)
    except json.JSONDecodeError as exc:
        raise InventoryError("invalid-job-json") from exc
    payload = job.get("payload") if isinstance(job, dict) else None
    if not isinstance(payload, dict) or payload.get("kind") != "command":
        return None
    argv = payload.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(item, str) for item in argv)
    ):
        raise InventoryError("invalid-command-payload")
    path_arguments = [
        normalized for item in argv if (normalized := normalized_path(item)) is not None
    ]
    executable = normalized_path(argv[0])
    if executable is None and argv[0] in SAFE_EXECUTABLES:
        executable = argv[0]
    return {
        "argumentCount": len(argv),
        "executable": executable or f"opaque:{fingerprint(argv[0])}",
        "pathArguments": path_arguments,
        "workingDirectory": normalized_path(payload.get("cwd")),
        "secretLikeArgumentCount": sum(
            1 for item in argv if SECRET_HINT_RE.search(item)
        ),
        "timeoutSeconds": (
            payload.get("timeoutSeconds")
            if isinstance(payload.get("timeoutSeconds"), int)
            else None
        ),
    }


def lifecycle_shape(job_json: Any, schedule_kind: str) -> dict[str, Any]:
    if not isinstance(job_json, str):
        raise InventoryError("invalid-job-json")
    try:
        job = json.loads(job_json)
    except json.JSONDecodeError as exc:
        raise InventoryError("invalid-job-json") from exc
    if not isinstance(job, dict):
        raise InventoryError("invalid-job-json")
    delete_after_run = job.get("deleteAfterRun", False)
    if not isinstance(delete_after_run, bool):
        raise InventoryError("invalid-delete-after-run")
    schedule = job.get("schedule")
    if not isinstance(schedule, dict) or schedule.get("kind") != schedule_kind:
        raise InventoryError("schedule-kind-drift")
    at = schedule.get("at")
    if schedule_kind == "at":
        if not isinstance(at, str) or not SAFE_AT_RE.fullmatch(at):
            raise InventoryError("invalid-at-schedule")
    elif at is not None:
        raise InventoryError("unexpected-at-schedule")
    return {
        "deleteAfterRun": delete_after_run,
        "at": at,
    }


def open_database(path: Path) -> sqlite3.Connection:
    resolved = path.resolve(strict=True)
    database = sqlite3.connect(
        f"file:{quote(str(resolved))}?mode=ro",
        uri=True,
    )
    database.row_factory = sqlite3.Row
    database.execute("PRAGMA query_only = ON")
    return database


def inventory_database(path: Path) -> dict[str, Any]:
    with closing(open_database(path)) as database:
        quick_check = database.execute("PRAGMA quick_check").fetchone()[0]
        if quick_check != "ok":
            raise InventoryError("database-quick-check-failed")
        columns = {row[1] for row in database.execute("PRAGMA table_info(cron_jobs)")}
        if not EXPECTED_COLUMNS.issubset(columns):
            raise InventoryError("unsupported-cron-schema")
        rows = database.execute("""
            SELECT store_key, job_id, name, enabled, agent_id, owner_agent_id,
                   schedule_kind, schedule_expr, schedule_tz, every_ms,
                   payload_kind, payload_model, payload_thinking,
                   payload_timeout_seconds,
                   payload_allow_unsafe_external_content,
                   payload_light_context, payload_tools_allow_json,
                   delivery_mode, delivery_channel, delivery_to,
                   delivery_account_id, last_run_status,
                   last_delivery_status, consecutive_errors, job_json
              FROM cron_jobs
             ORDER BY sort_order, name
            """).fetchall()

    jobs: list[dict[str, Any]] = []
    payload_counts: Counter[str] = Counter()
    owner_counts: Counter[str] = Counter()
    for row in rows:
        payload_kind = row["payload_kind"]
        if payload_kind not in PAYLOAD_KINDS:
            raise InventoryError("invalid-payload-kind")
        owner = safe_enum(
            row["owner_agent_id"] or row["agent_id"],
            SAFE_AGENT_RE,
        )
        payload_counts[payload_kind] += 1
        owner_counts[owner or "unowned"] += 1
        lifecycle = lifecycle_shape(row["job_json"], row["schedule_kind"])
        job = {
            "fingerprint": fingerprint(f"{row['store_key']}\0{row['job_id']}"),
            "name": row["name"] if isinstance(row["name"], str) else None,
            "enabled": bool(row["enabled"]),
            "ownerAgent": owner,
            "schedule": {
                "kind": row["schedule_kind"],
                "expression": row["schedule_expr"],
                "timezone": row["schedule_tz"],
                "everyMs": row["every_ms"],
                "at": lifecycle["at"],
            },
            "deleteAfterRun": lifecycle["deleteAfterRun"],
            "payload": {
                "kind": payload_kind,
                "model": safe_enum(row["payload_model"], SAFE_MODEL_RE),
                "thinking": row["payload_thinking"],
                "timeoutSeconds": row["payload_timeout_seconds"],
                "allowUnsafeExternalContent": bool(
                    row["payload_allow_unsafe_external_content"]
                ),
                "lightContext": bool(row["payload_light_context"]),
                "toolsAllow": parse_tools(row["payload_tools_allow_json"]),
                "command": command_shape(row["job_json"]),
            },
            "delivery": {
                "mode": row["delivery_mode"],
                "channel": row["delivery_channel"],
                "hasRecipient": bool(row["delivery_to"]),
                "hasAccount": bool(row["delivery_account_id"]),
            },
            "state": {
                "lastRunStatus": row["last_run_status"],
                "lastDeliveryStatus": row["last_delivery_status"],
                "consecutiveErrors": row["consecutive_errors"],
            },
        }
        jobs.append(job)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "databaseQuickCheck": quick_check,
        "summary": {
            "jobCount": len(jobs),
            "enabledCount": sum(1 for job in jobs if job["enabled"]),
            "payloadKinds": dict(sorted(payload_counts.items())),
            "owners": dict(sorted(owner_counts.items())),
        },
        "jobs": jobs,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = inventory_database(args.database)
    except (InventoryError, OSError, sqlite3.Error):
        result = {
            "schemaVersion": SCHEMA_VERSION,
            "status": "error",
            "errorCode": "inventory-failed",
        }
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
