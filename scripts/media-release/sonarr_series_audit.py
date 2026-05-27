#!/usr/bin/env python3
"""Summarize one Sonarr series' monitoring, files, queue, and grab history.

Run this on docker-vm. It is read-only and prints no API keys.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from typing import Any


def read_api_key(path: str) -> str:
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
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def quality_name(item: dict[str, Any] | None) -> str:
    if not item:
        return "unknown"
    quality = item.get("quality")
    if isinstance(quality, dict):
        return str(quality.get("name") or quality.get("source") or "unknown")
    return str(item.get("name") or "unknown")


def cf_names(items: list[dict[str, Any]] | None) -> list[str]:
    return [str(item.get("name") or item.get("id")) for item in items or []]


def find_series(series_list: list[dict[str, Any]], query: str) -> dict[str, Any]:
    lowered = query.lower()
    matches = [
        series
        for series in series_list
        if lowered == str(series.get("title", "")).lower()
        or lowered in str(series.get("title", "")).lower()
        or any(lowered in str(title.get("title", "")).lower() for title in series.get("alternateTitles") or [])
    ]
    if not matches:
        raise RuntimeError(f"no series matched {query!r}")
    if len(matches) > 1:
        names = ", ".join(f"{series['id']}:{series['title']}" for series in matches)
        raise RuntimeError(f"multiple series matched {query!r}: {names}")
    return matches[0]


def season_stats(episodes: list[dict[str, Any]]) -> dict[int, dict[str, int]]:
    stats: dict[int, dict[str, int]] = defaultdict(
        lambda: {"episodes": 0, "monitored": 0, "has_file": 0, "missing_monitored": 0}
    )
    for episode in episodes:
        season = int(episode.get("seasonNumber") or 0)
        bucket = stats[season]
        bucket["episodes"] += 1
        if episode.get("monitored"):
            bucket["monitored"] += 1
            if episode.get("hasFile"):
                bucket["has_file"] += 1
            else:
                bucket["missing_monitored"] += 1
    return dict(sorted(stats.items()))


def queue_summary(
    base_url: str, api_key: str, queue_records: list[dict[str, Any]], episode_cache: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    seasons = Counter()
    titles: dict[str, dict[str, Any]] = {}
    for record in queue_records:
        episode = record.get("episode") or {}
        episode_id = record.get("episodeId")
        if not episode and isinstance(episode_id, int):
            episode = episode_cache.get(episode_id)
            if episode is None:
                episode = api_get(base_url, api_key, f"/api/v3/episode/{episode_id}")
                episode_cache[episode_id] = episode
        season = episode.get("seasonNumber")
        seasons[str(season)] += 1
        title = str(record.get("title") or record.get("downloadTitle") or "unknown")
        entry = titles.setdefault(
            title,
            {
                "title": title,
                "records": 0,
                "score": record.get("customFormatScore")
                or (record.get("trackedDownload") or {}).get("customFormatScore"),
                "quality": quality_name(record.get("quality")),
                "cfs": cf_names(record.get("customFormats")),
                "status": record.get("status"),
                "tracked_state": record.get("trackedDownloadState"),
            },
        )
        entry["records"] += 1
    return {"season_rows": dict(sorted(seasons.items())), "downloads": list(titles.values())}


def record_series_id(
    base_url: str,
    api_key: str,
    record: dict[str, Any],
    episode_cache: dict[int, dict[str, Any]],
) -> int | None:
    series = record.get("series")
    if isinstance(series, dict) and isinstance(series.get("id"), int):
        return int(series["id"])

    episode = record.get("episode")
    if isinstance(episode, dict) and isinstance(episode.get("seriesId"), int):
        return int(episode["seriesId"])

    episode_id = record.get("episodeId")
    if isinstance(episode_id, int):
        episode = episode_cache.get(episode_id)
        if episode is None:
            episode = api_get(base_url, api_key, f"/api/v3/episode/{episode_id}")
            episode_cache[episode_id] = episode
        if isinstance(episode.get("seriesId"), int):
            return int(episode["seriesId"])
    return None


def history_summary(history_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for record in history_records:
        rows.append(
            {
                "date": record.get("date"),
                "event_type": record.get("eventType"),
                "season": (record.get("episode") or {}).get("seasonNumber"),
                "episode": (record.get("episode") or {}).get("episodeNumber"),
                "quality": quality_name(record.get("quality")),
                "score": record.get("customFormatScore"),
                "cfs": cf_names(record.get("customFormats")),
                "source_title": record.get("sourceTitle"),
                "indexer": (record.get("data") or {}).get("indexer"),
                "download_client": (record.get("data") or {}).get("downloadClientName"),
            }
        )
    return rows


def command_summary(commands: list[dict[str, Any]], series_id: int) -> list[dict[str, Any]]:
    rows = []
    for command in commands:
        body = command.get("body") or {}
        if body.get("seriesId") != series_id and series_id not in (body.get("seriesIds") or []):
            continue
        rows.append(
            {
                "id": command.get("id"),
                "name": command.get("name"),
                "status": command.get("status"),
                "state": command.get("state"),
                "queued": command.get("queued"),
                "started": command.get("started"),
                "ended": command.get("ended"),
                "message": command.get("message"),
            }
        )
    return rows


def audit(args: argparse.Namespace) -> dict[str, Any]:
    api_key = read_api_key(args.config)
    series = find_series(api_get(args.base_url, api_key, "/api/v3/series"), args.series)
    profiles = {
        profile["id"]: profile["name"]
        for profile in api_get(args.base_url, api_key, "/api/v3/qualityprofile")
    }
    episodes = api_get(args.base_url, api_key, "/api/v3/episode", {"seriesId": series["id"]})
    queue = api_get(
        args.base_url,
        api_key,
        "/api/v3/queue",
        {"seriesId": series["id"], "page": 1, "pageSize": 1000, "includeUnknownSeriesItems": "true"},
    )
    history = api_get(
        args.base_url,
        api_key,
        "/api/v3/history",
        {"seriesId": series["id"], "page": 1, "pageSize": args.history, "sortKey": "date", "sortDirection": "descending"},
    )
    commands = api_get(args.base_url, api_key, "/api/v3/command")
    monitored_missing = [
        episode
        for episode in episodes
        if episode.get("monitored") and not episode.get("hasFile")
    ]
    monitored_missing.sort(key=lambda episode: (episode.get("seasonNumber") or 0, episode.get("episodeNumber") or 0))
    episode_cache: dict[int, dict[str, Any]] = {
        episode["id"]: episode for episode in episodes if isinstance(episode.get("id"), int)
    }
    queue_records = [
        record
        for record in queue.get("records") or []
        if record_series_id(args.base_url, api_key, record, episode_cache) == series["id"]
    ]
    history_records = [
        record
        for record in history.get("records") or []
        if record_series_id(args.base_url, api_key, record, episode_cache) == series["id"]
    ]
    return {
        "series": {
            "id": series["id"],
            "title": series["title"],
            "path": series.get("path"),
            "monitored": series.get("monitored"),
            "quality_profile_id": series.get("qualityProfileId"),
            "quality_profile": profiles.get(series.get("qualityProfileId")),
            "season_folder": series.get("seasonFolder"),
            "seasons": series.get("seasons"),
        },
        "season_stats": season_stats(episodes),
        "missing_wanted_count": len(monitored_missing),
        "missing_wanted_sample": [
            {
                "season": episode.get("seasonNumber"),
                "episode": episode.get("episodeNumber"),
                "title": episode.get("title"),
                "air_date_utc": episode.get("airDateUtc"),
            }
            for episode in monitored_missing[:20]
        ],
        "queue": queue_summary(args.base_url, api_key, queue_records, episode_cache),
        "history": history_summary(history_records),
        "commands": command_summary(commands, series["id"]),
    }


def print_text(report: dict[str, Any]) -> None:
    series = report["series"]
    print(
        f"{series['title']} id={series['id']} monitored={series['monitored']} "
        f"profile={series['quality_profile']} path={series['path']}"
    )
    print("seasons:")
    for season in series["seasons"]:
        number = season.get("seasonNumber")
        stats = report["season_stats"].get(number, {})
        print(
            "  S{number:02}: monitored={monitored} episodes={episodes} has_file={has_file} "
            "missing_monitored={missing_monitored}".format(
                number=number,
                monitored=season.get("monitored"),
                episodes=stats.get("episodes", 0),
                has_file=stats.get("has_file", 0),
                missing_monitored=stats.get("missing_monitored", 0),
            )
        )
    print(f"wanted missing total: {report['missing_wanted_count']}")
    if report["missing_wanted_sample"]:
        print("wanted missing sample:")
        for episode in report["missing_wanted_sample"]:
            print(f"  S{episode['season']:02}E{episode['episode']:02}: {episode['title']}")
    print("queue by season:", report["queue"]["season_rows"])
    for item in report["queue"]["downloads"]:
        print(
            f"  queue: records={item['records']} quality={item['quality']} "
            f"score={item['score']} state={item['status']}/{item['tracked_state']}"
        )
        print(f"    {item['title']}")
        print(f"    CFs: {', '.join(item['cfs']) or '(none)'}")
    if report["commands"]:
        print("active/recent commands:")
        for command in report["commands"]:
            print(
                f"  #{command['id']} {command['name']} {command['status']}/{command['state']} "
                f"message={command['message']}"
            )
    print("recent series history:")
    for item in report["history"][:20]:
        season = item["season"]
        episode = item["episode"]
        label = f"S{season:02}E{episode:02}" if season is not None and episode is not None else "unknown"
        print(
            f"  {item['date']} {item['event_type']} {label} "
            f"{item['quality']} score={item['score']}"
        )
        print(f"    {item['source_title']}")
        print(f"    CFs: {', '.join(item['cfs']) or '(none)'}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("series")
    parser.add_argument("--base-url", default="http://127.0.0.1:8989")
    parser.add_argument("--config", default="/opt/media-stack/sonarr/config.xml")
    parser.add_argument("--history", type=int, default=80)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit(args)
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
