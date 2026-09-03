#!/usr/bin/env python3
"""Read-only qBittorrent torrent-state summary for Arr queue incidents."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from http.cookiejar import CookieJar
from typing import Any


PROBLEM_STATES = {
    "error",
    "missingFiles",
    "stalledDL",
    "queuedDL",
    "metaDL",
    "checkingDL",
    "checkingResumeData",
}
URL_PATTERN = re.compile(r"[a-z][a-z0-9+.-]*://[^\s]+", re.IGNORECASE)
ARR_APPS = {
    "radarr": {
        "base_url": "http://127.0.0.1:7878",
        "config": "/opt/media-stack/radarr/config.xml",
        "queue_params": {"includeMovie": "true"},
        "history_params": {"includeMovie": "true"},
    },
    "sonarr": {
        "base_url": "http://127.0.0.1:8989",
        "config": "/opt/media-stack/sonarr/config.xml",
        "queue_params": {"includeSeries": "true", "includeEpisode": "true"},
        "history_params": {"includeSeries": "true", "includeEpisode": "true"},
    },
}
QBIT_CATEGORY_APPS = {
    "radarr": "radarr",
    "tv-sonarr": "sonarr",
}
EXPLICIT_SEASON_PATTERNS = (
    re.compile(r"\bS(?P<season>\d{1,3})E\d{1,4}\b", re.IGNORECASE),
    re.compile(r"\bSeason[ ._-]*(?P<season>\d{1,3})\b", re.IGNORECASE),
    re.compile(
        r"\b(?P<season>\d{1,3})(?:st|nd|rd|th)[ ._-]+Season\b",
        re.IGNORECASE,
    ),
)


def parse_env(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    with open(path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if (
                len(value) >= 2
                and value[0] == value[-1]
                and value.startswith(("'", '"'))
            ):
                value = value[1:-1]
            values[key.strip()] = value
    return values


def qbit_client(
    env_path: str,
    attempts: int = 3,
    retry_delay: float = 1.0,
) -> tuple[str, urllib.request.OpenerDirector]:
    env = parse_env(env_path)
    missing = [key for key in ("QBIT_API", "QBIT_USER", "QBIT_PASS") if not env.get(key)]
    if missing:
        raise RuntimeError(f"{env_path}: missing required values: {', '.join(missing)}")
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    base_url = env["QBIT_API"].rstrip("/")
    body = urllib.parse.urlencode(
        {"username": env["QBIT_USER"], "password": env["QBIT_PASS"]}
    ).encode()

    for attempt in range(1, attempts + 1):
        jar = CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        request = urllib.request.Request(
            f"{base_url}/auth/login", data=body, method="POST"
        )
        try:
            with opener.open(request, timeout=15) as response:
                status = response.status
                text = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"qBittorrent API login rejected with HTTP {exc.code}"
            ) from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            if attempt == attempts:
                raise RuntimeError(
                    f"qBittorrent API login unavailable after {attempts} attempts"
                ) from exc
            time.sleep(retry_delay)
            continue

        if text.strip() != "Ok." and status != 204:
            raise RuntimeError("qBittorrent API login failed")
        return base_url, opener

    raise AssertionError("unreachable qBittorrent login state")


def api_get(
    base_url: str,
    opener: urllib.request.OpenerDirector,
    path: str,
    params: dict[str, Any] | None = None,
    timeout: float = 30,
) -> Any:
    query = ""
    if params:
        query = "?" + urllib.parse.urlencode(params)
    with opener.open(f"{base_url}{path}{query}", timeout=timeout) as response:
        return json.load(response)


def api_post(
    base_url: str,
    opener: urllib.request.OpenerDirector,
    path: str,
    params: dict[str, Any],
) -> str:
    body = urllib.parse.urlencode(params).encode()
    request = urllib.request.Request(f"{base_url}{path}", data=body, method="POST")
    with opener.open(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def read_arr_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def arr_api_get(
    base_url: str,
    api_key: str,
    path: str,
    params: dict[str, Any] | None = None,
    timeout: float = 30,
) -> Any:
    query = ""
    if params:
        query = "?" + urllib.parse.urlencode(params, doseq=True)
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}{query}",
        headers={"X-Api-Key": api_key, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def paged_arr_queue(
    base_url: str,
    api_key: str,
    queue_params: dict[str, Any],
    page_size: int = 1000,
    max_pages: int = 10,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        payload = arr_api_get(
            base_url,
            api_key,
            "/api/v3/queue",
            {
                **queue_params,
                "page": page,
                "pageSize": page_size,
                "sortKey": "timeleft",
                "sortDirection": "ascending",
            },
        )
        page_records = (
            payload.get("records", []) if isinstance(payload, dict) else payload
        )
        records.extend(page_records)
        total = payload.get("totalRecords") if isinstance(payload, dict) else None
        if isinstance(total, int) and len(records) >= total:
            break
        if len(page_records) < page_size:
            break
    return records


def normalize_download_id(value: Any) -> str:
    return str(value or "").strip().casefold()


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


def arr_label(app: str, record: dict[str, Any]) -> str:
    if app == "radarr":
        movie = record.get("movie") or {}
        return str(movie.get("title") or record.get("title") or "unknown movie")
    series = record.get("series") or {}
    episode = record.get("episode") or {}
    season = episode.get("seasonNumber")
    number = episode.get("episodeNumber")
    suffix = (
        f"S{season:02}E{number:02}"
        if isinstance(season, int) and isinstance(number, int)
        else "unknown episode"
    )
    return f"{series.get('title') or 'unknown series'} {suffix}"


def explicit_title_seasons(title: str) -> set[int]:
    seasons: set[int] = set()
    for pattern in EXPLICIT_SEASON_PATTERNS:
        for match in pattern.finditer(title):
            seasons.add(int(match.group("season")))
    return seasons


def seconds_since(value: Any, now_epoch: int) -> int | None:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    return max(0, now_epoch - timestamp)


def torrent_arr_correlation(
    torrent: dict[str, Any],
    app: str | None,
    rows: list[dict[str, Any]],
    stale_seconds: int,
    now_epoch: int,
) -> dict[str, Any]:
    title = str(torrent.get("name") or "")
    progress = float(torrent.get("progress") or 0)
    state = str(torrent.get("state") or "unknown")
    try:
        seeds = int(torrent.get("num_seeds") or 0)
    except (TypeError, ValueError):
        seeds = 0
    added_age = seconds_since(torrent.get("added_on"), now_epoch)
    idle_age = seconds_since(
        torrent.get("last_activity") or torrent.get("added_on"), now_epoch
    )
    title_seasons = explicit_title_seasons(title) if app == "sonarr" else set()
    arr_seasons = {
        season
        for row in rows
        for season in [(row.get("episode") or {}).get("seasonNumber")]
        if isinstance(season, int)
    }

    findings: list[str] = []
    if app is None:
        findings.append("unknown_arr_category")
    elif not rows:
        findings.append("orphaned_in_download_client")
    if (
        app == "sonarr"
        and len(title_seasons) == 1
        and arr_seasons
        and title_seasons.isdisjoint(arr_seasons)
    ):
        findings.append("explicit_season_mismatch")
    elif app == "sonarr" and len(title_seasons) > 1:
        findings.append("ambiguous_title_season_markers")
    if state == "missingFiles":
        findings.append("missing_payload")
    elif state == "stalledDL" and seeds <= 0:
        if idle_age is not None and idle_age >= stale_seconds:
            findings.append(
                "stale_no_peers" if progress <= 0 else "stale_partial_no_peers"
            )
        else:
            findings.append("no_peers_within_grace")
    elif state == "stalledDL":
        findings.append("stalled_with_reported_seeds")
    elif state in PROBLEM_STATES:
        findings.append(f"qbit_{state}")

    priority = (
        "explicit_season_mismatch",
        "ambiguous_title_season_markers",
        "missing_payload",
        "orphaned_in_download_client",
        "unknown_arr_category",
        "stale_no_peers",
        "stale_partial_no_peers",
        "no_peers_within_grace",
        "stalled_with_reported_seeds",
    )
    classification = next(
        (candidate for candidate in priority if candidate in findings),
        findings[0] if findings else "healthy_or_unclassified",
    )
    messages = sorted(
        {message for row in rows for message in status_messages(row)}
    )
    return {
        "app": app,
        "classification": classification,
        "findings": findings,
        "arr_row_count": len(rows),
        "arr_labels": sorted({arr_label(app, row) for row in rows}) if app else [],
        "arr_seasons": sorted(arr_seasons),
        "title_seasons": sorted(title_seasons),
        "arr_messages": messages,
        "added_age_seconds": added_age,
        "idle_age_seconds": idle_age,
    }


def arr_history_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    event_counts = Counter(str(record.get("eventType") or "unknown") for record in records)
    grabs = [record for record in records if record.get("eventType") == "grabbed"]
    indexers = sorted(
        {
            str((record.get("data") or {}).get("indexer"))
            for record in grabs
            if (record.get("data") or {}).get("indexer")
        }
    )
    grab_dates = sorted(str(record.get("date")) for record in grabs if record.get("date"))
    grab_batches = sorted(set(grab_dates))
    source_titles = sorted(
        {str(record.get("sourceTitle")) for record in grabs if record.get("sourceTitle")}
    )
    return {
        "record_count": len(records),
        "event_counts": dict(event_counts.most_common()),
        "grab_event_count": len(grabs),
        "grab_batch_count": len(grab_batches),
        "first_grab_at": grab_dates[0] if grab_dates else None,
        "last_grab_at": grab_dates[-1] if grab_dates else None,
        "indexers": indexers,
        "source_title_count": len(source_titles),
    }


def correlate_arr(
    torrents: list[dict[str, Any]],
    stale_seconds: int,
    now_epoch: int | None = None,
    include_history: bool = False,
) -> dict[str, dict[str, Any]]:
    queue_by_app: dict[str, dict[str, list[dict[str, Any]]]] = {}
    app_credentials: dict[str, tuple[str, str]] = {}
    required_apps = {
        QBIT_CATEGORY_APPS.get(str(torrent.get("category") or ""))
        for torrent in torrents
    }
    for app in sorted(required_apps - {None}):
        config = ARR_APPS[app]
        api_key = read_arr_api_key(config["config"])
        app_credentials[app] = (config["base_url"], api_key)
        records = paged_arr_queue(
            config["base_url"], api_key, config["queue_params"]
        )
        rows_by_download: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            download_id = normalize_download_id(record.get("downloadId"))
            if download_id:
                rows_by_download[download_id].append(record)
        queue_by_app[app] = rows_by_download

    current_epoch = int(time.time()) if now_epoch is None else now_epoch
    result: dict[str, dict[str, Any]] = {}
    for torrent in torrents:
        torrent_hash = normalize_download_id(torrent.get("hash"))
        app = QBIT_CATEGORY_APPS.get(str(torrent.get("category") or ""))
        rows = queue_by_app.get(app, {}).get(torrent_hash, []) if app else []
        result[torrent_hash] = torrent_arr_correlation(
            torrent, app, rows, stale_seconds, current_epoch
        )
        if include_history and app:
            base_url, api_key = app_credentials[app]
            config = ARR_APPS[app]
            try:
                payload = arr_api_get(
                    base_url,
                    api_key,
                    "/api/v3/history",
                    {
                        "downloadId": torrent_hash.upper(),
                        **config["history_params"],
                    },
                )
                records = (
                    payload.get("records", [])
                    if isinstance(payload, dict)
                    else payload
                )
                result[torrent_hash]["history"] = arr_history_summary(records)
            except (TimeoutError, urllib.error.HTTPError, urllib.error.URLError) as exc:
                result[torrent_hash]["history_error"] = type(exc).__name__
    return result


def progress_percent(torrent: dict[str, Any]) -> str:
    try:
        return f"{float(torrent.get('progress') or 0) * 100:.1f}%"
    except (TypeError, ValueError):
        return "unknown"


def epoch_timestamp(value: Any) -> str | None:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    return dt.datetime.fromtimestamp(timestamp, dt.UTC).isoformat().replace("+00:00", "Z")


def safe_tracker_url(value: Any) -> str | None:
    url = str(value or "").strip()
    if not url:
        return None
    try:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname
        if not parsed.scheme or not host:
            return "[redacted tracker URL]"
        port = f":{parsed.port}" if parsed.port is not None else ""
        return f"{parsed.scheme}://{host}{port}/[redacted]"
    except ValueError:
        return "[redacted tracker URL]"


def redact_tracker_message(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return URL_PATTERN.sub(
        lambda match: safe_tracker_url(match.group()) or "[redacted URL]",
        text,
    )


def compact_torrent(torrent: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": torrent.get("name"),
        "hash": str(torrent.get("hash") or "")[:12],
        "category": torrent.get("category"),
        "state": torrent.get("state"),
        "progress": progress_percent(torrent),
        "amount_left": torrent.get("amount_left"),
        "eta": torrent.get("eta"),
        "dlspeed": torrent.get("dlspeed"),
        "num_seeds": torrent.get("num_seeds"),
        "num_leechs": torrent.get("num_leechs"),
        "tracker": safe_tracker_url(torrent.get("tracker")),
        "save_path": torrent.get("save_path"),
        "content_path": torrent.get("content_path"),
        "added_at": epoch_timestamp(torrent.get("added_on")),
        "last_activity_at": epoch_timestamp(torrent.get("last_activity")),
        "completed_at": epoch_timestamp(torrent.get("completion_on")),
        "time_active_seconds": torrent.get("time_active"),
    }


def manifest_torrent(torrent: dict[str, Any]) -> dict[str, Any]:
    item = compact_torrent(torrent)
    item["hash"] = str(torrent.get("hash") or "")
    return item


def is_finished(torrent: dict[str, Any]) -> bool:
    try:
        return float(torrent.get("progress") or 0) >= 1.0
    except (TypeError, ValueError):
        return False


def torrent_size_left(torrent: dict[str, Any]) -> int:
    value = torrent.get("amount_left")
    return int(value) if isinstance(value, int) else 0


def write_manifest(path: str, result: dict[str, Any]) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    target.chmod(0o600)
    return str(target)


def require_root_only_directory(path: Path) -> None:
    if not path.is_dir():
        raise RuntimeError(f"backup path is not a directory: {path}")
    if path.stat().st_mode & 0o077:
        raise RuntimeError(f"backup path must be root-only (0700): {path}")


def backup_torrent_metadata(
    torrents: list[dict[str, Any]],
    backup_path: Path,
    bt_backup_dir: Path,
) -> list[str]:
    require_root_only_directory(backup_path)
    if not bt_backup_dir.is_dir():
        raise RuntimeError(f"qBittorrent metadata directory does not exist: {bt_backup_dir}")
    available = {item.name.casefold(): item for item in bt_backup_dir.iterdir() if item.is_file()}
    selected: list[Path] = []
    missing: list[str] = []
    for torrent in torrents:
        torrent_hash = str(torrent.get("hash") or "").strip()
        for suffix in (".torrent", ".fastresume"):
            name = f"{torrent_hash}{suffix}"
            source = available.get(name.casefold())
            if source is None:
                missing.append(name)
            else:
                selected.append(source)
    if missing:
        raise RuntimeError(
            "qBittorrent metadata backup is incomplete; missing: "
            + ", ".join(sorted(missing))
        )

    target_dir = backup_path / "qbit-metadata"
    target_dir.mkdir(mode=0o700, exist_ok=False)
    copied: list[str] = []
    for source in selected:
        target = target_dir / source.name
        shutil.copy2(source, target)
        target.chmod(0o600)
        copied.append(str(target))
    return sorted(copied)


def backup_selected_metadata(
    torrents: list[dict[str, Any]],
    expected_hashes: set[str],
    backup_path_value: str | None,
    manifest_value: str | None,
    bt_backup_dir_value: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    if not expected_hashes:
        raise RuntimeError("--backup-metadata-only requires --expected-hash")
    if not manifest_value:
        raise RuntimeError("--backup-metadata-only requires --manifest")
    if not backup_path_value:
        raise RuntimeError("--backup-metadata-only requires --backup-path")
    backup_path = Path(backup_path_value).resolve()
    manifest_path = Path(manifest_value).resolve()
    require_root_only_directory(backup_path)
    if manifest_path.parent != backup_path:
        raise RuntimeError("--manifest must be directly inside --backup-path")
    result["metadata_backup_only"] = True
    result["metadata_backup"] = backup_torrent_metadata(
        torrents,
        backup_path,
        Path(bt_backup_dir_value),
    )
    result["manifest"] = write_manifest(manifest_value, result)
    return result


def filter_arr_classifications(
    torrents: list[dict[str, Any]],
    correlations: dict[str, dict[str, Any]],
    classifications: set[str],
) -> list[dict[str, Any]]:
    if not classifications:
        return torrents
    return [
        torrent
        for torrent in torrents
        if (
            correlations.get(normalize_download_id(torrent.get("hash")), {}).get(
                "classification"
            )
            in classifications
        )
    ]


def filter_expected_hashes(
    torrents: list[dict[str, Any]], expected_hashes: set[str]
) -> list[dict[str, Any]]:
    normalized = {normalize_download_id(value) for value in expected_hashes if value}
    if not normalized:
        return torrents
    by_hash = {
        normalize_download_id(torrent.get("hash")): torrent for torrent in torrents
    }
    missing = normalized - set(by_hash)
    if missing:
        raise RuntimeError(
            "expected qBittorrent hashes were not found: " + ", ".join(sorted(missing))
        )
    return [by_hash[torrent_hash] for torrent_hash in sorted(normalized)]


def delete_torrents(
    base_url: str,
    opener: urllib.request.OpenerDirector,
    torrents: list[dict[str, Any]],
    delete_files: bool,
) -> None:
    hashes = [str(torrent.get("hash")) for torrent in torrents if torrent.get("hash")]
    if not hashes:
        return
    api_post(
        base_url,
        opener,
        "/torrents/delete",
        {
            "hashes": "|".join(hashes),
            "deleteFiles": str(delete_files).lower(),
        },
    )


def tracker_summary(
    base_url: str,
    opener: urllib.request.OpenerDirector,
    torrent_hash: str,
) -> list[dict[str, Any]]:
    trackers = api_get(
        base_url,
        opener,
        "/torrents/trackers",
        {"hash": torrent_hash},
        timeout=5,
    )
    summary: list[dict[str, Any]] = []
    for tracker in trackers:
        url = str(tracker.get("url") or "")
        if not url or url.startswith("**"):
            continue
        summary.append(
            {
                "status": tracker.get("status"),
                "tier": tracker.get("tier"),
                "url": safe_tracker_url(url),
                "msg": redact_tracker_message(tracker.get("msg")),
                "num_seeds": tracker.get("num_seeds"),
                "num_leeches": tracker.get("num_leeches"),
            }
        )
    return summary


def attach_tracker_summary(
    item: dict[str, Any],
    base_url: str,
    opener: urllib.request.OpenerDirector,
    torrent_hash: str,
) -> None:
    try:
        item["trackers"] = tracker_summary(base_url, opener, torrent_hash)
    except urllib.error.HTTPError as exc:
        item["tracker_error"] = f"HTTPError: HTTP {exc.code}"
    except (TimeoutError, urllib.error.URLError) as exc:
        item["tracker_error"] = f"{type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize qBittorrent states without printing credentials."
    )
    parser.add_argument("--env", default="/etc/qbit-port-sync.env")
    parser.add_argument(
        "--filter",
        default="all",
        help="qBittorrent torrent filter, for example all, downloading, stalled, errored.",
    )
    parser.add_argument("--title-regex")
    parser.add_argument("--problem-only", action="store_true")
    parser.add_argument(
        "--delete-states",
        help=(
            "comma-separated qBittorrent states to delete with files; requires "
            "--apply-delete and --manifest"
        ),
    )
    parser.add_argument("--category")
    parser.add_argument(
        "--expected-hash",
        action="append",
        default=[],
        help="retain only this exact torrent hash and require it to exist; may be repeated",
    )
    parser.add_argument("--keep-finished", action="store_true", default=True)
    parser.add_argument("--include-finished", action="store_false", dest="keep_finished")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply-delete", action="store_true")
    action.add_argument(
        "--backup-metadata-only",
        action="store_true",
        help="back up exact selected torrent metadata without deleting anything",
    )
    parser.add_argument(
        "--preserve-files",
        action="store_true",
        help="remove matching torrent metadata but retain payload files",
    )
    parser.add_argument("--manifest")
    parser.add_argument("--backup-path")
    parser.add_argument(
        "--bt-backup-dir",
        default="/opt/media-stack/qbittorrent/qBittorrent/BT_backup",
    )
    parser.add_argument("--include-trackers", action="store_true")
    parser.add_argument(
        "--correlate-arr",
        action="store_true",
        help="correlate exact torrent hashes with Sonarr/Radarr queue rows",
    )
    parser.add_argument(
        "--stale-hours",
        type=float,
        default=72,
        help="idle no-peer age used by --correlate-arr (default: 72)",
    )
    parser.add_argument(
        "--include-arr-history",
        action="store_true",
        help="include summarized exact-download-ID Arr history and indexer origin",
    )
    parser.add_argument(
        "--arr-classification",
        action="append",
        default=[],
        help="retain only this --correlate-arr classification; may be repeated",
    )
    parser.add_argument("--sample-limit", type=int, default=8)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.stale_hours <= 0:
        raise RuntimeError("--stale-hours must be greater than zero")
    if args.arr_classification and not args.correlate_arr:
        raise RuntimeError("--arr-classification requires --correlate-arr")

    base_url, opener = qbit_client(args.env)
    torrents = api_get(base_url, opener, "/torrents/info", {"filter": args.filter})
    if args.title_regex:
        import re

        pattern = re.compile(args.title_regex, re.IGNORECASE)
        torrents = [torrent for torrent in torrents if pattern.search(torrent.get("name") or "")]
    if args.problem_only:
        torrents = [
            torrent for torrent in torrents if str(torrent.get("state") or "") in PROBLEM_STATES
        ]
    if args.category:
        torrents = [
            torrent for torrent in torrents if str(torrent.get("category") or "") == args.category
        ]
    torrents = filter_expected_hashes(torrents, set(args.expected_hash))

    arr_correlations = (
        correlate_arr(
            torrents,
            int(args.stale_hours * 3600),
            include_history=args.include_arr_history,
        )
        if args.correlate_arr
        else {}
    )
    torrents = filter_arr_classifications(
        torrents, arr_correlations, set(args.arr_classification)
    )
    expected_hashes = {
        normalize_download_id(value) for value in args.expected_hash if value
    }
    selected_hashes = {
        normalize_download_id(torrent.get("hash")) for torrent in torrents
    }
    if args.apply_delete and expected_hashes and selected_hashes != expected_hashes:
        raise RuntimeError(
            "selected torrent hashes changed after Arr classification; refusing apply"
        )

    delete_states = {
        state.strip() for state in (args.delete_states or "").split(",") if state.strip()
    }
    delete_candidates = [
        torrent
        for torrent in torrents
        if delete_states
        and str(torrent.get("state") or "") in delete_states
        and (not args.keep_finished or not is_finished(torrent))
    ]
    delete_bytes_left = sum(torrent_size_left(torrent) for torrent in delete_candidates)

    state_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    save_path_counts: Counter[str] = Counter()
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    classification_counts: Counter[str] = Counter()
    finding_counts: Counter[str] = Counter()

    for torrent in torrents:
        state = str(torrent.get("state") or "unknown")
        state_counts[state] += 1
        category_counts[str(torrent.get("category") or "none")] += 1
        save_path_counts[str(torrent.get("save_path") or "unknown")] += 1
        correlation = arr_correlations.get(normalize_download_id(torrent.get("hash")))
        if correlation:
            classification_counts[correlation["classification"]] += 1
            finding_counts.update(correlation["findings"])
        if len(samples[state]) < args.sample_limit:
            item = compact_torrent(torrent)
            if correlation:
                item["arr_correlation"] = correlation
            if args.include_trackers and torrent.get("hash"):
                attach_tracker_summary(item, base_url, opener, str(torrent["hash"]))
            samples[state].append(item)

    result = {
        "apply_delete": args.apply_delete,
        "delete_files": not args.preserve_files,
        "delete_states": sorted(delete_states),
        "delete_candidate_count": len(delete_candidates),
        "delete_candidate_amount_left": delete_bytes_left,
        "delete_candidates": [manifest_torrent(torrent) for torrent in delete_candidates],
        "filter": args.filter,
        "problem_only": args.problem_only,
        "total": len(torrents),
        "state_counts": dict(state_counts.most_common()),
        "category_counts": dict(category_counts.most_common()),
        "save_path_counts": dict(save_path_counts.most_common()),
        "classification_counts": dict(classification_counts.most_common()),
        "finding_counts": dict(finding_counts.most_common()),
        "correlate_arr": args.correlate_arr,
        "stale_hours": args.stale_hours,
        "arr_classifications": sorted(set(args.arr_classification)),
        "expected_hashes": sorted(expected_hashes),
        "samples": samples,
    }

    if args.backup_metadata_only:
        backup_selected_metadata(
            torrents,
            expected_hashes,
            args.backup_path,
            args.manifest,
            args.bt_backup_dir,
            result,
        )
    elif args.apply_delete:
        if not delete_states:
            raise RuntimeError("--apply-delete requires --delete-states")
        if not args.manifest:
            raise RuntimeError("--apply-delete requires --manifest")
        if not args.backup_path:
            raise RuntimeError("--apply-delete requires --backup-path")
        backup_path = Path(args.backup_path).resolve()
        manifest_path = Path(args.manifest).resolve()
        require_root_only_directory(backup_path)
        if manifest_path.parent != backup_path:
            raise RuntimeError("--manifest must be directly inside --backup-path")
        result["metadata_backup"] = backup_torrent_metadata(
            delete_candidates,
            backup_path,
            Path(args.bt_backup_dir),
        )
        result["manifest"] = write_manifest(args.manifest, result)
        delete_torrents(
            base_url,
            opener,
            delete_candidates,
            delete_files=not args.preserve_files,
        )
        result["deleted_count"] = len(delete_candidates)
    elif args.manifest:
        result["manifest"] = write_manifest(args.manifest, result)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    print(f"qBittorrent torrents: {len(torrents)} filter={args.filter}")
    print("state counts:")
    for state, count in state_counts.most_common():
        print(f"- {state}: {count}")
    print("category counts:")
    for category, count in category_counts.most_common():
        print(f"- {category}: {count}")
    print("save paths:")
    for save_path, count in save_path_counts.most_common():
        print(f"- {save_path}: {count}")
    if args.correlate_arr:
        print("Arr correlation classifications:")
        for classification, count in classification_counts.most_common():
            print(f"- {classification}: {count}")
        print("Arr correlation findings:")
        for finding, count in finding_counts.most_common():
            print(f"- {finding}: {count}")
    print("samples:")
    for state, items in samples.items():
        print(f"- {state}:")
        for item in items:
            print(
                "  "
                f"{item['name']} | hash={item['hash']} | category={item['category']} "
                f"| progress={item['progress']} | left={item['amount_left']} "
                f"| seeds={item['num_seeds']} | eta={item['eta']} "
                f"| added={item['added_at']} | last_activity={item['last_activity_at']} "
                f"| active_seconds={item['time_active_seconds']} "
                f"| tracker={item['tracker'] or 'none'} | path={item['save_path']}"
            )
            correlation = item.get("arr_correlation")
            if correlation:
                labels = ", ".join(correlation["arr_labels"]) or "none"
                findings = ",".join(correlation["findings"]) or "none"
                print(
                    "    Arr "
                    f"app={correlation['app'] or 'none'} rows={correlation['arr_row_count']} "
                    f"classification={correlation['classification']} "
                    f"findings={findings} labels={labels}"
                )
                history = correlation.get("history")
                if history:
                    indexers = ", ".join(history["indexers"]) or "none"
                    print(
                        "    History "
                        f"grab_events={history['grab_event_count']} "
                        f"grab_batches={history['grab_batch_count']} "
                        f"indexers={indexers} "
                        f"first={history['first_grab_at']} last={history['last_grab_at']}"
                    )
                elif correlation.get("history_error"):
                    print(
                        "    History lookup failed: "
                        f"{correlation['history_error']}"
                    )
            if args.include_trackers:
                if item.get("tracker_error"):
                    print(f"    tracker lookup failed: {item['tracker_error']}")
                for tracker in item.get("trackers") or []:
                    print(
                        "    tracker "
                        f"status={tracker['status']} seeds={tracker['num_seeds']} "
                        f"url={tracker['url']} msg={tracker['msg'] or ''}"
                    )
    if delete_states:
        print(
            "delete candidates: "
            f"{len(delete_candidates)} amount_left={delete_bytes_left} "
            f"states={','.join(sorted(delete_states))}"
        )
        for torrent in delete_candidates:
            print(f"  hash={torrent.get('hash')} name={torrent.get('name')}")
        if result.get("manifest"):
            print(f"manifest: {result['manifest']}")
        if args.apply_delete:
            print(f"deleted torrents: {result['deleted_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
