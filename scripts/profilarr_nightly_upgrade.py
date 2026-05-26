#!/usr/bin/env python3
"""Queue controlled Profilarr upgrade jobs for the overnight coordinator.

Run on docker-vm as the johnny user. The helper keeps Profilarr's native
scheduled Arr upgrades disabled and queues explicit nightly arr.upgrade jobs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shlex
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any


DEFAULT_DB = Path("/opt/profilarr/config/data/profilarr.db")
DEFAULT_BACKUP_DIR = Path("/opt/profilarr/config/data/backups")


def argv_from_forced_command() -> list[str]:
    original = os.environ.get("SSH_ORIGINAL_COMMAND")
    if not original:
        return sys.argv[1:]
    return shlex.split(original)


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def utc_stamp() -> str:
    return utc_now().strftime("%Y%m%dT%H%M%SZ")


def iso_now() -> str:
    return utc_now().isoformat(timespec="milliseconds").replace("+00:00", "Z")


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def connect(path: Path, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    else:
        conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def create_sqlite_backup(db_path: Path, backup_dir: Path, reason: str) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"profilarr-nightly-{reason}-{utc_stamp()}.db"
    source = connect(db_path, read_only=True)
    try:
        target = sqlite3.connect(backup_path)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    shutil.copystat(db_path, backup_path, follow_symlinks=True)
    return backup_path


def fetch_all(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [row_dict(row) for row in conn.execute(sql, params).fetchall()]


def active_upgrade_jobs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return fetch_all(
        conn,
        """
        SELECT id, status, run_at, source, dedupe_key
        FROM job_queue
        WHERE job_type = 'arr.upgrade'
          AND status IN ('queued', 'pending', 'running', 'retry')
        ORDER BY id
        """,
    )


def upgrade_configs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return fetch_all(
        conn,
        """
        SELECT u.id AS config_id, a.id AS instance_id, a.name AS arr, a.type,
               a.enabled AS arr_enabled, u.enabled, u.filters
        FROM upgrade_configs u
        JOIN arr_instances a ON a.id = u.arr_instance_id
        WHERE a.enabled != 0
        ORDER BY a.name
        """,
    )


def scheduled_upgrade_work(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    enabled = fetch_all(
        conn,
        """
        SELECT u.id, a.name AS arr, u.enabled, u.next_run_at
        FROM upgrade_configs u
        JOIN arr_instances a ON a.id = u.arr_instance_id
        WHERE u.enabled != 0
        ORDER BY a.name
        """,
    )
    queued = fetch_all(
        conn,
        """
        SELECT id, status, run_at, source, dedupe_key
        FROM job_queue
        WHERE job_type = 'arr.upgrade'
          AND source = 'schedule'
          AND status IN ('queued', 'pending', 'retry')
        ORDER BY id
        """,
    )
    return enabled, queued


def ensure_native_scheduler_disabled(conn: sqlite3.Connection, db_path: Path, backup_dir: Path) -> Path | None:
    enabled, queued = scheduled_upgrade_work(conn)
    if not enabled and not queued:
        return None
    backup_path = create_sqlite_backup(db_path, backup_dir, "pre-disable-native")
    conn.execute(
        """
        UPDATE upgrade_configs
        SET enabled = 0,
            next_run_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE enabled != 0
        """
    )
    conn.execute(
        """
        UPDATE job_queue
        SET status = 'cancelled',
            finished_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE job_type = 'arr.upgrade'
          AND source = 'schedule'
          AND status IN ('queued', 'pending', 'retry')
        """
    )
    return backup_path


def filter_enabled(config: dict[str, Any]) -> bool:
    try:
        filters = json.loads(config.get("filters") or "[]")
    except json.JSONDecodeError:
        return False
    return any(item.get("enabled") for item in filters)


def cmd_enqueue(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    try:
        backup = ensure_native_scheduler_disabled(conn, args.db, args.backup_dir)
        if backup:
            print(f"Disabled native Profilarr scheduled Arr upgrades; backup={backup}")

        active = active_upgrade_jobs(conn)
        if active:
            print("Profilarr arr.upgrade job already active; not queueing another cycle.")
            for row in active:
                print(
                    "  - #{id} {status} run_at={run_at} source={source} dedupe={dedupe_key}".format(**row)
                )
            conn.commit()
            return 0

        configs = [config for config in upgrade_configs(conn) if filter_enabled(config)]
        if not configs:
            print("No enabled Profilarr upgrade filters found.")
            conn.commit()
            return 0

        run_at = iso_now()
        queued = 0
        for config in configs:
            dedupe = f"arr.upgrade.nightly:{args.window_id}:{args.slot}:{config['instance_id']}"
            exists = conn.execute(
                "SELECT id FROM job_queue WHERE dedupe_key = ?",
                (dedupe,),
            ).fetchone()
            if exists:
                print(f"{config['arr']} nightly job already exists for {args.slot}.")
                continue
            payload = json.dumps(
                {"instanceId": config["instance_id"], "dryRun": False},
                separators=(",", ":"),
            )
            conn.execute(
                """
                INSERT INTO job_queue (
                    job_type, status, run_at, payload, source, dedupe_key,
                    created_at, updated_at
                )
                VALUES ('arr.upgrade', 'queued', ?, ?, 'nightly', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (run_at, payload, dedupe),
            )
            queued += 1
            print(f"Queued {config['arr']} Profilarr upgrade for slot {args.slot}.")

        conn.commit()
        print(f"Queued {queued} Profilarr upgrade job(s).")
        return 0
    finally:
        conn.close()


def cmd_status(args: argparse.Namespace) -> int:
    conn = connect(args.db, read_only=True)
    try:
        report = {
            "active_upgrade_jobs": active_upgrade_jobs(conn),
            "scheduled_upgrade_work": scheduled_upgrade_work(conn),
            "upgrade_configs": upgrade_configs(conn),
        }
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
        return 0
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    sub = parser.add_subparsers(dest="command", required=True)

    enqueue = sub.add_parser("enqueue")
    enqueue.add_argument("--window-id", required=True)
    enqueue.add_argument("--slot", required=True)
    enqueue.set_defaults(func=cmd_enqueue)

    status = sub.add_parser("status")
    status.set_defaults(func=cmd_status)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args(argv_from_forced_command())
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
