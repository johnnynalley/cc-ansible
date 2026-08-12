#!/usr/bin/env python3
"""Compare OpenClaw workspace manifests without disclosing retained paths."""

from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
ALLOWED_ORIGINS = {"retained", "modern-overlay"}
ALLOWED_OWNER_CLASSES = {"executor-writable", "operator-readonly"}
REQUIRED_SUMMARY_KEYS = {
    "sourceObjects",
    "targetObjects",
    "files",
    "bytes",
    "filesByOrigin",
    "filesByOwnerClass",
}


class ManifestParityError(RuntimeError):
    """Raised when a workspace manifest is malformed or unsafe."""


def _safe_relative(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise ManifestParityError(f"{label}-unsafe")
    if any(ord(character) < 32 for character in value):
        raise ManifestParityError(f"{label}-unsafe")
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ManifestParityError(f"{label}-unsafe")
    return path.as_posix()


def _nonnegative_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ManifestParityError(f"{label}-invalid")
    return value


def _load_manifest(path: Path, label: str) -> tuple[dict[str, Any], dict[str, dict]]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ManifestParityError(f"{label}-unavailable") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise ManifestParityError(f"{label}-not-regular")
    if metadata.st_size > MAX_MANIFEST_BYTES:
        raise ManifestParityError(f"{label}-too-large")
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestParityError(f"{label}-invalid-json") from exc
    if not isinstance(payload, dict):
        raise ManifestParityError(f"{label}-invalid-root")
    if payload.get("schemaVersion") != SCHEMA_VERSION or payload.get("status") != "ok":
        raise ManifestParityError(f"{label}-invalid-schema")
    if (
        not isinstance(payload.get("archiveContract"), str)
        or not payload["archiveContract"]
    ):
        raise ManifestParityError(f"{label}-invalid-archive-contract")
    summary = payload.get("summary")
    files = payload.get("files")
    if not isinstance(summary, dict) or not REQUIRED_SUMMARY_KEYS.issubset(summary):
        raise ManifestParityError(f"{label}-invalid-summary")
    if not isinstance(files, list):
        raise ManifestParityError(f"{label}-invalid-files")

    records: dict[str, dict] = {}
    origin_counts: Counter[str] = Counter()
    owner_counts: Counter[str] = Counter()
    total_bytes = 0
    for row in files:
        if not isinstance(row, dict):
            raise ManifestParityError(f"{label}-invalid-file-row")
        target = _safe_relative(row.get("targetRelative"), f"{label}-target")
        source = _safe_relative(row.get("sourceRelative"), f"{label}-source")
        origin = row.get("origin")
        owner_class = row.get("ownerClass")
        byte_count = _nonnegative_integer(row.get("bytes"), f"{label}-bytes")
        digest = row.get("sha256")
        if origin not in ALLOWED_ORIGINS:
            raise ManifestParityError(f"{label}-invalid-origin")
        if owner_class not in ALLOWED_OWNER_CLASSES:
            raise ManifestParityError(f"{label}-invalid-owner-class")
        if origin == "modern-overlay" and owner_class != "operator-readonly":
            raise ManifestParityError(f"{label}-mutable-overlay")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ManifestParityError(f"{label}-invalid-sha256")
        if target in records:
            raise ManifestParityError(f"{label}-duplicate-target")
        records[target] = {
            "sourceRelative": source,
            "origin": origin,
            "ownerClass": owner_class,
            "bytes": byte_count,
            "sha256": digest,
        }
        total_bytes += byte_count
        origin_counts[origin] += 1
        owner_counts[owner_class] += 1

    if _nonnegative_integer(summary.get("files"), f"{label}-summary-files") != len(
        records
    ):
        raise ManifestParityError(f"{label}-summary-file-mismatch")
    if (
        _nonnegative_integer(summary.get("bytes"), f"{label}-summary-bytes")
        != total_bytes
    ):
        raise ManifestParityError(f"{label}-summary-byte-mismatch")
    if summary.get("filesByOrigin") != dict(origin_counts):
        raise ManifestParityError(f"{label}-summary-origin-mismatch")
    if summary.get("filesByOwnerClass") != dict(owner_counts):
        raise ManifestParityError(f"{label}-summary-owner-mismatch")
    _nonnegative_integer(summary.get("sourceObjects"), f"{label}-source-objects")
    target_objects = _nonnegative_integer(
        summary.get("targetObjects"), f"{label}-target-objects"
    )
    if target_objects < len(records):
        raise ManifestParityError(f"{label}-target-object-mismatch")
    return payload, records


def compare_manifests(baseline_path: Path, candidate_path: Path) -> dict[str, Any]:
    baseline, baseline_records = _load_manifest(baseline_path, "baseline")
    candidate, candidate_records = _load_manifest(candidate_path, "candidate")
    baseline_paths = set(baseline_records)
    candidate_paths = set(candidate_records)
    added = candidate_paths - baseline_paths
    removed = baseline_paths - candidate_paths
    metadata_changed = 0
    immutable_content_changed = 0
    mutable_content_changed = 0
    mutable_byte_delta = 0
    change_classes: Counter[str] = Counter()

    for target in sorted(baseline_paths & candidate_paths):
        before = baseline_records[target]
        after = candidate_records[target]
        metadata_fields = ("sourceRelative", "origin", "ownerClass")
        if any(before[field] != after[field] for field in metadata_fields):
            metadata_changed += 1
            continue
        if before["bytes"] == after["bytes"] and before["sha256"] == after["sha256"]:
            continue
        change_class = f"{after['origin']}:{after['ownerClass']}"
        change_classes[change_class] += 1
        if after["origin"] == "retained" and after["ownerClass"] == "executor-writable":
            mutable_content_changed += 1
            mutable_byte_delta += after["bytes"] - before["bytes"]
        else:
            immutable_content_changed += 1

    structural_summary_fields = (
        "sourceObjects",
        "targetObjects",
        "files",
        "filesByOrigin",
        "filesByOwnerClass",
    )
    summary_changed = sum(
        baseline["summary"].get(field) != candidate["summary"].get(field)
        for field in structural_summary_fields
    )
    archive_contract_changed = (
        baseline["archiveContract"] != candidate["archiveContract"]
    )
    allowed = not any(
        (
            added,
            removed,
            metadata_changed,
            immutable_content_changed,
            summary_changed,
            archive_contract_changed,
        )
    )
    parity = (
        "exact"
        if allowed and mutable_content_changed == 0
        else "approved-mutable-drift"
    )
    if not allowed:
        parity = "failed"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "ok" if allowed else "error",
        "parity": parity,
        "summary": {
            "filesCompared": len(baseline_paths & candidate_paths),
            "addedFiles": len(added),
            "removedFiles": len(removed),
            "metadataChangedFiles": metadata_changed,
            "immutableContentChangedFiles": immutable_content_changed,
            "mutableContentChangedFiles": mutable_content_changed,
            "mutableByteDelta": mutable_byte_delta,
            "structuralSummaryChanges": summary_changed,
            "archiveContractChanged": archive_contract_changed,
            "changeClasses": dict(sorted(change_classes.items())),
        },
    }


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    parent = path.parent
    try:
        metadata = parent.lstat()
    except OSError as exc:
        raise ManifestParityError("output-parent-unavailable") from exc
    if parent.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise ManifestParityError("output-parent-unsafe")
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ManifestParityError("output-path-unsafe")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise ManifestParityError("output-write-failed") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        report = compare_manifests(arguments.baseline, arguments.candidate)
        _write_json_atomic(arguments.output, report)
    except ManifestParityError as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "errorCode": "workspace-manifest-parity-failed",
                    "reason": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
