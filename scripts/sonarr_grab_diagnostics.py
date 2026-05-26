#!/usr/bin/env python3
"""Compare Sonarr queued grabs against the current episode files.

Run on docker-vm. By default this is read-only and prints no API keys. Cleanup
requires explicit flags and never blocklists unless asked.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def api_get(base_url: str, api_key: str, path: str, params: dict[str, Any] | None = None) -> Any:
    query = ""
    if params:
        query = "?" + urllib.parse.urlencode(params, doseq=True)
    url = f"{base_url.rstrip('/')}{path}{query}"
    req = urllib.request.Request(url, headers={"X-Api-Key": api_key})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {path} failed: {exc.code} {body}") from exc


def api_delete(
    base_url: str, api_key: str, path: str, params: dict[str, Any] | None = None
) -> tuple[int, str]:
    query = ""
    if params:
        query = "?" + urllib.parse.urlencode(params)
    url = f"{base_url.rstrip('/')}{path}{query}"
    req = urllib.request.Request(url, headers={"X-Api-Key": api_key}, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.getcode(), response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DELETE {path} failed: {exc.code} {body}") from exc


def quality_label(value: dict[str, Any] | None) -> str:
    if not isinstance(value, dict):
        return "unknown"
    quality = value.get("quality")
    if isinstance(quality, dict):
        return str(quality.get("name") or quality.get("source") or "unknown")
    return str(value.get("name") or "unknown")


def cf_names(values: list[dict[str, Any]] | None) -> list[str]:
    if not values:
        return []
    return [str(value.get("name") or value.get("id")) for value in values]


def status_messages(record: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    for status in record.get("statusMessages") or []:
        title = status.get("title")
        for message in status.get("messages") or []:
            if title:
                messages.append(f"{title}: {message}")
            else:
                messages.append(str(message))
    return messages


def summarize_queue_record(
    base_url: str,
    api_key: str,
    record: dict[str, Any],
    episode_cache: dict[int, dict[str, Any]],
    episode_file_cache: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    episode_id = record.get("episodeId")
    episode = None
    if isinstance(episode_id, int):
        episode = episode_cache.get(episode_id)
        if episode is None:
            episode = api_get(base_url, api_key, f"/api/v3/episode/{episode_id}")
            episode_cache[episode_id] = episode

    file_id = episode.get("episodeFileId") if isinstance(episode, dict) else None
    episode_file = None
    if isinstance(file_id, int) and file_id > 0:
        episode_file = episode_file_cache.get(file_id)
        if episode_file is None:
            episode_file = api_get(base_url, api_key, f"/api/v3/episodefile/{file_id}")
            episode_file_cache[file_id] = episode_file

    queued_score = record.get("customFormatScore")
    if queued_score is None:
        queued_score = record.get("trackedDownload", {}).get("customFormatScore")
    current_score = episode_file.get("customFormatScore") if isinstance(episode_file, dict) else None

    return {
        "queue_id": record.get("id"),
        "download_id": record.get("downloadId"),
        "series": (record.get("series") or {}).get("title"),
        "season": (record.get("episode") or episode or {}).get("seasonNumber"),
        "episode": (record.get("episode") or episode or {}).get("episodeNumber"),
        "queued_title": record.get("title") or record.get("downloadTitle"),
        "queued_quality": quality_label(record.get("quality")),
        "queued_cf_score": queued_score,
        "queued_cfs": cf_names(record.get("customFormats")),
        "current_path": episode_file.get("path") if isinstance(episode_file, dict) else None,
        "current_quality": quality_label(episode_file.get("quality")) if isinstance(episode_file, dict) else None,
        "current_cf_score": current_score,
        "current_cfs": cf_names(episode_file.get("customFormats")) if isinstance(episode_file, dict) else [],
        "protocol": record.get("protocol"),
        "download_client": record.get("downloadClient"),
        "tracked_state": record.get("trackedDownloadState"),
        "status": record.get("status"),
        "error_message": record.get("errorMessage"),
        "status_messages": status_messages(record),
    }


def summarize_history_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": record.get("date"),
        "event_type": record.get("eventType"),
        "series": (record.get("series") or {}).get("title"),
        "season": (record.get("episode") or {}).get("seasonNumber"),
        "episode": (record.get("episode") or {}).get("episodeNumber"),
        "source_title": record.get("sourceTitle"),
        "quality": quality_label(record.get("quality")),
        "cf_score": record.get("customFormatScore"),
        "cfs": cf_names(record.get("customFormats")),
        "data": {
            key: record.get("data", {}).get(key)
            for key in ("indexer", "releaseGroup", "downloadClientName", "ageHours", "publishedDate")
        },
    }


def print_text(report: dict[str, Any]) -> None:
    queue = report["queue"]
    print(f"queue records: {len(queue)} of {report['queue_total']}")
    print("queue release groups:")
    for item in report["queue_groups"]:
        print(f"- {item['title']}")
        print(
            "  records={records} current_better={current_better} queued_better={queued_better} "
            "same_or_unknown={same_or_unknown} queued_scores={queued_scores}".format(**item)
        )
        print(f"  series: {', '.join(item['series'])}")
    print()
    if report["include_details"]:
        for item in queue:
            label = f"S{item['season']:02}E{item['episode']:02}" if item["season"] is not None else "unknown episode"
            print(f"- {item['series']} {label}")
            print(f"  queued: {item['queued_quality']} score={item['queued_cf_score']} {item['queued_title']}")
            print(f"  queued CFs: {', '.join(item['queued_cfs']) or '(none)'}")
            print(f"  current: {item['current_quality']} score={item['current_cf_score']} {item['current_path']}")
            print(f"  current CFs: {', '.join(item['current_cfs']) or '(none)'}")
            print(f"  state: {item['status']} / {item['tracked_state']} via {item['download_client']}")
            print(f"  queue_id={item['queue_id']} download_id={item['download_id']}")
            for message in item["status_messages"][:3]:
                print(f"  message: {message}")
        print()
    if report["cleanup_candidates"]:
        print()
        print(
            "cleanup candidates: {rows} queue rows across {downloads} downloads where current file score is higher".format(
                rows=report["cleanup_candidate_rows"],
                downloads=len(report["cleanup_candidates"]),
            )
        )
        for item in report["cleanup_candidates"]:
            print(f"- queue_id={item['queue_id']} download_id={item['download_id']} {item['queued_title']}")
    if report["cleanup_results"]:
        print()
        print(f"cleanup removed downloads: {len(report['cleanup_results'])}")
        for item in report["cleanup_results"]:
            print(f"- queue_id={item['queue_id']} download_id={item['download_id']} {item['status']}: {item['queued_title']}")
    print()
    print(f"recent grabbed history: {len(report['recent_grabs'])}")
    for item in report["recent_grabs"]:
        label = f"S{item['season']:02}E{item['episode']:02}" if item["season"] is not None else "unknown episode"
        print(f"- {item['date']} {item['series']} {label}")
        print(f"  grabbed: {item['quality']} score={item['cf_score']} {item['source_title']}")
        print(f"  CFs: {', '.join(item['cfs']) or '(none)'}")
        print(f"  data: {item['data']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--details", action="store_true", help="print every queued episode row")
    parser.add_argument("--base-url", default="http://127.0.0.1:8989")
    parser.add_argument("--config", default="/opt/media-stack/sonarr/config.xml")
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--history-size", type=int, default=25)
    parser.add_argument(
        "--remove-current-better",
        action="store_true",
        help="remove queue downloads where the existing file has a higher CF score",
    )
    parser.add_argument(
        "--remove-from-client",
        action="store_true",
        help="also remove matching downloads from the download client",
    )
    parser.add_argument(
        "--blocklist",
        action="store_true",
        help="blocklist removed releases; default is false",
    )
    return parser.parse_args()


def queue_groups(queue: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for item in queue:
        title = str(item.get("queued_title") or "unknown")
        group = groups.setdefault(
            title,
            {
                "title": title,
                "records": 0,
                "current_better": 0,
                "queued_better": 0,
                "same_or_unknown": 0,
                "queued_scores": set(),
                "series": set(),
            },
        )
        group["records"] += 1
        group["series"].add(str(item.get("series") or "unknown"))
        if item.get("queued_cf_score") is not None:
            group["queued_scores"].add(str(item["queued_cf_score"]))
        queued_score = item.get("queued_cf_score")
        current_score = item.get("current_cf_score")
        if isinstance(queued_score, int) and isinstance(current_score, int):
            if current_score > queued_score:
                group["current_better"] += 1
            elif queued_score > current_score:
                group["queued_better"] += 1
            else:
                group["same_or_unknown"] += 1
        else:
            group["same_or_unknown"] += 1

    result = []
    for group in groups.values():
        result.append(
            {
                **group,
                "queued_scores": sorted(group["queued_scores"]),
                "series": sorted(group["series"]),
            }
        )
    return sorted(
        result,
        key=lambda item: (item["current_better"], item["records"]),
        reverse=True,
    )


def current_better(item: dict[str, Any]) -> bool:
    queued_score = item.get("queued_cf_score")
    current_score = item.get("current_cf_score")
    return (
        isinstance(queued_score, int)
        and isinstance(current_score, int)
        and current_score > queued_score
    )


def cleanup_candidates(queue: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    row_count = 0
    for item in queue:
        if not current_better(item):
            continue
        row_count += 1
        key = str(item.get("download_id") or f"queue:{item.get('queue_id')}")
        if key in seen:
            continue
        seen.add(key)
        candidates.append(item)
    return candidates, row_count


def remove_queue_items(
    base_url: str,
    api_key: str,
    candidates: list[dict[str, Any]],
    remove_from_client: bool,
    blocklist: bool,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in candidates:
        queue_id = item.get("queue_id")
        if not isinstance(queue_id, int):
            results.append({**item, "status": "skipped missing queue id"})
            continue
        api_delete(
            base_url,
            api_key,
            f"/api/v3/queue/{queue_id}",
            {
                "removeFromClient": str(remove_from_client).lower(),
                "blocklist": str(blocklist).lower(),
            },
        )
        results.append({**item, "status": "removed"})
    return results


def main() -> int:
    args = parse_args()
    api_key = read_api_key(args.config)
    queue_page = api_get(
        args.base_url,
        api_key,
        "/api/v3/queue",
        {
            "page": 1,
            "pageSize": args.page_size,
            "includeSeries": "true",
            "includeEpisode": "true",
            "sortKey": "timeleft",
            "sortDirection": "ascending",
        },
    )
    history_page = api_get(
        args.base_url,
        api_key,
        "/api/v3/history",
        {
            "page": 1,
            "pageSize": args.history_size,
            "includeSeries": "true",
            "includeEpisode": "true",
            "sortKey": "date",
            "sortDirection": "descending",
        },
    )

    episode_cache: dict[int, dict[str, Any]] = {}
    episode_file_cache: dict[int, dict[str, Any]] = {}
    records = queue_page.get("records", queue_page if isinstance(queue_page, list) else [])
    queue = [
        summarize_queue_record(
            args.base_url, api_key, record, episode_cache, episode_file_cache
        )
        for record in records
    ]
    candidates, candidate_rows = cleanup_candidates(queue)
    cleanup_results: list[dict[str, Any]] = []
    if args.remove_current_better:
        cleanup_results = remove_queue_items(
            args.base_url,
            api_key,
            candidates,
            remove_from_client=args.remove_from_client,
            blocklist=args.blocklist,
        )

    report = {
        "queue_total": queue_page.get("totalRecords") if isinstance(queue_page, dict) else len(records),
        "include_details": args.details,
        "queue": queue,
        "cleanup_candidate_rows": candidate_rows,
        "cleanup_candidates": candidates,
        "cleanup_results": cleanup_results,
        "recent_grabs": [
            summarize_history_record(record)
            for record in history_page.get("records", [])
            if str(record.get("eventType", "")).lower() in {"grabbed", "1"}
        ],
    }
    report["queue_groups"] = queue_groups(report["queue"])

    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        print_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
