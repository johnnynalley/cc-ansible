#!/usr/bin/env python3
"""Shared validation for Fortnite ranked progression payloads."""
from __future__ import annotations

from typing import Any


def ranked_progression_issue(entry: dict[str, Any] | None) -> str | None:
    if not entry:
        return None

    division = entry.get('division')
    unreal_placement = entry.get('unrealPlacement')
    if type(division) is not int:
        return 'missing or non-integer division'
    if division < 0 or division > 21:
        return f'out-of-range division {division}'

    # OliTracker may leave promotionProgress populated after promotion. A valid
    # placement is the authoritative signal that division 21 is really Unreal.
    if division == 21 and (type(unreal_placement) is not int or unreal_placement <= 0):
        return 'OliTracker reported Unreal without a valid Unreal placement'
    return None
