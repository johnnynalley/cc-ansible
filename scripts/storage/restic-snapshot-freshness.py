#!/usr/bin/env python3
"""Validate that a Restic repository has a recent, complete host snapshot."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import subprocess
import sys
from typing import Any


class FreshnessError(RuntimeError):
    """A bounded snapshot freshness failure."""


def parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise FreshnessError("snapshot-time-missing")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise FreshnessError("snapshot-time-invalid") from exc
    if parsed.tzinfo is None:
        raise FreshnessError("snapshot-time-naive")
    return parsed.astimezone(timezone.utc)


def evaluate_snapshots(
    snapshots: Any,
    *,
    host: str,
    max_age_seconds: int,
    required_paths: list[str],
    now: datetime | None = None,
) -> dict[str, Any]:
    if not isinstance(snapshots, list):
        raise FreshnessError("snapshot-json-not-list")
    if not snapshots:
        raise FreshnessError("snapshot-missing")

    rows = [row for row in snapshots if isinstance(row, dict)]
    if len(rows) != len(snapshots):
        raise FreshnessError("snapshot-row-invalid")
    matching = [row for row in rows if row.get("hostname") == host]
    if not matching:
        raise FreshnessError("snapshot-host-missing")

    latest = max(matching, key=lambda row: parse_timestamp(row.get("time")))
    snapshot_time = parse_timestamp(latest.get("time"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = int((current - snapshot_time).total_seconds())
    if age < -300:
        raise FreshnessError("snapshot-time-in-future")
    if age > max_age_seconds:
        raise FreshnessError("snapshot-stale")

    paths = latest.get("paths")
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise FreshnessError("snapshot-paths-invalid")
    missing = sorted(set(required_paths) - set(paths))
    if missing:
        raise FreshnessError("snapshot-required-path-missing")

    snapshot_id = latest.get("id")
    return {
        "ageSeconds": max(age, 0),
        "host": host,
        "requiredPathCount": len(required_paths),
        "schemaVersion": 1,
        "snapshotId": snapshot_id[:8] if isinstance(snapshot_id, str) else None,
        "status": "ok",
    }


def load_snapshots(restic_bin: str, host: str) -> Any:
    try:
        completed = subprocess.run(
            [
                restic_bin,
                "--no-lock",
                "snapshots",
                "--json",
                "--latest",
                "1",
                "--host",
                host,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise FreshnessError("restic-command-timeout") from exc
    if completed.returncode != 0:
        raise FreshnessError(f"restic-command-failed:{completed.returncode}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise FreshnessError("restic-json-invalid") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--max-age-seconds", type=int, required=True)
    parser.add_argument("--require-path", action="append", default=[])
    parser.add_argument("--restic-bin", default="/usr/bin/restic")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.max_age_seconds <= 0:
        print(json.dumps({"reason": "max-age-invalid", "status": "failed"}))
        return 2
    try:
        result = evaluate_snapshots(
            load_snapshots(args.restic_bin, args.host),
            host=args.host,
            max_age_seconds=args.max_age_seconds,
            required_paths=args.require_path,
        )
    except (FreshnessError, OSError, subprocess.SubprocessError) as exc:
        reason = str(exc) if isinstance(exc, FreshnessError) else "checker-runtime-failed"
        print(
            json.dumps(
                {
                    "host": args.host,
                    "reason": reason,
                    "schemaVersion": 1,
                    "status": "failed",
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
