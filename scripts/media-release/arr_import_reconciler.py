#!/usr/bin/env python3
"""Reconcile exact ledger-backed Arr downloads blocked only by ID matching."""

from __future__ import annotations

import argparse
import bisect
import datetime as dt
import hashlib
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import re
import subprocess
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
DEFAULT_HANDOFF_STATE = Path("/data/arr-terminal-handoff-state.json")
DEFAULT_MIN_PAYLOAD_AGE = 120
DEFAULT_MAX_HANDOFFS_PER_CYCLE = 5
DEFAULT_FFPROBE_TIMEOUT = 30
ID_MATCH_MARKERS = {
    "sonarr": "matched to series by id",
    "radarr": "matched to movie by id",
}
VIDEO_SUFFIXES = {".avi", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4", ".ts", ".webm"}
CURRENT_BETTER_MARKERS = {
    "already imported",
    "existing file",
    "not a custom format upgrade",
    "not an upgrade for existing",
}
IDENTITY_REJECTION_MARKERS = {
    "does not match the series",
    "does not match the movie",
}
DA_FORMAT_NAMES = {
    "anime dual audio",
    "regular dual audio",
}
HEVC_FORMAT_NAMES = {
    "h.265",
    "x265",
    "x265 (hd)",
    "x265 (no hdr/dv)",
}
LANGUAGE_ALIASES = {
    "chi": "zho",
    "chinese": "zho",
    "de": "deu",
    "deu": "deu",
    "en": "eng",
    "eng": "eng",
    "english": "eng",
    "fi": "fin",
    "fin": "fin",
    "finnish": "fin",
    "fr": "fra",
    "fra": "fra",
    "fre": "fra",
    "french": "fra",
    "ger": "deu",
    "german": "deu",
    "ja": "jpn",
    "japanese": "jpn",
    "jpn": "jpn",
    "ko": "kor",
    "kor": "kor",
    "korean": "kor",
    "und": "und",
    "zho": "zho",
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


class QbitClient:
    def __init__(self, base_url: str, username: str, password: str, timeout: int = 30):
        if not base_url or not username or not password:
            raise ValueError("qBittorrent API URL and credentials are required")
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        encoded = urllib.parse.urlencode(params or {}, doseq=True)
        data = encoded.encode("utf-8") if method == "POST" else None
        query = f"?{encoded}" if method == "GET" and encoded else ""
        request = urllib.request.Request(
            f"{self.base_url}/{path.lstrip('/')}{query}",
            data=data,
            headers={"Accept": "application/json"},
            method=method,
        )
        with self.opener.open(request, timeout=self.timeout) as response:
            payload = response.read()
        content_type = response.headers.get_content_type()
        if not payload:
            return None
        if content_type == "application/json" or payload[:1] in {b"{", b"["}:
            return json.loads(payload.decode("utf-8"))
        return payload.decode("utf-8", errors="replace")

    def login(self) -> None:
        response = self.request(
            "POST",
            "/auth/login",
            {"username": self.username, "password": self.password},
        )
        if str(response or "").strip() not in {"", "Ok."}:
            raise RuntimeError("qBittorrent API login failed")

    def version(self) -> str:
        return str(self.request("GET", "/app/version") or "").strip()

    def torrent(self, download_id: str) -> dict[str, Any] | None:
        torrents = self.request("GET", "/torrents/info", {"hashes": download_id}) or []
        normalized = normalize_download_id(download_id)
        matches = [
            torrent
            for torrent in torrents
            if normalize_download_id(torrent.get("hash")) == normalized
        ]
        return matches[0] if len(matches) == 1 else None

    def files(self, download_id: str) -> list[dict[str, Any]]:
        files = self.request("GET", "/torrents/files", {"hash": download_id}) or []
        return [item for item in files if isinstance(item, dict)]

    def set_share_limits(self, download_id: str, torrent: dict[str, Any], action: str) -> None:
        self.request(
            "POST",
            "/torrents/setShareLimits",
            {
                "hashes": download_id,
                "ratioLimit": torrent.get("ratio_limit", -2),
                "seedingTimeLimit": torrent.get("seeding_time_limit", -2),
                "inactiveSeedingTimeLimit": torrent.get("inactive_seeding_time_limit", -2),
                "shareLimitAction": action,
            },
        )


def version_tuple(value: str) -> tuple[int, ...]:
    match = re.search(r"\d+(?:\.\d+)+", value)
    return tuple(int(part) for part in match.group(0).split(".")) if match else ()


def profile_fingerprint(profile: object) -> str | None:
    if not isinstance(profile, dict):
        return None
    encoded = json.dumps(profile, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def quality_name(value: object) -> str | None:
    if not isinstance(value, dict):
        text = str(value or "").strip()
        return text or None
    quality = value.get("quality", value)
    if isinstance(quality, dict):
        text = str(quality.get("name") or "").strip()
        return text or None
    text = str(quality or "").strip()
    return text or None


def current_file_snapshot(target_id: int, media_file: object) -> dict[str, Any]:
    if not isinstance(media_file, dict):
        return {"target_id": target_id, "has_file": False}
    return {
        "target_id": target_id,
        "has_file": True,
        "file_id": media_file.get("id"),
        "quality": quality_name(media_file.get("quality")),
        "custom_format_score": media_file.get("customFormatScore"),
        "custom_formats": custom_format_names(media_file.get("customFormats")),
    }


def current_policy_state(
    app: str,
    client: JsonClient,
    context: dict[str, Any],
) -> tuple[str | None, list[dict[str, Any]]]:
    profile = context.get("quality_profile") or {}
    profile_id = profile.get("id")
    current_profile = (
        client.request("GET", f"/qualityprofile/{profile_id}")
        if isinstance(profile_id, int)
        else None
    )
    fingerprint = profile_fingerprint(current_profile)

    media_id = (context.get("media") or {}).get("id")
    if app == "radarr":
        if not isinstance(media_id, int):
            return fingerprint, []
        movie = client.request("GET", f"/movie/{media_id}") or {}
        return fingerprint, [current_file_snapshot(media_id, movie.get("movieFile"))]

    expected = expected_episode_ids(context)
    if not isinstance(media_id, int) or not expected:
        return fingerprint, []
    episodes = client.request("GET", "/episode", {"seriesId": media_id}) or []
    episode_files = client.request("GET", "/episodefile", {"seriesId": media_id}) or []
    files_by_id = {
        item.get("id"): item
        for item in episode_files
        if isinstance(item, dict) and isinstance(item.get("id"), int)
    }
    episodes_by_id = {
        item.get("id"): item
        for item in episodes
        if isinstance(item, dict) and item.get("id") in expected
    }
    return fingerprint, [
        current_file_snapshot(
            target_id,
            files_by_id.get((episodes_by_id.get(target_id) or {}).get("episodeFileId")),
        )
        for target_id in sorted(expected)
    ]


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


class HandoffState:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] = {"completed": {}, "searches": {}, "cursors": {}}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                for key in self.data:
                    if isinstance(loaded.get(key), dict):
                        self.data[key] = loaded[key]
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o640)
        temporary.replace(self.path)

    def mark_completed(self, app: str, download_id: str, classification: str) -> None:
        self.data["completed"][f"{app}:{normalize_download_id(download_id)}"] = {
            "at": iso_utc(),
            "classification": classification,
        }
        self.save()

    def is_completed(self, app: str, download_id: str) -> bool:
        return f"{app}:{normalize_download_id(download_id)}" in self.data["completed"]

    def cursor(self, app: str) -> str:
        return normalize_download_id(self.data["cursors"].get(app))

    def mark_cursor(self, app: str, download_id: str) -> None:
        self.data["cursors"][app] = normalize_download_id(download_id)
        self.save()

    def search_is_allowed(self, key: str, cooldown_hours: int = 24) -> bool:
        value = (self.data.get("searches") or {}).get(key)
        if not isinstance(value, str):
            return True
        observed = parse_history_date(value)
        return observed is None or (
            dt.datetime.now(dt.UTC) - observed
        ) >= dt.timedelta(hours=cooldown_hours)

    def mark_search(self, key: str) -> None:
        self.data["searches"][key] = iso_utc()
        self.save()


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


def queue_records(app: str, client: JsonClient) -> list[dict[str, Any]]:
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
        records.extend(item for item in page_records if isinstance(item, dict))
        total = payload.get("totalRecords") if isinstance(payload, dict) else None
        if (isinstance(total, int) and len(records) >= total) or len(page_records) < 1000:
            break
    return records


def reconcile_app(
    app: str,
    client: JsonClient,
    ledger: JsonClient,
    state: ReconcileState,
    dry_run: bool,
) -> list[dict[str, Any]]:
    records = queue_records(app, client)
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


def normalize_language(value: object) -> str:
    text = str(value or "").strip().casefold()
    if not text:
        return "und"
    return LANGUAGE_ALIASES.get(text, text[:3] if len(text) >= 3 else text)


def qbit_payload_path(torrent: dict[str, Any], item: dict[str, Any]) -> Path:
    save_path = Path(str(torrent.get("save_path") or ""))
    relative = Path(str(item.get("name") or ""))
    if not save_path.is_absolute() or relative.is_absolute() or not relative.parts:
        raise ValueError("qBittorrent returned an invalid payload path")
    path = (save_path / relative).resolve(strict=True)
    data_root = Path("/data").resolve(strict=True)
    if not path.is_relative_to(data_root):
        raise ValueError("qBittorrent payload path escapes the read-only /data mount")
    return path


def ffprobe_payload_file(path: Path, timeout: int) -> dict[str, Any]:
    before = path.stat()
    process = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=index,codec_type,codec_name,width,height:stream_tags=language,title",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    after = path.stat()
    if process.returncode != 0:
        raise ValueError(f"ffprobe failed for {path.name}: {process.stderr.strip()[:200]}")
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"payload changed while probing: {path.name}")
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"ffprobe returned invalid JSON for {path.name}") from exc
    streams = payload.get("streams") if isinstance(payload, dict) else []
    video = [item for item in streams or [] if item.get("codec_type") == "video"]
    audio = [item for item in streams or [] if item.get("codec_type") == "audio"]
    subtitles = [item for item in streams or [] if item.get("codec_type") == "subtitle"]

    def languages(values: list[dict[str, Any]]) -> list[str]:
        result = {
            normalize_language((item.get("tags") or {}).get("language"))
            for item in values
        }
        return sorted(result)

    return {
        "name": path.name,
        "size": before.st_size,
        "inode": before.st_ino,
        "links": before.st_nlink,
        "video_codecs": sorted(
            {str(item.get("codec_name") or "unknown").casefold() for item in video}
        ),
        "video_dimensions": sorted(
            {
                f"{int(item.get('width') or 0)}x{int(item.get('height') or 0)}"
                for item in video
            }
        ),
        "audio_languages": languages(audio),
        "subtitle_languages": languages(subtitles),
        "video_streams": len(video),
        "audio_streams": len(audio),
        "subtitle_streams": len(subtitles),
    }


