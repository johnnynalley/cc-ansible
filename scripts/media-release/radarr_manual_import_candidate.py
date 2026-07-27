#!/usr/bin/env python3
"""Inspect or import one exact Radarr manual-import candidate.

Run on docker-vm. The script reads Radarr's local API key, prints no secrets,
and requires an exact candidate path before it can queue an import.
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


def api_request(
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> Any:
    query = "?" + urllib.parse.urlencode(params, doseq=True) if params else ""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}{query}",
        data=data,
        headers={"Content-Type": "application/json", "X-Api-Key": api_key},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def find_movie(movies: list[dict[str, Any]], query: str) -> dict[str, Any]:
    lowered = query.casefold()
    exact = [movie for movie in movies if lowered == str(movie.get("title") or "").casefold()]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        names = ", ".join(f"{movie['id']}:{movie['title']}" for movie in exact)
        raise RuntimeError(f"multiple movies exactly matched {query!r}: {names}")

    matches = [
        movie
        for movie in movies
        if lowered in str(movie.get("title") or "").casefold()
    ]
    if not matches:
        raise RuntimeError(f"no movie matched {query!r}")
    if len(matches) > 1:
        names = ", ".join(f"{movie['id']}:{movie['title']}" for movie in matches)
        raise RuntimeError(f"multiple movies matched {query!r}: {names}")
    return matches[0]


def rejection_reasons(item: dict[str, Any]) -> list[str]:
    return [
        str(rejection.get("reason") or rejection)
        if isinstance(rejection, dict)
        else str(rejection)
        for rejection in item.get("rejections") or []
    ]


def quality_name(item: dict[str, Any]) -> str:
    quality = item.get("quality") or {}
    nested = quality.get("quality") if isinstance(quality, dict) else None
    if isinstance(nested, dict):
        return str(nested.get("name") or "unknown")
    return str(quality.get("name") or "unknown") if isinstance(quality, dict) else "unknown"


def language_names(item: dict[str, Any]) -> list[str]:
    return [str(language.get("name") or language.get("id")) for language in item.get("languages") or []]


def cf_names(item: dict[str, Any]) -> list[str]:
    return [str(custom_format.get("name") or custom_format.get("id")) for custom_format in item.get("customFormats") or []]


def candidate_file(item: dict[str, Any], movie_id: int, download_id: str) -> dict[str, Any]:
    return {
        "path": item["path"],
        "folderName": item.get("folderName"),
        "movieId": movie_id,
        "movieFileId": item.get("movieFileId") or 0,
        "quality": item.get("quality"),
        "languages": item.get("languages") or [],
        "releaseGroup": item.get("releaseGroup"),
        "indexerFlags": item.get("indexerFlags", 0),
        "downloadId": item.get("downloadId") or download_id,
    }


def has_only_unparseable_rejection(item: dict[str, Any]) -> bool:
    rejections = rejection_reasons(item)
    return bool(rejections) and all(reason.casefold() == "unable to parse file" for reason in rejections)


def queue_records_for_download(
    base_url: str,
    api_key: str,
    movie_id: int,
    download_id: str,
) -> list[dict[str, Any]]:
    records = api_request(
        base_url,
        api_key,
        "GET",
        "/api/v3/queue/details",
        {"movieId": movie_id},
    )
    return [record for record in records if record.get("downloadId") == download_id]


def candidate_file_with_queue_override(
    item: dict[str, Any],
    movie_id: int,
    download_id: str,
    queue_records: list[dict[str, Any]],
) -> dict[str, Any]:
    matching = [
        record
        for record in queue_records
        if record.get("movieId") == movie_id
        and record.get("outputPath") == item.get("path")
    ]
    if len(matching) != 1:
        raise RuntimeError(f"expected exactly one matching queue row, found {len(matching)}")
    queue = matching[0]
    quality = queue.get("quality") or item.get("quality")
    if not quality:
        raise RuntimeError("no quality was available from the candidate or queue row")

    return {
        "path": item["path"],
        "folderName": item.get("folderName"),
        "movieId": movie_id,
        "movieFileId": item.get("movieFileId") or queue.get("movieFileId") or 0,
        "quality": quality,
        "languages": queue.get("languages") or item.get("languages") or [],
        "releaseGroup": item.get("releaseGroup") or queue.get("releaseGroup"),
        "indexerFlags": item.get("indexerFlags") or queue.get("indexerFlags") or 0,
        "downloadId": item.get("downloadId") or queue.get("downloadId") or download_id,
    }


def wait_for_command(base_url: str, api_key: str, command_id: int, timeout: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = api_request(base_url, api_key, "GET", f"/api/v3/command/{command_id}")
        if str(last.get("status") or "").casefold() in {"completed", "failed"}:
            return last
        time.sleep(2)
    return last


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("movie")
    parser.add_argument("--download-id", required=True)
    parser.add_argument("--import-path")
    parser.add_argument(
        "--allow-unparseable-queue-match",
        action="store_true",
        help=(
            "allow an Unable to parse file candidate only when one Radarr queue row "
            "matches its movie, download ID, and exact output path"
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--import-mode", default="Auto", choices=("Auto", "Move", "Copy"))
    parser.add_argument("--wait", type=int, default=120)
    parser.add_argument("--base-url", default="http://127.0.0.1:7878")
    parser.add_argument("--config", default="/opt/media-stack/radarr/config.xml")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = read_api_key(args.config)
    movie = find_movie(api_request(args.base_url, api_key, "GET", "/api/v3/movie"), args.movie)
    candidates = api_request(
        args.base_url,
        api_key,
        "GET",
        "/api/v3/manualimport",
        {
            "downloadId": args.download_id,
            "movieId": movie["id"],
            "filterExistingFiles": "false",
        },
    )

    if args.json and not args.import_path:
        json.dump(candidates, sys.stdout, indent=2, sort_keys=True)
        print()
        return 0

    if not args.import_path:
        print(f"{movie['title']} id={movie['id']} candidates={len(candidates)}")
        for item in candidates:
            print(
                f"- score={item.get('customFormatScore')} quality={quality_name(item)} "
                f"languages={'+'.join(language_names(item)) or 'unknown'} {item.get('path')}"
            )
            print(f"  CFs={', '.join(cf_names(item)) or '(none)'}")
            reasons = rejection_reasons(item)
            if reasons:
                print(f"  rejections={'; '.join(reasons)}")
        return 0

    selected = [item for item in candidates if item.get("path") == args.import_path]
    if len(selected) != 1:
        raise RuntimeError(f"expected exactly one candidate matching --import-path, found {len(selected)}")
    item = selected[0]
    reasons = rejection_reasons(item)
    if reasons and not (
        args.allow_unparseable_queue_match and has_only_unparseable_rejection(item)
    ):
        raise RuntimeError(f"candidate has rejections: {'; '.join(reasons)}")

    if reasons:
        queue_records = queue_records_for_download(
            args.base_url,
            api_key,
            int(movie["id"]),
            args.download_id,
        )
        import_file = candidate_file_with_queue_override(
            item,
            int(movie["id"]),
            args.download_id,
            queue_records,
        )
    else:
        import_file = candidate_file(item, int(movie["id"]), args.download_id)

    print(
        f"selected {movie['title']} score={item.get('customFormatScore')} "
        f"languages={'+'.join(language_names(item)) or 'unknown'} path={item['path']}"
    )
    if args.dry_run:
        return 0

    command = api_request(
        args.base_url,
        api_key,
        "POST",
        "/api/v3/command",
        body={
            "name": "ManualImport",
            "files": [import_file],
            "importMode": args.import_mode,
        },
    )
    print(f"queued ManualImport command id={command.get('id')} status={command.get('status')}")
    if args.wait and command.get("id"):
        final = wait_for_command(args.base_url, api_key, int(command["id"]), args.wait)
        print(
            f"command id={final.get('id', command.get('id'))} "
            f"status={final.get('status')} message={final.get('message')}"
        )
        return 0 if str(final.get("status") or "").casefold() == "completed" else 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
