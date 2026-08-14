#!/usr/bin/env python3
"""Confirm native Hermes cron delivery before committing alert dedupe state."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class DeliveryStateError(Exception):
    """Raised when native job or pending-delivery state is ambiguous."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DeliveryStateError(f"invalid-json:{path.name}") from exc


def load_job_status(home: Path, name: str, script: str) -> dict[str, Any]:
    value = _read_json(home / "cron" / "jobs.json")
    jobs = value.get("jobs") if isinstance(value, dict) else None
    if not isinstance(jobs, list):
        raise DeliveryStateError("jobs-schema")
    matches = [
        row
        for row in jobs
        if isinstance(row, dict)
        and row.get("name") == name
        and Path(str(row.get("script", ""))).name == script
    ]
    if len(matches) != 1:
        raise DeliveryStateError("job-not-unique")
    row = matches[0]
    last_run = row.get("last_run_at")
    status = row.get("last_status")
    error = row.get("last_delivery_error")
    if last_run is not None and not isinstance(last_run, str):
        raise DeliveryStateError("job-last-run")
    if status is not None and not isinstance(status, str):
        raise DeliveryStateError("job-status")
    if error is not None and not isinstance(error, str):
        raise DeliveryStateError("job-delivery-error")
    return {
        "lastRunAt": last_run,
        "lastStatus": status,
        "lastDeliveryError": error,
    }


def validate_pending(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "keys",
        "payload",
        "priorLastRunAt",
        "stagedAt",
    }:
        raise DeliveryStateError("pending-schema")
    keys = value["keys"]
    payload = value["payload"]
    prior = value["priorLastRunAt"]
    staged = value["stagedAt"]
    if (
        not isinstance(keys, list)
        or not 1 <= len(keys) <= 64
        or not all(isinstance(key, str) and 0 < len(key) <= 200 for key in keys)
        or len(keys) != len(set(keys))
    ):
        raise DeliveryStateError("pending-keys")
    if not isinstance(payload, str) or not payload or len(payload) > 1_900:
        raise DeliveryStateError("pending-payload")
    if prior is not None and not isinstance(prior, str):
        raise DeliveryStateError("pending-prior")
    if not isinstance(staged, str):
        raise DeliveryStateError("pending-staged")
    try:
        datetime.fromisoformat(staged.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DeliveryStateError("pending-staged") from exc
    return value


def stage(
    keys: list[str],
    payload: str,
    status: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    return validate_pending(
        {
            "keys": keys,
            "payload": payload,
            "priorLastRunAt": status["lastRunAt"],
            "stagedAt": now.astimezone(timezone.utc).isoformat(),
        }
    ) or {}


def reconcile(
    pending: Any,
    status: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    current = validate_pending(pending)
    if current is None:
        return "none", None
    if status["lastRunAt"] == current["priorLastRunAt"]:
        return "waiting", current
    if status["lastStatus"] == "ok" and status["lastDeliveryError"] is None:
        return "delivered", current
    if status["lastStatus"] is None:
        return "waiting", current
    current["priorLastRunAt"] = status["lastRunAt"]
    return "retry", current
