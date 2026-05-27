#!/usr/bin/env python3
"""Check live Sonarr anime release-selection expectations.

Run this on docker-vm. It reads Sonarr's local config.xml for the API key,
queries localhost only, and prints no secrets.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any


SONARR_URL = "http://127.0.0.1:8989"
SONARR_CONFIG = "/opt/media-stack/sonarr/config.xml"
ANIME_PROFILE_NAME = "shows-anime-efficient"
DUAL_AUDIO_CF_NAME = "Anime Dual Audio"
X265_CF_NAME = "x265"
QUALITY_RANK_PREFIX = "Local Quality Rank - "
SOURCE_RANK_CF_NAME = "Local Anime Source Rank - Bluray"
EXPECTED_DA_SCORE = 100000
EXPECTED_X265_SCORE = 5000
EXPECTED_SOURCE_RANK_SCORE = 0
EXPECTED_CUTOFF_SCORE = 146979
EXPECTED_QUALITY_SCORES = {
    "480p": 10000,
    "576p": 20000,
    "720p": 30000,
    "1080p": 40000,
}


@dataclass(frozen=True)
class SpecResult:
    name: str
    implementation: str
    required: bool
    negate: bool
    matched: bool
    passed: bool


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def api_get(api_key: str, path: str, params: dict[str, Any] | None = None) -> Any:
    query = ""
    if params:
        query = "?" + urllib.parse.urlencode(params, doseq=True)
    url = f"{SONARR_URL.rstrip('/')}{path}{query}"
    request = urllib.request.Request(url, headers={"X-Api-Key": api_key})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {path} failed: {exc.code} {body}") from exc


def regex_from_spec(spec: dict[str, Any]) -> str | None:
    for field in spec.get("fields") or []:
        if field.get("name") == "value" and field.get("value"):
            return str(field["value"])
    return None


def regex_matches(pattern: str, value: str) -> bool:
    return re.search(pattern, value, flags=re.IGNORECASE) is not None


def evaluate_spec(spec: dict[str, Any], title: str) -> SpecResult:
    implementation = str(spec.get("implementation") or "")
    pattern = regex_from_spec(spec)
    matched = False

    if implementation in {"ReleaseTitleSpecification", "ReleaseTitleRegexSpecification"}:
        matched = regex_matches(pattern or r"$.", title)
    elif implementation == "LanguageSpecification":
        # The live DA CF's language specs are optional. Sonarr evaluates them
        # against parsed release/file language metadata, not only title text.
        matched = False
    elif implementation == "SourceSpecification":
        matched = regex_matches(pattern or r"$.", title) if pattern else False

    required = bool(spec.get("required"))
    negate = bool(spec.get("negate"))
    passed = (not matched) if negate else matched
    if not required:
        passed = True

    return SpecResult(
        name=str(spec.get("name") or implementation),
        implementation=implementation,
        required=required,
        negate=negate,
        matched=matched,
        passed=passed,
    )


def custom_format_matches(cf: dict[str, Any], title: str) -> tuple[bool, list[SpecResult]]:
    results = [evaluate_spec(spec, title) for spec in cf.get("specifications") or []]
    required_results = [result for result in results if result.required]
    return all(result.passed for result in required_results), results


def find_by_name(items: list[dict[str, Any]], name: str) -> dict[str, Any]:
    matches = [item for item in items if item.get("name") == name]
    if not matches:
        raise RuntimeError(f"missing {name!r}")
    if len(matches) > 1:
        raise RuntimeError(f"multiple matches for {name!r}")
    return matches[0]


def profile_score(profile: dict[str, Any], cf_id: int) -> int | None:
    for item in profile.get("formatItems") or []:
        value = item.get("format")
        if isinstance(value, dict):
            value = value.get("id")
        if value is None:
            value = item.get("customFormatId")
        try:
            item_id = int(value)
        except (TypeError, ValueError):
            continue
        if item_id == cf_id:
            return int(item.get("score") or 0)
    return None


def profile_format_rows(
    profile: dict[str, Any], custom_formats: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    cf_by_id = {
        int(cf["id"]): cf
        for cf in custom_formats
        if isinstance(cf.get("id"), int)
    }
    rows: list[dict[str, Any]] = []
    for item in profile.get("formatItems") or []:
        value = item.get("format")
        if isinstance(value, dict):
            value = value.get("id")
        if value is None:
            value = item.get("customFormatId")
        try:
            cf_id = int(value)
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "id": cf_id,
                "name": str(cf_by_id.get(cf_id, {}).get("name") or f"id:{cf_id}"),
                "score": int(item.get("score") or 0),
            }
        )
    return rows


def allowed_quality_group(profile: dict[str, Any]) -> dict[str, Any] | None:
    allowed_groups = [
        item
        for item in profile.get("items") or []
        if item.get("allowed") and item.get("items")
    ]
    if len(allowed_groups) != 1:
        return None
    return allowed_groups[0]


def grouped_quality_resolutions(group: dict[str, Any] | None) -> set[int]:
    if not group:
        return set()
    resolutions: set[int] = set()
    for item in group.get("items") or []:
        quality = item.get("quality") or {}
        resolution = quality.get("resolution")
        if isinstance(resolution, int):
            resolutions.add(resolution)
    return resolutions


def parse_title(api_key: str, title: str) -> dict[str, Any]:
    return api_get(api_key, "/api/v3/parse", {"title": title})


def print_header(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


def main() -> int:
    api_key = read_api_key(SONARR_CONFIG)
    custom_formats = api_get(api_key, "/api/v3/customformat")
    profiles = api_get(api_key, "/api/v3/qualityprofile")
    naming = api_get(api_key, "/api/v3/config/naming")
    series = api_get(api_key, "/api/v3/series")

    profile = find_by_name(profiles, ANIME_PROFILE_NAME)
    dual_audio_cf = find_by_name(custom_formats, DUAL_AUDIO_CF_NAME)
    x265_cf = find_by_name(custom_formats, X265_CF_NAME)
    source_rank_cf = find_by_name(custom_formats, SOURCE_RANK_CF_NAME)

    checks: list[tuple[str, bool, str]] = []
    da_score = profile_score(profile, int(dual_audio_cf["id"]))
    x265_score = profile_score(profile, int(x265_cf["id"]))
    source_rank_score = profile_score(profile, int(source_rank_cf["id"]))
    checks.append(("DA score is +100000", da_score == EXPECTED_DA_SCORE, str(da_score)))
    checks.append(("x265 score is +5000", x265_score == EXPECTED_X265_SCORE, str(x265_score)))
    checks.append(
        (
            "Bluray source rank is zero",
            source_rank_score == EXPECTED_SOURCE_RANK_SCORE,
            str(source_rank_score),
        )
    )
    checks.append(("minimum score is 0", profile.get("minFormatScore") == 0, str(profile.get("minFormatScore"))))
    checks.append(
        (
            "minimum upgrade score is 1",
            profile.get("minUpgradeFormatScore") == 1,
            str(profile.get("minUpgradeFormatScore")),
        )
    )
    checks.append(
        (
            "cutoff score is at least the efficient-profile maximum",
            int(profile.get("cutoffFormatScore") or 0) >= EXPECTED_CUTOFF_SCORE,
            str(profile.get("cutoffFormatScore")),
        )
    )

    rows = profile_format_rows(profile, custom_formats)
    quality_scores: dict[str, int] = {}
    for row in rows:
        name = row["name"]
        if name.startswith(QUALITY_RANK_PREFIX):
            quality_scores[name.removeprefix(QUALITY_RANK_PREFIX)] = int(row["score"])

    for quality, expected_score in EXPECTED_QUALITY_SCORES.items():
        actual = quality_scores.get(quality)
        checks.append((f"{quality} quality rank is +{expected_score}", actual == expected_score, str(actual)))

    quality_group = allowed_quality_group(profile)
    grouped_resolutions = grouped_quality_resolutions(quality_group)
    checks.append(
        (
            "anime qualities are in one native quality group",
            quality_group is not None,
            str(quality_group.get("name") if quality_group else None),
        )
    )
    checks.append(
        (
            "native quality group covers 480/576/720/1080",
            grouped_resolutions == {480, 576, 720, 1080},
            ",".join(str(value) for value in sorted(grouped_resolutions)),
        )
    )

    core_names = {
        DUAL_AUDIO_CF_NAME,
        X265_CF_NAME,
        SOURCE_RANK_CF_NAME,
        *(f"{QUALITY_RANK_PREFIX}{quality}" for quality in EXPECTED_QUALITY_SCORES),
    }
    other_positive_rows = [
        row for row in rows if row["score"] > 0 and row["name"] not in core_names
    ]
    max_other_positive = max((row["score"] for row in other_positive_rows), default=0)
    max_other_names = sorted(
        row["name"] for row in other_positive_rows if row["score"] == max_other_positive
    )
    web_tier_rows = [
        row for row in other_positive_rows if "web tier" in row["name"].lower()
    ]
    max_web_tier_score = max((row["score"] for row in web_tier_rows), default=0)
    max_web_tier_names = sorted(
        row["name"] for row in web_tier_rows if row["score"] == max_web_tier_score
    )
    lowest_da_score = EXPECTED_DA_SCORE + min(EXPECTED_QUALITY_SCORES.values())
    strongest_non_da_score = (
        max(EXPECTED_QUALITY_SCORES.values()) + EXPECTED_X265_SCORE + max_other_positive
    )
    high_da_score = EXPECTED_DA_SCORE + EXPECTED_QUALITY_SCORES["1080p"]
    high_da_bluray_x264_score = high_da_score + EXPECTED_SOURCE_RANK_SCORE
    high_da_web_x264_best_score = high_da_score + max_web_tier_score
    high_da_web_x265_best_score = high_da_score + EXPECTED_X265_SCORE + max_web_tier_score
    lower_da_best_score = (
        EXPECTED_DA_SCORE
        + EXPECTED_QUALITY_SCORES["720p"]
        + EXPECTED_X265_SCORE
        + EXPECTED_SOURCE_RANK_SCORE
        + max_other_positive
    )
    checks.append(
        (
            "lowest DA quality beats strongest single-tier non-DA",
            lowest_da_score > strongest_non_da_score,
            f"{lowest_da_score}>{strongest_non_da_score}; max other +{max_other_positive} {max_other_names}",
        )
    )
    checks.append(
        (
            "1080p DA beats 720p DA + x265 + top single tier",
            high_da_score > lower_da_best_score,
            f"{high_da_score}>{lower_da_best_score}; max other +{max_other_positive} {max_other_names}",
        )
    )
    checks.append(
        (
            "1080p DA Web x265 + best web tier beats 1080p DA Bluray x264 without group",
            high_da_web_x265_best_score > high_da_bluray_x264_score,
            f"{high_da_web_x265_best_score}>{high_da_bluray_x264_score}; max web +{max_web_tier_score} {max_web_tier_names}",
        )
    )

    anime_episode_format = str(naming.get("animeEpisodeFormat") or "")
    checks.append(
        (
            "anime rename format preserves audio languages",
            "MediaInfo AudioLanguages" in anime_episode_format,
            anime_episode_format,
        )
    )
    checks.append(
        (
            "anime rename format preserves video codec",
            "MediaInfo VideoCodec" in anime_episode_format,
            anime_episode_format,
        )
    )
    checks.append(
        (
            "Sonarr renaming is enabled",
            bool(naming.get("renameEpisodes")),
            str(naming.get("renameEpisodes")),
        )
    )

    profile_names_by_id = {
        int(item["id"]): str(item.get("name") or item["id"])
        for item in profiles
        if isinstance(item.get("id"), int)
    }
    series_profile_counts: dict[str, int] = {}
    unknown_profile_count = 0
    for item in series:
        profile_id = item.get("qualityProfileId")
        name = profile_names_by_id.get(profile_id) if isinstance(profile_id, int) else None
        if name is None:
            unknown_profile_count += 1
            name = str(profile_id)
        series_profile_counts[name] = series_profile_counts.get(name, 0) + 1
    checks.append(
        (
            "all series reference known quality profiles",
            unknown_profile_count == 0,
            str(series_profile_counts),
        )
    )

    print(f"Sonarr profile: {ANIME_PROFILE_NAME} (id={profile.get('id')})")
    for label, passed, detail in checks:
        print(f"{'PASS' if passed else 'FAIL'}: {label} ({detail})")
    print(f"series profile counts: {series_profile_counts}")

    samples = [
        ("JA+EN x265", "[EMBER] Jujutsu Kaisen S3 - 11 [JA+EN] [x265].mkv", True, True),
        ("EN+JA x265", "[EMBER] Jujutsu Kaisen S3 - 11 [EN+JA] [x265].mkv", True, True),
        ("JA+KO+EN x265", "[EMBER] Jujutsu Kaisen S3 - 11 [JA+KO+EN] [x265].mkv", True, True),
        ("KO+EN x265", "[EMBER] Jujutsu Kaisen S3 - 11 [KO+EN] [x265].mkv", True, True),
        ("single JA only", "[EMBER] Jujutsu Kaisen S3 - 11 [JA] [x265].mkv", False, True),
        ("single EN only", "[EMBER] Jujutsu Kaisen S3 - 11 [EN] [x265].mkv", False, True),
        ("generic Dual-Audio", "[EMBER] Jujutsu Kaisen S3 - 11 [Dual-Audio] [x265].mkv", True, True),
        (
            "Dual-Audio with Eng-Sub",
            "[Judas] Bleach 056-111 [BD 1080p][HEVC x265 10bit][Dual-Audio][Eng-Sub]",
            True,
            True,
        ),
        (
            "Eng-Sub without DA marker",
            "[Judas] Bleach 056-111 [BD 1080p][HEVC x265 10bit][Eng-Sub]",
            False,
            True,
        ),
        ("x264 DA", "[EMBER] Jujutsu Kaisen S3 - 11 [JA+EN] [x264].mkv", True, False),
    ]

    print_header("Custom Format Title Checks")
    all_passed = all(passed for _, passed, _ in checks)
    for label, title, expect_da, expect_x265 in samples:
        da_matches, da_results = custom_format_matches(dual_audio_cf, title)
        x265_matches, x265_results = custom_format_matches(x265_cf, title)
        da_ok = da_matches == expect_da
        x265_ok = x265_matches == expect_x265
        all_passed = all_passed and da_ok and x265_ok
        print(f"{'PASS' if da_ok and x265_ok else 'FAIL'}: {label}")
        print(f"  title: {title}")
        print(f"  DA expected={expect_da} actual={da_matches}")
        for result in da_results:
            if result.required:
                print(
                    "    DA spec {name}: required negate={negate} matched={matched} passed={passed}".format(
                        name=result.name,
                        negate=result.negate,
                        matched=result.matched,
                        passed=result.passed,
                    )
                )
        print(f"  x265 expected={expect_x265} actual={x265_matches}")
        for result in x265_results:
            if result.required:
                print(
                    "    x265 spec {name}: required negate={negate} matched={matched} passed={passed}".format(
                        name=result.name,
                        negate=result.negate,
                        matched=result.matched,
                        passed=result.passed,
                    )
                )

    print_header("Sonarr Parse Smoke Checks")
    for _, title, _, _ in samples[:4]:
        parsed = parse_title(api_key, title)
        quality = ((parsed.get("quality") or {}).get("quality") or {}).get("name")
        languages = parsed.get("languages") or parsed.get("language") or []
        print(f"{title}")
        print(f"  parsed quality={quality} languages={languages}")

    print_header("Result")
    if all_passed:
        print("PASS: live Sonarr profile scores and title-side CF checks match expectations")
        return 0
    print("FAIL: one or more live Sonarr expectations did not match")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
