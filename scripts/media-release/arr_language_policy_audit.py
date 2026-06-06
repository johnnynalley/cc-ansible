#!/usr/bin/env python3
"""Audit current Sonarr/Radarr files for language-policy mismatches.

Run this on docker-vm. It reads local Arr config.xml files for API keys, queries
localhost APIs only, and optionally uses the bundled Arr ffprobe binaries through
docker exec to inspect actual audio-track language tags. It is read-only and
prints no secrets.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SONARR_URL = "http://127.0.0.1:8989"
RADARR_URL = "http://127.0.0.1:7878"
SONARR_CONFIG = "/opt/media-stack/sonarr/config.xml"
RADARR_CONFIG = "/opt/media-stack/radarr/config.xml"

ANIME_PROFILE_NAMES = {"shows-anime-efficient", "movies-anime-efficient"}
REGULAR_PROFILE_NAMES = {"shows-regular-efficient", "movies-regular-efficient"}
REGULAR_DA_PROFILE_NAMES = {
    "shows-regular-dual-audio-efficient",
    "movies-regular-dual-audio-efficient",
}
DA_CF_NAMES = {"anime dual audio", "regular dual audio"}
ENGLISH_KEYS = {"en"}
UNKNOWN_KEYS = {"", "und", "unknown"}
DUAL_TITLE_RE = re.compile(r"(?i)\b(?:dual[ ._-]?audio|multi[ ._-]?audio|dual\b(?![ ._-]?sub))")

LANGUAGE_KEYS_BY_NAME = {
    "arabic": "ar",
    "chinese": "zh",
    "czech": "cs",
    "danish": "da",
    "dutch": "nl",
    "english": "en",
    "finnish": "fi",
    "french": "fr",
    "german": "de",
    "greek": "el",
    "hindi": "hi",
    "italian": "it",
    "japanese": "ja",
    "korean": "ko",
    "norwegian": "no",
    "polish": "pl",
    "portuguese": "pt",
    "russian": "ru",
    "spanish": "es",
    "swedish": "sv",
    "turkish": "tr",
    "unknown": "unknown",
}

LANGUAGE_KEYS_BY_CODE = {
    "ara": "ar",
    "ar": "ar",
    "chi": "zh",
    "chs": "zh",
    "cht": "zh",
    "cze": "cs",
    "cs": "cs",
    "dan": "da",
    "da": "da",
    "de": "de",
    "deu": "de",
    "dut": "nl",
    "el": "el",
    "en": "en",
    "eng": "en",
    "es": "es",
    "ell": "el",
    "fi": "fi",
    "fin": "fi",
    "fr": "fr",
    "fra": "fr",
    "fre": "fr",
    "ger": "de",
    "gre": "el",
    "hi": "hi",
    "hin": "hi",
    "it": "it",
    "ita": "it",
    "ja": "ja",
    "jpn": "ja",
    "ko": "ko",
    "kor": "ko",
    "nl": "nl",
    "no": "no",
    "nor": "no",
    "pl": "pl",
    "pol": "pl",
    "por": "pt",
    "pt": "pt",
    "ru": "ru",
    "rus": "ru",
    "spa": "es",
    "sv": "sv",
    "swe": "sv",
    "tr": "tr",
    "tur": "tr",
    "und": "unknown",
    "unknown": "unknown",
    "zho": "zh",
}

LANGUAGE_NAMES_BY_KEY = {
    "ar": "Arabic",
    "cs": "Czech",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "fi": "Finnish",
    "fr": "French",
    "hi": "Hindi",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "nl": "Dutch",
    "no": "Norwegian",
    "pl": "Polish",
    "pt": "Portuguese",
    "ru": "Russian",
    "sv": "Swedish",
    "tr": "Turkish",
    "unknown": "Unknown",
    "zh": "Chinese",
}


@dataclass(frozen=True)
class ArrInstance:
    name: str
    base_url: str
    config_path: str
    profiles: set[str]
    probe_container: str
    probe_binary: str


INSTANCES = (
    ArrInstance(
        name="sonarr",
        base_url=SONARR_URL,
        config_path=SONARR_CONFIG,
        profiles=ANIME_PROFILE_NAMES | REGULAR_PROFILE_NAMES | REGULAR_DA_PROFILE_NAMES,
        probe_container="sonarr",
        probe_binary="/app/sonarr/bin/ffprobe",
    ),
    ArrInstance(
        name="radarr",
        base_url=RADARR_URL,
        config_path=RADARR_CONFIG,
        profiles=ANIME_PROFILE_NAMES | REGULAR_PROFILE_NAMES | REGULAR_DA_PROFILE_NAMES,
        probe_container="radarr",
        probe_binary="/app/radarr/bin/ffprobe",
    ),
)


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    api_key = root.findtext("ApiKey")
    if not api_key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return api_key.strip()


def api_get(
    base_url: str,
    api_key: str,
    path: str,
    params: dict[str, Any] | None = None,
    timeout: int = 120,
) -> Any:
    query = "?" + urllib.parse.urlencode(params, doseq=True) if params else ""
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}{query}",
        headers={"X-Api-Key": api_key},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {path}{query} failed: {exc.code} {body}") from exc


def language_key(value: str | None) -> str:
    if value is None:
        return "unknown"
    normalized = value.strip().casefold()
    if not normalized:
        return "unknown"
    return LANGUAGE_KEYS_BY_NAME.get(normalized) or LANGUAGE_KEYS_BY_CODE.get(normalized) or normalized


def language_name(key: str) -> str:
    return LANGUAGE_NAMES_BY_KEY.get(key, key)


def language_names(keys: set[str]) -> list[str]:
    return [language_name(key) for key in sorted(keys) if key and key not in UNKNOWN_KEYS]


def arr_language_keys(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    keys: set[str] = set()
    for item in value:
        if isinstance(item, dict):
            keys.add(language_key(str(item.get("name") or item.get("id") or "")))
        else:
            keys.add(language_key(str(item)))
    return {key for key in keys if key not in UNKNOWN_KEYS}


def cf_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if isinstance(item, dict):
            name = item.get("name") or item.get("id")
        else:
            name = item
        if name:
            names.append(str(name))
    return names


def profile_names_by_id(profiles: list[dict[str, Any]]) -> dict[int, str]:
    return {
        int(profile["id"]): str(profile.get("name") or profile["id"])
        for profile in profiles
        if isinstance(profile.get("id"), int)
    }


def item_original_language(item: dict[str, Any]) -> str:
    value = item.get("originalLanguage")
    if isinstance(value, dict):
        return str(value.get("name") or value.get("id") or "")
    return str(value or "")


def has_anime_signal(app: str, item: dict[str, Any], profile_name: str) -> bool:
    if profile_name in ANIME_PROFILE_NAMES:
        return True
    if app == "sonarr" and str(item.get("seriesType") or "").casefold() == "anime":
        return True
    genres = {str(genre).casefold() for genre in item.get("genres") or []}
    if "anime" in genres:
        return True
    if app == "radarr" and language_key(item_original_language(item)) == "ja" and "animation" in genres:
        return True
    return False


def profile_class(profile_name: str) -> str:
    if profile_name in ANIME_PROFILE_NAMES:
        return "anime"
    if profile_name in REGULAR_DA_PROFILE_NAMES:
        return "regular_dual_audio"
    if profile_name in REGULAR_PROFILE_NAMES:
        return "regular"
    return "other"


def file_path_from_series(series_path: str, episode_file: dict[str, Any]) -> str | None:
    direct = episode_file.get("path")
    if isinstance(direct, str) and direct:
        return direct
    relative = episode_file.get("relativePath")
    if isinstance(relative, str) and relative:
        return f"{series_path.rstrip('/')}/{relative.lstrip('/')}"
    return None


def file_path_from_movie(movie_path: str, movie_file: dict[str, Any] | None) -> str | None:
    if not isinstance(movie_file, dict) or not movie_file:
        return None
    direct = movie_file.get("path")
    if isinstance(direct, str) and direct:
        return direct
    relative = movie_file.get("relativePath")
    if isinstance(relative, str) and relative:
        return f"{movie_path.rstrip('/')}/{relative.lstrip('/')}"
    return None


def probe_audio_languages(instance: ArrInstance, path: str, timeout: int) -> tuple[set[str], list[str]]:
    command = [
        "docker",
        "exec",
        instance.probe_container,
        instance.probe_binary,
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream_tags=language,title",
        "-of",
        "json",
        path,
    ]
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return set(), [f"ffprobe timed out after {timeout}s"]
    except OSError as exc:
        return set(), [f"ffprobe failed to start: {exc}"]
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return set(), [detail[:300] or f"ffprobe exited {result.returncode}"]
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        return set(), [f"ffprobe JSON parse failed: {exc}"]
    keys: set[str] = set()
    for stream in payload.get("streams") or []:
        tags = stream.get("tags") if isinstance(stream, dict) else None
        if isinstance(tags, dict):
            keys.add(language_key(str(tags.get("language") or "")))
    return {key for key in keys if key not in UNKNOWN_KEYS}, []


def title_claims_dual_audio(title: str) -> bool:
    return DUAL_TITLE_RE.search(title) is not None


def effective_languages(row: dict[str, Any]) -> set[str]:
    probed = row.get("probe_languages") or []
    if probed:
        return set(probed)
    return set(row.get("arr_languages") or [])


def classify_flags(row: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    original_key = row["original_key"]
    languages = effective_languages(row)
    profile = row["profile_class"]
    cf_lower = {name.casefold() for name in row["custom_formats"]}
    has_da_cf = bool(cf_lower & DA_CF_NAMES)
    has_title_da = title_claims_dual_audio(row["source_title"])
    has_english = bool(languages & ENGLISH_KEYS)
    known_non_english = {key for key in languages if key not in ENGLISH_KEYS and key not in UNKNOWN_KEYS}

    if row["probe_errors"]:
        flags.append("probe_error")
    if row["probe_languages"] and row["arr_languages"] and set(row["probe_languages"]) != set(row["arr_languages"]):
        flags.append("arr_probe_language_mismatch")
    if original_key not in UNKNOWN_KEYS and languages and original_key not in languages:
        flags.append("missing_original_audio")

    if profile == "regular_dual_audio" and not has_english:
        flags.append("dual_audio_profile_missing_english")
    if profile == "regular_dual_audio" and original_key not in UNKNOWN_KEYS and original_key in languages and has_english:
        flags.append("regular_original_plus_english_ok")

    if profile == "regular" and row["original_key"] == "en" and known_non_english:
        flags.append("english_regular_has_foreign_audio")
    if profile == "regular" and row["original_key"] != "en" and row["original_key"] not in UNKNOWN_KEYS:
        flags.append("non_english_regular_profile")

    if profile == "anime" and has_da_cf and not has_english:
        flags.append("anime_da_cf_without_english")
    if profile == "anime" and has_title_da and not has_english:
        flags.append("title_claims_da_without_english")
    if profile == "anime" and not has_english:
        flags.append("anime_original_only")
    if profile == "anime" and has_english and original_key not in UNKNOWN_KEYS and original_key in languages:
        flags.append("anime_original_plus_english_ok")

    if original_key not in UNKNOWN_KEYS and original_key in languages and not has_english:
        extra = known_non_english - {original_key}
        if extra:
            flags.append("original_plus_non_english_no_english")

    return flags


def row_sort_key(row: dict[str, Any]) -> tuple[int, str, str]:
    priority = 0
    flags = set(row["flags"])
    high_priority = {
        "dual_audio_profile_missing_english",
        "anime_da_cf_without_english",
        "title_claims_da_without_english",
        "original_plus_non_english_no_english",
        "missing_original_audio",
        "non_english_regular_profile",
    }
    if flags & high_priority:
        priority = -2
    elif "anime_original_only" in flags:
        priority = -1
    return (priority, row["app"], row["title"])


def compact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "app": row["app"],
        "title": row["title"],
        "season_episode": row.get("season_episode"),
        "year": row.get("year"),
        "profile": row["profile_name"],
        "original_language": row["original_language"],
        "arr_languages": language_names(set(row["arr_languages"])),
        "probe_languages": language_names(set(row["probe_languages"])),
        "score": row.get("score"),
        "custom_formats": row["custom_formats"],
        "flags": row["flags"],
        "source_title": row["source_title"],
        "path": row["path"],
        "probe_errors": row["probe_errors"],
    }


def audit_sonarr(instance: ArrInstance, api_key: str, args: argparse.Namespace) -> list[dict[str, Any]]:
    profiles = profile_names_by_id(api_get(instance.base_url, api_key, "/api/v3/qualityprofile"))
    series_list = api_get(instance.base_url, api_key, "/api/v3/series")
    title_re = re.compile(args.title_regex, flags=re.IGNORECASE) if args.title_regex else None
    rows: list[dict[str, Any]] = []
    for index, series in enumerate(series_list, start=1):
        if title_re and not title_re.search(str(series.get("title") or "")):
            continue
        series_id = int(series["id"])
        profile_name = profiles.get(int(series.get("qualityProfileId") or 0), "unknown")
        current_class = profile_class(profile_name)
        if not args.include_regular and current_class == "regular" and language_key(item_original_language(series)) == "en":
            continue
        if args.progress and index % 25 == 0:
            print(f"scanned Sonarr series metadata {index}/{len(series_list)}", file=sys.stderr, flush=True)
        episode_files = api_get(instance.base_url, api_key, "/api/v3/episodefile", {"seriesId": series_id})
        for episode_file in episode_files:
            path = file_path_from_series(str(series.get("path") or ""), episode_file)
            if not path:
                continue
            source_title = str(episode_file.get("sceneName") or episode_file.get("releaseGroup") or Path(path).name)
            arr_languages = arr_language_keys(episode_file.get("languages"))
            probe_languages: set[str] = set()
            probe_errors: list[str] = []
            if args.probe:
                probe_languages, probe_errors = probe_audio_languages(instance, path, args.probe_timeout)
            row = {
                "app": "sonarr",
                "title": str(series.get("title") or series_id),
                "season_episode": "",
                "year": series.get("year"),
                "profile_name": profile_name,
                "profile_class": current_class,
                "anime_signal": has_anime_signal("sonarr", series, profile_name),
                "original_language": item_original_language(series),
                "original_key": language_key(item_original_language(series)),
                "arr_languages": sorted(arr_languages),
                "probe_languages": sorted(probe_languages),
                "custom_formats": cf_names(episode_file.get("customFormats")),
                "score": episode_file.get("customFormatScore"),
                "source_title": source_title,
                "path": path,
                "probe_errors": probe_errors,
            }
            row["flags"] = classify_flags(row)
            rows.append(row)
    return rows


def audit_radarr(instance: ArrInstance, api_key: str, args: argparse.Namespace) -> list[dict[str, Any]]:
    profiles = profile_names_by_id(api_get(instance.base_url, api_key, "/api/v3/qualityprofile"))
    movies = api_get(instance.base_url, api_key, "/api/v3/movie")
    title_re = re.compile(args.title_regex, flags=re.IGNORECASE) if args.title_regex else None
    rows: list[dict[str, Any]] = []
    for index, movie in enumerate(movies, start=1):
        if title_re and not title_re.search(str(movie.get("title") or "")):
            continue
        movie_file = movie.get("movieFile")
        if not isinstance(movie_file, dict) or not movie_file:
            continue
        profile_name = profiles.get(int(movie.get("qualityProfileId") or 0), "unknown")
        current_class = profile_class(profile_name)
        if not args.include_regular and current_class == "regular" and language_key(item_original_language(movie)) == "en":
            continue
        if args.progress and index % 25 == 0:
            print(f"scanned Radarr movie metadata {index}/{len(movies)}", file=sys.stderr, flush=True)
        path = file_path_from_movie(str(movie.get("path") or ""), movie_file)
        if not path:
            continue
        source_title = str(movie_file.get("sceneName") or movie_file.get("releaseGroup") or Path(path).name)
        arr_languages = arr_language_keys(movie_file.get("languages"))
        probe_languages: set[str] = set()
        probe_errors: list[str] = []
        if args.probe:
            probe_languages, probe_errors = probe_audio_languages(instance, path, args.probe_timeout)
        row = {
            "app": "radarr",
            "title": str(movie.get("title") or movie.get("id")),
            "season_episode": None,
            "year": movie.get("year"),
            "profile_name": profile_name,
            "profile_class": current_class,
            "anime_signal": has_anime_signal("radarr", movie, profile_name),
            "original_language": item_original_language(movie),
            "original_key": language_key(item_original_language(movie)),
            "arr_languages": sorted(arr_languages),
            "probe_languages": sorted(probe_languages),
            "custom_formats": cf_names(movie_file.get("customFormats")),
            "score": movie_file.get("customFormatScore"),
            "source_title": source_title,
            "path": path,
            "probe_errors": probe_errors,
        }
        row["flags"] = classify_flags(row)
        rows.append(row)
    return rows


def audit(args: argparse.Namespace) -> dict[str, Any]:
    all_rows: list[dict[str, Any]] = []
    for instance in INSTANCES:
        if args.app != "all" and args.app != instance.name:
            continue
        api_key = read_api_key(instance.config_path)
        if instance.name == "sonarr":
            all_rows.extend(audit_sonarr(instance, api_key, args))
        else:
            all_rows.extend(audit_radarr(instance, api_key, args))

    flag_counts = collections.Counter(flag for row in all_rows for flag in row["flags"])
    profile_counts = collections.Counter(row["profile_name"] for row in all_rows)
    suspect_rows = [
        row
        for row in all_rows
        if set(row["flags"])
        - {
            "anime_original_only",
            "anime_original_plus_english_ok",
            "regular_original_plus_english_ok",
            "english_regular_has_foreign_audio",
        }
    ]
    suspect_group_counts: collections.Counter[tuple[str, str, str, str, str]] = collections.Counter()
    for row in suspect_rows:
        suspect_group_counts[
            (
                row["app"],
                row["title"],
                row["profile_name"],
                row["original_language"],
                ",".join(row["flags"]),
            )
        ] += 1
    anime_original_only = [row for row in all_rows if "anime_original_only" in row["flags"]]
    report = {
        "probe_enabled": args.probe,
        "rows_scanned": len(all_rows),
        "profile_counts": dict(profile_counts),
        "flag_counts": dict(flag_counts),
        "suspect_count": len(suspect_rows),
        "suspect_groups": [
            {
                "app": app,
                "title": title,
                "profile": profile,
                "original_language": original_language,
                "flags": flags.split(",") if flags else [],
                "count": count,
            }
            for (app, title, profile, original_language, flags), count in suspect_group_counts.most_common(
                args.group_limit
            )
        ],
        "suspects": [compact_row(row) for row in sorted(suspect_rows, key=row_sort_key)[: args.limit]],
        "anime_original_only_count": len(anime_original_only),
        "anime_original_only_samples": [
            compact_row(row) for row in sorted(anime_original_only, key=row_sort_key)[: args.limit]
        ],
    }
    if args.include_all:
        report["rows"] = [compact_row(row) for row in sorted(all_rows, key=row_sort_key)]
    return report


def print_text(report: dict[str, Any]) -> None:
    print(f"probe_enabled={report['probe_enabled']} rows_scanned={report['rows_scanned']}")
    print(f"profile_counts={report['profile_counts']}")
    print(f"flag_counts={report['flag_counts']}")
    print(f"suspect_count={report['suspect_count']}")
    if report["suspect_groups"]:
        print("suspect_groups:")
        for group in report["suspect_groups"]:
            print(
                f"- {group['app']} | {group['title']} | count={group['count']} "
                f"profile={group['profile']} orig={group['original_language'] or 'Unknown'} "
                f"flags={','.join(group['flags'])}"
            )
    if report["suspects"]:
        print("suspects:")
        for row in report["suspects"]:
            label = row["title"]
            if row.get("year"):
                label += f" ({row['year']})"
            arr_lang = "+".join(row["arr_languages"]) or "Unknown"
            probe_lang = "+".join(row["probe_languages"]) or "Unknown"
            flags = ",".join(row["flags"])
            print(
                f"- {row['app']} | {label} | profile={row['profile']} "
                f"orig={row['original_language'] or 'Unknown'} arr={arr_lang} probe={probe_lang} "
                f"score={row['score']} flags={flags}"
            )
            print(f"  source={row['source_title']}")
            print(f"  path={row['path']}")
            if row["probe_errors"]:
                print(f"  probe_errors={'; '.join(row['probe_errors'])}")
    print(f"anime_original_only_count={report['anime_original_only_count']}")
    if report["anime_original_only_samples"]:
        print("anime_original_only_samples:")
        for row in report["anime_original_only_samples"]:
            arr_lang = "+".join(row["arr_languages"]) or "Unknown"
            probe_lang = "+".join(row["probe_languages"]) or "Unknown"
            print(
                f"- {row['app']} | {row['title']} | profile={row['profile']} "
                f"orig={row['original_language'] or 'Unknown'} arr={arr_lang} probe={probe_lang} "
                f"score={row['score']} source={row['source_title']}"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", choices=["sonarr", "radarr", "all"], default="all")
    parser.add_argument("--probe", action="store_true", help="inspect actual audio-track tags with ffprobe")
    parser.add_argument("--probe-timeout", type=int, default=15)
    parser.add_argument("--title-regex", help="only audit media whose Sonarr/Radarr title matches this regex")
    parser.add_argument(
        "--include-regular",
        action="store_true",
        help="also scan English-original regular-profile files; slower but broader",
    )
    parser.add_argument("--include-all", action="store_true", help="include all scanned rows in JSON output")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--group-limit", type=int, default=40)
    parser.add_argument("--progress", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit(args)
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        print_text(report)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
