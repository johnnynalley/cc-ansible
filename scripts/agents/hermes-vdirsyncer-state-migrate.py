#!/usr/bin/env python3
"""Convert imported vdirsyncer collection paths without touching source state."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any


MAX_BYTES = 1_048_576


class MigrationError(RuntimeError):
    """Raised when the imported collection state is unsafe or malformed."""


def load_state(path: Path) -> tuple[dict[str, Any], os.stat_result]:
    metadata = path.lstat()
    if path.is_symlink() or not path.is_file() or metadata.st_size > MAX_BYTES:
        raise MigrationError("collections-file-invalid")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MigrationError("collections-json-invalid") from exc
    if not isinstance(value, dict) or set(value) != {"cache_key", "collections"}:
        raise MigrationError("collections-shape-invalid")
    if not isinstance(value["cache_key"], str) or not isinstance(
        value["collections"], list
    ):
        raise MigrationError("collections-shape-invalid")
    return value, metadata


def convert(value: dict[str, Any], old_root: Path, new_root: Path) -> int:
    old_prefix = f"{old_root}/"
    new_prefix = f"{new_root}/"
    names: set[str] = set()
    replacements = 0
    for row in value["collections"]:
        if (
            not isinstance(row, list)
            or len(row) != 2
            or not isinstance(row[0], str)
            or not isinstance(row[1], list)
        ):
            raise MigrationError("collection-row-invalid")
        if row[0] in names:
            raise MigrationError("collection-name-duplicate")
        names.add(row[0])
        for storage in row[1]:
            if not isinstance(storage, dict):
                raise MigrationError("collection-storage-invalid")
            path = storage.get("path")
            if path is None:
                continue
            if not isinstance(path, str):
                raise MigrationError("collection-path-invalid")
            if path.startswith(old_prefix):
                storage["path"] = new_prefix + path.removeprefix(old_prefix)
                replacements += 1
            elif not path.startswith(new_prefix):
                raise MigrationError("collection-path-outside-approved-roots")
    if not names:
        raise MigrationError("collections-empty")
    return replacements


def atomic_write(path: Path, value: dict[str, Any], metadata: os.stat_result) -> None:
    encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, metadata.st_mode & 0o777)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collections", type=Path, required=True)
    parser.add_argument("--old-root", type=Path, required=True)
    parser.add_argument("--new-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        value, metadata = load_state(args.collections)
        replacements = convert(value, args.old_root, args.new_root)
        if args.apply and replacements:
            atomic_write(args.collections, value, metadata)
        status = "ok" if args.apply or replacements == 0 else "migration-required"
        print(
            json.dumps(
                {
                    "status": status,
                    "collections": len(value["collections"]),
                    "replacements": replacements,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0 if status == "ok" else 3
    except (MigrationError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
