#!/usr/bin/env python3
"""Compatibility wrapper for the Radarr regular-English language guard."""

from __future__ import annotations

import sys

from arr_regular_english_language_guard import main


if __name__ == "__main__":
    sys.argv[1:1] = ["--instance", "radarr"]
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
