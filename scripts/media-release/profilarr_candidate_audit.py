#!/usr/bin/env python3
"""Audit Profilarr PCD databases as release-policy candidates.

Run this on docker-vm. It reads Profilarr's local SQLite database and cloned
PCD repositories, materializes each PCD database in memory, and compares
candidate custom formats/profiles with live Sonarr/Radarr names.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_PROFILARR_DB = "/opt/profilarr/config/data/profilarr.db"
DEFAULT_DATA_ROOT = "/opt/profilarr/config/data"


@dataclass(frozen=True)
class ArrInstance:
    name: str
    base_url: str
    config_path: str
    profile_names: tuple[str, ...]


ARR_INSTANCES = (
    ArrInstance(
        name="sonarr",
        base_url="http://127.0.0.1:8989",
        config_path="/opt/media-stack/sonarr/config.xml",
        profile_names=("shows-anime", "shows-anime-profilarr-test"),
    ),
    ArrInstance(
        name="radarr",
        base_url="http://127.0.0.1:7878",
        config_path="/opt/media-stack/radarr/config.xml",
        profile_names=("movies-anime", "movies-anime-profilarr-test"),
    ),
)

PROFILE_FOCUS = (
    "Anime 1080p",
    "TV 1080p",
    "Movies 1080p",
    "Movies 1080p HQ",
    "1080p LQ",
)
KEYWORDS = (
    "dual",
    "x265",
    "h265",
    "hevc",
    "tier",
    "group",
    "baseline",
    "lq",
    "banned",
    "bad",
    "raw",
    "multi",
    "source",
)


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    api_key = root.findtext("ApiKey")
    if not api_key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return api_key.strip()


def request_json(instance: ArrInstance, path: str) -> Any:
    request = urllib.request.Request(
        f"{instance.base_url.rstrip('/')}{path}",
        headers={"X-Api-Key": read_api_key(instance.config_path)},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def numeric_prefix(path: Path) -> tuple[int, str]:
    match = re.match(r"^(\d+)", path.name)
    return (int(match.group(1)) if match else 10**9, path.name)


def local_database_path(data_root: Path, local_path: str) -> Path:
    prefix = "/config/data/"
    if local_path.startswith(prefix):
        return data_root / local_path[len(prefix) :]
    return Path(local_path)


def exec_sql(conn: sqlite3.Connection, sql: str) -> int:
    skipped = 0
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
            # PCD history can contain duplicate inserts and rename collisions
            # across rebuild operations. Skip those for a read-only candidate
            # inspection instead of aborting the whole replay.
            conn.rollback()
            skipped += 1
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
            skipped += 1
        statement = ""
    if statement.strip():
        conn.execute(statement)
    return skipped


def exec_sql_file(conn: sqlite3.Connection, path: Path) -> int:
    return exec_sql(conn, path.read_text())


def materialize_database(
    data_root: Path, db_row: dict[str, Any], ops: list[dict[str, Any]]
) -> tuple[sqlite3.Connection, int]:
    repo_path = local_database_path(data_root, db_row["local_path"])
    schema_ops = sorted((repo_path / "deps" / "schema" / "ops").glob("*.sql"), key=numeric_prefix)
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")
    skipped = 0
    for path in schema_ops:
        skipped += exec_sql_file(conn, path)
    for row in sorted(ops, key=lambda item: (item.get("op_number") or 0, item["id"])):
        skipped += exec_sql(conn, row["sql"])
    return conn, skipped


def fetch_all(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [row_dict(row) for row in conn.execute(sql, params).fetchall()]


def focused_format_rows(conn: sqlite3.Connection, profile_name: str) -> list[dict[str, Any]]:
    rows = fetch_all(
        conn,
        """
        SELECT custom_format_name AS name, arr_type, score
        FROM quality_profile_custom_formats
        WHERE quality_profile_name = ?
        ORDER BY score DESC, custom_format_name
        """,
        (profile_name,),
    )
    focused: list[dict[str, Any]] = []
    for row in rows:
        name = row["name"].lower()
        if row["score"] != 0 or any(keyword in name for keyword in KEYWORDS):
            focused.append(row)
    return focused


def summarize_profile(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    profile = conn.execute(
        """
        SELECT name, minimum_custom_format_score, upgrade_until_score,
               upgrade_score_increment
        FROM quality_profiles
        WHERE name = ?
        """,
        (name,),
    ).fetchone()
    if profile is None:
        return None
    rows = focused_format_rows(conn, name)
    positive = [row for row in rows if row["score"] > 0]
    negative = [row for row in rows if row["score"] < 0]
    return {
        "name": name,
        "minimum_custom_format_score": profile["minimum_custom_format_score"],
        "upgrade_until_score": profile["upgrade_until_score"],
        "upgrade_score_increment": profile["upgrade_score_increment"],
        "scored_custom_format_count": len(
            fetch_all(
                conn,
                "SELECT 1 FROM quality_profile_custom_formats WHERE quality_profile_name = ? AND score != 0",
                (name,),
            )
        ),
        "positive": positive[:20],
        "negative": negative[:20],
        "watch_formats": [
            row
            for row in rows
            if any(keyword in row["name"].lower() for keyword in ("dual", "x265", "hevc", "h265"))
        ],
    }


def candidate_formats(conn: sqlite3.Connection, live_names: set[str]) -> dict[str, Any]:
    rows = fetch_all(
        conn,
        """
        SELECT DISTINCT cf.name
        FROM custom_formats cf
        LEFT JOIN quality_profile_custom_formats qpcf
          ON qpcf.custom_format_name = cf.name
        WHERE cf.name LIKE '%Tier%'
           OR cf.name LIKE '%Group%'
           OR cf.name LIKE '%LQ%'
           OR cf.name LIKE '%Banned%'
           OR cf.name LIKE '%Bad%'
           OR cf.name LIKE '%Dual%'
           OR cf.name LIKE '%x265%'
           OR cf.name LIKE '%HEVC%'
           OR cf.name LIKE '%Raw%'
           OR qpcf.score < 0
        ORDER BY cf.name
        """,
    )
    names = [row["name"] for row in rows]
    missing = [name for name in names if name not in live_names]
    present = [name for name in names if name in live_names]
    return {
        "interesting_count": len(names),
        "already_live_count": len(present),
        "missing_from_live_count": len(missing),
        "missing_from_live_sample": missing[:40],
        "already_live_sample": present[:40],
    }


def live_arr_state() -> dict[str, Any]:
    state: dict[str, Any] = {}
    for instance in ARR_INSTANCES:
        formats = request_json(instance, "/api/v3/customformat")
        profiles = request_json(instance, "/api/v3/qualityprofile")
        profile_map = {profile["name"]: profile for profile in profiles}
        state[instance.name] = {
            "custom_format_count": len(formats),
            "custom_format_names": sorted(format_row["name"] for format_row in formats),
            "profiles": {
                name: {
                    "id": profile_map[name]["id"],
                    "format_item_count": len(profile_map[name].get("formatItems", [])),
                }
                for name in instance.profile_names
                if name in profile_map
            },
        }
    return state


def audit(profilarr_db: Path, data_root: Path) -> dict[str, Any]:
    source = sqlite3.connect(f"file:{profilarr_db}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    database_rows = fetch_all(
        source,
        """
        SELECT id, name, repository_url, local_path, last_synced_at
        FROM database_instances
        ORDER BY id
        """,
    )
    ops_by_database: dict[int, list[dict[str, Any]]] = {}
    for row in fetch_all(
        source,
        """
        SELECT id, database_id, op_number, sql
        FROM pcd_ops
        WHERE state = 'published'
        ORDER BY database_id, op_number, id
        """,
    ):
        ops_by_database.setdefault(row["database_id"], []).append(row)

    live_state = live_arr_state()
    live_names = set(live_state["sonarr"]["custom_format_names"]) | set(live_state["radarr"]["custom_format_names"])
    databases: list[dict[str, Any]] = []
    for db_row in database_rows:
        conn, skipped_statement_count = materialize_database(
            data_root, db_row, ops_by_database.get(db_row["id"], [])
        )
        counts = {
            "custom_formats": conn.execute("SELECT count(*) FROM custom_formats").fetchone()[0],
            "regular_expressions": conn.execute("SELECT count(*) FROM regular_expressions").fetchone()[0],
            "quality_profiles": conn.execute("SELECT count(*) FROM quality_profiles").fetchone()[0],
            "tests": conn.execute("SELECT count(*) FROM custom_format_tests").fetchone()[0],
            "ops": len(ops_by_database.get(db_row["id"], [])),
        }
        profiles = [
            profile
            for profile in (summarize_profile(conn, name) for name in PROFILE_FOCUS)
            if profile is not None
        ]
        databases.append(
            {
                "id": db_row["id"],
                "name": db_row["name"],
                "repository_url": db_row["repository_url"],
                "last_synced_at": db_row["last_synced_at"],
                "counts": counts,
                "skipped_statement_count": skipped_statement_count,
                "profiles": profiles,
                "candidate_formats": candidate_formats(conn, live_names),
            }
        )
    return {"live": live_state, "databases": databases}


def print_format_rows(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        print(f"      {row['score']:>7} {row['arr_type']:<6} {row['name']}")


def print_text(report: dict[str, Any]) -> None:
    print("Live Arr CF counts:")
    for name, state in report["live"].items():
        profile_bits = ", ".join(
            f"{profile_name}=id {profile['id']} ({profile['format_item_count']} formats)"
            for profile_name, profile in state["profiles"].items()
        )
        print(f"  - {name}: {state['custom_format_count']} CFs; {profile_bits}")

    for database in report["databases"]:
        print()
        print(
            "{name}: {ops} ops, {custom_formats} CFs, {regular_expressions} regexes, "
            "{quality_profiles} profiles, {tests} tests".format(
                name=database["name"], **database["counts"]
            )
        )
        print(f"  repo: {database['repository_url']}")
        if database["skipped_statement_count"]:
            print(f"  replay skipped duplicate/schema-drift statements: {database['skipped_statement_count']}")
        candidates = database["candidate_formats"]
        print(
            "  interesting candidate formats: {interesting_count}; already live: "
            "{already_live_count}; missing by exact name: {missing_from_live_count}".format(**candidates)
        )
        if candidates["missing_from_live_sample"]:
            print("  missing sample:")
            for name in candidates["missing_from_live_sample"][:20]:
                print(f"    - {name}")
        for profile in database["profiles"]:
            print(
                "  profile {name}: min={minimum_custom_format_score} cutoff={upgrade_until_score} "
                "scored={scored_custom_format_count}".format(**profile)
            )
            if profile["watch_formats"]:
                print("    DA/x265 watch formats:")
                print_format_rows(profile["watch_formats"])
            if profile["positive"]:
                print("    positive score sample:")
                print_format_rows(profile["positive"][:10])
            if profile["negative"]:
                print("    negative score sample:")
                print_format_rows(profile["negative"][:10])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profilarr-db", default=DEFAULT_PROFILARR_DB)
    parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit(Path(args.profilarr_db), Path(args.data_root))
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        print_text(report)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
