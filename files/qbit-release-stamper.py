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
import collections
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
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
EPISODE_TOKEN_RE = re.compile(r"(?i)\bS\d{1,2}E\d{1,3}\b")
EPISODE_PREFIX_RE = re.compile(
    r"(?i)^(?P<group>\[[^\]]+\]\s*)?.*?(?P<episode>S\d{1,2}E\d{1,3}.*)$"
)
EXPLICIT_EPISODE_RE = re.compile(r"(?i)\bS(?P<season>\d{1,2})E(?P<episode>\d{1,3})\b")
SEASON_NUMBER_EPISODE_RE = re.compile(
    r"(?i)\bS(?P<season>\d{1,2})\s*[-._]\s*(?P<episode>\d{1,3})\b"
)
BARE_NUMBERED_EPISODE_RE = re.compile(
    r"(?P<prefix>\s+-\s+)(?P<number>\d{1,4})(?P<suffix>(?:\s+-\s+|\s+\[))"
)
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


def env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


class QbitClient:
    def __init__(
        self,
        api_url: str,
        username: str,
        password: str,
        retries: int = 3,
        retry_delay: int = 2,
        timeout: int = 60,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )
        self.username = username
        self.password = password
        self.retries = retries
        self.retry_delay = retry_delay
        self.timeout = timeout

    def request(
        self,
        endpoint: str,
        data: dict[str, str] | None = None,
        expected: tuple[int, ...] = (200, 204),
        retries: int | None = None,
        retry_delay: int | None = None,
        timeout: int | None = None,
    ) -> bytes:
        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        encoded = None
        if data is not None:
            encoded = urllib.parse.urlencode(data).encode("utf-8")
        last_error: Exception | None = None
        retries = retries or self.retries
        retry_delay = retry_delay or self.retry_delay
        timeout = timeout or self.timeout
        for attempt in range(1, retries + 1):
            request = urllib.request.Request(url, data=encoded)
            try:
                with self.opener.open(request, timeout=timeout) as response:
                    status = response.getcode()
                    body = response.read()
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                last_error = RuntimeError(f"{endpoint} failed with HTTP {exc.code}: {body}")
                if exc.code < 500 or attempt >= retries:
                    raise last_error from exc
            except (TimeoutError, urllib.error.URLError, OSError) as exc:
                last_error = RuntimeError(
                    f"{endpoint} failed on attempt {attempt}/{retries}: {exc}"
                )
                if attempt >= retries:
                    raise last_error from exc
            else:
                if status not in expected:
                    raise RuntimeError(f"{endpoint} returned unexpected HTTP {status}")
                return body
            log(
                f"{endpoint} failed on attempt {attempt}/{retries}; "
                f"retrying in {retry_delay}s"
            )
            time.sleep(retry_delay)

        raise RuntimeError(f"{endpoint} failed after {retries} attempts: {last_error}")

    def get_json(
        self,
        endpoint: str,
        params: dict[str, str] | None = None,
        retries: int | None = None,
        retry_delay: int | None = None,
        timeout: int | None = None,
    ):
        if params:
            endpoint = f"{endpoint}?{urllib.parse.urlencode(params)}"
        body = self.request(endpoint, retries=retries, retry_delay=retry_delay, timeout=timeout)
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

    def files(
        self,
        torrent_hash: str,
        retries: int | None = None,
        retry_delay: int | None = None,
        timeout: int | None = None,
    ):
        return self.get_json(
            "torrents/files",
            {"hash": torrent_hash},
            retries=retries,
            retry_delay=retry_delay,
            timeout=timeout,
        )

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
        or re.search(rf"(?i)-{escaped}$", stem)
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


def grab_context_by_download_id(context_api_url: str, download_id: str) -> dict | None:
    if not context_api_url or not download_id:
        return None
    url = context_api_url.rstrip("/") + "/v1/context/" + urllib.parse.quote(download_id, safe="")
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            log(f"optional grab-context lookup failed: HTTP {exc.code}")
        return None
    except Exception as exc:  # noqa: BLE001 - persisted context is optional.
        log(f"optional grab-context lookup failed: {exc}")
        return None
    context = payload.get("context") if isinstance(payload, dict) else None
    return context if isinstance(context, dict) else None


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


