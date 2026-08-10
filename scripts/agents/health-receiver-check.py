#!/usr/bin/env python3
"""Validate the isolated Health receiver without exposing its bearer token."""

import argparse
import ipaddress
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


def validated_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.path != "/health" or parsed.query:
        raise argparse.ArgumentTypeError(
            "URL must be http://<literal-ip>:<port>/health"
        )
    try:
        ipaddress.ip_address(parsed.hostname or "")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("URL host must be a literal IP") from exc
    if parsed.port is None or not 1024 <= parsed.port <= 65535:
        raise argparse.ArgumentTypeError("URL must use an unprivileged port")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", type=validated_url, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--require-metrics", action="store_true")
    args = parser.parse_args()

    token_stat = args.token_file.stat()
    if token_stat.st_mode & 0o037:
        print("ERROR: token file permissions are too broad", file=sys.stderr)
        return 1
    token = args.token_file.read_text(encoding="utf-8").strip()
    if len(token.encode("utf-8")) < 32:
        print("ERROR: token file is invalid", file=sys.stderr)
        return 1

    request = urllib.request.Request(
        args.url,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read(65537)
    except (OSError, urllib.error.URLError) as exc:
        print(f"ERROR: receiver request failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        token = ""

    if len(body) > 65536:
        print("ERROR: receiver response is too large", file=sys.stderr)
        return 1
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        print("ERROR: receiver returned invalid JSON", file=sys.stderr)
        return 1
    if payload.get("status") != "running":
        print("ERROR: receiver is not running", file=sys.stderr)
        return 1
    metrics = payload.get("records", {}).get("metrics")
    if args.require_metrics and (not isinstance(metrics, int) or metrics < 1):
        print("ERROR: receiver database has no metrics", file=sys.stderr)
        return 1

    print("OK: isolated Health receiver passed authenticated validation")
    return 0


if __name__ == "__main__":
    os.umask(0o077)
    raise SystemExit(main())
