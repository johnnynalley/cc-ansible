#!/usr/bin/env python3
"""Audit Arr libraries and mergerfs branches for duplicate media files.

Run on docker-vm without arguments to compare Sonarr/Radarr tracked files with
the library visible at /srv/media/plex. Run with --mode branch on the NAS host
to find hidden same-path duplicates across mergerfs branches. This script is
read-only and prints no API keys.
"""

from __future__ import annotations

import argparse
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
        "size_bytes": file_size(path),
    }
    if tracked is not None:
        payload["tracked"] = tracked
    return payload


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
                actual_by_key[key].append(compact_file(host_file_path, host_series_path, tracked=True))

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

    return {"totals": totals, "series_with_issues": issue_series}


def audit_radarr(args: argparse.Namespace) -> dict[str, Any]:
    api_key = read_api_key(args.radarr_config)
    movies = api_get(args.radarr_url, api_key, "/api/v3/movie")
    issue_movies: list[dict[str, Any]] = []
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

    return {"totals": totals, "movies_with_issues": issue_movies}


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
    parsed_episode_duplicates = [
        {
            "series_key": series_key,
            "episode": f"S{season:02}E{episode:02}",
            "files": files,
        }
        for (series_key, season, episode), files in sorted(episode_index.items())
        if len({file["path"] for file in files}) > 1
    ]

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("arr", "branch"), default="arr")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--sample-limit", type=int, default=10)
    parser.add_argument("--progress", action="store_true", help="print Sonarr scan progress to stderr")
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
