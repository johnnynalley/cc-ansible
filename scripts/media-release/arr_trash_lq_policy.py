#!/usr/bin/env python3
"""Remove TRaSH LQ scoring from efficient Arr profiles.

Run this on docker-vm. Dry-run is the default. With ``--apply`` the script
backs up live Arr policy state and sets selected TRaSH LQ custom-format scores
to zero in active ``*-efficient`` quality profiles only. It also reports remaining
TRaSH-sourced negative scores so they can be reviewed separately.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sqlite3
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_BACKUP_ROOT = "/srv/live-rollbacks/docker-vm/arr-policy"
DEFAULT_PROFILARR_DB = "/opt/profilarr/config/data/profilarr.db"
DEFAULT_DATA_ROOT = "/opt/profilarr/config/data"
TRASH_LQ_NAMES = (
    "Anime LQ Groups",
    "LQ",
    "LQ (Release Title)",
)


@dataclass(frozen=True)
class ArrInstance:
    name: str
    base_url: str
    config_path: str


ARR_INSTANCES = (
    ArrInstance("sonarr", "http://127.0.0.1:8989", "/opt/media-stack/sonarr/config.xml"),
    ArrInstance("radarr", "http://127.0.0.1:7878", "/opt/media-stack/radarr/config.xml"),
)


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def request_json(
    instance: ArrInstance,
    api_key: str,
    method: str,
    path: str,
    body: Any | None = None,
    timeout: int = 90,
) -> Any:
    data = None
    headers = {"X-Api-Key": api_key}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{instance.base_url.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status == 204:
                return None
            payload = response.read()
            if not payload:
                return None
            return json.loads(payload.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{instance.name}: {method} {path} failed: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{instance.name}: {method} {path} failed: {exc.reason}") from exc


def write_snapshot(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ensure_live_rollback_mount(backup_root: Path) -> None:
    live_root = Path("/srv/live-rollbacks")
    try:
        backup_root.relative_to(live_root)
    except ValueError:
        return
    mounts = Path("/proc/mounts").read_text(encoding="utf-8").splitlines()
    if not any(line.split()[1] == str(live_root) for line in mounts if line.split()):
        raise RuntimeError(f"{live_root} is not mounted; refusing to write rollback backup to root disk")


def mark_live_rollback_cache(backup_dir: Path, timestamp: str) -> None:
    (backup_dir / "manifest.txt").write_text(
        "\n".join(
            (
                f"created_utc={timestamp}",
                "host=docker-vm",
                "domain=arr-policy",
                "name=arr-trash-lq-policy",
                "paths=",
                "  Sonarr/Radarr API policy snapshots",
                "",
            )
        ),
        encoding="utf-8",
    )
    (backup_dir / ".live-rollback-cache").write_text(
        "\n".join(
            (
                f"created_utc={timestamp}",
                "host=docker-vm",
                "domain=arr-policy",
                "",
            )
        ),
        encoding="utf-8",
    )


def snapshot_instance(
    instance: ArrInstance,
    api_key: str,
    backup_dir: Path,
) -> dict[str, Any]:
    data = {
        "custom_formats": request_json(instance, api_key, "GET", "/api/v3/customformat"),
        "quality_profiles": request_json(instance, api_key, "GET", "/api/v3/qualityprofile"),
        "queue_status": request_json(instance, api_key, "GET", "/api/v3/queue/status"),
        "commands": request_json(instance, api_key, "GET", "/api/v3/command"),
    }
    for name, value in data.items():
        write_snapshot(backup_dir / f"{instance.name}-{name.replace('_', '-')}.json", value)
    return data


def custom_format_id_from_item(item: dict[str, Any]) -> int | None:
    value = item.get("format")
    if isinstance(value, dict):
        value = value.get("id")
    if value is None:
        value = item.get("customFormatId")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def custom_format_name_from_item(
    item: dict[str, Any],
    custom_formats_by_id: dict[int, dict[str, Any]],
) -> str:
    value = item.get("format")
    if isinstance(value, dict) and value.get("name"):
        return str(value["name"])
    cf_id = custom_format_id_from_item(item)
    if cf_id is not None and cf_id in custom_formats_by_id:
        return str(custom_formats_by_id[cf_id].get("name") or f"id:{cf_id}")
    return str(item.get("name") or f"id:{cf_id}")


def profile_is_target(profile: dict[str, Any], profile_pattern: re.Pattern[str]) -> bool:
    return profile_pattern.search(str(profile.get("name") or "")) is not None


def neutralize_lq_in_profile(
    profile: dict[str, Any],
    custom_formats_by_id: dict[int, dict[str, Any]],
    lq_names: set[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = copy.deepcopy(profile)
    changed: list[dict[str, Any]] = []
    for item in payload.get("formatItems") or []:
        name = custom_format_name_from_item(item, custom_formats_by_id)
        if name not in lq_names:
            continue
        before = int(item.get("score") or 0)
        if before != 0:
            item["score"] = 0
            changed.append(
                {
                    "name": name,
                    "before": before,
                    "after": 0,
                    "custom_format_id": custom_format_id_from_item(item),
                }
            )
    return payload, changed


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def fetch_all(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [row_dict(row) for row in conn.execute(sql, params).fetchall()]


def numeric_prefix(path: Path) -> tuple[int, str]:
    match = re.match(r"^(\d+)", path.name)
    return (int(match.group(1)) if match else 10**9, path.name)


def local_database_path(data_root: Path, local_path: str) -> Path:
    prefix = "/config/data/"
    if local_path.startswith(prefix):
        return data_root / local_path[len(prefix) :]
    return Path(local_path)


def exec_sql(conn: sqlite3.Connection, sql: str) -> None:
    statement = ""
    for line in sql.splitlines(keepends=True):
        statement += line
        if not sqlite3.complete_statement(statement):
            continue
        try:
            conn.execute(statement)
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed" not in str(exc):
                raise
            conn.rollback()
        except sqlite3.OperationalError as exc:
            message = str(exc)
            if not (
                "no such column" in message
                or "has no column named" in message
                or "no such table" in message
                or "duplicate column name" in message
            ):
                raise
            conn.rollback()
        statement = ""
    if statement.strip():
        conn.execute(statement)


def materialize_trash_database(profilarr_db: Path, data_root: Path) -> sqlite3.Connection | None:
    source_conn = sqlite3.connect(f"file:{profilarr_db}?mode=ro", uri=True)
    source_conn.row_factory = sqlite3.Row
    db_row = source_conn.execute(
        """
        SELECT id, name, repository_url, local_path, last_synced_at, enabled, auto_pull
        FROM database_instances
        WHERE name = 'TRaSH Guides'
        LIMIT 1
        """
    ).fetchone()
    if db_row is None or not bool(db_row["enabled"]):
        return None

    ops = fetch_all(
        source_conn,
        """
        SELECT id, database_id, op_number, sql
        FROM pcd_ops
        WHERE state = 'published' AND database_id = ?
        ORDER BY op_number, id
        """,
        (db_row["id"],),
    )

    repo_path = local_database_path(data_root, db_row["local_path"])
    schema_ops = sorted((repo_path / "deps" / "schema" / "ops").glob("*.sql"), key=numeric_prefix)
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")
    for path in schema_ops:
        exec_sql(conn, path.read_text(encoding="utf-8"))
    for row in sorted(ops, key=lambda item: (item.get("op_number") or 0, item["id"])):
        exec_sql(conn, row["sql"])
    return conn


def trash_source_map(profilarr_db: Path, data_root: Path) -> dict[str, str]:
    conn = materialize_trash_database(profilarr_db, data_root)
    if conn is None:
        return {}
    rows = fetch_all(conn, "SELECT DISTINCT name FROM custom_formats ORDER BY name")
    return {str(row["name"]): f"TRaSH Guides:{row['name']}" for row in rows}


def remaining_trash_negatives(
    profiles: list[dict[str, Any]],
    custom_formats_by_id: dict[int, dict[str, Any]],
    profile_pattern: re.Pattern[str],
    source_by_name: dict[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for profile in profiles:
        if not profile_is_target(profile, profile_pattern):
            continue
        for item in profile.get("formatItems") or []:
            score = int(item.get("score") or 0)
            if score >= 0:
                continue
            name = custom_format_name_from_item(item, custom_formats_by_id)
            source = source_by_name.get(name)
            if source is None:
                continue
            rows.append(
                {
                    "profile": profile.get("name"),
                    "custom_format": name,
                    "score": score,
                    "source": source,
                }
            )
    return rows


def process_instance(
    instance: ArrInstance,
    data: dict[str, Any],
    apply: bool,
    profile_pattern: re.Pattern[str],
    lq_names: set[str],
    trash_sources: dict[str, str],
) -> dict[str, Any]:
    api_key = read_api_key(instance.config_path)
    custom_formats = data["custom_formats"]
    profiles = data["quality_profiles"]
    custom_formats_by_id = {int(cf["id"]): cf for cf in custom_formats if isinstance(cf.get("id"), int)}

    changes: list[dict[str, Any]] = []
    projected_profiles: list[dict[str, Any]] = []
    for profile in profiles:
        if not profile_is_target(profile, profile_pattern):
            projected_profiles.append(profile)
            continue
        payload, changed = neutralize_lq_in_profile(profile, custom_formats_by_id, lq_names)
        if changed:
            profile_id = profile.get("id")
            if not isinstance(profile_id, int):
                raise RuntimeError(f"{instance.name}: profile {profile.get('name')!r} has no numeric id")
            changes.append(
                {
                    "profile": profile.get("name"),
                    "profile_id": profile_id,
                    "neutralized": changed,
                }
            )
            if apply:
                request_json(instance, api_key, "PUT", f"/api/v3/qualityprofile/{profile_id}", payload)
            projected_profiles.append(payload)
        else:
            projected_profiles.append(profile)

    return {
        "instance": instance.name,
        "changed": bool(changes),
        "changes": changes,
        "remaining_trash_negatives": remaining_trash_negatives(
            projected_profiles,
            custom_formats_by_id,
            profile_pattern,
            trash_sources,
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write updated profiles")
    parser.add_argument("--backup-root", default=DEFAULT_BACKUP_ROOT)
    parser.add_argument("--profilarr-db", default=DEFAULT_PROFILARR_DB)
    parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    parser.add_argument(
        "--profile-regex",
        default=r"-efficient$",
        help="quality profile names to update/audit; default targets active efficient profiles",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    profile_pattern = re.compile(args.profile_regex)
    lq_names = set(TRASH_LQ_NAMES)
    trash_sources = trash_source_map(Path(args.profilarr_db), Path(args.data_root))

    backup_dir: Path | None = None
    if args.apply:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_root = Path(args.backup_root)
        ensure_live_rollback_mount(backup_root)
        backup_dir = backup_root / f"{timestamp}-arr-trash-lq-policy"
        backup_dir.mkdir(parents=True, exist_ok=False)
        mark_live_rollback_cache(backup_dir, timestamp)

    results = []
    for instance in ARR_INSTANCES:
        api_key = read_api_key(instance.config_path)
        data = (
            snapshot_instance(instance, api_key, backup_dir)
            if backup_dir is not None
            else {
                "custom_formats": request_json(instance, api_key, "GET", "/api/v3/customformat"),
                "quality_profiles": request_json(instance, api_key, "GET", "/api/v3/qualityprofile"),
            }
        )
        results.append(
            process_instance(
                instance,
                data,
                args.apply,
                profile_pattern,
                lq_names,
                trash_sources,
            )
        )

    print(
        json.dumps(
            {
                "applied": args.apply,
                "backup_dir": str(backup_dir) if backup_dir is not None else None,
                "profile_regex": args.profile_regex,
                "neutralized_lq_names": sorted(lq_names),
                "results": results,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
