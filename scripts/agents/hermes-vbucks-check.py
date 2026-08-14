#!/usr/bin/env python3
"""Fetch and parse current Save the World V-Bucks missions."""

from __future__ import annotations

import json
import re
import sys
import urllib.request


URL = "https://freethevbucks.com/timed-missions/"


def main() -> int:
    try:
        request = urllib.request.Request(URL, headers={"User-Agent": "Hermes-STW/1.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            html = response.read(4 * 1024 * 1024).decode("utf-8", errors="replace")
        pattern = re.compile(
            r'(\d+)<img\s+src="[^"]*vbucks19\.png"[^>]*>'
            r'(?:&nbsp;)*\s*'
            r'<span[^>]*>(\d+)<i\s+class="icon-flash"[^>]*></i></span>'
            r'\s*<span\s+class="hidden-xs"[^>]*>([^<]*)</span>'
            r'.*?'
            r'<span[^>]*>\s*in\s+([A-Za-z\s]+)</span>',
            re.IGNORECASE,
        )
        missions = []
        seen: set[tuple[int, int]] = set()
        for match in pattern.finditer(html):
            amount = int(match.group(1))
            power_level = int(match.group(2))
            key = (amount, power_level)
            if key in seen:
                continue
            seen.add(key)
            missions.append(
                {
                    "zone": match.group(4).strip(),
                    "power_level": power_level,
                    "amount": amount,
                    "type": match.group(3).strip() or None,
                }
            )
        missions.sort(key=lambda item: item["power_level"])
        print(
            json.dumps(
                {
                    "total": sum(item["amount"] for item in missions),
                    "count": len(missions),
                    "missions": missions,
                },
                separators=(",", ":"),
            )
        )
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc), "total": 0, "count": 0, "missions": []}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
