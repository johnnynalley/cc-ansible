#!/usr/bin/env python3
"""Summarize Sonarr queue status messages without dumping every episode row."""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:8989"
DEFAULT_CONFIG = "/opt/media-stack/sonarr/config.xml"


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def api_get(base_url: str, api_key: str, path: str, params: dict[str, Any]) -> Any:
    query = "?" + urllib.parse.urlencode(params, doseq=True)
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}{query}",
        headers={"X-Api-Key": api_key},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def status_messages(record: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    for status in record.get("statusMessages") or []:
        title = str(status.get("title") or "").strip()
        for message in status.get("messages") or []:
            text = str(message)
            messages.append(f"{title}: {text}" if title else text)
    if record.get("errorMessage"):
        messages.append(str(record["errorMessage"]))
    return messages


def simplify_message(message: str) -> str:
    lowered = message.lower()
    if "unable to move existing file to the recycle bin" in lowered:
        return "unable to move existing file to the Recycle Bin"
    if "no files found are eligible for import" in lowered:
        return "no files found eligible for import"
    if "not an upgrade" in lowered:
        return "not an upgrade"
    if "tba title" in lowered:
        return "episode has a TBA title"
    return message


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--sample-limit", type=int, default=8)
    args = parser.parse_args()

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
    records = queue_page.get("records", queue_page if isinstance(queue_page, list) else [])

    categories: Counter[str] = Counter()
    downloads_by_category: dict[str, set[str]] = defaultdict(set)
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for record in records:
        messages = status_messages(record)
        if not messages:
            categories["no status messages"] += 1
            continue
        for message in messages:
            category = simplify_message(message)
            categories[category] += 1
            download_key = str(record.get("downloadId") or record.get("id"))
            downloads_by_category[category].add(download_key)
            if len(samples[category]) < args.sample_limit:
                episode = record.get("episode") or {}
                samples[category].append(
                    {
                        "title": record.get("title") or record.get("downloadTitle"),
                        "series": (record.get("series") or {}).get("title"),
                        "episode": (
                            f"S{episode.get('seasonNumber'):02}E{episode.get('episodeNumber'):02}"
                            if isinstance(episode.get("seasonNumber"), int)
                            and isinstance(episode.get("episodeNumber"), int)
                            else None
                        ),
                        "status": record.get("status"),
                        "tracked_state": record.get("trackedDownloadState"),
                        "message": message,
                    }
                )

    total = queue_page.get("totalRecords") if isinstance(queue_page, dict) else len(records)
    print(f"queue records: {len(records)} of {total}")
    print("status categories:")
    for category, count in categories.most_common():
        print(
            f"- {category}: rows={count}, downloads={len(downloads_by_category.get(category, set()))}"
        )
        for sample in samples.get(category, []):
            print(
                "  sample: {series} {episode} {status}/{tracked_state} {title}".format(
                    **sample
                )
            )
            print(f"    message: {sample['message']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