def expected_episodes_from_context(
    context: dict | None,
    arr_record: dict | None,
) -> list[dict[str, int]]:
    episodes = [
        dict(item)
        for item in (context or {}).get("expected_episodes", [])
        if isinstance(item, dict)
    ]
    record_episode = (arr_record or {}).get("episode")
    if isinstance(record_episode, dict):
        record_id = record_episode.get("id")
        for episode in episodes:
            if record_id is None or episode.get("id") == record_id:
                absolute = record_episode.get("absoluteEpisodeNumber")
                if isinstance(absolute, int):
                    episode["absolute_episode"] = absolute
    return episodes


def safe_title_component(title: str) -> str:
    cleaned = re.sub(r"[\\/:\x00]+", " ", title)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" ._-")


def comparable_title_words(value: str) -> list[str]:
    value = re.sub(r"\(\d{4}\)", " ", value)
    return re.findall(r"[a-z0-9]+", value.casefold())


def title_words_present(series_title: str, basename: str) -> bool:
    needle = comparable_title_words(series_title)
    candidate = re.sub(r"^(?:\[[^\]]+\]\s*)+", "", title_without_extension(basename))
    haystack = comparable_title_words(candidate)
    if not needle:
        return True
    return haystack[: len(needle)] == needle


def canonical_year_is_missing(series_title: str, basename: str) -> bool:
    match = re.search(r"\(((?:19|20)\d{2})\)\s*$", series_title)
    if not match:
        return False
    year = match.group(1)
    yearless = series_title[: match.start()].strip()
    return title_words_present(yearless, basename) and not re.search(
        rf"(?<!\d){re.escape(year)}(?!\d)", basename
    )


def path_with_expected_episode_target(
    path: str,
    expected_episodes: list[dict[str, int]] | None,
    video_count: int,
) -> str:
    episodes = [
        item
        for item in expected_episodes or []
        if isinstance(item.get("season"), int) and isinstance(item.get("episode"), int)
    ]
    if not episodes or len(episodes) != video_count:
        return path
    by_episode = {int(item["episode"]): int(item["season"]) for item in episodes}
    if len(by_episode) != len(episodes):
        return path

    posix_path = PurePosixPath(path)
    basename = posix_path.name
    explicit = EXPLICIT_EPISODE_RE.search(basename)
    if explicit:
        episode = int(explicit.group("episode"))
        season = by_episode.get(episode)
        if season is None or season == int(explicit.group("season")):
            return path
        replacement = f"S{season:02}E{episode:02}"
        return str(posix_path.with_name(
            f"{basename[:explicit.start()]}{replacement}{basename[explicit.end():]}"
        ))

    pair = SEASON_NUMBER_EPISODE_RE.search(basename)
    if pair:
        episode = int(pair.group("episode"))
        season = by_episode.get(episode)
        if season is None:
            return path
        replacement = f"S{season:02}E{episode:02}"
        return str(posix_path.with_name(
            f"{basename[:pair.start()]}{replacement}{basename[pair.end():]}"
        ))

    if len(episodes) != 1:
        return path
    bare = BARE_NUMBERED_EPISODE_RE.search(basename)
    if not bare:
        return path
    episode = episodes[0]
    valid_numbers = {int(episode["episode"])}
    absolute = episode.get("absolute_episode")
    if isinstance(absolute, int):
        valid_numbers.add(absolute)
    if int(bare.group("number")) not in valid_numbers:
        return path
    replacement = f"{bare.group('prefix')}S{episode['season']:02}E{episode['episode']:02}{bare.group('suffix')}"
    return str(posix_path.with_name(
        f"{basename[:bare.start()]}{replacement}{basename[bare.end():]}"
    ))


def path_with_episode_title_prefix(
    path: str,
    series_title: str | None,
    aliases: list[str] | None = None,
) -> str:
    if not series_title:
        return path
    posix_path = PurePosixPath(path)
    basename = posix_path.name
    if not EPISODE_TOKEN_RE.search(basename):
        return path
    needs_year = canonical_year_is_missing(series_title, basename)
    if title_words_present(series_title, basename) and not needs_year:
        return path
    alias_present = any(
        title_words_present(alias, basename)
        for alias in (aliases or [])
        if alias and alias.casefold() != series_title.casefold()
    )
    if not needs_year and not alias_present and not BARE_EPISODE_RE.search(basename):
        return path
    title = safe_title_component(series_title)
    if not title:
        return path
    episode_match = EPISODE_PREFIX_RE.match(basename)
    if not episode_match:
        return path
    leading_group = episode_match.group("group") or ""
    remainder = episode_match.group("episode").lstrip(" ._-")
    return str(posix_path.with_name(f"{leading_group}{title} - {remainder}"))


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


