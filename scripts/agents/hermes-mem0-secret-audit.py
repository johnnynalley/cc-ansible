#!/usr/bin/env python3
"""Scan a local Qdrant Mem0 collection for high-confidence credential shapes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


class AuditError(RuntimeError):
    """Raised when a complete content-free audit cannot be proven."""


SECRET_PATTERNS = {
    "aws-access-key": re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])"),
    "bearer-token": re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    "discord-token": re.compile(
        r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{20,32}\.[A-Za-z0-9_-]{6}\."
        r"[A-Za-z0-9_-]{20,64}(?![A-Za-z0-9_-])"
    ),
    "github-token": re.compile(r"(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9]{30,255}"),
    "google-api-key": re.compile(r"(?<![A-Za-z0-9_-])AIza[A-Za-z0-9_-]{30,60}"),
    "jwt": re.compile(
        r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\."
        r"[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])"
    ),
    "openai-api-key": re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}"),
    "private-key": re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    "credential-assignment": re.compile(
        r"(?i)\b(?:api[_ -]?key|access[_ -]?token|auth[_ -]?token|bearer[_ -]?token|"
        r"password|client[_ -]?secret)\b\s*(?::|=|is)\s*[\"']?"
        r"[A-Za-z0-9._~+/=-]{16,}"
    ),
}


def require(condition: bool, code: str) -> None:
    if not condition:
        raise AuditError(code)


def strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def finding_classes(payload: Any) -> list[str]:
    matches = {
        name
        for value in strings(payload)
        for name, pattern in SECRET_PATTERNS.items()
        if pattern.search(value)
    }
    return sorted(matches)


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def request_json(url: str, body: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            value = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise AuditError("qdrant-request") from exc
    require(isinstance(value, dict) and value.get("status") == "ok", "qdrant-response")
    return value


def scroll_collection(
    qdrant_url: str, collection: str, batch_size: int, max_points: int
) -> list[dict[str, Any]]:
    endpoint = (
        f"{qdrant_url.rstrip('/')}/collections/"
        f"{urllib.parse.quote(collection, safe='')}/points/scroll"
    )
    points: list[dict[str, Any]] = []
    offset: Any = None
    while True:
        body: dict[str, Any] = {
            "limit": batch_size,
            "with_payload": True,
            "with_vector": False,
        }
        if offset is not None:
            body["offset"] = offset
        value = request_json(endpoint, body)
        result = value.get("result")
        require(isinstance(result, dict), "qdrant-result")
        page = result.get("points")
        require(isinstance(page, list), "qdrant-points")
        for point in page:
            require(isinstance(point, dict) and "id" in point, "qdrant-point")
            require(isinstance(point.get("payload"), dict), "qdrant-payload")
            points.append(point)
            require(len(points) <= max_points, "point-limit")
        next_offset = result.get("next_page_offset")
        if next_offset is None:
            break
        require(next_offset != offset, "qdrant-offset-loop")
        offset = next_offset
    return points


def build_report(collection: str, points: list[dict[str, Any]]) -> dict[str, Any]:
    findings = []
    for point in points:
        payload = point["payload"]
        classes = finding_classes(payload)
        if classes:
            findings.append(
                {
                    "pointId": str(point["id"]),
                    "payloadSha256": canonical_hash(payload),
                    "classes": classes,
                }
            )
    findings.sort(key=lambda item: item["pointId"])
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "collection": collection,
        "scannedPoints": len(points),
        "findings": findings,
        "findingsDigest": canonical_hash(findings),
    }


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    info = os.lstat(path.parent)
    require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode), "report-parent")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    value.add_argument("--collection", required=True)
    value.add_argument("--report", type=Path, required=True)
    value.add_argument("--batch-size", type=int, default=256)
    value.add_argument("--max-points", type=int, default=100_000)
    value.add_argument("--fail-on-findings", action="store_true")
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        parsed = urllib.parse.urlparse(args.qdrant_url)
        require(parsed.scheme == "http", "qdrant-scheme")
        require(parsed.hostname in {"127.0.0.1", "localhost", "::1"}, "qdrant-not-loopback")
        require(1 <= args.batch_size <= 1_000, "batch-size")
        require(1 <= args.max_points <= 1_000_000, "max-points")
        require(args.report.is_absolute(), "report-relative")
        points = scroll_collection(
            args.qdrant_url, args.collection, args.batch_size, args.max_points
        )
        report = build_report(args.collection, points)
        atomic_json(args.report, report)
        counts = Counter(
            item for finding in report["findings"] for item in finding["classes"]
        )
        output = {
            "status": "findings" if report["findings"] else "clean",
            "collection": args.collection,
            "scannedPoints": report["scannedPoints"],
            "findingPoints": len(report["findings"]),
            "classes": dict(sorted(counts.items())),
            "findingsDigest": report["findingsDigest"],
            "reportSha256": hashlib.sha256(args.report.read_bytes()).hexdigest(),
        }
        print(json.dumps(output, sort_keys=True, separators=(",", ":")))
        return 2 if args.fail_on_findings and report["findings"] else 0
    except (AuditError, OSError, ValueError) as exc:
        code = str(exc) if isinstance(exc, AuditError) else type(exc).__name__
        print(f"mem0-secret-audit-error:{code}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