def payload_probes(
    torrent: dict[str, Any],
    files: list[dict[str, Any]],
    min_payload_age: int,
    ffprobe_timeout: int,
) -> tuple[list[dict[str, Any]], dict[str, Path]]:
    try:
        complete = float(torrent.get("progress") or 0) >= 1.0
        amount_left = int(torrent.get("amount_left") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("qBittorrent completion state is invalid") from exc
    completion_on = int(torrent.get("completion_on") or 0)
    if not complete or amount_left != 0:
        raise ValueError("qBittorrent payload is not complete")
    if completion_on <= 0 or time.time() - completion_on < min_payload_age:
        raise ValueError("qBittorrent payload has not reached the minimum stable age")
    if str(torrent.get("state") or "").casefold() in {
        "checkingup",
        "checkingresumedata",
        "moving",
    }:
        raise ValueError("qBittorrent payload is still changing state")

    media_items = [
        item
        for item in files
        if Path(str(item.get("name") or "")).suffix.casefold() in VIDEO_SUFFIXES
    ]
    if not media_items:
        raise ValueError("qBittorrent payload contains no supported media files")
    probes: list[dict[str, Any]] = []
    paths: dict[str, Path] = {}
    for item in media_items:
        try:
            progress = float(item.get("progress") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("qBittorrent file progress is invalid") from exc
        if progress < 1.0:
            raise ValueError(f"qBittorrent media file is incomplete: {item.get('name')}")
        path = qbit_payload_path(torrent, item)
        expected_size = item.get("size")
        if isinstance(expected_size, int) and path.stat().st_size != expected_size:
            raise ValueError(f"qBittorrent file size does not match disk: {path.name}")
        probe = ffprobe_payload_file(path, ffprobe_timeout)
        if not probe["video_streams"] or not probe["audio_streams"]:
            raise ValueError(f"payload lacks required video/audio streams: {path.name}")
        probes.append(probe)
        paths[str(path)] = path
    return probes, paths


def release_claims(context: dict[str, Any]) -> dict[str, Any]:
    title = str(context.get("source_title") or "")
    folded = title.casefold()
    formats = {name.casefold() for name in custom_format_names(context.get("custom_formats"))}
    dual_title = bool(
        re.search(r"\bdual[ ._-]*audio\b|\bdual\b(?![ ._-]*subs?\b)", folded)
        or re.search(r"\bmulti[ ._-]*audio\b", folded)
        or re.search(
            r"\b(?:ja|jp|jpn)[+ ._-]+(?:en|eng)\b|\b(?:en|eng)[+ ._-]+(?:ja|jp|jpn)\b",
            folded,
        )
    )
    resolution_match = re.search(r"\b(2160|1080|720|576|480)p\b", folded)
    if not resolution_match:
        resolution_match = re.search(r"(2160|1080|720|576|480)p", str(context.get("quality") or ""), re.I)
    return {
        "dual_audio": dual_title or bool(formats & DA_FORMAT_NAMES),
        "hevc": bool(re.search(r"\b(?:x265|h[ .]?265|hevc)\b", folded))
        or bool(formats & HEVC_FORMAT_NAMES),
        "resolution": int(resolution_match.group(1)) if resolution_match else None,
    }


def dimensions_meet_resolution(dimensions: list[str], expected: int) -> bool:
    parsed: list[tuple[int, int]] = []
    for value in dimensions:
        match = re.fullmatch(r"(\d+)x(\d+)", value)
        if match:
            parsed.append((int(match.group(1)), int(match.group(2))))
    if not parsed:
        return False
    minimums = {
        2160: (3000, 1600),
        1080: (1400, 800),
        720: (900, 500),
        576: (700, 400),
        480: (600, 350),
    }
    long_min, short_min = minimums[expected]
    return any(
        max(width, height) >= long_min or min(width, height) >= short_min
        for width, height in parsed
    )


def payload_contract(
    context: dict[str, Any],
    probes: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    claims = release_claims(context)
    original_languages = {
        normalize_language(value) for value in context.get("original_languages") or []
    } - {"und"}
    failures: list[dict[str, str]] = []
    unverifiable: list[dict[str, str]] = []
    for probe in probes:
        name = str(probe["name"])
        codecs = set(probe["video_codecs"])
        languages = set(probe["audio_languages"])
        if claims["hevc"] and not codecs.intersection({"hevc", "h265", "x265"}):
            failures.append({"file": name, "claim": "hevc", "actual": ",".join(sorted(codecs))})
        resolution = claims["resolution"]
        if isinstance(resolution, int) and not dimensions_meet_resolution(
            probe["video_dimensions"], resolution
        ):
            failures.append(
                {
                    "file": name,
                    "claim": f"{resolution}p",
                    "actual": ",".join(probe["video_dimensions"]),
                }
            )
        if not claims["dual_audio"]:
            continue
        required = {"eng"} if original_languages == {"eng"} else {"eng", *original_languages}
        if not original_languages:
            unverifiable.append({"file": name, "claim": "dual_audio", "actual": "original language unknown"})
        elif "und" in languages and not required.issubset(languages):
            unverifiable.append(
                {"file": name, "claim": "dual_audio", "actual": ",".join(sorted(languages))}
            )
        elif not required.issubset(languages):
            failures.append(
                {"file": name, "claim": "dual_audio", "actual": ",".join(sorted(languages))}
            )
    return failures, unverifiable


def path_key(value: object) -> str:
    try:
        return str(Path(str(value or "")).resolve(strict=True))
    except (OSError, RuntimeError):
        return ""


def captured_files_changed(
    captured: object,
    current: list[dict[str, Any]],
) -> bool:
    if not isinstance(captured, list) or not captured:
        return False
    old = {item.get("target_id"): item for item in captured if isinstance(item, dict)}
    new = {item.get("target_id"): item for item in current if isinstance(item, dict)}
    if not old or old.keys() != new.keys():
        return False
    return any(
        bool(old[target].get("has_file")) != bool(new[target].get("has_file"))
        or old[target].get("file_id") != new[target].get("file_id")
        for target in old
    )


def classify_terminal_download(
    app: str,
    context: dict[str, Any],
    candidates: list[dict[str, Any]],
    probes: list[dict[str, Any]],
    payload_paths: dict[str, Path],
    current_profile_fingerprint: str | None,
    current_files: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = expected_episode_ids(context) if app == "sonarr" else {(context.get("media") or {}).get("id")}
    expected.discard(None)
    candidate_paths: set[str] = set()
    native_terminal = True
    has_eligible = False
    identity_mismatch = bool(context.get("identity_conflict"))
    target_mismatch = False
    per_file: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_path = path_key(candidate.get("path"))
        if candidate_path:
            candidate_paths.add(candidate_path)
        owner = candidate.get("series") if app == "sonarr" else candidate.get("movie")
        targets = candidate_target_ids(app, candidate)
        reasons = rejection_reasons(candidate)
        reason_text = "\n".join(reasons).casefold()
        if (
            isinstance(owner, dict)
            and owner.get("id") != (context.get("media") or {}).get("id")
        ) or any(
            marker in reason_text for marker in IDENTITY_REJECTION_MARKERS
        ):
            identity_mismatch = True
        if targets and not targets.issubset(expected):
            target_mismatch = True
            native_terminal = False
        if not isinstance(owner, dict) or not targets:
            native_terminal = False
        if not reasons:
            has_eligible = True
            native_classification = "accepted"
        elif all(
            any(marker in reason.casefold() for marker in CURRENT_BETTER_MARKERS)
            for reason in reasons
        ):
            native_classification = "current_better"
        else:
            native_classification = "unverifiable"
            native_terminal = False
        per_file.append(
            {
                "name": Path(candidate_path).name if candidate_path else None,
                "target_ids": sorted(targets),
                "classification": native_classification,
                "grab_score": context.get("custom_format_score"),
                "import_score": candidate.get("customFormatScore"),
                "rejections": reasons,
            }
        )

    payload_mapping_complete = bool(candidates) and candidate_paths == set(payload_paths)
    if not payload_mapping_complete:
        native_terminal = False
    failures, contract_unverifiable = payload_contract(context, probes)
    captured_profile = (context.get("quality_profile") or {}).get("fingerprint")
    profile_changed = bool(
        captured_profile
        and current_profile_fingerprint
        and captured_profile != current_profile_fingerprint
    )
    files_changed = captured_files_changed(context.get("current_files"), current_files)

    if not payload_mapping_complete or target_mismatch:
        classification = "unverifiable"
    elif identity_mismatch:
        classification = "identity_mismatch"
    elif failures:
        classification = "payload_misrepresented"
    elif has_eligible:
        classification = "accepted"
    elif not native_terminal or contract_unverifiable:
        classification = "unverifiable"
    elif profile_changed:
        classification = "profile_drift"
    elif files_changed:
        classification = "superseded_in_flight"
    else:
        classification = "current_better"
    actionable = classification in {
        "current_better",
        "superseded_in_flight",
        "profile_drift",
        "payload_misrepresented",
        "identity_mismatch",
    }
    return {
        "classification": classification,
        "actionable": actionable,
        "blocklist": classification in {"payload_misrepresented", "identity_mismatch"},
        "profile_changed": profile_changed,
        "current_files_changed": files_changed,
        "target_mismatch": target_mismatch,
        "contract_failures": failures,
        "contract_unverifiable": contract_unverifiable,
        "payload_probes": probes,
        "per_file": per_file,
    }


def finite_share_quota(torrent: dict[str, Any]) -> bool:
    return any(
        isinstance(torrent.get(key), (int, float)) and float(torrent[key]) >= 0
        for key in ("max_ratio", "max_seeding_time", "max_inactive_seeding_time")
    )


def share_quota_met(torrent: dict[str, Any]) -> bool:
    ratio = torrent.get("ratio")
    max_ratio = torrent.get("max_ratio")
    if isinstance(ratio, (int, float)) and isinstance(max_ratio, (int, float)):
        if float(max_ratio) >= 0 and float(ratio) >= float(max_ratio):
            return True
    seeding_time = torrent.get("seeding_time")
    max_seeding_time = torrent.get("max_seeding_time")
    if isinstance(seeding_time, int) and isinstance(max_seeding_time, int):
        if max_seeding_time >= 0 and seeding_time >= max_seeding_time * 60:
            return True
    inactive_time = torrent.get("inactive_seeding_time")
    max_inactive_time = torrent.get("max_inactive_seeding_time")
    if isinstance(inactive_time, int) and isinstance(max_inactive_time, int):
        if max_inactive_time >= 0 and inactive_time >= max_inactive_time * 60:
            return True
    return False


def share_limits_equal(first: dict[str, Any], second: dict[str, Any]) -> bool:
    return all(
        first.get(key) == second.get(key)
        for key in ("ratio_limit", "seeding_time_limit", "inactive_seeding_time_limit")
    )


def restore_share_limits(
    qbit: QbitClient,
    download_id: str,
    original: dict[str, Any],
    original_action: str,
) -> None:
    qbit.set_share_limits(download_id, original, original_action)
    restored = qbit.torrent(download_id)
    if (
        not restored
        or restored.get("share_limit_action") != original_action
        or not share_limits_equal(original, restored)
    ):
        raise RuntimeError("qBittorrent share-limit rollback verification failed")


def remove_queue_download(
    client: JsonClient,
    queue_id: int,
    remove_from_client: bool,
    blocklist: bool,
) -> None:
    client.request(
        "DELETE",
        f"/queue/{queue_id}",
        {
            "removeFromClient": str(remove_from_client).lower(),
            "blocklist": str(blocklist).lower(),
            "skipRedownload": "true",
            "changeCategory": "false",
        },
    )


def schedule_replacement_searches(
    app: str,
    client: JsonClient,
    context: dict[str, Any],
    state: HandoffState,
) -> list[dict[str, Any]]:
    media_id = (context.get("media") or {}).get("id")
    if not isinstance(media_id, int):
        return []
    if app == "radarr":
        scopes = [(f"radarr:movie:{media_id}", {"name": "MoviesSearch", "movieIds": [media_id]})]
    else:
        seasons = sorted(
            {
                int(item["season"])
                for item in context.get("expected_episodes") or []
                if isinstance(item, dict) and isinstance(item.get("season"), int)
            }
        )
        scopes = [
            (
                f"sonarr:series:{media_id}:season:{season}",
                {"name": "SeasonSearch", "seriesId": media_id, "seasonNumber": season},
            )
            for season in seasons
        ]
    scheduled: list[dict[str, Any]] = []
    for key, body in scopes:
        if not state.search_is_allowed(key):
            scheduled.append({"scope": key, "result": "cooldown"})
            continue
        state.mark_search(key)
        response = client.request("POST", "/command", body=body) or {}
        scheduled.append({"scope": key, "result": "scheduled", "command_id": response.get("id")})
    return scheduled


def apply_terminal_handoff(
    app: str,
    client: JsonClient,
    qbit: QbitClient,
    state: HandoffState,
    rows: list[dict[str, Any]],
    context: dict[str, Any],
    torrent: dict[str, Any],
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    download_id = normalize_download_id(torrent.get("hash"))
    if not evaluation["actionable"]:
        return {"result": "left_untouched", **evaluation}
    if not finite_share_quota(torrent):
        return {"result": "left_untouched_no_finite_quota", **evaluation}
    queue_ids = sorted(
        {int(row["id"]) for row in rows if isinstance(row.get("id"), int)}
    )
    if not queue_ids:
        return {"result": "left_untouched_no_queue_id", **evaluation}

    blocklist = bool(evaluation["blocklist"])
    if share_quota_met(torrent):
        remove_queue_download(client, queue_ids[0], True, blocklist)
        action = "removed_from_arr_and_qbit_quota_met"
    else:
        original = dict(torrent)
        original_action = str(torrent.get("share_limit_action") or "")
        if not original_action:
            return {"result": "left_untouched_share_action_unknown", **evaluation}
        if original_action != "RemoveWithContent":
            qbit.set_share_limits(download_id, torrent, "RemoveWithContent")
        updated = qbit.torrent(download_id)
        if (
            not updated
            or updated.get("share_limit_action") != "RemoveWithContent"
            or not share_limits_equal(original, updated)
        ):
            restore_share_limits(qbit, download_id, original, original_action)
            return {"result": "left_untouched_qbit_readback_failed", **evaluation}
        try:
            remove_queue_download(client, queue_ids[0], False, blocklist)
        except Exception:
            restore_share_limits(qbit, download_id, original, original_action)
            raise
        action = "hidden_from_arr_seeding_until_quota"

    searches = (
        schedule_replacement_searches(app, client, context, state) if blocklist else []
    )
    state.mark_completed(app, download_id, evaluation["classification"])
    return {"result": action, "replacement_searches": searches, **evaluation}


def reconcile_terminal_app(
    app: str,
    client: JsonClient,
    ledger: JsonClient,
    qbit: QbitClient,
    state: HandoffState,
    mode: str,
    download_ids: set[str],
    min_payload_age: int,
    ffprobe_timeout: int,
    max_downloads: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in queue_records(app, client):
        download_id = normalize_download_id(row.get("downloadId"))
        if not download_id or (download_ids and download_id not in download_ids):
            continue
        grouped.setdefault(download_id, []).append(row)

    ordered_ids = sorted(grouped)
    if ordered_ids and not download_ids:
        cursor = state.cursor(app)
        split = bisect.bisect_right(ordered_ids, cursor) if cursor else 0
        ordered_ids = ordered_ids[split:] + ordered_ids[:split]

    results: list[dict[str, Any]] = []
    considered = 0
    last_considered = ""
    for download_id in ordered_ids:
        rows = grouped[download_id]
        if considered >= max_downloads:
            break
        if state.is_completed(app, download_id):
            continue
        if not rows or any(
            str(row.get("status") or "").casefold() != "completed"
            or str(row.get("trackedDownloadState") or "").casefold() != "importblocked"
            or str(row.get("protocol") or "").casefold() != "torrent"
            for row in rows
        ):
            continue
        considered += 1
        last_considered = download_id
        base = {"app": app, "download_id": download_id, "handoff_mode": mode}
        native_download_id = str(rows[0].get("downloadId") or "").strip()
        context = ledger_context(ledger, native_download_id)
        if not context or context.get("app") != app:
            results.append({**base, "result": "left_untouched", "classification": "unverifiable", "reason": "ledger_missing"})
            continue
        torrent = qbit.torrent(download_id)
        if not torrent:
            results.append({**base, "result": "left_untouched", "classification": "unverifiable", "reason": "qbit_torrent_missing"})
            continue
        try:
            probes, paths = payload_probes(
                torrent,
                qbit.files(download_id),
                min_payload_age,
                ffprobe_timeout,
            )
            media_id = (context.get("media") or {}).get("id")
            params: dict[str, Any] = {
                "downloadId": native_download_id,
                "filterExistingFiles": "false",
            }
            if app == "radarr" and isinstance(media_id, int):
                params["movieId"] = media_id
            candidates = client.request("GET", "/manualimport", params) or []
            current_profile, current_files = current_policy_state(app, client, context)
            evaluation = classify_terminal_download(
                app,
                context,
                candidates,
                probes,
                paths,
                current_profile,
                current_files,
            )
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError, urllib.error.URLError) as exc:
            results.append(
                {**base, "result": "left_untouched", "classification": "unverifiable", "reason": str(exc)}
            )
            continue
        if mode != "apply":
            results.append({**base, "result": "would_handoff" if evaluation["actionable"] else "left_untouched", **evaluation})
            continue
        outcome = apply_terminal_handoff(
            app, client, qbit, state, rows, context, torrent, evaluation
        )
        results.append({**base, **outcome})
    if last_considered and not download_ids:
        state.mark_cursor(app, last_considered)
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
    parser.add_argument(
        "--handoff-mode",
        choices=["disabled", "audit", "apply"],
        default="disabled",
        help="audit or apply terminal qBittorrent handoff; disabled by default",
    )
    parser.add_argument(
        "--handoff-download-id",
        action="append",
        default=[],
        help="limit terminal handoff to one exact download ID; repeatable",
    )
    parser.add_argument("--handoff-state", type=Path, default=DEFAULT_HANDOFF_STATE)
    parser.add_argument("--min-payload-age", type=int, default=DEFAULT_MIN_PAYLOAD_AGE)
    parser.add_argument("--ffprobe-timeout", type=int, default=DEFAULT_FFPROBE_TIMEOUT)
    parser.add_argument(
        "--max-handoffs-per-cycle",
        type=int,
        default=DEFAULT_MAX_HANDOFFS_PER_CYCLE,
        help=(
            "maximum completed torrent groups evaluated per application per cycle; "
            "a persistent cursor rotates across unresolved groups"
        ),
    )
    parser.add_argument(
        "--handoff-only",
        action="store_true",
        help="skip exact-ID import fallback and run only terminal handoff",
    )
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
    handoff_state = HandoffState(args.handoff_state)
    qbit: QbitClient | None = None
    handoff_ids = {normalize_download_id(value) for value in args.handoff_download_id if value}
    if args.handoff_mode != "disabled":
        if args.min_payload_age < 1 or args.ffprobe_timeout < 1 or args.max_handoffs_per_cycle < 1:
            raise SystemExit("handoff age, timeout, and cycle limit must be positive")
        qbit = QbitClient(
            os.environ.get("QBIT_API", ""),
            os.environ.get("QBIT_USER", ""),
            os.environ.get("QBIT_PASS", ""),
        )
        qbit.login()
        version = qbit.version()
        if version_tuple(version) < (5, 2, 0):
            raise SystemExit(f"qBittorrent 5.2.0 or newer is required; found {version or 'unknown'}")
    last_emitted: dict[str, str] = {}
    while True:
        for app, client in clients.items():
            try:
                results = (
                    []
                    if args.handoff_only
                    else reconcile_app(app, client, ledger, state, args.dry_run)
                )
                if qbit is not None:
                    qbit.login()
                    results.extend(
                        reconcile_terminal_app(
                            app,
                            client,
                            ledger,
                            qbit,
                            handoff_state,
                            args.handoff_mode,
                            handoff_ids,
                            args.min_payload_age,
                            args.ffprobe_timeout,
                            args.max_handoffs_per_cycle,
                        )
                    )
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
