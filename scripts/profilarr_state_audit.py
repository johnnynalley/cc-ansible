#!/usr/bin/env python3
"""Audit local Profilarr database, scheduler, and upgrade-job state.

Run this on media-vm. It reads Profilarr's SQLite database only and prints no
secrets.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DB = "/opt/profilarr/config/data/profilarr.db"


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    if "T" not in normalized and "+" not in normalized:
        normalized = normalized + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fetch_all(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [row_dict(row) for row in conn.execute(sql, params).fetchall()]


def audit(db_path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc)

    databases = fetch_all(
        conn,
        """
        SELECT id, name, repository_url, enabled, auto_pull, sync_strategy,
               local_ops_enabled, last_synced_at
        FROM database_instances
        ORDER BY name
        """,
    )
    upgrade_configs = fetch_all(
        conn,
        """
        SELECT u.id, a.name AS arr, a.type, u.arr_instance_id, u.enabled, u.cron,
               u.next_run_at, u.last_run_at, u.filter_mode, u.filters
        FROM upgrade_configs u
        JOIN arr_instances a ON a.id = u.arr_instance_id
        ORDER BY a.name
        """,
    )
    job_queue = fetch_all(
        conn,
        """
        SELECT id, job_type, status, run_at, payload, source, dedupe_key,
               attempts, started_at, finished_at, created_at, updated_at
        FROM job_queue
        WHERE job_type IN ('arr.upgrade', 'pcd.link', 'pcd.sync')
        ORDER BY id DESC
        LIMIT 20
        """,
    )
    upgrade_runs = fetch_all(
        conn,
        """
        SELECT id, instance_id, started_at, completed_at, status, dry_run, cron,
               filter_name, selected_count, searches_triggered, successful,
               failed, errors
        FROM upgrade_runs
        ORDER BY started_at DESC
        LIMIT 20
        """,
    )

    active_by_dedupe = {
        row.get("dedupe_key")
        for row in job_queue
        if row.get("status") in {"queued", "running"} and row.get("dedupe_key")
    }
    warnings: list[str] = []
    for config in upgrade_configs:
        if not config.get("enabled"):
            continue
        dedupe_key = f"arr.upgrade:{config['arr_instance_id']}"
        next_run = parse_time(config.get("next_run_at"))
        if dedupe_key not in active_by_dedupe and next_run and next_run <= now:
            warnings.append(
                f"{config['arr']} upgrade config is enabled but has no queued schedule; "
                f"next_run_at={config.get('next_run_at')} is due/past"
            )

    return {
        "database_path": str(db_path),
        "checked_at": now.isoformat(),
        "warnings": warnings,
        "databases": databases,
        "upgrade_configs": upgrade_configs,
        "job_queue": job_queue,
        "upgrade_runs": upgrade_runs,
    }


def print_text(report: dict[str, Any]) -> None:
    print(f"Profilarr DB: {report['database_path']}")
    print(f"Checked at: {report['checked_at']}")
    if report["warnings"]:
        print("Warnings:")
        for warning in report["warnings"]:
            print(f"  - {warning}")
    else:
        print("Warnings: none")

    print("Databases:")
    for row in report["databases"]:
        print(
            "  - {name} enabled={enabled} auto_pull={auto_pull} sync={sync_strategy}m "
            "last_synced={last_synced_at} repo={repository_url}".format(**row)
        )

    print("Upgrade configs:")
    for row in report["upgrade_configs"]:
        print(
            "  - {arr} enabled={enabled} cron={cron} next={next_run_at} "
            "last={last_run_at}".format(**row)
        )
        try:
            filters = json.loads(row.get("filters") or "[]")
        except (TypeError, json.JSONDecodeError):
            filters = []
        for filter_config in filters:
            print(
                "    filter={name} enabled={enabled} selector={selector} "
                "count={count} tag={tag}".format(
                    name=filter_config.get("name") or filter_config.get("id"),
                    enabled=filter_config.get("enabled"),
                    selector=filter_config.get("selector"),
                    count=filter_config.get("count"),
                    tag=filter_config.get("tag") or "",
                )
            )

    print("Recent queued jobs:")
    for row in report["job_queue"][:10]:
        print(
            "  - #{id} {job_type} {status} run_at={run_at} source={source} "
            "dedupe={dedupe_key}".format(**row)
        )

    print("Recent upgrade runs:")
    for row in report["upgrade_runs"][:10]:
        print(
            "  - {started_at} instance={instance_id} status={status} dry_run={dry_run} "
            "searched={searches_triggered} ok={successful} failed={failed} "
            "filter={filter_name}".format(**row)
        )
        errors = row.get("errors")
        if errors:
            try:
                parsed_errors = json.loads(errors)
            except (TypeError, json.JSONDecodeError):
                parsed_errors = [str(errors)]
            for error in parsed_errors[:3]:
                print(f"    error={error}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit(Path(args.db))
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        print_text(report)
    return 1 if report["warnings"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
