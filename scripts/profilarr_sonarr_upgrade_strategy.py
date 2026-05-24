#!/usr/bin/env python3
"""Adjust Profilarr's Sonarr upgrade filter using supported stored settings.

Run this on media-vm. It updates Profilarr's SQLite config and creates a
SQLite backup before mutation. It does not patch Profilarr application code.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB = Path("/opt/profilarr/config/data/profilarr.db")
DEFAULT_BACKUP_DIR = Path("/opt/profilarr/config/data/backups")
SUPPORTED_SELECTORS = {
    "random",
    "oldest",
    "newest",
    "lowest_score",
    "most_popular",
    "least_popular",
    "alphabetical_asc",
    "alphabetical_desc",
}


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
    backup_path = backup_dir / f"profilarr-pre-sonarr-upgrade-strategy-{utc_stamp()}.db"
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


def load_config(conn: sqlite3.Connection, arr_name: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT u.id, a.name AS arr, a.type, u.enabled, u.cron, u.filter_mode,
               u.filters, u.current_filter_index, u.next_run_at, u.last_run_at
        FROM upgrade_configs u
        JOIN arr_instances a ON a.id = u.arr_instance_id
        WHERE lower(a.name) = lower(?) AND lower(a.type) = 'sonarr'
        """,
        (arr_name,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Sonarr Profilarr upgrade config {arr_name!r} was not found")
    data = row_dict(row)
    data["filters"] = json.loads(data.get("filters") or "[]")
    return data


def update_filters(
    filters: list[dict[str, Any]],
    filter_id: str,
    selector: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    changed: list[str] = []
    updated: list[dict[str, Any]] = []
    found = False
    for filter_config in filters:
        new_filter = dict(filter_config)
        if new_filter.get("id") == filter_id:
            found = True
            old_selector = new_filter.get("selector")
            if old_selector != selector:
                new_filter["selector"] = selector
                changed.append(f"{filter_id}.selector: {old_selector} -> {selector}")
        updated.append(new_filter)
    if not found:
        raise RuntimeError(f"filter id {filter_id!r} was not found")
    return updated, changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--arr-name", default="Sonarr")
    parser.add_argument("--filter-id", default="sonarr-cutoff-unmet")
    parser.add_argument("--selector", default="random", choices=sorted(SUPPORTED_SELECTORS))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    conn = connect(args.db, read_only=args.dry_run)
    try:
        config = load_config(conn, args.arr_name)
        updated_filters, changes = update_filters(config["filters"], args.filter_id, args.selector)
        print(f"Profilarr DB: {args.db}")
        print(f"Arr: {config['arr']} enabled={config['enabled']} cron={config['cron']}")
        print(f"Filter: {args.filter_id}")
        if not changes:
            print("No changes needed.")
            return 0
        for change in changes:
            print(f"Change: {change}")
        if args.dry_run:
            print("Dry run only; no backup or DB update written.")
            return 0

        backup_path = create_sqlite_backup(args.db, args.backup_dir)
        filters_json = json.dumps(updated_filters, separators=(",", ":"), ensure_ascii=False)
        conn.execute(
            """
            UPDATE upgrade_configs
            SET filters = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (filters_json, config["id"]),
        )
        conn.commit()
        print(f"Backup: {backup_path}")
        print("Updated Profilarr Sonarr upgrade filter.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
