#!/usr/bin/env python3
"""Read-only Radarr replacement-candidate audit for language policy.

Run this on docker-vm. It reads Radarr's local config.xml for the API key,
queries localhost only, and performs Radarr interactive release searches without
grabbing releases. Results are based on Radarr's parsed release metadata, not
downloaded-file ffprobe tags.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any


RADARR_URL = "http://127.0.0.1:7878"
RADARR_CONFIG = "/opt/media-stack/radarr/config.xml"
ENGLISH_KEYS = {"en"}
UNKNOWN_KEYS = {"", "und", "unknown"}

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


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    api_key = root.findtext("ApiKey")
    if not api_key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return api_key.strip()


def api_get(api_key: str, path: str, params: dict[str, Any] | None = None, timeout: int = 180) -> Any:
    query = "?" + urllib.parse.urlencode(params, doseq=True) if params else ""
    request = urllib.request.Request(
        f"{RADARR_URL.rstrip('/')}{path}{query}",
        headers={"X-Api-Key": api_key},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {path}{query} failed: {exc.code} {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GET {path}{query} failed: {exc.reason}") from exc


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


def item_original_language(item: dict[str, Any]) -> str:
    value = item.get("originalLanguage")
    if isinstance(value, dict):
        return str(value.get("name") or value.get("id") or "")
    return str(value or "")


def custom_format_names(value: Any) -> list[str]:
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


def release_rejections(release: dict[str, Any]) -> list[str]:
    values = release.get("rejections")
    if not isinstance(values, list):
        return []
    reasons: list[str] = []
    for value in values:
        if isinstance(value, dict):
            reason = value.get("reason") or value.get("type")
        else:
            reason = value
        if reason:
            reasons.append(str(reason))
    return reasons


def release_score(release: dict[str, Any]) -> int:
    value = release.get("customFormatScore")
    if value is None:
        value = release.get("score")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def release_quality_name(release: dict[str, Any]) -> str:
    quality = release.get("quality")
    if isinstance(quality, dict):
        inner = quality.get("quality")
        if isinstance(inner, dict):
            return str(inner.get("name") or "")
    return ""


def release_size_mib(release: dict[str, Any]) -> float | None:
    size = release.get("size")
    try:
        return int(size) / 1024 / 1024
    except (TypeError, ValueError):
        return None


def language_flags(original_key: str, languages: set[str]) -> list[str]:
    flags: list[str] = []
    has_english = bool(languages & ENGLISH_KEYS)
    if original_key not in UNKNOWN_KEYS and original_key not in languages:
        flags.append("missing_original_audio")
    if not has_english:
        flags.append("missing_english_audio")
    if original_key not in UNKNOWN_KEYS and original_key in languages and has_english:
        flags.append("original_plus_english")
    return flags


def compact_release(release: dict[str, Any], original_key: str) -> dict[str, Any]:
    languages = arr_language_keys(release.get("languages"))
    return {
        "title": release.get("title"),
        "indexer": release.get("indexer"),
        "download_protocol": release.get("downloadProtocol"),
        "quality": release_quality_name(release),
        "score": release_score(release),
        "languages": language_names(languages),
        "flags": language_flags(original_key, languages),
        "custom_formats": custom_format_names(release.get("customFormats")),
        "approved": bool(release.get("approved")),
        "rejections": release_rejections(release),
        "size_mib": release_size_mib(release),
    }


def sorted_releases(releases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        releases,
        key=lambda item: (
            bool(item.get("approved")),
            release_score(item),
            -(release_size_mib(item) or 0),
        ),
        reverse=True,
    )


def select_movies(api_key: str, args: argparse.Namespace) -> list[dict[str, Any]]:
    movies = api_get(api_key, "/api/v3/movie", timeout=args.timeout)
    wanted_ids = {int(value) for value in args.movie_id}
    title_re = re.compile(args.title_regex, flags=re.IGNORECASE) if args.title_regex else None
    selected: list[dict[str, Any]] = []
    for movie in movies:
        movie_id = int(movie.get("id") or 0)
        title = str(movie.get("title") or "")
        if wanted_ids and movie_id not in wanted_ids:
            continue
        if title_re and not title_re.search(title):
            continue
        if not wanted_ids and not title_re:
            continue
        selected.append(movie)
    return selected[: args.max_movies]


def audit_movie(api_key: str, movie: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    movie_id = int(movie["id"])
    original_language = item_original_language(movie)
    original_key = language_key(original_language)
    movie_file = movie.get("movieFile") if isinstance(movie.get("movieFile"), dict) else {}
    current_languages = arr_language_keys(movie_file.get("languages"))
    try:
        releases = api_get(api_key, "/api/v3/release", {"movieId": movie_id}, timeout=args.timeout)
        search_error = None
    except RuntimeError as exc:
        releases = []
        search_error = str(exc)

    releases = sorted_releases([release for release in releases if isinstance(release, dict)])
    compact = [compact_release(release, original_key) for release in releases]
    policy_candidates = [
        release for release in compact if "original_plus_english" in release["flags"]
    ]
    approved_policy_candidates = [
        release for release in policy_candidates if release["approved"] and not release["rejections"]
    ]
    return {
        "id": movie_id,
        "tmdb_id": movie.get("tmdbId"),
        "title": movie.get("title"),
        "year": movie.get("year"),
        "profile_id": movie.get("qualityProfileId"),
        "original_language": original_language,
        "current_languages": language_names(current_languages),
        "current_flags": language_flags(original_key, current_languages),
        "current_source": movie_file.get("sceneName") or movie_file.get("releaseGroup"),
        "search_error": search_error,
        "release_count": len(releases),
        "policy_candidate_count": len(policy_candidates),
        "approved_policy_candidate_count": len(approved_policy_candidates),
        "top_releases": compact[: args.release_limit],
        "top_policy_candidates": policy_candidates[: args.release_limit],
        "top_approved_policy_candidates": approved_policy_candidates[: args.release_limit],
    }


def audit(args: argparse.Namespace) -> dict[str, Any]:
    api_key = read_api_key(args.config)
    movies = select_movies(api_key, args)
    return {
        "movie_count": len(movies),
        "movies": [audit_movie(api_key, movie, args) for movie in movies],
    }


def print_release(prefix: str, release: dict[str, Any]) -> None:
    langs = "+".join(release["languages"]) or "Unknown"
    cfs = ", ".join(release["custom_formats"]) or "none"
    rejections = "; ".join(release["rejections"]) or "none"
    print(
        f"{prefix} score={release['score']} approved={release['approved']} "
        f"quality={release['quality'] or 'Unknown'} langs={langs} "
        f"indexer={release['indexer'] or 'Unknown'}"
    )
    print(f"    title={release['title']}")
    print(f"    cfs={cfs}")
    print(f"    rejections={rejections}")


def print_text(report: dict[str, Any]) -> None:
    print(f"movie_count={report['movie_count']}")
    for movie in report["movies"]:
        current_langs = "+".join(movie["current_languages"]) or "Unknown"
        print()
        print(
            f"{movie['title']} ({movie['year']}) id={movie['id']} tmdb={movie['tmdb_id']} "
            f"orig={movie['original_language'] or 'Unknown'} current={current_langs} "
            f"current_flags={','.join(movie['current_flags']) or 'none'}"
        )
        if movie["search_error"]:
            print(f"  search_error={movie['search_error']}")
            continue
        print(
            f"  releases={movie['release_count']} policy_candidates={movie['policy_candidate_count']} "
            f"approved_policy_candidates={movie['approved_policy_candidate_count']}"
        )
        for release in movie["top_approved_policy_candidates"]:
            print_release("  approved_policy", release)
        if not movie["top_approved_policy_candidates"]:
            for release in movie["top_policy_candidates"]:
                print_release("  policy", release)
        if movie["top_releases"]:
            print_release("  top_overall", movie["top_releases"][0])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=RADARR_CONFIG)
    parser.add_argument("--movie-id", type=int, action="append", default=[])
    parser.add_argument("--title-regex")
    parser.add_argument("--max-movies", type=int, default=40)
    parser.add_argument("--release-limit", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=180)
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
