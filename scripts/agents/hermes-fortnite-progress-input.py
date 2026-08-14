#!/usr/bin/env python3
"""Expose only the latest bounded Fortnite progress collector result."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


SOURCE = Path("/var/lib/hermes-automation/fortnite-progress.json")
MAX_BYTES = 262_144
MAX_AGE_SECONDS = 3 * 60 * 60


def main() -> int:
    try:
        stat = SOURCE.stat()
        if not SOURCE.is_file() or SOURCE.is_symlink() or stat.st_size > MAX_BYTES:
            raise OSError("invalid artifact")
        age = datetime.now(timezone.utc).timestamp() - stat.st_mtime
        if age < -300 or age > MAX_AGE_SECONDS:
            raise OSError("stale artifact")
        content = SOURCE.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        print("STATUS: unavailable")
        return 0
    print("STATUS: Fortnite progress source is fresh and bounded.")
    print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
