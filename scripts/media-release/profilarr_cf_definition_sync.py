#!/usr/bin/env python3
"""Sync selected Arr custom-format definitions from Profilarr PCD databases.

Run this on docker-vm. It reads Profilarr's locally synced PCD databases,
compares selected source custom-format definitions with existing Sonarr/Radarr
custom formats, and optionally updates only the Arr custom-format definitions.

It intentionally does not import upstream quality profiles, does not change
quality profile structure, and does not change profile scores.
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
DEFAULT_MIN_FREE_SLOTS = 5


@dataclass(frozen=True)
class ArrInstance:
    name: str
    base_url: str
    config_path: str


@dataclass(frozen=True)
class SourceOption:
    database_name: str
    source_name: str


@dataclass(frozen=True)
class SyncTarget:
    target_name: str
    sources: tuple[SourceOption, ...]
    targets: tuple[str, ...] = ("sonarr", "radarr")
    owner: str = "profilarr-source"


INSTANCES = (
    ArrInstance(
        name="sonarr",
        base_url="http://127.0.0.1:8989",
        config_path="/opt/media-stack/sonarr/config.xml",
    ),
    ArrInstance(
        name="radarr",
        base_url="http://127.0.0.1:7878",
        config_path="/opt/media-stack/radarr/config.xml",
    ),
)

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

LOCAL_CUSTOM_NAMES = {
    "2160p",
    "Anime - Dual Audio (Metadata)",
    "Anime - Dual Audio (Title)",
    "Anime Dual Audio",
    "Dubs Only (Block)",
    "H.265",
    "Language - Not Original",
    "Local Anime Raw Group - DBD-Raws",
    "Local Anime Source Rank - Bluray",
    "No AV1",
    "No German Audio",
    "No ISO",
    "Portuguese (No English)",
    "UHD 2160p - Non-Dual (Block)",
    "x265",
    "x265 (HD)",
}
LOCAL_PREFIXES = ("Local Anime Quality Rank -",)

INTERESTING_KEYWORDS = (
    "tier",
    "group",
    "baseline",
    "lq",
    "banned",
    "bad",
    "raw",
    "multi",
    "source",
    "x265",
    "h265",
    "hevc",
    "dual",
)


def source(database_name: str, source_name: str) -> SourceOption:
    return SourceOption(database_name=database_name, source_name=source_name)


def source_options(name: str, *aliases: str) -> tuple[SourceOption, ...]:
    return tuple(
        dict.fromkeys(
            [
                source("TRaSH Guides", alias)
                for alias in (name, *aliases)
            ]
            + [
                source("Dumpstarr", alias)
                for alias in (name, *aliases)
            ]
            + [
                source("Dictionarry", alias)
                for alias in (name, *aliases)
            ]
        )
    )


def build_default_sync_targets() -> tuple[SyncTarget, ...]:
    targets: list[SyncTarget] = []

    for index in range(1, 9):
        name = f"Anime BD Tier {index:02d}"
        targets.append(SyncTarget(name, source_options(name)))

    for index in range(1, 7):
        target = f"Anime Web Tier {index:02d}"
        aliases = [f"Anime WEB Tier {index:02d}"]
        if index == 6:
            aliases.append("Anime WEB Tier 6")
        targets.append(SyncTarget(target, source_options(target, *aliases)))

    for name in (
        "Anime LQ Groups",
        "Anime Raws",
        "BR-DISK",
        "LQ",
        "LQ (Release Title)",
        "Extras",
        "AV1",
        "3D",
        "Upscaled",
        "No-RlsGroup",
        "WEB Tier 01",
        "WEB Tier 02",
        "WEB Tier 03",
        "WEB Scene",
        "HD Bluray Tier 01",
        "HD Bluray Tier 02",
        "HD Bluray Tier 03",
        "Repack/Proper",
        "Repack2",
        "Repack3",
    ):
        targets.append(SyncTarget(name, source_options(name)))

    for name in (
        "ABEMA",
        "ADN",
        "AMZN",
        "ATVP",
        "B-Global",
        "Bilibili",
        "CR",
        "DSNP",
        "FUNi",
        "HBO",
        "HIDIVE",
        "HMAX",
        "HULU",
        "Hulu",
        "MAX",
        "NF",
        "PCOK",
        "PMTP",
        "SHO",
        "STAN",
        "VRV",
        "iT",
    ):
        targets.append(SyncTarget(name, source_options(name)))

    return tuple(targets)


DEFAULT_SYNC_TARGETS = build_default_sync_targets()


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


def load_candidate_databases(profilarr_db: Path, data_root: Path) -> dict[str, dict[str, Any]]:
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

    result: dict[str, dict[str, Any]] = {}
    for db_row in databases:
        conn, skipped = materialize_database(data_root, db_row, ops_by_database.get(db_row["id"], []))
        result[str(db_row["name"])] = {
            "connection": conn,
            "metadata": db_row,
            "skipped_statement_count": skipped,
        }
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


def dedupe_conditions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row["name"]), str(row["type"]), str(row["arr_type"]))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return sorted(result, key=lambda item: str(item["name"]))


def candidate_payload(
    conn: sqlite3.Connection,
    source_name: str,
    target_name: str,
    arr_name: str,
    include_rename: bool,
) -> dict[str, Any] | None:
    cf = conn.execute(
        """
        SELECT name
        FROM custom_formats
        WHERE name = ?
        """,
        (source_name,),
    ).fetchone()
    if cf is None:
        return None

    rows = fetch_all(
        conn,
        """
        SELECT custom_format_name, name, type, arr_type, negate, required
        FROM custom_format_conditions
        WHERE custom_format_name = ?
          AND arr_type IN ('all', ?)
        ORDER BY id
        """,
        (source_name, arr_name),
    )
    specifications: list[dict[str, Any]] = []
    for condition in dedupe_conditions(rows):
        payload = condition_payload(conn, arr_name, condition)
        if payload is not None:
            specifications.append(payload)
    if not specifications:
        return None
    return {
        "name": target_name,
        "includeCustomFormatWhenRenaming": include_rename,
        "specifications": specifications,
    }


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
    }
    for key, value in data.items():
        (snapshot_dir / f"{instance.name}-{key.replace('_', '-')}.json").write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n"
        )
    return data


def canonical_spec(spec: dict[str, Any]) -> dict[str, Any]:
    fields = []
    for item in spec.get("fields") or []:
        fields.append(
            {
                "name": item.get("name"),
                "value": item.get("value"),
                "type": item.get("type"),
            }
        )
    return {
        "name": spec.get("name"),
        "implementation": spec.get("implementation"),
        "implementationName": spec.get("implementationName"),
        "negate": bool(spec.get("negate")),
        "required": bool(spec.get("required")),
        "fields": sorted(fields, key=lambda field_item: str(field_item.get("name"))),
    }


def canonical_specs(custom_format: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        (canonical_spec(spec) for spec in custom_format.get("specifications") or []),
        key=lambda spec: (
            str(spec.get("name")),
            str(spec.get("implementation")),
            bool(spec.get("negate")),
            bool(spec.get("required")),
            json.dumps(spec.get("fields"), sort_keys=True),
        ),
    )


def specs_changed(live: dict[str, Any], desired: dict[str, Any]) -> bool:
    return canonical_specs(live) != canonical_specs(desired)


def profile_references(
    profiles: list[dict[str, Any]],
    custom_formats_by_id: dict[int, dict[str, Any]],
) -> tuple[dict[int, list[str]], dict[int, list[str]]]:
    referenced: dict[int, set[str]] = {}
    scored: dict[int, set[str]] = {}
    for profile in profiles:
        profile_name = str(profile.get("name") or "")
        for item in profile.get("formatItems") or []:
            cf_id = custom_format_id_from_item(item)
            if cf_id is None or cf_id not in custom_formats_by_id:
                continue
            referenced.setdefault(cf_id, set()).add(profile_name)
            if int(item.get("score") or 0) != 0:
                scored.setdefault(cf_id, set()).add(profile_name)
    return (
        {key: sorted(value) for key, value in referenced.items()},
        {key: sorted(value) for key, value in scored.items()},
    )


def database_contains(db_info: dict[str, Any], name: str) -> bool:
    conn: sqlite3.Connection = db_info["connection"]
    row = conn.execute("SELECT 1 FROM custom_formats WHERE name = ? LIMIT 1", (name,)).fetchone()
    return row is not None


def first_source_match(
    candidate_dbs: dict[str, dict[str, Any]],
    sources: tuple[SourceOption, ...],
) -> SourceOption | None:
    for item in sources:
        db_info = candidate_dbs.get(item.database_name)
        if db_info is None:
            continue
        if database_contains(db_info, item.source_name):
            return item
    return None


def classify_live_cf(
    name: str,
    sync_targets_by_name: dict[str, SyncTarget],
    candidate_dbs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if name in LOCAL_CUSTOM_NAMES or any(name.startswith(prefix) for prefix in LOCAL_PREFIXES):
        return {"owner": "local-custom", "source": None}
    if name.startswith("Dumpstarr "):
        return {"owner": "profilarr-imported", "source": "Dumpstarr"}
    target = sync_targets_by_name.get(name)
    if target:
        match = first_source_match(candidate_dbs, target.sources)
        return {
            "owner": target.owner,
            "source": f"{match.database_name}:{match.source_name}" if match else None,
        }
    exact_sources = [
        database_name
        for database_name, db_info in candidate_dbs.items()
        if database_contains(db_info, name)
    ]
    if exact_sources:
        return {"owner": "profilarr-exact-unmanaged", "source": ",".join(exact_sources)}
    return {"owner": "unknown", "source": None}


def candidate_summary(
    candidate_dbs: dict[str, dict[str, Any]],
    live_names: set[str],
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for database_name, db_info in sorted(candidate_dbs.items()):
        conn: sqlite3.Connection = db_info["connection"]
        rows = fetch_all(conn, "SELECT DISTINCT name FROM custom_formats ORDER BY name")
        names = [str(row["name"]) for row in rows]
        interesting = [
            name
            for name in names
            if any(keyword in name.lower() for keyword in INTERESTING_KEYWORDS)
        ]
        missing = [name for name in interesting if name not in live_names]
        summaries.append(
            {
                "database": database_name,
                "repository_url": db_info["metadata"].get("repository_url"),
                "enabled": bool(db_info["metadata"].get("enabled")),
                "auto_pull": bool(db_info["metadata"].get("auto_pull")),
                "last_synced_at": db_info["metadata"].get("last_synced_at"),
                "custom_format_count": len(names),
                "interesting_count": len(interesting),
                "interesting_missing_from_live_count": len(missing),
                "interesting_missing_from_live_sample": missing[:30],
                "skipped_statement_count": db_info["skipped_statement_count"],
            }
        )
    return summaries


def load_manifest(path: str | None) -> tuple[SyncTarget, ...]:
    if not path:
        return DEFAULT_SYNC_TARGETS
    data = json.loads(Path(path).read_text())
    targets: list[SyncTarget] = []
    for row in data:
        sources = tuple(
            SourceOption(database_name=item["database"], source_name=item["name"])
            for item in row["sources"]
        )
        targets.append(
            SyncTarget(
                target_name=row["target_name"],
                sources=sources,
                targets=tuple(row.get("targets") or ("sonarr", "radarr")),
                owner=row.get("owner", "profilarr-source"),
            )
        )
    return tuple(targets)


def process_instance(
    instance: ArrInstance,
    candidate_dbs: dict[str, dict[str, Any]],
    sync_targets: tuple[SyncTarget, ...],
    snapshot_dir: Path,
    cf_limit: int,
    min_free_slots: int,
    dry_run: bool,
) -> dict[str, Any]:
    api_key = read_api_key(instance.config_path)
    before = snapshot_instance(instance, api_key, snapshot_dir)
    custom_formats = before["custom_formats"]
    profiles = before["quality_profiles"]
    custom_formats_by_name = {str(item["name"]): item for item in custom_formats}
    custom_formats_by_id = {
        int(item["id"]): item for item in custom_formats if isinstance(item.get("id"), int)
    }
    referenced, scored = profile_references(profiles, custom_formats_by_id)

    if len(custom_formats) > cf_limit - min_free_slots:
        raise RuntimeError(
            f"{instance.name}: CF count {len(custom_formats)} leaves fewer than "
            f"{min_free_slots} free slots under limit {cf_limit}"
        )

    sync_targets_by_name = {target.target_name: target for target in sync_targets}
    ownership = []
    for cf in sorted(custom_formats, key=lambda item: str(item.get("name", "")).lower()):
        cf_id = int(cf["id"])
        name = str(cf["name"])
        classification = classify_live_cf(name, sync_targets_by_name, candidate_dbs)
        ownership.append(
            {
                "id": cf_id,
                "name": name,
                "owner": classification["owner"],
                "source": classification["source"],
                "include_in_rename": bool(cf.get("includeCustomFormatWhenRenaming")),
                "referenced_by": referenced.get(cf_id, []),
                "scored_by": scored.get(cf_id, []),
            }
        )

    changes: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    applied: list[str] = []
    for target in sync_targets:
        if instance.name not in target.targets:
            continue
        live = custom_formats_by_name.get(target.target_name)
        if live is None:
            skipped.append(
                {
                    "target": target.target_name,
                    "reason": "target custom format is not present in Arr",
                }
            )
            continue
        match = first_source_match(candidate_dbs, target.sources)
        if match is None:
            skipped.append(
                {
                    "target": target.target_name,
                    "reason": "no configured source custom format found",
                    "sources": [f"{item.database_name}:{item.source_name}" for item in target.sources],
                }
            )
            continue
        db_info = candidate_dbs[match.database_name]
        try:
            desired = candidate_payload(
                db_info["connection"],
                match.source_name,
                target.target_name,
                instance.name,
                bool(live.get("includeCustomFormatWhenRenaming")),
            )
        except RuntimeError as exc:
            skipped.append(
                {
                    "target": target.target_name,
                    "source": f"{match.database_name}:{match.source_name}",
                    "reason": str(exc),
                }
            )
            continue
        if desired is None:
            skipped.append(
                {
                    "target": target.target_name,
                    "source": f"{match.database_name}:{match.source_name}",
                    "reason": "source produced no usable Arr specifications",
                }
            )
            continue
        changed = specs_changed(live, desired)
        changes.append(
            {
                "target": target.target_name,
                "source": f"{match.database_name}:{match.source_name}",
                "changed": changed,
                "live_spec_count": len(live.get("specifications") or []),
                "desired_spec_count": len(desired.get("specifications") or []),
                "rename_flag_preserved": bool(live.get("includeCustomFormatWhenRenaming")),
            }
        )
        if changed and not dry_run:
            payload = copy.deepcopy(desired)
            payload["id"] = live["id"]
            request_json(instance, api_key, "PUT", f"/api/v3/customformat/{live['id']}", payload)
            applied.append(target.target_name)

    return {
        "instance": instance.name,
        "dry_run": dry_run,
        "snapshot_dir": str(snapshot_dir),
        "custom_format_count": len(custom_formats),
        "custom_format_limit": cf_limit,
        "min_free_slots": min_free_slots,
        "ownership": ownership,
        "candidate_summaries": candidate_summary(candidate_dbs, set(custom_formats_by_name)),
        "planned_changes": changes,
        "skipped": skipped,
        "applied": applied,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profilarr-db", default=DEFAULT_PROFILARR_DB)
    parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    parser.add_argument("--snapshot-root", default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--cf-limit", type=int, default=DEFAULT_CF_LIMIT)
    parser.add_argument("--min-free-slots", type=int, default=DEFAULT_MIN_FREE_SLOTS)
    parser.add_argument("--manifest", help="optional JSON manifest overriding the embedded sync target list")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def print_text(report: dict[str, Any]) -> None:
    print(f"Snapshot: {report['snapshot_dir']}")
    for result in report["instances"]:
        print()
        print(
            "{instance}: {mode}; CFs={custom_format_count}/{custom_format_limit}; "
            "min_free_slots={min_free_slots}".format(
                mode="dry-run" if result["dry_run"] else "applied",
                **result,
            )
        )
        owner_counts: dict[str, int] = {}
        for item in result["ownership"]:
            owner_counts[item["owner"]] = owner_counts.get(item["owner"], 0) + 1
        print("  ownership:")
        for owner, count in sorted(owner_counts.items()):
            print(f"    - {owner}: {count}")
        print("  source databases:")
        for database in result["candidate_summaries"]:
            print(
                "    - {database}: enabled={enabled} auto_pull={auto_pull} "
                "CFs={custom_format_count} interesting_missing={interesting_missing_from_live_count} "
                "last_synced={last_synced_at}".format(**database)
            )
        changed = [item for item in result["planned_changes"] if item["changed"]]
        unchanged = [item for item in result["planned_changes"] if not item["changed"]]
        print(f"  sync targets: changed={len(changed)} unchanged={len(unchanged)} skipped={len(result['skipped'])}")
        for item in changed[:40]:
            print(
                "    change {target}: {source} specs {live_spec_count}->{desired_spec_count}".format(**item)
            )
        for item in result["skipped"][:20]:
            source = f" source={item['source']}" if item.get("source") else ""
            print(f"    skip {item['target']}: {item['reason']}{source}")
        if result["applied"]:
            print("  applied:")
            for name in result["applied"]:
                print(f"    - {name}")


def main() -> int:
    args = parse_args()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = "profilarr-cf-definition-sync-dry-run" if args.dry_run else "profilarr-cf-definition-sync"
    snapshot_dir = Path(args.snapshot_root) / f"{timestamp}-{suffix}"
    snapshot_dir.mkdir(parents=True, exist_ok=False)

    candidate_dbs = load_candidate_databases(Path(args.profilarr_db), Path(args.data_root))
    sync_targets = load_manifest(args.manifest)
    report = {
        "snapshot_dir": str(snapshot_dir),
        "dry_run": args.dry_run,
        "instances": [
            process_instance(
                instance,
                candidate_dbs,
                sync_targets,
                snapshot_dir,
                args.cf_limit,
                args.min_free_slots,
                args.dry_run,
            )
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
