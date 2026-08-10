"""Runtime configuration with file-backed secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _read_secret(path: Path, *, required: bool = True) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        if required:
            raise RuntimeError(f"required secret file is missing: {path}") from None
        return ""
    if required and not value:
        raise RuntimeError(f"required secret file is empty: {path}")
    return value


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false")


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be an integer") from None
    if value < minimum or value > maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be a number") from None
    if value < minimum or value > maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class Config:
    immich_url: str
    immich_api_key: str
    immich_web_url: str
    seerr_url: str
    seerr_api_key: str
    database_path: Path
    scan_interval_seconds: int
    scan_batch_size: int
    api_request_delay_ms: int
    candidate_threshold: float
    auto_match_threshold: float
    smart_search_size: int
    smart_search_interval_hours: int
    requests_enabled: bool
    allowed_visibilities: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "Config":
        immich_key_file = Path(
            os.getenv("IMMICH_API_KEY_FILE", "/run/secrets/immich_api_key")
        )
        seerr_key_file = Path(
            os.getenv("SEERR_API_KEY_FILE", "/run/secrets/seerr_api_key")
        )
        visibilities = tuple(
            item.strip().lower()
            for item in os.getenv("ALLOWED_VISIBILITIES", "timeline,archive").split(",")
            if item.strip()
        )
        valid_visibilities = {"timeline", "archive", "hidden", "locked"}
        if not visibilities or not set(visibilities).issubset(valid_visibilities):
            raise RuntimeError(
                "ALLOWED_VISIBILITIES contains an invalid Immich visibility"
            )
        if "locked" in visibilities:
            raise RuntimeError(
                "locked assets require a deliberate code/config change; they are not accepted here"
            )

        return cls(
            immich_url=os.getenv("IMMICH_URL", "http://100.66.6.113:2283/api").rstrip(
                "/"
            ),
            immich_api_key=_read_secret(immich_key_file),
            immich_web_url=os.getenv(
                "IMMICH_WEB_URL", "https://photos.jnalley.me"
            ).rstrip("/"),
            seerr_url=os.getenv("SEERR_URL", "http://seerr:5055/api/v1").rstrip("/"),
            seerr_api_key=_read_secret(seerr_key_file),
            database_path=Path(os.getenv("DATABASE_PATH", "/data/media-inbox.sqlite3")),
            scan_interval_seconds=_env_int("SCAN_INTERVAL_SECONDS", 300, 30, 86400),
            scan_batch_size=_env_int("SCAN_BATCH_SIZE", 250, 1, 1000),
            api_request_delay_ms=_env_int("API_REQUEST_DELAY_MS", 75, 0, 5000),
            candidate_threshold=_env_float("CANDIDATE_THRESHOLD", 0.40, 0.0, 1.0),
            auto_match_threshold=_env_float("AUTO_MATCH_THRESHOLD", 0.55, 0.0, 1.0),
            smart_search_size=_env_int("SMART_SEARCH_SIZE", 100, 1, 1000),
            smart_search_interval_hours=_env_int(
                "SMART_SEARCH_INTERVAL_HOURS", 24, 1, 720
            ),
            requests_enabled=_env_bool("REQUESTS_ENABLED", False),
            allowed_visibilities=visibilities,
        )
