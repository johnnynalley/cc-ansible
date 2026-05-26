#!/usr/bin/env python3
"""Repair arc-local Stardust Crusaders S01 releases in combined JoJo Sonarr.

This is intentionally narrow. It blocklists JoJo Stardust Crusaders releases
named as S01E01-S01E24 for both the Season 1 and Season 2 Sonarr episode IDs,
then optionally deletes the confirmed-wrong Season 1 imports for S01E23/S01E24
and queues fresh SeasonSearch commands.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SERIES_QUERY = "JoJo"
TITLE_TEMPLATE = (
    "JoJos.Bizarre.Adventure.Stardust.Crusaders.S01E{episode:02d}."
    "1080p.Blu-Ray.10-Bit.Dual-Audio.DTS-HD.x265-iAHD"
)
SOURCE_PATTERN = re.compile(
    r"(?i)\bJoJos?[ ._-]+Bizarre[ ._-]+Adventure"
    r"[ ._-]+Stardust[ ._-]+Crusaders[ ._-]+S01E(?P<episode>\d{1,3})\b"
)
WRONG_SEASON_ONE_EPISODES = {23, 24}
DEFAULT_QUALITY = {
    "quality": 7,
    "revision": {
        "version": 1,
        "real": 0,
        "isRepack": False,
    },
}
DEFAULT_LANGUAGES = [1, 8]


def read_api_key(path: Path) -> str:
    root = ET.parse(path).getroot()
    api_key = root.findtext("ApiKey")
    if not api_key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return api_key.strip()


def request_json(
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    payload: Any | None = None,
    params: dict[str, Any] | None = None,
    timeout: int = 60,
) -> Any:
    query = "?" + urllib.parse.urlencode(params or {}, doseq=True) if params else ""
    url = f"{base_url.rstrip('/')}{path}{query}"
    data = None
    headers = {"X-Api-Key": api_key}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            if not body:
                return None
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {body}") from exc


def page_records(
    base_url: str,
    api_key: str,
    path: str,
    params: dict[str, Any],
    page_size: int,
    max_pages: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        payload = request_json(
            base_url,
            api_key,
            "GET",
            path,
            params={**params, "page": page, "pageSize": page_size},
        )
        page_items = payload.get("records", payload if isinstance(payload, list) else [])
        records.extend(page_items)
        total = payload.get("totalRecords") if isinstance(payload, dict) else None
        if isinstance(total, int) and len(records) >= total:
            break
        if len(page_items) < page_size:
            break
    return records


def find_series(series_list: list[dict[str, Any]], query: str) -> dict[str, Any]:
    lowered = query.casefold()
    matches = [
        series
        for series in series_list
        if lowered == str(series.get("title", "")).casefold()
        or lowered in str(series.get("title", "")).casefold()
        or any(
            lowered in str(title.get("title", "")).casefold()
            for title in series.get("alternateTitles") or []
        )
    ]
    if not matches:
        raise RuntimeError(f"no series matched {query!r}")
    if len(matches) > 1:
        names = ", ".join(f"{series['id']}:{series['title']}" for series in matches)
        raise RuntimeError(f"multiple series matched {query!r}: {names}")
    return matches[0]


def backup_state(
    backup_root: Path,
    config: Path,
    data: dict[str, Any],
) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = backup_root / f"{timestamp}-jojo-stardust-s01-repair"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for source in (
        config,
        config.parent / "sonarr.db",
        config.parent / "sonarr.db-shm",
        config.parent / "sonarr.db-wal",
    ):
        if source.exists():
            shutil.copy2(source, backup_dir / source.name)
    for name, value in data.items():
        (backup_dir / f"{name}.json").write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    return backup_dir


def episode_map(episodes: list[dict[str, Any]]) -> dict[tuple[int, int], dict[str, Any]]:
    return {
        (int(item["seasonNumber"]), int(item["episodeNumber"])): item
        for item in episodes
        if isinstance(item.get("seasonNumber"), int) and isinstance(item.get("episodeNumber"), int)
    }


def representative_by_title(history: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    reps: dict[str, dict[str, Any]] = {}
    for record in history:
        title = str(record.get("sourceTitle") or "")
        match = SOURCE_PATTERN.search(title)
        if not match:
            continue
        episode = int(match.group("episode"))
        if not 1 <= episode <= 24:
            continue
        reps.setdefault(title, record)
    return reps


def existing_blocklist_keys(records: list[dict[str, Any]]) -> set[tuple[str, tuple[int, ...]]]:
    keys = set()
    for record in records:
        title = str(record.get("sourceTitle") or "")
        episode_ids = tuple(sorted(int(value) for value in record.get("episodeIds") or [] if isinstance(value, int)))
        keys.add((title, episode_ids))
    return keys


def existing_blocklist_keys_from_db(db_path: Path, series_id: int) -> set[tuple[str, tuple[int, ...]]]:
    keys: set[tuple[str, tuple[int, ...]]] = set()
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            'SELECT SourceTitle, EpisodeIds FROM Blocklist WHERE SeriesId = ?',
            (series_id,),
        )
        for title, episode_ids_raw in rows:
            try:
                episode_ids = tuple(sorted(int(value) for value in json.loads(episode_ids_raw)))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            keys.add((str(title), episode_ids))
    return keys


def parsed_release_fallback(base_url: str, api_key: str, title: str) -> dict[str, Any]:
    parsed = request_json(base_url, api_key, "GET", "/api/v3/parse", params={"title": title})
    return {
        "languages": parsed.get("languages") or [],
        "quality": parsed.get("quality") or {},
        "customFormats": parsed.get("customFormats") or [],
    }


def blocklist_payload(
    base_url: str,
    api_key: str,
    series_id: int,
    title: str,
    episode_id: int,
    representative: dict[str, Any] | None,
) -> dict[str, Any]:
    fallback = parsed_release_fallback(base_url, api_key, title) if representative is None else {}
    return {
        "seriesId": series_id,
        "episodeIds": [episode_id],
        "sourceTitle": title,
        "languages": (representative or fallback).get("languages") or [],
        "quality": (representative or fallback).get("quality") or {},
        "customFormats": (representative or fallback).get("customFormats") or [],
        "protocol": (representative or {}).get("protocol") or "usenet",
        "indexer": (representative or {}).get("indexer") or "manual",
        "message": "Manually blocklisted arc-local Stardust Crusaders S01 release for combined JoJo series",
    }


def history_representatives_from_db(db_path: Path) -> dict[str, dict[str, Any]]:
    representatives: dict[str, dict[str, Any]] = {}
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT SourceTitle, Quality, Languages, Data
            FROM History
            WHERE SourceTitle LIKE '%Stardust.Crusaders.S01E%'
            ORDER BY Date DESC
            """
        )
        for title, quality, languages, data_raw in rows:
            title = str(title)
            match = SOURCE_PATTERN.search(title)
            if not match:
                continue
            episode = int(match.group("episode"))
            if not 1 <= episode <= 24:
                continue
            data: dict[str, Any] = {}
            if data_raw:
                try:
                    data = json.loads(data_raw)
                except json.JSONDecodeError:
                    data = {}
            representative = representatives.setdefault(
                title,
                {
                    "Quality": quality or json.dumps(DEFAULT_QUALITY, indent=2),
                    "Languages": languages or json.dumps(DEFAULT_LANGUAGES, indent=2),
                    "Indexer": None,
                    "PublishedDate": None,
                    "Size": None,
                    "Protocol": 1,
                    "IndexerFlags": 0,
                    "ReleaseType": 1,
                },
            )
            representative["Indexer"] = representative["Indexer"] or data.get("indexer")
            representative["PublishedDate"] = representative["PublishedDate"] or data.get("publishedDate")
            representative["Size"] = representative["Size"] or data.get("size")
            representative["Protocol"] = representative["Protocol"] or data.get("protocol") or 1
            representative["IndexerFlags"] = representative["IndexerFlags"] or data.get("indexerFlags") or 0
            if data.get("releaseType") == "MultiEpisode":
                representative["ReleaseType"] = 2
    return representatives


