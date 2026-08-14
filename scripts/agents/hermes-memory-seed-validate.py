#!/usr/bin/env python3
"""Validate one curated memory seed with the pinned Hermes memory scanner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path


class SeedError(RuntimeError):
    """Raised when a memory seed violates the reviewed boundary."""


def require_regular(path: Path) -> None:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SeedError("seed-not-regular")
    if stat.S_IMODE(metadata.st_mode) & 0o111:
        raise SeedError("seed-executable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True)
    parser.add_argument("--name", choices=("MEMORY.md", "USER.md"), required=True)
    parser.add_argument("--max-chars", type=int, required=True)
    parser.add_argument("--hermes-source", required=True)
    args = parser.parse_args()

    try:
        if args.max_chars not in {1375, 2200}:
            raise SeedError("unsupported-character-limit")
        path = Path(args.path)
        require_regular(path)
        raw = path.read_text(encoding="utf-8")
        if "\x00" in raw:
            raise SeedError("seed-contains-nul")

        source = Path(args.hermes_source)
        require_regular(source / "tools" / "memory_tool.py")
        sys.path.insert(0, str(source))
        from tools.memory_tool import (  # pylint: disable=import-outside-toplevel
            ENTRY_DELIMITER,
            MemoryStore,
            _scan_memory_content,
        )

        entries = MemoryStore._parse_entries(raw)
        if not entries:
            raise SeedError("seed-empty")
        if raw.strip() != ENTRY_DELIMITER.join(entries):
            raise SeedError("seed-roundtrip-drift")
        char_count = sum(len(entry) for entry in entries)
        if char_count > args.max_chars:
            raise SeedError("seed-over-character-limit")
        for entry in entries:
            if _scan_memory_content(entry):
                raise SeedError("seed-threat-pattern")

        print(
            json.dumps(
                {
                    "status": "ok",
                    "name": args.name,
                    "entries": len(entries),
                    "characters": char_count,
                    "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                    "nativeThreatScanner": True,
                    "cleanRoundTrip": True,
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:  # Keep validation failures bounded and content-free.
        error_id = hashlib.sha256(str(exc).encode("utf-8")).hexdigest()[:12]
        print(json.dumps({"status": "error", "error": "memory-seed-invalid", "errorId": error_id}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
