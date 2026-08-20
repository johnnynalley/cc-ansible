#!/usr/bin/env python3
"""Emit bounded unseen HDD sale candidates for semantic review."""

from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
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
EBAY_QUERIES = ("4TB SATA HDD", "8TB SATA HDD", "12TB SATA HDD", "16TB SATA HDD")
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


def request_json(request: urllib.request.Request, *, max_response: int = MAX_RESPONSE) -> dict[str, Any]:
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = response.read(max_response + 1)
    if len(payload) > max_response:
        raise RuntimeError("source-response-too-large")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise RuntimeError("source-response-invalid")
    return value


def ebay_token() -> str:
    app_id = os.environ.get("EBAY_APP_ID", "").strip()
    cert_id = os.environ.get("EBAY_CERT_ID", "").strip()
    if not app_id or not cert_id:
        raise RuntimeError("ebay-credentials-missing")
    basic = base64.b64encode(f"{app_id}:{cert_id}".encode("utf-8")).decode("ascii")
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        }
    ).encode("ascii")
    request = urllib.request.Request(
        "https://api.ebay.com/identity/v1/oauth2/token",
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    value = request_json(request)
    token = value.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("ebay-token-invalid")
    return token


def fetch_ebay(query: str, token: str) -> dict[str, Any]:
    params = urllib.parse.urlencode(
        {"q": query, "limit": "50", "sort": "newlyListed"}
    )
    request = urllib.request.Request(
        f"https://api.ebay.com/buy/browse/v1/item_summary/search?{params}",
        headers={
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            "Accept": "application/json",
        },
    )
    return request_json(request)


def load_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = {}
    if isinstance(value, list):
        return {
            "seen": [item for item in value if isinstance(item, str)][-500:],
            "pending": None,
            "sourceHealth": None,
        }
    seen = value.get("seen") if isinstance(value, dict) else None
    if not isinstance(seen, list):
        seen = []
    return {
        "seen": [item for item in seen if isinstance(item, str)][-500:],
        "pending": value.get("pending") if isinstance(value, dict) else None,
        "sourceHealth": value.get("sourceHealth") if isinstance(value, dict) else None,
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


def ebay_candidates(value: dict[str, Any], seen: set[str]) -> list[dict[str, Any]]:
    rows = value.get("itemSummaries") or []
    if not isinstance(rows, list):
        raise RuntimeError("ebay-listing-invalid")
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_id = row.get("itemId")
        title = row.get("title")
        url = row.get("itemWebUrl")
        if not all(isinstance(item, str) and item for item in (item_id, title, url)):
            continue
        if item_id in seen or not KEYWORDS.search(title):
            continue
        if re.search(r"\b(?:ssd|nvme)\b", title, re.IGNORECASE) and not re.search(
            r"\b(?:hdd|hard.?drive)\b|sata.*(?:tb|drive)", title, re.IGNORECASE
        ):
            continue
        price = row.get("price") if isinstance(row.get("price"), dict) else {}
        shipping_options = row.get("shippingOptions")
        shipping = shipping_options[0] if isinstance(shipping_options, list) and shipping_options else {}
        shipping_cost = shipping.get("shippingCost") if isinstance(shipping, dict) else {}
        location = row.get("itemLocation") if isinstance(row.get("itemLocation"), dict) else {}
        result.append(
            {
                "id": item_id,
                "source": "eBay",
                "title": title[:300],
                "url": url,
                "condition": str(row.get("condition") or "")[:80],
                "price": price,
                "shippingCost": shipping_cost if isinstance(shipping_cost, dict) else {},
                "location": {
                    "country": location.get("country"),
                    "stateOrProvince": location.get("stateOrProvince"),
                },
                "buyingOptions": row.get("buyingOptions") or [],
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
        state = {
            "seen": seen_ordered,
            "pending": pending,
            "sourceHealth": state["sourceHealth"],
        }
        atomic_write(state_path, state)
        print(pending["payload"])
        return 0
    elif disposition == "waiting":
        print('{"status":"ok","candidates":[]}')
        return 0
    found: list[dict[str, Any]] = []
    source_errors: list[str] = []
    sources_ok = 0
    for subreddit in SUBREDDITS:
        try:
            rows = candidates(fetch(subreddit), subreddit, seen)
            found.extend(rows)
            sources_ok += 1
        except (RuntimeError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            source_errors.append(
                f"reddit-{subreddit}:{type(exc).__name__}:{exc}"
            )
    try:
        token = ebay_token()
    except (RuntimeError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        source_errors.append(f"ebay-auth:{type(exc).__name__}:{exc}")
    else:
        ebay_seen = seen | {row["id"] for row in found}
        for query_index, query in enumerate(EBAY_QUERIES, start=1):
            try:
                value = fetch_ebay(query, token)
            except (RuntimeError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
                source_errors.append(
                    f"ebay-query-{query_index}:{type(exc).__name__}:{exc}"
                )
                continue
            for row in ebay_candidates(value, ebay_seen):
                ebay_seen.add(row["id"])
                found.append(row)
            sources_ok += 1
    if sources_ok == 0:
        state = {
            "seen": seen_ordered,
            "pending": pending,
            "sourceHealth": {
                "status": "degraded",
                "checkedAt": datetime.now(timezone.utc).isoformat(),
                "errors": source_errors,
            },
        }
        atomic_write(state_path, state)
        print(json.dumps({"status": "degraded", "candidates": []}, separators=(",", ":")))
        return 0
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
    state = {
        "seen": seen_ordered,
        "pending": pending,
        "sourceHealth": {
            "status": "ok" if not source_errors else "partial",
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "errors": source_errors,
        },
    }
    atomic_write(state_path, state)
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
