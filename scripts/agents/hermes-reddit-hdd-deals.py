#!/usr/bin/env python3
"""Emit bounded unseen Reddit HDD sale candidates for semantic review."""

from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_cron_delivery import (
    DeliveryStateError,
    load_job_status,
    reconcile,
    stage,
)


SUBREDDITS = ("homelabsales", "hardwareswap")
KEYWORDS = re.compile(
    r"(?:\bhdd\b|hard.?drive|sata.*(?:tb|drive)|"
    r"\d+\s*tb.*(?:sata|hdd|drive|7200|5400)|barracuda|ultrastar|"
    r"ironwolf|exos|wd.*(?:red|gold|purple|blue)|seagate|"
    r"toshiba.*(?:n300|x300|mg)|hgst)",
    re.IGNORECASE,
)
SALE = re.compile(r"^\[FS\]|\[USA-.*\]\s*\[H\]", re.IGNORECASE)
MAX_RESPONSE = 2 * 1024 * 1024
MAX_CANDIDATES = 30
MAX_AGENT_INPUT = 1_800
JOB_NAME = "astra-reddit-hdd-deal-watch"
JOB_SCRIPT = "hermes-reddit-hdd-deals.py"


def fetch(subreddit: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"https://www.reddit.com/r/{subreddit}/new.json?limit=50",
        headers={"User-Agent": "Hermes-HDD-Deal-Watch/1.0"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = response.read(MAX_RESPONSE + 1)
    if len(payload) > MAX_RESPONSE:
        raise RuntimeError("reddit-response-too-large")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise RuntimeError("reddit-response-invalid")
    return value


def load_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = {}
    if isinstance(value, list):
        return {
            "seen": [item for item in value if isinstance(item, str)][-500:],
            "pending": None,
        }
    seen = value.get("seen") if isinstance(value, dict) else None
    if not isinstance(seen, list):
        seen = []
    return {
        "seen": [item for item in seen if isinstance(item, str)][-500:],
        "pending": value.get("pending") if isinstance(value, dict) else None,
    }


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def candidates(value: dict[str, Any], subreddit: str, seen: set[str]) -> list[dict[str, Any]]:
    children = ((value.get("data") or {}).get("children") or [])
    if not isinstance(children, list):
        raise RuntimeError("reddit-listing-invalid")
    result: list[dict[str, Any]] = []
    for row in children:
        data = row.get("data") if isinstance(row, dict) else None
        if not isinstance(data, dict):
            continue
        post_id = data.get("name")
        title = data.get("title")
        body = data.get("selftext") or ""
        flair = data.get("link_flair_text") or ""
        permalink = data.get("permalink")
        if not all(isinstance(item, str) for item in (post_id, title, body, flair, permalink)):
            continue
        if post_id in seen:
            continue
        combined = f"{title} {body[:2000]}"
        if not (SALE.search(title) or "selling" in flair.casefold() or "sale" in flair.casefold()):
            continue
        if not KEYWORDS.search(combined):
            continue
        if re.search(r"\b(?:ssd|nvme)\b", combined, re.IGNORECASE) and not re.search(
            r"\b(?:hdd|hard.?drive)\b|sata.*(?:tb|drive)", combined, re.IGNORECASE
        ):
            continue
        result.append(
            {
                "id": post_id,
                "subreddit": f"r/{subreddit}",
                "title": title[:300],
                "url": f"https://reddit.com{permalink}",
                "bodyPreview": body[:800],
                "flair": flair[:80],
                "createdUtc": data.get("created_utc"),
            }
        )
    return result


def main() -> int:
    home = Path(os.environ.get("HERMES_HOME", Path.home())).resolve()
    state_path = home / "state" / "reddit-hdd-seen.json"
    state = load_state(state_path)
    seen_ordered = state["seen"]
    seen = set(seen_ordered)
    try:
        status = load_job_status(home, JOB_NAME, JOB_SCRIPT)
        disposition, pending = reconcile(state["pending"], status)
    except DeliveryStateError as exc:
        print(f"Reddit HDD delivery state invalid: {exc}", file=os.sys.stderr)
        return 1
    if disposition == "delivered" and pending is not None:
        seen_ordered = (seen_ordered + pending["keys"])[-500:]
        seen = set(seen_ordered)
        pending = None
    elif disposition == "retry" and pending is not None:
        state = {"seen": seen_ordered, "pending": pending}
        atomic_write(state_path, state)
        print(pending["payload"])
        return 0
    elif disposition == "waiting":
        print('{"status":"ok","candidates":[]}')
        return 0
    found: list[dict[str, Any]] = []
    try:
        for subreddit in SUBREDDITS:
            rows = candidates(fetch(subreddit), subreddit, seen)
            found.extend(rows)
    except (RuntimeError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"Reddit HDD collector failed: {exc}", file=os.sys.stderr)
        return 1
    selected: list[dict[str, Any]] = []
    payload = '{"status":"ok","candidates":[]}'
    for row in found[:MAX_CANDIDATES]:
        candidate = json.dumps(
            {"status": "ok", "candidates": [*selected, row]},
            separators=(",", ":"),
        )
        if len(candidate) > MAX_AGENT_INPUT:
            break
        selected.append(row)
        payload = candidate
    if selected:
        try:
            pending = stage(
                [row["id"] for row in selected],
                payload,
                status,
                datetime.now(timezone.utc),
            )
        except DeliveryStateError as exc:
            print(f"Reddit HDD candidates refused: {exc}", file=os.sys.stderr)
            return 1
    state = {"seen": seen_ordered, "pending": pending}
    atomic_write(state_path, state)
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