def language_combo_tag_from_languages(
    languages: set[str],
    original_languages: set[str],
) -> str | None:
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


def language_combo_tag(path: Path | None, original_languages: set[str]) -> str | None:
    return language_combo_tag_from_languages(file_audio_languages(path), original_languages)


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


def filesystem_torrent_files(torrent: dict) -> list[dict[str, object]]:
    """Infer qBittorrent file names from the completed filesystem layout.

    qBittorrent's `torrents/files` endpoint is authoritative, but it can hang on
    busy completed torrents. `renameFile` still needs qBit-style relative paths,
    so prefer paths relative to `save_path`, then keep basename alternatives for
    single-root layouts where qBit reports only the payload basename.
    """

    roots: list[Path] = []
    for key in ("content_path",):
        value = str(torrent.get(key) or "").strip()
        if not value:
            continue
        path = Path(value)
        if path.is_file():
            roots.append(path.parent)
        elif path.is_dir():
            roots.append(path)

    torrent_name = str(torrent.get("name") or "").strip()
    save_path = Path(str(torrent.get("save_path") or "")) if torrent.get("save_path") else None
    if save_path and torrent_name:
        named_root = save_path / torrent_name
        if named_root.is_dir():
            roots.append(named_root)

    unique_roots: list[Path] = []
    seen_roots: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen_roots:
            continue
        seen_roots.add(key)
        unique_roots.append(root)

    files: list[dict[str, object]] = []
    seen_names: set[str] = set()
    save_base = Path(str(torrent.get("save_path") or "")) if torrent.get("save_path") else None
    for root in unique_roots:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            names: list[str] = []
            if save_base:
                try:
                    names.append(path.relative_to(save_base).as_posix())
                except ValueError:
                    pass
            try:
                names.append(path.relative_to(root).as_posix())
            except ValueError:
                pass
            names.append(path.name)

            primary = next((name for name in names if name), "")
            if not primary or primary in seen_names:
                continue
            seen_names.add(primary)
            files.append(
                {
                    "name": primary,
                    "absolute_path": str(path),
                    "alternative_names": [
                        name for name in dict.fromkeys(names) if name and name != primary
                    ],
                }
            )
    return files


def fallback_single_torrent_files(torrent: dict) -> list[dict[str, str]]:
    torrent_name = str(torrent.get("name") or "").strip()
    content_path = str(torrent.get("content_path") or "").strip()
    candidates = [
        PurePosixPath(content_path).name if content_path else "",
        torrent_name,
    ]
    for candidate in candidates:
        if PurePosixPath(candidate).suffix.lower() in VIDEO_EXTENSIONS:
            return [{"name": candidate}]
    return []


def wanted_tags(
    file_name: str,
    media_path: Path | None,
    original_languages: set[str],
    parent_title: str,
    trusted_release_group: str | None = None,
) -> tuple[list[str], str | None, list[str]]:
    basename = PurePosixPath(file_name).name
    tags: list[str] = []
    reasons: list[str] = []
    languages = file_audio_languages(media_path)
    language_tag = language_combo_tag_from_languages(languages, original_languages)
    if language_tag and not LANGUAGE_COMBO_RE.search(basename):
        tags.append(language_tag)
    elif language_tag:
        reasons.append("language_combo_already_present")
    elif media_path is None:
        reasons.append("media_path_unresolved")
    elif not languages:
        reasons.append("audio_languages_unknown")
    elif "eng" not in languages:
        reasons.append("missing_english_audio")
    else:
        reasons.append("missing_original_audio")

    has_hevc = file_has_hevc_marker(media_path)
    if has_hevc and not X265_RE.search(basename):
        tags.append("[x265]")
    elif has_hevc:
        reasons.append("x265_already_present")
    elif media_path is not None:
        reasons.append("no_hevc_marker")

    context_tags = context_tags_from_title(parent_title, basename)
    if context_tags:
        tags.extend(context_tags)
    elif any(pattern.search(parent_title) for _, pattern in PLATFORM_TAG_PATTERNS):
        reasons.append("platform_already_present_or_unneeded")

    release_group = release_group_candidate(trusted_release_group) or release_group_from_title(
        parent_title
    )
    if release_group and file_has_release_group(basename, release_group):
        release_group = None
        reasons.append("release_group_already_present")
    elif not release_group:
        reasons.append("release_group_not_in_parent_title")

    return tags, release_group, reasons


