#!/usr/bin/env python3
"""Report Sonarr manual-search release candidates and rejection reasons.

Run this on docker-vm. It reads Sonarr's local config.xml for the API key,
queries localhost only, and prints no secrets.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
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
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {path}{query} failed: {exc.code} {body}") from exc


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


def quality_name(value: dict[str, Any] | None) -> str:
    if not isinstance(value, dict):
        return "unknown"
    quality = value.get("quality")
    if isinstance(quality, dict):
        return str(quality.get("name") or quality.get("source") or "unknown")
    return str(value.get("name") or "unknown")


def cf_names(values: list[dict[str, Any]] | None) -> list[str]:
    return [str(value.get("name") or value.get("id")) for value in values or []]


def release_score(release: dict[str, Any]) -> int | None:
    for key in ("customFormatScore", "preferredWordScore"):
        value = release.get(key)
        if isinstance(value, int):
            return value
    return None


def rejection_reasons(release: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for item in release.get("rejections") or []:
        if isinstance(item, str):
            reasons.append(item)
        elif isinstance(item, dict):
            reason = item.get("reason") or item.get("message")
            if reason:
                reasons.append(str(reason))
    return reasons


def release_title(release: dict[str, Any]) -> str:
    return str(release.get("title") or release.get("releaseTitle") or "")


def current_file_report(
    base_url: str,
    api_key: str,
    episodes: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    file_ids = sorted(
        {
            int(episode.get("episodeFileId") or 0)
            for episode in episodes
            if int(episode.get("episodeFileId") or 0) > 0
        }
    )
    files: dict[int, dict[str, Any]] = {}
    for file_id in file_ids:
        item = api_get(base_url, api_key, f"/api/v3/episodefile/{file_id}")
        files[file_id] = {
            "id": item.get("id"),
            "quality": quality_name(item.get("quality")),
            "score": item.get("customFormatScore"),
            "custom_formats": cf_names(item.get("customFormats")),
            "path": item.get("path"),
        }
    return files


def search_releases(base_url: str, api_key: str, series_id: int, season: int | None, episode_id: int | None) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    if episode_id is not None:
        attempts.append({"episodeId": episode_id})
    if season is not None:
        attempts.append({"seriesId": series_id, "seasonNumber": season})
    attempts.append({"seriesId": series_id})

    last_error: Exception | None = None
    for params in attempts:
        try:
            releases = api_get(base_url, api_key, "/api/v3/release", params)
        except RuntimeError as exc:
            last_error = exc
            continue
        if isinstance(releases, list):
            return releases
    if last_error:
        raise last_error
    return []


def select_episodes(episodes: list[dict[str, Any]], season: int | None, episode_number: int | None) -> list[dict[str, Any]]:
    selected = episodes
    if season is not None:
        selected = [episode for episode in selected if int(episode.get("seasonNumber") or -1) == season]
    if episode_number is not None:
        selected = [episode for episode in selected if int(episode.get("episodeNumber") or -1) == episode_number]
    selected.sort(key=lambda item: (int(item.get("seasonNumber") or 0), int(item.get("episodeNumber") or 0)))
    return selected


def audit(args: argparse.Namespace) -> dict[str, Any]:
    api_key = read_api_key(args.config)
    series = find_series(api_get(args.base_url, api_key, "/api/v3/series"), args.series)
    all_episodes = api_get(args.base_url, api_key, "/api/v3/episode", {"seriesId": series["id"]})
    episodes = select_episodes(all_episodes, args.season, args.episode)
    if not episodes:
        raise RuntimeError("no matching episodes")

    search_episode = next((episode for episode in episodes if episode.get("monitored")), episodes[0])
    releases = search_releases(
        args.base_url,
        api_key,
        int(series["id"]),
        args.season,
        int(search_episode["id"]) if args.episode is not None else None,
    )
    title_filter = re.compile(args.title_regex, re.IGNORECASE) if args.title_regex else None
    filtered = [
        release for release in releases
        if title_filter is None or title_filter.search(release_title(release))
    ]
    filtered.sort(
        key=lambda release: (
            bool(rejection_reasons(release)),
            -(release_score(release) or -1000000),
            release_title(release).lower(),
        )
    )

    files = current_file_report(args.base_url, api_key, episodes)
    episode_rows = []
    for episode in episodes:
        file_id = int(episode.get("episodeFileId") or 0)
        episode_rows.append(
            {
                "id": episode.get("id"),
                "season": episode.get("seasonNumber"),
                "episode": episode.get("episodeNumber"),
                "title": episode.get("title"),
                "monitored": episode.get("monitored"),
                "has_file": episode.get("hasFile"),
                "file": files.get(file_id),
            }
        )

    return {
        "series": {
            "id": series.get("id"),
            "title": series.get("title"),
            "quality_profile_id": series.get("qualityProfileId"),
        },
        "search_basis": {
            "season": args.season,
            "episode": args.episode,
            "search_episode_id": search_episode.get("id"),
            "search_episode": f"S{int(search_episode.get('seasonNumber') or 0):02}E{int(search_episode.get('episodeNumber') or 0):02}",
        },
        "episodes": episode_rows,
        "release_count": len(releases),
        "filtered_release_count": len(filtered),
        "releases": [
            {
                "title": release_title(release),
                "indexer": release.get("indexer"),
                "quality": quality_name(release.get("quality")),
                "score": release_score(release),
                "custom_formats": cf_names(release.get("customFormats")),
                "size": release.get("size"),
                "seeders": release.get("seeders"),
                "protocol": release.get("protocol"),
                "rejections": rejection_reasons(release),
            }
            for release in filtered[:args.limit]
        ],
    }


def print_text(report: dict[str, Any]) -> None:
    series = report["series"]
    basis = report["search_basis"]
    print(
        f"{series['title']} id={series['id']} profile_id={series['quality_profile_id']} "
        f"search={basis['search_episode']} season={basis['season']}"
    )
    print("current files:")
    for episode in report["episodes"]:
        label = f"S{int(episode['season'] or 0):02}E{int(episode['episode'] or 0):02}"
        current = episode["file"]
        if current:
            print(f"  {label}: {current['quality']} score={current['score']} {current['path']}")
            print(f"    CFs: {', '.join(current['custom_formats']) or '(none)'}")
        else:
            print(f"  {label}: missing monitored={episode['monitored']}")
    print(f"releases: {report['filtered_release_count']} shown/filter matches out of {report['release_count']}")
    for release in report["releases"]:
        print(f"- {release['quality']} score={release['score']} seeders={release['seeders']} {release['title']}")
        print(f"  CFs: {', '.join(release['custom_formats']) or '(none)'}")
        if release["rejections"]:
            for reason in release["rejections"]:
                print(f"  reject: {reason}")
        else:
            print("  accepted")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("series")
    parser.add_argument("--season", type=int)
    parser.add_argument("--episode", type=int)
    parser.add_argument("--title-regex", help="case-insensitive release title filter")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--base-url", default="http://127.0.0.1:8989")
    parser.add_argument("--config", default="/opt/media-stack/sonarr/config.xml")
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
