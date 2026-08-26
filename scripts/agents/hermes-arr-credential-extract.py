#!/usr/bin/env python3
"""Extract one Arr API key into a bounded credential object for Ansible."""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

SERVICE_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


def find_key(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower().replace("_", "") == "apikey" and isinstance(item, str):
                return item.strip()
            found = find_key(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_key(item)
            if found:
                return found
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--format", choices=["xml", "yaml"], required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-header", choices=["X-Api-Key", "X-API-KEY"], required=True)
    parser.add_argument("--path-prefix", action="append", required=True)
    parser.add_argument("--status-path", required=True)
    args = parser.parse_args()
    try:
        if SERVICE_RE.fullmatch(args.service) is None:
            raise ValueError("invalid-service")
        if args.format == "xml":
            root = ET.parse(args.config).getroot()
            node = root.find("ApiKey")
            api_key = (node.text or "").strip() if node is not None else ""
        else:
            import yaml

            api_key = find_key(yaml.safe_load(args.config.read_text(encoding="utf-8"))) or ""
        if (
            not 16 <= len(api_key) <= 256
            or any(ord(char) < 33 or ord(char) > 126 for char in api_key)
            or any(not prefix.startswith("/api/") or not prefix.endswith("/") for prefix in args.path_prefix)
            or not any(args.status_path.startswith(prefix) for prefix in args.path_prefix)
        ):
            raise ValueError("invalid-api-key-or-prefix")
        print(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "service": args.service,
                    "baseUrl": args.base_url.rstrip("/"),
                    "apiHeader": args.api_header,
                    "apiKey": api_key,
                    "pathPrefixes": args.path_prefix,
                    "statusPath": args.status_path,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    except Exception as exc:
        print(f"hermes-arr-credential-extract-error:{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
