#!/usr/bin/env python3
"""Classify why Radarr queue items were grabbed and whether they should import.

This is intentionally read-only. It compares queued Radarr downloads against
the current movie file when one exists, then labels rows as valid upgrades,
current-file-better, payload score loss, stalled/warning, failed, or needing
manual review.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any


DA_RE = re.compile(
    r"(?i)\b(?:dual[ ._-]?audio|multi[ ._-]?audio|"
    r"dual\b(?![ ._-]sub(?:s|titles?)?\b)|"
    r"JA\+EN|JP\+EN|ZH\+EN|KO\+EN)\b"
)
X265_RE = re.compile(r"(?i)(?:\b[xh][\s._-]?265\b|\bhevc\b)")
TIER_CF_RE = re.compile(r"(?i)\btier\b")
LOCAL_QUALITY_RANK_RE = re.compile(r"(?i)^Local Quality Rank - ")
LOCAL_SOURCE_RANK_RE = re.compile(r"(?i)^Local .*Source Rank - ")
PLATFORM_RE = re.compile(
    r"(?i)(?:^|[\s._\-\[\(])"
    r"(?:CR|Crunchyroll|NF|Netflix|DSNP|Disney\+?|DisneyPlus|AMZN|Amazon|"
    r"FUNi|Funimation|VRV|ADN|ABEMA|ATVP|AppleTV\+?|HMAX|HBO.?Max|HULU|"
    r"PCOK|Peacock|PMTP|Paramount\+?|SHO|Showtime|STAN)"
    r"(?:$|[\s._\-\]\)])"
)
LEADING_GROUP_RE = re.compile(r"^\[([A-Za-z0-9][A-Za-z0-9._-]{1,31})\]")
TRAILING_GROUP_RE = re.compile(r"-([A-Za-z0-9][A-Za-z0-9._]{1,31})$")
NON_RELEASE_GROUPS = {
    "1080p",
    "10bit",
    "2160p",
    "480p",
    "576p",
    "720p",
    "8bit",
    "aac",
    "audio",
    "av1",
    "batch",
    "bd",
    "bdrip",
    "bit",
    "bluray",
    "dual",
    "dual-audio",
    "dvd",
    "eac3",
    "eng-sub",
    "english",
    "flac",
    "h264",
    "h265",
    "hdtv",
    "hevc",
    "japanese",
    "multi-audio",
    "proper",
    "repack",
    "season",
    "sub",
    "v2",
    "v3",
    "web",
    "web-dl",
    "webdl",
    "webrip",
    "x264",
    "x265",
}
BROAD_OR_LOCAL_CF_NAMES = {
    "br-disk",
    "no-rlsgroup",
    "x265 (hd)",
}
SCORE_MESSAGE_RE = re.compile(
    r"(?is)new custom formats .*?score of\s+(-?\d+).*?"
    r"existing custom formats .*?score of\s+(-?\d+)"
)
COMPACT_SCORE_MESSAGE_RE = re.compile(
    r"(?is)\bNew:\s+.*?\((-?\d+)\)\s+do not improve on\s+"
    r"Existing:\s+.*?\((-?\d+)\)"
)


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
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}{query}",
        headers={"X-Api-Key": api_key},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {path} failed: {exc.code} {body}") from exc


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
            messages.append(f"{title}: {message}" if title else str(message))
    error = record.get("errorMessage")
    if error:
        messages.append(str(error))
    return messages


def score_pair_from_messages(messages: list[str]) -> tuple[int | None, int | None]:
    for message in messages:
        match = SCORE_MESSAGE_RE.search(message) or COMPACT_SCORE_MESSAGE_RE.search(message)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None, None


def release_group_candidate(value: str | None) -> str | None:
    if not value:
        return None
    group = value.strip().strip("[]()")
    if not group or len(group) > 32 or " " in group:
        return None
    if group.casefold() in NON_RELEASE_GROUPS or group.isdigit():
        return None
    return group


def release_group_from_title(title: str) -> str | None:
    for raw_title in title.split(" || "):
        stripped = raw_title.strip()
        trailing = TRAILING_GROUP_RE.search(stripped)
        if trailing and (group := release_group_candidate(trailing.group(1))):
            return group
        leading = LEADING_GROUP_RE.search(stripped)
        if leading and (group := release_group_candidate(leading.group(1))):
            return group
    return None


def has_x265_signal(title: str, custom_formats: list[str]) -> bool:
    haystack = " ".join([title, *custom_formats])
    return X265_RE.search(haystack) is not None or any(
        "x265" in cf.casefold() or "hevc" in cf.casefold() for cf in custom_formats
    )


def has_tier_cf(custom_formats: list[str]) -> bool:
    return any(TIER_CF_RE.search(custom_format) for custom_format in custom_formats)


def is_broad_or_local_cf(custom_format: str) -> bool:
    lowered = custom_format.casefold()
    return (
        lowered in BROAD_OR_LOCAL_CF_NAMES
        or LOCAL_QUALITY_RANK_RE.search(custom_format) is not None
        or LOCAL_SOURCE_RANK_RE.search(custom_format) is not None
    )


def risk_flags(title: str, custom_formats: list[str]) -> list[str]:
    flags: list[str] = []
    x265 = has_x265_signal(title, custom_formats)
    tier = has_tier_cf(custom_formats)
    group = release_group_from_title(title)
    has_quality_rank = any(LOCAL_QUALITY_RANK_RE.search(custom_format) for custom_format in custom_formats)

    if x265 and not tier:
        flags.append("tierless_x265")
    if group and not tier:
        flags.append("release_group_unranked")
    if x265 and has_quality_rank and not tier and all(is_broad_or_local_cf(item) for item in custom_formats):
        flags.append("bare_quality_x265")
    return flags


def release_signals(title: str, custom_formats: list[str]) -> list[str]:
    haystack = " ".join([title, *custom_formats])
    signals: list[str] = []
    group = release_group_from_title(title)
    tier = has_tier_cf(custom_formats)
    if DA_RE.search(haystack) or any("dual audio" in cf.casefold() for cf in custom_formats):
        signals.append("dual_audio")
    if has_x265_signal(title, custom_formats):
        signals.append("x265_hevc")
    if PLATFORM_RE.search(haystack):
        signals.append("platform")
    if group:
        signals.append("release_group_in_title")
    if tier:
        signals.append("release_tier_cf")
    if group or tier:
        signals.append("release_group_or_tier")
    return signals


def movie_file_from_record(base_url: str, api_key: str, record: dict[str, Any]) -> dict[str, Any] | None:
    movie = record.get("movie") if isinstance(record.get("movie"), dict) else {}
    movie_file = movie.get("movieFile") if isinstance(movie.get("movieFile"), dict) else None
    if movie_file:
        return movie_file
    movie_id = record.get("movieId") or movie.get("id")
    if not isinstance(movie_id, int):
        return None
    fetched = api_get(base_url, api_key, f"/api/v3/movie/{movie_id}")
    return fetched.get("movieFile") if isinstance(fetched.get("movieFile"), dict) else None


def summarize_queue_record(base_url: str, api_key: str, record: dict[str, Any]) -> dict[str, Any]:
    movie_file = movie_file_from_record(base_url, api_key, record)
    messages = status_messages(record)
    message_queued_score, message_current_score = score_pair_from_messages(messages)
    queued_score = record.get("customFormatScore")
    if queued_score is None:
        queued_score = record.get("trackedDownload", {}).get("customFormatScore")
    if message_queued_score is not None:
        queued_score = message_queued_score
    current_score = movie_file.get("customFormatScore") if isinstance(movie_file, dict) else None
    if message_current_score is not None:
        current_score = message_current_score
    queued_title = str(record.get("title") or record.get("downloadTitle") or "")
    queued_cfs = cf_names(record.get("customFormats"))
    movie = record.get("movie") if isinstance(record.get("movie"), dict) else {}

    return {
        "queue_id": record.get("id"),
        "download_id": record.get("downloadId"),
        "title": queued_title,
        "movie": movie.get("title") or record.get("movieTitle"),
        "queued_quality": quality_label(record.get("quality")),
        "queued_score": queued_score,
        "queued_cfs": queued_cfs,
        "current_path": movie_file.get("path") if isinstance(movie_file, dict) else None,
        "current_quality": quality_label(movie_file.get("quality")) if isinstance(movie_file, dict) else None,
        "current_score": current_score,
        "current_cfs": cf_names(movie_file.get("customFormats")) if isinstance(movie_file, dict) else [],
        "download_client": record.get("downloadClient"),
        "status": record.get("status"),
        "tracked_state": record.get("trackedDownloadState"),
        "messages": messages,
        "signals": release_signals(queued_title, queued_cfs),
        "risk_flags": risk_flags(queued_title, queued_cfs),
        "inferred_release_group": release_group_from_title(queued_title),
    }


def compare_scores(item: dict[str, Any]) -> str:
    queued_score = item.get("queued_score")
    current_score = item.get("current_score")
    if isinstance(queued_score, int) and isinstance(current_score, int):
        if current_score > queued_score:
            return "current_better"
        if queued_score > current_score:
            return "queued_better"
        return "same_score"
    return "unknown_score"


def classify_group(rows: list[dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    score_states = [compare_scores(row) for row in rows]
    messages = "\n".join(message for row in rows for message in row["messages"])
    message_lc = messages.casefold()
    has_signals = any(row["signals"] for row in rows)

    if "current_better" in score_states:
        labels.append("current_file_score_higher")
    if (
        has_signals
        and "not a custom format upgrade" in message_lc
        and ("queued_better" in score_states or "current_better" in score_states)
    ):
        labels.append("payload_score_loss")
    if (
        "unable to parse" in message_lc
        or "does not belong to" in message_lc
        or "not a movie" in message_lc
        or "automatic import is not possible" in message_lc
    ):
        labels.append("mapping_or_import_block")
    if "aborted, cannot be completed" in message_lc or "failedpending" in "\n".join(
        str(row.get("tracked_state") or "").casefold() for row in rows
    ):
        labels.append("download_failed")
    if (
        "stalled" in message_lc
        or "no connections" in message_lc
        or "no seeders" in message_lc
        or any(str(row.get("status") or "").casefold() == "warning" for row in rows)
    ):
        labels.append("download_stalled_or_warning")
    if "queued_better" in score_states and not messages:
        labels.append("active_upgrade")
    if not labels:
        labels.append("needs_manual_review")
    return labels


def group_queue(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = str(row.get("download_id") or row.get("title") or f"queue:{row.get('queue_id')}")
        groups.setdefault(key, []).append(row)

    summaries: list[dict[str, Any]] = []
    for key, group_rows in groups.items():
        states = [compare_scores(row) for row in group_rows]
        messages = [message for row in group_rows for message in row["messages"]]
        summaries.append(
            {
                "key": key,
                "title": group_rows[0].get("title"),
                "download_client": group_rows[0].get("download_client"),
                "rows": len(group_rows),
                "movies": sorted({str(row.get("movie") or "unknown") for row in group_rows}),
                "classifications": classify_group(group_rows),
                "score_states": dict(collections.Counter(states)),
                "queued_scores": sorted(
                    {str(row["queued_score"]) for row in group_rows if row.get("queued_score") is not None}
                ),
                "current_scores": sorted(
                    {str(row["current_score"]) for row in group_rows if row.get("current_score") is not None}
                ),
                "signals": sorted({signal for row in group_rows for signal in row["signals"]}),
                "risk_flags": sorted({flag for row in group_rows for flag in row["risk_flags"]}),
                "inferred_release_groups": sorted(
                    {
                        str(row["inferred_release_group"])
                        for row in group_rows
                        if row.get("inferred_release_group")
                    }
                ),
                "sample_message": messages[0] if messages else "",
                "sample_rows": group_rows[:5],
            }
        )
    return sorted(
        summaries,
        key=lambda item: (
            "current_file_score_higher" in item["classifications"],
            "payload_score_loss" in item["classifications"],
            "bare_quality_x265" in item["risk_flags"],
            "tierless_x265" in item["risk_flags"],
            item["rows"],
        ),
        reverse=True,
    )


def print_text(report: dict[str, Any]) -> None:
    label_counts = collections.Counter(
        label for group in report["groups"] for label in group["classifications"]
    )
    risk_counts = collections.Counter(flag for group in report["groups"] for flag in group["risk_flags"])
    print(f"queue records: {report['queue_count']} of {report['queue_total']}")
    print(f"download groups: {len(report['groups'])}")
    print(f"labels: {dict(label_counts)}")
    print(f"risks: {dict(risk_counts)}")
    print()
    for group in report["groups"]:
        print(f"- {group['title']}")
        print(
            "  rows={rows} labels={labels} states={states} signals={signals} risks={risks}".format(
                rows=group["rows"],
                labels=", ".join(group["classifications"]),
                states=group["score_states"],
                signals=", ".join(group["signals"]) or "(none)",
                risks=", ".join(group["risk_flags"]) or "(none)",
            )
        )
        print(f"  key={group['key']}")
        print(f"  queued_scores={group['queued_scores']} current_scores={group['current_scores']}")
        print(f"  movies={', '.join(group['movies'])} client={group['download_client']}")
        if group["inferred_release_groups"]:
            print(f"  inferred_groups={', '.join(group['inferred_release_groups'])}")
        if group["sample_message"]:
            print(f"  sample_message={group['sample_message']}")
        if report["details"]:
            for row in group["sample_rows"]:
                print(
                    f"  row queue_id={row['queue_id']} {row['movie']} "
                    f"queued={row['queued_score']} current={row['current_score']}"
                )
                print(f"    queued_cfs={', '.join(row['queued_cfs']) or '(none)'}")
                print(f"    current_cfs={', '.join(row['current_cfs']) or '(none)'}")
        print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--details", action="store_true", help="print sample rows per group")
    parser.add_argument("--base-url", default="http://127.0.0.1:7878")
    parser.add_argument("--config", default="/opt/media-stack/radarr/config.xml")
    parser.add_argument("--page-size", type=int, default=1000)
    return parser.parse_args()


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
            "includeMovie": "true",
            "sortKey": "timeleft",
            "sortDirection": "ascending",
        },
    )
    records = queue_page.get("records", queue_page if isinstance(queue_page, list) else [])
    rows = [summarize_queue_record(args.base_url, api_key, record) for record in records]
    report = {
        "queue_total": queue_page.get("totalRecords") if isinstance(queue_page, dict) else len(records),
        "queue_count": len(rows),
        "details": args.details,
        "groups": group_queue(rows),
    }
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
