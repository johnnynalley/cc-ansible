"""Minimal clients for supported Immich and Seerr APIs."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class ApiError(RuntimeError):
    """An upstream API request failed without exposing credentials."""


class JsonClient:
    def __init__(
        self,
        base_url: str,
        headers: dict[str, str],
        *,
        request_delay_ms: int = 0,
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = dict(headers)
        self.request_delay_seconds = request_delay_ms / 1000
        self.timeout = timeout
        self._last_request = 0.0
        self._request_lock = threading.Lock()

    def _pace(self) -> None:
        if not self.request_delay_seconds:
            return
        elapsed = time.monotonic() - self._last_request
        remaining = self.request_delay_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def request(
        self,
        method: str,
        path: str,
        body: Any | None = None,
    ) -> Any:
        data = None
        headers = dict(self.headers)
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        # Scanner and CLI requests share each upstream client. Serializing the
        # paced request preserves the configured upstream rate limit.
        with self._request_lock:
            self._pace()
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = response.read()
                    if not payload or response.status == 204:
                        return None
                    return json.loads(payload.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                safe_path = path.split("?", 1)[0]
                raise ApiError(
                    f"{method} {safe_path} failed with HTTP {exc.code}"
                ) from exc
            except urllib.error.URLError as exc:
                safe_path = path.split("?", 1)[0]
                raise ApiError(f"{method} {safe_path} failed: {exc.reason}") from exc
            except (TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                safe_path = path.split("?", 1)[0]
                raise ApiError(
                    f"{method} {safe_path} returned an unusable response: {exc}"
                ) from exc
            finally:
                self._last_request = time.monotonic()


class ImmichClient:
    def __init__(
        self, base_url: str, api_key: str, *, request_delay_ms: int = 0
    ) -> None:
        self.http = JsonClient(
            base_url,
            {"x-api-key": api_key, "Accept": "application/json"},
            request_delay_ms=request_delay_ms,
        )

    def server_features(self) -> dict[str, Any]:
        return self.http.request("GET", "/server/features")

    def server_version(self) -> dict[str, Any]:
        return self.http.request("GET", "/server/version")

    def search_assets(
        self,
        *,
        visibility: str,
        page: int,
        size: int,
        order: str = "asc",
        updated_after: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": "IMAGE",
            "visibility": visibility,
            "page": page,
            "size": size,
            "order": order,
            "withExif": False,
            "withPeople": False,
            # False returns every asset instead of collapsing stacks to their
            # primary image, which matters for a complete screenshot audit.
            "withStacked": False,
            "withDeleted": False,
        }
        if updated_after:
            body["updatedAfter"] = updated_after
        return self.http.request("POST", "/search/metadata", body)

    def smart_search(
        self,
        query: str,
        *,
        visibility: str,
        size: int,
    ) -> list[dict[str, Any]]:
        body = {
            "query": query,
            "type": "IMAGE",
            "visibility": visibility,
            "page": 1,
            "size": size,
            "withExif": False,
        }
        response = self.http.request("POST", "/search/smart", body)
        return list(((response or {}).get("assets") or {}).get("items") or [])

    def get_ocr(self, asset_id: str) -> list[dict[str, Any]]:
        response = self.http.request(
            "GET", f"/assets/{urllib.parse.quote(asset_id)}/ocr"
        )
        return list(response or [])

    def get_asset(self, asset_id: str) -> dict[str, Any]:
        response = self.http.request("GET", f"/assets/{urllib.parse.quote(asset_id)}")
        return dict(response or {})


class SeerrClient:
    def __init__(
        self, base_url: str, api_key: str, *, request_delay_ms: int = 0
    ) -> None:
        self.http = JsonClient(
            base_url,
            {"X-Api-Key": api_key, "Accept": "application/json"},
            request_delay_ms=request_delay_ms,
        )

    def search(self, query: str, *, page: int = 1) -> list[dict[str, Any]]:
        params = urllib.parse.urlencode(
            {"query": query, "page": page, "language": "en"}
        )
        response = self.http.request("GET", f"/search?{params}")
        return list((response or {}).get("results") or [])

    def details(self, media_type: str, media_id: int) -> dict[str, Any]:
        if media_type not in {"movie", "tv"}:
            raise ValueError("media_type must be movie or tv")
        return self.http.request("GET", f"/{media_type}/{int(media_id)}")

    def request_media(
        self,
        media_type: str,
        media_id: int,
        *,
        seasons: list[int] | None = None,
    ) -> dict[str, Any]:
        if media_type not in {"movie", "tv"}:
            raise ValueError("media_type must be movie or tv")
        body: dict[str, Any] = {
            "mediaType": media_type,
            "mediaId": int(media_id),
            "is4k": False,
        }
        if media_type == "tv":
            if not seasons:
                raise ValueError("at least one TV season must be selected")
            body["seasons"] = sorted(
                set(int(season) for season in seasons if int(season) > 0)
            )
            if not body["seasons"]:
                raise ValueError("at least one non-special TV season must be selected")
        return self.http.request("POST", "/request", body)
