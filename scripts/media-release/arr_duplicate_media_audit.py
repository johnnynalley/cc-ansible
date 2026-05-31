#!/usr/bin/env python3
"""Audit and optionally clean up duplicate Arr media files.

Run on docker-vm without arguments to compare Sonarr/Radarr tracked files with
the library visible at /srv/media/plex. Run with --mode branch on the NAS host
to find hidden same-path duplicates across mergerfs branches. Default mode is
read-only. Cleanup requires --apply-delete and writes a manifest before unlinking
any media file. This script prints no API keys.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any


VIDEO_EXTENSIONS = {
    ".3gp",
    ".avi",
    ".divx",
    ".m2ts",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".mts",
    ".ogm",
    ".ogv",
    ".ts",
    ".webm",
    ".wmv",
}

IGNORED_DIR_NAMES = {
    ".appledouble",
    ".grab",
    ".radarr-recycle-bin",
    ".sonarr-recycle-bin",
    "@eadir",
    "behind the scenes",
    "deleted scenes",
    "extras",
    "featurettes",
    "interviews",
    "other",
    "sample",
    "samples",
    "shorts",
    "trailers",
}

IGNORED_FILE_RE = re.compile(
    r"(?i)(?:^|[\s._\-\[\(])(?:sample|trailer|featurette|behind[ ._-]?the[ ._-]?scenes|"
    r"deleted[ ._-]?scene|interview|extra)(?:$|[\s._\-\]\)])"
)

SEASON_EPISODE_RE = re.compile(r"(?i)\bS(?P<season>\d{1,2})(?P<eps>(?:[\s._-]*E\d{1,3})+)\b")
X_EPISODE_RE = re.compile(r"(?i)(?:^|[^\d])(?P<season>\d{1,2})x(?P<episode>\d{2,3})(?:[^\d]|$)")
SEASON_DIR_RE = re.compile(r"(?i)^season[\s._-]*(\d{1,3})$")
RESOLUTION_RE = re.compile(r"(?i)\b(480|576|720|1080|2160)p\b")
X265_RE = re.compile(r"(?i)(?:\b[xh][\s._-]?265\b|\bhevc\b)")
DUAL_AUDIO_TEXT_RE = re.compile(r"(?i)(?:dual[ ._-]?audio|multi[ ._-]?audio)")
LANGUAGE_PLUS_RE = re.compile(
    r"(?i)\b(?P<left>JA|JP|JPN|EN|ENG|KO|KOR|ZH|CHI|CN|FR|FRE|FIN|DE|GER|SPA|ES|POR|PT)"
    r"\+"
    r"(?P<right>JA|JP|JPN|EN|ENG|KO|KOR|ZH|CHI|CN|FR|FRE|FIN|DE|GER|SPA|ES|POR|PT)\b"
)
LANGUAGE_BRACKET_RE = re.compile(
    r"(?i)[\[\(](?P<token>JA|JP|JPN|EN|ENG|KO|KOR|ZH|CHI|CN|FR|FRE|FIN|DE|GER|SPA|ES|POR|PT)[\]\)]"
)
LANGUAGE_ALIASES = {
    "cn": "zh",
    "chi": "zh",
    "de": "de",
    "en": "en",
    "eng": "en",
    "es": "es",
    "fin": "fi",
    "fr": "fr",
    "fre": "fr",
    "ger": "de",
    "ja": "ja",
    "jp": "ja",
    "jpn": "ja",
    "ko": "ko",
    "kor": "ko",
    "por": "pt",
    "pt": "pt",
    "spa": "es",
    "zh": "zh",
}
SOURCE_PATTERNS = [
    (50, re.compile(r"(?i)\bremux\b")),
    (40, re.compile(r"(?i)(?:\bblu[ ._-]?ray\b|\bbd(?:rip)?\b|\bbdrip\b)")),
    (30, re.compile(r"(?i)(?:\bweb[ ._-]?dl\b|\bwebdl\b)")),
    (20, re.compile(r"(?i)\bweb[ ._-]?rip\b")),
    (10, re.compile(r"(?i)\bhdtv\b")),
]

DEFAULT_BRANCH_ROOTS = [
    "/srv/nas-01/media/plex",
    "/srv/nas-zfs/media/plex",
    "/srv/media-01/media/plex",
    "/srv/media-02/media/plex",
    "/srv/media-03/media/plex",
    "/srv/media-04/media/plex",
    "/srv/media-05/media/plex",
    "/srv/media-06/media/plex",
]

DEFAULT_MANIFEST_DIR = "/var/tmp/arr-duplicate-media-cleanup"


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    api_key = root.findtext("ApiKey")
    if not api_key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return api_key.strip()


def api_get(base_url: str, api_key: str, path: str, params: dict[str, Any] | None = None) -> Any:
    query = ""
    if params:
        query = "?" + urllib.parse.urlencode(params, doseq=True)
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}{query}",
        headers={"X-Api-Key": api_key},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {path} failed: {exc.code} {body}") from exc


def translate_path(path: str | None, container_root: str, host_root: str) -> str | None:
    if not path:
        return None
    normalized = path.rstrip("/")
    container = container_root.rstrip("/")
    host = host_root.rstrip("/")
    if normalized == container:
        return host
    if normalized.startswith(container + "/"):
        return host + normalized[len(container) :]
    return normalized


def is_video_file(path: Path) -> bool:
    return path.suffix.casefold() in VIDEO_EXTENSIONS


def ignored_file(path: Path) -> bool:
    for part in path.parts:
        if part.casefold() in IGNORED_DIR_NAMES:
            return True
    return IGNORED_FILE_RE.search(path.name) is not None


def iter_video_files(root: Path) -> list[Path]:
    if not root.exists() or not root.is_dir():
        return []
    files: list[Path] = []
    for current, dirs, names in os.walk(root):
        dirs[:] = [
            directory
            for directory in dirs
            if directory.casefold() not in IGNORED_DIR_NAMES
            and not directory.startswith(".")
        ]
        current_path = Path(current)
        for name in names:
            path = current_path / name
            if is_video_file(path) and not ignored_file(path):
                files.append(path)
    return sorted(files, key=lambda value: str(value).casefold())


def file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def file_nlink(path: Path) -> int | None:
    try:
        return path.stat().st_nlink
    except OSError:
        return None


def episode_keys_from_name(name: str) -> list[tuple[int, int]]:
    keys: list[tuple[int, int]] = []
    for match in SEASON_EPISODE_RE.finditer(name):
        season = int(match.group("season"))
        for episode in re.findall(r"(?i)E(\d{1,3})", match.group("eps")):
            keys.append((season, int(episode)))
    if keys:
        return sorted(set(keys))

    match = X_EPISODE_RE.search(name)
    if match:
        return [(int(match.group("season")), int(match.group("episode")))]
    return []


def rel_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def sample_paths(paths: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return paths[:limit]


def compact_file(path: Path, root: Path | None = None, tracked: bool | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": rel_path(path, root) if root else str(path),
        "absolute_path": str(path),
        "size_bytes": file_size(path),
        "hardlinks": file_nlink(path),
    }
    if tracked is not None:
        payload["tracked"] = tracked
    return payload


def deletion_candidate(
    *,
    absolute_path: str,
    relative_path: str,
    reason: str,
    media_type: str,
    title: str,
    size_bytes: int | None,
    hardlinks: int | None = None,
    tracked_files: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = {
        "absolute_path": absolute_path,
        "relative_path": relative_path,
        "reason": reason,
        "media_type": media_type,
        "title": title,
        "size_bytes": size_bytes,
        "hardlinks": hardlinks,
        "tracked_files": tracked_files or [],
    }
    if extra:
        candidate.update(extra)
    return candidate


def normalized_language(token: str) -> str:
    return LANGUAGE_ALIASES.get(token.casefold(), token.casefold())


def language_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for match in LANGUAGE_PLUS_RE.finditer(value):
        tokens.add(normalized_language(match.group("left")))
        tokens.add(normalized_language(match.group("right")))
    for match in LANGUAGE_BRACKET_RE.finditer(value):
        tokens.add(normalized_language(match.group("token")))
    return tokens


def media_signals(value: str) -> dict[str, Any]:
    resolutions = [int(match.group(1)) for match in RESOLUTION_RE.finditer(value)]
    source_rank = 0
    for rank, pattern in SOURCE_PATTERNS:
        if pattern.search(value):
            source_rank = max(source_rank, rank)
    languages = sorted(language_tokens(value))
    explicit_dual_audio = DUAL_AUDIO_TEXT_RE.search(value) is not None
    original_plus_english = "en" in languages and len(set(languages) - {"en"}) > 0
    return {
        "resolution": max(resolutions) if resolutions else None,
        "source_rank": source_rank,
        "x265": X265_RE.search(value) is not None,
        "audio_languages": languages,
        "dual_audio": explicit_dual_audio or original_plus_english,
        "explicit_dual_audio_text": explicit_dual_audio,
    }


def safe_loser_against_tracked(
    candidate_path: str,
    tracked_files: list[dict[str, Any]],
) -> tuple[bool, list[str], dict[str, Any]]:
    candidate_signals = media_signals(candidate_path)
    tracked_signal_rows = [
        {
            "path": str(file.get("absolute_path") or file.get("path") or ""),
            "signals": media_signals(str(file.get("absolute_path") or file.get("path") or "")),
        }
        for file in tracked_files
    ]
    reasons: list[str] = []
    if not tracked_signal_rows:
        return False, ["no tracked comparator"], {"candidate": candidate_signals, "tracked": []}
    if candidate_signals["resolution"] is None:
        return False, ["candidate resolution unknown"], {"candidate": candidate_signals, "tracked": tracked_signal_rows}

    for row in tracked_signal_rows:
        tracked = row["signals"]
        row_reasons: list[str] = []
        if tracked["resolution"] is None:
            row_reasons.append("tracked resolution unknown")
        elif candidate_signals["resolution"] > tracked["resolution"]:
            row_reasons.append("candidate has higher resolution")
        if candidate_signals["source_rank"] > tracked["source_rank"]:
            row_reasons.append("candidate has higher source rank")
        if candidate_signals["x265"] and not tracked["x265"]:
            row_reasons.append("candidate has x265/hevc and tracked does not")
        if candidate_signals["dual_audio"] and not tracked["dual_audio"]:
            row_reasons.append("candidate has dual-audio signal and tracked does not")
        if not candidate_signals["audio_languages"] and tracked["audio_languages"]:
            row_reasons.append("candidate audio language signal is unknown")
        if "en" in candidate_signals["audio_languages"] and "en" not in tracked["audio_languages"]:
            row_reasons.append("candidate has English audio signal and tracked does not")
        if not row_reasons:
            return True, [], {"candidate": candidate_signals, "tracked": tracked_signal_rows}
        reasons.extend(row_reasons)

    return False, sorted(set(reasons)), {"candidate": candidate_signals, "tracked": tracked_signal_rows}


def maybe_cleanup_candidate(
    candidate: dict[str, Any],
    skipped: list[dict[str, Any]],
) -> dict[str, Any] | None:
    safe, reasons, signals = safe_loser_against_tracked(
        str(candidate["absolute_path"]),
        candidate.get("tracked_files") or [],
    )
    candidate["comparison_signals"] = signals
    if safe:
        candidate["safe_delete"] = True
        return candidate
    skipped.append(
        {
            "absolute_path": candidate["absolute_path"],
            "relative_path": candidate["relative_path"],
            "reason": candidate["reason"],
            "media_type": candidate["media_type"],
            "title": candidate["title"],
            "size_bytes": candidate["size_bytes"],
            "unsafe_reasons": reasons,
            "tracked_files": candidate.get("tracked_files") or [],
            "comparison_signals": signals,
        }
    )
    return None


def unique_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        path = str(candidate["absolute_path"])
        unique.setdefault(path, candidate)
    return list(unique.values())


def cleanup_totals(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "candidate_files": len(candidates),
        "candidate_bytes": sum(int(candidate.get("size_bytes") or 0) for candidate in candidates),
    }


def write_manifest(args: argparse.Namespace, report: dict[str, Any]) -> str:
    manifest_dir = Path(args.manifest_dir)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    path = manifest_dir / f"{timestamp}-arr-duplicate-media-cleanup.json"
    payload = {
        "created_at": timestamp,
        "mode": args.mode,
        "apply_delete": bool(args.apply_delete),
        "report": report,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return str(path)


def apply_deletions(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for candidate in candidates:
        path = Path(str(candidate["absolute_path"]))
        result = {
            "absolute_path": str(path),
            "relative_path": candidate.get("relative_path"),
            "size_bytes": candidate.get("size_bytes"),
            "deleted": False,
            "error": None,
        }
        try:
            if not path.exists():
                result["error"] = "already missing"
            elif not path.is_file():
                result["error"] = "not a regular file"
            elif not is_video_file(path):
                result["error"] = "not a known video file extension"
            else:
                path.unlink()
                result["deleted"] = True
        except OSError as exc:
            result["error"] = str(exc)
        results.append(result)
    return results


def sonarr_episode_file_path(series_path: str, episode_file: dict[str, Any]) -> str | None:
    direct = episode_file.get("path")
    if isinstance(direct, str) and direct:
        return direct
    relative = episode_file.get("relativePath")
    if isinstance(relative, str) and relative:
        return f"{series_path.rstrip('/')}/{relative.lstrip('/')}"
    return None


def radarr_movie_file_path(movie_path: str, movie_file: dict[str, Any] | None) -> str | None:
    if not isinstance(movie_file, dict) or not movie_file:
        return None
    direct = movie_file.get("path")
    if isinstance(direct, str) and direct:
        return direct
    relative = movie_file.get("relativePath")
    if isinstance(relative, str) and relative:
        return f"{movie_path.rstrip('/')}/{relative.lstrip('/')}"
    return None


def sonarr_file_episode_keys(episodes: list[dict[str, Any]]) -> dict[int, list[tuple[int, int]]]:
    by_file: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for episode in episodes:
        file_id = episode.get("episodeFileId")
        if not isinstance(file_id, int) or file_id <= 0:
            continue
        season = episode.get("seasonNumber")
        number = episode.get("episodeNumber")
        if isinstance(season, int) and isinstance(number, int):
            by_file[file_id].append((season, number))
    return {file_id: sorted(set(keys)) for file_id, keys in by_file.items()}


def audit_sonarr(args: argparse.Namespace) -> dict[str, Any]:
    api_key = read_api_key(args.sonarr_config)
    series_list = api_get(args.sonarr_url, api_key, "/api/v3/series")
    issue_series: list[dict[str, Any]] = []
    cleanup_candidates: list[dict[str, Any]] = []
    cleanup_skipped: list[dict[str, Any]] = []
    totals = {
        "series": len(series_list),
        "tracked_files": 0,
        "missing_tracked_files": 0,
        "untracked_video_files": 0,
        "duplicate_episode_keys": 0,
        "missing_series_paths": 0,
        "unparsed_untracked_video_files": 0,
    }

    for index, series in enumerate(series_list, start=1):
        series_id = int(series["id"])
        arr_series_path = str(series.get("path") or "")
        host_series_path_str = translate_path(arr_series_path, args.container_root, args.host_root)
        if not host_series_path_str:
            continue
        host_series_path = Path(host_series_path_str)
        if not host_series_path.exists():
            episode_files = api_get(args.sonarr_url, api_key, "/api/v3/episodefile", {"seriesId": series_id})
            totals["missing_series_paths"] += 1
            totals["tracked_files"] += len(episode_files)
            totals["missing_tracked_files"] += len(episode_files)
            if episode_files:
                issue_series.append(
                    {
                        "id": series_id,
                        "title": series.get("title"),
                        "path": host_series_path_str,
                        "missing_series_path": True,
                        "missing_tracked_files": len(episode_files),
                        "untracked_video_files": 0,
                        "duplicate_episode_keys": 0,
                    }
                )
            continue

        episodes = api_get(args.sonarr_url, api_key, "/api/v3/episode", {"seriesId": series_id})
        file_keys = sonarr_file_episode_keys(episodes)
        episode_files = api_get(args.sonarr_url, api_key, "/api/v3/episodefile", {"seriesId": series_id})

        tracked_paths: dict[str, list[tuple[int, int]]] = {}
        missing_tracked: list[dict[str, Any]] = []
        actual_by_key: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
        tracked_by_key: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)

        for episode_file in episode_files:
            arr_file_path = sonarr_episode_file_path(arr_series_path, episode_file)
            host_file_path_str = translate_path(arr_file_path, args.container_root, args.host_root)
            if not host_file_path_str:
                continue
            host_file_path = Path(host_file_path_str)
            keys = file_keys.get(int(episode_file.get("id") or 0), [])
            if not keys:
                keys = episode_keys_from_name(host_file_path.name)
            tracked_paths[str(host_file_path)] = keys
            totals["tracked_files"] += 1
            if not host_file_path.exists():
                totals["missing_tracked_files"] += 1
                missing_tracked.append(compact_file(host_file_path, host_series_path, tracked=True))
                continue
            for key in keys:
                tracked_entry = compact_file(host_file_path, host_series_path, tracked=True)
                actual_by_key[key].append(tracked_entry)
                tracked_by_key[key].append(tracked_entry)

        actual_files = iter_video_files(host_series_path)
        untracked: list[dict[str, Any]] = []
        for path in actual_files:
            if str(path) in tracked_paths:
                continue
            keys = episode_keys_from_name(path.name)
            entry = compact_file(path, host_series_path, tracked=False)
            if keys:
                entry["parsed_episodes"] = [f"S{season:02}E{episode:02}" for season, episode in keys]
                for key in keys:
                    actual_by_key[key].append(entry)
                if all(tracked_by_key.get(key) for key in keys):
                    tracked_files_by_path = {
                        file["absolute_path"]: file
                        for key in keys
                        for file in tracked_by_key.get(key, [])
                    }
                    candidate = deletion_candidate(
                        absolute_path=str(path),
                        relative_path=rel_path(path, host_series_path),
                        reason="sonarr_untracked_duplicate_episode",
                        media_type="sonarr",
                        title=str(series.get("title") or series_id),
                        size_bytes=file_size(path),
                        hardlinks=file_nlink(path),
                        tracked_files=list(tracked_files_by_path.values()),
                        extra={
                            "series_id": series_id,
                            "episodes": [f"S{season:02}E{episode:02}" for season, episode in keys],
                        },
                    )
                    if safe_candidate := maybe_cleanup_candidate(candidate, cleanup_skipped):
                        cleanup_candidates.append(safe_candidate)
            else:
                totals["unparsed_untracked_video_files"] += 1
            untracked.append(entry)

        duplicate_keys = [
            {
                "episode": f"S{season:02}E{episode:02}",
                "files": files,
            }
            for (season, episode), files in sorted(actual_by_key.items())
            if len({file["path"] for file in files}) > 1
        ]

        totals["untracked_video_files"] += len(untracked)
        totals["duplicate_episode_keys"] += len(duplicate_keys)

        if missing_tracked or untracked or duplicate_keys:
            issue_series.append(
                {
                    "id": series_id,
                    "title": series.get("title"),
                    "path": host_series_path_str,
                    "missing_tracked_files": len(missing_tracked),
                    "untracked_video_files": len(untracked),
                    "duplicate_episode_keys": len(duplicate_keys),
                    "missing_tracked_samples": sample_paths(missing_tracked, args.sample_limit),
                    "untracked_samples": sample_paths(untracked, args.sample_limit),
                    "duplicate_samples": sample_paths(duplicate_keys, args.sample_limit),
                }
            )

        if args.progress and index % 25 == 0:
            print(f"scanned Sonarr series {index}/{len(series_list)}", file=sys.stderr)

    cleanup_candidates = unique_candidates(cleanup_candidates)
    return {
        "totals": totals,
        "series_with_issues": issue_series,
        "cleanup": cleanup_totals(cleanup_candidates),
        "cleanup_candidates": cleanup_candidates,
        "cleanup_skipped": cleanup_skipped,
    }


def audit_radarr(args: argparse.Namespace) -> dict[str, Any]:
    api_key = read_api_key(args.radarr_config)
    movies = api_get(args.radarr_url, api_key, "/api/v3/movie")
    issue_movies: list[dict[str, Any]] = []
    cleanup_candidates: list[dict[str, Any]] = []
    cleanup_skipped: list[dict[str, Any]] = []
    totals = {
        "movies": len(movies),
        "tracked_files": 0,
        "missing_movie_paths": 0,
        "missing_tracked_files": 0,
        "untracked_video_files": 0,
        "movie_folders_with_multiple_videos": 0,
    }

    for movie in movies:
        movie_path = str(movie.get("path") or "")
        host_movie_path_str = translate_path(movie_path, args.container_root, args.host_root)
        if not host_movie_path_str:
            continue
        host_movie_path = Path(host_movie_path_str)
        tracked_path_str = translate_path(
            radarr_movie_file_path(movie_path, movie.get("movieFile")),
            args.container_root,
            args.host_root,
        )
        tracked_path = Path(tracked_path_str) if tracked_path_str else None
        if not host_movie_path.exists():
            totals["missing_movie_paths"] += 1
            if tracked_path:
                totals["tracked_files"] += 1
                totals["missing_tracked_files"] += 1
                issue_movies.append(
                    {
                        "id": movie.get("id"),
                        "title": movie.get("title"),
                        "year": movie.get("year"),
                        "path": host_movie_path_str,
                        "missing_movie_path": True,
                        "missing_tracked_files": 1,
                        "untracked_video_files": 0,
                        "movie_folder_video_files": 0,
                        "missing_tracked_samples": [compact_file(tracked_path, host_movie_path, tracked=True)],
                    }
                )
            continue

        actual_files = iter_video_files(host_movie_path)
        untracked = [
            compact_file(path, host_movie_path, tracked=False)
            for path in actual_files
            if tracked_path is None or str(path) != str(tracked_path)
        ]

        missing_tracked: list[dict[str, Any]] = []
        if tracked_path:
            totals["tracked_files"] += 1
            if not tracked_path.exists():
                totals["missing_tracked_files"] += 1
                missing_tracked.append(compact_file(tracked_path, host_movie_path, tracked=True))

        has_multiple_videos = len(actual_files) > 1
        if has_multiple_videos:
            totals["movie_folders_with_multiple_videos"] += 1
        totals["untracked_video_files"] += len(untracked)

        if tracked_path and tracked_path.exists():
            tracked_file = compact_file(tracked_path, host_movie_path, tracked=True)
            for file in untracked:
                candidate = deletion_candidate(
                    absolute_path=str(host_movie_path / str(file["path"])),
                    relative_path=str(file["path"]),
                    reason="radarr_untracked_duplicate_movie_file",
                    media_type="radarr",
                    title=f"{movie.get('title')} ({movie.get('year')})",
                    size_bytes=file.get("size_bytes"),
                    hardlinks=file.get("hardlinks"),
                    tracked_files=[tracked_file],
                    extra={"movie_id": movie.get("id")},
                )
                if safe_candidate := maybe_cleanup_candidate(candidate, cleanup_skipped):
                    cleanup_candidates.append(safe_candidate)

        if missing_tracked or untracked or has_multiple_videos:
            issue_movies.append(
                {
                    "id": movie.get("id"),
                    "title": movie.get("title"),
                    "year": movie.get("year"),
                    "path": host_movie_path_str,
                    "missing_tracked_files": len(missing_tracked),
                    "untracked_video_files": len(untracked),
                    "movie_folder_video_files": len(actual_files),
                    "missing_tracked_samples": sample_paths(missing_tracked, args.sample_limit),
                    "untracked_samples": sample_paths(untracked, args.sample_limit),
                    "video_samples": sample_paths(
                        [compact_file(path, host_movie_path, tracked=(tracked_path is not None and path == tracked_path)) for path in actual_files],
                        args.sample_limit,
                    ),
                }
            )

    cleanup_candidates = unique_candidates(cleanup_candidates)
    return {
        "totals": totals,
        "movies_with_issues": issue_movies,
        "cleanup": cleanup_totals(cleanup_candidates),
        "cleanup_candidates": cleanup_candidates,
        "cleanup_skipped": cleanup_skipped,
    }


def series_key_from_relative_path(relative_path: str) -> str:
    parts = Path(relative_path).parts
    if len(parts) <= 1:
        return "."
    for index, part in enumerate(parts[:-1]):
        if SEASON_DIR_RE.match(part):
            return "/".join(parts[:index]) or "."
    return "/".join(parts[:-1])


def branch_file_payload(root: Path, path: Path) -> dict[str, Any]:
    return {
        "branch_root": str(root),
        "relative_path": rel_path(path, root),
        "path": str(path),
        "size_bytes": file_size(path),
    }


def audit_branches(args: argparse.Namespace) -> dict[str, Any]:
    branch_roots = [Path(root) for root in (args.branch_root or DEFAULT_BRANCH_ROOTS)]
    existing_roots = [root for root in branch_roots if root.exists() and root.is_dir()]
    missing_roots = [str(root) for root in branch_roots if root not in existing_roots]
    same_relative: dict[str, list[dict[str, Any]]] = defaultdict(list)
    episode_index: dict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
    total_files = 0

    for root in existing_roots:
        files = iter_video_files(root)
        total_files += len(files)
        for path in files:
            relative = rel_path(path, root)
            payload = branch_file_payload(root, path)
            same_relative[relative].append(payload)
            for season, episode in episode_keys_from_name(path.name):
                episode_index[(series_key_from_relative_path(relative), season, episode)].append(payload)

    same_relative_duplicates = [
        {"relative_path": relative, "files": files}
        for relative, files in sorted(same_relative.items())
        if len(files) > 1
    ]
    branch_order = {str(root): index for index, root in enumerate(branch_roots)}
    cleanup_candidates: list[dict[str, Any]] = []
    for duplicate in same_relative_duplicates:
        files = sorted(
            duplicate["files"],
            key=lambda file: branch_order.get(str(file["branch_root"]), len(branch_order)),
        )
        sizes = {file.get("size_bytes") for file in files}
        if len(sizes) != 1:
            continue
        kept = files[0]
        for file in files[1:]:
            cleanup_candidates.append(
                deletion_candidate(
                    absolute_path=str(file["path"]),
                    relative_path=str(file["relative_path"]),
                    reason="mergerfs_hidden_same_relative_path_duplicate",
                    media_type="branch",
                    title=str(file["relative_path"]),
                    size_bytes=file.get("size_bytes"),
                    tracked_files=[kept],
                    extra={
                        "deleted_branch_root": file.get("branch_root"),
                        "kept_branch_root": kept.get("branch_root"),
                    },
                )
            )
    parsed_episode_duplicates = [
        {
            "series_key": series_key,
            "episode": f"S{season:02}E{episode:02}",
            "files": files,
        }
        for (series_key, season, episode), files in sorted(episode_index.items())
        if len({file["path"] for file in files}) > 1
    ]

    cleanup_candidates = unique_candidates(cleanup_candidates)
    return {
        "totals": {
            "branch_roots": len(existing_roots),
            "missing_branch_roots": len(missing_roots),
            "video_files": total_files,
            "same_relative_path_duplicates": len(same_relative_duplicates),
            "parsed_episode_duplicates": len(parsed_episode_duplicates),
        },
        "existing_branch_roots": [str(root) for root in existing_roots],
        "missing_branch_roots": missing_roots,
        "same_relative_path_duplicate_samples": sample_paths(same_relative_duplicates, args.sample_limit),
        "parsed_episode_duplicate_samples": sample_paths(parsed_episode_duplicates, args.sample_limit),
        "cleanup": cleanup_totals(cleanup_candidates),
        "cleanup_candidates": cleanup_candidates,
    }


def print_arr_report(report: dict[str, Any], limit: int) -> None:
    print("Arr duplicate media audit")
    sonarr = report.get("sonarr")
    if sonarr:
        totals = sonarr["totals"]
        print(
            "Sonarr: series={series} tracked_files={tracked_files} "
            "missing_tracked={missing_tracked_files} untracked_videos={untracked_video_files} "
            "duplicate_episode_keys={duplicate_episode_keys} missing_series_paths={missing_series_paths}".format(**totals)
        )
        for item in sonarr["series_with_issues"][:limit]:
            missing_path = " missing_path=true" if item.get("missing_series_path") else ""
            print(
                "  - {title}: missing_tracked={missing} untracked={untracked} duplicate_keys={dupes}{missing_path}".format(
                    title=item.get("title"),
                    missing=item.get("missing_tracked_files", 0),
                    untracked=item.get("untracked_video_files", 0),
                    dupes=item.get("duplicate_episode_keys", 0),
                    missing_path=missing_path,
                )
            )
            for duplicate in item.get("duplicate_samples") or []:
                print(f"      duplicate {duplicate['episode']}:")
                for file in duplicate["files"][:limit]:
                    print(f"        [{'tracked' if file.get('tracked') else 'untracked'}] {file['path']}")
            for file in item.get("untracked_samples") or []:
                print(f"      untracked: {file['path']}")
            for file in item.get("missing_tracked_samples") or []:
                print(f"      missing tracked: {file['path']}")
        cleanup = sonarr.get("cleanup") or {}
        print(
            "Sonarr cleanup candidates: files={candidate_files} bytes={candidate_bytes} skipped={skipped}".format(
                candidate_files=cleanup.get("candidate_files", 0),
                candidate_bytes=cleanup.get("candidate_bytes", 0),
                skipped=len(sonarr.get("cleanup_skipped") or []),
            )
        )

    radarr = report.get("radarr")
    if radarr:
        totals = radarr["totals"]
        print(
            "Radarr: movies={movies} tracked_files={tracked_files} "
            "missing_tracked={missing_tracked_files} untracked_videos={untracked_video_files} "
            "multi_video_movie_folders={movie_folders_with_multiple_videos} missing_movie_paths={missing_movie_paths}".format(
                **totals
            )
        )
        for item in radarr["movies_with_issues"][:limit]:
            missing_path = " missing_path=true" if item.get("missing_movie_path") else ""
            print(
                "  - {title} ({year}): missing_tracked={missing} untracked={untracked} videos={videos}{missing_path}".format(
                    title=item.get("title"),
                    year=item.get("year"),
                    missing=item.get("missing_tracked_files", 0),
                    untracked=item.get("untracked_video_files", 0),
                    videos=item.get("movie_folder_video_files", 0),
                    missing_path=missing_path,
                )
            )
            for file in item.get("video_samples") or []:
                print(f"      [{'tracked' if file.get('tracked') else 'untracked'}] {file['path']}")
        cleanup = radarr.get("cleanup") or {}
        print(
            "Radarr cleanup candidates: files={candidate_files} bytes={candidate_bytes} skipped={skipped}".format(
                candidate_files=cleanup.get("candidate_files", 0),
                candidate_bytes=cleanup.get("candidate_bytes", 0),
                skipped=len(radarr.get("cleanup_skipped") or []),
            )
        )

    if report.get("cleanup_manifest"):
        print(f"cleanup manifest: {report['cleanup_manifest']}")
    if report.get("cleanup_results"):
        results = report["cleanup_results"]
        deleted = sum(1 for result in results if result.get("deleted"))
        errors = [result for result in results if result.get("error")]
        print(f"cleanup deleted files: {deleted}")
        if errors:
            print(f"cleanup errors: {len(errors)}")
            for result in errors[:limit]:
                print(f"  - {result['absolute_path']}: {result['error']}")
    if report.get("show_cleanup_candidates"):
        print_cleanup_candidates(all_cleanup_candidates(report), limit)


def print_branch_report(report: dict[str, Any], limit: int) -> None:
    totals = report["totals"]
    print("Mergerfs branch duplicate media audit")
    print(
        "Branches: roots={branch_roots} missing_roots={missing_branch_roots} "
        "video_files={video_files} same_relative_duplicates={same_relative_path_duplicates} "
        "parsed_episode_duplicates={parsed_episode_duplicates}".format(**totals)
    )
    if report["missing_branch_roots"]:
        print("Missing roots:")
        for root in report["missing_branch_roots"][:limit]:
            print(f"  - {root}")
    if report["same_relative_path_duplicate_samples"]:
        print("Same relative path duplicate samples:")
        for duplicate in report["same_relative_path_duplicate_samples"][:limit]:
            print(f"  - {duplicate['relative_path']}")
            for file in duplicate["files"][:limit]:
                print(f"      {file['branch_root']} size={file['size_bytes']}")
    if report["parsed_episode_duplicate_samples"]:
        print("Parsed episode duplicate samples:")
        for duplicate in report["parsed_episode_duplicate_samples"][:limit]:
            print(f"  - {duplicate['series_key']} {duplicate['episode']}")
            for file in duplicate["files"][:limit]:
                print(f"      {file['relative_path']} [{file['branch_root']}]")
    cleanup = report.get("cleanup") or {}
    print(
        "Branch cleanup candidates: files={candidate_files} bytes={candidate_bytes}".format(
            candidate_files=cleanup.get("candidate_files", 0),
            candidate_bytes=cleanup.get("candidate_bytes", 0),
        )
    )
    if report.get("cleanup_manifest"):
        print(f"cleanup manifest: {report['cleanup_manifest']}")
    if report.get("cleanup_results"):
        results = report["cleanup_results"]
        deleted = sum(1 for result in results if result.get("deleted"))
        errors = [result for result in results if result.get("error")]
        print(f"cleanup deleted files: {deleted}")
        if errors:
            print(f"cleanup errors: {len(errors)}")
            for result in errors[:limit]:
                print(f"  - {result['absolute_path']}: {result['error']}")
    if report.get("show_cleanup_candidates"):
        print_cleanup_candidates(report.get("cleanup_candidates") or [], limit)


def all_cleanup_candidates(report: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if report.get("sonarr"):
        candidates.extend(report["sonarr"].get("cleanup_candidates") or [])
    if report.get("radarr"):
        candidates.extend(report["radarr"].get("cleanup_candidates") or [])
    if report.get("cleanup_candidates"):
        candidates.extend(report.get("cleanup_candidates") or [])
    return unique_candidates(candidates)


def print_cleanup_candidates(candidates: list[dict[str, Any]], limit: int) -> None:
    if not candidates:
        return
    print("Cleanup candidate samples:")
    for candidate in candidates[:limit]:
        print(
            "  - {reason}: {absolute_path} size={size}".format(
                reason=candidate.get("reason"),
                absolute_path=candidate.get("absolute_path"),
                size=candidate.get("size_bytes"),
            )
        )
        for tracked in (candidate.get("tracked_files") or [])[:3]:
            print(f"      keeps: {tracked.get('absolute_path') or tracked.get('path')}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("arr", "branch"), default="arr")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--sample-limit", type=int, default=10)
    parser.add_argument("--progress", action="store_true", help="print Sonarr scan progress to stderr")
    parser.add_argument(
        "--show-cleanup-candidates",
        action="store_true",
        help="print sample deletion candidates in text output",
    )
    parser.add_argument(
        "--apply-delete",
        action="store_true",
        help=(
            "delete generated cleanup candidates after writing a manifest; default is dry-run"
        ),
    )
    parser.add_argument(
        "--manifest-dir",
        default=DEFAULT_MANIFEST_DIR,
        help="directory for cleanup manifests written before --apply-delete",
    )
    parser.add_argument("--skip-sonarr", action="store_true")
    parser.add_argument("--skip-radarr", action="store_true")
    parser.add_argument("--sonarr-url", default="http://127.0.0.1:8989")
    parser.add_argument("--sonarr-config", default="/opt/media-stack/sonarr/config.xml")
    parser.add_argument("--radarr-url", default="http://127.0.0.1:7878")
    parser.add_argument("--radarr-config", default="/opt/media-stack/radarr/config.xml")
    parser.add_argument("--container-root", default="/data")
    parser.add_argument("--host-root", default="/srv/media/plex")
    parser.add_argument(
        "--branch-root",
        action="append",
        help="mergerfs branch library root; repeat to override defaults",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.mode == "branch":
        report = audit_branches(args)
        report["show_cleanup_candidates"] = args.show_cleanup_candidates
        if args.apply_delete:
            report["cleanup_manifest"] = write_manifest(args, report)
            report["cleanup_results"] = apply_deletions(report.get("cleanup_candidates") or [])
        if args.json:
            json.dump(report, sys.stdout, indent=2, sort_keys=True)
            print()
        else:
            print_branch_report(report, args.sample_limit)
        return 0

    report: dict[str, Any] = {"mode": "arr", "host_root": args.host_root}
    if not args.skip_sonarr:
        report["sonarr"] = audit_sonarr(args)
    if not args.skip_radarr:
        report["radarr"] = audit_radarr(args)
    report["show_cleanup_candidates"] = args.show_cleanup_candidates
    if args.apply_delete:
        report["cleanup_manifest"] = write_manifest(args, report)
        report["cleanup_results"] = apply_deletions(all_cleanup_candidates(report))
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        print_arr_report(report, args.sample_limit)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
