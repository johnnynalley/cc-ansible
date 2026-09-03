#!/usr/bin/env python3
"""Persist exact Sonarr/Radarr grab context for download-client stampers."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


DEFAULT_DB = Path("/data/arr-grab-context.db")
DEFAULT_LISTEN = "0.0.0.0"
DEFAULT_PORT = 9899
DEFAULT_RETENTION_DAYS = 120
MAX_EVENT_BYTES = 1024 * 1024
TECHNICAL_WORDS = {
    "10bit",
    "1080p",
    "2160p",
    "480p",
    "576p",
    "720p",
    "aac",
    "ac3",
    "amzn",
    "atmos",
    "bluray",
    "ddp",
    "dsnp",
    "dual",
    "eac3",
    "flac",
    "h264",
    "h265",
    "hevc",
    "multi",
    "nf",
    "opus",
    "repack",
    "remux",
    "web",
    "webdl",
    "webrip",
    "x264",
    "x265",
}


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def iso_utc(value: dt.datetime | None = None) -> str:
    return (value or utc_now()).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_download_id(value: object) -> str:
    return str(value or "").strip().casefold()


def normalize_language(value: object) -> str | None:
    if isinstance(value, dict):
        value = value.get("name") or value.get("id")
    text = str(value or "").strip().casefold()
    aliases = {
        "chinese": "zho",
        "chi": "zho",
        "danish": "dan",
        "dutch": "nld",
        "english": "eng",
        "finnish": "fin",
        "french": "fra",
        "german": "deu",
        "italian": "ita",
        "japanese": "jpn",
        "korean": "kor",
        "norwegian": "nor",
        "portuguese": "por",
        "spanish": "spa",
        "swedish": "swe",
        "zh": "zho",
        "zho": "zho",
    }
    if not text:
        return None
    return aliases.get(text, text[:3] if len(text) >= 3 else text)


def normalized_words(value: object) -> list[str]:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    words = re.findall(r"[a-z0-9]+", text.casefold())
    return [word for word in words if word not in TECHNICAL_WORDS]


def primary_title_alias(value: str) -> str | None:
    """Return a distinctive title prefix before an explicit subtitle separator."""
    prefix = re.split(r"(?:\s+[-\u2013\u2014]\s+|:\s+)", str(value or ""), maxsplit=1)[0].strip()
    if not prefix or prefix == str(value or "").strip():
        return None
    words = normalized_words(prefix)
    if not words or sum(len(word) for word in words) < 5:
        return None
    if len(words) == 1 and len(words[0]) < 5:
        return None
    return prefix


def alias_matches_source(alias: str, source_title: str) -> bool:
    alias_words = normalized_words(alias)
    source_words = normalized_words(source_title)
    if not alias_words or not source_words:
        return False
    if len(alias_words) == 1:
        word = alias_words[0]
        return len(word) >= 3 and word in source_words
    width = len(alias_words)
    return any(source_words[index : index + width] == alias_words for index in range(len(source_words) - width + 1))


def identity_evidence(canonical_title: str, aliases: list[str], source_title: str) -> dict[str, Any]:
    candidates = []
    for value in [canonical_title, *aliases]:
        value = str(value or "").strip()
        if value and value.casefold() not in {item.casefold() for item in candidates}:
            candidates.append(value)
        primary = primary_title_alias(value)
        if primary and primary.casefold() not in {item.casefold() for item in candidates}:
            candidates.append(primary)
    candidates.sort(key=lambda alias: len(normalized_words(alias)), reverse=True)
    matched_alias = next((alias for alias in candidates if alias_matches_source(alias, source_title)), None)
    return {
        "identity_match": matched_alias is not None,
        "matched_alias": matched_alias,
        "aliases": candidates,
    }


def request_json(base_url: str, api_key: str, path: str, timeout: int = 10) -> Any:
    if not base_url or not api_key:
        return None
    request = urllib.request.Request(
        base_url.rstrip("/") + "/" + path.lstrip("/"),
        headers={"X-Api-Key": api_key, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    return json.loads(payload.decode("utf-8")) if payload else None


def alternate_titles(media: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for item in media.get("alternateTitles") or []:
        title = item.get("title") if isinstance(item, dict) else item
        title = str(title or "").strip()
        if title and title.casefold() not in {existing.casefold() for existing in result}:
            result.append(title)
    return result


def release_formats(release: dict[str, Any], event: dict[str, Any]) -> list[str]:
    values = release.get("customFormats") or (event.get("customFormatInfo") or {}).get("customFormats") or []
    result: list[str] = []
    for value in values:
        name = value.get("name") if isinstance(value, dict) else value
        name = str(name or "").strip()
        if name and name not in result:
            result.append(name)
    return result


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


def profile_snapshot(profile: object) -> dict[str, Any] | None:
    if not isinstance(profile, dict) or not isinstance(profile.get("id"), int):
        return None
    encoded = json.dumps(profile, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "id": profile["id"],
        "name": profile.get("name"),
        "fingerprint": hashlib.sha256(encoded).hexdigest(),
    }


def current_file_snapshot(target_id: int, media_file: object) -> dict[str, Any]:
    if not isinstance(media_file, dict):
        return {"target_id": target_id, "has_file": False}
    return {
        "target_id": target_id,
        "has_file": True,
        "file_id": media_file.get("id"),
        "quality": quality_name(media_file.get("quality")),
        "custom_format_score": media_file.get("customFormatScore"),
        "custom_formats": release_formats(
            {"customFormats": media_file.get("customFormats") or []}, {}
        ),
    }


def capture_policy_state(
    app: str,
    media: dict[str, Any],
    expected_episodes: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[str]]:
    base_url = os.environ.get(f"{app.upper()}_API", "")
    api_key = os.environ.get(f"{app.upper()}_API_KEY", "")
    errors: list[str] = []

    profile: dict[str, Any] | None = None
    profile_id = media.get("qualityProfileId")
    if isinstance(profile_id, int):
        try:
            profile = profile_snapshot(
                request_json(base_url, api_key, f"qualityprofile/{profile_id}")
            )
        except (OSError, TimeoutError, urllib.error.URLError, ValueError) as exc:
            errors.append(f"quality profile: {exc}")

    current_files: list[dict[str, Any]] = []
    media_id = media.get("id")
    if app == "radarr" and isinstance(media_id, int):
        movie_file = media.get("movieFile")
        current_files.append(current_file_snapshot(media_id, movie_file))
        return profile, current_files, errors

    expected_ids = {
        int(item["id"])
        for item in expected_episodes
        if isinstance(item.get("id"), int)
    }
    if app != "sonarr" or not isinstance(media_id, int) or not expected_ids:
        return profile, current_files, errors

    try:
        episodes = request_json(base_url, api_key, f"episode?seriesId={media_id}") or []
        episode_files = request_json(base_url, api_key, f"episodefile?seriesId={media_id}") or []
        files_by_id = {
            item.get("id"): item
            for item in episode_files
            if isinstance(item, dict) and isinstance(item.get("id"), int)
        }
        episodes_by_id = {
            item.get("id"): item
            for item in episodes
            if isinstance(item, dict) and item.get("id") in expected_ids
        }
        for target_id in sorted(expected_ids):
            episode = episodes_by_id.get(target_id) or {}
            episode_file_id = episode.get("episodeFileId")
            current_files.append(
                current_file_snapshot(target_id, files_by_id.get(episode_file_id))
            )
    except (OSError, TimeoutError, urllib.error.URLError, ValueError) as exc:
        errors.append(f"current episode files: {exc}")
    return profile, current_files, errors


def event_app(event: dict[str, Any]) -> str | None:
    if isinstance(event.get("series"), dict):
        return "sonarr"
    if isinstance(event.get("movie"), dict):
        return "radarr"
    instance = str(event.get("instanceName") or "").casefold()
    if "sonarr" in instance:
        return "sonarr"
    if "radarr" in instance:
        return "radarr"
    return None


def enrich_media(app: str, event_media: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    media = dict(event_media)
    base_url = os.environ.get(f"{app.upper()}_API", "")
    api_key = os.environ.get(f"{app.upper()}_API_KEY", "")
    media_id = media.get("id")
    if not media_id:
        return media, "event media has no id"
    endpoint = "series" if app == "sonarr" else "movie"
    try:
        enriched = request_json(base_url, api_key, f"{endpoint}/{media_id}")
    except (OSError, TimeoutError, urllib.error.URLError, ValueError) as exc:
        return media, str(exc)
    if isinstance(enriched, dict):
        media.update(enriched)
    return media, None


def build_context(event: dict[str, Any]) -> dict[str, Any]:
    app = event_app(event)
    if app is None:
        raise ValueError("unable to identify Sonarr or Radarr event")
    download_id = normalize_download_id(event.get("downloadId"))
    if not download_id:
        raise ValueError("grab event has no downloadId")

    event_media = event.get("series") if app == "sonarr" else event.get("movie")
    if not isinstance(event_media, dict):
        raise ValueError("grab event has no media object")
    media, enrichment_error = enrich_media(app, event_media)
    release = event.get("release") if isinstance(event.get("release"), dict) else {}
    source_title = str(release.get("releaseTitle") or event.get("downloadTitle") or "").strip()
    canonical_title = str(media.get("title") or event_media.get("title") or "").strip()
    aliases = alternate_titles(media)
    identity = identity_evidence(canonical_title, aliases, source_title)
    original_language = normalize_language(media.get("originalLanguage"))

    expected_episodes: list[dict[str, Any]] = []
    for episode in event.get("episodes") or []:
        if not isinstance(episode, dict):
            continue
        expected_episodes.append(
            {
                "id": episode.get("id"),
                "season": episode.get("seasonNumber"),
                "episode": episode.get("episodeNumber"),
                "title": episode.get("title"),
            }
        )

    profile, current_files, policy_enrichment_errors = capture_policy_state(
        app, media, expected_episodes
    )
    quality = quality_name(release.get("quality"))
    context = {
        "schema_version": 2,
        "download_id": download_id,
        "app": app,
        "instance_name": event.get("instanceName"),
        "captured_at": iso_utc(),
        "canonical_title": canonical_title,
        "aliases": identity["aliases"],
        "identity_match": identity["identity_match"],
        "identity_conflict": bool(source_title and canonical_title and not identity["identity_match"]),
        "matched_alias": identity["matched_alias"],
        "source_title": source_title,
        "original_languages": [original_language] if original_language else [],
        "release_group": release.get("releaseGroup"),
        "indexer": release.get("indexer"),
        "indexer_id": release.get("indexerId"),
        "protocol": release.get("protocol")
        or event.get("downloadProtocol")
        or event.get("protocol"),
        "quality": quality,
        "custom_formats": release_formats(release, event),
        "custom_format_score": release.get("customFormatScore")
        if release.get("customFormatScore") is not None
        else (event.get("customFormatInfo") or {}).get("customFormatScore"),
        "download_client": event.get("downloadClient"),
        "quality_profile": profile,
        "current_files": current_files,
        "media": {
            "id": media.get("id"),
            "title": canonical_title,
            "year": media.get("year"),
            "tvdb_id": media.get("tvdbId"),
            "tmdb_id": media.get("tmdbId"),
            "imdb_id": media.get("imdbId"),
        },
        "expected_episodes": expected_episodes,
        "enrichment_error": enrichment_error,
        "policy_enrichment_errors": policy_enrichment_errors,
    }
    return context


class ContextStore:
    def __init__(self, path: Path, retention_days: int = DEFAULT_RETENTION_DAYS):
        self.path = path
        self.retention_days = retention_days
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS grab_context (
                    download_id TEXT PRIMARY KEY,
                    app TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS grab_context_app_idx ON grab_context(app)")

    def upsert(self, context: dict[str, Any]) -> None:
        now = iso_utc()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO grab_context(download_id, app, captured_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(download_id) DO UPDATE SET
                    app = excluded.app,
                    captured_at = excluded.captured_at,
                    updated_at = excluded.updated_at,
                    payload = excluded.payload
                """,
                (
                    context["download_id"],
                    context["app"],
                    context["captured_at"],
                    now,
                    json.dumps(context, sort_keys=True, separators=(",", ":")),
                ),
            )
        self.prune()

    def get(self, download_id: str) -> dict[str, Any] | None:
        normalized = normalize_download_id(download_id)
        if not normalized:
            return None
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM grab_context WHERE download_id = ?",
                (normalized,),
            ).fetchone()
        if not row:
            return None
        context = json.loads(row["payload"])
        canonical_title = str(context.get("canonical_title") or "").strip()
        source_title = str(context.get("source_title") or "").strip()
        identity = identity_evidence(canonical_title, context.get("aliases") or [], source_title)
        context.update(
            {
                "aliases": identity["aliases"],
                "identity_match": identity["identity_match"],
                "identity_conflict": bool(
                    source_title and canonical_title and not identity["identity_match"]
                ),
                "matched_alias": identity["matched_alias"],
            }
        )
        return context

    def prune(self) -> int:
        cutoff = iso_utc(utc_now() - dt.timedelta(days=self.retention_days))
        with self.connect() as connection:
            cursor = connection.execute("DELETE FROM grab_context WHERE updated_at < ?", (cutoff,))
        return int(cursor.rowcount or 0)

    def count(self) -> int:
        with self.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM grab_context").fetchone()
        return int(row["count"])