def int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def insert_blocklist_rows(
    db_path: Path,
    series_id: int,
    payloads: list[dict[str, Any]],
    representatives: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    inserted = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%fZ")
    with sqlite3.connect(db_path) as connection:
        for payload in payloads:
            title = str(payload["sourceTitle"])
            episode_ids = [int(value) for value in payload["episodeIds"]]
            episode_ids_json = json.dumps(episode_ids, indent=2)
            representative = representatives.get(title, {})
            quality = representative.get("Quality") or json.dumps(DEFAULT_QUALITY, indent=2)
            languages = representative.get("Languages") or json.dumps(DEFAULT_LANGUAGES, indent=2)
            existing = connection.execute(
                """
                SELECT 1
                FROM Blocklist
                WHERE SeriesId = ? AND SourceTitle = ? AND EpisodeIds = ?
                LIMIT 1
                """,
                (series_id, title, episode_ids_json),
            ).fetchone()
            if existing:
                continue
            cursor = connection.execute(
                """
                INSERT INTO Blocklist (
                  SeriesId, EpisodeIds, SourceTitle, Quality, Date, PublishedDate,
                  Size, Protocol, Indexer, Message, TorrentInfoHash, Languages,
                  IndexerFlags, ReleaseType
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                """,
                (
                    series_id,
                    episode_ids_json,
                    title,
                    quality,
                    now,
                    representative.get("PublishedDate"),
                    int_or_none(representative.get("Size")),
                    int_or_none(representative.get("Protocol")) or 1,
                    representative.get("Indexer") or "manual",
                    "Manually blocklisted arc-local Stardust Crusaders S01 release for combined JoJo series",
                    languages,
                    int_or_none(representative.get("IndexerFlags")) or 0,
                    int_or_none(representative.get("ReleaseType")) or 1,
                ),
            )
            inserted.append(
                {
                    "id": cursor.lastrowid,
                    "sourceTitle": title,
                    "episodeIds": episode_ids,
                }
            )
    return inserted


def wrong_season_one_files(
    episodes_by_key: dict[tuple[int, int], dict[str, Any]],
    episode_files: list[dict[str, Any]],
    imported_history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    files_by_id = {
        int(item["id"]): item
        for item in episode_files
        if isinstance(item.get("id"), int)
    }
    wrong_by_file_id: dict[int, dict[str, Any]] = {}
    for record in imported_history:
        title = str(record.get("sourceTitle") or "")
        match = SOURCE_PATTERN.search(title)
        if not match:
            continue
        source_episode = int(match.group("episode"))
        episode = record.get("episode") or {}
        if episode.get("seasonNumber") != 1 or source_episode not in WRONG_SEASON_ONE_EPISODES:
            continue
        current_episode = episodes_by_key.get((1, int(episode.get("episodeNumber") or 0)))
        if not current_episode:
            continue
        episode_file = files_by_id.get(int(current_episode.get("episodeFileId") or 0))
        if not episode_file:
            continue
        file_id = int(episode_file["id"])
        wrong_by_file_id.setdefault(
            file_id,
            {
                "source_title": title,
                "season": 1,
                "episode": current_episode.get("episodeNumber"),
                "episode_title": current_episode.get("title"),
                "episode_file_id": file_id,
                "path": episode_file.get("path"),
                "quality": ((episode_file.get("quality") or {}).get("quality") or {}).get("name"),
                "custom_format_score": episode_file.get("customFormatScore"),
            },
        )
    return sorted(wrong_by_file_id.values(), key=lambda item: int(item["episode"]))


def trigger_search(base_url: str, api_key: str, series_id: int, season: int) -> dict[str, Any]:
    return request_json(
        base_url,
        api_key,
        "POST",
        "/api/v3/command",
        {"name": "SeasonSearch", "seriesId": series_id, "seasonNumber": season},
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:8989")
    parser.add_argument("--config", default="/opt/media-stack/sonarr/config.xml")
    parser.add_argument("--backup-root", default="/opt/media-stack/arr-policy-backups")
    parser.add_argument("--delete-wrong-imports", action="store_true")
    parser.add_argument("--request-timeout", type=int, default=20)
    parser.add_argument("--blocklist-method", choices=["database", "api"], default="database")
    parser.add_argument("--blocklist-limit", type=int, help="only add the first N missing blocklist rows")
    parser.add_argument("--delete-limit", type=int, help="only delete the first N confirmed wrong imports")
    parser.add_argument("--search-seasons", default="1,2")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = Path(args.config)
    db_path = config.parent / "sonarr.db"
    api_key = read_api_key(config)
    series = find_series(request_json(args.base_url, api_key, "GET", "/api/v3/series"), SERIES_QUERY)
    series_id = int(series["id"])
    episodes = request_json(args.base_url, api_key, "GET", "/api/v3/episode", params={"seriesId": series_id})
    episode_files = request_json(args.base_url, api_key, "GET", "/api/v3/episodefile", params={"seriesId": series_id})
    history = page_records(
        args.base_url,
        api_key,
        "/api/v3/history",
        {
            "seriesId": series_id,
            "includeSeries": "true",
            "includeEpisode": "true",
            "sortKey": "date",
            "sortDirection": "descending",
        },
        1000,
        2,
    )
    blocklist = page_records(
        args.base_url,
        api_key,
        "/api/v3/blocklist",
        {"seriesId": series_id, "sortKey": "date", "sortDirection": "descending"},
        1000,
        5,
    )
    backup_dir = backup_state(
        Path(args.backup_root),
        config,
        {
            "series": series,
            "episodes": episodes,
            "episode-files": episode_files,
            "history": history,
            "blocklist": blocklist,
        },
    )

    episodes_by_key = episode_map(episodes)
    reps = representative_by_title(history)
    existing_keys = existing_blocklist_keys(blocklist) | existing_blocklist_keys_from_db(db_path, series_id)
    desired_payloads: list[dict[str, Any]] = []
    for episode_number in range(1, 25):
        title = TITLE_TEMPLATE.format(episode=episode_number)
        representative = reps.get(title)
        for season in (1, 2):
            target_episode = episodes_by_key.get((season, episode_number))
            if not target_episode:
                continue
            episode_id = int(target_episode["id"])
            key = (title, (episode_id,))
            if key in existing_keys:
                continue
            desired_payloads.append(
                blocklist_payload(args.base_url, api_key, series_id, title, episode_id, representative)
            )

    blocklist_batch = desired_payloads[: args.blocklist_limit] if args.blocklist_limit else desired_payloads
    added_blocklist = []
    blocklist_errors = []
    if args.apply:
        try:
            if args.blocklist_method == "database":
                added_blocklist.extend(
                    insert_blocklist_rows(
                        db_path,
                        series_id,
                        blocklist_batch,
                        history_representatives_from_db(db_path),
                    )
                )
            else:
                for payload in blocklist_batch:
                    created = request_json(
                        args.base_url,
                        api_key,
                        "POST",
                        "/api/v3/blocklist",
                        payload=payload,
                        timeout=args.request_timeout,
                    )
                    added_blocklist.append(
                        {
                            "id": created.get("id") if isinstance(created, dict) else None,
                            "sourceTitle": payload["sourceTitle"],
                            "episodeIds": payload["episodeIds"],
                        }
                    )
        except Exception as exc:  # noqa: BLE001 - keep reporting all failures.
            if args.blocklist_method == "database":
                blocklist_errors.append(
                    {
                        "sourceTitle": "database batch",
                        "episodeIds": [],
                        "error": str(exc),
                    }
                )
            else:
                blocklist_errors.append(
                    {
                        "sourceTitle": payload["sourceTitle"],
                        "episodeIds": payload["episodeIds"],
                        "error": str(exc),
                    }
                )

    wrong_files = wrong_season_one_files(episodes_by_key, episode_files, history)
    deleted_files = []
    delete_errors = []
    if args.apply and args.delete_wrong_imports:
        seen_file_ids: set[int] = set()
        delete_batch = wrong_files[: args.delete_limit] if args.delete_limit else wrong_files
        for wrong_file in delete_batch:
            file_id = wrong_file.get("episode_file_id")
            if not isinstance(file_id, int) or file_id in seen_file_ids:
                continue
            seen_file_ids.add(file_id)
            try:
                request_json(
                    args.base_url,
                    api_key,
                    "DELETE",
                    f"/api/v3/episodefile/{file_id}",
                    params={"deleteFiles": "true"},
                    timeout=args.request_timeout,
                )
                deleted_files.append(wrong_file)
            except Exception as exc:  # noqa: BLE001 - report partial progress.
                delete_errors.append({**wrong_file, "error": str(exc)})

    queued_searches = []
    search_errors = []
    if args.apply:
        for raw_season in args.search_seasons.split(","):
            raw_season = raw_season.strip()
            if not raw_season:
                continue
            season = int(raw_season)
            try:
                queued_searches.append(
                    request_json(
                        args.base_url,
                        api_key,
                        "POST",
                        "/api/v3/command",
                        {"name": "SeasonSearch", "seriesId": series_id, "seasonNumber": season},
                        timeout=args.request_timeout,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - report partial progress.
                search_errors.append({"season": season, "error": str(exc)})

    report = {
        "apply": args.apply,
        "backup_dir": str(backup_dir),
        "series": {"id": series_id, "title": series.get("title")},
        "existing_matching_blocklist": len(
            [record for record in blocklist if SOURCE_PATTERN.search(str(record.get("sourceTitle") or ""))]
        ),
        "blocklist_method": args.blocklist_method,
        "desired_missing_blocklist": len(desired_payloads),
        "blocklist_batch_size": len(blocklist_batch),
        "desired_missing_blocklist_sample": [
            {"sourceTitle": item["sourceTitle"], "episodeIds": item["episodeIds"]}
            for item in desired_payloads[:20]
        ],
        "added_blocklist": added_blocklist,
        "blocklist_errors": blocklist_errors,
        "wrong_season_one_files": wrong_files,
        "deleted_wrong_files": deleted_files,
        "delete_errors": delete_errors,
        "queued_searches": [
            {"id": item.get("id"), "name": item.get("name"), "status": item.get("status")}
            for item in queued_searches
            if isinstance(item, dict)
        ],
        "search_errors": search_errors,
    }
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    print()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
