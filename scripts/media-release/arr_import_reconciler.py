#!/usr/bin/env python3
"""Reconcile exact ledger-backed Arr downloads blocked only by ID matching."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_INTERVAL = 60
DEFAULT_SUCCESS_SUPPRESSION = 3600
DEFAULT_HEARTBEAT = Path("/tmp/arr-import-reconciler.heartbeat")
DEFAULT_STATE = Path("/data/arr-import-reconciler-state.json")
DEFAULT_EVENT_LOG = Path("/data/arr-import-reconciler-events.jsonl")
ID_MATCH_MARKERS = {
    "sonarr": "matched to series by id",
    "radarr": "matched to movie by id",
}


def iso_utc() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        json.dump(event, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    path.chmod(0o640)


def normalize_download_id(value: object) -> str:
    return str(value or "").strip().casefold()


def status_messages(record: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    for status in record.get("statusMessages") or []:
        messages.extend(str(message) for message in status.get("messages") or [])
    if record.get("errorMessage"):
        messages.append(str(record["errorMessage"]))
    return messages


def is_exact_id_match_block(record: dict[str, Any], app: str) -> bool:
    if str(record.get("status") or "").casefold() != "completed":
        return False
    if str(record.get("trackedDownloadState") or "").casefold() != "importblocked":
        return False
    return ID_MATCH_MARKERS[app] in "\n".join(status_messages(record)).casefold()


def rejection_reasons(candidate: dict[str, Any]) -> list[str]:
    return [
        str(item.get("reason") or item) if isinstance(item, dict) else str(item)
        for item in candidate.get("rejections") or []
    ]


def expected_episode_ids(context: dict[str, Any]) -> set[int]:
    return {
        int(episode["id"])
        for episode in context.get("expected_episodes") or []
        if isinstance(episode, dict) and isinstance(episode.get("id"), int)
    }


def candidate_target_ids(app: str, candidate: dict[str, Any]) -> set[int]:
    if app == "sonarr":
        return {
            int(episode["id"])
            for episode in candidate.get("episodes") or []
            if isinstance(episode, dict) and isinstance(episode.get("id"), int)
        }
    movie = candidate.get("movie") or {}
    movie_id = movie.get("id")
    return {int(movie_id)} if isinstance(movie_id, int) else set()


def candidate_is_monitored(app: str, candidate: dict[str, Any]) -> bool:
    if app == "sonarr":
        episodes = candidate.get("episodes") or []
        return bool(episodes) and all(bool(episode.get("monitored")) for episode in episodes)
    return (candidate.get("movie") or {}).get("monitored") is not False


def custom_format_names(values: object) -> list[str]:
    result: list[str] = []
    for value in values or []:
        name = value.get("name") if isinstance(value, dict) else value
        name = str(name or "").strip()
        if name and name not in result:
            result.append(name)
    return result


def candidate_diagnostics(
    app: str,
    context: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    media_id = (context.get("media") or {}).get("id")
    expected = expected_episode_ids(context) if app == "sonarr" else {media_id}
    grabbed_formats = set(custom_format_names(context.get("custom_formats")))
    diagnostics: list[dict[str, Any]] = []
    for candidate in candidates:
        owner = candidate.get("series") if app == "sonarr" else candidate.get("movie")
        targets = candidate_target_ids(app, candidate)
        if (
            not isinstance(owner, dict)
            or owner.get("id") != media_id
            or not targets
            or not targets.issubset(expected)
        ):
            continue
        reasons = rejection_reasons(candidate)
        import_formats = set(custom_format_names(candidate.get("customFormats")))
        lost_formats = sorted(grabbed_formats - import_formats) if "customFormats" in candidate else []
        grab_score = context.get("custom_format_score")
        import_score = candidate.get("customFormatScore")
        score_changed = (
            isinstance(grab_score, int)
            and isinstance(import_score, int)
            and import_score != grab_score
        )
        reason_text = "\n".join(reasons).casefold()
        if context.get("identity_conflict"):
            classification = "identity_conflict"
        elif "not a custom format upgrade" in reason_text or "existing file" in reason_text:
            classification = "current_better"
        elif lost_formats and score_changed:
            classification = "grab_import_cf_drift"
        elif reasons:
            classification = "native_rejection"
        elif any(bool(item.get("hasFile")) for item in candidate.get("episodes") or []):
            classification = "eligible_upgrade"
        elif app == "radarr" and bool((candidate.get("movie") or {}).get("hasFile")):
            classification = "eligible_upgrade"
        else:
            classification = "eligible_missing"
        diagnostics.append(
            {
                "path": candidate.get("path"),
                "target_ids": sorted(targets),
                "classification": classification,
                "grab_score": grab_score,
                "import_score": import_score,
                "lost_formats": lost_formats,
                "gained_formats": sorted(import_formats - grabbed_formats)
                if "customFormats" in candidate
                else [],
                "rejections": reasons,
            }
        )
    return diagnostics


def select_candidates(
    app: str,
    context: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if context.get("app") != app or context.get("identity_conflict"):
        return []
    media_id = (context.get("media") or {}).get("id")
    if not isinstance(media_id, int):
        return []
    expected = expected_episode_ids(context) if app == "sonarr" else {media_id}
    if not expected:
        return []

    selected: list[dict[str, Any]] = []
    for candidate in candidates:
        if rejection_reasons(candidate) or not candidate.get("path"):
            continue
        owner = candidate.get("series") if app == "sonarr" else candidate.get("movie")
        if not isinstance(owner, dict) or owner.get("id") != media_id:
            continue
        targets = candidate_target_ids(app, candidate)
        if not targets or not targets.issubset(expected):
            continue
        if not candidate_is_monitored(app, candidate):
            continue
        selected.append(candidate)
    target_counts: dict[int, int] = {}
    for candidate in selected:
        for target in candidate_target_ids(app, candidate):
            target_counts[target] = target_counts.get(target, 0) + 1
    if any(count > 1 for count in target_counts.values()):
        return []
    return selected


def import_file(app: str, candidate: dict[str, Any], download_id: str) -> dict[str, Any]:
    common = {
        "path": candidate["path"],
        "folderName": candidate.get("folderName"),
        "quality": candidate.get("quality"),
        "languages": candidate.get("languages") or [],
        "releaseGroup": candidate.get("releaseGroup"),
        "indexerFlags": candidate.get("indexerFlags", 0),
        "downloadId": candidate.get("downloadId") or download_id,
    }
    if app == "sonarr":
        common.update(
            {
                "seriesId": candidate["series"]["id"],
                "episodeIds": sorted(candidate_target_ids(app, candidate)),
                "episodeFileId": candidate.get("episodeFileId") or 0,
                "releaseType": candidate.get("releaseType"),
            }
        )
    else:
        common.update(
            {
                "movieId": candidate["movie"]["id"],
                "movieFileId": candidate.get("movieFileId") or 0,
            }
        )
    return common


class JsonClient:
    def __init__(self, base_url: str, api_key: str = "", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        query = "?" + urllib.parse.urlencode(params, doseq=True) if params else ""
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}/{path.lstrip('/')}{query}",
            data=data,
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = response.read()
        return json.loads(payload.decode("utf-8")) if payload else None


class ReconcileState:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, str] = {}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data = {str(key): str(value) for key, value in loaded.items()}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

    def has(self, app: str, download_id: str) -> bool:
        value = self.data.get(f"{app}:{normalize_download_id(download_id)}")
        if not value:
            return False
        try:
            observed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return (dt.datetime.now(dt.UTC) - observed).total_seconds() <= DEFAULT_SUCCESS_SUPPRESSION

    def mark(self, app: str, download_id: str) -> None:
        self.data[f"{app}:{normalize_download_id(download_id)}"] = iso_utc()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.path)


def ledger_context(ledger: JsonClient, download_id: str) -> dict[str, Any] | None:
    try:
        payload = ledger.request("GET", f"/v1/context/{urllib.parse.quote(download_id, safe='')}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return payload.get("context") if isinstance(payload, dict) else None


def wait_for_command(client: JsonClient, command_id: int, timeout: int = 180) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = client.request("GET", f"/command/{command_id}") or {}
        if str(last.get("status") or "").casefold() in {"completed", "failed"}:
            return last
        time.sleep(2)
    return last


def reconcile_app(
    app: str,
    client: JsonClient,
    ledger: JsonClient,
    state: ReconcileState,
    dry_run: bool,
) -> list[dict[str, Any]]:
    queue_params: dict[str, Any] = {"pageSize": 1000}
    queue_params.update(
        {"includeSeries": "true", "includeEpisode": "true"}
        if app == "sonarr"
        else {"includeMovie": "true"}
    )
    records: list[dict[str, Any]] = []
    for page in range(1, 21):
        payload = client.request("GET", "/queue", {**queue_params, "page": page}) or {}
        page_records = payload.get("records", payload if isinstance(payload, list) else [])
        records.extend(page_records)
        total = payload.get("totalRecords") if isinstance(payload, dict) else None
        if (isinstance(total, int) and len(records) >= total) or len(page_records) < 1000:
            break
    results: list[dict[str, Any]] = []
    seen_download_ids: set[str] = set()
    for record in records:
        if not is_exact_id_match_block(record, app):
            continue
        download_id = str(record.get("downloadId") or "")
        normalized_download_id = normalize_download_id(download_id)
        if (
            not normalized_download_id
            or normalized_download_id in seen_download_ids
            or state.has(app, download_id)
        ):
            continue
        seen_download_ids.add(normalized_download_id)
        context = ledger_context(ledger, download_id)
        if not context:
            continue
        media_id = (context.get("media") or {}).get("id")
        params: dict[str, Any] = {
            "downloadId": download_id,
            "filterExistingFiles": "false",
        }
        if app == "radarr" and isinstance(media_id, int):
            params["movieId"] = media_id
        candidates = client.request("GET", "/manualimport", params) or []
        selected = select_candidates(app, context, candidates)
        result = {
            "app": app,
            "download_id": normalized_download_id,
            "media_id": media_id,
            "selected": len(selected),
            "paths": [candidate.get("path") for candidate in selected],
            "dry_run": dry_run,
            "identity_conflict": bool(context.get("identity_conflict")),
            "candidate_diagnostics": candidate_diagnostics(app, context, candidates),
        }
        if not selected:
            result["result"] = "no_safe_candidate"
            results.append(result)
            continue
        if dry_run:
            result["result"] = "would_import"
            results.append(result)
            continue
        # Persist before the request so an accepted command with a lost API
        # response cannot be submitted again on the next reconciliation pass.
        state.mark(app, download_id)
        command = client.request(
            "POST",
            "/command",
            body={
                "name": "ManualImport",
                "files": [import_file(app, candidate, download_id) for candidate in selected],
                "importMode": "Auto",
            },
        ) or {}
        command_id = command.get("id")
        final = wait_for_command(client, int(command_id)) if isinstance(command_id, int) else command
        result.update(
            {
                "command_id": command_id,
                "command_status": final.get("status"),
                "command_message": final.get("message"),
            }
        )
        if str(final.get("status") or "").casefold() == "completed":
            result["result"] = "imported"
        else:
            result["result"] = "command_failed"
        results.append(result)
    return results


def write_heartbeat(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(iso_utc() + "\n", encoding="utf-8")


def heartbeat_is_fresh(path: Path, max_age: int) -> bool:
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return False
    return age <= max_age


def parse_history_date(value: object) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def history_import_records(
    app: str,
    client: JsonClient,
    since: dt.datetime,
    max_history: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    page_size = min(max(max_history, 1), 1000)
    include = (
        {"includeSeries": "true", "includeEpisode": "true"}
        if app == "sonarr"
        else {"includeMovie": "true"}
    )
    for page in range(1, (max_history + page_size - 1) // page_size + 1):
        payload = client.request(
            "GET",
            "/history",
            {
                **include,
                "page": page,
                "pageSize": page_size,
                "sortKey": "date",
                "sortDirection": "descending",
            },
        ) or {}
        page_records = payload.get("records", payload if isinstance(payload, list) else [])
        if not isinstance(page_records, list):
            break
        reached_cutoff = False
        for record in page_records:
            if not isinstance(record, dict):
                continue
            observed = parse_history_date(record.get("date"))
            if observed is not None and observed < since:
                reached_cutoff = True
                continue
            if str(record.get("eventType") or "").casefold() == "downloadfolderimported":
                records.append(record)
            if len(records) >= max_history:
                return records
        total = payload.get("totalRecords") if isinstance(payload, dict) else None
        if reached_cutoff or len(page_records) < page_size:
            break
        if isinstance(total, int) and page * page_size >= total:
            break
    return records


def history_download_id(record: dict[str, Any]) -> str:
    data = record.get("data") if isinstance(record.get("data"), dict) else {}
    return str(record.get("downloadId") or data.get("downloadId") or "").strip()


def history_score(record: dict[str, Any]) -> int | None:
    value = record.get("customFormatScore")
    if value is None and isinstance(record.get("data"), dict):
        value = record["data"].get("customFormatScore")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def audit_import_history(
    app: str,
    client: JsonClient,
    ledger: JsonClient,
    since: dt.datetime,
    max_history: int,
) -> dict[str, Any]:
    imports = history_import_records(app, client, since, max_history)
    grouped: dict[str, list[dict[str, Any]]] = {}
    missing_download_id = 0
    for record in imports:
        download_id = normalize_download_id(history_download_id(record))
        if not download_id:
            missing_download_id += 1
            continue
        grouped.setdefault(download_id, []).append(record)

    results: list[dict[str, Any]] = []
    ledger_missing = 0
    for download_id, records in grouped.items():
        context = ledger_context(ledger, download_id)
        if not context or context.get("app") != app:
            ledger_missing += 1
            continue
        grab_formats = set(custom_format_names(context.get("custom_formats")))
        import_variants: dict[tuple[int | None, tuple[str, ...]], int] = {}
        for record in records:
            import_formats = tuple(sorted(custom_format_names(record.get("customFormats"))))
            variant = (history_score(record), import_formats)
            import_variants[variant] = import_variants.get(variant, 0) + 1

        variants: list[dict[str, Any]] = []
        classifications: set[str] = set()
        grab_score = context.get("custom_format_score")
        for (import_score, import_formats_tuple), count in import_variants.items():
            import_formats = set(import_formats_tuple)
            gained = sorted(import_formats - grab_formats)
            lost = sorted(grab_formats - import_formats)
            score_changed = (
                isinstance(grab_score, int)
                and isinstance(import_score, int)
                and grab_score != import_score
            )
            if score_changed:
                classification = "score_drift"
            elif gained or lost:
                classification = "format_drift"
            else:
                classification = "stable"
            classifications.add(classification)
            variants.append(
                {
                    "classification": classification,
                    "count": count,
                    "import_score": import_score,
                    "gained_formats": gained,
                    "lost_formats": lost,
                }
            )
        results.append(
            {
                "download_id": download_id,
                "source_title": context.get("source_title"),
                "captured_at": context.get("captured_at"),
                "grab_score": grab_score,
                "grab_formats": sorted(grab_formats),
                "import_count": len(records),
                "classification": (
                    "score_drift"
                    if "score_drift" in classifications
                    else "format_drift"
                    if "format_drift" in classifications
                    else "stable"
                ),
                "variants": sorted(
                    variants,
                    key=lambda item: (
                        str(item["classification"]),
                        item["import_score"] if isinstance(item["import_score"], int) else -1,
                    ),
                ),
            }
        )

    counts: dict[str, int] = {}
    for result in results:
        classification = str(result["classification"])
        counts[classification] = counts.get(classification, 0) + 1
    return {
        "app": app,
        "since": since.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "history_import_records": len(imports),
        "download_ids": len(grouped),
        "matched_download_ids": len(results),
        "ledger_missing_download_ids": ledger_missing,
        "missing_download_id_records": missing_download_id,
        "classification_counts": counts,
        "results": sorted(
            results,
            key=lambda item: (
                item["classification"] == "stable",
                str(item.get("captured_at") or ""),
                str(item.get("source_title") or "").casefold(),
            ),
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    parser.add_argument("--heartbeat", type=Path, default=DEFAULT_HEARTBEAT)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--event-log", type=Path, default=DEFAULT_EVENT_LOG)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check-health", action="store_true")
    parser.add_argument("--max-heartbeat-age", type=int, default=180)
    parser.add_argument("--audit-import-history", action="store_true")
    parser.add_argument("--audit-app", choices=["sonarr", "radarr", "all"], default="all")
    parser.add_argument("--since-hours", type=int, default=24 * 7)
    parser.add_argument("--max-history", type=int, default=5000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.check_health:
        return 0 if heartbeat_is_fresh(args.heartbeat, args.max_heartbeat_age) else 1

    ledger = JsonClient(os.environ.get("ARR_GRAB_CONTEXT_API", "http://arr-grab-context:9899"))
    clients = {
        "sonarr": JsonClient(os.environ.get("SONARR_API", ""), os.environ.get("SONARR_API_KEY", "")),
        "radarr": JsonClient(os.environ.get("RADARR_API", ""), os.environ.get("RADARR_API_KEY", "")),
    }
    if args.audit_import_history:
        if args.since_hours <= 0 or args.max_history <= 0:
            raise SystemExit("--since-hours and --max-history must be positive")
        since = dt.datetime.now(dt.UTC) - dt.timedelta(hours=args.since_hours)
        apps = list(clients) if args.audit_app == "all" else [args.audit_app]
        report = {
            app: audit_import_history(app, clients[app], ledger, since, args.max_history)
            for app in apps
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    state = ReconcileState(args.state)
    last_emitted: dict[str, str] = {}
    while True:
        for app, client in clients.items():
            try:
                results = reconcile_app(app, client, ledger, state, args.dry_run)
                for result in results:
                    fingerprint = json.dumps(result, sort_keys=True, separators=(",", ":"))
                    key = f"{app}:{result.get('download_id') or result.get('result')}"
                    if last_emitted.get(key) == fingerprint:
                        continue
                    last_emitted[key] = fingerprint
                    event = {"observed_at": iso_utc(), **result}
                    append_event(args.event_log, event)
                    print(json.dumps(event, sort_keys=True), flush=True)
            except (OSError, TimeoutError, ValueError, urllib.error.URLError) as exc:
                event = {
                    "observed_at": iso_utc(),
                    "app": app,
                    "result": "error",
                    "error": str(exc),
                }
                fingerprint = json.dumps(event | {"observed_at": None}, sort_keys=True)
                if last_emitted.get(f"{app}:error") != fingerprint:
                    last_emitted[f"{app}:error"] = fingerprint
                    append_event(args.event_log, event)
                    print(json.dumps(event, sort_keys=True), file=sys.stderr, flush=True)
        write_heartbeat(args.heartbeat)
        if args.once:
            return 0
        time.sleep(max(args.interval, 5))


if __name__ == "__main__":
    raise SystemExit(main())
