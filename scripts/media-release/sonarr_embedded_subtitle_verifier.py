#!/usr/bin/env python3
"""Stage Sonarr torrent candidates and verify embedded English subtitles.

The helper is intended to run as root on docker-vm behind Astra's typed
host-administration boundary. It reads local credentials, never returns them,
keeps verification downloads outside Sonarr's category, and never imports or
replaces library files.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.cookiejar import CookieJar
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = 1
MAX_REQUEST = 8192
MAX_RESPONSE_CANDIDATES = 50
MAX_TORRENT_BYTES = 20 * 1024 * 1024
SONARR_CONFIG = Path("/opt/media-stack/sonarr/config.xml")
SONARR_BASE = "http://127.0.0.1:8989/api/v3"
QBIT_ENV = Path("/etc/qbit-port-sync.env")
STATE_ROOT = Path("/var/lib/hermes-media-release-verifier")
FFPROBE = Path("/usr/bin/ffprobe")
COMPLETE_PREFIX = PurePosixPath("/data")
COMPLETE_HOST = Path("/srv/media/plex")
INCOMPLETE_PREFIX = PurePosixPath("/incomplete")
INCOMPLETE_HOST = Path("/srv/incomplete_downloads/incomplete/torrents")
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".avi", ".webm"}
TRANSACTION = re.compile(r"^[a-f0-9]{24}$")
CANDIDATE = re.compile(r"^[a-f0-9]{64}$")


class VerificationError(RuntimeError):
    """Expected bounded request failure."""


def fail(code: str) -> None:
    raise VerificationError(code)


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise VerificationError("qbit-config-unavailable") from exc
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def sonarr_key() -> str:
    try:
        root = ET.parse(SONARR_CONFIG).getroot()
        value = root.findtext("ApiKey") or ""
    except (OSError, ET.ParseError) as exc:
        raise VerificationError("sonarr-config-unavailable") from exc
    if not value or len(value) > 256:
        fail("sonarr-config-unavailable")
    return value


def sonarr_get(path: str, params: dict[str, Any] | None = None) -> Any:
    query = "?" + urllib.parse.urlencode(params) if params else ""
    request = urllib.request.Request(
        f"{SONARR_BASE}{path}{query}", headers={"X-Api-Key": sonarr_key()}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise VerificationError("sonarr-unavailable") from exc


def qbit_client() -> tuple[str, urllib.request.OpenerDirector]:
    env = parse_env(QBIT_ENV)
    if any(not env.get(key) for key in ("QBIT_API", "QBIT_USER", "QBIT_PASS")):
        fail("qbit-config-unavailable")
    base = env["QBIT_API"].rstrip("/")
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    body = urllib.parse.urlencode(
        {"username": env["QBIT_USER"], "password": env["QBIT_PASS"]}
    ).encode("ascii")
    request = urllib.request.Request(f"{base}/auth/login", data=body, method="POST")
    try:
        with opener.open(request, timeout=20) as response:
            text = response.read(128).decode("utf-8", errors="replace")
            status = response.status
    except OSError as exc:
        raise VerificationError("qbit-unavailable") from exc
    if text.strip() != "Ok." and status != 204:
        fail("qbit-auth-failed")
    return base, opener


def qbit_get(
    client: tuple[str, urllib.request.OpenerDirector],
    path: str,
    params: dict[str, Any] | None = None,
) -> Any:
    base, opener = client
    query = "?" + urllib.parse.urlencode(params) if params else ""
    try:
        with opener.open(f"{base}{path}{query}", timeout=30) as response:
            return json.load(response)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise VerificationError("qbit-request-failed") from exc


def qbit_post(
    client: tuple[str, urllib.request.OpenerDirector],
    path: str,
    params: dict[str, Any],
) -> str:
    base, opener = client
    body = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(f"{base}{path}", data=body, method="POST")
    try:
        with opener.open(request, timeout=30) as response:
            return response.read(4096).decode("utf-8", errors="replace")
    except OSError as exc:
        raise VerificationError("qbit-request-failed") from exc


def multipart(fields: dict[str, str], filename: str, payload: bytes) -> tuple[bytes, str]:
    boundary = "----------------hermes" + secrets.token_hex(16)
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            (
                'Content-Disposition: form-data; name="torrents"; '
                f'filename="{filename}"\r\n'
            ).encode(),
            b"Content-Type: application/x-bittorrent\r\n\r\n",
            payload,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), boundary


def qbit_add(
    client: tuple[str, urllib.request.OpenerDirector],
    payload: bytes,
    category: str,
    save_path: str,
) -> None:
    body, boundary = multipart(
        {
            "category": category,
            "savepath": save_path,
            "stopped": "true",
            "contentLayout": "Original",
        },
        "candidate.torrent",
        payload,
    )
    base, opener = client
    request = urllib.request.Request(
        f"{base}/torrents/add",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with opener.open(request, timeout=60) as response:
            text = response.read(256).decode("utf-8", errors="replace").strip()
    except OSError as exc:
        raise VerificationError("qbit-add-failed") from exc
    if text not in {"", "Ok."}:
        fail("qbit-add-failed")


def candidate_id(item: dict[str, Any]) -> str:
    canonical = json.dumps(
        {
            "guid": item.get("guid"),
            "indexerId": item.get("indexerId"),
            "size": item.get("size"),
            "title": item.get("title"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def bounded_text(value: Any, limit: int = 512) -> str | None:
    if not isinstance(value, str):
        return None
    return "".join(char for char in value if char >= " " or char == "\t")[:limit]


def release_candidates(series_id: int, season_number: int) -> list[dict[str, Any]]:
    value = sonarr_get(
        "/release", {"seriesId": series_id, "seasonNumber": season_number}
    )
    if not isinstance(value, list):
        fail("sonarr-response-invalid")
    return [item for item in value if isinstance(item, dict)]


def title_seasons(value: Any) -> set[int]:
    if not isinstance(value, str):
        return set()
    seasons: set[int] = set()
    for match in re.finditer(r"(?i)S(\d{1,3})(?:\s*-\s*S?(\d{1,3}))?", value):
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        if 0 <= start <= end <= 999 and end - start <= 100:
            seasons.update(range(start, end + 1))
    return seasons


def candidate_matches_season(item: dict[str, Any], season_number: int) -> bool:
    if item.get("protocol") != "torrent":
        return False
    if item.get("mappedSeasonNumber") == season_number:
        return True
    rejections = item.get("rejections")
    multi_season = isinstance(rejections, list) and any(
        isinstance(value, str) and "multi-season" in value.lower()
        for value in rejections
    )
    return multi_season and season_number in title_seasons(item.get("title"))


def candidate_sort_key(item: dict[str, Any], season_number: int) -> tuple[Any, ...]:
    seeders = item.get("seeders")
    score = item.get("customFormatScore")
    return (
        item.get("mappedSeasonNumber") != season_number,
        not bool(item.get("fullSeason")),
        -(score if isinstance(score, int) else -1),
        -(seeders if isinstance(seeders, int) else -1),
        str(item.get("title") or "").lower(),
    )


def compact_candidate(item: dict[str, Any]) -> dict[str, Any]:
    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    quality_inner = quality.get("quality") if isinstance(quality.get("quality"), dict) else {}
    rejections = item.get("rejections") if isinstance(item.get("rejections"), list) else []
    return {
        "candidateId": candidate_id(item),
        "title": bounded_text(item.get("title"), 768),
        "indexer": bounded_text(item.get("indexer"), 128),
        "indexerId": item.get("indexerId"),
        "protocol": item.get("protocol"),
        "fullSeason": bool(item.get("fullSeason")),
        "mappedSeasonNumber": item.get("mappedSeasonNumber"),
        "episodeNumbers": item.get("episodeNumbers")[:64]
        if isinstance(item.get("episodeNumbers"), list)
        else [],
        "size": item.get("size"),
        "seeders": item.get("seeders"),
        "leechers": item.get("leechers"),
        "ageHours": item.get("ageHours"),
        "quality": bounded_text(quality_inner.get("name"), 128),
        "customFormatScore": item.get("customFormatScore"),
        "rejected": bool(item.get("rejected")),
        "rejections": [bounded_text(value, 256) for value in rejections[:16]],
    }


def search(request: dict[str, Any]) -> dict[str, Any]:
    series_id, season_number = require_series(request)
    source = release_candidates(series_id, season_number)
    candidates = sorted(
        [item for item in source if candidate_matches_season(item, season_number)],
        key=lambda item: candidate_sort_key(item, season_number),
    )
    return {
        "seriesId": series_id,
        "seasonNumber": season_number,
        "sourceTotal": len(source),
        "total": len(candidates),
        "truncated": len(candidates) > MAX_RESPONSE_CANDIDATES,
        "candidates": [
            compact_candidate(item) for item in candidates[:MAX_RESPONSE_CANDIDATES]
        ],
    }


def require_int(request: dict[str, Any], key: str, minimum: int, maximum: int) -> int:
    value = request.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        fail(f"invalid-{key.replace('_', '-')}")
    return value


def require_series(request: dict[str, Any]) -> tuple[int, int]:
    return (
        require_int(request, "seriesId", 1, 2_000_000_000),
        require_int(request, "seasonNumber", 0, 999),
    )


def require_transaction(request: dict[str, Any]) -> str:
    value = request.get("transactionId")
    if not isinstance(value, str) or TRANSACTION.fullmatch(value) is None:
        fail("invalid-transaction-id")
    return value


def state_path(transaction_id: str) -> Path:
    if TRANSACTION.fullmatch(transaction_id) is None:
        fail("invalid-transaction-id")
    return STATE_ROOT / f"{transaction_id}.json"


def ensure_state_root() -> None:
    try:
        STATE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = os.lstat(STATE_ROOT)
    except OSError as exc:
        raise VerificationError("state-unavailable") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0:
        fail("state-unavailable")
    os.chmod(STATE_ROOT, 0o700)


def write_state(value: dict[str, Any]) -> None:
    ensure_state_root()
    target = state_path(str(value["transactionId"]))
    temp = target.with_suffix(".tmp")
    data = json.dumps(value, sort_keys=True, separators=(",", ":"))
    try:
        temp.write_text(data, encoding="utf-8")
        os.chmod(temp, 0o600)
        os.replace(temp, target)
    except OSError as exc:
        raise VerificationError("state-unavailable") from exc


def read_state(transaction_id: str) -> dict[str, Any]:
    ensure_state_root()
    target = state_path(transaction_id)
    try:
        info = os.lstat(target)
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError("transaction-not-found") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != 0
        or stat.S_IMODE(info.st_mode) != 0o600
        or not isinstance(value, dict)
        or value.get("transactionId") != transaction_id
    ):
        fail("state-invalid")
    return value


def fetch_torrent(item: dict[str, Any]) -> bytes:
    value = item.get("downloadUrl")
    if not isinstance(value, str) or not value or len(value) > 8192:
        fail("candidate-download-unavailable")
    url = urllib.parse.urljoin(SONARR_BASE + "/", value)
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        fail("candidate-download-invalid")
    headers: dict[str, str] = {}
    sonarr = urllib.parse.urlsplit(SONARR_BASE)
    try:
        target_port = parsed.port
        sonarr_port = sonarr.port
    except ValueError:
        fail("candidate-download-invalid")
    if (parsed.hostname, target_port) == (sonarr.hostname, sonarr_port):
        headers["X-Api-Key"] = sonarr_key()
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_TORRENT_BYTES:
                fail("candidate-download-too-large")
            payload = response.read(MAX_TORRENT_BYTES + 1)
    except VerificationError:
        raise
    except (OSError, ValueError) as exc:
        raise VerificationError("candidate-download-failed") from exc
    if len(payload) > MAX_TORRENT_BYTES:
        fail("candidate-download-too-large")
    if not payload.startswith(b"d") or b"4:info" not in payload[:65536]:
        fail("candidate-download-invalid")
    return payload


def torrents_for_category(
    client: tuple[str, urllib.request.OpenerDirector], category: str
) -> list[dict[str, Any]]:
    value = qbit_get(client, "/torrents/info", {"category": category})
    if not isinstance(value, list):
        fail("qbit-response-invalid")
    return [item for item in value if isinstance(item, dict)]


def torrent_files(
    client: tuple[str, urllib.request.OpenerDirector], torrent_hash: str
) -> list[dict[str, Any]]:
    value = qbit_get(client, "/torrents/files", {"hash": torrent_hash})
    if not isinstance(value, list):
        fail("qbit-response-invalid")
    return [item for item in value if isinstance(item, dict)]


def video_file(item: dict[str, Any]) -> bool:
    name = item.get("name")
    return isinstance(name, str) and PurePosixPath(name).suffix.lower() in VIDEO_EXTENSIONS


def episode_numbers(name: str, season_number: int) -> set[int]:
    result: set[int] = set()
    for match in re.finditer(r"(?i)S(\d{1,3})((?:[ ._-]*E\d{1,4})+)", name):
        if int(match.group(1)) != season_number:
            continue
        result.update(int(value) for value in re.findall(r"(?i)E(\d{1,4})", match.group(2)))
    return result


def set_file_priorities(
    client: tuple[str, urllib.request.OpenerDirector],
    torrent_hash: str,
    ids: list[int],
    priority: int,
) -> None:
    for offset in range(0, len(ids), 256):
        qbit_post(
            client,
            "/torrents/filePrio",
            {
                "hash": torrent_hash,
                "id": "|".join(str(value) for value in ids[offset : offset + 256]),
                "priority": priority,
            },
        )


def stage(request: dict[str, Any]) -> dict[str, Any]:
    series_id, season_number = require_series(request)
    sample_episode = require_int(request, "sampleEpisode", 1, 9999)
    wanted = request.get("candidateId")
    if not isinstance(wanted, str) or CANDIDATE.fullmatch(wanted) is None:
        fail("invalid-candidate-id")
    matches = [
        item
        for item in release_candidates(series_id, season_number)
        if candidate_id(item) == wanted
    ]
    if len(matches) != 1:
        fail("candidate-not-found")
    candidate = matches[0]
    if not candidate_matches_season(candidate, season_number):
        fail("candidate-season-unsupported")
    if str(candidate.get("protocol") or "").lower() != "torrent":
        fail("candidate-not-torrent")
    payload = fetch_torrent(candidate)
    transaction_id = secrets.token_hex(12)
    category = f"astra-verify-{transaction_id}"
    save_path = f"/data/downloads/torrents/{category}"
    client = qbit_client()
    if torrents_for_category(client, category):
        fail("transaction-conflict")
    qbit_post(client, "/torrents/createCategory", {"category": category, "savePath": save_path})
    qbit_add(client, payload, category, save_path)
    torrents: list[dict[str, Any]] = []
    for _ in range(20):
        torrents = torrents_for_category(client, category)
        if torrents:
            break
        time.sleep(0.5)
    if len(torrents) != 1 or not isinstance(torrents[0].get("hash"), str):
        fail("qbit-add-unverified")
    torrent = torrents[0]
    torrent_hash = str(torrent["hash"])
    files = torrent_files(client, torrent_hash)
    videos = [
        item
        for item in files
        if video_file(item)
        and sample_episode in episode_numbers(str(item.get("name") or ""), season_number)
    ]
    if len(videos) != 1:
        qbit_post(client, "/torrents/delete", {"hashes": torrent_hash, "deleteFiles": "true"})
        fail("sample-episode-ambiguous")
    all_ids = [item["index"] for item in files if isinstance(item.get("index"), int)]
    selected_id = videos[0].get("index")
    if not isinstance(selected_id, int):
        fail("qbit-response-invalid")
    set_file_priorities(client, torrent_hash, all_ids, 0)
    set_file_priorities(client, torrent_hash, [selected_id], 1)
    qbit_post(client, "/torrents/start", {"hashes": torrent_hash})
    state = {
        "schemaVersion": SCHEMA_VERSION,
        "transactionId": transaction_id,
        "createdAt": int(time.time()),
        "phase": "sample",
        "seriesId": series_id,
        "seasonNumber": season_number,
        "sampleEpisode": sample_episode,
        "candidateId": wanted,
        "candidate": compact_candidate(candidate),
        "category": category,
        "torrentHash": torrent_hash,
    }
    write_state(state)
    return transaction_summary(state, client)


def one_torrent(
    state: dict[str, Any], client: tuple[str, urllib.request.OpenerDirector]
) -> dict[str, Any]:
    values = qbit_get(client, "/torrents/info", {"hashes": state["torrentHash"]})
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        fail("torrent-not-found")
    value = values[0]
    if value.get("category") != state.get("category"):
        fail("torrent-state-mismatch")
    return value


def transaction_summary(
    state: dict[str, Any],
    client: tuple[str, urllib.request.OpenerDirector] | None = None,
) -> dict[str, Any]:
    client = client or qbit_client()
    torrent = one_torrent(state, client)
    return {
        "transactionId": state["transactionId"],
        "phase": state["phase"],
        "seriesId": state["seriesId"],
        "seasonNumber": state["seasonNumber"],
        "candidate": state["candidate"],
        "torrent": {
            "name": bounded_text(torrent.get("name"), 768),
            "hash": str(torrent.get("hash") or "")[:12],
            "category": torrent.get("category"),
            "state": torrent.get("state"),
            "progress": torrent.get("progress"),
            "amountLeft": torrent.get("amount_left"),
            "downloadSpeed": torrent.get("dlspeed"),
            "eta": torrent.get("eta"),
            "seeders": torrent.get("num_seeds"),
        },
    }


def status(request: dict[str, Any]) -> dict[str, Any]:
    return transaction_summary(read_state(require_transaction(request)))


def map_container_path(value: str) -> Path:
    path = PurePosixPath(value)
    for prefix, root in (
        (INCOMPLETE_PREFIX, INCOMPLETE_HOST),
        (COMPLETE_PREFIX, COMPLETE_HOST),
    ):
        try:
            relative = path.relative_to(prefix)
        except ValueError:
            continue
        if any(part in {"", ".", ".."} for part in relative.parts):
            fail("payload-path-invalid")
        return root.joinpath(*relative.parts)
    fail("payload-path-invalid")


def payload_path(torrent: dict[str, Any], file_name: str) -> Path:
    content = torrent.get("content_path")
    if not isinstance(content, str):
        fail("payload-path-invalid")
    base = PurePosixPath(content)
    relative = PurePosixPath(file_name)
    if relative.is_absolute() or ".." in relative.parts:
        fail("payload-path-invalid")
    if base.suffix.lower() in VIDEO_EXTENSIONS:
        if relative.name != base.name:
            fail("payload-path-invalid")
        return map_container_path(str(base))
    return map_container_path(str(base / relative))


def probe_file(path: Path) -> dict[str, Any]:
    if not FFPROBE.is_file():
        fail("ffprobe-unavailable")
    try:
        info = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise VerificationError("payload-unavailable") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        fail("payload-invalid")
    command = [
        str(FFPROBE),
        "-v",
        "error",
        "-show_entries",
        "stream=index,codec_type,codec_name:stream_tags=language,title",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=120,
            check=False,
            env={"PATH": "/usr/bin:/bin", "LANG": "C"},
        )
        value = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise VerificationError("ffprobe-failed") from exc
    streams = value.get("streams") if isinstance(value, dict) else None
    if result.returncode != 0 or not isinstance(streams, list):
        fail("ffprobe-failed")
    compact: list[dict[str, Any]] = []
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        tags = stream.get("tags") if isinstance(stream.get("tags"), dict) else {}
        compact.append(
            {
                "index": stream.get("index"),
                "type": stream.get("codec_type"),
                "codec": bounded_text(stream.get("codec_name"), 64),
                "language": bounded_text(tags.get("language"), 32),
                "title": bounded_text(tags.get("title"), 128),
            }
        )
    languages = {
        str(item.get("language") or "").strip().lower().replace("_", "-")
        for item in compact
        if item.get("type") == "subtitle"
    }
    has_english = any(
        value in {"en", "eng", "english"} or value.startswith("en-")
        for value in languages
    )
    return {
        "size": info.st_size,
        "hasVideo": any(item.get("type") == "video" for item in compact),
        "hasAudio": any(item.get("type") == "audio" for item in compact),
        "hasEmbeddedEnglishSubtitle": has_english,
        "streams": compact,
    }


def expected_episodes(series_id: int, season_number: int) -> set[int]:
    value = sonarr_get(
        "/episode", {"seriesId": series_id, "seasonNumber": season_number}
    )
    if not isinstance(value, list):
        fail("sonarr-response-invalid")
    result = {
        item["episodeNumber"]
        for item in value
        if isinstance(item, dict)
        and item.get("seasonNumber") == season_number
        and isinstance(item.get("episodeNumber"), int)
        and item["episodeNumber"] > 0
    }
    if not result:
        fail("season-episodes-unavailable")
    return result


def selected_videos(
    state: dict[str, Any], client: tuple[str, urllib.request.OpenerDirector]
) -> list[dict[str, Any]]:
    return [
        item
        for item in torrent_files(client, state["torrentHash"])
        if video_file(item) and int(item.get("priority") or 0) > 0
    ]


def verify_state(state: dict[str, Any]) -> dict[str, Any]:
    client = qbit_client()
    torrent = one_torrent(state, client)
    files = selected_videos(state, client)
    if not files:
        fail("selected-payload-missing")
    results: list[dict[str, Any]] = []
    for item in files:
        name = str(item.get("name") or "")
        complete = float(item.get("progress") or 0) >= 1.0
        result: dict[str, Any] = {
            "name": bounded_text(name, 1024),
            "episodes": sorted(episode_numbers(name, state["seasonNumber"])),
            "complete": complete,
        }
        if complete:
            result.update(probe_file(payload_path(torrent, name)))
        results.append(result)
    eligible_files = all(
        item.get("complete")
        and item.get("hasVideo")
        and item.get("hasAudio")
        and item.get("hasEmbeddedEnglishSubtitle")
        for item in results
    )
    expected = expected_episodes(state["seriesId"], state["seasonNumber"])
    observed = [episode for item in results for episode in item["episodes"]]
    complete_season = (
        state["phase"] == "season"
        and set(observed) == expected
        and len(observed) == len(expected)
    )
    return {
        **transaction_summary(state, client),
        "files": results,
        "allSelectedFilesEligible": eligible_files,
        "expectedEpisodes": sorted(expected),
        "observedEpisodes": sorted(observed),
        "completeSeason": complete_season,
        "eligibleForImport": eligible_files and complete_season,
    }


def verify(request: dict[str, Any]) -> dict[str, Any]:
    return verify_state(read_state(require_transaction(request)))


def expand(request: dict[str, Any]) -> dict[str, Any]:
    state = read_state(require_transaction(request))
    if state.get("phase") != "sample":
        fail("invalid-transaction-phase")
    sample = verify_state(state)
    if not sample["allSelectedFilesEligible"]:
        fail("sample-not-eligible")
    client = qbit_client()
    files = torrent_files(client, state["torrentHash"])
    selected = [
        item
        for item in files
        if video_file(item)
        and episode_numbers(str(item.get("name") or ""), state["seasonNumber"])
    ]
    expected = expected_episodes(state["seriesId"], state["seasonNumber"])
    observed = [
        episode
        for item in selected
        for episode in episode_numbers(str(item.get("name") or ""), state["seasonNumber"])
    ]
    if set(observed) != expected or len(observed) != len(expected):
        fail("season-payload-incomplete")
    all_ids = [item["index"] for item in files if isinstance(item.get("index"), int)]
    selected_ids = [item["index"] for item in selected if isinstance(item.get("index"), int)]
    set_file_priorities(client, state["torrentHash"], all_ids, 0)
    set_file_priorities(client, state["torrentHash"], selected_ids, 1)
    qbit_post(client, "/torrents/start", {"hashes": state["torrentHash"]})
    state["phase"] = "season"
    state["expandedAt"] = int(time.time())
    write_state(state)
    return transaction_summary(state, client)


def cleanup(request: dict[str, Any]) -> dict[str, Any]:
    transaction_id = require_transaction(request)
    state = read_state(transaction_id)
    client = qbit_client()
    one_torrent(state, client)
    qbit_post(
        client,
        "/torrents/delete",
        {"hashes": state["torrentHash"], "deleteFiles": "true"},
    )
    try:
        state_path(transaction_id).unlink()
    except OSError as exc:
        raise VerificationError("state-cleanup-failed") from exc
    try:
        qbit_post(client, "/torrents/removeCategories", {"categories": state["category"]})
    except VerificationError:
        pass
    return {"transactionId": transaction_id, "outcome": "removed-with-files"}


def handle(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict) or request.get("schemaVersion") != SCHEMA_VERSION:
        fail("invalid-request")
    allowed = {
        "schemaVersion",
        "action",
        "seriesId",
        "seasonNumber",
        "sampleEpisode",
        "candidateId",
        "transactionId",
    }
    if set(request) - allowed:
        fail("invalid-request")
    action = request.get("action")
    handlers = {
        "search": search,
        "stage": stage,
        "status": status,
        "verify": verify,
        "expand": expand,
        "cleanup": cleanup,
    }
    if action not in handlers:
        fail("invalid-action")
    required = {
        "search": {"schemaVersion", "action", "seriesId", "seasonNumber"},
        "stage": {
            "schemaVersion",
            "action",
            "seriesId",
            "seasonNumber",
            "sampleEpisode",
            "candidateId",
        },
        "status": {"schemaVersion", "action", "transactionId"},
        "verify": {"schemaVersion", "action", "transactionId"},
        "expand": {"schemaVersion", "action", "transactionId"},
        "cleanup": {"schemaVersion", "action", "transactionId"},
    }[action]
    if set(request) != required:
        fail("invalid-request")
    return handlers[action](request)


def main() -> int:
    if os.geteuid() != 0 or len(sys.argv) != 1:
        print(json.dumps({"schemaVersion": 1, "status": "error", "code": "authority-denied"}))
        return 1
    raw = sys.stdin.buffer.read(MAX_REQUEST + 1)
    try:
        if not raw or len(raw) > MAX_REQUEST:
            fail("invalid-request")
        body = handle(json.loads(raw))
        response = {"schemaVersion": 1, "status": "ok", "body": body}
    except (UnicodeDecodeError, json.JSONDecodeError, VerificationError) as exc:
        code = str(exc) if isinstance(exc, VerificationError) else "invalid-request"
        response = {"schemaVersion": 1, "status": "error", "code": code}
    print(json.dumps(response, sort_keys=True, separators=(",", ":")))
    return 0 if response["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
