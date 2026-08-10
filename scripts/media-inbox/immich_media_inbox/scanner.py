"""Incremental Immich crawl, OCR scoring, and conservative Seerr matching."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from .analysis import AnalysisResult
from .clients import (
    AnalysisInputError,
    AnalysisResponseError,
    ApiError,
    ImmichClient,
    OllamaClient,
    SeerrClient,
)
from .config import Config
from .scoring import (
    RankedMatch,
    detect_candidate,
    ocr_text,
    rank_analysis_results,
    rank_seerr_results,
)
from .store import Store, utc_now

LOGGER = logging.getLogger(__name__)

SMART_SEARCH_PROMPTS = (
    "a phone screenshot of a movie or television show",
    "a YouTube Short recommending a movie or TV series",
    "a social media video showing a scene from a film",
    "a movie or TV title shown on screen",
    "a cinematic scene with subtitles",
    "a vertical video clip from a movie or television show",
)
PIPELINE_VERSION = 6


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class Scanner:
    def __init__(
        self,
        config: Config,
        store: Store,
        immich: ImmichClient,
        seerr: SeerrClient,
        ollama: OllamaClient | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.immich = immich
        self.seerr = seerr
        self.ollama = ollama
        self._scan_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop, name="media-inbox-scanner", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=10)

    def trigger(self) -> bool:
        if self._scan_lock.locked():
            return False
        self._wake.set()
        return True

    @property
    def running(self) -> bool:
        return self._scan_lock.locked()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_cycle()
            except Exception:
                LOGGER.exception("scan cycle failed")
            self._wake.wait(self.config.scan_interval_seconds)
            self._wake.clear()

    def run_cycle(self) -> dict[str, Any]:
        if not self._scan_lock.acquire(blocking=False):
            return {"started": False, "reason": "scan already running"}
        started = utc_now()
        self.store.set_meta("scan_started_at", started)
        self.store.set_meta("scan_state", "running")
        report: dict[str, Any] = {"started": True, "started_at": started}
        try:
            report["pipeline_reset"] = self.store.ensure_pipeline_version(
                PIPELINE_VERSION
            )
            if report["pipeline_reset"]:
                self.store.prepare_analysis_queue(self.config.candidate_threshold)
            features = self.immich.server_features()
            if not features.get("ocr") or not features.get("search"):
                raise RuntimeError("Immich OCR and search must both be enabled")
            if not features.get("smartSearch"):
                raise RuntimeError("Immich Smart Search must be enabled")
            report["smart_seed"] = self._seed_one_smart_prompt()
            report["recent"] = self._recent_batch()
            report["crawl"] = self._crawl_batch()
            report["analysis"] = self._analyze_batch()
            self.store.set_meta("scan_state", "idle")
            self.store.set_meta("scan_completed_at", utc_now())
            self.store.set_meta("scan_last_error", "")
            self.store.set_meta("scan_last_report", json.dumps(report, sort_keys=True))
            return report
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            self.store.set_meta("scan_state", "error")
            self.store.set_meta("scan_last_error", message[:1000])
            raise
        finally:
            self._scan_lock.release()

    def _smart_seed_due(self) -> bool:
        index = int(self.store.get_meta("smart_prompt_index") or "0")
        if index:
            return True
        last_completed = _parse_time(self.store.get_meta("smart_seed_completed_at"))
        if last_completed is None:
            return True
        return datetime.now(timezone.utc) - last_completed >= timedelta(
            hours=self.config.smart_search_interval_hours
        )

    def _seed_one_smart_prompt(self) -> dict[str, Any]:
        if not self._smart_seed_due():
            return {"due": False}
        index = int(self.store.get_meta("smart_prompt_index") or "0")
        if index >= len(SMART_SEARCH_PROMPTS):
            index = 0
        prompt = SMART_SEARCH_PROMPTS[index]
        processed = 0
        errors = 0
        for visibility in self.config.allowed_visibilities:
            try:
                assets = self.immich.smart_search(
                    prompt,
                    visibility=visibility,
                    size=self.config.smart_search_size,
                )
            except ApiError as exc:
                LOGGER.warning("Immich smart-search prompt %d failed: %s", index, exc)
                errors += 1
                continue
            for asset in assets:
                try:
                    self._process_asset(asset, source=f"smart:{index}", force=True)
                    processed += 1
                except Exception as exc:
                    LOGGER.warning(
                        "smart-search asset %s failed: %s",
                        asset.get("id", "unknown"),
                        exc,
                    )
                    self.store.record_error(str(asset.get("id") or ""), str(exc))
                    errors += 1
        next_index = index + 1
        if next_index >= len(SMART_SEARCH_PROMPTS):
            self.store.set_meta("smart_prompt_index", "0")
            self.store.set_meta("smart_seed_completed_at", utc_now())
        else:
            self.store.set_meta("smart_prompt_index", str(next_index))
        return {
            "due": True,
            "prompt_index": index,
            "processed": processed,
            "errors": errors,
        }

    def _recent_batch(self) -> dict[str, Any]:
        """Process the newest images first while the historical crawl catches up."""
        processed = 0
        unchanged = 0
        errors = 0
        per_visibility = max(
            1,
            min(
                100,
                self.config.scan_batch_size // len(self.config.allowed_visibilities),
            ),
        )
        for visibility in self.config.allowed_visibilities:
            response = self.immich.search_assets(
                visibility=visibility,
                page=1,
                size=per_visibility,
                order="desc",
            )
            assets_page = (response or {}).get("assets") or {}
            for asset in list(assets_page.get("items") or []):
                asset_id = str(asset.get("id") or "")
                updated_at = str(asset.get("updatedAt") or "")
                if not asset_id or not updated_at:
                    errors += 1
                    continue
                if not self.store.asset_needs_ocr(asset_id, updated_at):
                    unchanged += 1
                    continue
                try:
                    self._process_asset(asset, source="recent-metadata")
                    processed += 1
                except Exception as exc:
                    LOGGER.warning("recent asset %s failed: %s", asset_id, exc)
                    self.store.record_error(asset_id, str(exc))
                    errors += 1
        return {
            "processed": processed,
            "unchanged": unchanged,
            "errors": errors,
        }

    def _crawl_batch(self) -> dict[str, Any]:
        visibility_index = int(self.store.get_meta("crawl_visibility_index") or "0")
        if visibility_index >= len(self.config.allowed_visibilities):
            visibility_index = 0
        visibility = self.config.allowed_visibilities[visibility_index]
        page_key = f"crawl_page:{visibility}"
        page = int(self.store.get_meta(page_key) or "1")
        page_size = min(250, self.config.scan_batch_size)
        processed = 0
        unchanged = 0
        errors = 0
        pages = 0

        while processed + unchanged < self.config.scan_batch_size:
            response = self.immich.search_assets(
                visibility=visibility,
                page=page,
                size=page_size,
            )
            assets_page = (response or {}).get("assets") or {}
            items = list(assets_page.get("items") or [])
            pages += 1
            if not items:
                self._finish_visibility(visibility_index, visibility, page_key)
                break
            for asset in items:
                if processed + unchanged >= self.config.scan_batch_size:
                    break
                asset_id = str(asset.get("id") or "")
                updated_at = str(asset.get("updatedAt") or "")
                if not asset_id or not updated_at:
                    errors += 1
                    continue
                if not self.store.asset_needs_ocr(asset_id, updated_at):
                    unchanged += 1
                    continue
                try:
                    self._process_asset(asset, source="metadata-crawl")
                    processed += 1
                except Exception as exc:
                    LOGGER.warning("metadata asset %s failed: %s", asset_id, exc)
                    self.store.record_error(asset_id, str(exc))
                    errors += 1

            next_page = assets_page.get("nextPage")
            if next_page is not None:
                try:
                    page = int(next_page)
                except (TypeError, ValueError):
                    page += 1
            elif len(items) >= page_size:
                page += 1
            else:
                self._finish_visibility(visibility_index, visibility, page_key)
                break
            self.store.set_meta(page_key, str(page))
            if processed + unchanged >= self.config.scan_batch_size:
                break

        return {
            "visibility": visibility,
            "page": page,
            "pages": pages,
            "processed": processed,
            "unchanged": unchanged,
            "errors": errors,
        }

    def _finish_visibility(self, index: int, visibility: str, page_key: str) -> None:
        self.store.set_meta(page_key, "1")
        next_index = index + 1
        if next_index >= len(self.config.allowed_visibilities):
            next_index = 0
            self.store.set_meta("full_crawl_completed_at", utc_now())
        self.store.set_meta("crawl_visibility_index", str(next_index))
        LOGGER.info("completed Immich %s image crawl", visibility)

    def _process_asset(
        self, asset: dict[str, Any], *, source: str, force: bool = False
    ) -> None:
        asset_id = str(asset.get("id") or "")
        if not asset_id:
            raise ValueError("asset has no ID")
        visibility = str(asset.get("visibility") or "").lower()
        if visibility not in self.config.allowed_visibilities:
            # Search filters should already enforce this. Keeping the check at
            # the content boundary prevents a stale or unexpected API result
            # from retaining OCR for a Locked Folder asset.
            self.store.delete_asset(asset_id)
            return
        sources = self.store.existing_sources(asset_id)
        sources.add(source)
        updated_at = str(asset.get("updatedAt") or "")
        if (
            not force
            and updated_at
            and not self.store.asset_needs_ocr(asset_id, updated_at)
        ):
            return
        rows = self.immich.get_ocr(asset_id)
        text = ocr_text(rows)
        detection = detect_candidate(asset, rows, sources)
        self.store.upsert_asset(asset, rows, detection, sources, ocr_text=text)
        if detection.score >= self.config.candidate_threshold:
            self.store.enqueue_local_analysis(asset_id)
        else:
            self.store.mark_prefilter_rejected(asset_id)

    def _analyze_batch(self) -> dict[str, Any]:
        if self.ollama is None:
            return {"configured": False, "processed": 0, "errors": 0}
        processed = 0
        escalated = 0
        errors = 0
        for candidate in self.store.local_analysis_batch(
            self.config.analysis_batch_size
        ):
            asset_id = str(candidate["asset_id"])
            try:
                live_asset = self.immich.get_asset(asset_id)
                visibility = str(live_asset.get("visibility") or "").lower()
                if visibility not in self.config.allowed_visibilities:
                    self.store.delete_asset(asset_id)
                    continue
                image_bytes, _content_type = self.immich.get_preview(asset_id)
            except ApiError as exc:
                self.store.record_local_analysis_error(
                    asset_id,
                    str(exc),
                    maximum_attempts=self.config.local_analysis_max_attempts,
                    escalate=False,
                )
                LOGGER.warning(
                    "candidate source retrieval failed for asset %s: %s",
                    asset_id,
                    exc,
                )
                errors += 1
                continue

            try:
                result = self.ollama.analyze(
                    image_bytes,
                    str(candidate.get("ocr_text") or ""),
                )
            except (AnalysisInputError, AnalysisResponseError) as exc:
                self.store.record_local_analysis_error(
                    asset_id,
                    str(exc),
                    maximum_attempts=self.config.local_analysis_max_attempts,
                    escalate=True,
                )
                self.store.replace_matches(asset_id, [])
                escalated += 1
                continue
            except ApiError as exc:
                state = self.store.record_local_analysis_error(
                    asset_id,
                    str(exc),
                    maximum_attempts=self.config.local_analysis_max_attempts,
                    escalate=False,
                    escalate_on_exhaustion=True,
                )
                LOGGER.warning(
                    "local model analysis failed for asset %s: %s", asset_id, exc
                )
                if state == "cloud_pending":
                    self.store.replace_matches(asset_id, [])
                    escalated += 1
                else:
                    errors += 1
                continue

            matches: list[RankedMatch] = []
            if result.local_complete and result.is_media:
                try:
                    matches = self.canonical_matches(result)
                except ApiError as exc:
                    self.store.record_local_analysis_error(
                        asset_id,
                        str(exc),
                        maximum_attempts=self.config.local_analysis_max_attempts,
                        escalate=False,
                    )
                    LOGGER.warning(
                        "Seerr canonicalization failed for asset %s: %s",
                        asset_id,
                        exc,
                    )
                    errors += 1
                    continue
            state = self.store.record_analysis(asset_id, result, provider="local")
            self.store.replace_matches(asset_id, matches)
            if state == "cloud_pending":
                escalated += 1
            processed += 1
        return {
            "configured": True,
            "processed": processed,
            "escalated": escalated,
            "errors": errors,
        }

    def canonicalize_analysis(
        self, asset_id: str, analysis: AnalysisResult
    ) -> list[RankedMatch]:
        ranked = self.canonical_matches(analysis)
        self.store.replace_matches(asset_id, ranked)
        return ranked

    def canonical_matches(self, analysis: AnalysisResult) -> list[RankedMatch]:
        if not analysis.is_media or not analysis.title:
            return []
        deduplicated: dict[tuple[str, int], RankedMatch] = {}
        queries = (analysis.title, *analysis.alternate_titles)
        for query in queries[:4]:
            results = self.seerr.search(query)
            for match in rank_analysis_results(
                query,
                results,
                hinted_year=analysis.year,
                hinted_media_type=analysis.media_type,
            ):
                key = (match.media_type, match.media_id)
                previous = deduplicated.get(key)
                if previous is None or match.score > previous.score:
                    deduplicated[key] = match
        ranked = sorted(
            deduplicated.values(), key=lambda item: item.score, reverse=True
        )[:8]
        return ranked

    def manual_match(self, asset_id: str, query: str) -> list[RankedMatch]:
        query = query.strip()
        if not query:
            raise ValueError("search query is required")
        results = self.seerr.search(query)
        ranked = rank_seerr_results(query, results)
        if not ranked:
            # Manual operator searches should still show Seerr results even when
            # fuzzy scoring is weak. Rank them conservatively for review.
            fallback: list[RankedMatch] = []
            for result in results[:12]:
                media_type = str(result.get("mediaType") or "")
                media_id = result.get("id")
                title = str(result.get("title") or result.get("name") or "").strip()
                if (
                    media_type not in {"movie", "tv"}
                    or not isinstance(media_id, int)
                    or not title
                ):
                    continue
                date = str(
                    result.get("releaseDate") or result.get("firstAirDate") or ""
                )
                year = int(date[:4]) if len(date) >= 4 and date[:4].isdigit() else None
                fallback.append(
                    RankedMatch(
                        media_type=media_type,
                        media_id=media_id,
                        title=title,
                        year=year,
                        score=0.40,
                        reasons=("manual Seerr search result",),
                        payload=result,
                        source_query=query,
                    )
                )
            ranked = fallback
        self.store.replace_matches(asset_id, ranked[:12])
        return ranked[:12]
