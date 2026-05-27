#!/usr/bin/env python3
"""Gate Profilarr upgrade scheduling for the overnight coordinator.

Run on docker-vm as the johnny user. The helper opens and closes Profilarr's
native Arr upgrade scheduler instead of inserting queue rows directly.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_DB = Path("/opt/profilarr/config/data/profilarr.db")
DEFAULT_BACKUP_DIR = Path("/opt/profilarr/config/data/backups")
DEFAULT_WAKE_COMMAND = "docker restart profilarr"
DEFAULT_UPGRADE_CRON = "0 * * * *"


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
               a.enabled AS arr_enabled, u.enabled, u.cron, u.next_run_at, u.filters
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
          AND (NULLIF(TRIM(u.cron), '') IS NOT NULL OR u.next_run_at IS NOT NULL)
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


def filter_enabled(config: dict[str, Any]) -> bool:
    try:
        filters = json.loads(config.get("filters") or "[]")
    except json.JSONDecodeError:
        return False
    return any(item.get("enabled") for item in filters)


def configured_upgrade_configs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [config for config in upgrade_configs(conn) if filter_enabled(config)]


def open_upgrade_window(
    conn: sqlite3.Connection,
    db_path: Path,
    backup_dir: Path,
    cron: str,
    run_now: bool,
) -> tuple[Path | None, int]:
    configs = configured_upgrade_configs(conn)
    if not configs:
        return None, 0

    run_at = iso_now() if run_now else None
    backup_path = create_sqlite_backup(db_path, backup_dir, "pre-open-upgrade-window")
    for config in configs:
        conn.execute(
            """
            UPDATE upgrade_configs
            SET enabled = 1,
                cron = ?,
                next_run_at = COALESCE(?, next_run_at),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (cron, run_at, config["config_id"]),
        )
    return backup_path, len(configs)


def close_upgrade_window(
    conn: sqlite3.Connection,
    db_path: Path,
    backup_dir: Path,
) -> tuple[Path | None, int, int]:
    active_configs = [config for config in upgrade_configs(conn) if config.get("enabled") != 0]
    _, queued = scheduled_upgrade_work(conn)
    if not active_configs and not queued:
        return None, 0, 0

    backup_path = create_sqlite_backup(db_path, backup_dir, "pre-close-upgrade-window")
    conn.execute(
        """
        UPDATE upgrade_configs
        SET enabled = 0,
            next_run_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE enabled != 0
        """
    )
    cancelled = conn.execute(
        """
        UPDATE job_queue
        SET status = 'cancelled',
            finished_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE job_type = 'arr.upgrade'
          AND source = 'schedule'
          AND status IN ('queued', 'pending', 'retry')
        """
    ).rowcount
    return backup_path, len(active_configs), int(cancelled or 0)


def wake_dispatcher(args: argparse.Namespace, reason: str) -> int:
    if args.no_wake:
        return 0
    command = shlex.split(args.wake_command)
    if not command:
        return 0
    result = subprocess.run(command, check=False, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    if result.returncode != 0:
        print(
            f"Failed to wake Profilarr dispatcher after {reason}; command exited {result.returncode}.",
            file=sys.stderr,
        )
        return result.returncode
    print(f"Woke Profilarr dispatcher after {reason}: {args.wake_command}")
    return 0


def cmd_open_window(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    try:
        backup, opened = open_upgrade_window(
            conn,
            args.db,
            args.backup_dir,
            args.cron,
            args.run_now,
        )
        conn.commit()
        if backup:
            print(f"Opened Profilarr upgrade window for {opened} config(s); backup={backup}")
            return wake_dispatcher(args, "opening the upgrade window")
        print("No Profilarr upgrade filters found; upgrade window was not opened.")
        return 0
    finally:
        conn.close()


def cmd_close_window(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    try:
        backup, disabled, cancelled = close_upgrade_window(conn, args.db, args.backup_dir)
        conn.commit()
        if backup:
            print(
                "Closed Profilarr upgrade window: "
                f"disabled={disabled} cancelled_scheduled_jobs={cancelled} backup={backup}"
            )
            if cancelled:
                return wake_dispatcher(args, "closing the upgrade window")
            return 0
        print("Profilarr upgrade window already closed.")
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

    open_window = sub.add_parser("open-window")
    open_window.add_argument("--cron", default=DEFAULT_UPGRADE_CRON)
    open_window.add_argument("--run-now", dest="run_now", action="store_true", default=True)
    open_window.add_argument("--no-run-now", dest="run_now", action="store_false")
    open_window.add_argument("--wake-command", default=DEFAULT_WAKE_COMMAND)
    open_window.add_argument("--no-wake", action="store_true")
    open_window.set_defaults(func=cmd_open_window)

    close_window = sub.add_parser("close-window")
    close_window.add_argument("--wake-command", default=DEFAULT_WAKE_COMMAND)
    close_window.add_argument("--no-wake", action="store_true")
    close_window.set_defaults(func=cmd_close_window)

    enqueue = sub.add_parser("enqueue", help=argparse.SUPPRESS)
    enqueue.add_argument("--window-id")
    enqueue.add_argument("--slot")
    enqueue.add_argument("--cron", default=DEFAULT_UPGRADE_CRON)
    enqueue.add_argument("--run-now", dest="run_now", action="store_true", default=True)
    enqueue.add_argument("--no-run-now", dest="run_now", action="store_false")
    enqueue.add_argument("--wake-command", default=DEFAULT_WAKE_COMMAND)
    enqueue.add_argument("--no-wake", action="store_true")
    enqueue.set_defaults(func=cmd_open_window)

    status = sub.add_parser("status")
    status.set_defaults(func=cmd_status)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args(argv_from_forced_command())
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
