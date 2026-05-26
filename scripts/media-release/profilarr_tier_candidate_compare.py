#!/usr/bin/env python3
"""Compare Profilarr release-tier candidates with live Arr tier formats.

Run this on docker-vm. It reads Profilarr's locally synced PCD databases and
live Sonarr/Radarr custom formats, then reports release-group style candidates
that may improve release selection without importing upstream profiles.
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
DEFAULT_CF_LIMIT = 100

RELEASE_KEYWORDS = (
    "tier",
    "group",
    "compact",
    "balanced",
    "efficient",
)

TOKEN_IGNORE = {
    "b",
    "d",
    "s",
    "w",
    "x",
    "web",
    "webdl",
    "webrip",
    "bluray",
    "blu",
    "ray",
    "remux",
    "dvd",
    "not",
    "raw",
    "raws",
}


@dataclass(frozen=True)
class ArrInstance:
    name: str
    base_url: str
    config_path: str
    profile_names: tuple[str, ...]


INSTANCES = (
    ArrInstance(
        name="sonarr",
        base_url="http://127.0.0.1:8989",
        config_path="/opt/media-stack/sonarr/config.xml",
        profile_names=("shows-anime", "shows-regular", "shows-anime-profilarr-test"),
    ),
    ArrInstance(
        name="radarr",
        base_url="http://127.0.0.1:7878",
        config_path="/opt/media-stack/radarr/config.xml",
        profile_names=("movies-anime", "movies-regular", "movies-anime-profilarr-test"),
    ),
)


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def request_json(instance: ArrInstance, path: str) -> Any:
    request = urllib.request.Request(
        f"{instance.base_url.rstrip('/')}{path}",
        headers={"X-Api-Key": read_api_key(instance.config_path)},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


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


def load_candidate_databases(
    profilarr_db: Path,
    data_root: Path,
    include_disabled: bool,
) -> list[dict[str, Any]]:
    source_conn = sqlite3.connect(f"file:{profilarr_db}?mode=ro", uri=True)
    source_conn.row_factory = sqlite3.Row
    databases = fetch_all(
        source_conn,
        """
        SELECT id, name, repository_url, local_path, last_synced_at, enabled, auto_pull
        FROM database_instances
        ORDER BY id
        """,
    )
    ops_by_database: dict[int, list[dict[str, Any]]] = {}
    for row in fetch_all(
        source_conn,
        """
        SELECT id, database_id, op_number, sql
        FROM pcd_ops
        WHERE state = 'published'
        ORDER BY database_id, op_number, id
        """,
    ):
        ops_by_database.setdefault(row["database_id"], []).append(row)

    loaded: list[dict[str, Any]] = []
    for db_row in databases:
        if not include_disabled and not bool(db_row.get("enabled")):
            continue
        conn, skipped = materialize_database(data_root, db_row, ops_by_database.get(db_row["id"], []))
        loaded.append(
            {
                "metadata": db_row,
                "connection": conn,
                "skipped_statement_count": skipped,
            }
        )
    return loaded


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


def field_value(spec: dict[str, Any]) -> Any:
    for field in spec.get("fields") or []:
        if field.get("name") == "value":
            return field.get("value")
    return None


def tokens_from_text(value: Any) -> set[str]:
    if value is None:
        return set()
    tokens = set()
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._-]{1,}", str(value)):
        cleaned = token.strip("._-").lower()
        if len(cleaned) < 2 or cleaned in TOKEN_IGNORE:
            continue
        tokens.add(cleaned)
    return tokens


def is_tier_name(name: str) -> bool:
    lowered = name.lower()
    return any(keyword in lowered for keyword in RELEASE_KEYWORDS)


def format_score(profile: dict[str, Any], cf_id: int | None) -> int | None:
    if cf_id is None:
        return None
    for item in profile.get("formatItems") or []:
        if custom_format_id_from_item(item) == cf_id:
            return int(item.get("score") or 0)
    return None


def live_instance_state(instance: ArrInstance) -> dict[str, Any]:
    custom_formats = request_json(instance, "/api/v3/customformat")
    quality_profiles = request_json(instance, "/api/v3/qualityprofile")
    cf_by_id = {int(cf["id"]): cf for cf in custom_formats if isinstance(cf.get("id"), int)}
    profile_by_name = {str(profile.get("name")): profile for profile in quality_profiles}

    live_tokens: set[str] = set()
    live_tiers: list[dict[str, Any]] = []
    for cf in custom_formats:
        name = str(cf.get("name") or "")
        cf_id = int(cf["id"]) if isinstance(cf.get("id"), int) else None
        scores = {
            profile_name: format_score(profile, cf_id)
            for profile_name, profile in profile_by_name.items()
            if profile_name in instance.profile_names
        }
        scored = {key: value for key, value in scores.items() if value not in (None, 0)}
        tier_like = is_tier_name(name) or bool(scored)
        cf_tokens = tokens_from_text(name)
        spec_count = 0
        release_spec_count = 0
        source_spec_count = 0
        for spec in cf.get("specifications") or []:
            spec_count += 1
            implementation = str(spec.get("implementation") or "")
            value = field_value(spec)
            if implementation in {"ReleaseTitleSpecification", "ReleaseGroupSpecification"}:
                release_spec_count += 1
                cf_tokens |= tokens_from_text(spec.get("name"))
                cf_tokens |= tokens_from_text(value)
            elif implementation == "SourceSpecification":
                source_spec_count += 1
        if tier_like and (is_tier_name(name) or release_spec_count > 0):
            live_tokens |= cf_tokens
            live_tiers.append(
                {
                    "id": cf_id,
                    "name": name,
                    "scores": scored,
                    "spec_count": spec_count,
                    "release_spec_count": release_spec_count,
                    "source_spec_count": source_spec_count,
                    "token_count": len(cf_tokens),
                    "tokens_sample": sorted(cf_tokens)[:20],
                }
            )

    return {
        "instance": instance.name,
        "custom_format_count": len(custom_formats),
        "free_slots": DEFAULT_CF_LIMIT - len(custom_formats),
        "profiles": {
            name: {
                "id": profile_by_name[name].get("id"),
                "format_item_count": len(profile_by_name[name].get("formatItems") or []),
            }
            for name in instance.profile_names
            if name in profile_by_name
        },
        "live_tiers": sorted(live_tiers, key=lambda item: str(item["name"]).lower()),
        "live_tokens": live_tokens,
        "live_names": {str(cf.get("name") or "") for cf in custom_formats},
    }


def condition_patterns(conn: sqlite3.Connection, cf_name: str, condition_name: str) -> list[str]:
    rows = fetch_all(
        conn,
        """
        SELECT re.pattern
        FROM condition_patterns cp
        JOIN regular_expressions re ON re.name = cp.regular_expression_name
        WHERE cp.custom_format_name = ? AND cp.condition_name = ?
        ORDER BY re.name
        """,
        (cf_name, condition_name),
    )
    return [str(row["pattern"]) for row in rows]


def condition_values(conn: sqlite3.Connection, table: str, column: str, cf_name: str, condition_name: str) -> list[str]:
    rows = fetch_all(
        conn,
        f"""
        SELECT {column} AS value
        FROM {table}
        WHERE custom_format_name = ? AND condition_name = ?
        ORDER BY {column}
        """,
        (cf_name, condition_name),
    )
    return [str(row["value"]) for row in rows]


def score_hints(conn: sqlite3.Connection, cf_name: str, arr_name: str) -> list[dict[str, Any]]:
    rows = fetch_all(
        conn,
        """
        SELECT quality_profile_name, arr_type, score
        FROM quality_profile_custom_formats
        WHERE custom_format_name = ?
          AND score != 0
          AND arr_type IN ('all', ?)
        ORDER BY score DESC, quality_profile_name
        """,
        (cf_name, arr_name),
    )
    return rows


def candidate_rows(conn: sqlite3.Connection, arr_name: str, name_regex: re.Pattern[str]) -> list[dict[str, Any]]:
    rows = fetch_all(
        conn,
        """
        SELECT DISTINCT cf.name
        FROM custom_formats cf
        LEFT JOIN quality_profile_custom_formats qpcf
          ON qpcf.custom_format_name = cf.name
        WHERE (
              lower(cf.name) LIKE '%tier%'
           OR lower(cf.name) LIKE '%group%'
           OR lower(cf.name) LIKE '%compact%'
           OR lower(cf.name) LIKE '%balanced%'
           OR lower(cf.name) LIKE '%efficient%'
           OR qpcf.score > 0
        )
        ORDER BY cf.name
        """,
    )
    return [row for row in rows if name_regex.search(str(row["name"]))]


def summarize_candidate(
    conn: sqlite3.Connection,
    database_name: str,
    cf_name: str,
    arr_name: str,
    live_tokens: set[str],
    live_names: set[str],
) -> dict[str, Any] | None:
    conditions = fetch_all(
        conn,
        """
        SELECT custom_format_name, name, type, arr_type, negate, required
        FROM custom_format_conditions
        WHERE custom_format_name = ?
          AND arr_type IN ('all', ?)
        ORDER BY id
        """,
        (cf_name, arr_name),
    )
    if not conditions:
        return None

    tokens = tokens_from_text(cf_name)
    pattern_count = 0
    release_title_count = 0
    release_group_count = 0
    source_values: set[str] = set()
    resolution_values: set[str] = set()
    quality_modifier_values: set[str] = set()
    condition_types: set[str] = set()
    arr_types: set[str] = set()

    for condition in conditions:
        condition_type = str(condition["type"])
        condition_name = str(condition["name"])
        condition_types.add(condition_type)
        arr_types.add(str(condition["arr_type"]))
        if condition_type in {"release_title", "release_group", "edition"}:
            patterns = condition_patterns(conn, cf_name, condition_name)
            pattern_count += len(patterns)
            if condition_type == "release_title":
                release_title_count += len(patterns)
            if condition_type == "release_group":
                release_group_count += len(patterns)
            tokens |= tokens_from_text(condition_name)
            for pattern in patterns:
                tokens |= tokens_from_text(pattern)
        elif condition_type == "source":
            source_values.update(condition_values(conn, "condition_sources", "source", cf_name, condition_name))
        elif condition_type == "resolution":
            resolution_values.update(
                condition_values(conn, "condition_resolutions", "resolution", cf_name, condition_name)
            )
        elif condition_type == "quality_modifier":
            quality_modifier_values.update(
                condition_values(
                    conn,
                    "condition_quality_modifiers",
                    "quality_modifier",
                    cf_name,
                    condition_name,
                )
            )

    if pattern_count == 0:
        return None

    overlap = tokens & live_tokens
    new_tokens = tokens - live_tokens
    hints = score_hints(conn, cf_name, arr_name)
    return {
        "database": database_name,
        "name": cf_name,
        "exact_live": cf_name in live_names,
        "arr_types": sorted(arr_types),
        "condition_types": sorted(condition_types),
        "condition_count": len(conditions),
        "pattern_count": pattern_count,
        "release_title_count": release_title_count,
        "release_group_count": release_group_count,
        "sources": sorted(source_values),
        "resolutions": sorted(resolution_values),
        "quality_modifiers": sorted(quality_modifier_values),
        "score_hints": hints,
        "token_count": len(tokens),
        "overlap_token_count": len(overlap),
        "new_token_count": len(new_tokens),
        "new_tokens_sample": sorted(new_tokens)[:20],
        "overlap_tokens_sample": sorted(overlap)[:20],
    }


def candidate_priority(candidate: dict[str, Any], instance_name: str) -> tuple[int, int, int, str]:
    name = str(candidate["name"]).lower()
    score = max((int(row["score"]) for row in candidate["score_hints"]), default=0)
    priority = 0
    if instance_name == "sonarr" and "compact tv" in name:
        priority += 100
    if instance_name == "radarr" and "compact movie" in name:
        priority += 100
    if "1080p compact" in name:
        priority += 25
    if "trash" in name:
        priority -= 20
    if candidate["exact_live"]:
        priority -= 10
    return (-priority, -score, -int(candidate["new_token_count"]), str(candidate["name"]).lower())


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    name_regex = re.compile(args.name_regex, re.IGNORECASE)
    databases = load_candidate_databases(
        Path(args.profilarr_db),
        Path(args.data_root),
        args.include_disabled_databases,
    )
    live_states = {instance.name: live_instance_state(instance) for instance in INSTANCES}
    report_instances: list[dict[str, Any]] = []

    for instance in INSTANCES:
        live = live_states[instance.name]
        candidates: list[dict[str, Any]] = []
        for db in databases:
            metadata = db["metadata"]
            conn: sqlite3.Connection = db["connection"]
            for row in candidate_rows(conn, instance.name, name_regex):
                summary = summarize_candidate(
                    conn,
                    str(metadata["name"]),
                    str(row["name"]),
                    instance.name,
                    live["live_tokens"],
                    live["live_names"],
                )
                if summary is None:
                    continue
                if args.only_missing and summary["exact_live"]:
                    continue
                candidates.append(summary)
        candidates = sorted(candidates, key=lambda item: candidate_priority(item, instance.name))
        report_instances.append(
            {
                "instance": instance.name,
                "custom_format_count": live["custom_format_count"],
                "free_slots": live["free_slots"],
                "profiles": live["profiles"],
                "live_tiers": live["live_tiers"],
                "candidate_count": len(candidates),
                "candidates": candidates[: args.limit],
            }
        )

    return {
        "databases": [
            {
                "name": db["metadata"]["name"],
                "repository_url": db["metadata"]["repository_url"],
                "enabled": bool(db["metadata"]["enabled"]),
                "auto_pull": bool(db["metadata"]["auto_pull"]),
                "last_synced_at": db["metadata"]["last_synced_at"],
                "skipped_statement_count": db["skipped_statement_count"],
            }
            for db in databases
        ],
        "instances": report_instances,
    }


def score_hint_text(hints: list[dict[str, Any]]) -> str:
    if not hints:
        return "no upstream score hints"
    return "; ".join(
        f"{row['quality_profile_name']}:{row['score']} ({row['arr_type']})"
        for row in hints[:5]
    )


def print_text(report: dict[str, Any]) -> None:
    print("Profilarr release-tier candidate comparison")
    print("Source databases:")
    for db in report["databases"]:
        print(
            "  - {name}: enabled={enabled} auto_pull={auto_pull} last_synced={last_synced_at}".format(
                **db
            )
        )
    for instance in report["instances"]:
        print()
        print(
            "{instance}: CFs={custom_format_count}/100 free_slots={free_slots}; "
            "candidates_shown={shown}/{candidate_count}".format(
                shown=len(instance["candidates"]),
                **instance,
            )
        )
        print("  live scored/tier-like formats:")
        for tier in instance["live_tiers"][:30]:
            score_text = ", ".join(f"{key}={value}" for key, value in tier["scores"].items()) or "unscored"
            print(
                "    - {name}: {score_text}; specs={spec_count} release_specs={release_spec_count} "
                "source_specs={source_spec_count}".format(score_text=score_text, **tier)
            )
        if len(instance["live_tiers"]) > 30:
            print(f"    ... {len(instance['live_tiers']) - 30} more")

        print("  candidate formats:")
        for candidate in instance["candidates"]:
            source_bits = ", ".join(candidate["sources"]) or "no source gate"
            print(
                "    - {database}:{name}: exact_live={exact_live}; patterns={pattern_count} "
                "title={release_title_count} group={release_group_count}; "
                "sources={source_text}; new_tokens={new_token_count}; {score_text}".format(
                    source_text=source_bits,
                    score_text=score_hint_text(candidate["score_hints"]),
                    **candidate,
                )
            )
            if candidate["new_tokens_sample"]:
                print(f"      new token sample: {', '.join(candidate['new_tokens_sample'][:12])}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profilarr-db", default=DEFAULT_PROFILARR_DB)
    parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    parser.add_argument(
        "--name-regex",
        default=r"(compact|balanced|efficient|tier|group)",
        help="case-insensitive regex for candidate custom format names",
    )
    parser.add_argument("--include-disabled-databases", action="store_true")
    parser.add_argument("--only-missing", action="store_true")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(args)
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
