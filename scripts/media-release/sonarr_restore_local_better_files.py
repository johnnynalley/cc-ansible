#!/usr/bin/env python3
"""Replace tracked Sonarr files with better existing local files.

This is intentionally narrow and dry-run by default. It looks for episodes
where Sonarr currently tracks a lower-scored file and the series folder already
contains a different local file for the same episode whose parsed score is
higher. With --apply it deletes only the lower tracked episode files through
Sonarr, then queues a RescanSeries command so Sonarr can attach the better
existing files.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any


VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv"}
LANGUAGE_COMBO_RE = re.compile(
    r"(?i)\b(?:ja|jp|jpn|japanese|zh|chi|zho|chinese|ko|kor|korean)"
    r"\b[ ._+&-]*\b(?:en|eng|english)\b|"
    r"\b(?:en|eng|english)\b[ ._+&-]*\b"
    r"(?:ja|jp|jpn|japanese|zh|chi|zho|chinese|ko|kor|korean)\b|"
    r"dual[ ._-]?audio|multi[ ._-]?audio"
)
X265_RE = re.compile(r"(?i)(?:\b[xh][\s._-]?265\b|\bhevc\b)")
BLURAY_RE = re.compile(r"(?i)(?:\bblu[ ._-]?ray\b|\bbluray\b|\bbdrip\b|\[bd\b|\bbd[ ._-]?1080p\b)")


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    api_key = root.findtext("ApiKey")
    if not api_key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return api_key.strip()


def api_request(
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    payload: Any | None = None,
    params: dict[str, Any] | None = None,
) -> Any:
    query = "?" + urllib.parse.urlencode(params, doseq=True) if params else ""
    data = None
    headers = {"X-Api-Key": api_key}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}{query}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read().decode("utf-8", errors="replace")
            if not body:
                return None
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {body}") from exc


def api_get(base_url: str, api_key: str, path: str, params: dict[str, Any] | None = None) -> Any:
    return api_request(base_url, api_key, "GET", path, params=params)


def find_series(series_list: list[dict[str, Any]], query: str) -> dict[str, Any]:
    lowered = query.lower()
    matches = [
        series
        for series in series_list
        if lowered == str(series.get("title", "")).lower()
        or lowered in str(series.get("title", "")).lower()
        or any(lowered in str(title.get("title", "")).lower() for title in series.get("alternateTitles") or [])
    ]
    if not matches:
        raise RuntimeError(f"no series matched {query!r}")
    if len(matches) > 1:
        names = ", ".join(f"{series['id']}:{series['title']}" for series in matches)
        raise RuntimeError(f"multiple series matched {query!r}: {names}")
    return matches[0]


def quality_name(item: dict[str, Any] | None) -> str:
    if not item:
        return "unknown"
    quality = item.get("quality")
    if isinstance(quality, dict):
        return str(quality.get("name") or quality.get("source") or "unknown")
    return str(item.get("name") or "unknown")


def cf_names(items: list[dict[str, Any]] | None) -> list[str]:
    return [str(item.get("name") or item.get("id")) for item in items or []]


def episode_label(season: int, episode: int) -> str:
    return f"S{season:02}E{episode:02}"


def label_regex(season: int, episode: int) -> re.Pattern[str]:
    return re.compile(rf"(?i)\bS{season:02}E{episode:02}\b")


def parse_title(base_url: str, api_key: str, title: str) -> dict[str, Any]:
    return api_get(base_url, api_key, "/api/v3/parse", {"title": title})


def heuristic_score(path: Path) -> tuple[int, list[str], str]:
    name = path.name
    score = 0
    cfs: list[str] = []
    quality = "unknown"
    if re.search(r"(?i)\b1080p\b", name):
        score += 40000
        cfs.append("Local Quality Rank - 1080p")
        quality = "Bluray-1080p" if BLURAY_RE.search(name) else "WEBDL-1080p"
    elif re.search(r"(?i)\b720p\b", name):
        score += 30000
        cfs.append("Local Quality Rank - 720p")
        quality = "Bluray-720p" if BLURAY_RE.search(name) else "WEBDL-720p"
    elif re.search(r"(?i)\b576p\b", name):
        score += 20000
        cfs.append("Local Quality Rank - 576p")
    elif re.search(r"(?i)\b480p\b", name):
        score += 10000
        cfs.append("Local Quality Rank - 480p")
    if LANGUAGE_COMBO_RE.search(name):
        score += 100000
        cfs.insert(0, "Anime Dual Audio")
    if X265_RE.search(name):
        score += 2000
        cfs.append("x265")
    if BLURAY_RE.search(name):
        score += 1500
        cfs.append("Local Anime Source Rank - Bluray")
    return score, cfs, quality


def path_name(path: str) -> str:
    return PurePosixPath(path).name


def candidate_score(base_url: str, api_key: str, path: str) -> tuple[int, list[str], str]:
    parsed = parse_title(base_url, api_key, path_name(path))
    parsed_score = int(parsed.get("customFormatScore") or 0)
    parsed_cfs = cf_names(parsed.get("customFormats"))
    parsed_quality = quality_name(parsed.get("quality"))
    fallback_score, fallback_cfs, fallback_quality = heuristic_score(Path(path_name(path)))
    if fallback_score > parsed_score:
        return fallback_score, fallback_cfs, fallback_quality
    return parsed_score, parsed_cfs, parsed_quality


def parse_episode_list(value: str) -> set[tuple[int, int]]:
    wanted: set[tuple[int, int]] = set()
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        match = re.fullmatch(r"(?i)S?(\d{1,2})E?(\d{1,3})(?:-(?:S?\d{1,2}E?)?(\d{1,3}))?", part)
        if not match:
            raise ValueError(f"invalid episode selector {part!r}")
        season = int(match.group(1))
        start = int(match.group(2))
        end = int(match.group(3) or start)
        for episode in range(start, end + 1):
            wanted.add((season, episode))
    return wanted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("series")
    parser.add_argument("--episodes", required=True, help="comma list, for example S17E02,S17E03-S17E04")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--docker-container", default="sonarr")
    parser.add_argument("--base-url", default="http://127.0.0.1:8989")
    parser.add_argument("--config", default="/opt/media-stack/sonarr/config.xml")
    return parser.parse_args()


def list_video_files(series_path: str, docker_container: str) -> list[str]:
    local_path = Path(series_path)
    if local_path.exists():
        return [
            str(path)
            for path in local_path.rglob("*")
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
        ]

    if not docker_container:
        return []

    result = subprocess.run(
        ["docker", "exec", docker_container, "find", series_path, "-type", "f"],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "docker find failed")
    return [
        line
        for line in result.stdout.splitlines()
        if PurePosixPath(line).suffix.lower() in VIDEO_EXTENSIONS
    ]


def main() -> int:
    args = parse_args()
    wanted = parse_episode_list(args.episodes)
    api_key = read_api_key(args.config)
    series = find_series(api_get(args.base_url, api_key, "/api/v3/series"), args.series)
    episodes = api_get(args.base_url, api_key, "/api/v3/episode", {"seriesId": series["id"]})
    episode_files = api_get(args.base_url, api_key, "/api/v3/episodefile", {"seriesId": series["id"]})
    files_by_id = {
        int(item["id"]): item
        for item in episode_files
        if isinstance(item.get("id"), int)
    }

    planned: list[dict[str, Any]] = []
    series_path = str(series.get("path") or "")
    all_local_files = list_video_files(series_path, args.docker_container)
    for episode in sorted(episodes, key=lambda item: (item.get("seasonNumber") or 0, item.get("episodeNumber") or 0)):
        season = int(episode.get("seasonNumber") or 0)
        number = int(episode.get("episodeNumber") or 0)
        if (season, number) not in wanted:
            continue
        current = files_by_id.get(int(episode.get("episodeFileId") or 0))
        if not current:
            print(f"{episode_label(season, number)}: no tracked current file")
            continue
        current_score = int(current.get("customFormatScore") or 0)
        current_relative = str(current.get("relativePath") or "")
        current_path = str(PurePosixPath(series_path) / current_relative)
        candidates = [
            path
            for path in all_local_files
            if path != current_path and label_regex(season, number).search(path_name(path))
        ]
        scored_candidates = []
        for candidate in candidates:
            try:
                score, cfs, quality = candidate_score(args.base_url, api_key, candidate)
            except Exception as exc:  # noqa: BLE001 - keep evaluating other files.
                scored_candidates.append((0, [], "parse-error", candidate, str(exc)))
                continue
            scored_candidates.append((score, cfs, quality, candidate, ""))
        scored_candidates.sort(key=lambda item: item[0], reverse=True)
        best = scored_candidates[0] if scored_candidates else None
        if not best or best[0] <= current_score:
            print(
                f"{episode_label(season, number)}: no better local candidate "
                f"current_score={current_score}"
            )
            continue
        planned.append(
            {
                "episode": episode_label(season, number),
                "episode_file_id": current.get("id"),
                "current_path": str(current_path),
                "current_score": current_score,
                "current_quality": quality_name(current.get("quality")),
                "current_cfs": cf_names(current.get("customFormats")),
                "candidate_path": str(best[3]),
                "candidate_score": best[0],
                "candidate_quality": best[2],
                "candidate_cfs": best[1],
            }
        )

    print(f"{series['title']} id={series['id']} apply={args.apply}")
    for item in planned:
        print(
            "{episode}: delete tracked {current_quality} score={current_score}; "
            "better local {candidate_quality} score={candidate_score}".format(**item)
        )
        print(f"  current:   {item['current_path']}")
        print(f"  current CFs: {', '.join(item['current_cfs']) or '(none)'}")
        print(f"  candidate: {item['candidate_path']}")
        print(f"  candidate CFs: {', '.join(item['candidate_cfs']) or '(none)'}")

    if args.apply and planned:
        for item in planned:
            api_request(
                args.base_url,
                api_key,
                "DELETE",
                f"/api/v3/episodefile/{item['episode_file_id']}",
                params={"deleteFiles": "true"},
            )
        command = api_request(
            args.base_url,
            api_key,
            "POST",
            "/api/v3/command",
            {"name": "RescanSeries", "seriesId": series["id"]},
        )
        print(f"queued RescanSeries command id={command.get('id') if command else None}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
