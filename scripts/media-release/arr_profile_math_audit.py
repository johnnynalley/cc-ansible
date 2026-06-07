#!/usr/bin/env python3
"""Audit Arr efficient-profile release-policy score math.

Run this on docker-vm. It reads local Sonarr/Radarr API keys, checks the
efficient profiles, and exits non-zero if the configured score bands can
violate the intended DA/x265/quality/source/tier ordering.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any


DEFAULT_CF_LIMIT = 100
LEGACY_TIER_PATTERN = re.compile(r"^(?!Dictionarry ).*\bTier \d{2}$", re.IGNORECASE)
LEGACY_TIER_NAMES = {"WEB Scene"}

ANIME_DUAL_AUDIO_SCORE = 100000
ANIME_METADATA_DUAL_AUDIO_CF_NAME = "Anime - Dual Audio (Metadata)"
ANIME_DUAL_AUDIO_TITLE_HELPER_CF_NAME = "Anime - Dual Audio (Title)"
ANIME_DUAL_AUDIO_DUPLICATE_GUARD_CF_NAME = "Anime Dual Audio - Metadata/Title Duplicate Guard"
REGULAR_DUAL_AUDIO_SCORE = 100000
REGULAR_DUAL_AUDIO_CF_NAME = "Regular Dual Audio"
RADARR_REGULAR_ENGLISH_GUARD_CF_NAME = "Regular English - Foreign/Multi Audio Guard"
QUALITY_RANK_PREFIX = "Local Quality Rank - "
QUALITY_RANK_SCORES = {
    "480p": 10000,
    "576p": 20000,
    "720p": 30000,
    "1080p": 40000,
}
ANIME_X265_MIN_SCORE = 5000
REGULAR_X265_MIN_SCORE = 5000
ANIME_BLURAY_SOURCE_RANK = 0
SERVICE_MAX_SCORE = 3
REPACK_MAX_SCORE = 3
REGULAR_QUALITY_GROUP_NAME = "Regular Enabled Qualities"
SERVICE_FORMAT_NAMES = {
    "ABEMA",
    "ADN",
    "AMZN",
    "ATVP",
    "B-Global",
    "Bilibili",
    "CR",
    "DSNP",
    "FUNi",
    "HBO",
    "HIDIVE",
    "HMAX",
    "HULU",
    "Hulu",
    "iT",
    "MAX",
    "NF",
    "PCOK",
    "PMTP",
    "SHO",
    "STAN",
    "VRV",
}
REPACK_FORMAT_NAMES = {
    "Repack/Proper",
    "Repack2",
    "Repack3",
}


@dataclass(frozen=True)
class ProfileCheck:
    name: str
    kind: str


@dataclass(frozen=True)
class ArrInstance:
    name: str
    base_url: str
    config_path: str
    x265_name: str
    profile_checks: tuple[ProfileCheck, ...]


INSTANCES = (
    ArrInstance(
        name="sonarr",
        base_url="http://127.0.0.1:8989",
        config_path="/opt/media-stack/sonarr/config.xml",
        x265_name="x265",
        profile_checks=(
            ProfileCheck("shows-anime-efficient", "anime"),
            ProfileCheck("shows-regular-efficient", "regular"),
            ProfileCheck("shows-regular-dual-audio-efficient", "regular_dual_audio"),
        ),
    ),
    ArrInstance(
        name="radarr",
        base_url="http://127.0.0.1:7878",
        config_path="/opt/media-stack/radarr/config.xml",
        x265_name="x265 (HD)",
        profile_checks=(
            ProfileCheck("movies-anime-efficient", "anime"),
            ProfileCheck("movies-regular-efficient", "regular"),
            ProfileCheck("movies-regular-dual-audio-efficient", "regular_dual_audio"),
        ),
    ),
)

STACKS = {
    "sonarr": {
        "best_bluray_hevc": (
            "Dictionarry 1080p Efficient TV Bluray Tier 1",
            "Dictionarry 1080p Compact TV Bluray Tier 1",
            "Dictionarry 1080p Bluray HEVC Tier 1",
        ),
        "second_bluray_hevc": (
            "Dictionarry 1080p Efficient TV Bluray Tier 2",
            "Dictionarry 1080p Compact TV Bluray Tier 2",
            "Dictionarry 1080p Bluray HEVC Tier 1",
        ),
        "best_web_hevc": (
            "Dictionarry 1080p Efficient TV WEB Tier 1",
            "Dictionarry 1080p Compact TV WEB Tier 1",
            "Dictionarry 1080p WEB-DL HEVC Tier 1",
            "Dictionarry WEB-DL Tier 1",
        ),
    },
    "radarr": {
        "best_bluray_hevc": (
            "Dictionarry 1080p Efficient Movie Bluray Tier 1",
            "Dictionarry 1080p Compact Movie Bluray Tier 1",
            "Dictionarry 1080p Bluray HEVC Tier 1",
        ),
        "second_bluray_hevc": (
            "Dictionarry 1080p Efficient Movie Bluray Tier 2",
            "Dictionarry 1080p Compact Movie Bluray Tier 2",
            "Dictionarry 1080p Bluray HEVC Tier 1",
        ),
        "best_web_hevc": (
            "Dictionarry 1080p Efficient Movie WEB Tier 1",
            "Dictionarry 1080p Compact Movie WEB Tier 1",
            "Dictionarry 1080p WEB-DL HEVC Tier 1",
            "Dictionarry WEB-DL Tier 1",
        ),
    },
}

SCORE_FAMILIES = {
    "sonarr": {
        "Efficient TV Bluray": (
            "Dictionarry 1080p Efficient TV Bluray Tier 1",
            "Dictionarry 1080p Efficient TV Bluray Tier 2",
            "Dictionarry 1080p Efficient TV Bluray Tier 3",
            "Dictionarry 1080p Efficient TV Bluray Tier 4",
            "Dictionarry 1080p Efficient TV Bluray Tier 5",
            "Dictionarry 1080p Efficient TV Bluray Tier 6",
        ),
        "Efficient TV WEB": (
            "Dictionarry 1080p Efficient TV WEB Tier 1",
            "Dictionarry 1080p Efficient TV WEB Tier 2",
            "Dictionarry 1080p Efficient TV WEB Tier 3",
            "Dictionarry 1080p Efficient TV WEB Tier 4",
            "Dictionarry 1080p Efficient TV WEB Tier 5",
        ),
        "Compact TV Bluray": (
            "Dictionarry 1080p Compact TV Bluray Tier 1",
            "Dictionarry 1080p Compact TV Bluray Tier 2",
            "Dictionarry 1080p Compact TV Bluray Tier 3",
            "Dictionarry 1080p Compact TV Bluray Tier 4",
            "Dictionarry 1080p Compact TV Bluray Tier 5",
            "Dictionarry 1080p Compact TV Bluray Tier 6",
        ),
        "Compact TV WEB": (
            "Dictionarry 1080p Compact TV WEB Tier 1",
            "Dictionarry 1080p Compact TV WEB Tier 2",
            "Dictionarry 1080p Compact TV WEB Tier 3",
            "Dictionarry 1080p Compact TV WEB Tier 4",
            "Dictionarry 1080p Compact TV WEB Tier 5",
        ),
        "WEB-DL": (
            "Dictionarry WEB-DL Tier 1",
            "Dictionarry WEB-DL Tier 2",
            "Dictionarry WEB-DL Tier 3",
            "Dictionarry WEB-DL Tier 4",
            "Dictionarry WEB-DL Tier 5",
        ),
    },
    "radarr": {
        "Efficient Movie Bluray": (
            "Dictionarry 1080p Efficient Movie Bluray Tier 1",
            "Dictionarry 1080p Efficient Movie Bluray Tier 2",
            "Dictionarry 1080p Efficient Movie Bluray Tier 3",
            "Dictionarry 1080p Efficient Movie Bluray Tier 4",
        ),
        "Efficient Movie WEB": (
            "Dictionarry 1080p Efficient Movie WEB Tier 1",
            "Dictionarry 1080p Efficient Movie WEB Tier 2",
            "Dictionarry 1080p Efficient Movie WEB Tier 3",
            "Dictionarry 1080p Efficient Movie WEB Tier 4",
        ),
        "Compact Movie Bluray": (
            "Dictionarry 1080p Compact Movie Bluray Tier 1",
            "Dictionarry 1080p Compact Movie Bluray Tier 2",
            "Dictionarry 1080p Compact Movie Bluray Tier 3",
            "Dictionarry 1080p Compact Movie Bluray Tier 4",
        ),
        "Compact Movie WEB": (
            "Dictionarry 1080p Compact Movie WEB Tier 1",
            "Dictionarry 1080p Compact Movie WEB Tier 2",
            "Dictionarry 1080p Compact Movie WEB Tier 3",
            "Dictionarry 1080p Compact Movie WEB Tier 4",
        ),
        "WEB-DL": (
            "Dictionarry WEB-DL Tier 1",
            "Dictionarry WEB-DL Tier 2",
            "Dictionarry WEB-DL Tier 3",
            "Dictionarry WEB-DL Tier 4",
            "Dictionarry WEB-DL Tier 5",
        ),
    },
}

SOURCE_ORDERING_CHECKS = {
    "sonarr": (
        ("Dictionarry 1080p Efficient TV Bluray Tier 2", "Dictionarry 1080p Efficient TV WEB Tier 1"),
        ("Dictionarry 1080p Compact TV Bluray Tier 2", "Dictionarry 1080p Compact TV WEB Tier 1"),
    ),
    "radarr": (
        ("Dictionarry 1080p Efficient Movie Bluray Tier 2", "Dictionarry 1080p Efficient Movie WEB Tier 1"),
        ("Dictionarry 1080p Compact Movie Bluray Tier 2", "Dictionarry 1080p Compact Movie WEB Tier 1"),
    ),
}

TRASH_FALLBACK_SCORES = {
    ("sonarr", "anime"): {
        **{f"Anime BD Tier {index:02d}": score for index, score in enumerate((96, 88, 80, 72, 64, 56, 48, 40), start=1)},
        **{f"Anime Web Tier {index:02d}": score for index, score in enumerate((32, 24, 16, 12, 8, 4), start=1)},
    },
    ("radarr", "anime"): {
        **{f"Anime BD Tier {index:02d}": score for index, score in enumerate((96, 88, 80, 72, 64, 56, 48, 40), start=1)},
        **{f"Anime Web Tier {index:02d}": score for index, score in enumerate((32, 24, 16, 12, 8, 4), start=1)},
    },
    ("sonarr", "regular"): {
        "WEB Tier 01": 96,
        "WEB Tier 02": 88,
        "WEB Tier 03": 80,
        "WEB Scene": 16,
    },
    ("radarr", "regular"): {
        "HD Bluray Tier 01": 96,
        "HD Bluray Tier 02": 88,
        "HD Bluray Tier 03": 80,
        "WEB Tier 01": 80,
        "WEB Tier 02": 72,
        "WEB Tier 03": 64,
    },
}

ANIME_NEGATIVE_GUARDRAILS = (
    "Anime LQ Groups",
    "Anime Raws",
    "Dubs Only (Block)",
    "LQ",
    "LQ (Release Title)",
    "Portuguese (No English)",
    "UHD 2160p - Non-Dual (Block)",
)
REGULAR_NEGATIVE_GUARDRAILS = (
    "BR-DISK",
    "Extras",
    "Language - Not Original",
    "LQ",
    "LQ (Release Title)",
    "No-RlsGroup",
)


def read_api_key(path: str) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey")
    if not key:
        raise RuntimeError(f"{path}: ApiKey was not found")
    return key.strip()


def api_get(instance: ArrInstance, path: str) -> Any:
    request = urllib.request.Request(
        f"{instance.base_url.rstrip('/')}{path}",
        headers={"X-Api-Key": read_api_key(instance.config_path)},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def custom_format_id_from_item(item: dict[str, Any]) -> int | None:
    value = item.get("format")
    if isinstance(value, dict):
        value = value.get("id")
    if value is None:
        value = item.get("customFormatId")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def custom_format_name_from_item(
    item: dict[str, Any],
    custom_formats_by_id: dict[int, dict[str, Any]],
) -> str:
    value = item.get("format")
    if isinstance(value, dict) and value.get("name"):
        return str(value["name"])
    cf_id = custom_format_id_from_item(item)
    if cf_id is not None and cf_id in custom_formats_by_id:
        return str(custom_formats_by_id[cf_id].get("name") or f"id:{cf_id}")
    return str(item.get("name") or f"id:{cf_id}")


def is_group_item(item: dict[str, Any]) -> bool:
    return "quality" not in item and isinstance(item.get("items"), list)


def is_quality_item(item: dict[str, Any]) -> bool:
    return isinstance(item.get("quality"), dict)


def quality_item_name(item: dict[str, Any]) -> str:
    quality = item.get("quality")
    if isinstance(quality, dict) and quality.get("name"):
        return str(quality["name"])
    return str(item.get("name") or "")


def iter_quality_locations(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    locations: dict[str, dict[str, Any]] = {}
    for item in profile.get("items") or []:
        if is_quality_item(item):
            locations[quality_item_name(item)] = {
                "allowed": bool(item.get("allowed")),
                "group": None,
            }
            continue
        if is_group_item(item):
            group_name = str(item.get("name") or "")
            for child in item.get("items") or []:
                if not is_quality_item(child):
                    continue
                locations[quality_item_name(child)] = {
                    "allowed": bool(child.get("allowed")),
                    "group": group_name,
                }
    return locations


def regular_enabled_quality_group_report(
    profile: dict[str, Any],
    failures: list[str],
    profile_name: str,
) -> dict[str, Any]:
    locations = iter_quality_locations(profile)
    allowed = [name for name, location in locations.items() if location["allowed"]]
    groups = {locations[name]["group"] for name in allowed}
    report = {
        REGULAR_QUALITY_GROUP_NAME: {
            "qualities": allowed,
            "groups": sorted(str(group) for group in groups),
        }
    }
    if len(allowed) < 2:
        failures.append(f"{profile_name}: expected multiple enabled qualities in regular test profile")
    if groups != {REGULAR_QUALITY_GROUP_NAME}:
        actual = ", ".join(sorted(str(group) for group in groups))
        failures.append(
            f"{profile_name}: all enabled regular qualities must be grouped as "
            f"{REGULAR_QUALITY_GROUP_NAME}; actual groups: {actual}"
        )
    if profile.get("cutoff") is not None:
        cutoff_group = None
        for item in profile.get("items") or []:
            if is_group_item(item) and item.get("id") == profile.get("cutoff"):
                cutoff_group = str(item.get("name") or "")
                break
        if cutoff_group != REGULAR_QUALITY_GROUP_NAME:
            failures.append(
                f"{profile_name}: cutoff must point at {REGULAR_QUALITY_GROUP_NAME}; actual {cutoff_group}"
            )
    return report


def find_one(items: list[dict[str, Any]], name: str, kind: str) -> dict[str, Any]:
    matches = [item for item in items if item.get("name") == name]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {kind} named {name!r}, found {len(matches)}")
    return matches[0]


def profile_scores(
    profile: dict[str, Any],
    custom_formats_by_id: dict[int, dict[str, Any]],
) -> dict[str, int]:
    scores: dict[str, int] = {}
    for item in profile.get("formatItems") or []:
        cf_id = custom_format_id_from_item(item)
        if cf_id is None:
            continue
        scores[custom_format_name_from_item(item, custom_formats_by_id)] = int(item.get("score") or 0)
    return scores


def score_sum(scores: dict[str, int], names: tuple[str, ...]) -> tuple[int, list[str]]:
    missing = [name for name in names if name not in scores]
    return sum(scores.get(name, 0) for name in names), missing


def unexpected_fallback_tiers(scores: dict[str, int], expected_scores: dict[str, int]) -> dict[str, int]:
    return {
        name: score
        for name, score in scores.items()
        if score != expected_scores.get(name, 0)
        and (LEGACY_TIER_PATTERN.match(name) or name in LEGACY_TIER_NAMES)
    }


def check_negative_guardrails(scores: dict[str, int], names: tuple[str, ...]) -> dict[str, int]:
    return {name: scores[name] for name in names if name in scores and scores[name] > -10000}


def active_service_scores(scores: dict[str, int]) -> dict[str, int]:
    return {
        name: score
        for name, score in scores.items()
        if name in SERVICE_FORMAT_NAMES and score != 0
    }


def active_repack_scores(scores: dict[str, int]) -> dict[str, int]:
    return {
        name: score
        for name, score in scores.items()
        if name in REPACK_FORMAT_NAMES and score != 0
    }


def quality_resolution_from_name(name: str) -> str | None:
    match = re.search(r"\b(480p|576p|720p|1080p)\b", name, flags=re.IGNORECASE)
    return match.group(1).lower() if match else None


def quality_rank_score_report(scores: dict[str, int], failures: list[str], profile_name: str) -> dict[str, int]:
    report: dict[str, int] = {}
    for quality, expected in QUALITY_RANK_SCORES.items():
        name = f"{QUALITY_RANK_PREFIX}{quality}"
        if name not in scores:
            continue
        actual = scores[name]
        report[quality] = actual
        if actual != expected:
            failures.append(f"{profile_name}: {name} score {actual} must be {expected}")
    if not report:
        failures.append(f"{profile_name}: no generic quality-rank custom formats are scored")
    return report


def min_configured_tier_gap(instance_name: str, scores: dict[str, int], failures: list[str], profile_name: str) -> int:
    gaps: list[int] = []
    for family_name, names in SCORE_FAMILIES[instance_name].items():
        missing = [name for name in names if name not in scores]
        if missing:
            failures.append(f"{profile_name}: missing {family_name} scores: {', '.join(missing)}")
            continue
        for earlier, later in zip(names[:-1], names[1:], strict=True):
            gap = scores[earlier] - scores[later]
            gaps.append(gap)
            if gap <= 0:
                failures.append(
                    f"{profile_name}: {earlier} ({scores[earlier]}) "
                    f"must stay above {later} ({scores[later]})"
                )
    return min(gaps or [0])


def expected_fallback_scores(instance_name: str, profile_kind: str) -> dict[str, int]:
    if profile_kind == "regular_dual_audio":
        profile_kind = "regular"
    return TRASH_FALLBACK_SCORES.get((instance_name, profile_kind), {})


def audit_profile(
    instance: ArrInstance,
    profile_check: ProfileCheck,
    profile: dict[str, Any],
    custom_formats_by_id: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    scores = profile_scores(profile, custom_formats_by_id)
    failures: list[str] = []
    stack_rows: dict[str, dict[str, Any]] = {}

    for stack_name, components in STACKS[instance.name].items():
        total, missing = score_sum(scores, components)
        stack_rows[stack_name] = {"score": total, "components": list(components), "missing": missing}
        if missing:
            failures.append(f"{profile_check.name}: missing {stack_name} components: {', '.join(missing)}")

    bluray_stack = stack_rows["best_bluray_hevc"]["score"]
    second_bluray_stack = stack_rows["second_bluray_hevc"]["score"]
    web_stack = stack_rows["best_web_hevc"]["score"]
    if bluray_stack <= web_stack:
        failures.append(
            f"{profile_check.name}: best Bluray HEVC stack {bluray_stack} "
            f"must stay above best WEB HEVC stack {web_stack}"
        )
    if second_bluray_stack <= web_stack:
        failures.append(
            f"{profile_check.name}: second Bluray HEVC stack {second_bluray_stack} "
            f"must stay above best WEB HEVC stack {web_stack}"
        )

    for bluray_name, web_name in SOURCE_ORDERING_CHECKS[instance.name]:
        if bluray_name not in scores or web_name not in scores:
            failures.append(f"{profile_check.name}: missing source ordering scores: {bluray_name} / {web_name}")
        elif scores[bluray_name] <= scores[web_name]:
            failures.append(
                f"{profile_check.name}: {bluray_name} ({scores[bluray_name]}) "
                f"must stay above {web_name} ({scores[web_name]})"
            )

    service_scores = active_service_scores(scores)
    excessive_services = {name: score for name, score in service_scores.items() if score > SERVICE_MAX_SCORE}
    if excessive_services:
        names = ", ".join(f"{name}={score}" for name, score in sorted(excessive_services.items()))
        failures.append(f"{profile_check.name}: service scores above max {SERVICE_MAX_SCORE}: {names}")
    max_service_score = max(service_scores.values() or [0])

    repack_scores = active_repack_scores(scores)
    excessive_repacks = {name: score for name, score in repack_scores.items() if score > REPACK_MAX_SCORE}
    if excessive_repacks:
        names = ", ".join(f"{name}={score}" for name, score in sorted(excessive_repacks.items()))
        failures.append(f"{profile_check.name}: repack/proper scores above max {REPACK_MAX_SCORE}: {names}")
    max_repack_score = max(repack_scores.values() or [0])
    max_incidental_score = max_service_score + max_repack_score

    min_tier_gap = min_configured_tier_gap(instance.name, scores, failures, profile_check.name)
    if max_incidental_score >= min_tier_gap:
        failures.append(
            f"{profile_check.name}: max incidental score {max_incidental_score} "
            f"must stay below smallest Dictionarry tier gap {min_tier_gap}"
        )

    fallback_expected = expected_fallback_scores(instance.name, profile_check.kind)
    fallback_scores = {name: scores.get(name, 0) for name in fallback_expected}
    fallback_mismatches = {
        name: {"expected": expected, "actual": fallback_scores.get(name, 0)}
        for name, expected in fallback_expected.items()
        if fallback_scores.get(name, 0) != expected
    }
    if fallback_mismatches:
        names = ", ".join(
            f"{name}={item['actual']} expected {item['expected']}"
            for name, item in sorted(fallback_mismatches.items())
        )
        failures.append(f"{profile_check.name}: fallback TRaSH tier score mismatch: {names}")
    legacy_scores = unexpected_fallback_tiers(scores, fallback_expected)
    if legacy_scores:
        names = ", ".join(f"{name}={score}" for name, score in sorted(legacy_scores.items()))
        failures.append(f"{profile_check.name}: unexpected legacy/fallback tier scores: {names}")
    max_fallback_score = max(fallback_expected.values() or [0])
    min_positive_dictionarry = min(
        (
            score
            for name, score in scores.items()
            if name.startswith("Dictionarry ") and score > 0
        ),
        default=0,
    )
    if min_positive_dictionarry <= max_fallback_score + max_incidental_score:
        failures.append(
            f"{profile_check.name}: lowest Dictionarry score {min_positive_dictionarry} "
            f"must stay above fallback+incidental {max_fallback_score + max_incidental_score}"
        )

    x265_score = scores.get(instance.x265_name, 0)
    x265_floor = ANIME_X265_MIN_SCORE if profile_check.kind == "anime" else REGULAR_X265_MIN_SCORE
    if x265_score < x265_floor:
        failures.append(f"{profile_check.name}: {instance.x265_name} score {x265_score} is below {x265_floor}")
    quality_rank_scores = quality_rank_score_report(scores, failures, profile_check.name)

    negative_guardrails = (
        ANIME_NEGATIVE_GUARDRAILS if profile_check.kind == "anime" else REGULAR_NEGATIVE_GUARDRAILS
    )
    weak_negatives = check_negative_guardrails(scores, negative_guardrails)
    if weak_negatives:
        names = ", ".join(f"{name}={score}" for name, score in sorted(weak_negatives.items()))
        failures.append(f"{profile_check.name}: weak negative guardrails: {names}")

    source_rank = scores.get("Local Anime Source Rank - Bluray", 0)
    if source_rank != ANIME_BLURAY_SOURCE_RANK:
        failures.append(
            f"{profile_check.name}: Local Anime Source Rank - Bluray score {source_rank} "
            f"must be {ANIME_BLURAY_SOURCE_RANK}"
        )
    if profile_check.kind == "anime":
        regular_quality_groups: dict[str, Any] = {}
        da_score = scores.get("Anime Dual Audio", 0)
        if da_score < ANIME_DUAL_AUDIO_SCORE:
            failures.append(f"{profile_check.name}: Anime Dual Audio score {da_score} is below {ANIME_DUAL_AUDIO_SCORE}")
        if instance.name == "radarr" and profile_check.name == "movies-anime-efficient":
            metadata_da_score = scores.get(ANIME_METADATA_DUAL_AUDIO_CF_NAME, 0)
            duplicate_guard_score = scores.get(ANIME_DUAL_AUDIO_DUPLICATE_GUARD_CF_NAME, 0)
            title_helper_score = scores.get(ANIME_DUAL_AUDIO_TITLE_HELPER_CF_NAME, 0)
            regular_da_score = scores.get(REGULAR_DUAL_AUDIO_CF_NAME, 0)
            if metadata_da_score != da_score:
                failures.append(
                    f"{profile_check.name}: {ANIME_METADATA_DUAL_AUDIO_CF_NAME} score "
                    f"{metadata_da_score} must equal Anime Dual Audio {da_score}"
                )
            if duplicate_guard_score != -da_score:
                failures.append(
                    f"{profile_check.name}: {ANIME_DUAL_AUDIO_DUPLICATE_GUARD_CF_NAME} score "
                    f"{duplicate_guard_score} must equal -Anime Dual Audio {-da_score}"
                )
            if title_helper_score != 0:
                failures.append(
                    f"{profile_check.name}: {ANIME_DUAL_AUDIO_TITLE_HELPER_CF_NAME} "
                    f"must stay zero-scored, got {title_helper_score}"
                )
            if regular_da_score != 0:
                failures.append(
                    f"{profile_check.name}: {REGULAR_DUAL_AUDIO_CF_NAME} must stay zero-scored "
                    f"on anime profile, got {regular_da_score}"
                )
            net_both_da = da_score + metadata_da_score + duplicate_guard_score
            if net_both_da != da_score:
                failures.append(
                    f"{profile_check.name}: title+metadata DA nets {net_both_da}, "
                    f"must equal one DA bonus {da_score}"
                )

        release_stack = max(bluray_stack, web_stack) + max_fallback_score + max_incidental_score
        source_plus_stack = source_rank + release_stack
        if source_plus_stack >= x265_score:
            failures.append(
                f"{profile_check.name}: source+tier stack {source_plus_stack} "
                f"must stay below x265 {x265_score}"
            )

        max_non_da_1080p = (
            QUALITY_RANK_SCORES["1080p"]
            + x265_score
            + source_rank
            + release_stack
        )
        if max_non_da_1080p >= da_score:
            failures.append(
                f"{profile_check.name}: max non-DA 1080p score {max_non_da_1080p} "
                f"must stay below DA {da_score}"
            )

        max_720p_da = (
            da_score
            + QUALITY_RANK_SCORES["720p"]
            + x265_score
            + source_rank
            + release_stack
        )
        min_1080p_da = da_score + QUALITY_RANK_SCORES["1080p"]
        if min_1080p_da <= max_720p_da:
            failures.append(
                f"{profile_check.name}: 1080p DA floor {min_1080p_da} "
                f"must beat max 720p DA {max_720p_da}"
            )
        expected_cutoff_score = da_score + max(quality_rank_scores.values() or [0]) + x265_score + source_rank + release_stack
    else:
        regular_quality_groups = regular_enabled_quality_group_report(profile, failures, profile_check.name)
        release_stack = max(bluray_stack, web_stack) + max_fallback_score + max_incidental_score
        if release_stack >= x265_score:
            failures.append(
                f"{profile_check.name}: tier stack {release_stack} "
                f"must stay below x265 {x265_score}"
            )
        grouped_qualities = next(iter(regular_quality_groups.values()), {}).get("qualities", [])
        grouped_resolutions = sorted(
            {
                resolution
                for quality_name in grouped_qualities
                if (resolution := quality_resolution_from_name(quality_name)) is not None
            },
            key=lambda value: QUALITY_RANK_SCORES.get(value, 0),
        )
        unranked_qualities = [
            quality_name
            for quality_name in grouped_qualities
            if quality_resolution_from_name(quality_name) is None
        ]
        if unranked_qualities:
            max_unranked_stack = x265_score + release_stack
            lowest_rank = min(QUALITY_RANK_SCORES.values())
            if max_unranked_stack >= lowest_rank:
                failures.append(
                    f"{profile_check.name}: unranked qualities {', '.join(unranked_qualities)} "
                    f"can score {max_unranked_stack}, which must stay below lowest quality rank {lowest_rank}"
                )
        missing_ranks = [
            resolution
            for resolution in grouped_resolutions
            if quality_rank_scores.get(resolution, 0) != QUALITY_RANK_SCORES[resolution]
        ]
        if missing_ranks:
            failures.append(
                f"{profile_check.name}: enabled regular qualities lack matching quality-rank scores: "
                + ", ".join(missing_ranks)
            )
        ordered_scores = [QUALITY_RANK_SCORES[resolution] for resolution in grouped_resolutions]
        for lower, higher, lower_score, higher_score in zip(
            grouped_resolutions[:-1],
            grouped_resolutions[1:],
            ordered_scores[:-1],
            ordered_scores[1:],
            strict=True,
        ):
            max_lower_stack = lower_score + x265_score + release_stack
            if max_lower_stack >= higher_score:
                failures.append(
                    f"{profile_check.name}: max {lower} regular stack {max_lower_stack} "
                    f"must stay below bare {higher} rank {higher_score}"
                )
        regular_dual_audio_score = scores.get(REGULAR_DUAL_AUDIO_CF_NAME, 0)
        radarr_regular_english_guard_score = scores.get(RADARR_REGULAR_ENGLISH_GUARD_CF_NAME, 0)
        if instance.name == "radarr":
            if profile_check.name == "movies-regular-efficient":
                if radarr_regular_english_guard_score > -10000:
                    failures.append(
                        f"{profile_check.name}: {RADARR_REGULAR_ENGLISH_GUARD_CF_NAME} "
                        f"must be a hard negative, got {radarr_regular_english_guard_score}"
                    )
            elif radarr_regular_english_guard_score:
                failures.append(
                    f"{profile_check.name}: {RADARR_REGULAR_ENGLISH_GUARD_CF_NAME} "
                    f"must stay unscored outside the English regular profile, got "
                    f"{radarr_regular_english_guard_score}"
                )
        if profile_check.kind == "regular_dual_audio":
            if regular_dual_audio_score < REGULAR_DUAL_AUDIO_SCORE:
                failures.append(
                    f"{profile_check.name}: {REGULAR_DUAL_AUDIO_CF_NAME} score "
                    f"{regular_dual_audio_score} is below {REGULAR_DUAL_AUDIO_SCORE}"
                )
            max_non_da_1080p = max(quality_rank_scores.values() or [0]) + x265_score + release_stack
            if max_non_da_1080p >= regular_dual_audio_score:
                failures.append(
                    f"{profile_check.name}: max non-DA 1080p score {max_non_da_1080p} "
                    f"must stay below regular DA {regular_dual_audio_score}"
                )
            max_720p_da = regular_dual_audio_score + QUALITY_RANK_SCORES["720p"] + x265_score + release_stack
            min_1080p_da = regular_dual_audio_score + QUALITY_RANK_SCORES["1080p"]
            if min_1080p_da <= max_720p_da:
                failures.append(
                    f"{profile_check.name}: 1080p regular DA floor {min_1080p_da} "
                    f"must beat max 720p regular DA {max_720p_da}"
                )
            expected_cutoff_score = (
                regular_dual_audio_score
                + max(quality_rank_scores.values() or [0])
                + x265_score
                + source_rank
                + release_stack
            )
        else:
            if regular_dual_audio_score:
                failures.append(
                    f"{profile_check.name}: {REGULAR_DUAL_AUDIO_CF_NAME} must stay unscored "
                    f"on regular English-default profiles, got {regular_dual_audio_score}"
                )
            expected_cutoff_score = max(quality_rank_scores.values() or [0]) + x265_score + source_rank + release_stack

    actual_cutoff_score = int(profile.get("cutoffFormatScore") or 0)
    if actual_cutoff_score != expected_cutoff_score:
        failures.append(
            f"{profile_check.name}: cutoffFormatScore {actual_cutoff_score} "
            f"must equal max applicable score {expected_cutoff_score}"
        )

    return {
        "profile": profile_check.name,
        "kind": profile_check.kind,
        "stacks": stack_rows,
        "x265_score": x265_score,
        "source_rank_bluray_score": source_rank,
        "max_service_score": max_service_score,
        "max_repack_score": max_repack_score,
        "max_incidental_score": max_incidental_score,
        "min_tier_gap": min_tier_gap,
        "service_scores": service_scores,
        "repack_scores": repack_scores,
        "fallback_scores": fallback_scores,
        "max_fallback_score": max_fallback_score,
        "min_positive_dictionarry_score": min_positive_dictionarry,
        "dual_audio_score": scores.get("Anime Dual Audio"),
        "regular_dual_audio_score": scores.get(REGULAR_DUAL_AUDIO_CF_NAME),
        "radarr_regular_english_guard_score": scores.get(RADARR_REGULAR_ENGLISH_GUARD_CF_NAME),
        "quality_rank_scores": quality_rank_scores,
        "regular_enabled_quality_group": regular_quality_groups,
        "expected_cutoff_format_score": expected_cutoff_score,
        "actual_cutoff_format_score": actual_cutoff_score,
        "unexpected_legacy_tier_scores": legacy_scores,
        "metadata_dual_audio_score": scores.get(ANIME_METADATA_DUAL_AUDIO_CF_NAME),
        "dual_audio_duplicate_guard_score": scores.get(ANIME_DUAL_AUDIO_DUPLICATE_GUARD_CF_NAME),
        "failures": failures,
    }


def audit_instance(instance: ArrInstance, cf_limit: int) -> dict[str, Any]:
    custom_formats = api_get(instance, "/api/v3/customformat")
    profiles = api_get(instance, "/api/v3/qualityprofile")
    custom_formats_by_id = {int(cf["id"]): cf for cf in custom_formats if isinstance(cf.get("id"), int)}

    profile_reports = [
        audit_profile(
            instance,
            profile_check,
            find_one(profiles, profile_check.name, "quality profile"),
            custom_formats_by_id,
        )
        for profile_check in instance.profile_checks
    ]
    failures = [failure for report in profile_reports for failure in report["failures"]]
    if len(custom_formats) > cf_limit:
        failures.append(f"{instance.name}: custom format count {len(custom_formats)} exceeds limit {cf_limit}")
    return {
        "instance": instance.name,
        "custom_format_count": len(custom_formats),
        "custom_format_limit": cf_limit,
        "profiles": profile_reports,
        "failures": failures,
    }


def print_text(report: dict[str, Any]) -> None:
    for instance in report["instances"]:
        print(f"{instance['instance']}: CFs {instance['custom_format_count']}/{instance['custom_format_limit']}")
        for profile in instance["profiles"]:
            stacks = profile["stacks"]
            print(
                "  {profile}: Bluray HEVC stack={bluray}; second Bluray={second}; "
                "WEB HEVC stack={web}; fallback max={fallback}; incidental max={incidental}; "
                "service max={service}; repack max={repack}; min tier gap={gap}; "
                "x265={x265}; Bluray source={source}; DA={da}; regular DA={regular_da}; "
                "cutoff={cutoff}/{expected_cutoff}".format(
                    profile=profile["profile"],
                    bluray=stacks["best_bluray_hevc"]["score"],
                    second=stacks["second_bluray_hevc"]["score"],
                    web=stacks["best_web_hevc"]["score"],
                    fallback=profile["max_fallback_score"],
                    incidental=profile["max_incidental_score"],
                    service=profile["max_service_score"],
                    repack=profile["max_repack_score"],
                    gap=profile["min_tier_gap"],
                    x265=profile["x265_score"],
                    source=profile["source_rank_bluray_score"],
                    da=profile["dual_audio_score"],
                    regular_da=profile["regular_dual_audio_score"],
                    cutoff=profile["actual_cutoff_format_score"],
                    expected_cutoff=profile["expected_cutoff_format_score"],
                )
            )
            if profile["regular_enabled_quality_group"]:
                print("    regular enabled quality group:")
                for group_name, item in sorted(profile["regular_enabled_quality_group"].items()):
                    print(f"      - {group_name}: {', '.join(item['qualities'])}")
            if profile["unexpected_legacy_tier_scores"]:
                print("    unexpected legacy/fallback tiers:")
                for name, score in sorted(profile["unexpected_legacy_tier_scores"].items()):
                    print(f"      - {name}: {score}")
        if instance["failures"]:
            print("  failures:")
            for failure in instance["failures"]:
                print(f"    - {failure}")
        else:
            print("  failures: none")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cf-limit", type=int, default=DEFAULT_CF_LIMIT)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-fail", action="store_true", help="return 0 even when audit failures are present")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = {"instances": [audit_instance(instance, args.cf_limit) for instance in INSTANCES]}
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        print_text(report)
    failed = any(instance["failures"] for instance in report["instances"])
    return 1 if failed and not args.no_fail else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
