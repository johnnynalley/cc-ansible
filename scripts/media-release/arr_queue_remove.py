#!/usr/bin/env python3
"""Dry-run or remove selected Sonarr/Radarr queue rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


APPS = {
    "radarr": {
        "base_url": "http://127.0.0.1:7878",
        "config": "/opt/media-stack/radarr/config.xml",
        "queue_params": {"includeMovie": "true"},
    },
    "sonarr": {
        "base_url": "http://127.0.0.1:8989",
        "config": "/opt/media-stack/sonarr/config.xml",
        "queue_params": {"includeSeries": "true", "includeEpisode": "true"},
    },
}


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def request_json(
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    timeout: int = 30,
) -> Any:
    query = ""
    if params:
        query = "?" + urllib.parse.urlencode(params, doseq=True)
    data = None
    headers = {"X-Api-Key": api_key, "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, sort_keys=True).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}{query}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8", errors="replace")
            return json.loads(payload) if payload else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code}: {detail}") from exc


def paged_queue(
    base_url: str,
    api_key: str,
    queue_params: dict[str, Any],
    page_size: int,
    max_pages: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        payload = request_json(
            base_url,
            api_key,
            "GET",
            "/api/v3/queue",
            {
                **queue_params,
                "page": page,
                "pageSize": page_size,
                "sortKey": "timeleft",
                "sortDirection": "ascending",
            },
        )
        page_records = payload.get("records", payload if isinstance(payload, list) else [])
        records.extend(page_records)
        total = payload.get("totalRecords") if isinstance(payload, dict) else None
        if isinstance(total, int) and len(records) >= total:
            break
        if len(page_records) < page_size:
            break
    return records


def status_messages(record: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    for status in record.get("statusMessages") or []:
        title = str(status.get("title") or "").strip()
        for message in status.get("messages") or []:
            text = str(message)
            messages.append(f"{title}: {text}" if title else text)
    error = record.get("errorMessage")
    if error:
        messages.append(str(error))
    return messages


def title_for_record(record: dict[str, Any]) -> str:
    return str(record.get("title") or record.get("downloadTitle") or "")


def label_for_record(app: str, record: dict[str, Any]) -> str:
    if app == "radarr":
        movie = record.get("movie") or {}
        return str(movie.get("title") or title_for_record(record))
    series = record.get("series") or {}
    episode = record.get("episode") or {}
    season = episode.get("seasonNumber")
    number = episode.get("episodeNumber")
    suffix = f"S{season:02}E{number:02}" if isinstance(season, int) and isinstance(number, int) else "episode"
    return f"{series.get('title') or title_for_record(record)} {suffix}"


def matches(record: dict[str, Any], args: argparse.Namespace) -> bool:
    if args.status and record.get("status") != args.status:
        return False
    if args.tracked_state and record.get("trackedDownloadState") != args.tracked_state:
        return False
    if args.download_client is not None:
        client = record.get("downloadClient")
        client_name = str(client or "")
        if args.download_client == "none":
            if client is not None:
                return False
        elif client_name.casefold() != args.download_client.casefold():
            return False
    if args.title_regex and not re.search(args.title_regex, title_for_record(record)):
        return False
    if args.message_regex:
        joined = "\n".join(status_messages(record))
        if not re.search(args.message_regex, joined):
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, choices=sorted(APPS))
    parser.add_argument("--status")
    parser.add_argument("--tracked-state")
    parser.add_argument(
        "--download-client",
        help="Download client name to match, or 'none' for null/unavailable rows.",
    )
    parser.add_argument("--title-regex")
    parser.add_argument("--message-regex")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-path", help="Existing rollback backup path. Required with --apply.")
    parser.add_argument(
        "--remove-from-client",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--blocklist",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    args = parser.parse_args()

    if args.apply:
        if not args.backup_path:
            raise RuntimeError("--apply requires --backup-path")
        backup_path = Path(args.backup_path)
        if not backup_path.exists():
            raise RuntimeError(f"backup path does not exist: {backup_path}")

    app_info = APPS[args.app]
    api_key = read_api_key(app_info["config"])
    records = paged_queue(
        app_info["base_url"],
        api_key,
        app_info["queue_params"],
        args.page_size,
        args.max_pages,
    )
    selected = [record for record in records if matches(record, args)]
    if args.limit is not None:
        selected = selected[: args.limit]

    removals: list[dict[str, Any]] = []
    for record in selected:
        queue_id = record.get("id")
        summary = {
            "id": queue_id,
            "title": title_for_record(record),
            "label": label_for_record(args.app, record),
            "status": record.get("status"),
            "tracked_state": record.get("trackedDownloadState"),
            "download_client": record.get("downloadClient"),
            "download_id": record.get("downloadId"),
            "messages": status_messages(record),
        }
        if args.apply:
            if not isinstance(queue_id, int):
                summary["result"] = "skipped missing queue id"
            else:
                try:
                    request_json(
                        app_info["base_url"],
                        api_key,
                        "DELETE",
                        f"/api/v3/queue/{queue_id}",
                        {
                            "removeFromClient": str(args.remove_from_client).lower(),
                            "blocklist": str(args.blocklist).lower(),
                        },
                    )
                    summary["result"] = "removed"
                except RuntimeError as exc:
                    if "HTTP 404" not in str(exc):
                        raise
                    summary["result"] = "already_missing"
        removals.append(summary)

    print(
        json.dumps(
            {
                "app": args.app,
                "apply": args.apply,
                "queue_records": len(records),
                "matched_rows": len(selected),
                "remove_from_client": args.remove_from_client,
                "blocklist": args.blocklist,
                "matches": removals,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
