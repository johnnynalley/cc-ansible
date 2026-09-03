#!/usr/bin/env python3
"""Return one bounded, read-only Arr operations report for Astra."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


QBIT_AUDIT = Path("/usr/local/bin/qbit-arr-stall-audit")
PROFILE_MATH_AUDIT = Path("/usr/local/sbin/arr-profile-math-audit")
TRANSACTION_AUDIT = Path("/usr/local/sbin/sonarr-transaction-audit")
MEDIA_HEALTH = Path("/usr/local/sbin/media-stack-health")
REPORTS = {"queue", "policy", "transactions", "storage"}
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_TEXT_BYTES = 256 * 1024
MAX_SAMPLES = 20


class ReportError(RuntimeError):
    """Expected fixed-code report failure."""


def error(code: str) -> dict[str, Any]:
    return {"schemaVersion": 1, "status": "error", "code": code}


def require_helper(path: Path) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise ReportError("helper-unavailable") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != 0
        or not info.st_mode & stat.S_IXUSR
    ):
        raise ReportError("helper-unavailable")


def run_json(command: list[str], timeout: int) -> dict[str, Any]:
    require_helper(Path(command[0]))
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=timeout,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReportError("report-unavailable") from exc
    if result.returncode != 0 or len(result.stdout) > MAX_JSON_BYTES:
        raise ReportError("report-unavailable")
    try:
        value = json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReportError("invalid-report") from exc
    if not isinstance(value, dict):
        raise ReportError("invalid-report")
    return value


def run_text(command: list[str], timeout: int) -> tuple[int, list[str], bool]:
    require_helper(Path(command[0]))
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=timeout,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReportError("report-unavailable") from exc
    truncated = len(result.stdout) > MAX_TEXT_BYTES
    text = result.stdout[:MAX_TEXT_BYTES].decode("utf-8", errors="replace")
    lines = [
        "".join(character for character in raw if character == "\t" or ord(character) >= 32)[:2048]
        for raw in text.splitlines()[:128]
    ]
    return result.returncode, lines, truncated or len(text.splitlines()) > 128


def mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def list_of_mappings(value: Any, limit: int = MAX_SAMPLES) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value[:limit] if isinstance(item, dict)]


def qbit_samples(value: Any) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for state, rows in sorted(mapping(value).items()):
        for row in list_of_mappings(rows, MAX_SAMPLES - len(samples)):
            correlation = mapping(row.get("arr_correlation"))
            history = mapping(correlation.get("history"))
            samples.append(
                {
                    "state": str(state)[:64],
                    "name": str(row.get("name") or "")[:512],
                    "hash": str(row.get("hash") or "")[:64],
                    "category": str(row.get("category") or "")[:64],
                    "progress": str(row.get("progress") or "")[:32],
                    "amountLeft": int(row.get("amount_left") or 0),
                    "seeds": int(row.get("num_seeds") or 0),
                    "peers": int(row.get("num_leechs") or 0),
                    "addedAt": row.get("added_at"),
                    "lastActivityAt": row.get("last_activity_at"),
                    "arr": {
                        "app": correlation.get("app"),
                        "classification": correlation.get("classification"),
                        "findings": list(correlation.get("findings") or [])[:16],
                        "labels": list(correlation.get("arr_labels") or [])[:16],
                        "messages": list(correlation.get("arr_messages") or [])[:16],
                        "grabBatchCount": history.get("grab_batch_count"),
                        "indexers": list(history.get("indexers") or [])[:16],
                    },
                }
            )
            if len(samples) >= MAX_SAMPLES:
                return samples
    return samples


def transaction_payload(*, hours: int, limit: int, live: bool = True) -> dict[str, Any]:
    command = [
        str(TRANSACTION_AUDIT),
        "--hours",
        str(hours),
        "--limit",
        str(limit),
        "--json",
    ]
    if not live:
        command.append("--no-live")
    return run_json(command, timeout=120)


def queue_report() -> dict[str, Any]:
    transaction = transaction_payload(hours=24, limit=MAX_SAMPLES)
    qbit = run_json(
        [
            str(QBIT_AUDIT),
            "--problem-only",
            "--correlate-arr",
            "--include-arr-history",
            "--sample-limit",
            str(MAX_SAMPLES),
            "--json",
        ],
        timeout=120,
    )
    return {
        "report": "arr-queue",
        "checkedAt": transaction.get("checked_at"),
        "liveQueue": mapping(transaction.get("live_queue")),
        "queueSnapshots": mapping(transaction.get("snapshots")),
        "qBittorrent": {
            "total": qbit.get("total"),
            "stateCounts": mapping(qbit.get("state_counts")),
            "classificationCounts": mapping(qbit.get("classification_counts")),
            "findingCounts": mapping(qbit.get("finding_counts")),
            "samples": qbit_samples(qbit.get("samples")),
        },
    }


def policy_report() -> dict[str, Any]:
    value = run_json(
        [str(PROFILE_MATH_AUDIT), "--json", "--no-fail"],
        timeout=120,
    )
    instances = []
    for instance in list_of_mappings(value.get("instances"), 8):
        profiles = []
        for profile in list_of_mappings(instance.get("profiles"), 16):
            profiles.append(
                {
                    "profile": profile.get("profile"),
                    "kind": profile.get("kind"),
                    "failures": list(profile.get("failures") or [])[:32],
                    "dual_audio_score": profile.get("dual_audio_score"),
                    "metadata_dual_audio_score": profile.get("metadata_dual_audio_score"),
                    "regular_dual_audio_score": profile.get("regular_dual_audio_score"),
                    "regular_english_guard_score": profile.get("regular_english_guard_score"),
                    "x265_score": profile.get("x265_score"),
                    "quality_rank_scores": mapping(profile.get("quality_rank_scores")),
                    "min_positive_dictionarry_score": profile.get("min_positive_dictionarry_score"),
                    "max_fallback_score": profile.get("max_fallback_score"),
                    "max_service_score": profile.get("max_service_score"),
                    "max_repack_score": profile.get("max_repack_score"),
                    "max_applicable_path_score": profile.get("max_applicable_path_score"),
                    "positive_score_ceiling": profile.get("positive_score_ceiling"),
                    "actual_cutoff_format_score": profile.get("actual_cutoff_format_score"),
                    "expected_cutoff_format_score": profile.get("expected_cutoff_format_score"),
                    "stacks": mapping(profile.get("stacks")),
                }
            )
        instances.append(
            {
                "instance": instance.get("instance"),
                "customFormatCount": instance.get("custom_format_count"),
                "customFormatLimit": instance.get("custom_format_limit"),
                "failures": list(instance.get("failures") or [])[:32],
                "profiles": profiles,
            }
        )
    return {"report": "arr-policy", "instances": instances}


def transactions_report() -> dict[str, Any]:
    value = transaction_payload(hours=72, limit=MAX_SAMPLES)
    return {
        "report": "arr-transactions",
        "since": value.get("since"),
        "checkedAt": value.get("checked_at"),
        "history": mapping(value.get("history")),
        "reconciler": mapping(value.get("reconciler")),
        "stamper": mapping(value.get("stamper")),
    }


def storage_report() -> dict[str, Any]:
    value = transaction_payload(hours=168, limit=1, live=False)
    health_exit, health_output, health_truncated = run_text(
        [str(MEDIA_HEALTH), "--status"], timeout=45
    )
    return {
        "report": "arr-storage",
        "since": value.get("since"),
        "checkedAt": value.get("checked_at"),
        "storage": mapping(value.get("storage")),
        "queueSnapshots": mapping(value.get("snapshots")),
        "mediaHealth": {
            "exitCode": health_exit,
            "output": health_output,
            "truncated": health_truncated,
        },
    }


def build_report(name: str) -> dict[str, Any]:
    if name == "queue":
        return queue_report()
    if name == "policy":
        return policy_report()
    if name == "transactions":
        return transactions_report()
    if name == "storage":
        return storage_report()
    raise ReportError("invalid-report")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", choices=sorted(REPORTS), required=True)
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise ReportError("authority-denied")
        response = {
            "schemaVersion": 1,
            "status": "ok",
            "body": build_report(args.report),
        }
    except ReportError as exc:
        response = error(str(exc))
    print(json.dumps(response, sort_keys=True, separators=(",", ":")))
    return 0 if response["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
