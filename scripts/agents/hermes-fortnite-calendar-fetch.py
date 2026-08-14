#!/usr/bin/env python3
"""Fetch the public Fortnite schedule through Firefox for the calendar job."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


SOURCE_URL = "https://www.fortnite.com/competitive/schedule?region=NAC"
GECKODRIVER = Path("/snap/bin/geckodriver")
ROUTE_ID = "routes/competitive.schedule"
REGION = "NAC"
MAX_BYTES = 8 * 1024 * 1024


class FetchError(RuntimeError):
    """Raised when the official schedule cannot be fetched or validated."""


def request(
    method: str,
    url: str,
    *,
    payload: dict[str, object] | None = None,
    timeout: int = 30,
) -> Any:
    response = requests.request(method, url, json=payload, timeout=timeout)
    try:
        body = response.json()
    except ValueError as exc:
        raise FetchError(f"webdriver-non-json:{response.status_code}") from exc
    value = body.get("value") if isinstance(body, dict) else None
    if response.status_code >= 400:
        raise FetchError(f"webdriver-http:{response.status_code}")
    if isinstance(value, dict) and value.get("error"):
        raise FetchError(f"webdriver-error:{value['error']}")
    return value


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def fetch() -> dict[str, object]:
    if not GECKODRIVER.is_file():
        raise FetchError("geckodriver-missing")
    port = reserve_port()
    base = f"http://127.0.0.1:{port}"
    session_id: str | None = None
    with tempfile.NamedTemporaryFile(
        "w+", prefix="hermes-fortnite-geckodriver-", encoding="utf-8"
    ) as log:
        process = subprocess.Popen(
            [str(GECKODRIVER), "--port", str(port)],
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, "MOZ_HEADLESS": "1"},
        )
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                try:
                    status = request("GET", f"{base}/status", timeout=2)
                    if isinstance(status, dict) and status.get("ready"):
                        break
                except (requests.RequestException, FetchError):
                    time.sleep(0.25)
            else:
                raise FetchError("geckodriver-timeout")
            if process.poll() is not None:
                log.flush()
                log.seek(0)
                detail = log.read()[-500:].strip().replace("\n", " ")
                raise FetchError(f"geckodriver-start:{detail}")

            session = request(
                "POST",
                f"{base}/session",
                payload={
                    "capabilities": {
                        "alwaysMatch": {
                            "browserName": "firefox",
                            "pageLoadStrategy": "normal",
                            "moz:firefoxOptions": {"args": ["-headless"]},
                        }
                    }
                },
            )
            if not isinstance(session, dict) or not session.get("sessionId"):
                raise FetchError("webdriver-session")
            session_id = str(session["sessionId"])
            session_url = f"{base}/session/{session_id}"
            request(
                "POST",
                f"{session_url}/url",
                payload={"url": SOURCE_URL},
                timeout=120,
            )
            script = f"""
const route = window.__reactRouterDataRouter?.state?.loaderData?.[{json.dumps(ROUTE_ID)}];
if (!route || !Array.isArray(route.scheduleDays)) return null;
return {{ activeRegion: route.activeRegion, scheduleDays: route.scheduleDays }};
"""
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                value = request(
                    "POST",
                    f"{session_url}/execute/sync",
                    payload={"script": script, "args": []},
                    timeout=20,
                )
                if isinstance(value, dict) and isinstance(value.get("scheduleDays"), list):
                    if value.get("activeRegion") != REGION or not value["scheduleDays"]:
                        raise FetchError("schedule-region-or-shape")
                    body: dict[str, object] = {
                        "schemaVersion": 1,
                        "generatedAt": datetime.now(timezone.utc)
                        .replace(microsecond=0)
                        .isoformat(),
                        "source": SOURCE_URL,
                        "activeRegion": REGION,
                        "scheduleDays": value["scheduleDays"],
                    }
                    digest = hashlib.sha256(
                        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
                    ).hexdigest()
                    return {**body, "digest": digest}
                time.sleep(1)
            raise FetchError("schedule-data-timeout")
        finally:
            if session_id:
                try:
                    request("DELETE", f"{base}/session/{session_id}", timeout=15)
                except Exception:
                    pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(encoded) > MAX_BYTES:
        raise FetchError("schedule-artifact-too-large")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o640)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = fetch()
        atomic_json(args.output, payload)
        print(json.dumps({"status": "ok", "days": len(payload["scheduleDays"])}))
        return 0
    except (FetchError, OSError, requests.RequestException, subprocess.SubprocessError) as exc:
        print(f"Fortnite schedule fetch failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
