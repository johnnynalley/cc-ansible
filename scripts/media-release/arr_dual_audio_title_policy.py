#!/usr/bin/env python3
"""Patch Arr dual-audio custom formats to trust explicit title markers.

Run this on docker-vm. It reads local Sonarr/Radarr config.xml files for API
keys, backs up current custom formats and quality profiles, then updates:

- Anime Dual Audio: title marker based, no parsed-language dependency.
- Language - Not Original: does not apply when explicit DA title markers exist.
- Dubs Only (Block): requires a dub-only title marker and does not apply when
  explicit DA title markers exist.

The backup contains no API keys.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DA_CF_NAME = "Anime Dual Audio"
LANG_NOT_ORIGINAL_CF_NAME = "Language - Not Original"
DUBS_ONLY_CF_NAME = "Dubs Only (Block)"

DA_TITLE_REGEX = (
    r"dual[ ._-]?audio|multi[ ._-]?audio|"
    r"\bdual\b(?![ ._-]sub(?:s|titles?)?\b)(?![ ._-]?(?:franceira|yg)\b)|"
    r"\b(ja|jp|jpn|japanese|zh|chi|zho|chinese|ko|kor|korean)"
    r"\b[ ._+&-]*\b(en|eng|english)\b|"
    r"\b(en|eng|english)\b[ ._+&-]*\b"
    r"(ja|jp|jpn|japanese|zh|chi|zho|chinese|ko|kor|korean)\b"
)
SINGLE_ORIGINAL_LANGUAGE_REGEX = r"\[(JA|JP|JPN|ZH|CHI|ZHO|KO|KOR)\]"
NON_ENGLISH_DUB_MARKER_REGEX = (
    r"(?=.*\b(?:german|deutsch|spanish|espa(?:n|ñ)ol|castellano|latino|"
    r"french|fran(?:c|ç)ais|italian|italiano|portuguese|portugu[eê]s|"
    r"russian|russisch|hindi|arabic)\b)"
    r"(?!.*\b(?:en|eng|english)\b)"
    r".*\b(?:dub|dubs|dubbed|audio|synchro|synchro[nn]is(?:e|é|ee|ed))\b"
)


@dataclass(frozen=True)
class Arr:
    name: str
    base_url: str
    config_path: Path


def read_api_key(path: Path) -> str:
    root = ET.parse(path).getroot()
    api_key = root.findtext("ApiKey")
    if not api_key:
        raise RuntimeError(f"{path}: ApiKey not found")
    return api_key.strip()


def request_json(
    arr: Arr,
    api_key: str,
    method: str,
    path: str,
    payload: Any | None = None,
    params: dict[str, Any] | None = None,
) -> Any:
    query = ""
    if params:
        query = "?" + urllib.parse.urlencode(params, doseq=True)
    url = f"{arr.base_url.rstrip('/')}{path}{query}"
    data = None
    headers = {"X-Api-Key": api_key}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = response.read().decode("utf-8", errors="replace")
            if not body:
                return None
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{arr.name} {method} {path} failed: {exc.code} {body}") from exc


def spec_field(spec: dict[str, Any], name: str) -> dict[str, Any] | None:
    for field in spec.get("fields") or []:
        if field.get("name") == name:
            return field
    return None


def set_regex(spec: dict[str, Any], value: str) -> None:
    field = spec_field(spec, "value")
    if field is None:
        spec.setdefault("fields", []).append({"name": "value", "value": value})
    else:
        field["value"] = value


def release_title_spec(name: str, value: str, *, negate: bool, required: bool) -> dict[str, Any]:
    return {
        "name": name,
        "implementation": "ReleaseTitleSpecification",
        "implementationName": "Release Title",
        "infoLink": "https://wiki.servarr.com/sonarr/settings#custom-formats-2",
        "negate": negate,
        "required": required,
        "fields": [
            {
                "order": 0,
                "name": "value",
                "label": "Regular Expression",
                "helpText": "Custom Format RegEx is Case Insensitive",
                "value": value,
                "type": "textbox",
                "advanced": False,
                "privacy": "normal",
                "isFloat": False,
            }
        ],
    }


def patch_dual_audio(custom_format: dict[str, Any]) -> bool:
    before = json.dumps(custom_format, sort_keys=True)
    specs = custom_format.setdefault("specifications", [])

    kept: list[dict[str, Any]] = []
    title_spec_found = False
    single_language_spec_found = False
    non_english_dub_spec_found = False

    for spec in specs:
        if spec.get("implementation") == "LanguageSpecification":
            continue
        if spec.get("name") == "Dual Audio":
            spec["implementation"] = "ReleaseTitleSpecification"
            spec["implementationName"] = "Release Title"
            spec["negate"] = False
            spec["required"] = True
            set_regex(spec, DA_TITLE_REGEX)
            title_spec_found = True
        elif spec.get("name") == "Not Single Language Only":
            spec["implementation"] = "ReleaseTitleSpecification"
            spec["implementationName"] = "Release Title"
            spec["negate"] = True
            spec["required"] = True
            set_regex(spec, SINGLE_ORIGINAL_LANGUAGE_REGEX)
            single_language_spec_found = True
        elif spec.get("name") == "Exclude Explicit Non-English Dub Markers":
            spec["implementation"] = "ReleaseTitleSpecification"
            spec["implementationName"] = "Release Title"
            spec["negate"] = True
            spec["required"] = True
            set_regex(spec, NON_ENGLISH_DUB_MARKER_REGEX)
            non_english_dub_spec_found = True
        kept.append(spec)

    if not title_spec_found:
        kept.append(release_title_spec("Dual Audio", DA_TITLE_REGEX, negate=False, required=True))
    if not single_language_spec_found:
        kept.append(
            release_title_spec(
                "Not Single Language Only",
                SINGLE_ORIGINAL_LANGUAGE_REGEX,
                negate=True,
                required=True,
            )
        )
    if not non_english_dub_spec_found:
        kept.append(
            release_title_spec(
                "Exclude Explicit Non-English Dub Markers",
                NON_ENGLISH_DUB_MARKER_REGEX,
                negate=True,
                required=True,
            )
        )

    custom_format["specifications"] = kept
    after = json.dumps(custom_format, sort_keys=True)
    return before != after


def patch_language_not_original(custom_format: dict[str, Any]) -> bool:
    before = json.dumps(custom_format, sort_keys=True)
    specs = custom_format.setdefault("specifications", [])

    found = False
    for spec in specs:
        if spec.get("name") == "Exclude Explicit Dual Audio Title Markers":
            spec["implementation"] = "ReleaseTitleSpecification"
            spec["implementationName"] = "Release Title"
            spec["negate"] = True
            spec["required"] = True
            set_regex(spec, DA_TITLE_REGEX)
            found = True
            break

    if not found:
        specs.append(
            release_title_spec(
                "Exclude Explicit Dual Audio Title Markers",
                DA_TITLE_REGEX,
                negate=True,
                required=True,
            )
        )

    after = json.dumps(custom_format, sort_keys=True)
    return before != after


def patch_dubs_only(custom_format: dict[str, Any]) -> bool:
    before = json.dumps(custom_format, sort_keys=True)
    specs = custom_format.setdefault("specifications", [])

    exclude_da_found = False
    for spec in specs:
        if spec.get("name") == "No Dubs Title":
            spec["implementation"] = "ReleaseTitleSpecification"
            spec["implementationName"] = "Release Title"
            spec["negate"] = False
            spec["required"] = True
        if spec.get("name") == "Exclude Explicit Dual Audio Title Markers":
            spec["implementation"] = "ReleaseTitleSpecification"
            spec["implementationName"] = "Release Title"
            spec["negate"] = True
            spec["required"] = True
            set_regex(spec, DA_TITLE_REGEX)
            exclude_da_found = True

    if not exclude_da_found:
        specs.append(
            release_title_spec(
                "Exclude Explicit Dual Audio Title Markers",
                DA_TITLE_REGEX,
                negate=True,
                required=True,
            )
        )

    after = json.dumps(custom_format, sort_keys=True)
    return before != after


def find_by_name(custom_formats: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for custom_format in custom_formats:
        if custom_format.get("name") == name:
            return custom_format
    return None


def backup_state(
    backup_root: Path,
    timestamp: str,
    arr: Arr,
    custom_formats: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
) -> Path:
    backup_dir = backup_root / f"{timestamp}-dual-audio-title-policy"
    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / f"{arr.name}-customformat.json").write_text(
        json.dumps(custom_formats, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (backup_dir / f"{arr.name}-qualityprofile.json").write_text(
        json.dumps(profiles, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return backup_dir


def parse_smoke(arr: Arr, api_key: str, title: str) -> dict[str, Any]:
    parsed = request_json(arr, api_key, "GET", "/api/v3/parse", params={"title": title})
    return {
        "title": title,
        "languages": [item.get("name") for item in parsed.get("languages") or []],
        "score": parsed.get("customFormatScore"),
        "customFormats": [item.get("name") for item in parsed.get("customFormats") or []],
    }


def patch_arr(arr: Arr, backup_root: Path, timestamp: str, apply: bool) -> dict[str, Any]:
    api_key = read_api_key(arr.config_path)
    custom_formats = request_json(arr, api_key, "GET", "/api/v3/customformat")
    profiles = request_json(arr, api_key, "GET", "/api/v3/qualityprofile")
    backup_dir = backup_state(backup_root, timestamp, arr, custom_formats, profiles)

    changes: list[str] = []
    for name, patcher in (
        (DA_CF_NAME, patch_dual_audio),
        (LANG_NOT_ORIGINAL_CF_NAME, patch_language_not_original),
        (DUBS_ONLY_CF_NAME, patch_dubs_only),
    ):
        custom_format = find_by_name(custom_formats, name)
        if custom_format is None:
            continue
        changed = patcher(custom_format)
        if changed:
            changes.append(name)
            if apply:
                request_json(
                    arr,
                    api_key,
                    "PUT",
                    f"/api/v3/customformat/{custom_format['id']}",
                    payload=custom_format,
                )

    smoke_titles = [
        "[Judas] Bleach 056-111 [BD 1080p][HEVC x265 10bit][Dual-Audio][Eng-Sub]",
        "JoJos.Bizarre.Adventure.2012.S03E04.1080p.BluRay.x265.SDR.Opus.2.0.Dual.Yogi-HONE",
        "JoJos Bizarre Adventure - S05E38 - DUAL 1080p WEB H.264 -NanDesuKa (NF)",
        "Evangelion.2.22.You.Can.Not.Advance.2009.1080p.BluRay.FLAC.7ch.X265-Baws.DUAL-Franceira",
        "Demon Slayer Kimetsu no Yaiba Infinity Castle 2025 1080p WEB-DL H 264 Dual-YG",
        "[KaiDubs] JoJo's Bizarre Adventure - Golden Wind - 28 [1080p] [8-bit] [Dual Audio] [JPBD]",
        "[KaiDubs] JoJo's Bizarre Adventure - Golden Wind - 28 [1080p] [English Dub] [CC] [AS-DL]",
        "[Fuchs] Love, Chunibyo & Other Delusions! - S00E02 (BD 1080p AVC Opus 2.0) [Multi-Audio] (Japanese, German/Deutsch Dubs)",
        "[EMBER] Jujutsu Kaisen S3 - 11 [JA+EN] [x265].mkv",
        "[EMBER] Jujutsu Kaisen S3 - 11 [JA] [x265].mkv",
    ]
    if apply and arr.name == "sonarr":
        smokes = [parse_smoke(arr, api_key, title) for title in smoke_titles]
    else:
        smokes = []

    return {
        "arr": arr.name,
        "backup_dir": str(backup_dir),
        "apply": apply,
        "changed": changes,
        "smoke": smokes,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="apply changes; default is dry-run backup only")
    parser.add_argument("--sonarr-url", default="http://127.0.0.1:8989")
    parser.add_argument("--radarr-url", default="http://127.0.0.1:7878")
    parser.add_argument("--sonarr-config", default="/opt/media-stack/sonarr/config.xml")
    parser.add_argument("--radarr-config", default="/opt/media-stack/radarr/config.xml")
    parser.add_argument("--backup-root", default="/opt/media-stack/arr-policy-backups")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = Path(args.backup_root)
    targets = [
        Arr("sonarr", args.sonarr_url, Path(args.sonarr_config)),
        Arr("radarr", args.radarr_url, Path(args.radarr_config)),
    ]
    results = [patch_arr(arr, backup_root, timestamp, args.apply) for arr in targets]
    json.dump(results, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
