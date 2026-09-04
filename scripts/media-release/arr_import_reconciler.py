#!/usr/bin/env python3
"""Reconcile exact ledger-backed Arr downloads blocked only by ID matching."""

from __future__ import annotations

import argparse
import bisect
import copy
import datetime as dt
import hashlib
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any
import unicodedata
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_INTERVAL = 60
DEFAULT_SUCCESS_SUPPRESSION = 3600
DEFAULT_HEARTBEAT = Path("/tmp/arr-import-reconciler.heartbeat")
DEFAULT_STATE = Path("/data/arr-import-reconciler-state.json")
DEFAULT_EVENT_LOG = Path("/data/arr-import-reconciler-events.jsonl")
DEFAULT_HANDOFF_STATE = Path("/data/arr-terminal-handoff-state.json")
DEFAULT_MIN_PAYLOAD_AGE = 120
DEFAULT_MAX_HANDOFFS_PER_CYCLE = 5
DEFAULT_FFPROBE_TIMEOUT = 30
ID_MATCH_MARKERS = {
    "sonarr": "matched to series by id",
    "radarr": "matched to movie by id",
}
VIDEO_SUFFIXES = {".avi", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4", ".ts", ".webm"}
EPISODE_TOKEN_RE = re.compile(r"(?i)\bS(?P<season>\d{1,2})E(?P<episode>\d{1,3})\b")
TECHNICAL_RELEASE_TOKEN_RE = re.compile(
    r"(?i)\b(?:2160p|1080[pi]|720p|576[pi]|480[pi]|"
    r"web[ ._-]?dl|webrip|webcap|blu[ ._-]?ray|bluray|bdrip|brrip|hdtv|"
    r"x26[45]|h26[45]|hevc|av1|eac3|ac3|ddp|aac|flac|opus|dts|truehd)\b"
)
CURRENT_BETTER_MARKERS = {
    "already imported",
    "existing file",
    "not a custom format upgrade",
    "not an upgrade for existing",
}
XEM_REJECTION_MARKER = "thexem needs manual input"
IDENTITY_REJECTION_MARKERS = {
    "does not match the series",
    "does not match the movie",
}
HEVC_FORMAT_NAMES = {
    "h.265",
    "x265",
    "x265 (hd)",
    "x265 (no hdr/dv)",
}
ENGLISH_ORIGINAL_REGULAR_PROFILES = {
    "movies-regular-efficient",
    "shows-regular-efficient",
}
UNTAGGED_AUDIO_AMBIGUITY_RE = re.compile(
    r"(?i)\b(?:dual|multi(?:[ ._-]*audio)?|dubbed?|"
    r"arabic|cantonese|chinese|danish|dutch|finnish|french|german|greek|"
    r"hebrew|hindi|hungarian|italian|japanese|korean|norwegian|polish|"
    r"portuguese|romanian|russian|spanish|swedish|tamil|telugu|thai|turkish|"
    r"ara|chi|zho|dan|dut|nld|fin|fra|fre|deu|ger|ell|gre|heb|hin|hun|ita|"
    r"jpn|kor|nor|pol|por|ron|rum|rus|spa|swe|tam|tel|tha|tur)\b"
)
LANGUAGE_ALIASES = {
    "chi": "zho",
    "chinese": "zho",
    "de": "deu",
    "deu": "deu",
    "en": "eng",
    "eng": "eng",
    "english": "eng",
    "fi": "fin",
    "fin": "fin",
    "finnish": "fin",
    "fr": "fra",
    "fra": "fra",
    "fre": "fra",
    "french": "fra",
    "ger": "deu",
    "german": "deu",
    "ja": "jpn",
    "japanese": "jpn",
    "jpn": "jpn",
    "ko": "kor",
    "kor": "kor",
    "korean": "kor",
    "und": "und",
    "zho": "zho",
}


def iso_utc() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        json.dump(event, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    path.chmod(0o640)


def normalize_download_id(value: object) -> str:
    return str(value or "").strip().casefold()


def status_messages(record: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    for status in record.get("statusMessages") or []:
        messages.extend(str(message) for message in status.get("messages") or [])
    if record.get("errorMessage"):
        messages.append(str(record["errorMessage"]))
    return messages


def is_exact_id_match_block(record: dict[str, Any], app: str) -> bool:
    if str(record.get("status") or "").casefold() != "completed":
        return False
    if str(record.get("trackedDownloadState") or "").casefold() != "importblocked":
        return False
    return ID_MATCH_MARKERS[app] in "\n".join(status_messages(record)).casefold()


def rejection_reasons(candidate: dict[str, Any]) -> list[str]:
    return [
        str(item.get("reason") or item) if isinstance(item, dict) else str(item)
        for item in candidate.get("rejections") or []
    ]


def expected_episode_ids(context: dict[str, Any]) -> set[int]:
    return {
        int(episode["id"])
        for episode in context.get("expected_episodes") or []
        if isinstance(episode, dict) and isinstance(episode.get("id"), int)
    }


def episode_pair_from_name(value: object) -> tuple[int, int] | None:
    matches = list(EPISODE_TOKEN_RE.finditer(Path(str(value or "")).stem))
    if len(matches) != 1:
        return None
    match = matches[0]
    return int(match.group("season")), int(match.group("episode"))


def episode_title_region(value: object) -> str:
    stem = Path(str(value or "")).stem
    matches = list(EPISODE_TOKEN_RE.finditer(stem))
    if len(matches) != 1:
        return ""
    region = stem[matches[0].end() :]
    technical = TECHNICAL_RELEASE_TOKEN_RE.search(region)
    if technical:
        region = region[: technical.start()]
    return region.strip(" ._-[]()")


def expected_episode_pairs(context: dict[str, Any]) -> set[tuple[int, int]]:
    pairs = {
        (int(item["season"]), int(item["episode"]))
        for item in context.get("expected_episodes") or []
        if isinstance(item, dict)
        and isinstance(item.get("season"), int)
        and isinstance(item.get("episode"), int)
    }
    return pairs


def normalized_title_words(value: object) -> list[str]:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.findall(r"[a-z0-9]+", text.casefold())


def ordered_subsequence(needle: list[str], haystack: list[str]) -> bool:
    index = 0
    for word in haystack:
        if index < len(needle) and word == needle[index]:
            index += 1
    return bool(needle) and index == len(needle)


def distinctive_episode_title_matches(title: object, source: object) -> bool:
    title_words = normalized_title_words(title)
    lexical_words = [word for word in title_words if not word.isdigit()]
    return (
        len(lexical_words) >= 2
        and sum(len(word) for word in lexical_words) >= 8
        and lexical_words[0] not in {"episode", "chapter", "part"}
        and ordered_subsequence(title_words, normalized_title_words(source))
    )


def title_confirmed_xem_correction(
    client: JsonClient,
    context: dict[str, Any],
    candidates: list[dict[str, Any]],
    diagnostics: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]] | None:
    def reject(reason: str, **details: Any) -> None:
        if diagnostics is not None:
            diagnostics.clear()
            diagnostics.update({"guard": reason, **details})

    media_id = (context.get("media") or {}).get("id")
    expected = expected_episode_ids(context)
    if not isinstance(media_id, int) or len(expected) != 1 or len(candidates) != 1:
        reject(
            "scope",
            media_id=media_id,
            expected_target_ids=sorted(expected),
            candidate_count=len(candidates),
        )
        return None

    candidate = candidates[0]
    owner = candidate.get("series")
    mapped_ids = candidate_target_ids("sonarr", candidate)
    reasons = rejection_reasons(candidate)
    pair = episode_pair_from_name(candidate.get("path"))
    if not isinstance(owner, dict) or owner.get("id") != media_id:
        reject("series_identity", media_id=media_id, candidate_series_id=(owner or {}).get("id"))
        return None
    if mapped_ids != expected or len(mapped_ids) != 1:
        reject(
            "native_target_parity",
            expected_target_ids=sorted(expected),
            native_target_ids=sorted(mapped_ids),
        )
        return None
    if not reasons or not all(
        XEM_REJECTION_MARKER in reason.casefold() for reason in reasons
    ):
        reject("native_rejections", rejections=reasons)
        return None
    if pair is None:
        reject("episode_token", path=str(candidate.get("path") or ""))
        return None

    episodes = client.request("GET", "/episode", {"seriesId": media_id}) or []
    episodes = [episode for episode in episodes if isinstance(episode, dict)]
    by_id = {
        episode.get("id"): episode
        for episode in episodes
        if isinstance(episode.get("id"), int)
    }
    by_pair = {
        (episode.get("seasonNumber"), episode.get("episodeNumber")): episode
        for episode in episodes
        if isinstance(episode.get("seasonNumber"), int)
        and isinstance(episode.get("episodeNumber"), int)
    }
    mapped = by_id.get(next(iter(mapped_ids)))
    canonical = by_pair.get(pair)
    source = episode_title_region(candidate.get("path"))
    title_matches = [
        episode
        for episode in episodes
        if distinctive_episode_title_matches(episode.get("title"), source)
    ]
    if not isinstance(mapped, dict) or not isinstance(canonical, dict):
        reject(
            "episode_lookup",
            native_target_id=next(iter(mapped_ids)),
            canonical_pair=list(pair),
        )
        return None
    if mapped.get("id") == canonical.get("id"):
        reject("not_a_correction", target_id=mapped.get("id"))
        return None
    if (mapped.get("sceneSeasonNumber"), mapped.get("sceneEpisodeNumber")) != pair:
        reject(
            "scene_pair",
            filename_pair=list(pair),
            native_scene_pair=[
                mapped.get("sceneSeasonNumber"),
                mapped.get("sceneEpisodeNumber"),
            ],
        )
        return None
    if canonical.get("monitored") is False or bool(canonical.get("hasFile")):
        reject(
            "canonical_target_state",
            target_id=canonical.get("id"),
            monitored=canonical.get("monitored"),
            has_file=canonical.get("hasFile"),
        )
        return None
    canonical_title_matches = distinctive_episode_title_matches(
        canonical.get("title"), source
    )
    mapped_title_matches = distinctive_episode_title_matches(mapped.get("title"), source)
    title_match_ids = {episode.get("id") for episode in title_matches}
    if (
        not canonical_title_matches
        or mapped_title_matches
        or title_match_ids != {canonical.get("id")}
    ):
        reject(
            "canonical_title",
            title_region=source,
            canonical_target_id=canonical.get("id"),
            canonical_title=canonical.get("title"),
            canonical_title_matches=canonical_title_matches,
            native_target_id=mapped.get("id"),
            native_title=mapped.get("title"),
            native_title_matches=mapped_title_matches,
            title_match_ids=sorted(
                target_id for target_id in title_match_ids if isinstance(target_id, int)
            ),
        )
        return None

    corrected_context = copy.deepcopy(context)
    corrected_context["expected_episodes"] = [
        {
            "id": canonical["id"],
            "season": canonical["seasonNumber"],
            "episode": canonical["episodeNumber"],
            "title": canonical.get("title"),
        }
    ]
    corrected_context["current_files"] = [
        {"target_id": canonical["id"], "has_file": False}
    ]
    corrected_candidate = copy.deepcopy(candidate)
    corrected_candidate["episodes"] = [canonical]
    corrected_candidate["rejections"] = []
    correction = {
        "from_target_id": mapped.get("id"),
        "from_season": mapped.get("seasonNumber"),
        "from_episode": mapped.get("episodeNumber"),
        "from_title": mapped.get("title"),
        "to_target_id": canonical.get("id"),
        "to_season": canonical.get("seasonNumber"),
        "to_episode": canonical.get("episodeNumber"),
        "to_title": canonical.get("title"),
        "scene_pair": list(pair),
        "title_region": source,
    }
    return corrected_context, [corrected_candidate], correction


def is_canonical_title_collision_current_better(
    context: dict[str, Any],
    candidates: list[dict[str, Any]],
    probes: list[dict[str, Any]],
) -> bool:
    media = context.get("media") if isinstance(context.get("media"), dict) else {}
    media_id = media.get("id")
    year = media.get("year")
    canonical_title = str(context.get("canonical_title") or "").strip()
    expected = expected_episode_pairs(context)
    if (
        context.get("identity_conflict")
        or not isinstance(media_id, int)
        or not isinstance(year, int)
        or str(year) not in canonical_title
        or not expected
        or len(candidates) != len(probes)
        or len(probes) != len(expected)
    ):
        return False

    canonical_prefix = f"{canonical_title} - ".casefold()
    probe_pairs: set[tuple[int, int]] = set()
    for probe in probes:
        name = str(probe.get("name") or "")
        pair = episode_pair_from_name(name)
        if not name.casefold().startswith(canonical_prefix) or pair is None:
            return False
        probe_pairs.add(pair)
    if probe_pairs != expected:
        return False

    candidate_pairs: set[tuple[int, int]] = set()
    for candidate in candidates:
        owner = candidate.get("series")
        episodes = candidate.get("episodes") or []
        reasons = rejection_reasons(candidate)
        pair = episode_pair_from_name(candidate.get("path"))
        if (
            not isinstance(owner, dict)
            or owner.get("id") == media_id
            or len(episodes) != 1
            or pair is None
            or pair
            != (
                episodes[0].get("seasonNumber"),
                episodes[0].get("episodeNumber"),
            )
            or not reasons
            or not any(
                any(marker in reason.casefold() for marker in CURRENT_BETTER_MARKERS)
                for reason in reasons
            )
            or not all(
                "was not found in the grabbed release" in reason.casefold()
                or any(marker in reason.casefold() for marker in CURRENT_BETTER_MARKERS)
                for reason in reasons
            )
        ):
            return False
        candidate_pairs.add(pair)
    return candidate_pairs == expected


def candidate_target_ids(app: str, candidate: dict[str, Any]) -> set[int]:
    if app == "sonarr":
        return {
            int(episode["id"])
            for episode in candidate.get("episodes") or []
            if isinstance(episode, dict) and isinstance(episode.get("id"), int)
        }
    movie = candidate.get("movie") or {}
    movie_id = movie.get("id")
    return {int(movie_id)} if isinstance(movie_id, int) else set()


def candidate_is_monitored(app: str, candidate: dict[str, Any]) -> bool:
    if app == "sonarr":
        episodes = candidate.get("episodes") or []
        return bool(episodes) and all(bool(episode.get("monitored")) for episode in episodes)
    return (candidate.get("movie") or {}).get("monitored") is not False


def custom_format_names(values: object) -> list[str]:
    result: list[str] = []
    for value in values or []:
        name = value.get("name") if isinstance(value, dict) else value
        name = str(name or "").strip()
        if name and name not in result:
            result.append(name)
    return result


def candidate_diagnostics(
    app: str,
    context: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    media_id = (context.get("media") or {}).get("id")
    expected = expected_episode_ids(context) if app == "sonarr" else {media_id}
    grabbed_formats = set(custom_format_names(context.get("custom_formats")))
    diagnostics: list[dict[str, Any]] = []
    for candidate in candidates:
        owner = candidate.get("series") if app == "sonarr" else candidate.get("movie")
        targets = candidate_target_ids(app, candidate)
        if (
            not isinstance(owner, dict)
            or owner.get("id") != media_id
            or not targets
            or not targets.issubset(expected)
        ):
            continue
        reasons = rejection_reasons(candidate)
        import_formats = set(custom_format_names(candidate.get("customFormats")))
        lost_formats = sorted(grabbed_formats - import_formats) if "customFormats" in candidate else []
        grab_score = context.get("custom_format_score")
        import_score = candidate.get("customFormatScore")
        score_changed = (
            isinstance(grab_score, int)
            and isinstance(import_score, int)
            and import_score != grab_score
        )
        reason_text = "\n".join(reasons).casefold()
        if context.get("identity_conflict"):
            classification = "identity_conflict"
        elif "not a custom format upgrade" in reason_text or "existing file" in reason_text:
            classification = "current_better"
        elif lost_formats and score_changed:
            classification = "grab_import_cf_drift"
        elif reasons:
            classification = "native_rejection"
        elif any(bool(item.get("hasFile")) for item in candidate.get("episodes") or []):
            classification = "eligible_upgrade"
        elif app == "radarr" and bool((candidate.get("movie") or {}).get("hasFile")):
            classification = "eligible_upgrade"
        else:
            classification = "eligible_missing"
        diagnostics.append(
            {
                "path": candidate.get("path"),
                "target_ids": sorted(targets),
                "classification": classification,
                "grab_score": grab_score,
                "import_score": import_score,
                "lost_formats": lost_formats,
                "gained_formats": sorted(import_formats - grabbed_formats)
                if "customFormats" in candidate
                else [],
                "rejections": reasons,
            }
        )
    return diagnostics


def select_candidates(
    app: str,
    context: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if context.get("app") != app or context.get("identity_conflict"):
        return []
    media_id = (context.get("media") or {}).get("id")
    if not isinstance(media_id, int):
        return []
    expected = expected_episode_ids(context) if app == "sonarr" else {media_id}
    if not expected:
        return []

    selected: list[dict[str, Any]] = []
    for candidate in candidates:
        if rejection_reasons(candidate) or not candidate.get("path"):
            continue
        owner = candidate.get("series") if app == "sonarr" else candidate.get("movie")
        if not isinstance(owner, dict) or owner.get("id") != media_id:
            continue
        targets = candidate_target_ids(app, candidate)
        if not targets or not targets.issubset(expected):
            continue
        if not candidate_is_monitored(app, candidate):
            continue
        selected.append(candidate)
    target_counts: dict[int, int] = {}
    for candidate in selected:
        for target in candidate_target_ids(app, candidate):
            target_counts[target] = target_counts.get(target, 0) + 1
    if any(count > 1 for count in target_counts.values()):
        return []
    return selected


def import_file(app: str, candidate: dict[str, Any], download_id: str) -> dict[str, Any]:
    common = {
        "path": candidate["path"],
        "folderName": candidate.get("folderName"),
        "quality": candidate.get("quality"),
        "languages": candidate.get("languages") or [],
        "releaseGroup": candidate.get("releaseGroup"),
        "indexerFlags": candidate.get("indexerFlags", 0),
        "downloadId": candidate.get("downloadId") or download_id,
    }
    if app == "sonarr":
        common.update(
            {
                "seriesId": candidate["series"]["id"],
                "episodeIds": sorted(candidate_target_ids(app, candidate)),
                "episodeFileId": candidate.get("episodeFileId") or 0,
                "releaseType": candidate.get("releaseType"),
            }
        )
    else:
        common.update(
            {
                "movieId": candidate["movie"]["id"],
                "movieFileId": candidate.get("movieFileId") or 0,
            }
        )
    return common


class JsonClient:
    def __init__(self, base_url: str, api_key: str = "", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        query = "?" + urllib.parse.urlencode(params, doseq=True) if params else ""
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}/{path.lstrip('/')}{query}",
            data=data,
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = response.read()
        return json.loads(payload.decode("utf-8")) if payload else None


class QbitClient:
    def __init__(self, base_url: str, username: str, password: str, timeout: int = 30):
        if not base_url or not username or not password:
            raise ValueError("qBittorrent API URL and credentials are required")
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        encoded = urllib.parse.urlencode(params or {}, doseq=True)
        data = encoded.encode("utf-8") if method == "POST" else None
        query = f"?{encoded}" if method == "GET" and encoded else ""
        request = urllib.request.Request(
            f"{self.base_url}/{path.lstrip('/')}{query}",
            data=data,
            headers={"Accept": "application/json"},
            method=method,
        )
        with self.opener.open(request, timeout=self.timeout) as response:
            payload = response.read()
        content_type = response.headers.get_content_type()
        if not payload:
            return None
        if content_type == "application/json" or payload[:1] in {b"{", b"["}:
            return json.loads(payload.decode("utf-8"))
        return payload.decode("utf-8", errors="replace")

    def login(self) -> None:
        response = self.request(
            "POST",
            "/auth/login",
            {"username": self.username, "password": self.password},
        )
        if str(response or "").strip() not in {"", "Ok."}:
            raise RuntimeError("qBittorrent API login failed")

    def version(self) -> str:
        return str(self.request("GET", "/app/version") or "").strip()

    def torrent(self, download_id: str) -> dict[str, Any] | None:
        torrents = self.request("GET", "/torrents/info", {"hashes": download_id}) or []
        normalized = normalize_download_id(download_id)
        matches = [
            torrent
            for torrent in torrents
            if normalize_download_id(torrent.get("hash")) == normalized
        ]
        return matches[0] if len(matches) == 1 else None

    def files(self, download_id: str) -> list[dict[str, Any]]:
        files = self.request("GET", "/torrents/files", {"hash": download_id}) or []
        return [item for item in files if isinstance(item, dict)]

    def set_share_limits(self, download_id: str, torrent: dict[str, Any], action: str) -> None:
        self.request(
            "POST",
            "/torrents/setShareLimits",
            {
                "hashes": download_id,
                "ratioLimit": torrent.get("ratio_limit", -2),
                "seedingTimeLimit": torrent.get("seeding_time_limit", -2),
                "inactiveSeedingTimeLimit": torrent.get("inactive_seeding_time_limit", -2),
                "shareLimitAction": action,
            },
        )


def version_tuple(value: str) -> tuple[int, ...]:
    match = re.search(r"\d+(?:\.\d+)+", value)
    return tuple(int(part) for part in match.group(0).split(".")) if match else ()


def profile_fingerprint(profile: object) -> str | None:
    if not isinstance(profile, dict):
        return None
    encoded = json.dumps(profile, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def quality_name(value: object) -> str | None:
    if not isinstance(value, dict):
        text = str(value or "").strip()
        return text or None
    quality = value.get("quality", value)
    if isinstance(quality, dict):
        text = str(quality.get("name") or "").strip()
        return text or None
    text = str(quality or "").strip()
    return text or None


def current_file_snapshot(target_id: int, media_file: object) -> dict[str, Any]:
    if not isinstance(media_file, dict):
        return {"target_id": target_id, "has_file": False}
    return {
        "target_id": target_id,
        "has_file": True,
        "file_id": media_file.get("id"),
        "quality": quality_name(media_file.get("quality")),
        "custom_format_score": media_file.get("customFormatScore"),
        "custom_formats": custom_format_names(media_file.get("customFormats")),
    }


def current_policy_state(
    app: str,
    client: JsonClient,
    context: dict[str, Any],
) -> tuple[str | None, list[dict[str, Any]]]:
    profile = context.get("quality_profile") or {}
    profile_id = profile.get("id")
    media_id = (context.get("media") or {}).get("id")
    current_media: dict[str, Any] = {}
    if not isinstance(profile_id, int) and isinstance(media_id, int):
        current_media = client.request(
            "GET", f"/{'series' if app == 'sonarr' else 'movie'}/{media_id}"
        ) or {}
        profile_id = current_media.get("qualityProfileId")
    current_profile = (
        client.request("GET", f"/qualityprofile/{profile_id}")
        if isinstance(profile_id, int)
        else None
    )
    fingerprint = profile_fingerprint(current_profile)
    if isinstance(current_profile, dict):
        context["current_quality_profile_name"] = current_profile.get("name")

    if app == "radarr":
        if not isinstance(media_id, int):
            return fingerprint, []
        movie = current_media or client.request("GET", f"/movie/{media_id}") or {}
        return fingerprint, [current_file_snapshot(media_id, movie.get("movieFile"))]

    expected = expected_episode_ids(context)
    if not isinstance(media_id, int) or not expected:
        return fingerprint, []
    episodes = client.request("GET", "/episode", {"seriesId": media_id}) or []
    episode_files = client.request("GET", "/episodefile", {"seriesId": media_id}) or []
    files_by_id = {
        item.get("id"): item
        for item in episode_files
        if isinstance(item, dict) and isinstance(item.get("id"), int)
    }
    episodes_by_id = {
        item.get("id"): item
        for item in episodes
        if isinstance(item, dict) and item.get("id") in expected
    }
    return fingerprint, [
        current_file_snapshot(
            target_id,
            files_by_id.get((episodes_by_id.get(target_id) or {}).get("episodeFileId")),
        )
        for target_id in sorted(expected)
    ]


class ReconcileState:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, str] = {}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data = {str(key): str(value) for key, value in loaded.items()}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

    def has(self, app: str, download_id: str) -> bool:
        value = self.data.get(f"{app}:{normalize_download_id(download_id)}")
        if not value:
            return False
        try:
            observed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return (dt.datetime.now(dt.UTC) - observed).total_seconds() <= DEFAULT_SUCCESS_SUPPRESSION

    def mark(self, app: str, download_id: str) -> None:
        self.data[f"{app}:{normalize_download_id(download_id)}"] = iso_utc()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.path)


class HandoffState:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] = {
            "completed": {},
            "pending_imports": {},
            "pending_searches": {},
            "searches": {},
            "cursors": {},
        }
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                for key in self.data:
                    if isinstance(loaded.get(key), dict):
                        self.data[key] = loaded[key]
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        for key, value in list(self.data["completed"].items()):
            if (
                isinstance(value, dict)
                and value.get("classification") == "validated_import_submitted"
            ):
                self.data["pending_imports"][key] = value
                del self.data["completed"][key]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o640)
        temporary.replace(self.path)

    def mark_completed(self, app: str, download_id: str, classification: str) -> None:
        self.data["completed"][f"{app}:{normalize_download_id(download_id)}"] = {
            "at": iso_utc(),
            "classification": classification,
        }
        self.save()

    def is_completed(self, app: str, download_id: str) -> bool:
        return f"{app}:{normalize_download_id(download_id)}" in self.data["completed"]

    def pending_import(self, app: str, download_id: str) -> dict[str, Any] | None:
        value = self.data["pending_imports"].get(
            f"{app}:{normalize_download_id(download_id)}"
        )
        return value if isinstance(value, dict) else None

    def mark_pending_import(
        self,
        app: str,
        download_id: str,
        command_id: int | None,
    ) -> None:
        self.data["pending_imports"][
            f"{app}:{normalize_download_id(download_id)}"
        ] = {
            "at": iso_utc(),
            "command_id": command_id,
        }
        self.save()

    def clear_pending_import(self, app: str, download_id: str) -> None:
        self.data["pending_imports"].pop(
            f"{app}:{normalize_download_id(download_id)}", None
        )
        self.save()

    def prune_pending_imports(self, app: str, active_download_ids: set[str]) -> None:
        prefix = f"{app}:"
        stale = [
            key
            for key in self.data["pending_imports"]
            if key.startswith(prefix) and key.removeprefix(prefix) not in active_download_ids
        ]
        if not stale:
            return
        for key in stale:
            del self.data["pending_imports"][key]
        self.save()

    def finish_pending_import(self, app: str, download_id: str) -> None:
        self.data["pending_imports"].pop(
            f"{app}:{normalize_download_id(download_id)}", None
        )
        self.data["completed"][f"{app}:{normalize_download_id(download_id)}"] = {
            "at": iso_utc(),
            "classification": "validated_import_completed",
        }
        self.save()

    def has_pending_imports(self, app: str) -> bool:
        prefix = f"{app}:"
        return any(key.startswith(prefix) for key in self.data["pending_imports"])

    def stage_search(self, app: str, key: str, body: dict[str, Any]) -> None:
        if key in self.data["pending_searches"]:
            return
        self.data["pending_searches"][key] = {
            "app": app,
            "at": iso_utc(),
            "body": body,
        }
        self.save()

    def pending_searches(self, app: str) -> list[tuple[str, dict[str, Any]]]:
        return sorted(
            (
                (key, value)
                for key, value in self.data["pending_searches"].items()
                if isinstance(value, dict) and value.get("app") == app
            ),
            key=lambda item: item[0],
        )

    def clear_pending_search(self, key: str) -> None:
        if self.data["pending_searches"].pop(key, None) is not None:
            self.save()

    def finish_pending_search(self, key: str) -> None:
        self.data["pending_searches"].pop(key, None)
        self.data["searches"][key] = iso_utc()
        self.save()

    def cursor(self, app: str) -> str:
        return normalize_download_id(self.data["cursors"].get(app))

    def mark_cursor(self, app: str, download_id: str) -> None:
        self.data["cursors"][app] = normalize_download_id(download_id)
        self.save()

    def search_is_allowed(self, key: str, cooldown_hours: int = 24) -> bool:
        value = (self.data.get("searches") or {}).get(key)
        if not isinstance(value, str):
            return True
        observed = parse_history_date(value)
        return observed is None or (
            dt.datetime.now(dt.UTC) - observed
        ) >= dt.timedelta(hours=cooldown_hours)

    def mark_search(self, key: str) -> None:
        self.data["searches"][key] = iso_utc()
        self.save()


def ledger_context(ledger: JsonClient, download_id: str) -> dict[str, Any] | None:
    try:
        payload = ledger.request("GET", f"/v1/context/{urllib.parse.quote(download_id, safe='')}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return payload.get("context") if isinstance(payload, dict) else None


def wait_for_command(
    client: JsonClient,
    command_id: int,
    timeout: int = 180,
    heartbeat: Path | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        if heartbeat is not None:
            write_heartbeat(heartbeat)
        last = client.request("GET", f"/command/{command_id}") or {}
        if str(last.get("status") or "").casefold() in {"completed", "failed"}:
            return last
        time.sleep(2)
    return last


def manual_import_command(
    client: JsonClient,
    download_id: str,
) -> dict[str, Any] | None:
    normalized = normalize_download_id(download_id)
    commands = client.request("GET", "/command") or []
    matches = []
    for command in commands if isinstance(commands, list) else []:
        if str(command.get("name") or "").casefold() != "manualimport":
            continue
        files = (command.get("body") or {}).get("files") or []
        if any(
            normalize_download_id(item.get("downloadId")) == normalized
            for item in files
            if isinstance(item, dict)
        ):
            matches.append(command)
    return max(
        matches,
        key=lambda item: int(item.get("id") or 0),
        default=None,
    )


def reconcile_pending_import(
    app: str,
    client: JsonClient,
    state: HandoffState,
    download_id: str,
) -> dict[str, Any] | None:
    pending = state.pending_import(app, download_id)
    if pending is None:
        return None
    command_id = pending.get("command_id")
    command: dict[str, Any] | None = None
    if isinstance(command_id, int):
        try:
            candidate = client.request("GET", f"/command/{command_id}") or {}
            command = candidate if isinstance(candidate, dict) else None
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
    if command is None:
        command = manual_import_command(client, download_id)
        command_id = command.get("id") if isinstance(command, dict) else None
        if isinstance(command_id, int):
            state.mark_pending_import(app, download_id, command_id)
    if command is None:
        state.clear_pending_import(app, download_id)
        return None

    status = str(command.get("status") or "").casefold()
    if status == "completed":
        state.finish_pending_import(app, download_id)
        return {
            "result": "native_import_completed_waiting_for_queue_refresh",
            "command_id": command_id,
            "command_status": status,
        }
    if status in {"failed", "cancelled", "aborted"}:
        state.clear_pending_import(app, download_id)
        return None
    return {
        "result": "native_import_pending",
        "command_id": command_id,
        "command_status": status or "unknown",
    }


def queue_records(app: str, client: JsonClient) -> list[dict[str, Any]]:
    queue_params: dict[str, Any] = {"pageSize": 1000}
    queue_params.update(
        {"includeSeries": "true", "includeEpisode": "true"}
        if app == "sonarr"
        else {"includeMovie": "true"}
    )
    records: list[dict[str, Any]] = []
    for page in range(1, 21):
        payload = client.request("GET", "/queue", {**queue_params, "page": page}) or {}
        page_records = payload.get("records", payload if isinstance(payload, list) else [])
        records.extend(item for item in page_records if isinstance(item, dict))
        total = payload.get("totalRecords") if isinstance(payload, dict) else None
        if (isinstance(total, int) and len(records) >= total) or len(page_records) < 1000:
            break
    return records


def reconcile_app(
    app: str,
    client: JsonClient,
    ledger: JsonClient,
    state: ReconcileState,
    dry_run: bool,
    heartbeat: Path | None = None,
) -> list[dict[str, Any]]:
    records = queue_records(app, client)
    results: list[dict[str, Any]] = []
    seen_download_ids: set[str] = set()
    for record in records:
        if heartbeat is not None:
            write_heartbeat(heartbeat)
        if not is_exact_id_match_block(record, app):
            continue
        download_id = str(record.get("downloadId") or "")
        normalized_download_id = normalize_download_id(download_id)
        if (
            not normalized_download_id
            or normalized_download_id in seen_download_ids
            or state.has(app, download_id)
        ):
            continue
        seen_download_ids.add(normalized_download_id)
        context = ledger_context(ledger, download_id)
        if not context:
            continue
        media_id = (context.get("media") or {}).get("id")
        params: dict[str, Any] = {
            "downloadId": download_id,
            "filterExistingFiles": "false",
        }
        if app == "radarr" and isinstance(media_id, int):
            params["movieId"] = media_id
        candidates = client.request("GET", "/manualimport", params) or []
        selected = select_candidates(app, context, candidates)
        result = {
            "app": app,
            "download_id": normalized_download_id,
            "media_id": media_id,
            "selected": len(selected),
            "paths": [candidate.get("path") for candidate in selected],
            "dry_run": dry_run,
            "identity_conflict": bool(context.get("identity_conflict")),
            "candidate_diagnostics": candidate_diagnostics(app, context, candidates),
        }
        if not selected:
            result["result"] = "no_safe_candidate"
            results.append(result)
            continue
        if dry_run:
            result["result"] = "would_import"
            results.append(result)
            continue
        # Persist before the request so an accepted command with a lost API
        # response cannot be submitted again on the next reconciliation pass.
        state.mark(app, download_id)
        command = client.request(
            "POST",
            "/command",
            body={
                "name": "ManualImport",
                "files": [import_file(app, candidate, download_id) for candidate in selected],
                "importMode": "Auto",
            },
        ) or {}
        command_id = command.get("id")
        final = (
            wait_for_command(client, int(command_id), heartbeat=heartbeat)
            if isinstance(command_id, int)
            else command
        )
        result.update(
            {
                "command_id": command_id,
                "command_status": final.get("status"),
                "command_message": final.get("message"),
            }
        )
        if str(final.get("status") or "").casefold() == "completed":
            result["result"] = "imported"
        else:
            result["result"] = "command_failed"
        results.append(result)
    return results


def normalize_language(value: object) -> str:
    text = str(value or "").strip().casefold()
    if not text:
        return "und"
    return LANGUAGE_ALIASES.get(text, text[:3] if len(text) >= 3 else text)


def qbit_payload_path(torrent: dict[str, Any], item: dict[str, Any]) -> Path:
    save_path = Path(str(torrent.get("save_path") or ""))
    relative = Path(str(item.get("name") or ""))
    if not save_path.is_absolute() or relative.is_absolute() or not relative.parts:
        raise ValueError("qBittorrent returned an invalid payload path")
    path = (save_path / relative).resolve(strict=True)
    data_root = Path("/data").resolve(strict=True)
    if not path.is_relative_to(data_root):
        raise ValueError("qBittorrent payload path escapes the read-only /data mount")
    return path


def ffprobe_payload_file(path: Path, timeout: int) -> dict[str, Any]:
    before = path.stat()
    process = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=index,codec_type,codec_name,width,height:stream_tags=language,title",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    after = path.stat()
    if process.returncode != 0:
        raise ValueError(f"ffprobe failed for {path.name}: {process.stderr.strip()[:200]}")
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"payload changed while probing: {path.name}")
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"ffprobe returned invalid JSON for {path.name}") from exc
    streams = payload.get("streams") if isinstance(payload, dict) else []
    video = [item for item in streams or [] if item.get("codec_type") == "video"]
    audio = [item for item in streams or [] if item.get("codec_type") == "audio"]
    subtitles = [item for item in streams or [] if item.get("codec_type") == "subtitle"]

    def languages(values: list[dict[str, Any]]) -> list[str]:
        result = {
            normalize_language((item.get("tags") or {}).get("language"))
            for item in values
        }
        return sorted(result)

    return {
        "name": path.name,
        "size": before.st_size,
        "inode": before.st_ino,
        "links": before.st_nlink,
        "video_codecs": sorted(
            {str(item.get("codec_name") or "unknown").casefold() for item in video}
        ),
        "video_dimensions": sorted(
            {
                f"{int(item.get('width') or 0)}x{int(item.get('height') or 0)}"
                for item in video
            }
        ),
        "audio_languages": languages(audio),
        "subtitle_languages": languages(subtitles),
        "video_streams": len(video),
        "audio_streams": len(audio),
        "subtitle_streams": len(subtitles),
    }


def payload_probes(
    torrent: dict[str, Any],
    files: list[dict[str, Any]],
    min_payload_age: int,
    ffprobe_timeout: int,
) -> tuple[list[dict[str, Any]], dict[str, Path]]:
    try:
        complete = float(torrent.get("progress") or 0) >= 1.0
        amount_left = int(torrent.get("amount_left") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("qBittorrent completion state is invalid") from exc
    completion_on = int(torrent.get("completion_on") or 0)
    if not complete or amount_left != 0:
        raise ValueError("qBittorrent payload is not complete")
    if completion_on <= 0 or time.time() - completion_on < min_payload_age:
        raise ValueError("qBittorrent payload has not reached the minimum stable age")
    if str(torrent.get("state") or "").casefold() in {
        "checkingup",
        "checkingresumedata",
        "moving",
    }:
        raise ValueError("qBittorrent payload is still changing state")

    media_items = [
        item
        for item in files
        if Path(str(item.get("name") or "")).suffix.casefold() in VIDEO_SUFFIXES
    ]
    if not media_items:
        raise ValueError("qBittorrent payload contains no supported media files")
    probes: list[dict[str, Any]] = []
    paths: dict[str, Path] = {}
    for item in media_items:
        try:
            progress = float(item.get("progress") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("qBittorrent file progress is invalid") from exc
        if progress < 1.0:
            raise ValueError(f"qBittorrent media file is incomplete: {item.get('name')}")
        path = qbit_payload_path(torrent, item)
        expected_size = item.get("size")
        if isinstance(expected_size, int) and path.stat().st_size != expected_size:
            raise ValueError(f"qBittorrent file size does not match disk: {path.name}")
        probe = ffprobe_payload_file(path, ffprobe_timeout)
        if not probe["video_streams"] or not probe["audio_streams"]:
            raise ValueError(f"payload lacks required video/audio streams: {path.name}")
        probes.append(probe)
        paths[str(path)] = path
    return probes, paths


def filesystem_payload_probes(
    rows: list[dict[str, Any]],
    min_payload_age: int,
    ffprobe_timeout: int,
) -> tuple[list[dict[str, Any]], dict[str, Path]]:
    roots = {
        str(row.get("outputPath") or "").strip()
        for row in rows
        if str(row.get("outputPath") or "").strip()
    }
    if len(roots) != 1:
        raise ValueError("Usenet queue rows do not have one exact payload root")
    root = Path(roots.pop()).resolve(strict=True)
    data_root = Path("/data").resolve(strict=True)
    try:
        root.relative_to(data_root)
    except ValueError as exc:
        raise ValueError("Usenet payload root is outside the read-only media mount") from exc
    if any(part.casefold().startswith("_unpack_") for part in root.parts):
        raise ValueError("Usenet payload is still being unpacked")

    candidates = [root] if root.is_file() else sorted(root.rglob("*"))
    media_paths: list[Path] = []
    for candidate in candidates:
        if not candidate.is_file() or candidate.suffix.casefold() not in VIDEO_SUFFIXES:
            continue
        resolved = candidate.resolve(strict=True)
        try:
            resolved.relative_to(data_root)
        except ValueError as exc:
            raise ValueError("Usenet payload file escapes the read-only media mount") from exc
        if any(part.casefold().startswith("_unpack_") for part in resolved.parts):
            raise ValueError("Usenet payload is still being unpacked")
        media_paths.append(resolved)
    if not media_paths:
        raise ValueError("Usenet payload contains no supported media files")

    probes: list[dict[str, Any]] = []
    paths: dict[str, Path] = {}
    for path in media_paths:
        if time.time() - path.stat().st_mtime < min_payload_age:
            raise ValueError("Usenet payload has not reached the minimum stable age")
        probe = ffprobe_payload_file(path, ffprobe_timeout)
        if not probe["video_streams"] or not probe["audio_streams"]:
            raise ValueError(f"payload lacks required video/audio streams: {path.name}")
        probes.append(probe)
        paths[str(path)] = path
    return probes, paths


def release_claims(context: dict[str, Any]) -> dict[str, Any]:
    title = str(context.get("source_title") or "")
    folded = title.casefold()
    formats = {name.casefold() for name in custom_format_names(context.get("custom_formats"))}
    dual_title = bool(
        re.search(r"\bdual[ ._-]*audio\b|\bdual\b(?![ ._-]*subs?\b)", folded)
        or re.search(r"\bmulti[ ._-]*audio\b", folded)
        or re.search(
            r"\b(?:ja|jp|jpn)[+ ._-]+(?:en|eng)\b|\b(?:en|eng)[+ ._-]+(?:ja|jp|jpn)\b",
            folded,
        )
    )
    resolution_match = re.search(r"\b(2160|1080|720|576|480)p\b", folded)
    if not resolution_match:
        resolution_match = re.search(r"(2160|1080|720|576|480)p", str(context.get("quality") or ""), re.I)
    return {
        # A metadata-backed DA format can match without the release title making
        # that claim, and it may carry zero score in this profile. Only title
        # evidence is a pre-download dual-audio contract.
        "dual_audio": dual_title,
        "hevc": bool(re.search(r"\b(?:x265|h[ .]?265|hevc)\b", folded))
        or bool(formats & HEVC_FORMAT_NAMES),
        "resolution": int(resolution_match.group(1)) if resolution_match else None,
    }


def dimensions_meet_resolution(dimensions: list[str], expected: int) -> bool:
    parsed: list[tuple[int, int]] = []
    for value in dimensions:
        match = re.fullmatch(r"(\d+)x(\d+)", value)
        if match:
            parsed.append((int(match.group(1)), int(match.group(2))))
    if not parsed:
        return False
    minimums = {
        2160: (3000, 1600),
        1080: (1400, 800),
        720: (900, 500),
        576: (700, 400),
        480: (600, 350),
    }
    long_min, short_min = minimums[expected]
    return any(
        max(width, height) >= long_min or min(width, height) >= short_min
        for width, height in parsed
    )


def payload_contract(
    context: dict[str, Any],
    probes: list[dict[str, Any]],
    allow_english_original_und_audio: bool = False,
) -> tuple[
    list[dict[str, str]],
    list[dict[str, str]],
    list[dict[str, str]],
]:
    claims = release_claims(context)
    original_languages = {
        normalize_language(value) for value in context.get("original_languages") or []
    } - {"und"}
    failures: list[dict[str, str]] = []
    unverifiable: list[dict[str, str]] = []
    assumptions: list[dict[str, str]] = []
    profile_name = str(
        (context.get("quality_profile") or {}).get("name")
        or context.get("current_quality_profile_name")
        or ""
    )
    source_title = str(context.get("source_title") or "")
    for probe in probes:
        name = str(probe["name"])
        codecs = set(probe["video_codecs"])
        languages = set(probe["audio_languages"])
        if claims["hevc"] and not codecs.intersection({"hevc", "h265", "x265"}):
            failures.append({"file": name, "claim": "hevc", "actual": ",".join(sorted(codecs))})
        resolution = claims["resolution"]
        if isinstance(resolution, int) and not dimensions_meet_resolution(
            probe["video_dimensions"], resolution
        ):
            failures.append(
                {
                    "file": name,
                    "claim": f"{resolution}p",
                    "actual": ",".join(probe["video_dimensions"]),
                }
            )
        if original_languages and not original_languages.issubset(languages):
            evidence = ",".join(sorted(languages)) or "none"
            eligible_untagged_english = (
                allow_english_original_und_audio
                and original_languages == {"eng"}
                and profile_name.casefold() in ENGLISH_ORIGINAL_REGULAR_PROFILES
                and probe.get("audio_streams") == 1
                and languages == {"und"}
                and not UNTAGGED_AUDIO_AMBIGUITY_RE.search(source_title)
            )
            if eligible_untagged_english:
                assumptions.append(
                    {
                        "file": name,
                        "assumption": "single_untagged_audio_is_original_english",
                        "profile": profile_name,
                    }
                )
            elif "und" in languages or not languages:
                unverifiable.append(
                    {"file": name, "claim": "original_audio", "actual": evidence}
                )
            else:
                failures.append(
                    {"file": name, "claim": "original_audio", "actual": evidence}
                )
        if not claims["dual_audio"]:
            continue
        required = {"eng"} if original_languages == {"eng"} else {"eng", *original_languages}
        if not original_languages:
            unverifiable.append({"file": name, "claim": "dual_audio", "actual": "original language unknown"})
        elif "und" in languages and not required.issubset(languages):
            unverifiable.append(
                {"file": name, "claim": "dual_audio", "actual": ",".join(sorted(languages))}
            )
        elif not required.issubset(languages):
            failures.append(
                {"file": name, "claim": "dual_audio", "actual": ",".join(sorted(languages))}
            )
    return failures, unverifiable, assumptions


def path_key(value: object) -> str:
    try:
        return str(Path(str(value or "")).resolve(strict=True))
    except (OSError, RuntimeError):
        return ""


def captured_files_changed(
    captured: object,
    current: list[dict[str, Any]],
) -> bool:
    if not isinstance(captured, list) or not captured:
        return False
    old = {item.get("target_id"): item for item in captured if isinstance(item, dict)}
    new = {item.get("target_id"): item for item in current if isinstance(item, dict)}
    if not old or old.keys() != new.keys():
        return False
    return any(
        bool(old[target].get("has_file")) != bool(new[target].get("has_file"))
        or old[target].get("file_id") != new[target].get("file_id")
        for target in old
    )


def classify_terminal_download(
    app: str,
    context: dict[str, Any],
    candidates: list[dict[str, Any]],
    probes: list[dict[str, Any]],
    payload_paths: dict[str, Path],
    current_profile_fingerprint: str | None,
    current_files: list[dict[str, Any]],
    allow_english_original_und_audio: bool = False,
) -> dict[str, Any]:
    expected = expected_episode_ids(context) if app == "sonarr" else {(context.get("media") or {}).get("id")}
    expected.discard(None)
    candidate_paths: set[str] = set()
    canonical_title_collision = is_canonical_title_collision_current_better(
        context, candidates, probes
    ) if app == "sonarr" else False
    native_terminal = True
    has_eligible = False
    context_identity_conflict = bool(context.get("identity_conflict"))
    identity_mismatch = False
    target_mismatch = False
    eligible_target_counts: dict[int, int] = {}
    per_file: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_path = path_key(candidate.get("path"))
        if candidate_path:
            candidate_paths.add(candidate_path)
        owner = candidate.get("series") if app == "sonarr" else candidate.get("movie")
        targets = candidate_target_ids(app, candidate)
        reasons = rejection_reasons(candidate)
        reason_text = "\n".join(reasons).casefold()
        if (
            isinstance(owner, dict)
            and owner.get("id") != (context.get("media") or {}).get("id")
            and not canonical_title_collision
        ) or any(
            marker in reason_text for marker in IDENTITY_REJECTION_MARKERS
        ):
            identity_mismatch = True
        if targets and not targets.issubset(expected) and not canonical_title_collision:
            target_mismatch = True
            native_terminal = False
        if not isinstance(owner, dict) or not targets:
            native_terminal = False
        if not reasons:
            has_eligible = True
            native_classification = "accepted"
            for target in targets:
                eligible_target_counts[target] = eligible_target_counts.get(target, 0) + 1
        elif canonical_title_collision or all(
            any(marker in reason.casefold() for marker in CURRENT_BETTER_MARKERS)
            for reason in reasons
        ):
            native_classification = "current_better"
        else:
            native_classification = "unverifiable"
            native_terminal = False
        per_file.append(
            {
                "name": Path(candidate_path).name if candidate_path else None,
                "target_ids": sorted(targets),
                "classification": native_classification,
                "grab_score": context.get("custom_format_score"),
                "import_score": candidate.get("customFormatScore"),
                "rejections": reasons,
            }
        )

    payload_mapping_complete = bool(candidates) and candidate_paths == set(payload_paths)
    if not payload_mapping_complete:
        native_terminal = False
    failures, contract_unverifiable, contract_assumptions = payload_contract(
        context,
        probes,
        allow_english_original_und_audio,
    )
    duplicate_eligible_targets = sorted(
        target
        for target, count in eligible_target_counts.items()
        if count > 1
    )
    eligible_mapping_complete = set(eligible_target_counts) == expected
    captured_profile = (context.get("quality_profile") or {}).get("fingerprint")
    profile_changed = bool(
        captured_profile
        and current_profile_fingerprint
        and captured_profile != current_profile_fingerprint
    )
    files_changed = captured_files_changed(context.get("current_files"), current_files)

    if not payload_mapping_complete or target_mismatch or context_identity_conflict:
        classification = "unverifiable"
    elif identity_mismatch:
        classification = "identity_mismatch"
    elif failures:
        classification = "payload_misrepresented"
    elif contract_unverifiable:
        classification = "unverifiable"
    elif profile_changed:
        classification = "profile_drift"
    elif files_changed:
        classification = "superseded_in_flight"
    elif duplicate_eligible_targets:
        classification = "identity_mismatch"
    elif has_eligible and eligible_mapping_complete:
        classification = "accepted"
    elif has_eligible or not native_terminal:
        classification = "unverifiable"
    else:
        classification = "current_better"
    actionable = classification in {
        "current_better",
        "superseded_in_flight",
        "profile_drift",
        "payload_misrepresented",
        "identity_mismatch",
    }
    return {
        "classification": classification,
        "actionable": actionable,
        "blocklist": classification in {"payload_misrepresented", "identity_mismatch"},
        "profile_changed": profile_changed,
        "current_files_changed": files_changed,
        "target_mismatch": target_mismatch,
        "canonical_title_collision": canonical_title_collision,
        "duplicate_eligible_targets": duplicate_eligible_targets,
        "contract_failures": failures,
        "contract_unverifiable": contract_unverifiable,
        "contract_assumptions": contract_assumptions,
        "payload_probes": probes,
        "per_file": per_file,
    }


def finite_share_quota(torrent: dict[str, Any]) -> bool:
    return any(
        isinstance(torrent.get(key), (int, float)) and float(torrent[key]) >= 0
        for key in ("max_ratio", "max_seeding_time", "max_inactive_seeding_time")
    )


def share_quota_met(torrent: dict[str, Any]) -> bool:
    ratio = torrent.get("ratio")
    max_ratio = torrent.get("max_ratio")
    if isinstance(ratio, (int, float)) and isinstance(max_ratio, (int, float)):
        if float(max_ratio) >= 0 and float(ratio) >= float(max_ratio):
            return True
    seeding_time = torrent.get("seeding_time")
    max_seeding_time = torrent.get("max_seeding_time")
    if isinstance(seeding_time, int) and isinstance(max_seeding_time, int):
        if max_seeding_time >= 0 and seeding_time >= max_seeding_time * 60:
            return True
    inactive_time = torrent.get("inactive_seeding_time")
    max_inactive_time = torrent.get("max_inactive_seeding_time")
    if isinstance(inactive_time, int) and isinstance(max_inactive_time, int):
        if max_inactive_time >= 0 and inactive_time >= max_inactive_time * 60:
            return True
    return False


def share_limits_equal(first: dict[str, Any], second: dict[str, Any]) -> bool:
    return all(
        first.get(key) == second.get(key)
        for key in ("ratio_limit", "seeding_time_limit", "inactive_seeding_time_limit")
    )


def restore_share_limits(
    qbit: QbitClient,
    download_id: str,
    original: dict[str, Any],
    original_action: str,
) -> None:
    qbit.set_share_limits(download_id, original, original_action)
    restored = qbit.torrent(download_id)
    if (
        not restored
        or restored.get("share_limit_action") != original_action
        or not share_limits_equal(original, restored)
    ):
        raise RuntimeError("qBittorrent share-limit rollback verification failed")


def remove_queue_download(
    client: JsonClient,
    queue_id: int,
    remove_from_client: bool,
    blocklist: bool,
) -> None:
    client.request(
        "DELETE",
        f"/queue/{queue_id}",
        {
            "removeFromClient": str(remove_from_client).lower(),
            "blocklist": str(blocklist).lower(),
            "skipRedownload": "true",
            "changeCategory": "false",
        },
    )


def replacement_search_scopes(
    app: str,
    context: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    media_id = (context.get("media") or {}).get("id")
    if not isinstance(media_id, int):
        return []
    if app == "radarr":
        return [
            (
                f"radarr:movie:{media_id}",
                {"name": "MoviesSearch", "movieIds": [media_id]},
            )
        ]
    seasons = sorted(
        {
            int(item["season"])
            for item in context.get("expected_episodes") or []
            if isinstance(item, dict) and isinstance(item.get("season"), int)
        }
    )
    return [
        (
            f"sonarr:series:{media_id}:season:{season}",
            {"name": "SeasonSearch", "seriesId": media_id, "seasonNumber": season},
        )
        for season in seasons
    ]


def defer_replacement_searches(
    app: str,
    context: dict[str, Any],
    state: HandoffState,
) -> list[dict[str, Any]]:
    deferred: list[dict[str, Any]] = []
    for key, body in replacement_search_scopes(app, context):
        if not state.search_is_allowed(key):
            deferred.append({"scope": key, "result": "cooldown"})
            continue
        state.stage_search(app, key, body)
        deferred.append({"scope": key, "result": "deferred"})
    return deferred


def native_manual_import_is_active(client: JsonClient) -> bool:
    commands = client.request("GET", "/command") or []
    return any(
        str(command.get("name") or "").casefold() == "manualimport"
        and str(command.get("status") or "").casefold() in {"queued", "started"}
        for command in commands
        if isinstance(command, dict)
    )


def dispatch_pending_searches(
    app: str,
    client: JsonClient,
    state: HandoffState,
    eligible_keys: set[str],
) -> list[dict[str, Any]]:
    pending = [
        (key, value)
        for key, value in state.pending_searches(app)
        if key in eligible_keys
    ]
    if not pending:
        return []
    if state.has_pending_imports(app) or native_manual_import_is_active(client):
        return [
            {
                "download_id": f"replacement:{key}",
                "protocol": "internal",
                "handoff_mode": "apply",
                "replacement_scope": key,
                "result": "replacement_search_deferred_import_pending",
            }
            for key, _value in pending
        ]

    results: list[dict[str, Any]] = []
    for key, value in pending:
        if not state.search_is_allowed(key):
            state.clear_pending_search(key)
            result = "replacement_search_skipped_cooldown"
            command_id = None
        else:
            body = value.get("body")
            if not isinstance(body, dict):
                state.clear_pending_search(key)
                result = "replacement_search_discarded_invalid_state"
                command_id = None
            else:
                response = client.request("POST", "/command", body=body) or {}
                command_id = response.get("id")
                if not isinstance(command_id, int):
                    result = "replacement_search_submission_unconfirmed"
                else:
                    state.finish_pending_search(key)
                    result = "replacement_search_scheduled"
        results.append(
            {
                "download_id": f"replacement:{key}",
                "protocol": "internal",
                "handoff_mode": "apply",
                "replacement_scope": key,
                "result": result,
                "command_id": command_id,
            }
        )
    return results


def apply_terminal_handoff(
    app: str,
    client: JsonClient,
    qbit: QbitClient,
    state: HandoffState,
    rows: list[dict[str, Any]],
    context: dict[str, Any],
    torrent: dict[str, Any],
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    download_id = normalize_download_id(torrent.get("hash"))
    if not evaluation["actionable"]:
        return {"result": "left_untouched", **evaluation}
    if not finite_share_quota(torrent):
        return {"result": "left_untouched_no_finite_quota", **evaluation}
    queue_ids = sorted(
        {int(row["id"]) for row in rows if isinstance(row.get("id"), int)}
    )
    if not queue_ids:
        return {"result": "left_untouched_no_queue_id", **evaluation}

    blocklist = bool(evaluation["blocklist"])
    if share_quota_met(torrent):
        remove_queue_download(client, queue_ids[0], True, blocklist)
        action = "removed_from_arr_and_qbit_quota_met"
    else:
        original = dict(torrent)
        original_action = str(torrent.get("share_limit_action") or "")
        if not original_action:
            return {"result": "left_untouched_share_action_unknown", **evaluation}
        if original_action != "RemoveWithContent":
            qbit.set_share_limits(download_id, torrent, "RemoveWithContent")
        updated = qbit.torrent(download_id)
        if (
            not updated
            or updated.get("share_limit_action") != "RemoveWithContent"
            or not share_limits_equal(original, updated)
        ):
            restore_share_limits(qbit, download_id, original, original_action)
            return {"result": "left_untouched_qbit_readback_failed", **evaluation}
        try:
            remove_queue_download(client, queue_ids[0], False, blocklist)
        except Exception:
            restore_share_limits(qbit, download_id, original, original_action)
            raise
        action = "hidden_from_arr_seeding_until_quota"

    searches = defer_replacement_searches(app, context, state) if blocklist else []
    state.mark_completed(app, download_id, evaluation["classification"])
    return {"result": action, "replacement_searches": searches, **evaluation}


def apply_usenet_terminal_handoff(
    app: str,
    client: JsonClient,
    state: HandoffState,
    rows: list[dict[str, Any]],
    context: dict[str, Any],
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    if not evaluation["actionable"]:
        return {"result": "left_untouched", **evaluation}
    queue_ids = sorted(
        {int(row["id"]) for row in rows if isinstance(row.get("id"), int)}
    )
    if not queue_ids:
        return {"result": "left_untouched_no_queue_id", **evaluation}

    blocklist = bool(evaluation["blocklist"])
    remove_queue_download(client, queue_ids[0], True, blocklist)
    searches = defer_replacement_searches(app, context, state) if blocklist else []
    download_id = normalize_download_id(rows[0].get("downloadId"))
    state.mark_completed(app, download_id, evaluation["classification"])
    return {
        "result": "removed_from_arr_and_sab",
        "replacement_searches": searches,
        **evaluation,
    }


def apply_validated_import(
    app: str,
    client: JsonClient,
    state: HandoffState,
    rows: list[dict[str, Any]],
    context: dict[str, Any],
    candidates: list[dict[str, Any]],
    evaluation: dict[str, Any],
    heartbeat: Path | None = None,
) -> dict[str, Any]:
    selected = select_candidates(app, context, candidates)
    expected = expected_episode_ids(context) if app == "sonarr" else {
        (context.get("media") or {}).get("id")
    }
    expected.discard(None)
    selected_targets = {
        target
        for candidate in selected
        for target in candidate_target_ids(app, candidate)
    }
    if not selected or selected_targets != expected:
        return {
            "result": "left_untouched_validated_import_incomplete",
            **evaluation,
        }

    native_download_id = str(rows[0].get("downloadId") or "").strip()
    command = client.request(
        "POST",
        "/command",
        body={
            "name": "ManualImport",
            "files": [
                import_file(app, candidate, native_download_id)
                for candidate in selected
            ],
            "importMode": "Auto",
        },
    ) or {}
    command_id = command.get("id")
    if not isinstance(command_id, int):
        return {
            "result": "left_untouched_import_submission_unconfirmed",
            "selected": len(selected),
            **evaluation,
        }
    state.mark_pending_import(app, native_download_id, command_id)
    return {
        "result": "command_pending",
        "command_id": command_id,
        "command_status": command.get("status") or "queued",
        "command_message": command.get("message"),
        "selected": len(selected),
        **evaluation,
    }


def terminal_rows_are_eligible(rows: list[dict[str, Any]]) -> bool:
    if not rows or any(
        str(row.get("status") or "").casefold() != "completed" for row in rows
    ):
        return False
    states = {
        str(row.get("trackedDownloadState") or "").casefold() for row in rows
    }
    if states == {"importblocked"}:
        return True
    if states != {"importpending"}:
        return False
    return all(
        any(
            marker in "\n".join(status_messages(row)).casefold()
            for marker in CURRENT_BETTER_MARKERS
        )
        for row in rows
    )


def terminal_rows_are_xem_hold(rows: list[dict[str, Any]]) -> bool:
    return bool(rows) and all(
        str(row.get("status") or "").casefold() == "completed"
        and str(row.get("trackedDownloadState") or "").casefold() == "importpending"
        and XEM_REJECTION_MARKER in "\n".join(status_messages(row)).casefold()
        for row in rows
    )


def reconcile_terminal_app(
    app: str,
    client: JsonClient,
    ledger: JsonClient,
    qbit: QbitClient | None,
    state: HandoffState,
    mode: str,
    download_ids: set[str],
    min_payload_age: int,
    ffprobe_timeout: int,
    max_downloads: int,
    usenet_mode: str = "disabled",
    xem_mode: str = "disabled",
    heartbeat: Path | None = None,
    allow_english_original_und_audio: bool = False,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in queue_records(app, client):
        download_id = normalize_download_id(row.get("downloadId"))
        if not download_id or (download_ids and download_id not in download_ids):
            continue
        grouped.setdefault(download_id, []).append(row)
    state.prune_pending_imports(app, set(grouped))
    pending_search_keys = {key for key, _value in state.pending_searches(app)}

    ordered_ids = sorted(grouped)
    if ordered_ids and not download_ids:
        cursor = state.cursor(app)
        split = bisect.bisect_right(ordered_ids, cursor) if cursor else 0
        ordered_ids = ordered_ids[split:] + ordered_ids[:split]

    results: list[dict[str, Any]] = []
    considered = 0
    last_considered = ""
    for download_id in ordered_ids:
        if heartbeat is not None:
            write_heartbeat(heartbeat)
        rows = grouped[download_id]
        if considered >= max_downloads:
            break
        if state.is_completed(app, download_id):
            continue
        xem_hold = app == "sonarr" and terminal_rows_are_xem_hold(rows)
        protocols = {
            str(row.get("protocol") or "").casefold() for row in rows
        }
        if len(protocols) != 1 or (
            not terminal_rows_are_eligible(rows)
            and not (xem_mode != "disabled" and xem_hold)
        ):
            continue
        protocol = protocols.pop()
        protocol_mode = mode if protocol == "torrent" else usenet_mode if protocol == "usenet" else "disabled"
        action_mode = xem_mode if xem_hold else protocol_mode
        if action_mode == "disabled" or (protocol == "torrent" and qbit is None):
            continue
        considered += 1
        last_considered = download_id
        base = {
            "app": app,
            "download_id": download_id,
            "protocol": protocol,
            "handoff_mode": action_mode,
        }
        pending_result = reconcile_pending_import(
            app, client, state, download_id
        )
        if pending_result is not None:
            results.append({**base, **pending_result})
            continue
        native_download_id = str(rows[0].get("downloadId") or "").strip()
        context = ledger_context(ledger, native_download_id)
        if not context or context.get("app") != app:
            results.append({**base, "result": "left_untouched", "classification": "unverifiable", "reason": "ledger_missing"})
            continue
        try:
            media_id = (context.get("media") or {}).get("id")
            params: dict[str, Any] = {
                "downloadId": native_download_id,
                "filterExistingFiles": "false",
            }
            if app == "radarr" and isinstance(media_id, int):
                params["movieId"] = media_id
            candidates = client.request("GET", "/manualimport", params) or []
            effective_context = context
            xem_correction: dict[str, Any] | None = None
            if xem_hold:
                xem_diagnostics: dict[str, Any] = {}
                corrected = title_confirmed_xem_correction(
                    client, context, candidates, xem_diagnostics
                )
                if corrected is None:
                    results.append(
                        {
                            **base,
                            "result": "left_untouched",
                            "classification": "unverifiable",
                            "reason": "xem_title_correction_unproven",
                            "xem_guard": xem_diagnostics,
                        }
                    )
                    continue
                effective_context, candidates, xem_correction = corrected
            torrent: dict[str, Any] | None = None
            if protocol == "torrent":
                assert qbit is not None
                torrent = qbit.torrent(download_id)
                if not torrent:
                    results.append(
                        {
                            **base,
                            "result": "left_untouched",
                            "classification": "unverifiable",
                            "reason": "qbit_torrent_missing",
                        }
                    )
                    continue
                probes, paths = payload_probes(
                    torrent,
                    qbit.files(download_id),
                    min_payload_age,
                    ffprobe_timeout,
                )
            else:
                probes, paths = filesystem_payload_probes(
                    rows,
                    min_payload_age,
                    ffprobe_timeout,
                )
            current_profile, current_files = current_policy_state(
                app, client, effective_context
            )
            if heartbeat is not None:
                write_heartbeat(heartbeat)
            evaluation = classify_terminal_download(
                app,
                effective_context,
                candidates,
                probes,
                paths,
                current_profile,
                current_files,
                allow_english_original_und_audio,
            )
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError, urllib.error.URLError) as exc:
            results.append(
                {**base, "result": "left_untouched", "classification": "unverifiable", "reason": str(exc)}
            )
            continue
        if action_mode != "apply":
            audit_result = (
                "would_import"
                if evaluation["classification"] == "accepted"
                else "would_handoff"
                if evaluation["actionable"]
                else "left_untouched"
            )
            results.append(
                {
                    **base,
                    "result": audit_result,
                    "xem_correction": xem_correction,
                    **evaluation,
                }
            )
            continue
        if evaluation["classification"] == "accepted":
            outcome = apply_validated_import(
                app,
                client,
                state,
                rows,
                effective_context,
                candidates,
                evaluation,
                heartbeat,
            )
        elif protocol == "torrent":
            assert qbit is not None and torrent is not None
            outcome = apply_terminal_handoff(
                app, client, qbit, state, rows, effective_context, torrent, evaluation
            )
        else:
            outcome = apply_usenet_terminal_handoff(
                app, client, state, rows, effective_context, evaluation
            )
        results.append({**base, "xem_correction": xem_correction, **outcome})
    if last_considered and not download_ids:
        state.mark_cursor(app, last_considered)
    results.extend(
        dispatch_pending_searches(app, client, state, pending_search_keys)
    )
    return results


def write_heartbeat(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(iso_utc() + "\n", encoding="utf-8")


def heartbeat_is_fresh(path: Path, max_age: int) -> bool:
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return False
    return age <= max_age


def parse_history_date(value: object) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def history_import_records(
    app: str,
    client: JsonClient,
    since: dt.datetime,
    max_history: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    page_size = min(max(max_history, 1), 1000)
    include = (
        {"includeSeries": "true", "includeEpisode": "true"}
        if app == "sonarr"
        else {"includeMovie": "true"}
    )
    for page in range(1, (max_history + page_size - 1) // page_size + 1):
        payload = client.request(
            "GET",
            "/history",
            {
                **include,
                "page": page,
                "pageSize": page_size,
                "sortKey": "date",
                "sortDirection": "descending",
            },
        ) or {}
        page_records = payload.get("records", payload if isinstance(payload, list) else [])
        if not isinstance(page_records, list):
            break
        reached_cutoff = False
        for record in page_records:
            if not isinstance(record, dict):
                continue
            observed = parse_history_date(record.get("date"))
            if observed is not None and observed < since:
                reached_cutoff = True
                continue
            if str(record.get("eventType") or "").casefold() == "downloadfolderimported":
                records.append(record)
            if len(records) >= max_history:
                return records
        total = payload.get("totalRecords") if isinstance(payload, dict) else None
        if reached_cutoff or len(page_records) < page_size:
            break
        if isinstance(total, int) and page * page_size >= total:
            break
    return records


def history_download_id(record: dict[str, Any]) -> str:
    data = record.get("data") if isinstance(record.get("data"), dict) else {}
    return str(record.get("downloadId") or data.get("downloadId") or "").strip()


def history_score(record: dict[str, Any]) -> int | None:
    value = record.get("customFormatScore")
    if value is None and isinstance(record.get("data"), dict):
        value = record["data"].get("customFormatScore")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def audit_import_history(
    app: str,
    client: JsonClient,
    ledger: JsonClient,
    since: dt.datetime,
    max_history: int,
) -> dict[str, Any]:
    imports = history_import_records(app, client, since, max_history)
    grouped: dict[str, list[dict[str, Any]]] = {}
    missing_download_id = 0
    for record in imports:
        download_id = normalize_download_id(history_download_id(record))
        if not download_id:
            missing_download_id += 1
            continue
        grouped.setdefault(download_id, []).append(record)

    results: list[dict[str, Any]] = []
    ledger_missing = 0
    for download_id, records in grouped.items():
        context = ledger_context(ledger, download_id)
        if not context or context.get("app") != app:
            ledger_missing += 1
            continue
        grab_formats = set(custom_format_names(context.get("custom_formats")))
        import_variants: dict[tuple[int | None, tuple[str, ...]], int] = {}
        for record in records:
            import_formats = tuple(sorted(custom_format_names(record.get("customFormats"))))
            variant = (history_score(record), import_formats)
            import_variants[variant] = import_variants.get(variant, 0) + 1

        variants: list[dict[str, Any]] = []
        classifications: set[str] = set()
        grab_score = context.get("custom_format_score")
        for (import_score, import_formats_tuple), count in import_variants.items():
            import_formats = set(import_formats_tuple)
            gained = sorted(import_formats - grab_formats)
            lost = sorted(grab_formats - import_formats)
            score_changed = (
                isinstance(grab_score, int)
                and isinstance(import_score, int)
                and grab_score != import_score
            )
            if score_changed:
                classification = "score_drift"
            elif gained or lost:
                classification = "format_drift"
            else:
                classification = "stable"
            classifications.add(classification)
            variants.append(
                {
                    "classification": classification,
                    "count": count,
                    "import_score": import_score,
                    "gained_formats": gained,
                    "lost_formats": lost,
                }
            )
        results.append(
            {
                "download_id": download_id,
                "source_title": context.get("source_title"),
                "captured_at": context.get("captured_at"),
                "grab_score": grab_score,
                "grab_formats": sorted(grab_formats),
                "import_count": len(records),
                "classification": (
                    "score_drift"
                    if "score_drift" in classifications
                    else "format_drift"
                    if "format_drift" in classifications
                    else "stable"
                ),
                "variants": sorted(
                    variants,
                    key=lambda item: (
                        str(item["classification"]),
                        item["import_score"] if isinstance(item["import_score"], int) else -1,
                    ),
                ),
            }
        )

    counts: dict[str, int] = {}
    for result in results:
        classification = str(result["classification"])
        counts[classification] = counts.get(classification, 0) + 1
    return {
        "app": app,
        "since": since.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "history_import_records": len(imports),
        "download_ids": len(grouped),
        "matched_download_ids": len(results),
        "ledger_missing_download_ids": ledger_missing,
        "missing_download_id_records": missing_download_id,
        "classification_counts": counts,
        "results": sorted(
            results,
            key=lambda item: (
                item["classification"] == "stable",
                str(item.get("captured_at") or ""),
                str(item.get("source_title") or "").casefold(),
            ),
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    parser.add_argument("--heartbeat", type=Path, default=DEFAULT_HEARTBEAT)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--event-log", type=Path, default=DEFAULT_EVENT_LOG)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check-health", action="store_true")
    parser.add_argument("--max-heartbeat-age", type=int, default=180)
    parser.add_argument("--audit-import-history", action="store_true")
    parser.add_argument("--audit-app", choices=["sonarr", "radarr", "all"], default="all")
    parser.add_argument("--since-hours", type=int, default=24 * 7)
    parser.add_argument("--max-history", type=int, default=5000)
    parser.add_argument(
        "--handoff-mode",
        choices=["disabled", "audit", "apply"],
        default="disabled",
        help="audit or apply terminal qBittorrent handoff; disabled by default",
    )
    parser.add_argument(
        "--usenet-handoff-mode",
        choices=["disabled", "audit", "apply"],
        default="disabled",
        help="audit or apply terminal SABnzbd handoff; disabled by default",
    )
    parser.add_argument(
        "--xem-handoff-mode",
        choices=["disabled", "audit", "apply"],
        default="disabled",
        help="audit or apply title-confirmed Sonarr TheXEM corrections",
    )
    parser.add_argument(
        "--handoff-download-id",
        action="append",
        default=[],
        help="limit terminal handoff to one exact download ID; repeatable",
    )
    parser.add_argument("--handoff-state", type=Path, default=DEFAULT_HANDOFF_STATE)
    parser.add_argument("--min-payload-age", type=int, default=DEFAULT_MIN_PAYLOAD_AGE)
    parser.add_argument("--ffprobe-timeout", type=int, default=DEFAULT_FFPROBE_TIMEOUT)
    parser.add_argument(
        "--max-handoffs-per-cycle",
        type=int,
        default=DEFAULT_MAX_HANDOFFS_PER_CYCLE,
        help=(
            "maximum completed torrent groups evaluated per application per cycle; "
            "a persistent cursor rotates across unresolved groups"
        ),
    )
    parser.add_argument(
        "--handoff-only",
        action="store_true",
        help="skip exact-ID import fallback and run only terminal handoff",
    )
    parser.add_argument(
        "--allow-english-original-und-audio",
        action="store_true",
        help=(
            "accept one unknown-tagged audio stream as original English only "
            "for regular English-original profiles without dual/multi/foreign markers"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.check_health:
        return 0 if heartbeat_is_fresh(args.heartbeat, args.max_heartbeat_age) else 1

    ledger = JsonClient(os.environ.get("ARR_GRAB_CONTEXT_API", "http://arr-grab-context:9899"))
    clients = {
        "sonarr": JsonClient(os.environ.get("SONARR_API", ""), os.environ.get("SONARR_API_KEY", "")),
        "radarr": JsonClient(os.environ.get("RADARR_API", ""), os.environ.get("RADARR_API_KEY", "")),
    }
    if args.audit_import_history:
        if args.since_hours <= 0 or args.max_history <= 0:
            raise SystemExit("--since-hours and --max-history must be positive")
        since = dt.datetime.now(dt.UTC) - dt.timedelta(hours=args.since_hours)
        apps = list(clients) if args.audit_app == "all" else [args.audit_app]
        report = {
            app: audit_import_history(app, clients[app], ledger, since, args.max_history)
            for app in apps
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    state = ReconcileState(args.state)
    handoff_state = HandoffState(args.handoff_state)
    qbit: QbitClient | None = None
    handoff_ids = {normalize_download_id(value) for value in args.handoff_download_id if value}
    if (
        args.handoff_mode != "disabled"
        or args.usenet_handoff_mode != "disabled"
        or args.xem_handoff_mode != "disabled"
    ):
        if args.min_payload_age < 1 or args.ffprobe_timeout < 1 or args.max_handoffs_per_cycle < 1:
            raise SystemExit("handoff age, timeout, and cycle limit must be positive")
    if args.handoff_mode != "disabled":
        qbit = QbitClient(
            os.environ.get("QBIT_API", ""),
            os.environ.get("QBIT_USER", ""),
            os.environ.get("QBIT_PASS", ""),
        )
        qbit.login()
        version = qbit.version()
        if version_tuple(version) < (5, 2, 0):
            raise SystemExit(f"qBittorrent 5.2.0 or newer is required; found {version or 'unknown'}")
    last_emitted: dict[str, str] = {}
    while True:
        write_heartbeat(args.heartbeat)
        for app, client in clients.items():
            try:
                terminal_enabled = (
                    qbit is not None
                    or args.usenet_handoff_mode != "disabled"
                    or args.xem_handoff_mode != "disabled"
                )
                results = (
                    []
                    if args.handoff_only or terminal_enabled
                    else reconcile_app(
                        app,
                        client,
                        ledger,
                        state,
                        args.dry_run,
                        args.heartbeat,
                    )
                )
                if qbit is not None:
                    qbit.login()
                if (
                    qbit is not None
                    or args.usenet_handoff_mode != "disabled"
                    or args.xem_handoff_mode != "disabled"
                ):
                    results.extend(
                        reconcile_terminal_app(
                            app,
                            client,
                            ledger,
                            qbit,
                            handoff_state,
                            args.handoff_mode,
                            handoff_ids,
                            args.min_payload_age,
                            args.ffprobe_timeout,
                            args.max_handoffs_per_cycle,
                            args.usenet_handoff_mode,
                            args.xem_handoff_mode,
                            args.heartbeat,
                            args.allow_english_original_und_audio,
                        )
                    )
                for result in results:
                    fingerprint = json.dumps(result, sort_keys=True, separators=(",", ":"))
                    key = f"{app}:{result.get('download_id') or result.get('result')}"
                    if last_emitted.get(key) == fingerprint:
                        continue
                    last_emitted[key] = fingerprint
                    event = {"observed_at": iso_utc(), **result}
                    append_event(args.event_log, event)
                    print(json.dumps(event, sort_keys=True), flush=True)
            except (OSError, TimeoutError, ValueError, urllib.error.URLError) as exc:
                event = {
                    "observed_at": iso_utc(),
                    "app": app,
                    "result": "error",
                    "error": str(exc),
                }
                fingerprint = json.dumps(event | {"observed_at": None}, sort_keys=True)
                if last_emitted.get(f"{app}:error") != fingerprint:
                    last_emitted[f"{app}:error"] = fingerprint
                    append_event(args.event_log, event)
                    print(json.dumps(event, sort_keys=True), file=sys.stderr, flush=True)
        write_heartbeat(args.heartbeat)
        if args.once:
            return 0
        time.sleep(max(args.interval, 5))


if __name__ == "__main__":
    raise SystemExit(main())
