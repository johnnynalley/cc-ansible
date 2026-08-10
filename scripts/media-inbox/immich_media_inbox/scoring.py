"""Candidate admission and canonical metadata ordering."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable

SCREENSHOT_RE = re.compile(r"(?:screen(?:shot|recording)|screenshot_|screencap)", re.I)
SOCIAL_RE = re.compile(
    r"(?:\byoutube\b|\bshorts?\b|\btiktok\b|\breels?\b|\bsubscribe\b|"
    r"\bfollow\b|\blink in bio\b|\bcomments?\b|\bshares?\b|@[\w.]{2,}|#[\w]{2,})",
    re.I,
)
MEDIA_LABEL_RE = re.compile(
    r"\b(?:movie|film|tv\s*show|show|series|episode|season|netflix|hulu|"
    r"prime\s*video|disney\+?|hbo|max|peacock|paramount\+?)\b",
    re.I,
)
TITLE_LABEL_RE = re.compile(
    r"\b(?:movie|film|show|series)(?:\s+(?:name|title))?\s*[:\-]\s*"
    r"(?P<title>[^\n|]{2,80})",
    re.I,
)
YEAR_RE = re.compile(r"(?<!\d)(?P<year>19\d{2}|20\d{2})(?!\d)")


@dataclass(frozen=True)
class Detection:
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RankedMatch:
    media_type: str
    media_id: int
    title: str
    year: int | None
    score: float
    reasons: tuple[str, ...]
    payload: dict[str, Any]
    source_query: str


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def ordered_ocr_lines(rows: Iterable[dict[str, Any]]) -> list[str]:
    visible = [
        row
        for row in rows
        if row.get("isVisible", True) and str(row.get("text") or "").strip()
    ]
    visible.sort(
        key=lambda row: (
            min(_number(row.get(f"y{index}")) for index in range(1, 5)),
            min(_number(row.get(f"x{index}")) for index in range(1, 5)),
        )
    )
    return [re.sub(r"\s+", " ", str(row.get("text") or "")).strip() for row in visible]


def ocr_text(rows: Iterable[dict[str, Any]]) -> str:
    return "\n".join(ordered_ocr_lines(rows))


def detect_candidate(
    asset: dict[str, Any],
    ocr_rows: list[dict[str, Any]],
    sources: Iterable[str] = (),
) -> Detection:
    reasons: list[str] = []
    score = 0.0
    filename = str(asset.get("originalFileName") or "")
    width = _number(asset.get("width"))
    height = _number(asset.get("height"))
    text = ocr_text(ocr_rows)
    source_set = set(sources)

    if any(source.startswith("smart:") for source in source_set):
        score += 0.50
        reasons.append("Immich Smart Search classified the image as movie/TV-like")
    if SCREENSHOT_RE.search(filename):
        score += 0.55
        reasons.append("filename identifies a screenshot")
    if width and height:
        ratio = width / height
        if 0.42 <= ratio <= 0.75:
            score += 0.08
            reasons.append("portrait phone-screen aspect ratio")
        elif 1.70 <= ratio <= 1.82:
            score += 0.04
            reasons.append("16:9 frame aspect ratio")
    if text and SOCIAL_RE.search(text):
        score += 0.30
        reasons.append("OCR contains social-video interface text")
    if text and MEDIA_LABEL_RE.search(text):
        score += 0.35
        reasons.append("OCR explicitly mentions movie/TV context")
    if text and TITLE_LABEL_RE.search(text):
        score += 0.25
        reasons.append("OCR contains a labeled title")

    lower_third_lines = 0
    for row in ocr_rows:
        if not row.get("isVisible", True):
            continue
        line = str(row.get("text") or "").strip()
        if not 3 <= len(line) <= 90:
            continue
        average_y = sum(_number(row.get(f"y{index}")) for index in range(1, 5)) / 4
        # Immich has stored OCR boxes as both normalized and pixel coordinates
        # across schema/model revisions. Normalize either representation.
        relative_y = average_y / height if height and average_y > 1 else average_y
        if relative_y >= 0.58 and _number(row.get("textScore")) >= 0.70:
            lower_third_lines += 1
    if 1 <= lower_third_lines <= 4:
        score += 0.12
        reasons.append("OCR resembles lower-third dialogue or a short caption")

    return Detection(round(min(score, 1.0), 3), tuple(reasons))


def normalize_title(value: str) -> str:
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def _result_title(result: dict[str, Any]) -> str:
    return str(result.get("title") or result.get("name") or "").strip()


def _result_year(result: dict[str, Any]) -> int | None:
    date = str(result.get("releaseDate") or result.get("firstAirDate") or "")
    match = YEAR_RE.search(date)
    return int(match.group("year")) if match else None


def rank_seerr_results(
    query: str,
    results: Iterable[dict[str, Any]],
    *,
    hinted_year: int | None = None,
) -> list[RankedMatch]:
    normalized_query = normalize_title(query)
    ranked: list[RankedMatch] = []
    for result in results:
        media_type = str(result.get("mediaType") or "")
        media_id = result.get("id")
        title = _result_title(result)
        if (
            media_type not in {"movie", "tv"}
            or not isinstance(media_id, int)
            or not title
        ):
            continue
        normalized_title = normalize_title(title)
        similarity = SequenceMatcher(None, normalized_query, normalized_title).ratio()
        reasons: list[str] = ["fuzzy_title"]
        score = similarity * 0.78
        if normalized_query == normalized_title:
            score = 0.94
            reasons = ["exact_title"]
        elif (
            normalized_title in normalized_query or normalized_query in normalized_title
        ):
            score = max(score, 0.78)
            reasons = ["contained_title"]
        year = _result_year(result)
        if hinted_year and year == hinted_year:
            score += 0.05
            reasons.append("year_match")
        elif hinted_year and year and year != hinted_year:
            score -= 0.18
            reasons.append("year_conflict")
        if score < 0.48:
            continue
        ranked.append(
            RankedMatch(
                media_type=media_type,
                media_id=media_id,
                title=title,
                year=year,
                score=round(max(0.0, min(score, 0.99)), 3),
                reasons=tuple(reasons),
                payload=result,
                source_query=query,
            )
        )
    return sorted(ranked, key=lambda item: item.score, reverse=True)


def rank_analysis_results(
    query: str,
    results: Iterable[dict[str, Any]],
    *,
    hinted_year: int | None,
    hinted_media_type: str,
) -> list[RankedMatch]:
    """Rank canonical metadata for a title selected by semantic analysis.

    The numeric value is only an internal ordering key. User-facing output
    exposes the categorical reasons instead of presenting it as a probability.
    """

    normalized_query = normalize_title(query)
    ranked: list[RankedMatch] = []
    for result in results:
        media_type = str(result.get("mediaType") or "")
        media_id = result.get("id")
        title = _result_title(result)
        if (
            media_type not in {"movie", "tv"}
            or not isinstance(media_id, int)
            or not title
        ):
            continue
        if hinted_media_type in {"movie", "tv"} and media_type != hinted_media_type:
            continue

        normalized_title = normalize_title(title)
        similarity = SequenceMatcher(None, normalized_query, normalized_title).ratio()
        reasons: list[str] = []
        if normalized_query == normalized_title:
            score = 0.80
            reasons.append("exact_title")
        elif (
            normalized_title in normalized_query or normalized_query in normalized_title
        ):
            score = 0.58
            reasons.append("contained_title")
        else:
            score = similarity * 0.55
            reasons.append("fuzzy_title")

        year = _result_year(result)
        if hinted_year and year == hinted_year:
            score += 0.15
            reasons.append("year_match")
        elif hinted_year and year and year != hinted_year:
            score -= 0.35
            reasons.append("year_conflict")
        if hinted_media_type in {"movie", "tv"}:
            score += 0.05
            reasons.append("media_type_match")
        if score < 0.42:
            continue
        ranked.append(
            RankedMatch(
                media_type=media_type,
                media_id=media_id,
                title=title,
                year=year,
                score=round(max(0.0, min(score, 1.0)), 3),
                reasons=tuple(reasons),
                payload=result,
                source_query=query,
            )
        )
    return sorted(ranked, key=lambda item: item.score, reverse=True)
