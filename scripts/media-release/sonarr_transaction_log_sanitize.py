#!/usr/bin/env python3
"""Redact secrets from Sonarr transaction-monitor JSONL logs."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SECRET_FIELD_RE = re.compile(r"(?i)(api[-_]?key|apikey|authorization|password|passwd|secret|token)")
SECRET_QUERY_KEYS = {
    "apikey",
    "api_key",
    "authorization",
    "auth",
    "key",
    "password",
    "passwd",
    "passkey",
    "secret",
    "token",
}
SENSITIVE_URL_FIELDS = {"downloadurl"}
REDACTED = "REDACTED"
REDACTED_URL = "REDACTED_URL"


def utc_stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def redact_url(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc or not parsed.query:
        return value
    query = []
    changed = False
    for key, item_value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.casefold() in SECRET_QUERY_KEYS:
            query.append((key, REDACTED))
            changed = True
        else:
            query.append((key, item_value))
    if not changed:
        return value
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def sanitize(value: Any, key: str | None = None) -> Any:
    if key and key.casefold() in SENSITIVE_URL_FIELDS:
        return REDACTED_URL
    if key and SECRET_FIELD_RE.search(key):
        return REDACTED
    if isinstance(value, dict):
        return {item_key: sanitize(item_value, item_key) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return redact_url(value)
    return value


def sanitize_file(path: Path, backup_dir: Path | None, in_place: bool) -> tuple[Path, int]:
    output = path.with_name(path.name + ".sanitized")
    rows = 0
    with path.open("r", encoding="utf-8") as source, output.open("w", encoding="utf-8") as target:
        for line_number, line in enumerate(source, start=1):
            stripped = line.strip()
            if not stripped:
                target.write(line)
                continue
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            json.dump(sanitize(event), target, sort_keys=True, separators=(",", ":"))
            target.write("\n")
            rows += 1
    output.chmod(path.stat().st_mode & 0o777)

    if not in_place:
        return output, rows

    if backup_dir is None:
        backup_dir = path.parent
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{path.name}.sanitized-backup-{utc_stamp()}"
    os.replace(output, backup)
    path_tmp = path.with_name(path.name + ".tmp-sanitized")
    with backup.open("r", encoding="utf-8") as source, path_tmp.open("w", encoding="utf-8") as target:
        for line in source:
            target.write(line)
    path_tmp.chmod(path.stat().st_mode & 0o777)
    os.replace(path_tmp, path)
    return backup, rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, default=Path("/var/log/sonarr-transaction-monitor/events.jsonl"))
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--in-place", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact, rows = sanitize_file(args.log, args.backup_dir, args.in_place)
    action = "updated" if args.in_place else "wrote"
    print(f"{action} rows={rows} artifact={artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