class ContextHandler(BaseHTTPRequestHandler):
    server_version = "arr-grab-context/1"

    @property
    def store(self) -> ContextStore:
        return self.server.store  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} {fmt % args}", file=sys.stderr, flush=True)

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/health":
            self.send_json(HTTPStatus.OK, {"ok": True, "records": self.store.count()})
            return
        prefix = "/v1/context/"
        if parsed.path.startswith(prefix):
            download_id = urllib.parse.unquote(parsed.path[len(prefix) :])
            context = self.store.get(download_id)
            if context is None:
                self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "context not found"})
                return
            self.send_json(HTTPStatus.OK, {"ok": True, "context": context})
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/v1/events":
            self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_EVENT_BYTES:
            self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": "invalid event size"})
            return
        try:
            event = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid JSON"})
            return
        event_type = str(event.get("eventType") or "").casefold()
        if event_type in {"test", "testevent"}:
            self.send_json(HTTPStatus.OK, {"ok": True, "result": "test accepted"})
            return
        if event_type != "grab":
            self.send_json(HTTPStatus.ACCEPTED, {"ok": True, "result": "event ignored"})
            return
        try:
            context = build_context(event)
            self.store.upsert(context)
        except ValueError as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return
        self.send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "result": "context stored",
                "download_id": context["download_id"],
                "identity_match": context["identity_match"],
                "identity_conflict": context["identity_conflict"],
                "enrichment_error": context["enrichment_error"],
            },
        )


class ContextServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], store: ContextStore):
        super().__init__(address, ContextHandler)
        self.store = store


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--listen", default=DEFAULT_LISTEN)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS)
    parser.add_argument("--lookup", help="print one exact download-ID context and exit")
    parser.add_argument("--prune", action="store_true", help="prune expired context and exit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = ContextStore(args.db, retention_days=args.retention_days)
    if args.lookup:
        context = store.get(args.lookup)
        if context is None:
            return 1
        json.dump(context, sys.stdout, indent=2, sort_keys=True)
        print()
        return 0
    if args.prune:
        print(store.prune())
        return 0
    server = ContextServer((args.listen, args.port), store)
    print(f"arr-grab-context listening on {args.listen}:{args.port} db={args.db}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
