"""Result-only operations for Astra's headless review workflow."""

from __future__ import annotations

import json
import re
from typing import Any

from .clients import ApiError, ImmichClient, SeerrClient
from .config import Config
from .scanner import Scanner
from .scoring import extract_year
from .store import Store

ASSET_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-" r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
VISIBLE_STATUSES = {
    "pending",
    "ignored",
    "not_media",
    "requested",
    "available",
    "error",
}
MUTABLE_STATUSES = {"pending", "ignored", "not_media"}


def _clean_title(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:160]


def _availability(media_info: dict[str, Any]) -> tuple[str, bool]:
    status = media_info.get("status")
    if status == 5:
        return "available", True
    requests = list(media_info.get("requests") or [])
    active = [request for request in requests if request.get("status") in {1, 2}]
    if active:
        return (
            "request_pending" if active[0].get("status") == 1 else "request_approved",
            True,
        )
    states = {
        2: "pending",
        3: "processing",
        4: "partially_available",
        6: "deleted",
    }
    return states.get(status, "not_requested"), status in {2, 3, 4}


class Inbox:
    """Expose interpreted media results without image or raw-OCR access."""

    def __init__(
        self,
        config: Config,
        store: Store,
        scanner: Scanner,
        immich: ImmichClient,
        seerr: SeerrClient,
    ) -> None:
        self.config = config
        self.store = store
        self.scanner = scanner
        self.immich = immich
        self.seerr = seerr

    def status(self) -> dict[str, Any]:
        scan_state = self.store.get_meta("scan_state") or "starting"
        completed_at = self.store.get_meta("scan_completed_at")
        return {
            "schema": 1,
            "healthy": scan_state != "error" and bool(completed_at),
            "scan_state": scan_state,
            "scan_completed_at": completed_at,
            "full_crawl_completed_at": self.store.get_meta("full_crawl_completed_at"),
            "requests_enabled": self.config.requests_enabled,
            "allowed_visibilities": list(self.config.allowed_visibilities),
            "counts": self.store.stats(self.config.candidate_threshold),
        }

    def _validated_candidate(self, asset_id: str) -> dict[str, Any]:
        if not ASSET_ID_RE.fullmatch(asset_id):
            raise ValueError("invalid candidate ID")
        candidate = self.store.candidate(asset_id)
        if candidate is None:
            raise KeyError(asset_id)
        live_asset = self.immich.get_asset(asset_id)
        visibility = str(live_asset.get("visibility") or "").lower()
        if visibility not in self.config.allowed_visibilities:
            self.store.delete_asset(asset_id)
            raise KeyError(asset_id)
        candidate["visibility"] = visibility
        return candidate

    @staticmethod
    def _review_reasons(candidate: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        detected_year = extract_year(str(candidate.get("ocr_text") or ""))
        matches = list(candidate.get("matches") or [])
        if detected_year is None:
            reasons.append("year_missing")
        if not matches:
            reasons.append("title_unresolved")
            return reasons
        top_score = float(matches[0].get("score") or 0)
        if top_score < 0.78:
            reasons.append("low_match_confidence")
        if len(matches) > 1:
            second_score = float(matches[1].get("score") or 0)
            if top_score - second_score < 0.08:
                reasons.append("multiple_close_matches")
        top_year = matches[0].get("year")
        if detected_year and top_year and int(top_year) != detected_year:
            reasons.append("year_conflict")
        return reasons

    @staticmethod
    def _sanitized_match(match: dict[str, Any]) -> dict[str, Any]:
        media_info: dict[str, Any] = {}
        try:
            payload = json.loads(match.get("payload") or "{}")
            media_info = dict(payload.get("mediaInfo") or {})
        except (TypeError, json.JSONDecodeError):
            pass
        state, _blocked = _availability(media_info)
        return {
            "media_type": str(match.get("media_type") or ""),
            "media_id": int(match.get("media_id") or 0),
            "title": _clean_title(match.get("title")),
            "year": int(match["year"]) if match.get("year") else None,
            "confidence": round(float(match.get("score") or 0), 3),
            "state": state,
        }

    def _sanitized_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        matches = [
            self._sanitized_match(match)
            for match in list(candidate.get("matches") or [])[:8]
        ]
        review_reasons = self._review_reasons(candidate)
        asset_id = str(candidate["asset_id"])
        return {
            "candidate_id": asset_id,
            "captured_at": candidate.get("file_created_at"),
            "candidate_confidence": round(
                float(candidate.get("detection_score") or 0), 3
            ),
            "review_status": str(candidate.get("review_status") or "pending"),
            "manual_review_required": bool(review_reasons),
            "manual_review_reasons": review_reasons,
            "detected_year": extract_year(str(candidate.get("ocr_text") or "")),
            "matches": matches,
            "immich_review_url": f"{self.config.immich_web_url}/photos/{asset_id}",
        }

    def list_candidates(self, *, status: str, limit: int) -> dict[str, Any]:
        if status not in VISIBLE_STATUSES:
            raise ValueError("invalid review status")
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        rows = self.store.queue(
            status=status,
            limit=limit,
            threshold=(self.config.candidate_threshold if status == "pending" else 0.0),
        )
        results: list[dict[str, Any]] = []
        validation_errors = 0
        for row in rows:
            try:
                candidate = self._validated_candidate(str(row["asset_id"]))
            except KeyError:
                continue
            except ApiError:
                validation_errors += 1
                continue
            results.append(self._sanitized_candidate(candidate))
        return {
            "schema": 1,
            "status": status,
            "count": len(results),
            "validation_errors": validation_errors,
            "candidates": results,
        }

    def show(self, asset_id: str) -> dict[str, Any]:
        return {
            "schema": 1,
            "candidate": self._sanitized_candidate(self._validated_candidate(asset_id)),
        }

    def search(self, asset_id: str, query: str) -> dict[str, Any]:
        self._validated_candidate(asset_id)
        self.scanner.manual_match(asset_id, query)
        return self.show(asset_id)

    def set_status(self, asset_id: str, status: str) -> dict[str, Any]:
        if status not in MUTABLE_STATUSES:
            raise ValueError("status must be pending, ignored, or not_media")
        self._validated_candidate(asset_id)
        self.store.set_status(asset_id, status, {"actor": "astra-cli"})
        return self.show(asset_id)

    def request(
        self,
        asset_id: str,
        media_type: str,
        media_id: int,
        *,
        seasons: list[int],
        confirmed: bool,
        confirm_ambiguous: bool,
    ) -> dict[str, Any]:
        if not self.config.requests_enabled:
            raise ValueError("Seerr requests are disabled during calibration")
        if not confirmed:
            raise ValueError("explicit request confirmation is required")
        if media_type not in {"movie", "tv"} or media_id <= 0:
            raise ValueError("invalid media selection")
        candidate = self._validated_candidate(asset_id)
        review_reasons = self._review_reasons(candidate)
        if review_reasons and not confirm_ambiguous:
            raise ValueError(
                "manual review is required before this candidate can be requested: "
                + ",".join(review_reasons)
            )
        stored = [
            match
            for match in candidate.get("matches") or []
            if str(match.get("media_type")) == media_type
            and int(match.get("media_id") or 0) == media_id
        ]
        if not stored:
            raise ValueError("media selection is not a current candidate match")
        details = self.seerr.details(media_type, media_id)
        state, blocked = _availability(dict(details.get("mediaInfo") or {}))
        if blocked:
            status = "available" if state == "available" else "requested"
            self.store.set_status(asset_id, status, {"existing_state": state})
            return {
                "schema": 1,
                "request": {"created": False, "state": state},
                "candidate": self._sanitized_candidate(
                    self._validated_candidate(asset_id)
                ),
            }
        selected_seasons: list[int] | None = None
        if media_type == "tv":
            selected_seasons = sorted({int(season) for season in seasons if season > 0})
            if not selected_seasons:
                raise ValueError("at least one non-special TV season is required")
            available = {
                int(season.get("seasonNumber") or 0)
                for season in details.get("seasons") or []
                if int(season.get("seasonNumber") or 0) > 0
            }
            if available and not set(selected_seasons).issubset(available):
                raise ValueError("one or more selected TV seasons do not exist")
        response = self.seerr.request_media(
            media_type, media_id, seasons=selected_seasons
        )
        self.store.set_status(
            asset_id,
            "requested",
            {
                "actor": "astra-cli",
                "media_type": media_type,
                "media_id": media_id,
                "request_id": (response or {}).get("id"),
                "seasons": selected_seasons,
            },
        )
        return {
            "schema": 1,
            "request": {
                "created": True,
                "request_id": (response or {}).get("id"),
                "media_type": media_type,
                "media_id": media_id,
                "seasons": selected_seasons,
            },
            "candidate": self._sanitized_candidate(self._validated_candidate(asset_id)),
        }
