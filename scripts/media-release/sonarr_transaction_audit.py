#!/usr/bin/env python3
"""Summarize Sonarr grab/import history and current queue state.

Run this on docker-vm. It reads the Sonarr transaction monitor JSONL log and,
unless disabled, the live Sonarr API. It is intentionally read-only.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = Path("/opt/media-stack/sonarr/config.xml")
DEFAULT_LOG = Path("/var/log/sonarr-transaction-monitor/events.jsonl")
DEFAULT_STAMPER_LOGS = (
    Path("/opt/media-stack/qbittorrent/scripts/release-stamper-events.jsonl"),
    Path("/opt/media-stack/sabnzbd/scripts/release-stamper-events.jsonl"),
)

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


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def read_api_key(path: Path) -> str:
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
    return [str(value.get("name") or value.get("id")) for value in values or []]


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


def monitor_events(path: Path, since: dt.datetime) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"warning: skipped malformed log line {line_number}: {exc}", file=sys.stderr)
                continue
            observed_at = parse_time(event.get("observedAt"))
            if observed_at and observed_at >= since:
                events.append(event)
    return events


def format_bytes(value: int | float | None) -> str:
    size = float(value or 0)
    sign = "-" if size < 0 else ""
    size = abs(size)
    for suffix in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if size < 1024 or suffix == "PiB":
            if suffix == "B":
                return f"{sign}{int(size)} {suffix}"
            return f"{sign}{size:.2f} {suffix}"
        size /= 1024
    return f"{sign}{size:.2f} PiB"


def stamper_events(paths: list[Path], since: dt.datetime) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    print(f"warning: skipped malformed stamper log {path}:{line_number}: {exc}", file=sys.stderr)
                    continue
                observed_at = parse_time(event.get("observedAt"))
                if observed_at and observed_at >= since:
                    event["_log_path"] = str(path)
                    events.append(event)
    events.sort(key=lambda item: parse_time(item.get("observedAt")) or dt.datetime.min.replace(tzinfo=dt.UTC))
    return events


def summarize_stamper_events(events: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    by_result = collections.Counter(
        f"{event.get('client') or 'unknown'}:{event.get('result') or 'unknown'}"
        for event in events
    )
    zero_rename_completed = [
        event
        for event in events
        if event.get("result") == "completed"
        and int(event.get("changes") or 0) == 0
        and int(event.get("videos_scanned") or 0) > 0
    ]
    errors = [event for event in events if event.get("result") == "error"]
    recent = sorted(
        events,
        key=lambda item: parse_time(item.get("observedAt")) or dt.datetime.min.replace(tzinfo=dt.UTC),
        reverse=True,
    )[:limit]
    return {
        "count": len(events),
        "by_result": dict(sorted(by_result.items())),
        "zero_rename_completed": len(zero_rename_completed),
        "errors": len(errors),
        "recent": [
            {
                "observedAt": event.get("observedAt"),
                "client": event.get("client"),
                "result": event.get("result"),
                "reason": event.get("reason"),
                "changes": event.get("changes"),
                "videos_scanned": event.get("videos_scanned"),
                "skipped_no_stamp": event.get("skipped_no_stamp"),
                "skip_reasons": event.get("skip_reasons"),
                "file_list_source": event.get("file_list_source"),
                "download_name": event.get("download_name"),
            }
            for event in recent
        ],
    }


def summarize_history(events: list[dict[str, Any]], limit: int, include_bootstrap: bool) -> dict[str, Any]:
    history_events = [
        event
        for event in events
        if event.get("kind") == "history" and isinstance(event.get("record"), dict)
    ]
    bootstrap_count = sum(1 for event in history_events if event.get("bootstrap"))
    history = [
        event["record"]
        for event in history_events
        if include_bootstrap or not event.get("bootstrap")
    ]
    counts = collections.Counter(str(record.get("eventType") or "unknown") for record in history)
    groups: dict[str, dict[str, Any]] = {}
    for record in history:
        key = str(record.get("downloadId") or record.get("sourceTitle") or f"history:{record.get('id')}")
        group = groups.setdefault(
            key,
            {
                "key": key,
                "first": record.get("date"),
                "last": record.get("date"),
                "title": record.get("sourceTitle") or key,
                "series": set(),
                "events": collections.Counter(),
                "scores": set(),
                "qualities": set(),
                "formats": set(),
                "risk_flags": set(),
                "inferred_groups": set(),
                "rows": 0,
            },
        )
        group["rows"] += 1
        group["last"] = record.get("date") or group["last"]
        if record.get("seriesTitle"):
            group["series"].add(str(record["seriesTitle"]))
        group["events"][str(record.get("eventType") or "unknown")] += 1
        if record.get("customFormatScore") is not None:
            group["scores"].add(str(record["customFormatScore"]))
        if record.get("quality"):
            group["qualities"].add(str(record["quality"]))
        for custom_format in record.get("customFormats") or []:
            group["formats"].add(str(custom_format))
        record_flags = record.get("riskFlags")
        if isinstance(record_flags, list):
            group["risk_flags"].update(str(flag) for flag in record_flags)
        else:
            group["risk_flags"].update(
                risk_flags(
                    str(record.get("sourceTitle") or group["title"]),
                    [str(item) for item in record.get("customFormats") or []],
                )
            )
        inferred_group = record.get("inferredReleaseGroup") or release_group_from_title(str(record.get("sourceTitle") or ""))
        if inferred_group:
            group["inferred_groups"].add(str(inferred_group))

    recent_groups = sorted(
        groups.values(),
        key=lambda item: parse_time(item.get("last")) or dt.datetime.min.replace(tzinfo=dt.UTC),
        reverse=True,
    )[:limit]
    for group in recent_groups:
        group["series"] = sorted(group["series"])
        group["events"] = dict(group["events"])
        group["scores"] = sorted(group["scores"])
        group["qualities"] = sorted(group["qualities"])
        group["signals"] = release_signals(str(group["title"]), sorted(group["formats"]))
        group["formats"] = sorted(group["formats"])
        group["risk_flags"] = sorted(group["risk_flags"])
        group["inferred_groups"] = sorted(group["inferred_groups"])
    return {
        "count": len(history),
        "bootstrap_skipped": 0 if include_bootstrap else bootstrap_count,
        "event_counts": dict(counts),
        "recent_groups": recent_groups,
    }


def summarize_snapshots(events: list[dict[str, Any]]) -> dict[str, Any]:
    snapshots = [event for event in events if event.get("kind") == "queue_snapshot"]
    if not snapshots:
        return {"count": 0}
    first = snapshots[0]
    last = snapshots[-1]
    max_count = max(int(snapshot.get("count") or 0) for snapshot in snapshots)
    min_count = min(int(snapshot.get("count") or 0) for snapshot in snapshots)
    return {
        "count": len(snapshots),
        "first_observed_at": first.get("observedAt"),
        "first_count": first.get("count"),
        "last_observed_at": last.get("observedAt"),
        "last_count": last.get("count"),
        "min_count": min_count,
        "max_count": max_count,
    }


def storage_app_delta(snapshots: list[dict[str, Any]], app: str) -> dict[str, Any]:
    valid: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for snapshot in snapshots:
        apps = snapshot.get("apps") if isinstance(snapshot.get("apps"), dict) else {}
        app_data = apps.get(app) if isinstance(apps, dict) else None
        if isinstance(app_data, dict) and app_data.get("ok"):
            valid.append((snapshot, app_data))
    if not valid:
        return {"ok": False}
    first_snapshot, first = valid[0]
    last_snapshot, last = valid[-1]
    first_bytes = int(first.get("bytes") or 0)
    last_bytes = int(last.get("bytes") or 0)
    first_files = int(first.get("files") or 0)
    last_files = int(last.get("files") or 0)
    codec_delta: dict[str, dict[str, int]] = {}
    codec_names = set((first.get("byCodec") or {}).keys()) | set((last.get("byCodec") or {}).keys())
    for codec in sorted(codec_names):
        first_codec = (first.get("byCodec") or {}).get(codec) or {}
        last_codec = (last.get("byCodec") or {}).get(codec) or {}
        codec_delta[codec] = {
            "files": int(last_codec.get("files") or 0) - int(first_codec.get("files") or 0),
            "bytes": int(last_codec.get("bytes") or 0) - int(first_codec.get("bytes") or 0),
        }
    return {
        "ok": True,
        "first_observed_at": first_snapshot.get("observedAt"),
        "last_observed_at": last_snapshot.get("observedAt"),
        "first_bytes": first_bytes,
        "last_bytes": last_bytes,
        "delta_bytes": last_bytes - first_bytes,
        "first_files": first_files,
        "last_files": last_files,
        "delta_files": last_files - first_files,
        "by_codec_delta": codec_delta,
    }


def summarize_storage_snapshots(events: list[dict[str, Any]]) -> dict[str, Any]:
    snapshots = [
        event
        for event in events
        if event.get("kind") == "storage_snapshot" and isinstance(event.get("apps"), dict)
    ]
    if not snapshots:
        return {"count": 0, "apps": {}}
    return {
        "count": len(snapshots),
        "first_observed_at": snapshots[0].get("observedAt"),
        "last_observed_at": snapshots[-1].get("observedAt"),
        "apps": {
            "sonarr": storage_app_delta(snapshots, "sonarr"),
            "radarr": storage_app_delta(snapshots, "radarr"),
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

    title = str(record.get("title") or record.get("downloadTitle") or "")
    queued_cfs = cf_names(record.get("customFormats"))
    return {
        "queue_id": record.get("id"),
        "download_id": record.get("downloadId"),
        "title": title,
        "series": (record.get("series") or {}).get("title"),
        "queued_score": record.get("customFormatScore")
        if record.get("customFormatScore") is not None
        else (record.get("trackedDownload") or {}).get("customFormatScore"),
        "queued_quality": quality_label(record.get("quality")),
        "queued_cfs": queued_cfs,
        "current_score": episode_file.get("customFormatScore") if isinstance(episode_file, dict) else None,
        "current_quality": quality_label(episode_file.get("quality")) if isinstance(episode_file, dict) else None,
        "current_cfs": cf_names(episode_file.get("customFormats")) if isinstance(episode_file, dict) else [],
        "download_client": record.get("downloadClient"),
        "status": record.get("status"),
        "tracked_state": record.get("trackedDownloadState"),
        "messages": status_messages(record),
        "signals": release_signals(title, queued_cfs),
        "risk_flags": risk_flags(title, queued_cfs),
        "inferred_release_group": release_group_from_title(title),
    }


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
        or "unexpected considering" in message_lc
        or "unable to parse" in message_lc
        or "does not belong to" in message_lc
        or "automatic import is not possible" in message_lc
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


def summarize_live_queue(base_url: str, api_key: str, limit: int) -> dict[str, Any]:
    queue_page = api_get(
        base_url,
        api_key,
        "/api/v3/queue",
        {
            "page": 1,
            "pageSize": 1000,
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
        summarize_queue_record(base_url, api_key, record, episode_cache, episode_file_cache)
        for record in records
    ]

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
                "series": sorted({str(row.get("series") or "unknown") for row in group_rows}),
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
            }
        )

    classification_counts = collections.Counter(
        label for group in summaries for label in group["classifications"]
    )
    risk_flag_counts = collections.Counter(flag for group in summaries for flag in group["risk_flags"])
    summaries.sort(
        key=lambda item: (
            "current_file_score_higher" in item["classifications"],
            "payload_score_loss" in item["classifications"],
            "pack_collateral_or_mapping" in item["classifications"],
            "bare_quality_x265" in item["risk_flags"],
            "tierless_x265" in item["risk_flags"],
            "download_failed" in item["classifications"],
            "download_stalled_or_warning" in item["classifications"],
            item["rows"],
        ),
        reverse=True,
    )
    return {
        "queue_total": queue_page.get("totalRecords") if isinstance(queue_page, dict) else len(records),
        "queue_count": len(rows),
        "group_count": len(summaries),
        "classification_counts": dict(classification_counts),
        "risk_flag_counts": dict(risk_flag_counts),
        "groups": summaries[:limit],
    }


def print_text(report: dict[str, Any]) -> None:
    print(f"window: {report['since']} -> {report['checked_at']}")
    print(f"log: {report['log_path']}")
    print()

    history = report["history"]
    bootstrap_note = (
        f" bootstrap_skipped={history['bootstrap_skipped']}"
        if history.get("bootstrap_skipped")
        else ""
    )
    print(f"history events: {history['count']}{bootstrap_note}")
    if history["event_counts"]:
        print("history by type: " + ", ".join(f"{k}={v}" for k, v in sorted(history["event_counts"].items())))
    snapshots = report["snapshots"]
    if snapshots.get("count"):
        print(
            "queue snapshots: {count} first={first_count}@{first_observed_at} "
            "last={last_count}@{last_observed_at} min={min_count} max={max_count}".format(**snapshots)
        )
    else:
        print("queue snapshots: 0")

    storage = report["storage"]
    if storage.get("count"):
        print()
        print(
            "storage snapshots: {count} first={first_observed_at} last={last_observed_at}".format(
                **storage
            )
        )
        for app, app_data in storage["apps"].items():
            if not app_data.get("ok"):
                print(f"  - {app}: no valid snapshots")
                continue
            print(
                "  - {app}: {first_bytes} -> {last_bytes} delta={delta_bytes} "
                "files={first_files}->{last_files} delta_files={delta_files}".format(
                    app=app,
                    first_bytes=format_bytes(app_data["first_bytes"]),
                    last_bytes=format_bytes(app_data["last_bytes"]),
                    delta_bytes=format_bytes(app_data["delta_bytes"]),
                    first_files=app_data["first_files"],
                    last_files=app_data["last_files"],
                    delta_files=app_data["delta_files"],
                )
            )
            codec_bits = [
                f"{codec}:{format_bytes(delta['bytes'])}/{delta['files']} files"
                for codec, delta in sorted(app_data["by_codec_delta"].items())
                if delta["bytes"] or delta["files"]
            ]
            if codec_bits:
                print("    codec_delta=" + ", ".join(codec_bits))

    stamper = report["stamper"]
    print()
    print(
        "stamper events: count={count} zero_rename_completed={zero_rename_completed} "
        "errors={errors} by_result={by_result}".format(**stamper)
    )
    for event in stamper["recent"]:
        print(
            "  - {observedAt} {client} {result} changes={changes} videos={videos_scanned} "
            "skipped={skipped_no_stamp} source={file_list_source} reason={reason} "
            "skip_reasons={skip_reasons} {download_name}".format(**event)
        )

    print()
    print("recent grabbed/import groups:")
    if not history["recent_groups"]:
        print("  (none in window)")
    for group in history["recent_groups"]:
        print(
            "  - {title} rows={rows} events={events} scores={scores} signals={signals} risks={risks}".format(
                title=group["title"],
                rows=group["rows"],
                events=group["events"],
                scores=group["scores"],
                signals=", ".join(group["signals"]) or "(none)",
                risks=", ".join(group["risk_flags"]) or "(none)",
            )
        )
        if group["series"]:
            print(f"    series={', '.join(group['series'])}")
        if group["inferred_groups"]:
            print(f"    inferred_groups={', '.join(group['inferred_groups'])}")

    live_queue = report.get("live_queue")
    if live_queue:
        print()
        print(
            "current queue: records={queue_count}/{queue_total} groups={group_count} labels={labels} risks={risks}".format(
                labels=live_queue["classification_counts"],
                risks=live_queue["risk_flag_counts"],
                **live_queue,
            )
        )
        for group in live_queue["groups"]:
            print(
                "  - {title} rows={rows} labels={labels} states={states} "
                "queued={queued} current={current} signals={signals} risks={risks}".format(
                    title=group["title"],
                    rows=group["rows"],
                    labels=", ".join(group["classifications"]),
                    states=group["score_states"],
                    queued=group["queued_scores"],
                    current=group["current_scores"],
                    signals=", ".join(group["signals"]) or "(none)",
                    risks=", ".join(group["risk_flags"]) or "(none)",
                )
            )
            print(f"    series={', '.join(group['series'])} client={group['download_client']} key={group['key']}")
            if group["inferred_release_groups"]:
                print(f"    inferred_groups={', '.join(group['inferred_release_groups'])}")
            if group["sample_message"]:
                print(f"    sample_message={group['sample_message']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=24.0, help="monitor log window to summarize")
    parser.add_argument("--limit", type=int, default=25, help="maximum groups to print in each section")
    parser.add_argument("--include-bootstrap", action="store_true", help="include monitor bootstrap history records")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--no-live", action="store_true", help="skip current Sonarr API queue inspection")
    parser.add_argument("--base-url", default="http://127.0.0.1:8989")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument(
        "--stamper-log",
        action="append",
        type=Path,
        default=list(DEFAULT_STAMPER_LOGS),
        help="release stamper event JSONL path; may be repeated",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    checked_at = dt.datetime.now(dt.UTC)
    since = checked_at - dt.timedelta(hours=args.hours)
    events = monitor_events(args.log, since)
    stampers = stamper_events(args.stamper_log, since)
    report: dict[str, Any] = {
        "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
        "since": since.isoformat().replace("+00:00", "Z"),
        "log_path": str(args.log),
        "history": summarize_history(events, args.limit, args.include_bootstrap),
        "snapshots": summarize_snapshots(events),
        "storage": summarize_storage_snapshots(events),
        "stamper": summarize_stamper_events(stampers, args.limit),
    }
    if not args.no_live:
        api_key = read_api_key(args.config)
        report["live_queue"] = summarize_live_queue(args.base_url, api_key, args.limit)

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
