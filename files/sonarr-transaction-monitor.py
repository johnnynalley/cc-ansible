#!/usr/bin/env python3
"""Persist Arr history, queue, and storage snapshots for release-policy audits."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

PRIVATE_FILE_MODE = 0o640
SAFE_HISTORY_DATA_KEYS = {
    "ageHours",
    "downloadClientName",
    "indexer",
    "publishedDate",
    "releaseGroup",
    "releaseSource",
    "releaseType",
    "size",
}


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def read_api_key(path: Path) -> str:
    root = ET.parse(path).getroot()
    api_key = root.findtext("ApiKey")
    if not api_key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return api_key.strip()


def api_get(base_url: str, api_key: str, path: str, params: dict[str, Any] | None = None) -> Any:
    query = "?" + urllib.parse.urlencode(params, doseq=True) if params else ""
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}{query}",
        headers={"X-Api-Key": api_key},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {path} failed: {exc.code} {body}") from exc


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, sort_keys=True)
        handle.write("\n")
    temp.replace(path)
    path.chmod(PRIVATE_FILE_MODE)


def append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        json.dump(event, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    path.chmod(PRIVATE_FILE_MODE)


def cf_names(items: list[dict[str, Any]] | None) -> list[str]:
    return [str(item.get("name") or item.get("id")) for item in items or []]


def quality_name(item: dict[str, Any] | None) -> str | None:
    if not isinstance(item, dict):
        return None
    quality = item.get("quality")
    if isinstance(quality, dict):
        return str(quality.get("name") or quality.get("source") or "unknown")
    return str(item.get("name") or "unknown")


def int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def video_codec_name(item: dict[str, Any] | None) -> str:
    media_info = item.get("mediaInfo") if isinstance(item, dict) else None
    if not isinstance(media_info, dict):
        return "unknown"
    raw = str(
        media_info.get("videoCodec")
        or media_info.get("videoCodecID")
        or media_info.get("videoFormat")
        or "unknown"
    )
    normalized = raw.casefold()
    if "265" in normalized or "hevc" in normalized:
        return "hevc"
    if "264" in normalized or "avc" in normalized:
        return "h264"
    if "av1" in normalized:
        return "av1"
    return raw or "unknown"


def add_bucket(
    buckets: dict[str, dict[str, int]],
    key: Any,
    size: int,
    file_count: int = 1,
) -> None:
    name = str(key or "unknown")
    bucket = buckets.setdefault(name, {"files": 0, "bytes": 0})
    bucket["files"] += file_count
    bucket["bytes"] += size


def sorted_buckets(buckets: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    return dict(sorted(buckets.items(), key=lambda item: (-item[1]["bytes"], item[0])))


def summarize_history_data(data: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key in sorted(SAFE_HISTORY_DATA_KEYS)
        if (value := data.get(key)) is not None
    }


def summarize_history(record: dict[str, Any]) -> dict[str, Any]:
    source_title = record.get("sourceTitle") or record.get("downloadId") or ""
    series = record.get("series") or {}
    episode = record.get("episode") or {}
    return {
        "id": record.get("id"),
        "date": record.get("date"),
        "eventType": record.get("eventType"),
        "sourceTitle": source_title,
        "downloadId": record.get("downloadId"),
        "seriesId": record.get("seriesId") or series.get("id"),
        "seriesTitle": series.get("title"),
        "episodeId": record.get("episodeId") or episode.get("id"),
        "seasonNumber": episode.get("seasonNumber"),
        "episodeNumber": episode.get("episodeNumber"),
        "quality": quality_name(record.get("quality")),
        "customFormatScore": record.get("customFormatScore"),
        "customFormats": cf_names(record.get("customFormats")),
        "data": summarize_history_data(record.get("data") or {}),
    }


def status_messages(record: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    for status in record.get("statusMessages") or []:
        title = status.get("title")
        for message in status.get("messages") or []:
            messages.append(f"{title}: {message}" if title else str(message))
    error = record.get("errorMessage")
    if error:
        messages.append(str(error))
    return messages


def summarize_queue(record: dict[str, Any]) -> dict[str, Any]:
    series = record.get("series") or {}
    episode = record.get("episode") or {}
    return {
        "id": record.get("id"),
        "downloadId": record.get("downloadId"),
        "title": record.get("title") or record.get("downloadTitle"),
        "seriesId": series.get("id"),
        "seriesTitle": series.get("title"),
        "episodeId": episode.get("id") or record.get("episodeId"),
        "seasonNumber": episode.get("seasonNumber"),
        "episodeNumber": episode.get("episodeNumber"),
        "quality": quality_name(record.get("quality")),
        "customFormatScore": record.get("customFormatScore")
        if record.get("customFormatScore") is not None
        else (record.get("trackedDownload") or {}).get("customFormatScore"),
        "customFormats": cf_names(record.get("customFormats")),
        "status": record.get("status"),
        "trackedDownloadState": record.get("trackedDownloadState"),
        "downloadClient": record.get("downloadClient"),
        "protocol": record.get("protocol"),
        "messages": status_messages(record),
    }


def fetch_new_history(
    base_url: str,
    api_key: str,
    last_history_id: int,
    bootstrap_records: int,
    max_pages: int,
) -> list[dict[str, Any]]:
    page_size = 1000 if last_history_id else bootstrap_records
    records: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        history = api_get(
            base_url,
            api_key,
            "/api/v3/history",
            {
                "page": page,
                "pageSize": page_size,
                "sortKey": "id",
                "sortDirection": "descending",
            },
        )
        page_records = history.get("records") or []
        if not page_records:
            break
        for record in page_records:
            record_id = int(record.get("id") or 0)
            if record_id <= last_history_id:
                return records
            records.append(record)
        if len(page_records) < page_size:
            break
    return records


def fetch_paginated_records(
    base_url: str,
    api_key: str,
    path: str,
    params: dict[str, Any] | None = None,
    page_size: int = 1000,
    max_pages: int = 50,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        payload = api_get(
            base_url,
            api_key,
            path,
            {
                **(params or {}),
                "page": page,
                "pageSize": page_size,
                "sortKey": "id",
                "sortDirection": "ascending",
            },
        )
        if isinstance(payload, list):
            page_records = payload
            total_records = len(payload)
        elif isinstance(payload, dict):
            page_records = payload.get("records") or []
            total_records = payload.get("totalRecords")
        else:
            page_records = []
            total_records = None
        records.extend(record for record in page_records if isinstance(record, dict))
        if total_records is not None and len(records) >= int_value(total_records):
            break
        if len(page_records) < page_size:
            break
    return records


def summarize_sonarr_storage(base_url: str, api_key: str) -> dict[str, Any]:
    series_payload = api_get(base_url, api_key, "/api/v3/series")
    series_records = series_payload if isinstance(series_payload, list) else []
    total_size = 0
    file_count = 0
    by_root: dict[str, dict[str, int]] = {}
    by_quality_profile: dict[str, dict[str, int]] = {}
    for series in series_records:
        if not isinstance(series, dict):
            continue
        statistics = series.get("statistics") if isinstance(series.get("statistics"), dict) else {}
        size = int_value(statistics.get("sizeOnDisk"))
        files = int_value(statistics.get("episodeFileCount"))
        total_size += size
        file_count += files
        add_bucket(by_root, series.get("rootFolderPath") or "unknown", size, files)
        add_bucket(by_quality_profile, series.get("qualityProfileId") or "unknown", size, files)
    return {
        "ok": True,
        "detail": "series_statistics",
        "files": file_count,
        "bytes": total_size,
        "byQuality": {},
        "byCodec": {},
        "byRoot": sorted_buckets(by_root),
        "byQualityProfileId": sorted_buckets(by_quality_profile),
    }


def summarize_radarr_storage(base_url: str, api_key: str) -> dict[str, Any]:
    movie_payload = api_get(base_url, api_key, "/api/v3/movie")
    movie_records = movie_payload if isinstance(movie_payload, list) else []
    total_size = 0
    file_count = 0
    by_quality: dict[str, dict[str, int]] = {}
    by_codec: dict[str, dict[str, int]] = {}
    by_root: dict[str, dict[str, int]] = {}
    by_quality_profile: dict[str, dict[str, int]] = {}
    for movie in movie_records:
        if not isinstance(movie, dict):
            continue
        movie_file = movie.get("movieFile")
        if not isinstance(movie_file, dict) or not movie_file.get("id"):
            continue
        size = int_value(movie_file.get("size") or movie.get("sizeOnDisk"))
        file_count += 1
        total_size += size
        add_bucket(by_quality, quality_name(movie_file.get("quality")) or "unknown", size)
        add_bucket(by_codec, video_codec_name(movie_file), size)
        add_bucket(by_root, movie.get("rootFolderPath") or "unknown", size)
        add_bucket(by_quality_profile, movie.get("qualityProfileId") or "unknown", size)
    return {
        "ok": True,
        "files": file_count,
        "bytes": total_size,
        "byQuality": sorted_buckets(by_quality),
        "byCodec": sorted_buckets(by_codec),
        "byRoot": sorted_buckets(by_root),
        "byQualityProfileId": sorted_buckets(by_quality_profile),
    }


def storage_snapshot(args: argparse.Namespace, observed_at: str, sonarr_api_key: str) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "observedAt": observed_at,
        "kind": "storage_snapshot",
        "apps": {},
    }
    try:
        snapshot["apps"]["sonarr"] = summarize_sonarr_storage(args.base_url, sonarr_api_key)
    except Exception as exc:  # noqa: BLE001 - monitoring should preserve partial snapshots
        snapshot["apps"]["sonarr"] = {"ok": False, "error": str(exc)}

    if args.radarr_config and args.radarr_config.exists():
        try:
            radarr_api_key = read_api_key(args.radarr_config)
            snapshot["apps"]["radarr"] = summarize_radarr_storage(args.radarr_base_url, radarr_api_key)
        except Exception as exc:  # noqa: BLE001 - monitoring should preserve partial snapshots
            snapshot["apps"]["radarr"] = {"ok": False, "error": str(exc)}
    else:
        snapshot["apps"]["radarr"] = {"ok": False, "error": f"{args.radarr_config}: config not found"}

    return snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8989")
    parser.add_argument("--config", type=Path, default=Path("/opt/media-stack/sonarr/config.xml"))
    parser.add_argument("--radarr-base-url", default="http://127.0.0.1:7878")
    parser.add_argument("--radarr-config", type=Path, default=Path("/opt/media-stack/radarr/config.xml"))
    parser.add_argument("--state", type=Path, default=Path("/var/lib/sonarr-transaction-monitor/state.json"))
    parser.add_argument("--output", type=Path, default=Path("/var/log/sonarr-transaction-monitor/events.jsonl"))
    parser.add_argument("--bootstrap-records", type=int, default=1000)
    parser.add_argument("--max-history-pages", type=int, default=10)
    parser.add_argument("--no-storage-snapshot", action="store_true")
    parser.add_argument("--storage-snapshot-interval-sec", type=int, default=900)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = read_api_key(args.config)
    state = load_state(args.state)
    previous_last_id = int(state.get("last_history_id") or 0)
    observed_at = utc_now()
    observed_dt = parse_time(observed_at) or dt.datetime.now(dt.UTC)
    last_storage_snapshot_at = parse_time(state.get("last_storage_snapshot_at"))
    should_storage_snapshot = (
        not args.no_storage_snapshot
        and (
            last_storage_snapshot_at is None
            or (observed_dt - last_storage_snapshot_at).total_seconds()
            >= args.storage_snapshot_interval_sec
        )
    )

    history_records = fetch_new_history(
        args.base_url,
        api_key,
        previous_last_id,
        args.bootstrap_records,
        args.max_history_pages,
    )
    for record in sorted(history_records, key=lambda item: int(item.get("id") or 0)):
        append_event(
            args.output,
            {
                "observedAt": observed_at,
                "kind": "history",
                "bootstrap": previous_last_id == 0,
                "record": summarize_history(record),
            },
        )

    queue = api_get(
        args.base_url,
        api_key,
        "/api/v3/queue",
        {"page": 1, "pageSize": 1000, "includeUnknownSeriesItems": "true"},
    )
    queue_records = queue.get("records") or []
    append_event(
        args.output,
        {
            "observedAt": observed_at,
            "kind": "queue_snapshot",
            "count": len(queue_records),
            "records": [summarize_queue(record) for record in queue_records],
        },
    )
    if should_storage_snapshot:
        append_event(args.output, storage_snapshot(args, observed_at, api_key))

    max_history_id = previous_last_id
    for record in history_records:
        max_history_id = max(max_history_id, int(record.get("id") or 0))
    next_state = {
        "last_history_id": max_history_id,
        "last_observed_at": observed_at,
        "last_queue_count": len(queue_records),
        "last_storage_snapshot_at": state.get("last_storage_snapshot_at"),
    }
    if should_storage_snapshot:
        next_state["last_storage_snapshot_at"] = observed_at
    save_state(args.state, next_state)
    print(
        f"recorded history={len(history_records)} queue={len(queue_records)} "
        f"last_history_id={max_history_id}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
