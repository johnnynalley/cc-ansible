#!/usr/bin/env python3
"""Audit Radarr anime profile files/queue for DA double scoring.

Run this on docker-vm. It reads Radarr's local config.xml for the API key and
queries localhost only. It does not mutate Radarr.
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


RADARR_URL = "http://127.0.0.1:7878"
RADARR_CONFIG = "/opt/media-stack/radarr/config.xml"
PROFILE_NAME = "movies-anime-efficient"
TITLE_DA_CF_NAME = "Anime Dual Audio"
METADATA_DA_CF_NAME = "Anime - Dual Audio (Metadata)"
GUARD_CF_NAME = "Anime Dual Audio - Metadata/Title Duplicate Guard"
EXPECTED_DA_NET = 100000


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    api_key = root.findtext("ApiKey")
    if not api_key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return api_key.strip()


def api_get(
    base_url: str,
    api_key: str,
    path: str,
    params: dict[str, Any] | None = None,
    timeout: int = 120,
) -> Any:
    query = "?" + urllib.parse.urlencode(params, doseq=True) if params else ""
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}{query}",
        headers={"X-Api-Key": api_key},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {path}{query} failed: {exc.code} {body}") from exc


def paged_get(
    base_url: str,
    api_key: str,
    path: str,
    params: dict[str, Any],
    page_size: int,
) -> tuple[list[dict[str, Any]], int | None]:
    records: list[dict[str, Any]] = []
    total: int | None = None
    page = 1
    while True:
        page_params = dict(params)
        page_params.update({"page": page, "pageSize": page_size})
        result = api_get(base_url, api_key, path, page_params)
        if isinstance(result, list):
            page_records = result
            total = len(result)
        else:
            page_records = result.get("records") or []
            total_value = result.get("totalRecords")
            total = int(total_value) if isinstance(total_value, int) else total
        records.extend(page_records)
        if not page_records:
            return records, total
        if total is not None and len(records) >= total:
            return records, total
        if len(page_records) < page_size:
            return records, total
        page += 1


def cf_names(values: list[dict[str, Any]] | None) -> set[str]:
    return {str(value.get("name") or value.get("id")) for value in values or []}


def hydrate_movie_file(
    base_url: str,
    api_key: str,
    movie_file: dict[str, Any],
) -> dict[str, Any]:
    movie_file_id = movie_file.get("id")
    if not isinstance(movie_file_id, int):
        return movie_file
    try:
        return api_get(base_url, api_key, f"/api/v3/moviefile/{movie_file_id}")
    except RuntimeError:
        return movie_file


def profile_scores(
    profile: dict[str, Any],
    custom_formats_by_id: dict[int, dict[str, Any]],
) -> dict[str, int]:
    scores: dict[str, int] = {}
    for item in profile.get("formatItems") or []:
        value = item.get("format")
        if isinstance(value, dict):
            value = value.get("id")
        if value is None:
            value = item.get("customFormatId")
        try:
            cf_id = int(value)
        except (TypeError, ValueError):
            continue
        name = str(custom_formats_by_id.get(cf_id, {}).get("name") or item.get("name") or cf_id)
        scores[name] = int(item.get("score") or 0)
    return scores


def find_one(items: list[dict[str, Any]], name: str, kind: str) -> dict[str, Any]:
    matches = [item for item in items if item.get("name") == name]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {kind} named {name!r}, found {len(matches)}")
    return matches[0]


def title_for_item(item: dict[str, Any]) -> str:
    movie = item.get("movie") if isinstance(item.get("movie"), dict) else item
    title = movie.get("title") if isinstance(movie, dict) else None
    year = movie.get("year") if isinstance(movie, dict) else None
    if title and year:
        return f"{title} ({year})"
    if title:
        return str(title)
    return str(item.get("title") or item.get("downloadTitle") or item.get("id"))


def classify(
    *,
    source: str,
    title: str,
    score: int | None,
    custom_formats: set[str],
    scores: dict[str, int],
) -> dict[str, Any]:
    title_da = TITLE_DA_CF_NAME in custom_formats
    metadata_da = METADATA_DA_CF_NAME in custom_formats
    guard = GUARD_CF_NAME in custom_formats
    da_net = sum(
        scores.get(name, 0)
        for name in (TITLE_DA_CF_NAME, METADATA_DA_CF_NAME, GUARD_CF_NAME)
        if name in custom_formats
    )
    status = "ok"
    if title_da and metadata_da and not guard:
        status = "missing_guard"
    elif title_da and metadata_da and guard and da_net != EXPECTED_DA_NET:
        status = "bad_net"
    elif (title_da or metadata_da) and da_net > EXPECTED_DA_NET:
        status = "over_scored"
    elif guard and not (title_da and metadata_da):
        status = "guard_without_intersection"
    if title_da and metadata_da and guard:
        match_bucket = "title_and_metadata_guarded"
    elif title_da and metadata_da:
        match_bucket = "title_and_metadata_missing_guard"
    elif title_da:
        match_bucket = "title_only"
    elif metadata_da:
        match_bucket = "metadata_only"
    elif guard:
        match_bucket = "guard_only"
    else:
        match_bucket = "no_da"
    return {
        "source": source,
        "title": title,
        "score": score,
        "status": status,
        "title_da": title_da,
        "metadata_da": metadata_da,
        "guard": guard,
        "da_net": da_net,
        "match_bucket": match_bucket,
        "custom_formats": sorted(custom_formats),
    }


def audit(args: argparse.Namespace) -> dict[str, Any]:
    api_key = read_api_key(args.config)
    custom_formats = api_get(args.base_url, api_key, "/api/v3/customformat")
    profiles = api_get(args.base_url, api_key, "/api/v3/qualityprofile")
    movies = api_get(args.base_url, api_key, "/api/v3/movie")
    queue, queue_total = paged_get(
        args.base_url,
        api_key,
        "/api/v3/queue",
        {"includeMovie": "true", "sortKey": "timeleft", "sortDirection": "ascending"},
        args.page_size,
    )

    profiles_by_id = {
        int(profile["id"]): str(profile.get("name") or profile["id"])
        for profile in profiles
        if isinstance(profile.get("id"), int)
    }
    custom_formats_by_id = {
        int(custom_format["id"]): custom_format
        for custom_format in custom_formats
        if isinstance(custom_format.get("id"), int)
    }
    target_profile = find_one(profiles, PROFILE_NAME, "quality profile")
    scores = profile_scores(target_profile, custom_formats_by_id)

    movie_rows: list[dict[str, Any]] = []
    for movie in movies:
        if profiles_by_id.get(movie.get("qualityProfileId")) != PROFILE_NAME:
            continue
        movie_file = movie.get("movieFile")
        if not isinstance(movie_file, dict):
            movie_rows.append(
                {
                    "source": "movie_file",
                    "title": title_for_item(movie),
                    "score": None,
                    "status": "missing_file",
                    "title_da": False,
                    "metadata_da": False,
                    "guard": False,
                    "da_net": 0,
                    "match_bucket": "missing_file",
                    "custom_formats": [],
                }
            )
            continue
        hydrated_file = hydrate_movie_file(args.base_url, api_key, movie_file)
        movie_rows.append(
            classify(
                source="movie_file",
                title=title_for_item(movie),
                score=hydrated_file.get("customFormatScore"),
                custom_formats=cf_names(hydrated_file.get("customFormats")),
                scores=scores,
            )
        )

    target_movie_ids = {
        movie.get("id")
        for movie in movies
        if profiles_by_id.get(movie.get("qualityProfileId")) == PROFILE_NAME
    }
    queue_rows: list[dict[str, Any]] = []
    for record in queue:
        movie = record.get("movie") if isinstance(record.get("movie"), dict) else {}
        if movie.get("id") not in target_movie_ids:
            continue
        queue_rows.append(
            classify(
                source="queue",
                title=str(record.get("title") or record.get("downloadTitle") or title_for_item(movie)),
                score=record.get("customFormatScore")
                if record.get("customFormatScore") is not None
                else (record.get("trackedDownload") or {}).get("customFormatScore"),
                custom_formats=cf_names(record.get("customFormats")),
                scores=scores,
            )
        )

    all_rows = movie_rows + queue_rows
    by_status: dict[str, int] = {}
    by_match_bucket: dict[str, int] = {}
    for row in all_rows:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
        by_match_bucket[row["match_bucket"]] = by_match_bucket.get(row["match_bucket"], 0) + 1
    failures = [row for row in all_rows if row["status"] not in {"ok", "missing_file"}]
    return {
        "profile": PROFILE_NAME,
        "movie_count": len(movie_rows),
        "queue_count": len(queue_rows),
        "queue_total": queue_total,
        "score_model": {
            "title_only": scores.get(TITLE_DA_CF_NAME, 0),
            "metadata_only": scores.get(METADATA_DA_CF_NAME, 0),
            "title_and_metadata": (
                scores.get(TITLE_DA_CF_NAME, 0)
                + scores.get(METADATA_DA_CF_NAME, 0)
                + scores.get(GUARD_CF_NAME, 0)
            ),
        },
        "status_counts": by_status,
        "match_counts": by_match_bucket,
        "failures": failures,
        "movie_rows": movie_rows,
        "queue_rows": queue_rows,
    }


def print_report(report: dict[str, Any], *, verbose: bool) -> None:
    print(
        f"profile={report['profile']} movies={report['movie_count']} "
        f"queue_rows={report['queue_count']} queue_total={report['queue_total']}"
    )
    model = report["score_model"]
    print(
        "score_model: title_only={title_only} metadata_only={metadata_only} "
        "title_and_metadata={title_and_metadata}".format(**model)
    )
    print("status_counts:")
    for status, count in sorted(report["status_counts"].items()):
        print(f"  {status}: {count}")
    print("match_counts:")
    for bucket, count in sorted(report["match_counts"].items()):
        print(f"  {bucket}: {count}")
    if report["failures"]:
        print("failures:")
        for row in report["failures"]:
            print(
                "  [{source}] {title}: status={status} score={score} "
                "title_da={title_da} metadata_da={metadata_da} guard={guard} da_net={da_net}".format(**row)
            )
    else:
        print("failures: none")

    if verbose:
        print("rows:")
        for row in report["movie_rows"] + report["queue_rows"]:
            print(
                "  [{source}] {title}: status={status} score={score} "
                "title_da={title_da} metadata_da={metadata_da} guard={guard} da_net={da_net}".format(**row)
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=RADARR_URL)
    parser.add_argument("--config", default=RADARR_CONFIG)
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--no-fail", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit(args)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_report(report, verbose=args.verbose)
    if report["failures"] and not args.no_fail:
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
