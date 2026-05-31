#!/usr/bin/env python3
"""Classify why Sonarr queue items were grabbed and why they may not import.

This is intentionally read-only. It is for deciding whether a queued release is
a valid upgrade, a payload-filename score loss, pack collateral, or a download
client problem before any queue cleanup is considered.
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
    "x265",
}


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
    url = f"{base_url.rstrip('/')}{path}{query}"
    request = urllib.request.Request(url, headers={"X-Api-Key": api_key})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {path} failed: {exc.code} {body}") from exc


def try_api_get(
    base_url: str,
    api_key: str,
    path: str,
    params: dict[str, Any] | None = None,
) -> tuple[Any | None, str | None]:
    try:
        return api_get(base_url, api_key, path, params), None
    except RuntimeError as exc:
        return None, str(exc)


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


def summarize_queue_record(
    base_url: str,
    api_key: str,
    record: dict[str, Any],
    episode_cache: dict[int, dict[str, Any]],
    episode_file_cache: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    episode_id = record.get("episodeId")
    episode = None
    if isinstance(episode_id, int):
        episode = episode_cache.get(episode_id)
        if episode is None:
            episode = api_get(base_url, api_key, f"/api/v3/episode/{episode_id}")
            episode_cache[episode_id] = episode

    file_id = episode.get("episodeFileId") if isinstance(episode, dict) else None
    episode_file = None
    if isinstance(file_id, int) and file_id > 0:
        episode_file = episode_file_cache.get(file_id)
        if episode_file is None:
            episode_file = api_get(base_url, api_key, f"/api/v3/episodefile/{file_id}")
            episode_file_cache[file_id] = episode_file

    queued_score = record.get("customFormatScore")
    if queued_score is None:
        queued_score = record.get("trackedDownload", {}).get("customFormatScore")
    current_score = episode_file.get("customFormatScore") if isinstance(episode_file, dict) else None
    queued_title = str(record.get("title") or record.get("downloadTitle") or "")
    queued_cfs = cf_names(record.get("customFormats"))
    messages = status_messages(record)

    return {
        "queue_id": record.get("id"),
        "download_id": record.get("downloadId"),
        "episode_id": record.get("episodeId"),
        "series_id": (record.get("series") or {}).get("id")
        or (record.get("episode") or episode or {}).get("seriesId"),
        "title": queued_title,
        "series": (record.get("series") or {}).get("title"),
        "season": (record.get("episode") or episode or {}).get("seasonNumber"),
        "episode": (record.get("episode") or episode or {}).get("episodeNumber"),
        "queued_quality": quality_label(record.get("quality")),
        "queued_score": queued_score,
        "queued_cfs": queued_cfs,
        "current_path": episode_file.get("path") if isinstance(episode_file, dict) else None,
        "current_quality": quality_label(episode_file.get("quality")) if isinstance(episode_file, dict) else None,
        "current_score": current_score,
        "current_cfs": cf_names(episode_file.get("customFormats")) if isinstance(episode_file, dict) else [],
        "download_client": record.get("downloadClient"),
        "protocol": record.get("protocol"),
        "status": record.get("status"),
        "tracked_state": record.get("trackedDownloadState"),
        "signals": release_signals(queued_title, queued_cfs),
        "risk_flags": risk_flags(queued_title, queued_cfs),
        "inferred_release_group": release_group_from_title(queued_title),
        "messages": messages,
    }


def row_matches(row: dict[str, Any], filters: list[str]) -> bool:
    if not filters:
        return True
    haystack = "\n".join(
        [
            str(row.get("download_id") or ""),
            str(row.get("queue_id") or ""),
            str(row.get("title") or ""),
            str(row.get("series") or ""),
            " ".join(row.get("queued_cfs") or []),
            "\n".join(row.get("messages") or []),
        ]
    ).casefold()
    return any(term.casefold() in haystack for term in filters)


def summarize_manual_import_candidate(item: dict[str, Any]) -> dict[str, Any]:
    episodes = item.get("episodes") or []
    return {
        "path": item.get("path"),
        "relative_path": item.get("relativePath"),
        "name": item.get("name"),
        "quality": quality_label(item.get("quality")),
        "score": item.get("customFormatScore"),
        "custom_formats": cf_names(item.get("customFormats")),
        "episodes": [
            {
                "id": episode.get("id"),
                "season": episode.get("seasonNumber"),
                "episode": episode.get("episodeNumber"),
                "title": episode.get("title"),
            }
            for episode in episodes
        ],
        "rejections": [
            str(rejection.get("reason") or rejection)
            for rejection in item.get("rejections") or []
        ],
    }


def manual_import_report(
    base_url: str,
    api_key: str,
    group_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    download_id = group_rows[0].get("download_id")
    if not download_id:
        return {"error": "download has no downloadId"}
    series_ids = sorted({row.get("series_id") for row in group_rows if isinstance(row.get("series_id"), int)})
    attempts: list[dict[str, Any]] = []
    attempts.append({"downloadId": download_id, "filterExistingFiles": "false"})
    if len(series_ids) == 1:
        attempts.append(
            {
                "downloadId": download_id,
                "seriesId": series_ids[0],
                "filterExistingFiles": "false",
            }
        )

    errors: list[str] = []
    for params in attempts:
        candidates, error = try_api_get(base_url, api_key, "/api/v3/manualimport", params)
        if error:
            errors.append(error)
            continue
        if isinstance(candidates, list):
            return {
                "params": params,
                "candidate_count": len(candidates),
                "candidates": [summarize_manual_import_candidate(item) for item in candidates[:25]],
            }
    return {"errors": errors}


def history_matches(record: dict[str, Any], group_rows: list[dict[str, Any]]) -> bool:
    download_ids = {
        str(row.get("download_id"))
        for row in group_rows
        if row.get("download_id") is not None
    }
    titles = {
        str(row.get("title") or "").casefold()
        for row in group_rows
        if row.get("title")
    }
    data = record.get("data") or {}
    if str(data.get("downloadId") or data.get("download_id") or "") in download_ids:
        return True
    source_title = str(record.get("sourceTitle") or "").casefold()
    return any(title and (title in source_title or source_title in title) for title in titles)


def summarize_history_record(record: dict[str, Any]) -> dict[str, Any]:
    data = record.get("data") or {}
    return {
        "date": record.get("date"),
        "event_type": record.get("eventType"),
        "series": (record.get("series") or {}).get("title"),
        "season": (record.get("episode") or {}).get("seasonNumber"),
        "episode": (record.get("episode") or {}).get("episodeNumber"),
        "source_title": record.get("sourceTitle"),
        "quality": quality_label(record.get("quality")),
        "score": record.get("customFormatScore"),
        "custom_formats": cf_names(record.get("customFormats")),
        "data": {
            key: data.get(key)
            for key in (
                "downloadId",
                "indexer",
                "releaseGroup",
                "downloadClient",
                "downloadClientName",
                "publishedDate",
                "droppedPath",
                "importedPath",
            )
            if data.get(key) is not None
        },
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
        ("queued_better" in score_states and "current_better" in score_states)
        or "episode wasn't found" in message_lc
        or "was not found in the grabbed release" in message_lc
        or "unable to parse" in message_lc
        or "does not belong to" in message_lc
    ):
        labels.append("pack_collateral_or_mapping")
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


def group_queue(
    rows: list[dict[str, Any]],
    base_url: str | None = None,
    api_key: str | None = None,
    include_manual_import: bool = False,
    history_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = str(row.get("download_id") or row.get("title") or f"queue:{row.get('queue_id')}")
        groups.setdefault(key, []).append(row)

    summaries: list[dict[str, Any]] = []
    for key, group_rows in groups.items():
        states = [compare_scores(row) for row in group_rows]
        messages = [message for row in group_rows for message in row["messages"]]
        summary = {
                "key": key,
                "title": group_rows[0].get("title"),
                "download_client": group_rows[0].get("download_client"),
                "rows": len(group_rows),
                "series": sorted({str(row.get("series") or "unknown") for row in group_rows}),
                "classifications": classify_group(group_rows),
                "score_states": {
                    "queued_better": states.count("queued_better"),
                    "current_better": states.count("current_better"),
                    "same_score": states.count("same_score"),
                    "unknown_score": states.count("unknown_score"),
                },
                "queued_scores": sorted(
                    {
                        str(row["queued_score"])
                        for row in group_rows
                        if row.get("queued_score") is not None
                    }
                ),
                "current_scores": sorted(
                    {
                        str(row["current_score"])
                        for row in group_rows
                        if row.get("current_score") is not None
                    }
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
                "sample_rows": group_rows[:3],
        }
        if include_manual_import and base_url and api_key:
            summary["manual_import"] = manual_import_report(base_url, api_key, group_rows)
        if history_records is not None:
            matches = [record for record in history_records if history_matches(record, group_rows)]
            summary["history"] = [summarize_history_record(record) for record in matches[:20]]
        summaries.append(summary)
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
    print(f"queue records: {report['queue_count']} of {report['queue_total']}")
    print(f"download groups: {len(report['groups'])}")
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
        print(f"  series={', '.join(group['series'])} client={group['download_client']}")
        if group["inferred_release_groups"]:
            print(f"  inferred_groups={', '.join(group['inferred_release_groups'])}")
        if group["sample_message"]:
            print(f"  sample_message={group['sample_message']}")
        if group.get("history"):
            print("  history:")
            for item in group["history"][:5]:
                label = (
                    f"S{int(item['season']):02}E{int(item['episode']):02}"
                    if item["season"] is not None and item["episode"] is not None
                    else "unknown episode"
                )
                print(
                    f"    {item['date']} {item['event_type']} {item['series']} {label} "
                    f"score={item['score']} {item['source_title']}"
                )
                print(f"      CFs={', '.join(item['custom_formats']) or '(none)'}")
        if group.get("manual_import"):
            manual = group["manual_import"]
            print(
                "  manual_import: {count} candidates via {params}".format(
                    count=manual.get("candidate_count", "unknown"),
                    params=manual.get("params") or manual.get("errors") or manual.get("error"),
                )
            )
            for item in manual.get("candidates", [])[:8]:
                episodes = ",".join(
                    "S{season:02}E{episode:02}".format(
                        season=int(episode.get("season") or 0),
                        episode=int(episode.get("episode") or 0),
                    )
                    for episode in item.get("episodes") or []
                )
                print(
                    f"    {episodes or 'unknown'} score={item.get('score')} "
                    f"quality={item.get('quality')} {item.get('path')}"
                )
                print(f"      CFs={', '.join(item.get('custom_formats') or []) or '(none)'}")
                if item.get("rejections"):
                    print(f"      rejections={'; '.join(item['rejections'])}")
        if report["details"]:
            for row in group["sample_rows"]:
                label = (
                    f"S{int(row['season']):02}E{int(row['episode']):02}"
                    if row["season"] is not None and row["episode"] is not None
                    else "unknown episode"
                )
                print(
                    f"  row queue_id={row['queue_id']} {row['series']} {label} "
                    f"episode_id={row['episode_id']} queued={row['queued_score']} current={row['current_score']}"
                )
                print(f"    queued_cfs={', '.join(row['queued_cfs']) or '(none)'}")
                print(f"    current_cfs={', '.join(row['current_cfs']) or '(none)'}")
        print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--details", action="store_true", help="print sample rows per group")
    parser.add_argument("--base-url", default="http://127.0.0.1:8989")
    parser.add_argument("--config", default="/opt/media-stack/sonarr/config.xml")
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument(
        "--filter",
        action="append",
        default=[],
        help="only include queue rows matching this text; may be passed multiple times",
    )
    parser.add_argument(
        "--manual-import",
        action="store_true",
        help="ask Sonarr how filtered completed downloads would score during manual import",
    )
    parser.add_argument(
        "--history-size",
        type=int,
        default=0,
        help="include recent history rows matching filtered download IDs/titles",
    )
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
            "includeSeries": "true",
            "includeEpisode": "true",
            "sortKey": "timeleft",
            "sortDirection": "ascending",
        },
    )
    records = queue_page.get("records", queue_page if isinstance(queue_page, list) else [])
    episode_cache: dict[int, dict[str, Any]] = {}
    episode_file_cache: dict[int, dict[str, Any]] = {}
    rows = [
        summarize_queue_record(args.base_url, api_key, record, episode_cache, episode_file_cache)
        for record in records
    ]
    rows = [row for row in rows if row_matches(row, args.filter)]
    history_records = None
    if args.history_size:
        history = api_get(
            args.base_url,
            api_key,
            "/api/v3/history",
            {
                "page": 1,
                "pageSize": args.history_size,
                "sortKey": "date",
                "sortDirection": "descending",
                "includeSeries": "true",
                "includeEpisode": "true",
            },
        )
        history_records = history.get("records", history if isinstance(history, list) else [])
    report = {
        "queue_total": queue_page.get("totalRecords") if isinstance(queue_page, dict) else len(records),
        "queue_count": len(rows),
        "details": args.details,
        "filters": args.filter,
        "groups": group_queue(
            rows,
            args.base_url,
            api_key,
            args.manual_import,
            history_records,
        ),
    }
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        print_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
