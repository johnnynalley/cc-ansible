#!/usr/bin/env python3
"""Print Sonarr manual-import candidates for one series folder.

Run this on docker-vm. It reads Sonarr's local config.xml for the API key and
prints no secrets.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
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


def api_post(base_url: str, api_key: str, path: str, body: dict[str, Any]) -> Any:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Api-Key": api_key,
        },
        method="POST",
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
    parser.add_argument("--download-id")
    parser.add_argument("--import-path")
    parser.add_argument("--import-mode", default="Auto", choices=("Auto", "Move", "Copy"))
    parser.add_argument("--wait", type=int, default=120, help="seconds to wait for queued manual import completion")
    parser.add_argument("--season", type=int)
    parser.add_argument("--base-url", default="http://127.0.0.1:8989")
    parser.add_argument("--config", default="/opt/media-stack/sonarr/config.xml")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def request_params(args: argparse.Namespace, series: dict[str, Any]) -> dict[str, Any]:
    if args.download_id:
        return {
            "downloadId": args.download_id,
            "filterExistingFiles": "false",
        }

    folder = args.folder or str(series.get("path") or "")
    return {
        "seriesId": series["id"],
        "folder": folder,
        "filterExistingFiles": "false",
    }


def candidate_file(item: dict[str, Any]) -> dict[str, Any]:
    episodes = item.get("episodes") or []
    series = item.get("series") or {}
    return {
        "path": item["path"],
        "folderName": item.get("folderName"),
        "seriesId": series["id"],
        "episodeIds": [episode["id"] for episode in episodes],
        "episodeFileId": item.get("episodeFileId"),
        "quality": item.get("quality"),
        "languages": item.get("languages") or [],
        "releaseGroup": item.get("releaseGroup"),
        "indexerFlags": item.get("indexerFlags", 0),
        "releaseType": item.get("releaseType"),
        "downloadId": item.get("downloadId"),
    }


def find_import_candidate(candidates: list[dict[str, Any]], import_path: str) -> dict[str, Any]:
    matches = [item for item in candidates if item.get("path") == import_path]
    if not matches:
        raise RuntimeError(f"no manual-import candidate exactly matched path {import_path!r}")
    if len(matches) > 1:
        raise RuntimeError(f"{len(matches)} manual-import candidates matched path {import_path!r}")

    item = matches[0]
    rejections = item.get("rejections") or []
    episodes = item.get("episodes") or []
    if rejections:
        reasons = "; ".join(str(rejection.get("reason") or rejection) for rejection in rejections)
        raise RuntimeError(f"candidate has rejections: {reasons}")
    if not episodes:
        raise RuntimeError("candidate has no selected episodes")
    if not item.get("series", {}).get("id"):
        raise RuntimeError("candidate has no series id")
    return item


def wait_for_command(base_url: str, api_key: str, command_id: int, timeout: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        last = api_get(base_url, api_key, f"/api/v3/command/{command_id}")
        status = str(last.get("status") or "").lower()
        if status in {"completed", "failed"}:
            return last
        time.sleep(2)
    return last


def main() -> int:
    args = parse_args()
    api_key = read_api_key(args.config)
    series = find_series(api_get(args.base_url, api_key, "/api/v3/series"), args.series)
    candidates = api_get(
        args.base_url,
        api_key,
        "/api/v3/manualimport",
        request_params(args, series),
    )
    if args.import_path:
        item = find_import_candidate(candidates, args.import_path)
        command = api_post(
            args.base_url,
            api_key,
            "/api/v3/command",
            {
                "name": "ManualImport",
                "files": [candidate_file(item)],
                "importMode": args.import_mode,
            },
        )
        print(
            "queued ManualImport command id={id} status={status} path={path}".format(
                id=command.get("id"),
                status=command.get("status"),
                path=args.import_path,
            )
        )
        if args.wait and command.get("id"):
            final = wait_for_command(args.base_url, api_key, int(command["id"]), args.wait)
            print(
                "command id={id} status={status} message={message}".format(
                    id=final.get("id", command.get("id")),
                    status=final.get("status"),
                    message=final.get("message"),
                )
            )
        return 0

    if args.json:
        json.dump(candidates, sys.stdout, indent=2, sort_keys=True)
        print()
        return 0

    print(f"{series['title']} id={series['id']} params={request_params(args, series)}")
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
