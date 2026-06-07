#!/usr/bin/env python3
"""Audit media files for subtitle tracks whose tags do not match their text."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ENGLISH_LANGUAGE_VALUES = {"en", "eng", "english"}
CJK_RANGES = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x20000, 0x2A6DF),
    (0x2A700, 0x2B73F),
    (0x2B740, 0x2B81F),
    (0x2B820, 0x2CEAF),
)


def parse_path_map(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("path maps must use SRC=DST")
    src, dst = value.split("=", 1)
    src = src.rstrip("/")
    dst = dst.rstrip("/")
    if not src or not dst:
        raise argparse.ArgumentTypeError("path maps must use non-empty SRC=DST")
    return src, dst


def mapped_path(path: str, path_maps: list[tuple[str, str]]) -> str:
    for src, dst in path_maps:
        if path == src:
            return dst
        if path.startswith(src + "/"):
            return dst + path[len(src):]
    return path


def run_json(command: list[str], timeout: int) -> Any:
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "command failed").strip())
    return json.loads(completed.stdout)


def ffprobe_streams(path: str, timeout: int) -> list[dict[str, Any]]:
    payload = run_json(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=index,codec_type,codec_name:stream_tags=language,title:stream_disposition=default,forced",
            "-of",
            "json",
            path,
        ],
        timeout,
    )
    return [stream for stream in payload.get("streams") or [] if isinstance(stream, dict)]


def is_cjk_character(character: str) -> bool:
    codepoint = ord(character)
    return any(start <= codepoint <= end for start, end in CJK_RANGES)


def subtitle_text_stats(text: str) -> dict[str, int]:
    return {
        "chars": len(text),
        "ascii_letters": sum(1 for character in text if character.isascii() and character.isalpha()),
        "nonascii": sum(1 for character in text if not character.isascii()),
        "cjk": sum(1 for character in text if is_cjk_character(character)),
    }


def stream_language_values(stream: dict[str, Any]) -> set[str]:
    tags = stream.get("tags") if isinstance(stream.get("tags"), dict) else {}
    values = {
        str(tags.get("language") or "").strip().casefold(),
        str(tags.get("title") or "").strip().casefold(),
    }
    return {value for value in values if value}


def stream_is_target_language(stream: dict[str, Any], target_languages: set[str]) -> bool:
    return bool(stream_language_values(stream) & target_languages)


def extract_subtitle_text(path: str, stream_index: int, timeout: int, sample_chars: int) -> tuple[str, str | None]:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            path,
            "-map",
            f"0:{stream_index}",
            "-f",
            "srt",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0 and not completed.stdout:
        return "", (completed.stderr or "subtitle extraction failed").strip()
    return completed.stdout[:sample_chars], None


def english_cjk_mismatch(stats: dict[str, int], min_cjk_chars: int, min_cjk_fraction: float) -> bool:
    cjk = stats["cjk"]
    ascii_letters = stats["ascii_letters"]
    comparable = max(1, cjk + ascii_letters)
    return cjk >= min_cjk_chars and cjk / comparable >= min_cjk_fraction and cjk > ascii_letters


def audit_path(path: str, args: argparse.Namespace) -> dict[str, Any]:
    host_path = mapped_path(path, args.path_map)
    result: dict[str, Any] = {
        "path": path,
        "hostPath": host_path,
        "status": "ok",
        "issues": [],
        "streams": [],
    }
    if not Path(host_path).exists():
        result["status"] = "error"
        result["error"] = "file not found"
        return result

    try:
        streams = ffprobe_streams(host_path, args.probe_timeout)
    except (OSError, subprocess.TimeoutExpired, RuntimeError, json.JSONDecodeError) as exc:
        result["status"] = "error"
        result["error"] = str(exc)
        return result

    subtitle_streams = [stream for stream in streams if stream.get("codec_type") == "subtitle"]
    target_languages = set(args.language)
    first_target_seen = False
    safe_target_streams: list[int] = []

    for stream in subtitle_streams[:args.max_subtitle_streams]:
        stream_index = int(stream.get("index") or -1)
        stream_record: dict[str, Any] = {
            "index": stream_index,
            "codec": stream.get("codec_name"),
            "languageValues": sorted(stream_language_values(stream)),
            "targetLanguage": stream_is_target_language(stream, target_languages),
        }
        if stream_index < 0 or not stream_record["targetLanguage"]:
            result["streams"].append(stream_record)
            continue

        first_target = not first_target_seen
        first_target_seen = True
        try:
            text, error = extract_subtitle_text(host_path, stream_index, args.stream_timeout, args.sample_chars)
        except (OSError, subprocess.TimeoutExpired) as exc:
            text, error = "", str(exc)
        if error:
            stream_record["sampleError"] = error
            result["streams"].append(stream_record)
            continue

        stats = subtitle_text_stats(text)
        stream_record["sampleStats"] = stats
        mismatch = english_cjk_mismatch(stats, args.min_cjk_chars, args.min_cjk_fraction)
        stream_record["mismatch"] = mismatch
        if mismatch:
            issue = {
                "type": "english_subtitle_cjk_mismatch",
                "streamIndex": stream_index,
                "firstTargetLanguageStream": first_target,
                "languageValues": stream_record["languageValues"],
                "sampleStats": stats,
            }
            result["issues"].append(issue)
        else:
            safe_target_streams.append(stream_index)
        result["streams"].append(stream_record)

    if result["issues"]:
        result["status"] = "issues"
        result["safeTargetSubtitleStreams"] = safe_target_streams
    return result


def print_human(results: list[dict[str, Any]]) -> None:
    for result in results:
        print(f"{result['path']} -> {result['status']}")
        if result.get("error"):
            print(f"  error: {result['error']}")
        for issue in result.get("issues") or []:
            stats = issue["sampleStats"]
            first = " first-target" if issue.get("firstTargetLanguageStream") else ""
            print(
                "  issue: stream {stream}{first} tagged as {langs} but sampled "
                "ascii_letters={ascii_letters} cjk={cjk}".format(
                    stream=issue["streamIndex"],
                    first=first,
                    langs=",".join(issue["languageValues"]),
                    ascii_letters=stats["ascii_letters"],
                    cjk=stats["cjk"],
                )
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="media files to audit")
    parser.add_argument("--json", action="store_true", help="emit JSON results")
    parser.add_argument(
        "--language",
        action="append",
        default=["en", "eng", "english"],
        help="subtitle language tag/title value to audit; may be repeated",
    )
    parser.add_argument("--path-map", type=parse_path_map, action="append", default=[])
    parser.add_argument("--probe-timeout", type=int, default=30)
    parser.add_argument("--stream-timeout", type=int, default=20)
    parser.add_argument("--sample-chars", type=int, default=20000)
    parser.add_argument("--max-subtitle-streams", type=int, default=12)
    parser.add_argument("--min-cjk-chars", type=int, default=40)
    parser.add_argument("--min-cjk-fraction", type=float, default=0.25)
    parser.add_argument("--fail-on-issue", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.language = [language.strip().casefold() for language in args.language if language.strip()]
    results = [audit_path(path, args) for path in args.paths]
    if args.json:
        json.dump(results, sys.stdout, sort_keys=True, separators=(",", ":"))
        sys.stdout.write("\n")
    else:
        print_human(results)
    if any(result["status"] == "error" for result in results):
        return 2
    if args.fail_on_issue and any(result["status"] == "issues" for result in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
