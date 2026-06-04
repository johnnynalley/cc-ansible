#!/usr/bin/env python3
"""Read-only Arr import status snapshot for active queue recovery checks."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from typing import Any


APPS = {
    "sonarr": {
        "base_url": "http://127.0.0.1:8989",
        "config": "/opt/media-stack/sonarr/config.xml",
        "queue_params": {"includeSeries": "true", "includeEpisode": "true"},
        "history_params": {"includeSeries": "true", "includeEpisode": "true"},
    },
    "radarr": {
        "base_url": "http://127.0.0.1:7878",
        "config": "/opt/media-stack/radarr/config.xml",
        "queue_params": {"includeMovie": "true"},
        "history_params": {"includeMovie": "true"},
    },
}

TERMINAL_COMMAND_STATUSES = {"completed", "failed", "cancelled", "aborted"}


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def api_get(
    base_url: str,
    api_key: str,
    path: str,
    params: dict[str, Any] | None = None,
    timeout: int = 60,
) -> Any:
    query = ""
    if params:
        query = "?" + urllib.parse.urlencode(params, doseq=True)
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}{query}",
        headers={"X-Api-Key": api_key},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def paged_get(
    base_url: str,
    api_key: str,
    path: str,
    params: dict[str, Any],
    page_size: int,
    max_records: int | None = None,
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
        if max_records is not None and len(records) >= max_records:
            return records[:max_records], total
        if not page_records:
            return records, total
        if total is not None and len(records) >= total:
            return records, total
        if len(page_records) < page_size:
            return records, total
        page += 1


def parse_dt(value: str) -> dt.datetime:
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


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


def message_class(message: str) -> str:
    lowered = message.casefold()
    if "unable to move existing file to the recycle bin" in lowered:
        return "recycle_bin_move_failed"
    if "no files found are eligible for import" in lowered:
        return "no_files_eligible_for_import"
    if "not an upgrade" in lowered or "existing file" in lowered and "better" in lowered:
        return "current_file_better"
    if "download wasn't grabbed" in lowered or "download was not grabbed" in lowered:
        return "not_grabbed_by_arr"
    if "repair failed" in lowered or "aborted" in lowered or "incomplete" in lowered:
        return "download_failed_or_incomplete"
    if "access" in lowered and "denied" in lowered or "permission denied" in lowered:
        return "permission_denied"
    if "failed to import" in lowered:
        return "import_failed"
    return "other_status_message"


def item_label(app: str, record: dict[str, Any]) -> str:
    if app == "sonarr":
        series = (record.get("series") or {}).get("title") or "unknown series"
        episode = record.get("episode") or {}
        if isinstance(episode.get("seasonNumber"), int) and isinstance(
            episode.get("episodeNumber"), int
        ):
            suffix = f"S{episode['seasonNumber']:02}E{episode['episodeNumber']:02}"
        else:
            suffix = str(record.get("episodeId") or "unknown episode")
        return f"{series} {suffix}"
    movie = record.get("movie") or {}
    return str(movie.get("title") or record.get("title") or record.get("downloadTitle") or "unknown movie")


def history_label(app: str, record: dict[str, Any]) -> str:
    if app == "sonarr":
        series = (record.get("series") or {}).get("title") or "unknown series"
        episode = record.get("episode") or {}
        if isinstance(episode.get("seasonNumber"), int) and isinstance(
            episode.get("episodeNumber"), int
        ):
            return f"{series} S{episode['seasonNumber']:02}E{episode['episodeNumber']:02}"
        return series
    movie = record.get("movie") or {}
    return str(movie.get("title") or record.get("sourceTitle") or "unknown movie")


def queue_summary(
    app: str,
    base_url: str,
    api_key: str,
    queue_params: dict[str, Any],
    page_size: int,
    sample_limit: int,
) -> dict[str, Any]:
    params = {
        "sortKey": "timeleft",
        "sortDirection": "ascending",
        **queue_params,
    }
    records, total = paged_get(base_url, api_key, "/api/v3/queue", params, page_size)

    status_counts: Counter[str] = Counter()
    tracked_state_counts: Counter[str] = Counter()
    tracked_status_counts: Counter[str] = Counter()
    client_counts: Counter[str] = Counter()
    message_counts: Counter[str] = Counter()
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    state_samples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for record in records:
        status = str(record.get("status") or "unknown")
        tracked_state = str(record.get("trackedDownloadState") or "none")
        tracked_status = str(record.get("trackedDownloadStatus") or "none")
        status_counts[status] += 1
        tracked_state_counts[tracked_state] += 1
        tracked_status_counts[tracked_status] += 1
        client_counts[str(record.get("downloadClient") or "unknown")] += 1
        if (
            tracked_state not in {"downloading", "none"}
            or status in {"completed", "failed", "warning", "downloadClientUnavailable"}
        ) and len(state_samples[tracked_state]) < sample_limit:
            state_samples[tracked_state].append(
                {
                    "label": item_label(app, record),
                    "title": record.get("title") or record.get("downloadTitle"),
                    "status": status,
                    "tracked_state": tracked_state,
                    "tracked_status": tracked_status,
                    "client": record.get("downloadClient"),
                    "timeleft": record.get("timeleft"),
                    "sizeleft": record.get("sizeleft"),
                    "output_path": record.get("outputPath"),
                }
            )
        messages = status_messages(record)
        if not messages:
            message_counts["no_status_messages"] += 1
            continue
        seen_classes: set[str] = set()
        for message in messages:
            category = message_class(message)
            if category in seen_classes:
                continue
            seen_classes.add(category)
            message_counts[category] += 1
            if len(samples[category]) < sample_limit:
                samples[category].append(
                    {
                        "label": item_label(app, record),
                        "title": record.get("title") or record.get("downloadTitle"),
                        "status": record.get("status"),
                        "tracked_state": record.get("trackedDownloadState"),
                        "tracked_status": record.get("trackedDownloadStatus"),
                        "client": record.get("downloadClient"),
                        "message": message,
                    }
                )

    return {
        "total": total,
        "fetched": len(records),
        "status_counts": dict(status_counts.most_common()),
        "tracked_state_counts": dict(tracked_state_counts.most_common()),
        "tracked_status_counts": dict(tracked_status_counts.most_common()),
        "client_counts": dict(client_counts.most_common()),
        "message_counts": dict(message_counts.most_common()),
        "samples": {key: value for key, value in samples.items()},
        "state_samples": {key: value for key, value in state_samples.items()},
    }


def command_summary(base_url: str, api_key: str, sample_limit: int) -> dict[str, Any]:
    result = api_get(base_url, api_key, "/api/v3/command")
    records = result if isinstance(result, list) else result.get("records", [])
    status_counts: Counter[str] = Counter()
    active: list[dict[str, Any]] = []
    for record in records:
        status = str(record.get("status") or "unknown")
        status_counts[status] += 1
        if status.casefold() not in TERMINAL_COMMAND_STATUSES and len(active) < sample_limit:
            active.append(
                {
                    "name": record.get("name"),
                    "status": status,
                    "started": record.get("startedAt"),
                    "message": record.get("message"),
                    "state": record.get("stateChangeTime"),
                }
            )
    return {"status_counts": dict(status_counts.most_common()), "active": active}


def history_summary(
    app: str,
    base_url: str,
    api_key: str,
    history_params: dict[str, Any],
    since: dt.datetime,
    page_size: int,
    max_history: int,
    sample_limit: int,
) -> dict[str, Any]:
    params = {
        "sortKey": "date",
        "sortDirection": "descending",
        **history_params,
    }
    records, total = paged_get(
        base_url,
        api_key,
        "/api/v3/history",
        params,
        page_size,
        max_records=max_history,
    )

    kept: list[dict[str, Any]] = []
    for record in records:
        raw_date = record.get("date")
        if not raw_date:
            continue
        try:
            record_date = parse_dt(str(raw_date))
        except ValueError:
            continue
        if record_date < since:
            continue
        kept.append(record)

    event_counts: Counter[str] = Counter()
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in kept:
        event = str(record.get("eventType") or "unknown")
        event_counts[event] += 1
        if len(samples[event]) < sample_limit:
            samples[event].append(
                {
                    "date": record.get("date"),
                    "label": history_label(app, record),
                    "quality": ((record.get("quality") or {}).get("quality") or {}).get("name"),
                    "source": record.get("sourceTitle"),
                }
            )

    return {
        "total_available": total,
        "scanned": len(records),
        "since": since.isoformat(),
        "matched": len(kept),
        "event_counts": dict(event_counts.most_common()),
        "samples": {key: value for key, value in samples.items()},
    }


def app_snapshot(app: str, args: argparse.Namespace, since: dt.datetime) -> dict[str, Any]:
    config = APPS[app]
    api_key = read_api_key(config["config"])
    base_url = config["base_url"]
    return {
        "queue": queue_summary(
            app,
            base_url,
            api_key,
            config["queue_params"],
            args.page_size,
            args.sample_limit,
        ),
        "commands": command_summary(base_url, api_key, args.sample_limit),
        "history": history_summary(
            app,
            base_url,
            api_key,
            config["history_params"],
            since,
            args.page_size,
            args.max_history,
            args.sample_limit,
        ),
    }


def print_counter(title: str, values: dict[str, int]) -> None:
    print(f"{title}:")
    if not values:
        print("- none")
        return
    for key, value in values.items():
        print(f"- {key}: {value}")


def print_samples(title: str, samples: dict[str, list[dict[str, Any]]]) -> None:
    if not samples:
        return
    print(title)
    for category, rows in samples.items():
        print(f"- {category}:")
        for row in rows:
            print(
                "  {label} | {status}/{tracked_state}/{tracked_status} | {client} | {title}".format(
                    label=row.get("label"),
                    status=row.get("status", ""),
                    tracked_state=row.get("tracked_state", ""),
                    tracked_status=row.get("tracked_status", ""),
                    client=row.get("client", ""),
                    title=row.get("title") or row.get("source") or "",
                )
            )
            if row.get("message"):
                print(f"    message: {row['message']}")
            if row.get("timeleft") or row.get("sizeleft") is not None:
                print(
                    f"    timeleft={row.get('timeleft')} sizeleft={row.get('sizeleft')} "
                    f"output={row.get('output_path') or ''}"
                )


def print_history_samples(samples: dict[str, list[dict[str, Any]]]) -> None:
    if not samples:
        return
    print("history samples:")
    for event, rows in samples.items():
        print(f"- {event}:")
        for row in rows:
            print(
                f"  {row.get('date')} | {row.get('label')} | "
                f"{row.get('quality') or 'unknown'} | {row.get('source') or ''}"
            )


def print_snapshot(snapshot: dict[str, Any]) -> None:
    for app, data in snapshot.items():
        queue = data["queue"]
        print(f"== {app} ==")
        print(f"queue: fetched={queue['fetched']} total={queue['total']}")
        print_counter("status_counts", queue["status_counts"])
        print_counter("tracked_state_counts", queue["tracked_state_counts"])
        print_counter("tracked_status_counts", queue["tracked_status_counts"])
        print_counter("download_clients", queue["client_counts"])
        print_counter("message_classes", queue["message_counts"])
        print_samples("queue state samples:", queue["state_samples"])
        print_samples("queue samples:", queue["samples"])

        commands = data["commands"]
        print_counter("command_status_counts", commands["status_counts"])
        if commands["active"]:
            print("active_commands:")
            for command in commands["active"]:
                print(
                    f"- {command.get('name')} | {command.get('status')} | "
                    f"started={command.get('started')} | {command.get('message') or ''}"
                )

        history = data["history"]
        print(
            "history: since={since} scanned={scanned} matched={matched} total_available={total}".format(
                since=history["since"],
                scanned=history["scanned"],
                matched=history["matched"],
                total=history["total_available"],
            )
        )
        print_counter("history_event_counts", history["event_counts"])
        print_history_samples(history["samples"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", choices=["sonarr", "radarr", "all"], default="all")
    parser.add_argument("--since")
    parser.add_argument("--since-minutes", type=int, default=60)
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--max-history", type=int, default=5000)
    parser.add_argument("--sample-limit", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    since = parse_dt(args.since) if args.since else now_utc() - dt.timedelta(minutes=args.since_minutes)
    apps = list(APPS) if args.app == "all" else [args.app]
    snapshot = {app: app_snapshot(app, args, since) for app in apps}

    if args.json:
        print(json.dumps(snapshot, indent=2, sort_keys=True))
    else:
        print_snapshot(snapshot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
