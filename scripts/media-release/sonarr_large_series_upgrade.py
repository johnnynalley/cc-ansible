#!/usr/bin/env python3
"""Queue one guarded Sonarr season search for a large monitored series.

Profilarr searches Sonarr at series scope. This companion handles series that
are excluded from Profilarr by an episode-count ceiling, preserving proactive
upgrades without allowing several large searches to overlap. It is dry-run by
default and never removes, imports, or blocklists a release.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


DEFAULT_SONARR_URL = "http://127.0.0.1:8989/api/v3"
DEFAULT_SONARR_CONFIG = Path("/opt/media-stack/sonarr/config.xml")
DEFAULT_PROFILARR_DB = Path("/opt/profilarr/config/data/profilarr.db")
DEFAULT_STATE = Path("/var/lib/sonarr-large-series-upgrade/state.json")
DEFAULT_LOCK = Path("/run/sonarr-large-series-upgrade.lock")
DEFAULT_WINDOW = "00:00-07:00"
SEARCH_WORKLOADS = {
    "RssSync",
    "SeriesSearch",
    "SeasonSearch",
    "EpisodeSearch",
    "MissingEpisodeSearch",
    "CutoffUnmetEpisodeSearch",
}
ACTIVE_STATUSES = {"queued", "started", "running"}


def read_api_key(path: Path) -> str:
    key = ET.parse(path).getroot().findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def api_request(
    base_url: str,
    api_key: str,
    path: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> Any:
    body = None
    headers = {"X-Api-Key": api_key}
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/{path.lstrip('/')}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Sonarr {method} {path} failed with HTTP {exc.code}") from exc
    if not data:
        return None
    return json.loads(data)


def parse_window(value: str) -> tuple[dt.time, dt.time]:
    try:
        start_text, end_text = value.split("-", 1)
        return (
            dt.datetime.strptime(start_text, "%H:%M").time(),
            dt.datetime.strptime(end_text, "%H:%M").time(),
        )
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{value!r} must look like HH:MM-HH:MM") from exc


def inside_window(window: tuple[dt.time, dt.time], now: dt.datetime | None = None) -> bool:
    current = (now or dt.datetime.now().astimezone()).time().replace(tzinfo=None)
    start, end = window
    if start < end:
        return start <= current < end
    return current >= start or current < end


def available_memory_mib(path: Path = Path("/proc/meminfo")) -> int:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    raise RuntimeError(f"{path}: MemAvailable was not found")


def active_sonarr_workloads(commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": command.get("id"),
            "name": command.get("name"),
            "status": command.get("status"),
            "message": command.get("message"),
        }
        for command in commands
        if str(command.get("status") or "").lower() in ACTIVE_STATUSES
        and (
            str(command.get("name") or "") in SEARCH_WORKLOADS
            or str(command.get("name") or "").endswith("Search")
        )
    ]


def profilarr_gate(db_path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        config = conn.execute(
            """
            SELECT u.enabled, a.id AS instance_id
            FROM upgrade_configs u
            JOIN arr_instances a ON a.id = u.arr_instance_id
            WHERE lower(a.type) = 'sonarr' AND a.enabled != 0
            ORDER BY a.id
            LIMIT 1
            """
        ).fetchone()
        if config is None:
            return {"window_open": False, "reason": "Profilarr Sonarr config is absent"}
        instance_id = int(config["instance_id"])
        active = conn.execute(
            """
            SELECT id, status, dedupe_key
            FROM job_queue
            WHERE job_type = 'arr.upgrade'
              AND status IN ('queued', 'pending', 'running', 'retry')
              AND dedupe_key IN (?, ?)
            ORDER BY id
            """,
            (f"arr.upgrade:{instance_id}", f"arr.upgrade.manual:{instance_id}"),
        ).fetchall()
        return {
            "window_open": bool(config["enabled"]),
            "instance_id": instance_id,
            "active_jobs": [dict(row) for row in active],
        }
    finally:
        conn.close()


def season_candidates(
    series_list: list[dict[str, Any]],
    large_series_threshold: int,
    max_season_episodes: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    oversized: list[dict[str, Any]] = []
    for series in series_list:
        if not series.get("monitored"):
            continue
        series_episodes = int((series.get("statistics") or {}).get("episodeCount") or 0)
        if series_episodes <= large_series_threshold:
            continue
        for season in series.get("seasons") or []:
            number = season.get("seasonNumber")
            if not season.get("monitored") or not isinstance(number, int) or number <= 0:
                continue
            episode_count = int((season.get("statistics") or {}).get("episodeCount") or 0)
            if episode_count < 1:
                continue
            item = {
                "series_id": int(series["id"]),
                "series_title": str(series.get("title") or series["id"]),
                "season_number": number,
                "episode_count": episode_count,
                "series_episode_count": series_episodes,
            }
            if episode_count > max_season_episodes:
                oversized.append(item)
            else:
                candidates.append(item)
    key = lambda item: (item["series_title"].casefold(), item["series_id"], item["season_number"])
    return sorted(candidates, key=key), sorted(oversized, key=key)


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "cursor": None, "runs": []}
    with path.open(encoding="utf-8") as handle:
        state = json.load(handle)
    state.setdefault("version", 1)
    state.setdefault("cursor", None)
    state.setdefault("runs", [])
    return state


def target_key(item: dict[str, Any]) -> str:
    return f"{item['series_id']}:{item['season_number']}"


def select_next(candidates: list[dict[str, Any]], cursor: str | None) -> dict[str, Any] | None:
    if not candidates:
        return None
    if cursor:
        for index, item in enumerate(candidates):
            if target_key(item) == cursor:
                return candidates[(index + 1) % len(candidates)]
    return candidates[0]


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


class ProcessLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any = None

    def __enter__(self) -> "ProcessLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("w", encoding="utf-8")
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another large-series upgrade worker is active") from exc
        self.handle.write(str(os.getpid()))
        self.handle.flush()
        return self

    def __exit__(self, *_exc: object) -> None:
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


def build_report(args: argparse.Namespace) -> tuple[dict[str, Any], str | None]:
    report: dict[str, Any] = {
        "checked_at": dt.datetime.now(dt.UTC).isoformat(),
        "mode": "apply" if args.apply else "dry-run",
    }
    if not args.ignore_window and not inside_window(args.window):
        return report, "outside overnight window"

    gate = profilarr_gate(args.profilarr_db)
    report["profilarr"] = gate
    if not args.ignore_window and not gate.get("window_open"):
        return report, "Profilarr Sonarr upgrade window is closed"
    if gate.get("active_jobs"):
        return report, "Profilarr Sonarr upgrade job is active"

    available_mib = available_memory_mib()
    report["available_memory_mib"] = available_mib
    if available_mib < args.min_available_mib:
        return report, f"available memory {available_mib} MiB is below guard"

    api_key = read_api_key(args.sonarr_config)
    commands = api_request(args.sonarr_url, api_key, "command")
    workloads = active_sonarr_workloads(commands)
    report["active_workloads"] = workloads
    if workloads:
        return report, "Sonarr search or RSS workload is active"

    series_list = api_request(args.sonarr_url, api_key, "series")
    candidates, oversized = season_candidates(
        series_list,
        args.large_series_threshold,
        args.max_season_episodes,
    )
    state = load_state(args.state)
    target = select_next(candidates, state.get("cursor"))
    report.update(
        {
            "candidate_seasons": len(candidates),
            "oversized_seasons": len(oversized),
            "oversized_sample": oversized[:10],
            "target": target,
        }
    )
    if target is None:
        return report, "no eligible large-series season"
    if not args.apply:
        return report, None

    command = api_request(
        args.sonarr_url,
        api_key,
        "command",
        method="POST",
        payload={
            "name": "SeasonSearch",
            "seriesId": target["series_id"],
            "seasonNumber": target["season_number"],
        },
    )
    command_id = command.get("id") if isinstance(command, dict) else None
    if not isinstance(command_id, int):
        raise RuntimeError("Sonarr did not return a command ID")
    run = {
        "queued_at": dt.datetime.now(dt.UTC).isoformat(),
        "command_id": command_id,
        **target,
    }
    state["cursor"] = target_key(target)
    state["runs"] = (state.get("runs") or [])[-999:] + [run]
    save_state(args.state, state)
    report["command_id"] = command_id
    return report, None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sonarr-url", default=DEFAULT_SONARR_URL)
    parser.add_argument("--sonarr-config", type=Path, default=DEFAULT_SONARR_CONFIG)
    parser.add_argument("--profilarr-db", type=Path, default=DEFAULT_PROFILARR_DB)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--window", type=parse_window, default=parse_window(DEFAULT_WINDOW))
    parser.add_argument("--large-series-threshold", type=int, default=30)
    parser.add_argument("--max-season-episodes", type=int, default=60)
    parser.add_argument("--min-available-mib", type=int, default=3072)
    parser.add_argument("--ignore-window", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.large_series_threshold < 1:
        parser.error("--large-series-threshold must be at least 1")
    if args.max_season_episodes < 1:
        parser.error("--max-season-episodes must be at least 1")
    if args.min_available_mib < 0:
        parser.error("--min-available-mib cannot be negative")
    return args


def main() -> int:
    args = parse_args()
    try:
        with ProcessLock(args.lock):
            report, skipped = build_report(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    report["skipped"] = skipped
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
    elif skipped:
        print(f"Skipped: {skipped}")
    elif args.apply:
        target = report["target"]
        print(
            f"Queued Sonarr command {report['command_id']} for "
            f"{target['series_title']} S{target['season_number']:02} "
            f"({target['episode_count']} episodes)."
        )
    else:
        target = report["target"]
        print(
            f"Dry run: next target is {target['series_title']} "
            f"S{target['season_number']:02} ({target['episode_count']} episodes); "
            f"candidates={report['candidate_seasons']} "
            f"oversized={report['oversized_seasons']}."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
