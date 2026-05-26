#!/usr/bin/env python3
"""Import selected Profilarr database custom formats into Arr test profiles.

Run this on docker-vm. It reads the local Profilarr database and linked PCD
repositories, copies only curated custom-format definitions into Sonarr/Radarr,
then scores those copied formats in the anime Profilarr test profiles.

The production anime profiles are not assigned to media and are not modified by
default. This script intentionally does not import upstream quality profiles.
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


DEFAULT_PROFILARR_DB = "/opt/profilarr/config/data/profilarr.db"
DEFAULT_DATA_ROOT = "/opt/profilarr/config/data"
DEFAULT_SNAPSHOT_ROOT = "/opt/media-stack/release-policy-snapshots"
DEFAULT_CF_LIMIT = 100


@dataclass(frozen=True)
class ArrInstance:
    name: str
    base_url: str
    config_path: str
    source_profile_name: str
    test_profile_name: str
    assignment_path: str


@dataclass(frozen=True)
class CuratedFormat:
    database_name: str
    source_name: str
    target_name: str
    score: int
    targets: tuple[str, ...] = ("sonarr", "radarr")


INSTANCES = (
    ArrInstance(
        name="sonarr",
        base_url="http://127.0.0.1:8989",
        config_path="/opt/media-stack/sonarr/config.xml",
        source_profile_name="shows-anime",
        test_profile_name="shows-anime-profilarr-test",
        assignment_path="/api/v3/series",
    ),
    ArrInstance(
        name="radarr",
        base_url="http://127.0.0.1:7878",
        config_path="/opt/media-stack/radarr/config.xml",
        source_profile_name="movies-anime",
        test_profile_name="movies-anime-profilarr-test",
        assignment_path="/api/v3/movie",
    ),
)


def dumpstarr(source_name: str, score: int, targets: tuple[str, ...] = ("sonarr", "radarr")) -> CuratedFormat:
    return CuratedFormat(
        database_name="Dumpstarr",
        source_name=source_name,
        target_name=f"Dumpstarr {source_name}",
        score=score,
        targets=targets,
    )


CURATED_FORMATS: tuple[CuratedFormat, ...] = (
    dumpstarr("Anime BD Tier 01", 1400),
    dumpstarr("Anime BD Tier 02", 1300),
    dumpstarr("Anime BD Tier 03", 1200),
    dumpstarr("Anime BD Tier 04", 1100),
    dumpstarr("Anime BD Tier 05", 1000),
    dumpstarr("Anime BD Tier 06", 900),
    dumpstarr("Anime BD Tier 07", 800),
    dumpstarr("Anime BD Tier 08", 700),
    dumpstarr("Anime WEB Tier 01", 1400),
    dumpstarr("Anime WEB Tier 02", 1300),
    dumpstarr("Anime WEB Tier 03", 1200),
    dumpstarr("Anime WEB Tier 04", 1100),
    dumpstarr("Anime WEB Tier 05", 1000),
    dumpstarr("Anime WEB Tier 6", 900),
    dumpstarr("Anime Baseline Groups", 150),
    dumpstarr("Anime LQ", -1000000),
    dumpstarr("Bad Dual Groups", -1000000),
    dumpstarr("Bad Multis", -1000000),
    dumpstarr("Bad Source", -1000000),
    dumpstarr("Banned Groups", -1000000),
    dumpstarr("Banned Groups (Title)", -1000000),
)

OLD_ANIME_TIER_NAMES = {
    *(f"Anime BD Tier {index:02d}" for index in range(1, 9)),
    *(f"Anime Web Tier {index:02d}" for index in range(1, 7)),
}

SOURCE_VALUES = {
    "sonarr": {
        "unknown": 0,
        "television": 1,
        "tv": 1,
        "televisionraw": 2,
        "web": 3,
        "webdl": 3,
        "web-dl": 3,
        "webrip": 4,
        "web-rip": 4,
        "dvd": 5,
        "bluray": 6,
        "blu-ray": 6,
        "blurayraw": 7,
        "blurayraw/remux": 7,
        "remux": 7,
    },
    "radarr": {
        "unknown": 0,
        "cam": 1,
        "telesync": 2,
        "telecine": 3,
        "workprint": 4,
        "dvd": 5,
        "tv": 6,
        "web": 7,
        "webdl": 7,
        "web-dl": 7,
        "webrip": 8,
        "web-rip": 8,
        "bluray": 9,
        "blu-ray": 9,
    },
}

QUALITY_MODIFIER_VALUES = {
    "none": 0,
    "regional": 1,
    "sdtv": 1,
    "rawhd": 2,
    "brdisk": 3,
    "remux": 4,
}


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
        with urllib.request.urlopen(request, timeout=90) as response:
            if response.status == 204:
                return None
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{instance.name}: {method} {path} failed: {exc.code} {detail}") from exc


def find_one(items: list[dict[str, Any]], name: str, item_type: str) -> dict[str, Any] | None:
    matches = [item for item in items if item.get("name") == name]
    if len(matches) > 1:
        raise RuntimeError(f"multiple {item_type} entries named {name!r}")
    return matches[0] if matches else None


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


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def fetch_all(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [row_dict(row) for row in conn.execute(sql, params).fetchall()]


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


def load_candidate_databases(profilarr_db: Path, data_root: Path) -> dict[str, sqlite3.Connection]:
    source = sqlite3.connect(f"file:{profilarr_db}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    databases = fetch_all(
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

    result: dict[str, sqlite3.Connection] = {}
    for db_row in databases:
        conn, _skipped = materialize_database(data_root, db_row, ops_by_database.get(db_row["id"], []))
        result[str(db_row["name"])] = conn
    return result


def normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def field(value: Any, field_type: str = "textbox") -> dict[str, Any]:
    return {
        "order": 0,
        "name": "value",
        "label": "Value",
        "value": value,
        "type": field_type,
        "advanced": False,
        "privacy": "normal",
        "isFloat": False,
    }


def spec_payload(
    arr_name: str,
    condition: dict[str, Any],
    implementation: str,
    implementation_name: str,
    value: Any,
    field_type: str = "textbox",
) -> dict[str, Any]:
    return {
        "name": condition["name"],
        "implementation": implementation,
        "implementationName": implementation_name,
        "infoLink": f"https://wiki.servarr.com/{arr_name}/settings#custom-formats-2",
        "negate": bool(condition["negate"]),
        "required": bool(condition["required"]),
        "fields": [field(value, field_type)],
    }


def condition_payload(
    conn: sqlite3.Connection,
    arr_name: str,
    condition: dict[str, Any],
) -> dict[str, Any] | None:
    condition_type = str(condition["type"])
    params = (condition["custom_format_name"], condition["name"])

    if condition_type == "release_title":
        row = conn.execute(
            """
            SELECT re.pattern
            FROM condition_patterns cp
            JOIN regular_expressions re ON re.name = cp.regular_expression_name
            WHERE cp.custom_format_name = ? AND cp.condition_name = ?
            """,
            params,
        ).fetchone()
        if row is None:
            return None
        return spec_payload(arr_name, condition, "ReleaseTitleSpecification", "Release Title", row["pattern"])

    if condition_type == "release_group":
        row = conn.execute(
            """
            SELECT re.pattern
            FROM condition_patterns cp
            JOIN regular_expressions re ON re.name = cp.regular_expression_name
            WHERE cp.custom_format_name = ? AND cp.condition_name = ?
            """,
            params,
        ).fetchone()
        if row is None:
            return None
        return spec_payload(arr_name, condition, "ReleaseGroupSpecification", "Release Group", row["pattern"])

    if condition_type == "edition":
        row = conn.execute(
            """
            SELECT re.pattern
            FROM condition_patterns cp
            JOIN regular_expressions re ON re.name = cp.regular_expression_name
            WHERE cp.custom_format_name = ? AND cp.condition_name = ?
            """,
            params,
        ).fetchone()
        if row is None:
            return None
        return spec_payload(arr_name, condition, "EditionSpecification", "Edition", row["pattern"])

    if condition_type == "source":
        row = conn.execute(
            """
            SELECT source
            FROM condition_sources
            WHERE custom_format_name = ? AND condition_name = ?
            """,
            params,
        ).fetchone()
        if row is None:
            return None
        key = normalize_token(str(row["source"]))
        mapping = SOURCE_VALUES[arr_name]
        if key not in mapping:
            raise RuntimeError(f"{condition['custom_format_name']}: unsupported {arr_name} source {row['source']!r}")
        return spec_payload(arr_name, condition, "SourceSpecification", "Source", mapping[key], "select")

    if condition_type == "resolution":
        row = conn.execute(
            """
            SELECT resolution
            FROM condition_resolutions
            WHERE custom_format_name = ? AND condition_name = ?
            """,
            params,
        ).fetchone()
        if row is None:
            return None
        match = re.search(r"(\d{3,4})", str(row["resolution"]))
        if not match:
            raise RuntimeError(f"{condition['custom_format_name']}: unsupported resolution {row['resolution']!r}")
        return spec_payload(arr_name, condition, "ResolutionSpecification", "Resolution", int(match.group(1)), "select")

    if condition_type == "quality_modifier":
        row = conn.execute(
            """
            SELECT quality_modifier
            FROM condition_quality_modifiers
            WHERE custom_format_name = ? AND condition_name = ?
            """,
            params,
        ).fetchone()
        if row is None:
            return None
        key = normalize_token(str(row["quality_modifier"]))
        if key not in QUALITY_MODIFIER_VALUES:
            raise RuntimeError(
                f"{condition['custom_format_name']}: unsupported quality modifier {row['quality_modifier']!r}"
            )
        return spec_payload(
            arr_name,
            condition,
            "QualityModifierSpecification",
            "Quality Modifier",
            QUALITY_MODIFIER_VALUES[key],
            "select",
        )

    raise RuntimeError(f"{condition['custom_format_name']}: unsupported condition type {condition_type!r}")


def candidate_payload(
    conn: sqlite3.Connection,
    curated: CuratedFormat,
    arr_name: str,
) -> dict[str, Any] | None:
    cf = conn.execute(
        """
        SELECT name, description, include_in_rename
        FROM custom_formats
        WHERE name = ?
        """,
        (curated.source_name,),
    ).fetchone()
    if cf is None:
        return None

    aliases = source_name_aliases(curated.source_name)
    placeholders = ", ".join("?" for _ in aliases)
    rows = fetch_all(
        conn,
        f"""
        SELECT custom_format_name, name, type, arr_type, negate, required
        FROM custom_format_conditions
        WHERE custom_format_name IN ({placeholders})
          AND arr_type IN ('all', ?)
        ORDER BY id
        """,
        (*aliases, arr_name),
    )
    conditions = dedupe_conditions(rows, aliases)
    specifications: list[dict[str, Any]] = []
    for condition in conditions:
        payload = condition_payload(conn, arr_name, condition)
        if payload is not None:
            specifications.append(payload)
    if not specifications:
        return None
    return {
        "name": curated.target_name,
        "includeCustomFormatWhenRenaming": bool(cf["include_in_rename"]),
        "specifications": specifications,
    }


def source_name_aliases(source_name: str) -> tuple[str, ...]:
    aliases = [source_name]
    match = re.match(r"^(Anime (?:BD|WEB) Tier) 0([1-9])$", source_name)
    if match:
        aliases.append(f"{match.group(1)} {match.group(2)}")
        if match.group(1) == "Anime BD Tier":
            aliases.append(f"Anime Tier {match.group(2)}")
    return tuple(dict.fromkeys(aliases))


def dedupe_conditions(rows: list[dict[str, Any]], aliases: tuple[str, ...]) -> list[dict[str, Any]]:
    alias_rank = {name: index for index, name in enumerate(aliases)}
    rows = sorted(
        rows,
        key=lambda item: (
            str(item["name"]),
            alias_rank.get(str(item["custom_format_name"]), len(aliases)),
            str(item["custom_format_name"]),
        ),
    )
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row["name"]), str(row["type"]), str(row["arr_type"]))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return sorted(result, key=lambda item: str(item["name"]))


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


def clone_profile_payload(source: dict[str, Any], target_name: str, target_id: int | None) -> dict[str, Any]:
    payload = copy.deepcopy(source)
    payload["name"] = target_name
    if target_id is None:
        payload.pop("id", None)
    else:
        payload["id"] = target_id
    return payload


def snapshot_instance(
    instance: ArrInstance,
    api_key: str,
    snapshot_dir: Path,
) -> dict[str, Any]:
    data = {
        "custom_formats": request_json(instance, api_key, "GET", "/api/v3/customformat"),
        "quality_profiles": request_json(instance, api_key, "GET", "/api/v3/qualityprofile"),
        "naming": request_json(instance, api_key, "GET", "/api/v3/config/naming"),
        "queue_status": request_json(instance, api_key, "GET", "/api/v3/queue/status"),
        "assignments": request_json(instance, api_key, "GET", instance.assignment_path),
    }
    for key, value in data.items():
        (snapshot_dir / f"{instance.name}-{key.replace('_', '-')}.json").write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n"
        )
    return data


def create_or_refresh_test_profile(
    instance: ArrInstance,
    api_key: str,
    profiles: list[dict[str, Any]],
) -> tuple[str, int]:
    source = find_one(profiles, instance.source_profile_name, "quality profile")
    if source is None:
        raise RuntimeError(f"{instance.name}: missing source profile {instance.source_profile_name!r}")
    existing = find_one(profiles, instance.test_profile_name, "quality profile")
    target_id = int(existing["id"]) if existing and isinstance(existing.get("id"), int) else None
    payload = clone_profile_payload(source, instance.test_profile_name, target_id)
    if target_id is None:
        created = request_json(instance, api_key, "POST", "/api/v3/qualityprofile", payload)
        return "created", int(created["id"])
    request_json(instance, api_key, "PUT", f"/api/v3/qualityprofile/{target_id}", payload)
    return "refreshed", target_id


def add_missing_format_item(
    profile: dict[str, Any],
    custom_format: dict[str, Any],
    score: int = 0,
) -> None:
    cf_id = int(custom_format["id"])
    for item in profile.get("formatItems", []):
        if custom_format_id_from_item(item) == cf_id:
            return
    profile.setdefault("formatItems", []).append({"format": custom_format, "score": score})


def set_profile_scores(
    profile: dict[str, Any],
    custom_formats_by_id: dict[int, dict[str, Any]],
    target_scores: dict[str, int],
) -> dict[str, int]:
    applied: dict[str, int] = {}
    for item in profile.get("formatItems", []):
        cf_id = custom_format_id_from_item(item)
        if cf_id is None or cf_id not in custom_formats_by_id:
            continue
        name = str(custom_formats_by_id[cf_id].get("name") or cf_id)
        if name in OLD_ANIME_TIER_NAMES:
            item["score"] = 0
            applied[name] = 0
        if name in target_scores:
            item["score"] = target_scores[name]
            applied[name] = target_scores[name]
    return applied


def process_instance(
    instance: ArrInstance,
    candidate_dbs: dict[str, sqlite3.Connection],
    snapshot_dir: Path,
    cf_limit: int,
    dry_run: bool,
) -> dict[str, Any]:
    api_key = read_api_key(instance.config_path)
    before = snapshot_instance(instance, api_key, snapshot_dir)
    before_formats = before["custom_formats"]
    before_profiles = before["quality_profiles"]
    selected = [item for item in CURATED_FORMATS if instance.name in item.targets]
    current_by_name = {str(item["name"]): item for item in before_formats}
    to_create = [item for item in selected if item.target_name not in current_by_name]

    if len(before_formats) + len(to_create) > cf_limit:
        raise RuntimeError(
            f"{instance.name}: curated import would exceed CF limit: "
            f"{len(before_formats)} existing + {len(to_create)} new > {cf_limit}"
        )

    payloads: list[tuple[CuratedFormat, dict[str, Any]]] = []
    skipped: list[dict[str, Any]] = []
    for curated in selected:
        db = candidate_dbs.get(curated.database_name)
        if db is None:
            raise RuntimeError(f"missing Profilarr database {curated.database_name!r}")
        payload = candidate_payload(db, curated, instance.name)
        if payload is None:
            skipped.append(
                {
                    "source": f"{curated.database_name}:{curated.source_name}",
                    "target": curated.target_name,
                    "reason": "no usable arr specifications",
                }
            )
            continue
        payloads.append((curated, payload))
    payload_names = {item.target_name for item, _payload in payloads}
    usable_to_create = [item for item in to_create if item.target_name in payload_names]

    profile_action = "dry-run"
    existing_test_profile = find_one(before_profiles, instance.test_profile_name, "quality profile")
    profile_id = (
        int(existing_test_profile["id"])
        if existing_test_profile and isinstance(existing_test_profile.get("id"), int)
        else None
    )
    created: list[str] = []
    updated: list[str] = []
    score_changes: dict[str, int] = {}

    if not dry_run:
        profile_action, profile_id = create_or_refresh_test_profile(instance, api_key, before_profiles)
        for curated, payload in payloads:
            existing = current_by_name.get(curated.target_name)
            if existing is None:
                created_payload = request_json(instance, api_key, "POST", "/api/v3/customformat", payload)
                current_by_name[curated.target_name] = created_payload
                created.append(curated.target_name)
                continue
            payload["id"] = existing["id"]
            request_json(instance, api_key, "PUT", f"/api/v3/customformat/{existing['id']}", payload)
            updated.append(curated.target_name)

        custom_formats = request_json(instance, api_key, "GET", "/api/v3/customformat")
        profiles = request_json(instance, api_key, "GET", "/api/v3/qualityprofile")
        test_profile = find_one(profiles, instance.test_profile_name, "quality profile")
        if test_profile is None or not isinstance(test_profile.get("id"), int):
            raise RuntimeError(f"{instance.name}: missing refreshed test profile {instance.test_profile_name!r}")
        custom_formats_by_id = {int(item["id"]): item for item in custom_formats if isinstance(item.get("id"), int)}
        custom_formats_by_name = {str(item["name"]): item for item in custom_formats}
        imported_curated = [curated for curated, _payload in payloads]
        for curated in imported_curated:
            add_missing_format_item(test_profile, custom_formats_by_name[curated.target_name])
        target_scores = {item.target_name: item.score for item in imported_curated}
        score_changes = set_profile_scores(test_profile, custom_formats_by_id, target_scores)
        request_json(instance, api_key, "PUT", f"/api/v3/qualityprofile/{test_profile['id']}", test_profile)
        profile_id = int(test_profile["id"])

    return {
        "instance": instance.name,
        "dry_run": dry_run,
        "snapshot_dir": str(snapshot_dir),
        "existing_custom_formats": len(before_formats),
        "new_custom_formats": len(usable_to_create),
        "post_import_custom_formats": len(before_formats) + len(usable_to_create),
        "custom_format_limit": cf_limit,
        "profile_action": profile_action,
        "test_profile": instance.test_profile_name,
        "test_profile_id": profile_id,
        "selected_formats": [
            {
                "source": f"{item.database_name}:{item.source_name}",
                "target": item.target_name,
                "score": item.score,
                "specifications": len(payload["specifications"]),
                "action": "create" if item.target_name in {cf.target_name for cf in to_create} else "update",
            }
            for item, payload in payloads
        ],
        "skipped_formats": skipped,
        "created": created,
        "updated": updated,
        "score_changes": score_changes,
        "old_tiers_zeroed": sorted(OLD_ANIME_TIER_NAMES),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profilarr-db", default=DEFAULT_PROFILARR_DB)
    parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    parser.add_argument("--snapshot-root", default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--cf-limit", type=int, default=DEFAULT_CF_LIMIT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def print_text(report: dict[str, Any]) -> None:
    print(f"Snapshot: {report['snapshot_dir']}")
    for result in report["instances"]:
        print()
        print(
            "{instance}: {mode}; CFs {existing_custom_formats}+{new_custom_formats}="
            "{post_import_custom_formats}/{custom_format_limit}; {profile_action} "
            "{test_profile} id={test_profile_id}".format(
                mode="dry-run" if result["dry_run"] else "applied",
                **result,
            )
        )
        for item in result["selected_formats"]:
            print(
                "  - {action:6} {target}: score={score}, specs={specifications}, source={source}".format(
                    **item
                )
            )
        for item in result["skipped_formats"]:
            print("  - skip   {target}: {reason}, source={source}".format(**item))
        if result["score_changes"]:
            print("  score changes in test profile:")
            for name, score in sorted(result["score_changes"].items()):
                print(f"    - {name}: {score}")


def main() -> int:
    args = parse_args()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = "selective-profilarr-cfs-dry-run" if args.dry_run else "selective-profilarr-cfs"
    snapshot_dir = Path(args.snapshot_root) / f"{timestamp}-{suffix}"
    snapshot_dir.mkdir(parents=True, exist_ok=False)

    candidate_dbs = load_candidate_databases(Path(args.profilarr_db), Path(args.data_root))
    report = {
        "snapshot_dir": str(snapshot_dir),
        "dry_run": args.dry_run,
        "instances": [
            process_instance(instance, candidate_dbs, snapshot_dir, args.cf_limit, args.dry_run)
            for instance in INSTANCES
        ],
    }
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
