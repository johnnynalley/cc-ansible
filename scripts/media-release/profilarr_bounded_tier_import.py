#!/usr/bin/env python3
"""Import bounded Dictionarry release tiers into Arr test profiles.

Run this on docker-vm. It reads Profilarr's locally synced Dictionarry PCD
database, creates or updates a curated set of release-tier custom formats in
Sonarr/Radarr, refreshes test profiles from their current source profiles, and
scores only those test profiles.

The script does not import upstream quality profiles, does not change profile
cutoffs, and does not modify local DA/x265 custom formats.
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
DEFAULT_DATABASE = "Dictionarry"

PROTECTED_CLEANUP_NAMES = {
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

PROTECTED_CLEANUP_PREFIXES = ("Local Anime Quality Rank -",)
LEGACY_TIER_PATTERN = re.compile(r"^(?!Dictionarry ).*\bTier \d{2}$", re.IGNORECASE)
LEGACY_TIER_NAMES = {
    "WEB Scene",
}

ANIME_DUAL_AUDIO_SCORE = 100000
ANIME_QUALITY_RANKS = {
    "480p": 10000,
    "576p": 20000,
    "720p": 30000,
    "1080p": 40000,
}
ANIME_X265_SCORE = 2000
REGULAR_X265_SCORE = 3000
ANIME_BLURAY_SOURCE_RANK = 1500
SERVICE_TIEBREAKER_SCORE = 1
SERVICE_FORMAT_NAMES = {
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
    "iT",
    "MAX",
    "NF",
    "PCOK",
    "PMTP",
    "SHO",
    "STAN",
    "VRV",
}


@dataclass(frozen=True)
class ProfilePair:
    source_name: str
    test_name: str


@dataclass(frozen=True)
class ArrInstance:
    name: str
    base_url: str
    config_path: str
    profile_pairs: tuple[ProfilePair, ...]


@dataclass(frozen=True)
class CuratedFormat:
    database_name: str
    source_name: str
    target_name: str
    score: int
    targets: tuple[str, ...]


INSTANCES = (
    ArrInstance(
        name="sonarr",
        base_url="http://127.0.0.1:8989",
        config_path="/opt/media-stack/sonarr/config.xml",
        profile_pairs=(
            ProfilePair("shows-anime", "shows-anime-profilarr-test"),
            ProfilePair("shows-regular", "shows-regular-profilarr-test"),
        ),
    ),
    ArrInstance(
        name="radarr",
        base_url="http://127.0.0.1:7878",
        config_path="/opt/media-stack/radarr/config.xml",
        profile_pairs=(
            ProfilePair("movies-anime", "movies-anime-profilarr-test"),
            ProfilePair("movies-regular", "movies-regular-profilarr-test"),
        ),
    ),
)


def dictionarry(source_name: str, score: int, targets: tuple[str, ...]) -> CuratedFormat:
    return CuratedFormat(
        database_name=DEFAULT_DATABASE,
        source_name=source_name,
        target_name=f"Dictionarry {source_name}",
        score=score,
        targets=targets,
    )


CURATED_FORMATS: tuple[CuratedFormat, ...] = (
    # Scores are intentionally small because families can stack. The strongest
    # practical positive stack is capped below x265, even with Bluray source rank.
    dictionarry("1080p Efficient TV Bluray Tier 1", 180, ("sonarr",)),
    dictionarry("1080p Efficient TV Bluray Tier 2", 172, ("sonarr",)),
    dictionarry("1080p Efficient TV Bluray Tier 3", 150, ("sonarr",)),
    dictionarry("1080p Efficient TV Bluray Tier 4", 135, ("sonarr",)),
    dictionarry("1080p Efficient TV Bluray Tier 5", 120, ("sonarr",)),
    dictionarry("1080p Efficient TV Bluray Tier 6", 105, ("sonarr",)),
    dictionarry("1080p Efficient TV WEB Tier 1", 160, ("sonarr",)),
    dictionarry("1080p Efficient TV WEB Tier 2", 145, ("sonarr",)),
    dictionarry("1080p Efficient TV WEB Tier 3", 130, ("sonarr",)),
    dictionarry("1080p Efficient TV WEB Tier 4", 115, ("sonarr",)),
    dictionarry("1080p Efficient TV WEB Tier 5", 100, ("sonarr",)),
    dictionarry("1080p Compact TV Bluray Tier 1", 150, ("sonarr",)),
    dictionarry("1080p Compact TV Bluray Tier 2", 142, ("sonarr",)),
    dictionarry("1080p Compact TV Bluray Tier 3", 126, ("sonarr",)),
    dictionarry("1080p Compact TV Bluray Tier 4", 114, ("sonarr",)),
    dictionarry("1080p Compact TV Bluray Tier 5", 102, ("sonarr",)),
    dictionarry("1080p Compact TV Bluray Tier 6", 90, ("sonarr",)),
    dictionarry("1080p Compact TV WEB Tier 1", 130, ("sonarr",)),
    dictionarry("1080p Compact TV WEB Tier 2", 118, ("sonarr",)),
    dictionarry("1080p Compact TV WEB Tier 3", 106, ("sonarr",)),
    dictionarry("1080p Compact TV WEB Tier 4", 94, ("sonarr",)),
    dictionarry("1080p Compact TV WEB Tier 5", 82, ("sonarr",)),
    dictionarry("1080p Compact TV Trash Tier 1", -250, ("sonarr",)),
    dictionarry("1080p Compact TV Trash Tier 2", -350, ("sonarr",)),
    dictionarry("1080p Efficient Movie Bluray Tier 1", 180, ("radarr",)),
    dictionarry("1080p Efficient Movie Bluray Tier 2", 165, ("radarr",)),
    dictionarry("1080p Efficient Movie Bluray Tier 3", 150, ("radarr",)),
    dictionarry("1080p Efficient Movie Bluray Tier 4", 135, ("radarr",)),
    dictionarry("1080p Efficient Movie WEB Tier 1", 150, ("radarr",)),
    dictionarry("1080p Efficient Movie WEB Tier 2", 132, ("radarr",)),
    dictionarry("1080p Efficient Movie WEB Tier 3", 114, ("radarr",)),
    dictionarry("1080p Efficient Movie WEB Tier 4", 96, ("radarr",)),
    dictionarry("1080p Compact Movie Bluray Tier 1", 150, ("radarr",)),
    dictionarry("1080p Compact Movie Bluray Tier 2", 135, ("radarr",)),
    dictionarry("1080p Compact Movie Bluray Tier 3", 120, ("radarr",)),
    dictionarry("1080p Compact Movie Bluray Tier 4", 105, ("radarr",)),
    dictionarry("1080p Compact Movie WEB Tier 1", 125, ("radarr",)),
    dictionarry("1080p Compact Movie WEB Tier 2", 110, ("radarr",)),
    dictionarry("1080p Compact Movie WEB Tier 3", 95, ("radarr",)),
    dictionarry("1080p Compact Movie WEB Tier 4", 80, ("radarr",)),
    dictionarry("1080p Bluray HEVC Tier 1", 60, ("sonarr", "radarr")),
    dictionarry("1080p WEB-DL HEVC Tier 1", 60, ("sonarr", "radarr")),
    dictionarry("WEB-DL Tier 1", 20, ("sonarr", "radarr")),
    dictionarry("WEB-DL Tier 2", 16, ("sonarr", "radarr")),
    dictionarry("WEB-DL Tier 3", 12, ("sonarr", "radarr")),
    dictionarry("WEB-DL Tier 4", 8, ("sonarr", "radarr")),
    dictionarry("WEB-DL Tier 5", 4, ("sonarr", "radarr")),
)

CURATED_SCORE_STACKS = {
    "sonarr": {
        "best_bluray_hevc": (
            "1080p Efficient TV Bluray Tier 1",
            "1080p Compact TV Bluray Tier 1",
            "1080p Bluray HEVC Tier 1",
        ),
        "second_bluray_hevc": (
            "1080p Efficient TV Bluray Tier 2",
            "1080p Compact TV Bluray Tier 2",
            "1080p Bluray HEVC Tier 1",
        ),
        "best_web_hevc": (
            "1080p Efficient TV WEB Tier 1",
            "1080p Compact TV WEB Tier 1",
            "1080p WEB-DL HEVC Tier 1",
            "WEB-DL Tier 1",
        ),
    },
    "radarr": {
        "best_bluray_hevc": (
            "1080p Efficient Movie Bluray Tier 1",
            "1080p Compact Movie Bluray Tier 1",
            "1080p Bluray HEVC Tier 1",
        ),
        "second_bluray_hevc": (
            "1080p Efficient Movie Bluray Tier 2",
            "1080p Compact Movie Bluray Tier 2",
            "1080p Bluray HEVC Tier 1",
        ),
        "best_web_hevc": (
            "1080p Efficient Movie WEB Tier 1",
            "1080p Compact Movie WEB Tier 1",
            "1080p WEB-DL HEVC Tier 1",
            "WEB-DL Tier 1",
        ),
    },
}

CURATED_SCORE_FAMILIES = {
    "sonarr": {
        "Efficient TV Bluray": (
            "1080p Efficient TV Bluray Tier 1",
            "1080p Efficient TV Bluray Tier 2",
            "1080p Efficient TV Bluray Tier 3",
            "1080p Efficient TV Bluray Tier 4",
            "1080p Efficient TV Bluray Tier 5",
            "1080p Efficient TV Bluray Tier 6",
        ),
        "Efficient TV WEB": (
            "1080p Efficient TV WEB Tier 1",
            "1080p Efficient TV WEB Tier 2",
            "1080p Efficient TV WEB Tier 3",
            "1080p Efficient TV WEB Tier 4",
            "1080p Efficient TV WEB Tier 5",
        ),
        "Compact TV Bluray": (
            "1080p Compact TV Bluray Tier 1",
            "1080p Compact TV Bluray Tier 2",
            "1080p Compact TV Bluray Tier 3",
            "1080p Compact TV Bluray Tier 4",
            "1080p Compact TV Bluray Tier 5",
            "1080p Compact TV Bluray Tier 6",
        ),
        "Compact TV WEB": (
            "1080p Compact TV WEB Tier 1",
            "1080p Compact TV WEB Tier 2",
            "1080p Compact TV WEB Tier 3",
            "1080p Compact TV WEB Tier 4",
            "1080p Compact TV WEB Tier 5",
        ),
        "WEB-DL": (
            "WEB-DL Tier 1",
            "WEB-DL Tier 2",
            "WEB-DL Tier 3",
            "WEB-DL Tier 4",
            "WEB-DL Tier 5",
        ),
    },
    "radarr": {
        "Efficient Movie Bluray": (
            "1080p Efficient Movie Bluray Tier 1",
            "1080p Efficient Movie Bluray Tier 2",
            "1080p Efficient Movie Bluray Tier 3",
            "1080p Efficient Movie Bluray Tier 4",
        ),
        "Efficient Movie WEB": (
            "1080p Efficient Movie WEB Tier 1",
            "1080p Efficient Movie WEB Tier 2",
            "1080p Efficient Movie WEB Tier 3",
            "1080p Efficient Movie WEB Tier 4",
        ),
        "Compact Movie Bluray": (
            "1080p Compact Movie Bluray Tier 1",
            "1080p Compact Movie Bluray Tier 2",
            "1080p Compact Movie Bluray Tier 3",
            "1080p Compact Movie Bluray Tier 4",
        ),
        "Compact Movie WEB": (
            "1080p Compact Movie WEB Tier 1",
            "1080p Compact Movie WEB Tier 2",
            "1080p Compact Movie WEB Tier 3",
            "1080p Compact Movie WEB Tier 4",
        ),
        "WEB-DL": (
            "WEB-DL Tier 1",
            "WEB-DL Tier 2",
            "WEB-DL Tier 3",
            "WEB-DL Tier 4",
            "WEB-DL Tier 5",
        ),
    },
}

CURATED_SOURCE_ORDERING_CHECKS = {
    "sonarr": (
        ("1080p Efficient TV Bluray Tier 2", "1080p Efficient TV WEB Tier 1"),
        ("1080p Compact TV Bluray Tier 2", "1080p Compact TV WEB Tier 1"),
    ),
    "radarr": (
        ("1080p Efficient Movie Bluray Tier 2", "1080p Efficient Movie WEB Tier 1"),
        ("1080p Compact Movie Bluray Tier 2", "1080p Compact Movie WEB Tier 1"),
    ),
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


def score_model_report() -> dict[str, Any]:
    scores_by_arr = {
        arr_name: {
            curated.source_name: curated.score
            for curated in CURATED_FORMATS
            if arr_name in curated.targets
        }
        for arr_name in CURATED_SCORE_STACKS
    }
    instances: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    for arr_name, stacks in CURATED_SCORE_STACKS.items():
        arr_scores = scores_by_arr[arr_name]
        stack_scores: dict[str, int] = {}
        stack_components: dict[str, dict[str, int]] = {}
        for stack_name, component_names in stacks.items():
            missing = [name for name in component_names if name not in arr_scores]
            if missing:
                errors.append(f"{arr_name} {stack_name} has missing components: {', '.join(missing)}")
                continue
            component_scores = {name: int(arr_scores[name]) for name in component_names}
            stack_components[stack_name] = component_scores
            stack_scores[stack_name] = sum(component_scores.values())

        bluray_hevc = stack_scores.get("best_bluray_hevc", 0)
        second_bluray_hevc = stack_scores.get("second_bluray_hevc", 0)
        web_hevc = stack_scores.get("best_web_hevc", 0)
        if bluray_hevc <= web_hevc:
            errors.append(
                f"{arr_name} best Bluray HEVC stack ({bluray_hevc}) "
                f"must stay above best WEB HEVC stack ({web_hevc})"
            )
        if second_bluray_hevc <= web_hevc:
            errors.append(
                f"{arr_name} second Bluray HEVC stack ({second_bluray_hevc}) "
                f"must stay above best WEB HEVC stack ({web_hevc})"
            )

        source_ordering: list[dict[str, Any]] = []
        for bluray_name, web_name in CURATED_SOURCE_ORDERING_CHECKS[arr_name]:
            bluray_score = arr_scores.get(bluray_name)
            web_score = arr_scores.get(web_name)
            source_ordering.append(
                {
                    "bluray": bluray_name,
                    "bluray_score": bluray_score,
                    "web": web_name,
                    "web_score": web_score,
                }
            )
            if bluray_score is None or web_score is None:
                errors.append(f"{arr_name} missing source ordering check: {bluray_name} / {web_name}")
            elif bluray_score <= web_score:
                errors.append(
                    f"{arr_name} {bluray_name} ({bluray_score}) "
                    f"must stay above {web_name} ({web_score})"
                )

        tier_gaps: dict[str, int] = {}
        for family_name, names in CURATED_SCORE_FAMILIES[arr_name].items():
            family_scores = [arr_scores.get(name) for name in names]
            if any(score is None for score in family_scores):
                errors.append(f"{arr_name} {family_name} is missing configured scores")
                continue
            for earlier, later, earlier_score, later_score in zip(
                names[:-1],
                names[1:],
                family_scores[:-1],
                family_scores[1:],
                strict=True,
            ):
                assert earlier_score is not None
                assert later_score is not None
                gap = int(earlier_score) - int(later_score)
                tier_gaps[f"{earlier} > {later}"] = gap
                if gap <= 0:
                    errors.append(
                        f"{arr_name} {earlier} ({earlier_score}) "
                        f"must stay above {later} ({later_score})"
                    )
        min_tier_gap = min(tier_gaps.values() or [0])
        if min_tier_gap <= SERVICE_TIEBREAKER_SCORE:
            errors.append(
                f"{arr_name} smallest Dictionarry tier gap ({min_tier_gap}) "
                f"must stay above service tiebreaker ({SERVICE_TIEBREAKER_SCORE})"
            )

        max_stack_with_service = max(stack_scores.values() or [0]) + SERVICE_TIEBREAKER_SCORE
        if max_stack_with_service + ANIME_BLURAY_SOURCE_RANK >= ANIME_X265_SCORE:
            errors.append(
                f"{arr_name} Bluray source+tier stack "
                f"({ANIME_BLURAY_SOURCE_RANK}+{max_stack_with_service}) "
                f"must stay below anime x265 ({ANIME_X265_SCORE})"
            )
        if max_stack_with_service >= REGULAR_X265_SCORE:
            errors.append(f"{arr_name} Dictionarry stack must stay below regular x265 ({REGULAR_X265_SCORE})")
        min_positive_score = min((score for score in arr_scores.values() if score > 0), default=0)
        if min_positive_score <= SERVICE_TIEBREAKER_SCORE:
            errors.append(
                f"{arr_name} lowest positive Dictionarry score ({min_positive_score}) "
                f"must stay above service tiebreaker ({SERVICE_TIEBREAKER_SCORE})"
            )

        max_non_da_1080p = (
            ANIME_QUALITY_RANKS["1080p"]
            + ANIME_X265_SCORE
            + ANIME_BLURAY_SOURCE_RANK
            + max_stack_with_service
        )
        if max_non_da_1080p >= ANIME_DUAL_AUDIO_SCORE:
            errors.append(
                f"{arr_name} max non-DA 1080p score ({max_non_da_1080p}) "
                f"must stay below DA ({ANIME_DUAL_AUDIO_SCORE})"
            )

        max_720p_da = (
            ANIME_DUAL_AUDIO_SCORE
            + ANIME_QUALITY_RANKS["720p"]
            + ANIME_X265_SCORE
            + ANIME_BLURAY_SOURCE_RANK
            + max_stack_with_service
        )
        min_1080p_da = ANIME_DUAL_AUDIO_SCORE + ANIME_QUALITY_RANKS["1080p"]
        if min_1080p_da <= max_720p_da:
            errors.append(
                f"{arr_name} 1080p DA floor ({min_1080p_da}) "
                f"must beat max 720p DA ({max_720p_da})"
            )

        instances[arr_name] = {
            "stacks": stack_scores,
            "stack_components": stack_components,
            "source_ordering": source_ordering,
            "min_tier_gap": min_tier_gap,
            "bluray_source_plus_best_stack": ANIME_BLURAY_SOURCE_RANK + max_stack_with_service,
            "anime_x265_score": ANIME_X265_SCORE,
            "regular_x265_score": REGULAR_X265_SCORE,
            "service_tiebreaker_score": SERVICE_TIEBREAKER_SCORE,
            "min_positive_dictionarry_score": min_positive_score,
            "max_non_da_1080p_score": max_non_da_1080p,
            "dual_audio_score": ANIME_DUAL_AUDIO_SCORE,
            "max_720p_da_score": max_720p_da,
            "min_1080p_da_score": min_1080p_da,
        }

    return {"instances": instances, "errors": errors}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


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
            payload = response.read()
            if not payload.strip():
                return None
            return json.loads(payload)
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


def load_candidate_databases(
    profilarr_db: Path,
    data_root: Path,
    include_disabled: bool,
) -> dict[str, dict[str, Any]]:
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
        if not include_disabled and not bool(db_row.get("enabled")):
            continue
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
    curated: CuratedFormat,
    arr_name: str,
) -> dict[str, Any] | None:
    cf = conn.execute("SELECT name FROM custom_formats WHERE name = ?", (curated.source_name,)).fetchone()
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
        (curated.source_name, arr_name),
    )
    specifications: list[dict[str, Any]] = []
    for condition in dedupe_conditions(rows):
        payload = condition_payload(conn, arr_name, condition)
        if payload is not None:
            specifications.append(payload)
    if not specifications:
        return None
    return {
        "name": curated.target_name,
        "includeCustomFormatWhenRenaming": False,
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


def find_one(items: list[dict[str, Any]], name: str, kind: str) -> dict[str, Any]:
    matches = [item for item in items if item.get("name") == name]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {kind} named {name!r}, found {len(matches)}")
    return matches[0]


def find_optional(items: list[dict[str, Any]], name: str, kind: str) -> dict[str, Any] | None:
    matches = [item for item in items if item.get("name") == name]
    if len(matches) > 1:
        raise RuntimeError(f"expected at most one {kind} named {name!r}, found {len(matches)}")
    return matches[0] if matches else None


def clone_profile_payload(source: dict[str, Any], target_name: str, target_id: int | None) -> dict[str, Any]:
    payload = copy.deepcopy(source)
    payload["name"] = target_name
    if target_id is None:
        payload.pop("id", None)
    else:
        payload["id"] = target_id
    return payload


def add_missing_format_item(profile: dict[str, Any], custom_format: dict[str, Any]) -> None:
    cf_id = int(custom_format["id"])
    for item in profile.get("formatItems", []):
        if custom_format_id_from_item(item) == cf_id:
            return
    profile.setdefault("formatItems", []).append(
        {
            "format": {
                "id": cf_id,
                "name": custom_format["name"],
            },
            "name": custom_format["name"],
            "score": 0,
        }
    )


def set_profile_scores(
    profile: dict[str, Any],
    custom_formats_by_id: dict[int, dict[str, Any]],
    target_scores: dict[str, int],
) -> dict[str, dict[str, int]]:
    changes: dict[str, dict[str, int]] = {}
    for item in profile.get("formatItems", []):
        cf_id = custom_format_id_from_item(item)
        if cf_id is None:
            continue
        name = str(custom_formats_by_id.get(cf_id, {}).get("name") or item.get("name") or "")
        if name not in target_scores:
            continue
        old_score = int(item.get("score") or 0)
        new_score = int(target_scores[name])
        if old_score != new_score:
            changes[name] = {"old": old_score, "new": new_score}
        item["score"] = new_score
    return changes


def zero_legacy_tier_scores(
    profile: dict[str, Any],
    custom_formats_by_id: dict[int, dict[str, Any]],
) -> dict[str, dict[str, int]]:
    changes: dict[str, dict[str, int]] = {}
    for item in profile.get("formatItems", []):
        cf_id = custom_format_id_from_item(item)
        if cf_id is None:
            continue
        name = str(custom_formats_by_id.get(cf_id, {}).get("name") or item.get("name") or "")
        if not (LEGACY_TIER_PATTERN.match(name) or name in LEGACY_TIER_NAMES):
            continue
        old_score = int(item.get("score") or 0)
        if old_score == 0:
            continue
        changes[name] = {"old": old_score, "new": 0}
        item["score"] = 0
    return changes


def cap_service_scores(
    profile: dict[str, Any],
    custom_formats_by_id: dict[int, dict[str, Any]],
) -> dict[str, dict[str, int]]:
    changes: dict[str, dict[str, int]] = {}
    for item in profile.get("formatItems", []):
        cf_id = custom_format_id_from_item(item)
        if cf_id is None:
            continue
        name = str(custom_formats_by_id.get(cf_id, {}).get("name") or item.get("name") or "")
        if name not in SERVICE_FORMAT_NAMES:
            continue
        old_score = int(item.get("score") or 0)
        if old_score <= SERVICE_TIEBREAKER_SCORE:
            continue
        changes[name] = {"old": old_score, "new": SERVICE_TIEBREAKER_SCORE}
        item["score"] = SERVICE_TIEBREAKER_SCORE
    return changes


def merge_score_changes(*change_sets: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    merged: dict[str, dict[str, int]] = {}
    for changes in change_sets:
        for name, score_change in changes.items():
            if name in merged and merged[name]["old"] == score_change["new"]:
                merged.pop(name)
                continue
            if name in merged:
                merged[name]["new"] = score_change["new"]
            else:
                merged[name] = dict(score_change)
    return merged


def scored_custom_format_ids(profiles: list[dict[str, Any]]) -> set[int]:
    scored: set[int] = set()
    for profile in profiles:
        for item in profile.get("formatItems") or []:
            cf_id = custom_format_id_from_item(item)
            if cf_id is not None and int(item.get("score") or 0) != 0:
                scored.add(cf_id)
    return scored


def all_zero_non_rename_custom_formats(
    custom_formats: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    scored = scored_custom_format_ids(profiles)
    return sorted(
        (
            {"id": int(cf["id"]), "name": str(cf.get("name") or "")}
            for cf in custom_formats
            if isinstance(cf.get("id"), int)
            and int(cf["id"]) not in scored
            and not bool(cf.get("includeCustomFormatWhenRenaming"))
            and str(cf.get("name") or "") not in PROTECTED_CLEANUP_NAMES
            and not any(str(cf.get("name") or "").startswith(prefix) for prefix in PROTECTED_CLEANUP_PREFIXES)
        ),
        key=lambda item: item["name"].lower(),
    )


def replace_profile(profile_list: list[dict[str, Any]], replacement: dict[str, Any]) -> None:
    replacement_name = replacement.get("name")
    for index, profile in enumerate(profile_list):
        if profile.get("name") == replacement_name:
            profile_list[index] = replacement
            return
    profile_list.append(replacement)


def process_instance(
    instance: ArrInstance,
    candidate_dbs: dict[str, dict[str, Any]],
    snapshot_dir: Path,
    cf_limit: int,
    dry_run: bool,
    cleanup_all_zero: bool,
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
            f"{instance.name}: bounded tier import would exceed CF limit: "
            f"{len(before_formats)} existing + {len(to_create)} new > {cf_limit}"
        )

    payloads: list[tuple[CuratedFormat, dict[str, Any]]] = []
    skipped: list[dict[str, Any]] = []
    for curated in selected:
        db = candidate_dbs.get(curated.database_name)
        if db is None:
            raise RuntimeError(f"missing enabled Profilarr database {curated.database_name!r}")
        payload = candidate_payload(db["connection"], curated, instance.name)
        if payload is None:
            skipped.append(
                {
                    "source": f"{curated.database_name}:{curated.source_name}",
                    "target": curated.target_name,
                    "reason": "no usable Arr specifications",
                }
            )
            continue
        payloads.append((curated, payload))

    usable_to_create = [item for item in to_create if item.target_name in {curated.target_name for curated, _ in payloads}]
    created: list[str] = []
    updated: list[str] = []
    profile_actions: dict[str, str] = {}
    profile_score_changes: dict[str, dict[str, dict[str, int]]] = {}
    all_zero_deleted: list[dict[str, Any]] = []
    all_zero_planned: list[dict[str, Any]] = []

    target_scores = {curated.target_name: curated.score for curated, _ in payloads}
    if dry_run:
        custom_formats_by_id = {int(cf["id"]): cf for cf in before_formats if isinstance(cf.get("id"), int)}
        simulated_by_name = copy.deepcopy(current_by_name)
        for curated, _payload in payloads:
            simulated_by_name.setdefault(
                curated.target_name,
                {"id": -(len(simulated_by_name) + 1), "name": curated.target_name},
            )
        simulated_by_id = {
            int(cf["id"]): cf for cf in simulated_by_name.values() if isinstance(cf.get("id"), int)
        }
        custom_formats_by_id.update(simulated_by_id)
        simulated_profiles = copy.deepcopy(before_profiles)
        for pair in instance.profile_pairs:
            source = find_one(before_profiles, pair.source_name, "quality profile")
            existing = find_optional(before_profiles, pair.test_name, "quality profile")
            target_id = int(existing["id"]) if existing and isinstance(existing.get("id"), int) else None
            profile = clone_profile_payload(source, pair.test_name, target_id)
            profile_actions[pair.test_name] = "would-refresh" if target_id is not None else "would-create"
            for curated, _payload in payloads:
                add_missing_format_item(profile, simulated_by_name[curated.target_name])
            changes = merge_score_changes(
                zero_legacy_tier_scores(profile, custom_formats_by_id),
                cap_service_scores(profile, custom_formats_by_id),
                set_profile_scores(profile, custom_formats_by_id, target_scores),
            )
            if changes:
                profile_score_changes[pair.test_name] = changes
            replace_profile(simulated_profiles, profile)
        if cleanup_all_zero:
            all_zero_planned = all_zero_non_rename_custom_formats(list(simulated_by_name.values()), simulated_profiles)
    else:
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
        for pair in instance.profile_pairs:
            source = find_one(profiles, pair.source_name, "quality profile")
            existing = find_optional(profiles, pair.test_name, "quality profile")
            target_id = int(existing["id"]) if existing and isinstance(existing.get("id"), int) else None
            payload = clone_profile_payload(source, pair.test_name, target_id)
            if target_id is None:
                created_profile = request_json(instance, api_key, "POST", "/api/v3/qualityprofile", payload)
                profile_actions[pair.test_name] = f"created id={created_profile.get('id')}"
            else:
                request_json(instance, api_key, "PUT", f"/api/v3/qualityprofile/{target_id}", payload)
                profile_actions[pair.test_name] = f"refreshed id={target_id}"

        custom_formats = request_json(instance, api_key, "GET", "/api/v3/customformat")
        profiles = request_json(instance, api_key, "GET", "/api/v3/qualityprofile")
        custom_formats_by_id = {int(item["id"]): item for item in custom_formats if isinstance(item.get("id"), int)}
        custom_formats_by_name = {str(item["name"]): item for item in custom_formats}
        for pair in instance.profile_pairs:
            profile = find_one(profiles, pair.test_name, "quality profile")
            for curated, _payload in payloads:
                add_missing_format_item(profile, custom_formats_by_name[curated.target_name])
            changes = merge_score_changes(
                zero_legacy_tier_scores(profile, custom_formats_by_id),
                cap_service_scores(profile, custom_formats_by_id),
                set_profile_scores(profile, custom_formats_by_id, target_scores),
            )
            request_json(instance, api_key, "PUT", f"/api/v3/qualityprofile/{profile['id']}", profile)
            if changes:
                profile_score_changes[pair.test_name] = changes

        if cleanup_all_zero:
            final_profiles = request_json(instance, api_key, "GET", "/api/v3/qualityprofile")
            final_formats = request_json(instance, api_key, "GET", "/api/v3/customformat")
            all_zero_deleted = all_zero_non_rename_custom_formats(final_formats, final_profiles)
            for item in all_zero_deleted:
                request_json(instance, api_key, "DELETE", f"/api/v3/customformat/{item['id']}")

    return {
        "instance": instance.name,
        "dry_run": dry_run,
        "snapshot_dir": str(snapshot_dir),
        "existing_custom_formats": len(before_formats),
        "new_custom_formats": len(usable_to_create),
        "post_import_custom_formats": len(before_formats) + len(usable_to_create) - len(all_zero_planned or all_zero_deleted),
        "custom_format_limit": cf_limit,
        "profiles": [pair.test_name for pair in instance.profile_pairs],
        "source_profiles": [pair.source_name for pair in instance.profile_pairs],
        "profile_actions": profile_actions,
        "selected_formats": [
            {
                "source": f"{curated.database_name}:{curated.source_name}",
                "target": curated.target_name,
                "score": curated.score,
                "specifications": len(payload["specifications"]),
                "action": "create" if curated.target_name in {item.target_name for item in to_create} else "update",
            }
            for curated, payload in payloads
        ],
        "skipped_formats": skipped,
        "created": created,
        "updated": updated,
        "profile_score_changes": profile_score_changes,
        "all_zero_non_rename_custom_formats": all_zero_planned if dry_run else all_zero_deleted,
        "cleanup_all_zero": cleanup_all_zero,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profilarr-db", default=DEFAULT_PROFILARR_DB)
    parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    parser.add_argument("--snapshot-root", default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--cf-limit", type=int, default=DEFAULT_CF_LIMIT)
    parser.add_argument("--include-disabled-databases", action="store_true")
    parser.add_argument(
        "--keep-all-zero-custom-formats",
        action="store_true",
        help="do not delete all-zero, non-rename custom formats after refreshing test profiles",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def print_text(report: dict[str, Any]) -> None:
    print(f"Snapshot: {report['snapshot_dir']}")
    print("Score model:")
    for arr_name, item in report["score_model"]["instances"].items():
        stacks = item["stacks"]
        print(
            f"  {arr_name}: best Bluray HEVC stack={stacks['best_bluray_hevc']}; "
            f"second Bluray HEVC stack={stacks['second_bluray_hevc']}; "
            f"best WEB HEVC stack={stacks['best_web_hevc']}; "
            f"service={item['service_tiebreaker_score']} < "
            f"min tier gap={item['min_tier_gap']}; "
            f"Bluray source+max stack+service={item['bluray_source_plus_best_stack']} < "
            f"x265={item['anime_x265_score']}; "
            f"max non-DA 1080p={item['max_non_da_1080p_score']} < "
            f"DA={item['dual_audio_score']}; "
            f"max 720p DA={item['max_720p_da_score']} < "
            f"1080p DA floor={item['min_1080p_da_score']}"
        )
    for result in report["instances"]:
        mode = "dry-run" if result["dry_run"] else "applied"
        print()
        print(
            "{instance}: {mode}; CFs {existing_custom_formats}+{new_custom_formats}="
            "{post_import_custom_formats}/{custom_format_limit}; profiles={profile_text}".format(
                mode=mode,
                profile_text=", ".join(result["profiles"]),
                **result,
            )
        )
        if result["profile_actions"]:
            print("  test profile actions:")
            for name, action in result["profile_actions"].items():
                print(f"    - {name}: {action}")
        for item in result["selected_formats"]:
            print(
                "  - {action:6} {target}: score={score}, specs={specifications}, source={source}".format(
                    **item
                )
            )
        for item in result["skipped_formats"]:
            print("  - skip   {target}: {reason}, source={source}".format(**item))
        if result["profile_score_changes"]:
            print("  profile score changes:")
            for profile_name, changes in result["profile_score_changes"].items():
                print(f"    {profile_name}:")
                for name, scores in sorted(changes.items()):
                    print(f"      - {name}: {scores['old']} -> {scores['new']}")
        if result["created"]:
            print("  created:")
            for name in result["created"]:
                print(f"    - {name}")
        if result["updated"]:
            print("  updated:")
            for name in result["updated"]:
                print(f"    - {name}")
        if result["cleanup_all_zero"] and result["all_zero_non_rename_custom_formats"]:
            label = "would delete all-zero non-rename CFs" if result["dry_run"] else "deleted all-zero non-rename CFs"
            print(f"  {label}:")
            for item in result["all_zero_non_rename_custom_formats"]:
                print(f"    - {item['name']} (id={item['id']})")


def main() -> int:
    args = parse_args()
    score_model = score_model_report()
    if score_model["errors"]:
        raise RuntimeError("score model failed: " + "; ".join(score_model["errors"]))

    suffix = "dictionarry-bounded-tiers-dry-run" if args.dry_run else "dictionarry-bounded-tiers"
    snapshot_dir = Path(args.snapshot_root) / f"{utc_stamp()}-{suffix}"
    snapshot_dir.mkdir(parents=True, exist_ok=False)

    candidate_dbs = load_candidate_databases(
        Path(args.profilarr_db),
        Path(args.data_root),
        args.include_disabled_databases,
    )
    report = {
        "snapshot_dir": str(snapshot_dir),
        "score_model": score_model,
        "instances": [
            process_instance(
                instance,
                candidate_dbs,
                snapshot_dir,
                args.cf_limit,
                args.dry_run,
                not args.keep_all_zero_custom_formats,
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
