#!/usr/bin/env python3
"""Reconcile exact reviewed OpenClaw delivery-recovery records atomically."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

RECOVERY_FIELDS = {
    "pendingFinalDelivery",
    "pendingFinalDeliveryAttemptCount",
    "pendingFinalDeliveryContext",
    "pendingFinalDeliveryCreatedAt",
    "pendingFinalDeliveryIntentId",
    "pendingFinalDeliveryLastAttemptAt",
    "pendingFinalDeliveryLastError",
    "pendingFinalDeliveryText",
    "restartRecoveryDeliveryContext",
    "restartRecoveryDeliveryRunId",
}


class ReconciliationError(RuntimeError):
    """Raised when exact-state reconciliation cannot proceed safely."""


def _regular_file(path: Path) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ReconciliationError("session-index-unavailable") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise ReconciliationError("session-index-not-regular-file")
    return metadata


def _load(path: Path) -> tuple[dict[str, Any], bytes, os.stat_result]:
    metadata = _regular_file(path)
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReconciliationError("session-index-invalid-json") from exc
    if not isinstance(payload, dict):
        raise ReconciliationError("session-index-invalid-shape")
    return payload, raw, metadata


def _fingerprint(session_key: str, entry: dict[str, Any]) -> str:
    recovery = {
        field: entry[field]
        for field in sorted(RECOVERY_FIELDS.intersection(entry))
    }
    encoded = json.dumps(
        {"sessionKey": session_key, "recovery": recovery},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def inventory(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for session_key, entry in sorted(payload.items()):
        if not isinstance(entry, dict) or entry.get("archivedAt") is not None:
            continue
        fields = sorted(RECOVERY_FIELDS.intersection(entry))
        if not fields:
            continue
        records.append(
            {
                "fingerprint": _fingerprint(session_key, entry),
                "fields": fields,
            }
        )
    return records


def _write_new_private(path: Path, payload: bytes) -> None:
    parent = path.parent.resolve(strict=True)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
        dir_fd=None,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        directory_descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError:
        try:
            os.close(descriptor)
        except OSError:
            pass
        path.unlink(missing_ok=True)
        raise


def _replace_index(
    path: Path,
    payload: dict[str, Any],
    metadata: os.stat_result,
) -> None:
    parent = path.parent.resolve(strict=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, stat.S_IMODE(metadata.st_mode))
        os.fchown(descriptor, metadata.st_uid, metadata.st_gid)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise ReconciliationError("session-index-replace-failed") from exc


def reconcile(
    path: Path,
    expected_fingerprints: set[str],
    backup: Path,
) -> dict[str, Any]:
    payload, raw, metadata = _load(path)
    records = inventory(payload)
    actual_fingerprints = {record["fingerprint"] for record in records}
    if not expected_fingerprints:
        raise ReconciliationError("expected-fingerprint-set-empty")
    if actual_fingerprints != expected_fingerprints:
        raise ReconciliationError("recovery-fingerprint-set-mismatch")
    if len(actual_fingerprints) != len(records):
        raise ReconciliationError("duplicate-recovery-fingerprint")

    field_counts: Counter[str] = Counter()
    for entry in payload.values():
        if not isinstance(entry, dict) or entry.get("archivedAt") is not None:
            continue
        fields = RECOVERY_FIELDS.intersection(entry)
        if not fields:
            continue
        for field in fields:
            del entry[field]
            field_counts[field] += 1

    if inventory(payload):
        raise ReconciliationError("recovery-state-remained-after-reconcile")
    if backup.exists() or backup.is_symlink():
        raise ReconciliationError("backup-path-already-exists")
    _write_new_private(backup, raw)
    _replace_index(path, payload, metadata)
    return {
        "status": "reconciled",
        "entries": len(records),
        "fields": dict(sorted(field_counts.items())),
        "fingerprints": sorted(actual_fingerprints),
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    encoded = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    _write_new_private(path, encoded)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["inspect", "apply"], required=True)
    parser.add_argument("--session-index", type=Path, required=True)
    parser.add_argument("--expected-fingerprint", action="append", default=[])
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        payload, _, _ = _load(arguments.session_index)
        if arguments.mode == "inspect":
            records = inventory(payload)
            report = {
                "status": "inspection",
                "entries": len(records),
                "records": records,
            }
        else:
            if arguments.backup is None:
                raise ReconciliationError("backup-path-required")
            report = reconcile(
                arguments.session_index,
                set(arguments.expected_fingerprint),
                arguments.backup,
            )
        _write_report(arguments.output, report)
    except (OSError, ReconciliationError):
        print(json.dumps({"status": "error", "errorCode": "reconcile-failed"}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
