#!/usr/bin/env python3
"""Blocklist queued Sonarr downloads whose titles match a regex.

Run this on docker-vm. It reads Sonarr's local config.xml for the API key,
backs up Sonarr DB/config plus queue/history snapshots, then optionally removes
matching queue entries with blocklist=true.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_STARDUST_S01_PATTERN = (
    r"(?i)\bJoJos?[ ._-]+Bizarre[ ._-]+Adventure"
    r"[ ._-]+Stardust[ ._-]+Crusaders[ ._-]+S01E\d{1,3}\b"
)


def read_api_key(path: Path) -> str:
    root = ET.parse(path).getroot()
    api_key = root.findtext("ApiKey")
    if not api_key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return api_key.strip()


def read_sab_api_key(path: Path) -> str:
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "api_key":
            api_key = value.strip()
            if api_key:
                return api_key
    raise RuntimeError(f"{path}: SABnzbd api_key was not found")


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


def request_sab_json(
    base_url: str,
    api_key: str,
    params: dict[str, Any],
    timeout: int,
) -> Any:
    query = urllib.parse.urlencode({**params, "apikey": api_key, "output": "json"}, doseq=True)
    url = f"{base_url.rstrip('/')}/api?{query}"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"SABnzbd API failed: {exc.code} {body}") from exc


def find_series(series_list: list[dict[str, Any]], query: str) -> dict[str, Any]:
    lowered = query.casefold()
    if query.isdigit():
        series_id = int(query)
        matches = [series for series in series_list if series.get("id") == series_id]
        if not matches:
            raise RuntimeError(f"no series matched id {series_id}")
        return matches[0]

    exact_matches = [
        series for series in series_list if lowered == str(series.get("title", "")).casefold()
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        names = ", ".join(f"{series['id']}:{series['title']}" for series in exact_matches)
        raise RuntimeError(f"multiple exact series matched {query!r}: {names}")

    matches = [
        series
        for series in series_list
        if lowered in str(series.get("title", "")).casefold()
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
        page_params = {**params, "page": page, "pageSize": page_size}
        payload = request_json(base_url, api_key, "GET", path, params=page_params)
        page_records_raw = payload.get("records", payload if isinstance(payload, list) else [])
        records.extend(page_records_raw)
        total = payload.get("totalRecords") if isinstance(payload, dict) else None
        if isinstance(total, int) and len(records) >= total:
            break
        if len(page_records_raw) < page_size:
            break
    return records


def title_for_record(record: dict[str, Any]) -> str:
    return str(record.get("title") or record.get("downloadTitle") or "")


def episode_label(record: dict[str, Any]) -> str:
    episode = record.get("episode") or {}
    season = episode.get("seasonNumber")
    number = episode.get("episodeNumber")
    if isinstance(season, int) and isinstance(number, int):
        return f"S{season:02}E{number:02}"
    return "unknown"


def match_queue(records: list[dict[str, Any]], pattern: re.Pattern[str]) -> list[dict[str, Any]]:
    matched = [record for record in records if pattern.search(title_for_record(record))]
    selected: dict[str, dict[str, Any]] = {}
    for record in matched:
        key = str(record.get("downloadId") or f"queue:{record.get('id')}")
        entry = selected.setdefault(
            key,
            {
                "queue_id": record.get("id"),
                "download_id": record.get("downloadId"),
                "title": title_for_record(record),
                "records": 0,
                "episodes": [],
                "status": record.get("status"),
                "tracked_state": record.get("trackedDownloadState"),
                "custom_format_score": record.get("customFormatScore")
                or (record.get("trackedDownload") or {}).get("customFormatScore"),
            },
        )
        entry["records"] += 1
        label = episode_label(record)
        if label not in entry["episodes"]:
            entry["episodes"].append(label)
    return sorted(selected.values(), key=lambda item: str(item["title"]))


def backup_state(
    backup_root: Path,
    sonarr_config: Path,
    queue_records: list[dict[str, Any]],
    history_records: list[dict[str, Any]],
    series: dict[str, Any],
) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = backup_root / f"{timestamp}-sonarr-blocklist-queue-matches"
    backup_dir.mkdir(parents=True, exist_ok=True)

    for source in (
        sonarr_config,
        sonarr_config.parent / "sonarr.db",
        sonarr_config.parent / "sonarr.db-shm",
        sonarr_config.parent / "sonarr.db-wal",
    ):
        if source.exists():
            shutil.copy2(source, backup_dir / source.name)

    (backup_dir / "series.json").write_text(json.dumps(series, indent=2, sort_keys=True) + "\n")
    (backup_dir / "queue.json").write_text(json.dumps(queue_records, indent=2, sort_keys=True) + "\n")
    (backup_dir / "history.json").write_text(json.dumps(history_records, indent=2, sort_keys=True) + "\n")
    return backup_dir


def matching_history(records: list[dict[str, Any]], pattern: re.Pattern[str]) -> list[dict[str, Any]]:
    results = []
    for record in records:
        source_title = str(record.get("sourceTitle") or "")
        if not pattern.search(source_title):
            continue
        episode = record.get("episode") or {}
        results.append(
            {
                "date": record.get("date"),
                "event_type": record.get("eventType"),
                "source_title": source_title,
                "season": episode.get("seasonNumber"),
                "episode": episode.get("episodeNumber"),
                "episode_title": episode.get("title"),
                "quality": ((record.get("quality") or {}).get("quality") or {}).get("name"),
                "custom_format_score": record.get("customFormatScore"),
            }
        )
    return results


def delete_queue_item(
    base_url: str,
    api_key: str,
    queue_id: int,
    remove_from_client: bool,
    blocklist: bool,
    timeout: int,
) -> Any:
    return request_json(
        base_url,
        api_key,
        "DELETE",
        f"/api/v3/queue/{queue_id}",
        params={
            "removeFromClient": str(remove_from_client).lower(),
            "blocklist": str(blocklist).lower(),
        },
        timeout=timeout,
    )


def trigger_season_search(
    base_url: str,
    api_key: str,
    series_id: int,
    season_number: int,
) -> dict[str, Any]:
    return request_json(
        base_url,
        api_key,
        "POST",
        "/api/v3/command",
        {"name": "SeasonSearch", "seriesId": series_id, "seasonNumber": season_number},
    )


def trigger_monitored_download_refresh(base_url: str, api_key: str, timeout: int) -> dict[str, Any]:
    return request_json(
        base_url,
        api_key,
        "POST",
        "/api/v3/command",
        {"name": "RefreshMonitoredDownloads"},
        timeout=timeout,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("series", help="series title or alternate title to scope the queue query")
    parser.add_argument("--apply", action="store_true", help="remove matching queue items")
    parser.add_argument("--pattern", default=DEFAULT_STARDUST_S01_PATTERN)
    parser.add_argument("--base-url", default="http://127.0.0.1:8989")
    parser.add_argument("--config", default="/opt/media-stack/sonarr/config.xml")
    parser.add_argument("--backup-root", default="/opt/media-stack/arr-policy-backups")
    parser.add_argument("--sab-config", default="/opt/media-stack/sabnzbd/sabnzbd.ini")
    parser.add_argument("--sab-url", default="http://127.0.0.1:8080")
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--history-size", type=int, default=1000)
    parser.add_argument("--limit", type=int, help="only process the first N matching downloads")
    parser.add_argument("--request-timeout", type=int, default=20)
    parser.add_argument("--remove-from-client", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--blocklist", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--sab-delete-history", action="store_true")
    parser.add_argument("--sab-del-files", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--search-season", type=int, help="queue a SeasonSearch after apply")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pattern = re.compile(args.pattern)
    config = Path(args.config)
    api_key = read_api_key(config)
    series = find_series(request_json(args.base_url, api_key, "GET", "/api/v3/series"), args.series)
    series_id = int(series["id"])
    queue_records = page_records(
        args.base_url,
        api_key,
        "/api/v3/queue",
        {"seriesId": series_id, "includeSeries": "true", "includeEpisode": "true"},
        args.page_size,
        args.max_pages,
    )
    history_records = page_records(
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
        args.history_size,
        1,
    )
    matches = match_queue(queue_records, pattern)
    backup_dir = backup_state(Path(args.backup_root), config, queue_records, history_records, series)

    removals = []
    sab_api_key = read_sab_api_key(Path(args.sab_config)) if args.apply and args.sab_delete_history else None
    if args.apply:
        for match in matches[: args.limit]:
            queue_id = match.get("queue_id")
            download_id = str(match.get("download_id") or "")
            if args.sab_delete_history:
                if not download_id:
                    removals.append({**match, "result": "skipped missing download id"})
                    continue
                try:
                    response = request_sab_json(
                        args.sab_url,
                        str(sab_api_key),
                        {
                            "mode": "history",
                            "name": "delete",
                            "value": download_id,
                            "del_files": int(args.sab_del_files),
                        },
                        args.request_timeout,
                    )
                    if isinstance(response, dict) and response.get("status") is False:
                        raise RuntimeError(response)
                except Exception as exc:  # noqa: BLE001 - continue with later queue items.
                    removals.append({**match, "result": f"sab error: {exc}"})
                    continue
                removals.append({**match, "result": "removed from sab history"})
                continue
            if not isinstance(queue_id, int):
                removals.append({**match, "result": "skipped missing queue id"})
                continue
            try:
                delete_queue_item(
                    args.base_url,
                    api_key,
                    queue_id,
                    remove_from_client=args.remove_from_client,
                    blocklist=args.blocklist,
                    timeout=args.request_timeout,
                )
            except Exception as exc:  # noqa: BLE001 - continue with later queue items.
                removals.append({**match, "result": f"error: {exc}"})
                continue
            removals.append({**match, "result": "removed"})

    queued_search = None
    if args.apply and args.search_season is not None:
        queued_search = trigger_season_search(args.base_url, api_key, series_id, args.search_season)
    refresh_command = None
    refresh_error = None
    if args.apply and args.sab_delete_history:
        try:
            refresh_command = trigger_monitored_download_refresh(
                args.base_url,
                api_key,
                args.request_timeout,
            )
        except Exception as exc:  # noqa: BLE001 - report and let cleanup stand.
            refresh_error = str(exc)

    report = {
        "apply": args.apply,
        "series": {"id": series_id, "title": series.get("title")},
        "pattern": args.pattern,
        "backup_dir": str(backup_dir),
        "queue_records": len(queue_records),
        "matched_queue_downloads": len(matches),
        "matched_queue_rows": sum(int(item["records"]) for item in matches),
        "matches": matches[:10] if args.summary_only else matches,
        "matching_history": [] if args.summary_only else matching_history(history_records, pattern),
        "removals": removals,
        "queued_search": queued_search,
        "refresh_command": refresh_command,
        "refresh_error": refresh_error,
    }
    if args.summary_only:
        report["matches_truncated"] = len(matches) > 10
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    print()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
