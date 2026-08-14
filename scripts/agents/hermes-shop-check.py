#!/usr/bin/env python3
"""Fetch genuinely first-time Fortnite shop entries, excluding Jam Tracks."""

from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone


URL = "https://fortnite-api.com/v2/shop"
RECENT_DAYS = 30


def main() -> int:
    try:
        request = urllib.request.Request(URL, headers={"User-Agent": "Hermes-Shop/1.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.load(response)
        shop_date = data.get("data", {}).get("date", "")[:10]
        entries = data.get("data", {}).get("entries", [])
        cutoff = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
        selected: dict[str, dict] = {}
        for entry in entries:
            if entry.get("tracks") or entry.get("inDate", "")[:10] != shop_date:
                continue
            bundle = entry.get("bundle") or {}
            is_bundle = bool(bundle.get("name"))
            for item in entry.get("brItems") or []:
                name = item.get("name")
                if not name or item.get("added", "")[:10] < cutoff or item.get("shopHistory"):
                    continue
                if name in selected and not selected[name]["isBundle"]:
                    continue
                selected[name] = {"item": item, "entry": entry, "isBundle": is_bundle}
        result = []
        for name, row in selected.items():
            item = row["item"]
            entry = row["entry"]
            result.append(
                {
                    "name": name,
                    "type": (item.get("type") or {}).get("displayValue", "Unknown"),
                    "rarity": (item.get("rarity") or {}).get("displayValue", "Unknown"),
                    "price": entry.get("finalPrice", 0),
                    "firstTimeInShop": True,
                    "inDate": entry.get("inDate", ""),
                }
            )
        print(json.dumps({"date": shop_date, "count": len(result), "new_items": result}, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc), "date": "", "count": 0, "new_items": []}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
