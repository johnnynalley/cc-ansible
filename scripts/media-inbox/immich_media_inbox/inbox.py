"""Headless review and candidate-scoped vision operations for Astra."""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .analysis import AnalysisResult, cloud_analysis_prompt, parse_analysis
from .clients import ApiError, ImmichClient, SeerrClient
from .config import Config
from .scanner import PIPELINE_VERSION, Scanner
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
CLOUD_ERROR_CODES = {
    "invalid_output",
    "provider_error",
    "submit_error",
    "transport_error",
}


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
    """Expose results plus a candidate-scoped automatic vision boundary."""

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
        pipeline_version = int(self.store.get_meta("pipeline_version") or "0")
        return {
            "schema": 2,
            "healthy": scan_state in {"idle", "running"} and bool(completed_at),
            "scan_state": scan_state,
            "scan_completed_at": completed_at,
            "full_crawl_completed_at": self.store.get_meta("full_crawl_completed_at"),
            "pipeline_version": pipeline_version,
            "expected_pipeline_version": PIPELINE_VERSION,
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
    def _analysis(candidate: dict[str, Any]) -> AnalysisResult | None:
        raw = candidate.get("analysis_result")
        if not raw:
            return None
        try:
            return parse_analysis(str(raw))
        except ValueError:
            return None

    @classmethod
    def _review_reasons(cls, candidate: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        analysis = cls._analysis(candidate)
        if analysis is None or candidate.get("analysis_state") != "complete":
            return ["analysis_incomplete"]
        if analysis.decision == "ambiguous":
            reasons.append("semantic_ambiguity")
        if analysis.certainty != "high":
            reasons.append("model_uncertain")
        matches = list(candidate.get("matches") or [])
        if not matches:
            reasons.append("title_unresolved")
            return reasons
        top_score = float(matches[0].get("score") or 0)
        if top_score < 0.78:
            reasons.append("weak_canonical_match")
        if len(matches) > 1:
            second_score = float(matches[1].get("score") or 0)
            if top_score - second_score < 0.08:
                reasons.append("multiple_close_matches")
        top_year = matches[0].get("year")
        if analysis.year and top_year and int(top_year) != analysis.year:
            reasons.append("year_conflict")
        return list(dict.fromkeys(reasons))

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
            "basis": list(json.loads(match.get("reasons") or "[]")),
            "state": state,
        }

    @classmethod
    def _sanitized_analysis(cls, candidate: dict[str, Any]) -> dict[str, Any] | None:
        analysis = cls._analysis(candidate)
        if analysis is None:
            return None
        return {
            "provider": str(candidate.get("analysis_provider") or ""),
            "decision": analysis.decision,
            "media_type": analysis.media_type,
            "title": analysis.title,
            "year": analysis.year,
            "certainty": analysis.certainty,
            "evidence": [item.as_dict() for item in analysis.evidence],
            "summary": analysis.summary,
            "uncertainty_reasons": list(analysis.uncertainty_reasons),
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
            "review_status": str(candidate.get("review_status") or "pending"),
            "manual_review_required": bool(review_reasons),
            "manual_review_reasons": review_reasons,
            "analysis": self._sanitized_analysis(candidate),
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
            "schema": 2,
            "status": status,
            "count": len(results),
            "validation_errors": validation_errors,
            "candidates": results,
        }

    def show(self, asset_id: str) -> dict[str, Any]:
        return {
            "schema": 2,
            "candidate": self._sanitized_candidate(self._validated_candidate(asset_id)),
        }

    def _validated_cloud_candidate(self, asset_id: str) -> dict[str, Any]:
        if not ASSET_ID_RE.fullmatch(asset_id):
            raise ValueError("invalid candidate ID")
        candidate = self.store.cloud_candidate(asset_id)
        if candidate is None:
            raise KeyError(asset_id)
        live_asset = self.immich.get_asset(asset_id)
        visibility = str(live_asset.get("visibility") or "").lower()
        if visibility not in self.config.allowed_visibilities:
            self.store.delete_asset(asset_id)
            raise KeyError(asset_id)
        return candidate

    def claim_cloud(self) -> dict[str, Any]:
        stale_before = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat(
            timespec="seconds"
        )
        while candidate := self.store.claim_cloud_analysis(
            stale_before=stale_before,
            maximum_attempts=self.config.cloud_analysis_max_attempts,
        ):
            asset_id = str(candidate["asset_id"])
            try:
                self._validated_cloud_candidate(asset_id)
            except KeyError:
                continue
            prompt = cloud_analysis_prompt(str(candidate.get("ocr_text") or ""))
            return {
                "schema": 1,
                "candidate": {
                    "candidate_id": asset_id,
                    "prompt_base64": base64.b64encode(prompt.encode("utf-8")).decode(
                        "ascii"
                    ),
                },
            }
        return {"schema": 1, "candidate": None}

    def export_cloud_image(self, asset_id: str) -> bytes:
        self._validated_cloud_candidate(asset_id)
        image, _content_type = self.immich.get_preview(asset_id)
        return image

    def submit_cloud_analysis(
        self, asset_id: str, payload: str | dict[str, Any]
    ) -> dict[str, Any]:
        self._validated_cloud_candidate(asset_id)
        result = parse_analysis(payload)
        if result.needs_cloud:
            raise ValueError("cloud analysis must be terminal")
        matches = self.scanner.canonical_matches(result)
        self.store.record_analysis(asset_id, result, provider="gpt-5.6-sol")
        self.store.replace_matches(asset_id, matches)
        return self.show(asset_id)

    def fail_cloud(self, asset_id: str, error_code: str) -> dict[str, Any]:
        if not ASSET_ID_RE.fullmatch(asset_id):
            raise ValueError("invalid candidate ID")
        if error_code not in CLOUD_ERROR_CODES:
            raise ValueError("invalid cloud error code")
        state = self.store.fail_cloud_analysis(
            asset_id,
            error_code,
            maximum_attempts=self.config.cloud_analysis_max_attempts,
        )
        return {
            "schema": 1,
            "candidate_id": asset_id,
            "analysis_state": state,
            "requeued": state == "cloud_pending",
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
