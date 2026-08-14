#!/usr/bin/env python3
"""Run the retained signed Fortnite calendar transaction without OpenClaw."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
SOURCE_URL = "https://www.fortnite.com/competitive/schedule?region=NAC"
MAX_SCHEDULE_AGE = timedelta(minutes=15)
MAX_SCHEDULE_BYTES = 8 * 1024 * 1024


def load_schedule(path: Path) -> list[dict[str, object]]:
    metadata = path.lstat()
    if path.is_symlink() or not path.is_file() or metadata.st_size > MAX_SCHEDULE_BYTES:
        raise RuntimeError("schedule-artifact")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("schedule-shape")
    digest = value.get("digest")
    body = {key: item for key, item in value.items() if key != "digest"}
    computed = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if digest != computed or value.get("schemaVersion") != 1:
        raise RuntimeError("schedule-digest")
    if value.get("source") != SOURCE_URL or value.get("activeRegion") != "NAC":
        raise RuntimeError("schedule-source")
    generated = datetime.fromisoformat(str(value.get("generatedAt", "")))
    if generated.tzinfo is None:
        raise RuntimeError("schedule-timezone")
    age = datetime.now(timezone.utc) - generated.astimezone(timezone.utc)
    if age < timedelta(seconds=-30) or age > MAX_SCHEDULE_AGE:
        raise RuntimeError("schedule-stale")
    days = value.get("scheduleDays")
    if not isinstance(days, list) or not days or not all(isinstance(day, dict) for day in days):
        raise RuntimeError("schedule-days")
    return days


def load_legacy(script: Path) -> Any:
    metadata = script.lstat()
    if script.is_symlink() or not script.is_file() or metadata.st_size > 2 * 1024 * 1024:
        raise RuntimeError("legacy-script")
    spec = importlib.util.spec_from_file_location("hermes_fortnite_calendar_legacy", script)
    if not spec or not spec.loader:
        raise RuntimeError("legacy-import")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def validate_plan(plan: dict[str, Any]) -> str:
    digest = plan.get("digest")
    decisions = plan.get("decisions")
    summary = plan.get("summary")
    if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
        raise RuntimeError("plan-digest")
    if not isinstance(decisions, list) or not isinstance(summary, dict):
        raise RuntimeError("plan-shape")
    if summary.get("candidateCount") != len(decisions):
        raise RuntimeError("plan-count")
    accepted = sum(1 for row in decisions if isinstance(row, dict) and row.get("accepted") is True)
    rejected = sum(1 for row in decisions if isinstance(row, dict) and row.get("accepted") is False)
    if accepted + rejected != len(decisions):
        raise RuntimeError("plan-decision")
    if summary.get("acceptedCount") != accepted or summary.get("rejectedCount") != rejected:
        raise RuntimeError("plan-summary")
    return digest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--schedule-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        schedule_days = load_schedule(args.schedule_file)
        module = load_legacy(args.script)
        module.fetch_official_schedule_days = lambda **_kwargs: schedule_days
        self_test = module.self_test()
        if self_test.get("tests", 0) < 15:
            raise RuntimeError("self-test-count")
        plan = module.collect_candidate_plan(write=True)
        digest = validate_plan(plan)
        reviewed = module.load_reviewed_plan(digest)
        eligibility = module.load_eligibility()
        events = module.events_from_plan(reviewed)
        module.ensure_remote_calendar()
        module.vdirsyncer_sync()
        counts = module.sync_events(events, dry_run=False)
        module.vdirsyncer_sync()
        verification = module.verify_local_calendar(events)
        if not isinstance(verification, dict) or verification.get("ok") is not True:
            raise RuntimeError("apply-verification")
        module.write_state(
            events,
            counts,
            "UTC",
            eligibility,
            digest,
            verification,
            dry_run=False,
        )
        print(json.dumps({"status": "ok", "digest": digest, "counts": counts}, separators=(",", ":")))
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"Fortnite calendar compatibility transaction failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
