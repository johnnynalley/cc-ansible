"""SQLite persistence for incremental scanning and review decisions."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .analysis import AnalysisResult
from .scoring import Detection, RankedMatch

SQLITE_WRITE_BATCH_SIZE = 100


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS assets (
                    asset_id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL DEFAULT '',
                    width INTEGER,
                    height INTEGER,
                    file_created_at TEXT,
                    updated_at TEXT NOT NULL,
                    visibility TEXT NOT NULL,
                    checksum TEXT,
                    ocr_text TEXT NOT NULL DEFAULT '',
                    ocr_json TEXT NOT NULL DEFAULT '[]',
                    detection_score REAL NOT NULL DEFAULT 0,
                    detection_reasons TEXT NOT NULL DEFAULT '[]',
                    sources TEXT NOT NULL DEFAULT '[]',
                    review_status TEXT NOT NULL DEFAULT 'pending',
                    analysis_state TEXT NOT NULL DEFAULT 'unprocessed',
                    analysis_media INTEGER,
                    analysis_provider TEXT,
                    analysis_result TEXT,
                    analysis_attempts INTEGER NOT NULL DEFAULT 0,
                    cloud_analysis_attempts INTEGER NOT NULL DEFAULT 0,
                    analysis_updated_at TEXT,
                    analysis_error TEXT,
                    scanned_at TEXT NOT NULL,
                    last_error TEXT
                );

                CREATE INDEX IF NOT EXISTS assets_review_queue
                    ON assets(review_status, detection_score DESC, file_created_at DESC);

                CREATE TABLE IF NOT EXISTS matches (
                    asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
                    media_type TEXT NOT NULL,
                    media_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    year INTEGER,
                    poster_path TEXT,
                    overview TEXT,
                    availability_status INTEGER,
                    request_status TEXT,
                    score REAL NOT NULL,
                    reasons TEXT NOT NULL,
                    source_query TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(asset_id, media_type, media_id)
                );

                CREATE INDEX IF NOT EXISTS matches_asset_score
                    ON matches(asset_id, score DESC);

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id TEXT,
                    event_type TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """)
            self._ensure_column(
                connection,
                "assets",
                "analysis_state",
                "TEXT NOT NULL DEFAULT 'unprocessed'",
            )
            self._ensure_column(connection, "assets", "analysis_media", "INTEGER")
            self._ensure_column(connection, "assets", "analysis_provider", "TEXT")
            self._ensure_column(connection, "assets", "analysis_result", "TEXT")
            self._ensure_column(
                connection,
                "assets",
                "analysis_attempts",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                connection,
                "assets",
                "cloud_analysis_attempts",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(connection, "assets", "analysis_updated_at", "TEXT")
            self._ensure_column(connection, "assets", "analysis_error", "TEXT")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS assets_analysis_queue "
                "ON assets(analysis_state, detection_score DESC, file_created_at DESC)"
            )

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        name: str,
        definition: str,
    ) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if name not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def get_meta(
        self, key: str, *, connection: sqlite3.Connection | None = None
    ) -> str | None:
        if connection is not None:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = ?", (key,)
            ).fetchone()
            return str(row["value"]) if row else None
        with self.connect() as local:
            return self.get_meta(key, connection=local)

    def set_meta(
        self,
        key: str,
        value: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        if connection is not None:
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            return
        with self.connect() as local:
            self.set_meta(key, value, connection=local)

    @staticmethod
    def _asset_id_batches(
        connection: sqlite3.Connection,
        *,
        where: str = "",
        parameters: tuple[Any, ...] = (),
    ) -> Iterator[list[str]]:
        query = "SELECT asset_id FROM assets"
        if where:
            query += f" WHERE {where}"
        rows = connection.execute(query, parameters).fetchall()
        asset_ids = [str(row["asset_id"]) for row in rows]
        for offset in range(0, len(asset_ids), SQLITE_WRITE_BATCH_SIZE):
            yield asset_ids[offset : offset + SQLITE_WRITE_BATCH_SIZE]

    def ensure_pipeline_version(self, version: int) -> bool:
        """Invalidate derived matches once when scanner logic changes."""
        expected = str(version)
        with self.connect() as connection:
            current = self.get_meta("pipeline_version", connection=connection)
            if current == expected:
                return False
            connection.execute("DELETE FROM matches")
            for asset_ids in self._asset_id_batches(connection):
                placeholders = ",".join("?" for _asset_id in asset_ids)
                connection.execute(
                    f"""
                    UPDATE assets
                    SET review_status = CASE
                            WHEN review_status = 'not_media'
                             AND NOT EXISTS (
                                SELECT 1 FROM events
                                WHERE events.asset_id = assets.asset_id
                                  AND events.event_type = 'status:not_media'
                             )
                            THEN 'pending'
                            ELSE review_status
                        END,
                        analysis_state = 'unprocessed', analysis_media = NULL,
                        analysis_provider = NULL, analysis_result = NULL,
                        analysis_attempts = 0, cloud_analysis_attempts = 0,
                        analysis_updated_at = NULL,
                        analysis_error = NULL
                    WHERE asset_id IN ({placeholders})
                    """,
                    asset_ids,
                )
            self.set_meta("pipeline_version", expected, connection=connection)
        return True

    def prepare_analysis_queue(self, threshold: float) -> None:
        """Queue cached candidates without re-fetching unchanged OCR."""

        with self.connect() as connection:
            now = utc_now()
            for asset_ids in self._asset_id_batches(
                connection,
                where="analysis_state = ?",
                parameters=("unprocessed",),
            ):
                placeholders = ",".join("?" for _asset_id in asset_ids)
                connection.execute(
                    f"""
                    UPDATE assets
                    SET analysis_state = CASE
                            WHEN detection_score >= ? THEN 'local_pending'
                            ELSE 'filtered'
                        END,
                        analysis_media = CASE
                            WHEN detection_score >= ? THEN NULL
                            ELSE 0
                        END,
                        analysis_provider = CASE
                            WHEN detection_score >= ? THEN NULL
                            ELSE 'prefilter'
                        END,
                        analysis_updated_at = ?
                    WHERE analysis_state = 'unprocessed'
                      AND asset_id IN ({placeholders})
                    """,
                    (threshold, threshold, threshold, now, *asset_ids),
                )

    def asset_needs_ocr(self, asset_id: str, updated_at: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT updated_at, last_error FROM assets WHERE asset_id = ?",
                (asset_id,),
            ).fetchone()
            return (
                row is None
                or str(row["updated_at"]) != updated_at
                or row["last_error"] is not None
            )

    def existing_sources(self, asset_id: str) -> set[str]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT sources FROM assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
        if not row:
            return set()
        try:
            return set(json.loads(row["sources"]))
        except (TypeError, json.JSONDecodeError):
            return set()

    def delete_asset(self, asset_id: str) -> None:
        """Forget cached content for an asset that is no longer reviewable."""
        with self.connect() as connection:
            connection.execute("DELETE FROM events WHERE asset_id = ?", (asset_id,))
            connection.execute("DELETE FROM assets WHERE asset_id = ?", (asset_id,))

    def upsert_asset(
        self,
        asset: dict[str, Any],
        ocr_rows: list[dict[str, Any]],
        detection: Detection,
        sources: set[str],
        *,
        ocr_text: str,
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            existing = connection.execute(
                """
                SELECT updated_at, checksum, ocr_text, detection_score
                FROM assets WHERE asset_id = ?
                """,
                (str(asset["id"]),),
            ).fetchone()
            changed = (
                existing is None
                or str(existing["updated_at"] or "")
                != str(asset.get("updatedAt") or now)
                or str(existing["checksum"] or "") != str(asset.get("checksum") or "")
                or str(existing["ocr_text"] or "") != ocr_text
                or float(existing["detection_score"] or 0) != detection.score
            )
            connection.execute(
                """
                INSERT INTO assets(
                    asset_id, filename, width, height, file_created_at, updated_at,
                    visibility, checksum, ocr_text, ocr_json, detection_score,
                    detection_reasons, sources, scanned_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_id) DO UPDATE SET
                    filename = excluded.filename,
                    width = excluded.width,
                    height = excluded.height,
                    file_created_at = excluded.file_created_at,
                    updated_at = excluded.updated_at,
                    visibility = excluded.visibility,
                    checksum = excluded.checksum,
                    ocr_text = excluded.ocr_text,
                    ocr_json = excluded.ocr_json,
                    detection_score = excluded.detection_score,
                    detection_reasons = excluded.detection_reasons,
                    sources = excluded.sources,
                    scanned_at = excluded.scanned_at,
                    last_error = NULL,
                    analysis_state = CASE WHEN ? THEN 'unprocessed'
                        ELSE assets.analysis_state END,
                    analysis_media = CASE WHEN ? THEN NULL
                        ELSE assets.analysis_media END,
                    analysis_provider = CASE WHEN ? THEN NULL
                        ELSE assets.analysis_provider END,
                    analysis_result = CASE WHEN ? THEN NULL
                        ELSE assets.analysis_result END,
                    analysis_attempts = CASE WHEN ? THEN 0
                        ELSE assets.analysis_attempts END,
                    cloud_analysis_attempts = CASE WHEN ? THEN 0
                        ELSE assets.cloud_analysis_attempts END,
                    analysis_updated_at = CASE WHEN ? THEN NULL
                        ELSE assets.analysis_updated_at END,
                    analysis_error = CASE WHEN ? THEN NULL
                        ELSE assets.analysis_error END
                """,
                (
                    asset["id"],
                    str(asset.get("originalFileName") or ""),
                    asset.get("width"),
                    asset.get("height"),
                    asset.get("fileCreatedAt"),
                    str(asset.get("updatedAt") or now),
                    str(asset.get("visibility") or "timeline").lower(),
                    asset.get("checksum"),
                    ocr_text,
                    json.dumps(ocr_rows, separators=(",", ":")),
                    detection.score,
                    json.dumps(detection.reasons),
                    json.dumps(sorted(sources)),
                    now,
                    changed,
                    changed,
                    changed,
                    changed,
                    changed,
                    changed,
                    changed,
                    changed,
                ),
            )

    def enqueue_local_analysis(self, asset_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE assets
                SET analysis_state = 'local_pending', analysis_error = NULL
                WHERE asset_id = ? AND analysis_state = 'unprocessed'
                """,
                (asset_id,),
            )

    def mark_prefilter_rejected(self, asset_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE assets
                SET analysis_state = 'filtered', analysis_media = 0,
                    analysis_provider = 'prefilter', analysis_updated_at = ?,
                    analysis_error = NULL
                WHERE asset_id = ?
                """,
                (utc_now(), asset_id),
            )

    def local_analysis_batch(self, limit: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT asset_id, ocr_text
                FROM assets
                WHERE analysis_state = 'local_pending'
                ORDER BY detection_score DESC, file_created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_analysis(
        self,
        asset_id: str,
        result: AnalysisResult,
        *,
        provider: str,
    ) -> str:
        if provider not in {"local", "gpt-5.6-sol"}:
            raise ValueError("invalid analysis provider")
        expected_state = (
            "cloud_running" if provider == "gpt-5.6-sol" else "local_pending"
        )
        state = "complete" if provider == "gpt-5.6-sol" else "cloud_pending"
        if provider == "local" and result.local_complete:
            state = "complete"
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE assets
                SET analysis_state = ?, analysis_media = ?, analysis_provider = ?,
                    analysis_result = ?, analysis_attempts = analysis_attempts + 1,
                    analysis_updated_at = ?, analysis_error = NULL
                WHERE asset_id = ? AND analysis_state = ?
                """,
                (
                    state,
                    1 if result.is_media else 0,
                    provider,
                    json.dumps(result.as_dict(), separators=(",", ":")),
                    now,
                    asset_id,
                    expected_state,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(asset_id)
            if state == "complete" and not result.is_media:
                connection.execute(
                    "UPDATE assets SET review_status = 'not_media' "
                    "WHERE asset_id = ? AND review_status = 'pending'",
                    (asset_id,),
                )
            connection.execute(
                "INSERT INTO events(asset_id, event_type, detail, created_at) "
                "VALUES(?, ?, ?, ?)",
                (
                    asset_id,
                    f"analysis:{provider}:{state}",
                    json.dumps(
                        {
                            "decision": result.decision,
                            "certainty": result.certainty,
                        }
                    ),
                    now,
                ),
            )
        return state

    def record_local_analysis_error(
        self,
        asset_id: str,
        message: str,
        *,
        maximum_attempts: int,
        escalate: bool,
        escalate_on_exhaustion: bool = False,
    ) -> str:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT analysis_attempts FROM assets WHERE asset_id = ?",
                (asset_id,),
            ).fetchone()
            if row is None:
                raise KeyError(asset_id)
            attempts = int(row["analysis_attempts"] or 0) + 1
            if escalate or (attempts >= maximum_attempts and escalate_on_exhaustion):
                state = "cloud_pending"
            elif attempts >= maximum_attempts:
                state = "error"
            else:
                state = "local_pending"
            connection.execute(
                """
                UPDATE assets
                SET analysis_state = ?, analysis_attempts = ?,
                    analysis_updated_at = ?, analysis_error = ?
                WHERE asset_id = ?
                """,
                (state, attempts, utc_now(), message[:500], asset_id),
            )
        return state

    def claim_cloud_analysis(
        self,
        *,
        stale_before: str,
        maximum_attempts: int,
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE assets
                SET analysis_state = CASE
                        WHEN cloud_analysis_attempts + 1 >= ? THEN 'error'
                        ELSE 'cloud_pending'
                    END,
                    cloud_analysis_attempts = cloud_analysis_attempts + 1,
                    analysis_error = 'stale_claim'
                WHERE analysis_state = 'cloud_running'
                  AND analysis_updated_at < ?
                """,
                (maximum_attempts, stale_before),
            )
            row = connection.execute("""
                SELECT asset_id, ocr_text
                FROM assets
                WHERE analysis_state = 'cloud_pending'
                ORDER BY detection_score DESC, file_created_at DESC
                LIMIT 1
                """).fetchone()
            if row is None:
                return None
            asset_id = str(row["asset_id"])
            cursor = connection.execute(
                """
                UPDATE assets
                SET analysis_state = 'cloud_running', analysis_updated_at = ?
                WHERE asset_id = ? AND analysis_state = 'cloud_pending'
                """,
                (utc_now(), asset_id),
            )
            if cursor.rowcount != 1:
                return None
        return dict(row)

    def cloud_candidate(self, asset_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT asset_id, visibility, analysis_state
                FROM assets
                WHERE asset_id = ? AND analysis_state = 'cloud_running'
                """,
                (asset_id,),
            ).fetchone()
        return dict(row) if row else None

    def fail_cloud_analysis(
        self,
        asset_id: str,
        error_code: str,
        *,
        maximum_attempts: int,
    ) -> str:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE assets
                SET analysis_state = CASE
                        WHEN cloud_analysis_attempts + 1 >= ? THEN 'error'
                        ELSE 'cloud_pending'
                    END,
                    cloud_analysis_attempts = cloud_analysis_attempts + 1,
                    analysis_updated_at = ?, analysis_error = ?
                WHERE asset_id = ? AND analysis_state = 'cloud_running'
                """,
                (maximum_attempts, utc_now(), error_code[:120], asset_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(asset_id)
            row = connection.execute(
                "SELECT analysis_state FROM assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
        return str(row["analysis_state"])

    def record_error(self, asset_id: str, message: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE assets SET last_error = ?, scanned_at = ? WHERE asset_id = ?",
                (message[:1000], utc_now(), asset_id),
            )

    def replace_matches(self, asset_id: str, matches: list[RankedMatch]) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute("DELETE FROM matches WHERE asset_id = ?", (asset_id,))
            for match in matches:
                media_info = match.payload.get("mediaInfo") or {}
                request_status = None
                requests = media_info.get("requests") or []
                if requests:
                    request_status = str(requests[0].get("status"))
                connection.execute(
                    """
                    INSERT INTO matches(
                        asset_id, media_type, media_id, title, year, poster_path,
                        overview, availability_status, request_status, score,
                        reasons, source_query, payload, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        asset_id,
                        match.media_type,
                        match.media_id,
                        match.title,
                        match.year,
                        match.payload.get("posterPath"),
                        match.payload.get("overview"),
                        media_info.get("status"),
                        request_status,
                        match.score,
                        json.dumps(match.reasons),
                        match.source_query,
                        json.dumps(match.payload, separators=(",", ":")),
                        now,
                    ),
                )

    def queue(
        self, *, status: str = "pending", limit: int = 100, threshold: float = 0.0
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            # Rank only lightweight IDs first. Sorting/grouping ``a.*`` makes
            # SQLite copy the large OCR text/JSON columns into a temporary
            # B-tree; the deployed container intentionally has a small tmpfs
            # and a few thousand OCR-heavy rows can exhaust it.
            id_rows = connection.execute(
                """
                SELECT asset_id
                FROM assets
                WHERE review_status = ? AND detection_score >= ?
                  AND (? != 'pending' OR
                       (analysis_state = 'complete' AND analysis_media = 1))
                ORDER BY detection_score DESC, file_created_at DESC
                LIMIT ?
                """,
                (status, threshold, status, limit),
            ).fetchall()
            asset_ids = [str(row["asset_id"]) for row in id_rows]
            if not asset_ids:
                return []
            placeholders = ",".join("?" for _ in asset_ids)
            rows = connection.execute(
                f"""
                SELECT a.*, COUNT(m.media_id) AS match_count,
                       MAX(m.score) AS best_match_score
                FROM assets a
                LEFT JOIN matches m ON m.asset_id = a.asset_id
                WHERE a.asset_id IN ({placeholders})
                GROUP BY a.asset_id
                """,
                asset_ids,
            ).fetchall()
        by_id = {str(row["asset_id"]): dict(row) for row in rows}
        return [by_id[asset_id] for asset_id in asset_ids if asset_id in by_id]

    def candidate(self, asset_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
            if not row:
                return None
            matches = connection.execute(
                "SELECT * FROM matches WHERE asset_id = ? ORDER BY score DESC",
                (asset_id,),
            ).fetchall()
        result = dict(row)
        result["matches"] = [dict(match) for match in matches]
        return result

    def set_status(
        self, asset_id: str, status: str, detail: dict[str, Any] | None = None
    ) -> None:
        allowed = {"pending", "ignored", "not_media", "requested", "available", "error"}
        if status not in allowed:
            raise ValueError(f"invalid review status: {status}")
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE assets SET review_status = ? WHERE asset_id = ?",
                (status, asset_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(asset_id)
            connection.execute(
                "INSERT INTO events(asset_id, event_type, detail, created_at) VALUES(?, ?, ?, ?)",
                (asset_id, f"status:{status}", json.dumps(detail or {}), utc_now()),
            )

    def stats(self, threshold: float) -> dict[str, Any]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT review_status, COUNT(*) AS count FROM assets "
                "WHERE detection_score >= ? GROUP BY review_status",
                (threshold,),
            ).fetchall()
            totals = connection.execute(
                """
                SELECT COUNT(*) AS scanned,
                       SUM(CASE WHEN ocr_text != '' THEN 1 ELSE 0 END) AS with_ocr,
                       SUM(CASE WHEN detection_score >= ? THEN 1 ELSE 0 END) AS candidates,
                       SUM(CASE WHEN analysis_state = 'local_pending' THEN 1 ELSE 0 END)
                           AS local_pending,
                       SUM(CASE WHEN analysis_state IN ('cloud_pending', 'cloud_running')
                                THEN 1 ELSE 0 END) AS cloud_pending,
                       SUM(CASE WHEN analysis_state = 'complete' AND analysis_media = 1
                                THEN 1 ELSE 0 END) AS analyzed_media,
                       SUM(CASE WHEN analysis_state = 'error' THEN 1 ELSE 0 END)
                           AS analysis_errors,
                       SUM(CASE WHEN last_error IS NOT NULL THEN 1 ELSE 0 END) AS errors
                FROM assets
                """,
                (threshold,),
            ).fetchone()
        result = dict(totals) if totals else {}
        result["statuses"] = {
            str(row["review_status"]): int(row["count"]) for row in rows
        }
        return result