def rename_with_tags(
    path: str,
    tags: list[str],
    release_group: str | None,
    series_title: str | None,
    aliases: list[str] | None = None,
    expected_episodes: list[dict[str, int]] | None = None,
    video_count: int = 0,
) -> str:
    targeted = path_with_expected_episode_target(path, expected_episodes, video_count)
    posix_path = PurePosixPath(path_with_episode_title_prefix(targeted, series_title, aliases))
    stem = posix_path.stem
    if tags:
        stem = f"{stem} {' '.join(tags)}"
    if release_group:
        stem = f"{stem} -{release_group}"
    return str(posix_path.with_name(f"{stem}{posix_path.suffix}"))


def rename_file_with_alternatives(
    client: QbitClient,
    torrent_hash: str,
    old_path: str,
    tags: list[str],
    release_group: str | None,
    series_title: str | None,
    aliases: list[str] | None,
    expected_episodes: list[dict[str, int]] | None,
    video_count: int,
    alternatives: list[str],
) -> tuple[str, str, str | None]:
    attempts = [old_path, *alternatives]
    errors: list[str] = []
    for candidate in attempts:
        candidate_new_path = rename_with_tags(
            candidate,
            tags,
            release_group,
            series_title,
            aliases,
            expected_episodes,
            video_count,
        )
        try:
            client.rename_file(torrent_hash, candidate, candidate_new_path)
            return candidate, candidate_new_path, None
        except Exception as exc:  # noqa: BLE001 - try alternate qBit path forms.
            errors.append(f"{candidate}: {exc}")
    return old_path, rename_with_tags(
        old_path,
        tags,
        release_group,
        series_title,
        aliases,
        expected_episodes,
        video_count,
    ), "; ".join(errors[:3])


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
    parser.add_argument(
        "--series-title",
        default="",
        help="explicit canonical Sonarr series title for targeted repairs",
    )
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
        client = QbitClient(
            api_url,
            username,
            password,
            retries=env_int("QBIT_API_RETRIES", 3),
            retry_delay=env_int("QBIT_API_RETRY_DELAY", 2),
            timeout=env_int("QBIT_API_TIMEOUT", 60),
        )
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
        grab_context = grab_context_by_download_id(
            os.environ.get("ARR_GRAB_CONTEXT_API", ""),
            torrent_hash,
        )
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
        context_languages = {
            language
            for value in (grab_context or {}).get("original_languages", [])
            if (language := normalize_language(str(value)))
        }
        original_languages = (
            context_languages
            or original_languages_from_arr_record(arr_record)
            or parse_languages(os.environ.get("DA_ORIGINAL_LANGUAGES", ""))
            or DEFAULT_DUAL_AUDIO_ORIGINAL_LANGUAGES
        )
        identity_conflict = bool((grab_context or {}).get("identity_conflict"))
        context_title = str((grab_context or {}).get("canonical_title") or "").strip()
        series_title = args.series_title.strip() or (
            None if identity_conflict else context_title or series_title_from_arr_record(arr_record)
        )
        aliases = [
            str(value).strip()
            for value in (grab_context or {}).get("aliases", [])
            if str(value).strip()
        ]
        expected_episodes = expected_episodes_from_context(grab_context, arr_record)
        trusted_release_group = release_group_candidate(
            str((grab_context or {}).get("release_group") or "")
        )
        parent_title = parent_title_from_values(
            (grab_context or {}).get("source_title"),
            torrent.get("name"),
            args.name,
            arr_record.get("title") if arr_record else None,
            arr_record.get("downloadTitle") if arr_record else None,
        )
        log(
            "processing torrent={torrent!r} category={category!r} "
            "context={context} identity_conflict={conflict} "
            "original_language(s)={languages} parent_title={parent!r}".format(
                torrent=torrent.get("name", ""),
                category=category,
                context="ledger" if grab_context else "exact_queue" if arr_record else "fallback",
                conflict=identity_conflict,
                languages=", ".join(sorted(original_languages)),
                parent=parent_title,
            )
        )

        changes = 0
        videos_scanned = 0
        skipped_no_stamp = 0
        skip_reasons: collections.Counter[str] = collections.Counter()
        skipped_samples: list[dict[str, object]] = []
        rename_failures: list[dict[str, str]] = []
        file_list_source = "qbittorrent_api"
        file_list_error = ""
        torrent_files = fallback_single_torrent_files(torrent)
        if torrent_files:
            file_list_source = "single_torrent_metadata"
            log("using single-file torrent metadata instead of qBittorrent file-list API")
        else:
            try:
                torrent_files = client.files(
                    torrent_hash,
                    retries=env_int("QBIT_FILES_API_RETRIES", 1),
                    retry_delay=env_int("QBIT_FILES_API_RETRY_DELAY", 1),
                    timeout=env_int("QBIT_FILES_API_TIMEOUT", 8),
                )
            except Exception as exc:  # noqa: BLE001 - fall back to the completed filesystem.
                file_list_error = str(exc)
                log(f"qBittorrent file-list API failed; trying filesystem fallback: {exc}")
                torrent_files = filesystem_torrent_files(torrent)
                file_list_source = "filesystem_fallback" if torrent_files else "none"
                if not torrent_files:
                    raise RuntimeError(
                        "qBittorrent file-list API failed and filesystem fallback found no video files: "
                        f"{exc}"
                    )

        video_count = sum(
            1
            for item in torrent_files
            if PurePosixPath(str(item.get("name") or "")).suffix.lower() in VIDEO_EXTENSIONS
        )

        for torrent_file in torrent_files:
            old_path = str(torrent_file.get("name") or "")
            if PurePosixPath(old_path).suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            videos_scanned += 1

            absolute_path = str(torrent_file.get("absolute_path") or "")
            media_path = Path(absolute_path) if absolute_path else absolute_file_path(torrent, old_path)
            tags, release_group, reasons = wanted_tags(
                old_path,
                media_path,
                original_languages,
                parent_title,
                trusted_release_group,
            )
            if not tags and not release_group:
                targeted_path = path_with_expected_episode_target(
                    old_path, expected_episodes, video_count
                )
                prefixed_path = path_with_episode_title_prefix(
                    targeted_path, series_title, aliases
                )
                if prefixed_path == old_path:
                    skipped_no_stamp += 1
                    if not reasons:
                        reasons = ["no_matching_stamp_needed"]
                    skip_reasons.update(reasons)
                    if len(skipped_samples) < 10:
                        skipped_samples.append(
                            {
                                "path": old_path,
                                "reasons": reasons,
                                "media_path_found": media_path is not None,
                            }
                        )
                    log(f"no stamp needed for {old_path!r}; reasons={','.join(reasons)}")
                    continue

            new_path = rename_with_tags(
                old_path,
                tags,
                release_group,
                series_title,
                aliases,
                expected_episodes,
                video_count,
            )
            if new_path == old_path:
                continue

            if args.dry_run:
                log(
                    f"would rename {old_path!r} -> {new_path!r} "
                    f"tags={tags} release_group={release_group!r}"
                )
            else:
                actual_old_path, actual_new_path, error = rename_file_with_alternatives(
                    client,
                    torrent_hash,
                    old_path,
                    tags,
                    release_group,
                    series_title,
                    aliases,
                    expected_episodes,
                    video_count,
                    [
                        str(name)
                        for name in torrent_file.get("alternative_names", [])
                        if isinstance(name, str)
                    ],
                )
                if error:
                    rename_failures.append(
                        {
                            "path": old_path,
                            "target": new_path,
                            "error": error,
                        }
                    )
                    log(f"rename failed for {old_path!r}: {error}")
                    continue
                log(
                    f"renamed {actual_old_path!r} -> {actual_new_path!r} "
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
                "context_source": "ledger" if grab_context else "exact_queue" if arr_record else "fallback",
                "identity_conflict": identity_conflict,
                "trusted_release_group": trusted_release_group,
                "original_languages": sorted(original_languages),
                "changes": changes,
                "videos_scanned": videos_scanned,
                "skipped_no_stamp": skipped_no_stamp,
                "skip_reasons": dict(sorted(skip_reasons.items())),
                "skipped_samples": skipped_samples,
                "file_list_source": file_list_source,
                "file_list_error": file_list_error,
                "rename_failures": rename_failures[:10],
            }
        )
    except Exception as exc:  # noqa: BLE001 - post-processing must not fail imports
        log(f"error: {exc}")
        write_event({**event, "result": "error", "error": str(exc)})
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
