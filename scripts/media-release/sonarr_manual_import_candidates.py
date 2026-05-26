#!/usr/bin/env python3
"""Print Sonarr manual-import candidates for one series folder.

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
    with urllib.request.urlopen(request, timeout=120) as response:
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
    parser.add_argument("--folder")
    parser.add_argument("--season", type=int)
    parser.add_argument("--base-url", default="http://127.0.0.1:8989")
    parser.add_argument("--config", default="/opt/media-stack/sonarr/config.xml")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = read_api_key(args.config)
    series = find_series(api_get(args.base_url, api_key, "/api/v3/series"), args.series)
    folder = args.folder or str(series.get("path") or "")
    candidates = api_get(
        args.base_url,
        api_key,
        "/api/v3/manualimport",
        {
            "seriesId": series["id"],
            "folder": folder,
            "filterExistingFiles": "false",
        },
    )
    if args.json:
        json.dump(candidates, sys.stdout, indent=2, sort_keys=True)
        print()
        return 0

    print(f"{series['title']} id={series['id']} folder={folder}")
    for item in candidates:
        episodes = item.get("episodes") or []
        if args.season is not None and not any(int(ep.get("seasonNumber") or 0) == args.season for ep in episodes):
            continue
        labels = [
            "S{season:02}E{episode:02}".format(
                season=int(ep.get("seasonNumber") or 0),
                episode=int(ep.get("episodeNumber") or 0),
            )
            for ep in episodes
        ]
        print(
            "{labels} quality={quality} score={score} rejections={rejections}".format(
                labels=",".join(labels) or "unknown",
                quality=quality_name(item.get("quality")),
                score=item.get("customFormatScore"),
                rejections="; ".join(str(rej.get("reason") or rej) for rej in item.get("rejections") or []),
            )
        )
        print(f"  {item.get('path')}")
        print(f"  CFs: {', '.join(cf_names(item.get('customFormats'))) or '(none)'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
