#!/usr/bin/env python3
"""Disable Profilarr scheduled Arr upgrade jobs with a SQLite backup.

Run this on docker-vm. It disables the Profilarr upgrade_configs rows for
Sonarr/Radarr and cancels queued scheduled arr.upgrade jobs. It does not modify
PCD database auto-pull/sync jobs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB = Path("/opt/profilarr/config/data/profilarr.db")
DEFAULT_BACKUP_DIR = Path("/opt/profilarr/config/data/backups")


def utc_stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def connect(path: Path, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    else:
        conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def create_sqlite_backup(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"profilarr-pre-disable-upgrade-jobs-{utc_stamp()}.db"
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


def fetch_upgrade_configs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        row_dict(row)
        for row in conn.execute(
            """
            SELECT u.id, a.name AS arr, a.type, u.enabled, u.cron,
                   u.next_run_at, u.last_run_at
            FROM upgrade_configs u
            JOIN arr_instances a ON a.id = u.arr_instance_id
            ORDER BY a.name
            """
        )
    ]


def fetch_scheduled_jobs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        row_dict(row)
        for row in conn.execute(
            """
            SELECT id, job_type, status, run_at, source, dedupe_key
            FROM job_queue
            WHERE job_type = 'arr.upgrade'
              AND source = 'schedule'
              AND status IN ('queued', 'pending', 'retry')
            ORDER BY id
            """
        )
    ]


def print_state(label: str, configs: list[dict[str, Any]], jobs: list[dict[str, Any]]) -> None:
    print(label)
    print("Upgrade configs:")
    for row in configs:
        print(
            "  - {arr} enabled={enabled} cron={cron} next={next_run_at} "
            "last={last_run_at}".format(**row)
        )
    print("Queued scheduled arr.upgrade jobs:")
    if not jobs:
        print("  - none")
    for row in jobs:
        print(
            "  - #{id} {status} run_at={run_at} dedupe={dedupe_key}".format(**row)
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    conn = connect(args.db, read_only=args.dry_run)
    try:
        before_configs = fetch_upgrade_configs(conn)
        before_jobs = fetch_scheduled_jobs(conn)
        print_state("Before:", before_configs, before_jobs)

        enabled_configs = [row for row in before_configs if row["enabled"]]
        if not enabled_configs and not before_jobs:
            print("No Profilarr scheduled upgrade changes needed.")
            return 0

        if args.dry_run:
            print("Dry run only; no backup or DB update written.")
            return 0

        backup_path = create_sqlite_backup(args.db, args.backup_dir)
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
        conn.commit()

        after_configs = fetch_upgrade_configs(conn)
        after_jobs = fetch_scheduled_jobs(conn)
        print(f"Backup: {backup_path}")
        print_state("After:", after_configs, after_jobs)
        print("Disabled Profilarr scheduled Arr upgrade jobs.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
