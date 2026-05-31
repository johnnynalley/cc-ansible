#!/usr/bin/env python3
"""Audit recent Sonarr original-language-only imports against manual search.

Run this on docker-vm. It reads Sonarr's local config.xml for the API key,
queries localhost only, and prints no secrets. The manual release checks are
read-only, but they can be slow because they ask Sonarr/indexers for candidates
for each affected episode.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any


SONARR_URL = "http://127.0.0.1:8989"
SONARR_CONFIG = "/opt/media-stack/sonarr/config.xml"
IMPORT_EVENT_TYPES = {"downloadFolderImported", "episodeFileImported"}
ENGLISH_NAMES = {"english"}
UNKNOWN_NAMES = {"unknown"}
DA_CF_NAMES = {"anime dual audio"}
X265_RE = re.compile(r"(?i)(?:\b[xh][\s._-]?265\b|\bhevc\b)")
DA_TITLE_RE = re.compile(
    r"(?i)\b(?:dual[ ._-]?audio|multi[ ._-]?audio|"
    r"dual\b(?![ ._-]sub(?:s|titles?)?\b)|"
    r"(?:ja|jp|jpn|japanese|zh|chi|zho|chinese|ko|kor|korean)"
    r"[ ._+&-]*(?:en|eng|english)|"
    r"(?:en|eng|english)[ ._+&-]*"
    r"(?:ja|jp|jpn|japanese|zh|chi|zho|chinese|ko|kor|korean))\b"
)
NON_ENGLISH_DUB_RE = re.compile(
    r"(?i)(?=.*\b(?:german|deutsch|spanish|espa(?:n|ñ)ol|castellano|latino|"
    r"french|fran(?:c|ç)ais|italian|italiano|portuguese|portugu[eê]s|"
    r"russian|russisch|hindi|arabic)\b)"
    r"(?!.*\b(?:en|eng|english)\b)"
    r".*\b(?:dub|dubs|dubbed|audio|synchro|synchro[nn]is(?:e|é|ee|ed))\b"
)


def parse_time(value: str) -> dt.datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


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


def page_records(
    base_url: str,
    api_key: str,
    path: str,
    params: dict[str, Any],
    page_size: int,
    max_pages: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        payload = api_get(base_url, api_key, path, {**params, "page": page, "pageSize": page_size})
        page_records_raw = payload.get("records", payload if isinstance(payload, list) else [])
        records.extend(page_records_raw)
        total = payload.get("totalRecords") if isinstance(payload, dict) else None
        if isinstance(total, int) and len(records) >= total:
            break
        if len(page_records_raw) < page_size:
            break
    return records


def language_names(value: Any) -> list[str]:
    names: list[str] = []
    if not isinstance(value, list):
        return names
    for item in value:
        if isinstance(item, dict):
            name = item.get("name")
        else:
            name = item
        if name:
            names.append(str(name))
    return names


def language_key_set(value: Any) -> set[str]:
    return {item.casefold() for item in language_names(value)}


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


def release_title(release: dict[str, Any]) -> str:
    return str(release.get("title") or release.get("releaseTitle") or "")


def quality_name(value: dict[str, Any] | None) -> str:
    if not isinstance(value, dict):
        return "unknown"
    quality = value.get("quality")
    if isinstance(quality, dict):
        return str(quality.get("name") or quality.get("source") or "unknown")
    return str(value.get("name") or "unknown")


def release_score(release: dict[str, Any]) -> int | None:
    for key in ("customFormatScore", "preferredWordScore"):
        value = release.get(key)
        if isinstance(value, int):
            return value
    return None


def imported_score(record: dict[str, Any]) -> int | None:
    data = record.get("data") if isinstance(record.get("data"), dict) else {}
    for value in (data.get("customFormatScore"), record.get("customFormatScore")):
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def rejection_reasons(release: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for item in release.get("rejections") or []:
        if isinstance(item, str):
            reasons.append(item)
        elif isinstance(item, dict):
            reason = item.get("reason") or item.get("message")
            if reason:
                reasons.append(str(reason))
    return reasons


def has_english(languages: set[str]) -> bool:
    return bool(languages & ENGLISH_NAMES)


def is_original_language_only(record: dict[str, Any]) -> bool:
    languages = language_key_set(record.get("languages"))
    if not languages or languages <= UNKNOWN_NAMES:
        return False
    if has_english(languages):
        return False
    original = (
        (record.get("series") or {})
        .get("originalLanguage", {})
        .get("name")
    )
    if original and original.casefold() in languages:
        return True
    return bool(languages - UNKNOWN_NAMES)


def release_has_desired_audio(release: dict[str, Any], original_language: str | None) -> bool:
    languages = language_key_set(release.get("languages"))
    if original_language and original_language.casefold() in languages:
        return has_english(languages) or (
            release_claims_da(release) and NON_ENGLISH_DUB_RE.search(release_title(release)) is None
        )
    if release_claims_da(release) and NON_ENGLISH_DUB_RE.search(release_title(release)) is None:
        return True
    if not has_english(languages):
        return False
    return False


def release_claims_da(release: dict[str, Any]) -> bool:
    title = release_title(release)
    return DA_TITLE_RE.search(title) is not None or any(
        name.casefold() in DA_CF_NAMES for name in cf_names(release.get("customFormats"))
    )


def release_has_x265(release: dict[str, Any]) -> bool:
    title = release_title(release)
    formats = " ".join(cf_names(release.get("customFormats")))
    return X265_RE.search(f"{title} {formats}") is not None


def compact_release(release: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": release_title(release),
        "indexer": release.get("indexer"),
        "quality": quality_name(release.get("quality")),
        "languages": language_names(release.get("languages")),
        "score": release_score(release),
        "custom_formats": cf_names(release.get("customFormats")),
        "size": release.get("size"),
        "rejections": rejection_reasons(release),
    }


def dedupe_imports(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_episode: dict[int, dict[str, Any]] = {}
    for record in sorted(records, key=lambda item: parse_time(str(item.get("date")))):
        episode_id = int(record.get("episodeId") or 0)
        if episode_id <= 0:
            continue
        latest_by_episode[episode_id] = record
    return sorted(latest_by_episode.values(), key=lambda item: parse_time(str(item.get("date"))))


def audit_episode(
    base_url: str,
    api_key: str,
    record: dict[str, Any],
    top: int,
    release_timeout: int,
) -> dict[str, Any]:
    episode_id = int(record.get("episodeId"))
    series = record.get("series") or {}
    episode = record.get("episode") or {}
    original_language = (series.get("originalLanguage") or {}).get("name")
    releases = api_get(base_url, api_key, "/api/v3/release", {"episodeId": episode_id}, timeout=release_timeout)
    if not isinstance(releases, list):
        releases = []

    accepted = [release for release in releases if not rejection_reasons(release)]
    desired = [release for release in releases if release_has_desired_audio(release, original_language)]
    accepted_desired = [release for release in accepted if release_has_desired_audio(release, original_language)]
    da_claims = [release for release in releases if release_claims_da(release)]
    suspicious_da_claims = [
        release
        for release in da_claims
        if NON_ENGLISH_DUB_RE.search(release_title(release)) and not has_english(language_key_set(release.get("languages")))
    ]

    def score_key(release: dict[str, Any]) -> tuple[int, int, str]:
        return (
            release_score(release) if release_score(release) is not None else -10**9,
            1 if release_has_x265(release) else 0,
            release_title(release),
        )

    ranked = sorted(releases, key=score_key, reverse=True)
    accepted_ranked = sorted(accepted, key=score_key, reverse=True)
    desired_ranked = sorted(desired, key=score_key, reverse=True)
    accepted_desired_ranked = sorted(accepted_desired, key=score_key, reverse=True)
    imported = imported_score(record)
    best = accepted_ranked[0] if accepted_ranked else (ranked[0] if ranked else None)
    best_desired = accepted_desired_ranked[0] if accepted_desired_ranked else (desired_ranked[0] if desired_ranked else None)

    flags: list[str] = []
    imported_languages = language_key_set(record.get("languages"))
    if best and imported is not None and release_score(best) is not None and int(release_score(best) or 0) > imported:
        flags.append("best_allowed_score_higher_than_import")
    if accepted_desired_ranked and not has_english(imported_languages):
        flags.append("original_plus_english_available_but_not_imported")
    elif desired_ranked and not accepted_desired_ranked:
        flags.append("original_plus_english_only_rejected")
    else:
        flags.append("no_original_plus_english_candidate")
    if suspicious_da_claims:
        flags.append("suspicious_non_english_da_claim")

    return {
        "series": series.get("title"),
        "series_id": series.get("id"),
        "season": episode.get("seasonNumber"),
        "episode": episode.get("episodeNumber"),
        "episode_id": episode_id,
        "date": record.get("date"),
        "source_title": record.get("sourceTitle"),
        "imported_languages": language_names(record.get("languages")),
        "original_language": original_language,
        "imported_score": imported,
        "imported_quality": quality_name(record.get("quality")),
        "imported_custom_formats": cf_names(record.get("customFormats")),
        "release_count": len(releases),
        "accepted_count": len(accepted),
        "desired_count": len(desired),
        "accepted_desired_count": len(accepted_desired),
        "da_claim_count": len(da_claims),
        "flags": flags,
        "best": compact_release(best) if best else None,
        "best_desired": compact_release(best_desired) if best_desired else None,
        "top": [compact_release(release) for release in ranked[:top]],
        "top_desired": [compact_release(release) for release in desired_ranked[:top]],
        "suspicious_da_claims": [compact_release(release) for release in suspicious_da_claims[:top]],
    }


def audit(args: argparse.Namespace) -> dict[str, Any]:
    api_key = read_api_key(args.config)
    since = parse_time(args.since)
    history = page_records(
        args.base_url,
        api_key,
        "/api/v3/history",
        {
            "includeSeries": "true",
            "includeEpisode": "true",
            "sortKey": "date",
            "sortDirection": "descending",
        },
        args.page_size,
        args.max_pages,
    )
    imports = [
        record
        for record in history
        if record.get("eventType") in IMPORT_EVENT_TYPES
        and record.get("date")
        and parse_time(str(record["date"])) >= since
    ]
    original_only = [record for record in imports if is_original_language_only(record)]
    latest = dedupe_imports(original_only)
    if args.max_episodes:
        latest = latest[: args.max_episodes]

    episode_reports: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if not args.history_only:
        for index, record in enumerate(latest, start=1):
            if args.sleep and index > 1:
                time.sleep(args.sleep)
            if args.progress:
                episode = record.get("episode") or {}
                label = f"S{int(episode.get('seasonNumber') or 0):02}E{int(episode.get('episodeNumber') or 0):02}"
                series_title = (record.get("series") or {}).get("title") or "unknown"
                print(f"checking {index}/{len(latest)} {series_title} {label}", file=sys.stderr, flush=True)
            try:
                episode_reports.append(audit_episode(args.base_url, api_key, record, args.top, args.release_timeout))
            except Exception as exc:  # noqa: BLE001 - keep the audit moving across indexer/API failures.
                errors.append(
                    {
                        "episode_id": record.get("episodeId"),
                        "series": (record.get("series") or {}).get("title"),
                        "source_title": record.get("sourceTitle"),
                        "error": str(exc),
                    }
                )

    series_counts = collections.Counter(str((record.get("series") or {}).get("title") or "unknown") for record in original_only)
    language_counts = collections.Counter(
        "+".join(language_names(record.get("languages")) or ["Unknown"]) for record in original_only
    )
    flag_counts = collections.Counter(flag for report in episode_reports for flag in report.get("flags", []))

    return {
        "since": since.isoformat().replace("+00:00", "Z"),
        "history_records_scanned": len(history),
        "imports_since": len(imports),
        "original_language_only_imports": len(original_only),
        "unique_original_language_only_episodes_checked": len(episode_reports),
        "series_counts": dict(series_counts),
        "language_counts": dict(language_counts),
        "source_titles": [
            {
                "date": record.get("date"),
                "series": (record.get("series") or {}).get("title"),
                "season": (record.get("episode") or {}).get("seasonNumber"),
                "episode": (record.get("episode") or {}).get("episodeNumber"),
                "episode_id": record.get("episodeId"),
                "languages": language_names(record.get("languages")),
                "score": imported_score(record),
                "source_title": record.get("sourceTitle"),
            }
            for record in original_only
        ],
        "flag_counts": dict(flag_counts),
        "errors": errors,
        "episodes": episode_reports,
    }


def print_text(report: dict[str, Any]) -> None:
    print(
        f"since={report['since']} scanned={report['history_records_scanned']} "
        f"imports={report['imports_since']} original_only={report['original_language_only_imports']} "
        f"checked={report['unique_original_language_only_episodes_checked']}"
    )
    print(f"series_counts={report['series_counts']}")
    print(f"language_counts={report['language_counts']}")
    print(f"flag_counts={report['flag_counts']}")
    if report["errors"]:
        print("errors:")
        for error in report["errors"]:
            print(f"- episode_id={error['episode_id']} series={error['series']} error={error['error']}")
    if not report["episodes"]:
        print("source_titles:")
        for item in report["source_titles"]:
            label = f"S{int(item.get('season') or 0):02}E{int(item.get('episode') or 0):02}"
            print(
                f"- {item['date']} {item['series']} {label} episode_id={item['episode_id']} "
                f"languages={'+'.join(item['languages'])} score={item['score']} {item['source_title']}"
            )
        return
    print()
    for item in report["episodes"]:
        label = f"S{int(item.get('season') or 0):02}E{int(item.get('episode') or 0):02}"
        print(
            f"{item['series']} {label} episode_id={item['episode_id']} "
            f"imported={'+'.join(item['imported_languages'])} score={item['imported_score']} "
            f"releases={item['release_count']} accepted={item['accepted_count']} "
            f"desired={item['accepted_desired_count']}/{item['desired_count']} "
            f"flags={','.join(item['flags'])}"
        )
        print(f"  source: {item['source_title']}")
        best = item["best"]
        if best:
            print(
                f"  best: score={best['score']} lang={'+'.join(best['languages']) or 'Unknown'} "
                f"{best['quality']} {best['title']}"
            )
            print(f"    CFs: {', '.join(best['custom_formats']) or '(none)'}")
        desired = item["best_desired"]
        if desired:
            print(
                f"  best original+english/DA: score={desired['score']} "
                f"lang={'+'.join(desired['languages']) or 'Unknown'} "
                f"{desired['quality']} {desired['title']}"
            )
            if desired["rejections"]:
                print(f"    rejected: {'; '.join(desired['rejections'])}")
            print(f"    CFs: {', '.join(desired['custom_formats']) or '(none)'}")
        else:
            print("  best original+english/DA: none found")
        if item["suspicious_da_claims"]:
            print("  suspicious DA claims:")
            for release in item["suspicious_da_claims"]:
                print(f"    - score={release['score']} lang={'+'.join(release['languages'])} {release['title']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True, help="UTC or offset timestamp, e.g. 2026-05-30T05:00:00Z")
    parser.add_argument("--max-episodes", type=int, default=0, help="limit unique affected episodes checked; 0 means no limit")
    parser.add_argument("--top", type=int, default=3, help="candidate rows retained per episode")
    parser.add_argument("--sleep", type=float, default=0.0, help="seconds to sleep between manual release checks")
    parser.add_argument("--release-timeout", type=int, default=45, help="seconds to wait for each manual release check")
    parser.add_argument("--progress", action="store_true", help="print per-episode progress to stderr")
    parser.add_argument("--history-only", action="store_true", help="only summarize matching import history; do not query live releases")
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--base-url", default=SONARR_URL)
    parser.add_argument("--config", default=SONARR_CONFIG)
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
