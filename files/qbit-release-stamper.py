#!/usr/bin/env python3
"""Preserve release-title metadata in qBittorrent payload file names.

Sonarr/Radarr score custom formats from the release title at grab time, but
they re-evaluate individual file names at import time. Multi-file torrents can
therefore lose DA/x265 evidence when the payload file names are generic. This
script uses qBittorrent's renameFile API so the torrent metadata and seeding
state stay aligned with the filesystem rename.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path
from pathlib import PurePosixPath


VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv"}
LANGUAGE_COMBO_RE = re.compile(r"(?i)\b(?:JA|ZH|KO|EN)(?:\s*\+\s*(?:JA|ZH|KO|EN))+\b")
X265_RE = re.compile(r"(?i)(?:\b[xh][\s._-]?265\b|\bhevc\b)")
BARE_EPISODE_RE = re.compile(r"(?i)^(?:\[[^\]]+\]\s*)?S\d{1,2}E\d{1,3}(?:\b|[\s._-])")
PLATFORM_TAG_PATTERNS = (
    ("CR", re.compile(r"(?i)(?:^|[\s._\-\[\(])(?:CR|Crunchyroll)(?:$|[\s._\-\]\)])")),
    ("NF", re.compile(r"(?i)(?:^|[\s._\-\[\(])(?:NF|Netflix)(?:$|[\s._\-\]\)])")),
    ("DSNP", re.compile(r"(?i)(?:^|[\s._\-\[\(])(?:DSNP|Disney(?:\+|Plus)?)(?:$|[\s._\-\]\)])")),
    ("AMZN", re.compile(r"(?i)(?:^|[\s._\-\[\(])(?:AMZN|Amazon)(?:$|[\s._\-\]\)])")),
    ("FUNi", re.compile(r"(?i)(?:^|[\s._\-\[\(])(?:FUNi|Funimation)(?:$|[\s._\-\]\)])")),
    ("VRV", re.compile(r"(?i)(?:^|[\s._\-\[\(])VRV(?:$|[\s._\-\]\)])")),
    ("ADN", re.compile(r"(?i)(?:^|[\s._\-\[\(])ADN(?:$|[\s._\-\]\)])")),
    ("ABEMA", re.compile(r"(?i)(?:^|[\s._\-\[\(])ABEMA(?:$|[\s._\-\]\)])")),
    ("ATVP", re.compile(r"(?i)(?:^|[\s._\-\[\(])(?:ATVP|AppleTV\+?)(?:$|[\s._\-\]\)])")),
    ("HMAX", re.compile(r"(?i)(?:^|[\s._\-\[\(])(?:HMAX|HBO.?Max)(?:$|[\s._\-\]\)])")),
    ("HULU", re.compile(r"(?i)(?:^|[\s._\-\[\(])HULU(?:$|[\s._\-\]\)])")),
    ("PCOK", re.compile(r"(?i)(?:^|[\s._\-\[\(])(?:PCOK|Peacock)(?:$|[\s._\-\]\)])")),
    ("PMTP", re.compile(r"(?i)(?:^|[\s._\-\[\(])(?:PMTP|Paramount\+?)(?:$|[\s._\-\]\)])")),
    ("SHO", re.compile(r"(?i)(?:^|[\s._\-\[\(])(?:SHO|Showtime)(?:$|[\s._\-\]\)])")),
    ("STAN", re.compile(r"(?i)(?:^|[\s._\-\[\(])STAN(?:$|[\s._\-\]\)])")),
)
LEADING_GROUP_RE = re.compile(r"^\[([A-Za-z0-9][A-Za-z0-9._-]{1,31})\]")
TRAILING_GROUP_RE = re.compile(r"-([A-Za-z0-9][A-Za-z0-9._]{1,31})$")
NON_RELEASE_GROUPS = {
    "1080p",
    "10bit",
    "2160p",
    "480p",
    "576p",
    "720p",
    "8bit",
    "aac",
    "abema",
    "adn",
    "amzn",
    "atvp",
    "audio",
    "av1",
    "batch",
    "bd",
    "bdrip",
    "bit",
    "bluray",
    "cr",
    "dsnp",
    "dts",
    "dual-audio",
    "dvd",
    "eng-sub",
    "english",
    "flac",
    "funi",
    "h264",
    "h265",
    "hdtv",
    "hevc",
    "hmax",
    "hulu",
    "japanese",
    "multi-audio",
    "nf",
    "pcok",
    "pmtp",
    "proper",
    "repack",
    "season",
    "sho",
    "stan",
    "sub",
    "v2",
    "v3",
    "vrv",
    "web",
    "web-dl",
    "webdl",
    "webrip",
    "x264",
    "x265",
}
HEVC_MARKERS = (
    b"V_MPEGH/ISO/HEVC",
    b"hvc1",
    b"hev1",
    b"x265",
    b"HEVC",
)
SCAN_BYTES = 8 * 1024 * 1024
DEFAULT_DUAL_AUDIO_ORIGINAL_LANGUAGES = {"jpn"}
LANGUAGE_TAGS = {"jpn": "JA", "zho": "ZH", "kor": "KO", "eng": "EN"}
VIDEO_TRACK_TYPE = 1
AUDIO_TRACK_TYPE = 2
MKV_SEGMENT_ID = 0x18538067
MKV_TRACKS_ID = 0x1654AE6B
MKV_TRACK_ENTRY_ID = 0xAE
MKV_TRACK_TYPE_ID = 0x83
MKV_CODEC_ID = 0x86
MKV_TRACK_NAME_ID = 0x536E
MKV_LANGUAGE_ID = 0x22B59C
MKV_LANGUAGE_IETF_ID = 0x22B59D


def log(message: str) -> None:
    print(f"qbit-release-stamper: {message}", flush=True)


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def write_event(event: dict[str, object]) -> None:
    path = os.environ.get("STAMPER_EVENT_LOG", "/config/scripts/release-stamper-events.jsonl")
    if not path:
        return
    event.setdefault("observedAt", utc_now())
    event.setdefault("client", "qbittorrent")
    try:
        event_path = Path(path)
        event_path.parent.mkdir(parents=True, exist_ok=True)
        with event_path.open("a", encoding="utf-8") as handle:
            json.dump(event, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
        event_path.chmod(0o640)
    except Exception as exc:  # noqa: BLE001 - telemetry must not block imports
        log(f"event log write failed: {exc}")


def load_env(path: str) -> None:
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip("'").strip('"')
            os.environ.setdefault(key.strip(), value)


class QbitClient:
    def __init__(self, api_url: str, username: str, password: str) -> None:
        self.api_url = api_url.rstrip("/")
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )
        self.username = username
        self.password = password

    def request(
        self,
        endpoint: str,
        data: dict[str, str] | None = None,
        expected: tuple[int, ...] = (200, 204),
    ) -> bytes:
        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        encoded = None
        if data is not None:
            encoded = urllib.parse.urlencode(data).encode("utf-8")
        request = urllib.request.Request(url, data=encoded)
        try:
            with self.opener.open(request, timeout=30) as response:
                status = response.getcode()
                body = response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{endpoint} failed with HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{endpoint} failed: {exc}") from exc

        if status not in expected:
            raise RuntimeError(f"{endpoint} returned unexpected HTTP {status}")
        return body

    def get_json(self, endpoint: str, params: dict[str, str] | None = None):
        if params:
            endpoint = f"{endpoint}?{urllib.parse.urlencode(params)}"
        body = self.request(endpoint)
        return json.loads(body.decode("utf-8"))

    def login(self) -> None:
        self.request(
            "auth/login",
            {"username": self.username, "password": self.password},
            expected=(200, 204),
        )

    def torrent_by_hash_or_name(self, torrent_hash: str, torrent_name: str):
        if torrent_hash and not torrent_hash.startswith("%"):
            torrents = self.get_json("torrents/info", {"hashes": torrent_hash})
            if torrents:
                return torrents[0]

        if torrent_name and not torrent_name.startswith("%"):
            torrents = self.get_json("torrents/info")
            matches = [torrent for torrent in torrents if torrent.get("name") == torrent_name]
            if matches:
                return matches[0]

        return None

    def files(self, torrent_hash: str):
        return self.get_json("torrents/files", {"hash": torrent_hash})

    def rename_file(self, torrent_hash: str, old_path: str, new_path: str) -> None:
        self.request(
            "torrents/renameFile",
            {"hash": torrent_hash, "oldPath": old_path, "newPath": new_path},
        )


def file_has_hevc_marker(path: Path | None) -> bool:
    if path is None or not path.is_file():
        return False

    try:
        size = path.stat().st_size
        with path.open("rb") as media_file:
            chunks = [media_file.read(SCAN_BYTES)]
            if size > SCAN_BYTES:
                media_file.seek(max(0, size - SCAN_BYTES))
                chunks.append(media_file.read(SCAN_BYTES))
    except OSError:
        return False

    if chunks and chunks[0].startswith(b"\x1a\x45\xdf\xa3") and mkv_has_hevc_video(chunks[0]):
        return True

    return any(marker in chunk for marker in HEVC_MARKERS for chunk in chunks)


def normalize_language(value: str) -> str | None:
    language = value.strip().lower().replace("_", "-")
    if not language:
        return None
    primary = language.split("-", 1)[0]
    mapping = {
        "en": "eng",
        "eng": "eng",
        "english": "eng",
        "ja": "jpn",
        "jp": "jpn",
        "jpn": "jpn",
        "japanese": "jpn",
        "zh": "zho",
        "zho": "zho",
        "chi": "zho",
        "chinese": "zho",
        "ko": "kor",
        "kr": "kor",
        "kor": "kor",
        "korean": "kor",
        "und": None,
        "unknown": None,
    }
    return mapping.get(primary, primary if primary.isalpha() and len(primary) in (2, 3) else None)


def language_from_text(value: str) -> set[str]:
    languages: set[str] = set()
    if re.search(r"(?i)\beng(?:lish)?\b", value):
        languages.add("eng")
    if re.search(r"(?i)\b(?:jpn|japanese)\b", value):
        languages.add("jpn")
    if re.search(r"(?i)\b(?:zho|chi|chinese)\b", value):
        languages.add("zho")
    if re.search(r"(?i)\b(?:kor|korean)\b", value):
        languages.add("kor")
    return languages


def read_ebml_id(data: bytes, offset: int) -> tuple[int, int] | None:
    if offset >= len(data):
        return None
    first = data[offset]
    mask = 0x80
    length = 1
    while length <= 4 and not first & mask:
        mask >>= 1
        length += 1
    if length > 4 or offset + length > len(data):
        return None
    return int.from_bytes(data[offset : offset + length], "big"), offset + length


def read_ebml_size(data: bytes, offset: int) -> tuple[int, int] | None:
    if offset >= len(data):
        return None
    first = data[offset]
    mask = 0x80
    length = 1
    while length <= 8 and not first & mask:
        mask >>= 1
        length += 1
    if length > 8 or offset + length > len(data):
        return None
    value = first & (mask - 1)
    for byte in data[offset + 1 : offset + length]:
        value = (value << 8) | byte
    return value, offset + length


def ebml_children(data: bytes, start: int, end: int):
    offset = start
    end = min(end, len(data))
    while offset < end:
        parsed_id = read_ebml_id(data, offset)
        if not parsed_id:
            return
        element_id, after_id = parsed_id
        parsed_size = read_ebml_size(data, after_id)
        if not parsed_size:
            return
        size, content_start = parsed_size
        if content_start > len(data):
            return
        content_end = min(content_start + size, len(data))
        yield element_id, content_start, content_end
        offset = content_end


def int_from_bytes(data: bytes) -> int:
    return int.from_bytes(data, "big") if data else 0


def text_from_bytes(data: bytes) -> str:
    return data.rstrip(b"\x00").decode("utf-8", errors="ignore")


def mkv_audio_languages(data: bytes) -> set[str]:
    languages: set[str] = set()
    segment_bounds: tuple[int, int] | None = None
    for element_id, content_start, content_end in ebml_children(data, 0, len(data)):
        if element_id == MKV_SEGMENT_ID:
            segment_bounds = (content_start, content_end)
            break
    if not segment_bounds:
        return languages

    tracks_bounds: tuple[int, int] | None = None
    for element_id, content_start, content_end in ebml_children(data, *segment_bounds):
        if element_id == MKV_TRACKS_ID:
            tracks_bounds = (content_start, content_end)
            break
    if not tracks_bounds:
        return languages

    for element_id, content_start, content_end in ebml_children(data, *tracks_bounds):
        if element_id != MKV_TRACK_ENTRY_ID:
            continue
        track_type = None
        track_languages: set[str] = set()
        for child_id, child_start, child_end in ebml_children(data, content_start, content_end):
            raw = data[child_start:child_end]
            if child_id == MKV_TRACK_TYPE_ID:
                track_type = int_from_bytes(raw)
            elif child_id in (MKV_LANGUAGE_ID, MKV_LANGUAGE_IETF_ID):
                language = normalize_language(text_from_bytes(raw))
                if language:
                    track_languages.add(language)
            elif child_id == MKV_TRACK_NAME_ID:
                track_languages.update(language_from_text(text_from_bytes(raw)))
        if track_type == AUDIO_TRACK_TYPE:
            languages.update(track_languages)
    return languages


def mkv_has_hevc_video(data: bytes) -> bool:
    segment_bounds: tuple[int, int] | None = None
    for element_id, content_start, content_end in ebml_children(data, 0, len(data)):
        if element_id == MKV_SEGMENT_ID:
            segment_bounds = (content_start, content_end)
            break
    if not segment_bounds:
        return False

    tracks_bounds: tuple[int, int] | None = None
    for element_id, content_start, content_end in ebml_children(data, *segment_bounds):
        if element_id == MKV_TRACKS_ID:
            tracks_bounds = (content_start, content_end)
            break
    if not tracks_bounds:
        return False

    for element_id, content_start, content_end in ebml_children(data, *tracks_bounds):
        if element_id != MKV_TRACK_ENTRY_ID:
            continue
        track_type = None
        codec_id = ""
        for child_id, child_start, child_end in ebml_children(data, content_start, content_end):
            raw = data[child_start:child_end]
            if child_id == MKV_TRACK_TYPE_ID:
                track_type = int_from_bytes(raw)
            elif child_id == MKV_CODEC_ID:
                codec_id = text_from_bytes(raw)
        if track_type == VIDEO_TRACK_TYPE and "HEVC" in codec_id.upper():
            return True

    return False


def mp4_language_from_bits(value: int) -> str | None:
    if not value:
        return None
    chars = []
    for shift in (10, 5, 0):
        chars.append(chr(((value >> shift) & 0x1F) + 0x60))
    return normalize_language("".join(chars))


def mp4_boxes(data: bytes, start: int, end: int):
    offset = start
    end = min(end, len(data))
    while offset + 8 <= end:
        size = int.from_bytes(data[offset : offset + 4], "big")
        box_type = data[offset + 4 : offset + 8]
        header = 8
        if size == 1 and offset + 16 <= end:
            size = int.from_bytes(data[offset + 8 : offset + 16], "big")
            header = 16
        elif size == 0:
            size = end - offset
        if size < header or offset + size > end:
            return
        yield box_type, offset + header, offset + size
        offset += size


def mp4_find_child(data: bytes, start: int, end: int, box_type: bytes) -> tuple[int, int] | None:
    for child_type, child_start, child_end in mp4_boxes(data, start, end):
        if child_type == box_type:
            return child_start, child_end
    return None


def mp4_audio_languages(data: bytes) -> set[str]:
    languages: set[str] = set()
    for box_type, moov_start, moov_end in mp4_boxes(data, 0, len(data)):
        if box_type != b"moov":
            continue
        for trak_type, trak_start, trak_end in mp4_boxes(data, moov_start, moov_end):
            if trak_type != b"trak":
                continue
            mdia = mp4_find_child(data, trak_start, trak_end, b"mdia")
            if not mdia:
                continue
            hdlr = mp4_find_child(data, *mdia, b"hdlr")
            mdhd = mp4_find_child(data, *mdia, b"mdhd")
            if not hdlr or not mdhd:
                continue
            hdlr_start, hdlr_end = hdlr
            if hdlr_start + 12 > hdlr_end or data[hdlr_start + 8 : hdlr_start + 12] != b"soun":
                continue
            mdhd_start, mdhd_end = mdhd
            if mdhd_start + 4 > mdhd_end:
                continue
            version = data[mdhd_start]
            language_offset = mdhd_start + (32 if version == 1 else 20)
            if language_offset + 2 > mdhd_end:
                continue
            language = mp4_language_from_bits(
                int.from_bytes(data[language_offset : language_offset + 2], "big")
            )
            if language:
                languages.add(language)
    return languages


def file_audio_languages(path: Path | None) -> set[str]:
    if path is None or not path.is_file():
        return set()
    probed_languages = ffprobe_audio_languages(path)
    if probed_languages:
        return probed_languages
    try:
        with path.open("rb") as media_file:
            data = media_file.read(SCAN_BYTES)
    except OSError:
        return set()
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return mkv_audio_languages(data)
    if path.suffix.lower() in {".mp4", ".m4v", ".mov"}:
        return mp4_audio_languages(data)
    return set()


def ffprobe_audio_languages(path: Path) -> set[str]:
    if not shutil.which("ffprobe"):
        return set()
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream_tags=language,title",
                "-of",
                "json",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception:
        return set()
    if result.returncode != 0 or not result.stdout:
        return set()
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return set()

    languages: set[str] = set()
    for stream in payload.get("streams") or []:
        tags = stream.get("tags") or {}
        for value in (tags.get("language"), tags.get("title")):
            if value:
                language = normalize_language(str(value))
                if language:
                    languages.add(language)
                languages.update(language_from_text(str(value)))
    return languages


def parse_languages(value: str) -> set[str]:
    return {
        language
        for raw_language in value.split(",")
        if (language := normalize_language(raw_language))
    }


def release_group_candidate(value: str | None) -> str | None:
    if not value:
        return None
    group = value.strip().strip("[]()")
    if not group or len(group) > 32 or " " in group:
        return None
    if group.casefold() in NON_RELEASE_GROUPS:
        return None
    if group.isdigit():
        return None
    return group


def title_without_extension(title: str) -> str:
    candidate = PurePosixPath(title).name if "/" in title else title
    suffix = PurePosixPath(candidate).suffix
    if suffix.lower() in VIDEO_EXTENSIONS:
        return candidate[: -len(suffix)]
    return title


def release_group_from_title(title: str) -> str | None:
    for raw_title in title.split(" || "):
        stripped = title_without_extension(raw_title.strip())
        trailing = TRAILING_GROUP_RE.search(stripped)
        if trailing and (group := release_group_candidate(trailing.group(1))):
            return group

        leading = LEADING_GROUP_RE.search(stripped)
        if leading and (group := release_group_candidate(leading.group(1))):
            return group

    return None


def file_has_release_group(file_name: str, release_group: str) -> bool:
    stem = title_without_extension(PurePosixPath(file_name).name)
    escaped = re.escape(release_group)
    return bool(
        re.search(rf"(?i)^\[{escaped}\]", stem)
        or re.search(rf"(?i)(?<![A-Za-z0-9])-{escaped}$", stem)
    )


def platform_tag_present(file_name: str, tag: str) -> bool:
    escaped = re.escape(tag)
    return bool(
        re.search(rf"(?i)(?:^|[\s._\-\[\(]){escaped}(?:$|[\s._\-\]\)])", file_name)
    )


def context_tags_from_title(parent_title: str, file_name: str) -> list[str]:
    tags: list[str] = []
    for tag, pattern in PLATFORM_TAG_PATTERNS:
        if not pattern.search(parent_title):
            continue
        if platform_tag_present(file_name, tag):
            continue
        tags.append(f"[{tag}]")
    return tags


def arr_queue_record_by_download_id(
    arr_api_url: str,
    arr_api_key: str,
    download_id: str,
) -> dict | None:
    if not arr_api_url or not arr_api_key or not download_id:
        return None

    url = (
        arr_api_url.rstrip("/")
        + "/queue?"
        + urllib.parse.urlencode(
            {
                "page": "1",
                "pageSize": "1000",
                "includeSeries": "true",
                "includeMovie": "true",
                "includeUnknownSeriesItems": "true",
            }
        )
    )
    request = urllib.request.Request(url, headers={"X-Api-Key": arr_api_key})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            queue = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - Arr context must be optional.
        log(f"optional Arr lookup failed for {arr_api_url}: {exc}")
        return None

    expected_download_id = download_id.upper()
    for record in queue.get("records", []):
        if str(record.get("downloadId") or "").upper() != expected_download_id:
            continue
        return record

    return None


def original_languages_from_arr_record(record: dict | None) -> set[str]:
    if not record:
        return set()
    media_item = record.get("series") or record.get("movie") or {}
    original_language = media_item.get("originalLanguage") or {}
    language = normalize_language(original_language.get("name", ""))
    return {language} if language else set()


def series_title_from_arr_record(record: dict | None) -> str | None:
    if not record:
        return None
    series = record.get("series")
    if not isinstance(series, dict):
        return None
    title = str(series.get("title") or "").strip()
    return title or None


def safe_title_component(title: str) -> str:
    cleaned = re.sub(r"[\\/:\x00]+", " ", title)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" ._-")


def path_with_episode_title_prefix(path: str, series_title: str | None) -> str:
    if not series_title:
        return path
    posix_path = PurePosixPath(path)
    basename = posix_path.name
    if not BARE_EPISODE_RE.search(basename):
        return path
    title = safe_title_component(series_title)
    if not title:
        return path
    return str(posix_path.with_name(f"{title} - {basename}"))


def parent_title_from_values(*values: str | None) -> str:
    titles: list[str] = []
    seen: set[str] = set()
    for value in values:
        title = str(value or "").strip()
        if not title or title.startswith("%"):
            continue
        key = title.casefold()
        if key in seen:
            continue
        seen.add(key)
        titles.append(title)
    return " || ".join(titles)


def language_combo_tag(path: Path | None, original_languages: set[str]) -> str | None:
    languages = file_audio_languages(path)
    original_languages = {language for language in original_languages if language != "eng"}
    if "eng" not in languages or not languages & original_languages:
        return None

    ordered_languages: list[str] = []
    for language in sorted(original_languages):
        if language in languages and language in LANGUAGE_TAGS and language not in ordered_languages:
            ordered_languages.append(language)
    for language in ("jpn", "zho", "kor"):
        if language in languages and language not in ordered_languages:
            ordered_languages.append(language)
    if "eng" not in ordered_languages:
        ordered_languages.append("eng")

    return "[" + "+".join(LANGUAGE_TAGS[language] for language in ordered_languages) + "]"


def absolute_file_path(torrent: dict, file_name: str) -> Path | None:
    save_path = torrent.get("save_path") or torrent.get("download_path") or ""
    if save_path:
        candidate = Path(save_path) / file_name
        if candidate.exists():
            return candidate

    content_path = torrent.get("content_path") or ""
    if content_path:
        candidate = Path(content_path)
        if candidate.is_file() and candidate.name == PurePosixPath(file_name).name:
            return candidate

    return None


def wanted_tags(
    file_name: str,
    media_path: Path | None,
    original_languages: set[str],
    parent_title: str,
) -> tuple[list[str], str | None]:
    basename = PurePosixPath(file_name).name
    tags: list[str] = []
    language_tag = language_combo_tag(media_path, original_languages)
    if language_tag and not LANGUAGE_COMBO_RE.search(basename):
        tags.append(language_tag)
    if file_has_hevc_marker(media_path) and not X265_RE.search(basename):
        tags.append("[x265]")
    tags.extend(context_tags_from_title(parent_title, basename))
    release_group = release_group_from_title(parent_title)
    if release_group and file_has_release_group(basename, release_group):
        release_group = None
    return tags, release_group


def rename_with_tags(
    path: str,
    tags: list[str],
    release_group: str | None,
    series_title: str | None,
) -> str:
    posix_path = PurePosixPath(path_with_episode_title_prefix(path, series_title))
    stem = posix_path.stem
    if tags:
        stem = f"{stem} {' '.join(tags)}"
    if release_group:
        stem = f"{stem} -{release_group}"
    return str(posix_path.with_name(f"{stem}{posix_path.suffix}"))


def parse_categories(value: str) -> set[str]:
    return {part.strip() for part in value.split(",") if part.strip()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hash", default="")
    parser.add_argument("--name", default="")
    parser.add_argument("--category", default="")
    parser.add_argument("--env", default="/config/scripts/qbit-release-stamper.env")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_env(args.env)
    api_url = os.environ.get("QBIT_API", "http://127.0.0.1:8085/api/v2")
    username = os.environ.get("QBIT_USER", "")
    password = os.environ.get("QBIT_PASS", "")
    allowed_categories = parse_categories(
        os.environ.get("QBIT_STAMP_CATEGORIES", "tv-sonarr,sonarr,radarr")
    )
    event: dict[str, object] = {
        "client": "qbittorrent",
        "download_name": args.name,
        "category": args.category,
        "dry_run": args.dry_run,
    }

    if not username or not password:
        log("missing QBIT_USER/QBIT_PASS; skipping")
        write_event({**event, "result": "skipped", "reason": "missing_credentials"})
        return 0

    try:
        client = QbitClient(api_url, username, password)
        client.login()
        torrent = client.torrent_by_hash_or_name(args.hash, args.name)
        if not torrent:
            log("torrent not found; skipping")
            write_event({**event, "result": "skipped", "reason": "torrent_not_found"})
            return 0

        category = args.category if args.category and not args.category.startswith("%") else ""
        category = category or torrent.get("category", "")
        event.update({"download_name": torrent.get("name", args.name), "category": category})
        if category not in allowed_categories:
            log(f"category {category!r} is not enabled for stamping")
            write_event({**event, "result": "skipped", "reason": "category_disabled"})
            return 0

        progress = float(torrent.get("progress") or 0)
        if not args.force and progress < 0.999:
            log(f"torrent {torrent.get('name', '')!r} is not complete; skipping")
            write_event({**event, "result": "skipped", "reason": "torrent_incomplete"})
            return 0

        torrent_hash = torrent.get("hash") or args.hash
        sonarr_record = arr_queue_record_by_download_id(
            os.environ.get("SONARR_API", ""),
            os.environ.get("SONARR_API_KEY", ""),
            torrent_hash,
        )
        radarr_record = None
        if not sonarr_record:
            radarr_record = arr_queue_record_by_download_id(
                os.environ.get("RADARR_API", ""),
                os.environ.get("RADARR_API_KEY", ""),
                torrent_hash,
            )
        arr_record = sonarr_record or radarr_record
        original_languages = (
            original_languages_from_arr_record(arr_record)
            or parse_languages(os.environ.get("DA_ORIGINAL_LANGUAGES", ""))
            or DEFAULT_DUAL_AUDIO_ORIGINAL_LANGUAGES
        )
        series_title = series_title_from_arr_record(arr_record)
        parent_title = parent_title_from_values(
            torrent.get("name"),
            args.name,
            arr_record.get("title") if arr_record else None,
            arr_record.get("downloadTitle") if arr_record else None,
        )
        log(
            "processing torrent={torrent!r} category={category!r} "
            "original_language(s)={languages} parent_title={parent!r}".format(
                torrent=torrent.get("name", ""),
                category=category,
                languages=", ".join(sorted(original_languages)),
                parent=parent_title,
            )
        )

        changes = 0
        videos_scanned = 0
        skipped_no_stamp = 0
        for torrent_file in client.files(torrent_hash):
            old_path = torrent_file.get("name", "")
            if PurePosixPath(old_path).suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            videos_scanned += 1

            tags, release_group = wanted_tags(
                old_path,
                absolute_file_path(torrent, old_path),
                original_languages,
                parent_title,
            )
            if not tags and not release_group:
                prefixed_path = path_with_episode_title_prefix(old_path, series_title)
                if prefixed_path == old_path:
                    skipped_no_stamp += 1
                    log(f"no stamp needed for {old_path!r}")
                    continue

            new_path = rename_with_tags(old_path, tags, release_group, series_title)
            if new_path == old_path:
                continue

            if args.dry_run:
                log(
                    f"would rename {old_path!r} -> {new_path!r} "
                    f"tags={tags} release_group={release_group!r}"
                )
            else:
                client.rename_file(torrent_hash, old_path, new_path)
                log(
                    f"renamed {old_path!r} -> {new_path!r} "
                    f"tags={tags} release_group={release_group!r}"
                )
            changes += 1

        action = "candidate rename(s)" if args.dry_run else "rename(s)"
        log(
            f"completed with {changes} {action}; "
            f"videos_scanned={videos_scanned} skipped_no_stamp={skipped_no_stamp}"
        )
        write_event(
            {
                **event,
                "result": "completed",
                "parent_title": parent_title,
                "original_languages": sorted(original_languages),
                "changes": changes,
                "videos_scanned": videos_scanned,
                "skipped_no_stamp": skipped_no_stamp,
            }
        )
    except Exception as exc:  # noqa: BLE001 - post-processing must not fail imports
        log(f"error: {exc}")
        write_event({**event, "result": "error", "error": str(exc)})
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
