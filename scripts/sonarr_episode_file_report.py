#!/usr/bin/env python3
"""Report current Sonarr episode-file scores for one series.

Run this on docker-vm. It reads Sonarr's local config.xml for the API key and
prints no secrets.
"""

from __future__ import annotations

import argparse
import json
import sys
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
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


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


def quality_name(item: dict[str, Any] | None) -> str:
    if not item:
        return "unknown"
    quality = item.get("quality")
    if isinstance(quality, dict):
        return str(quality.get("name") or quality.get("source") or "unknown")
    return str(item.get("name") or "unknown")


def cf_names(items: list[dict[str, Any]] | None) -> list[str]:
    return [str(item.get("name") or item.get("id")) for item in items or []]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("series")
    parser.add_argument("--season", type=int)
    parser.add_argument("--base-url", default="http://127.0.0.1:8989")
    parser.add_argument("--config", default="/opt/media-stack/sonarr/config.xml")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = read_api_key(args.config)
    series = find_series(api_get(args.base_url, api_key, "/api/v3/series"), args.series)
    episodes = api_get(args.base_url, api_key, "/api/v3/episode", {"seriesId": series["id"]})
    episode_files = api_get(args.base_url, api_key, "/api/v3/episodefile", {"seriesId": series["id"]})
    files_by_id = {
        int(item["id"]): item
        for item in episode_files
        if isinstance(item.get("id"), int)
    }

    print(f"{series['title']} id={series['id']}")
    for episode in sorted(episodes, key=lambda item: (item.get("seasonNumber") or 0, item.get("episodeNumber") or 0)):
        season = int(episode.get("seasonNumber") or 0)
        if args.season is not None and season != args.season:
            continue
        number = int(episode.get("episodeNumber") or 0)
        episode_file = files_by_id.get(int(episode.get("episodeFileId") or 0))
        if not episode_file:
            print(f"S{season:02}E{number:02} missing monitored={episode.get('monitored')}")
            continue
        print(
            "S{season:02}E{episode:02} file_id={file_id} quality={quality} score={score}".format(
                season=season,
                episode=number,
                file_id=episode_file.get("id"),
                quality=quality_name(episode_file.get("quality")),
                score=episode_file.get("customFormatScore"),
            )
        )
        print(f"  {episode_file.get('relativePath')}")
        print(f"  CFs: {', '.join(cf_names(episode_file.get('customFormats'))) or '(none)'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
