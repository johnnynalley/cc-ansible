#!/usr/bin/env python3
"""Reconcile a bounded manifest through Hermes's native cron API."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._#-]{0,95}$")
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,95}$")
SCRIPT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
DELIVERY_RE = re.compile(r"^(?:local|discord:[0-9]{17,20})$")
ORIGIN_KIND = "cc-ansible-hermes-production"


class ReconcileError(Exception):
    """Raised when the manifest or native cron state is unsafe."""


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReconcileError(
            f"json-read-failed:{path.name}:errno={exc.errno}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ReconcileError(
            f"invalid-json:{path.name}:line={exc.lineno}:column={exc.colno}"
        ) from exc


def parse_expiry(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ReconcileError("invalid-expiry")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReconcileError("invalid-expiry") from exc
    if parsed.tzinfo is None:
        raise ReconcileError("naive-expiry")
    return parsed.astimezone(timezone.utc)


def optional_string_list(value: Any, code: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 16:
        raise ReconcileError(code)
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or len(item) > 96:
            raise ReconcileError(code)
        result.append(item)
    if len(result) != len(set(result)):
        raise ReconcileError(code)
    return result


def validate_job(value: Any, scripts_root: Path) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReconcileError("invalid-job")
    allowed = {
        "key",
        "name",
        "schedule",
        "prompt",
        "deliver",
        "script",
        "noAgent",
        "model",
        "provider",
        "skills",
        "enabledToolsets",
        "continuity",
        "workdir",
        "adoptExisting",
        "expiresAt",
    }
    if set(value) - allowed:
        raise ReconcileError("unknown-job-field")
    key = value.get("key")
    name = value.get("name")
    schedule = value.get("schedule")
    prompt = value.get("prompt", "")
    deliver = value.get("deliver")
    script = value.get("script")
    no_agent = value.get("noAgent", False)
    model = value.get("model")
    provider = value.get("provider")
    continuity = value.get("continuity", False)
    workdir = value.get("workdir")
    adopt_existing = value.get("adoptExisting", False)
    if not isinstance(key, str) or not KEY_RE.fullmatch(key):
        raise ReconcileError("invalid-job-key")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ReconcileError(f"invalid-job-name:{key}")
    if not isinstance(schedule, str) or not schedule or len(schedule) > 128:
        raise ReconcileError(f"invalid-schedule:{key}")
    if not isinstance(prompt, str) or len(prompt.encode("utf-8")) > 32_768:
        raise ReconcileError(f"invalid-prompt:{key}")
    if not isinstance(deliver, str) or not DELIVERY_RE.fullmatch(deliver):
        raise ReconcileError(f"invalid-delivery:{key}")
    if (
        not isinstance(no_agent, bool)
        or not isinstance(continuity, bool)
        or not isinstance(adopt_existing, bool)
    ):
        raise ReconcileError(f"invalid-mode:{key}")
    if script is not None:
        if not isinstance(script, str) or not SCRIPT_RE.fullmatch(script):
            raise ReconcileError(f"invalid-script:{key}")
        script_path = scripts_root / script
        if not script_path.is_file() or script_path.is_symlink():
            raise ReconcileError(f"missing-script:{key}")
    if no_agent and script is None:
        raise ReconcileError(f"script-required:{key}")
    if not no_agent and not prompt.strip():
        raise ReconcileError(f"prompt-required:{key}")
    if continuity and no_agent:
        raise ReconcileError(f"continuity-requires-agent:{key}")
    if workdir is not None and (
        not isinstance(workdir, str)
        or not workdir
        or len(workdir) > 512
        or "\x00" in workdir
        or not Path(workdir).is_absolute()
    ):
        raise ReconcileError(f"invalid-workdir:{key}")
    if (model is None) != (provider is None):
        raise ReconcileError(f"incomplete-model-pin:{key}")
    if model is not None and (
        not isinstance(model, str)
        or not isinstance(provider, str)
        or not model
        or not provider
        or len(model) > 128
        or len(provider) > 64
    ):
        raise ReconcileError(f"invalid-model-pin:{key}")
    normalized = dict(value)
    normalized["skills"] = optional_string_list(value.get("skills"), f"invalid-skills:{key}")
    normalized["enabledToolsets"] = optional_string_list(
        value.get("enabledToolsets"), f"invalid-toolsets:{key}"
    )
    normalized["adoptExisting"] = adopt_existing
    normalized["continuity"] = continuity
    normalized["workdir"] = workdir
    normalized["expiresAt"] = parse_expiry(value.get("expiresAt"))
    return normalized


def load_manifest(path: Path, scripts_root: Path, profile: str) -> list[dict[str, Any]]:
    value = load_json(path)
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise ReconcileError("invalid-manifest")
    if set(value) != {"schemaVersion", "profile", "jobs"}:
        raise ReconcileError("unknown-manifest-field")
    if value.get("profile") != profile:
        raise ReconcileError("profile-mismatch")
    jobs = value.get("jobs")
    if not isinstance(jobs, list):
        raise ReconcileError("invalid-jobs")
    normalized = [validate_job(job, scripts_root) for job in jobs]
    for field in ("key", "name"):
        values = [job[field].casefold() for job in normalized]
        if len(values) != len(set(values)):
            raise ReconcileError(f"duplicate-job-{field}")
    return normalized


def origin_for(job: dict[str, Any], profile: str) -> dict[str, Any]:
    return {
        "kind": ORIGIN_KIND,
        "key": job["key"],
        "profile": profile,
        "schemaVersion": 1,
    }


def managed_key(job: dict[str, Any], profile: str) -> str | None:
    origin = job.get("origin")
    if not isinstance(origin, dict) or origin.get("kind") != ORIGIN_KIND:
        return None
    if origin.get("profile") != profile or origin.get("schemaVersion") != 1:
        raise ReconcileError("managed-origin-drift")
    key = origin.get("key")
    if not isinstance(key, str) or not KEY_RE.fullmatch(key):
        raise ReconcileError("managed-origin-key-drift")
    return key


def desired_fields(job: dict[str, Any], profile: str, api: Any | None = None) -> dict[str, Any]:
    schedule_display = job["schedule"]
    if api is not None:
        parsed = api.parse_schedule(job["schedule"])
        if not isinstance(parsed, dict) or not isinstance(parsed.get("display"), str):
            raise ReconcileError(f"native-schedule-normalization:{job['key']}")
        schedule_display = parsed["display"]
    return {
        "name": job["name"],
        "prompt": job.get("prompt", ""),
        "deliver": job["deliver"],
        "script": job.get("script"),
        "no_agent": job.get("noAgent", False),
        "model": job.get("model"),
        "provider": job.get("provider"),
        "skills": job.get("skills") or [],
        "enabled_toolsets": job.get("enabledToolsets") or None,
        "context_from": ["self"] if job.get("continuity") else None,
        "workdir": job.get("workdir"),
        "schedule_display": schedule_display,
        "origin": origin_for(job, profile),
    }


def is_current(existing: dict[str, Any], desired: dict[str, Any], profile: str, api: Any) -> bool:
    fields = desired_fields(desired, profile, api)
    for key, expected in fields.items():
        if key == "schedule_display":
            actual = existing.get("schedule_display")
        else:
            actual = existing.get(key)
        if actual != expected:
            return False
    return existing.get("enabled", True) is True and existing.get("state") != "paused"


@contextmanager
def reconcile_lock(home: Path) -> Iterator[None]:
    lock_path = home / "state" / "cc-ansible-cron-reconcile.lock"
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ReconcileError("reconcile-already-running") from exc
        yield


def native_api() -> Any:
    try:
        import cron.jobs as cron_jobs  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ReconcileError("native-cron-api-unavailable") from exc
    required = (
        "list_jobs",
        "create_job",
        "update_job",
        "remove_job",
        "resume_job",
        "parse_schedule",
    )
    if not all(callable(getattr(cron_jobs, name, None)) for name in required):
        raise ReconcileError("native-cron-api-incomplete")
    return cron_jobs


def create_native(api: Any, job: dict[str, Any], profile: str) -> dict[str, Any]:
    return api.create_job(
        prompt=job.get("prompt", ""),
        schedule=job["schedule"],
        name=job["name"],
        deliver=job["deliver"],
        origin=origin_for(job, profile),
        skills=job.get("skills") or None,
        model=job.get("model"),
        provider=job.get("provider"),
        script=job.get("script"),
        enabled_toolsets=job.get("enabledToolsets") or None,
        context_from=["self"] if job.get("continuity") else None,
        workdir=job.get("workdir"),
        no_agent=job.get("noAgent", False),
    )


def update_native(api: Any, existing: dict[str, Any], job: dict[str, Any], profile: str) -> None:
    job_id = existing.get("id")
    if not isinstance(job_id, str) or not job_id:
        raise ReconcileError(f"missing-native-job-id:{job['key']}")
    updates = desired_fields(job, profile, api)
    updates["schedule"] = job["schedule"]
    updates["enabled"] = True
    updated = api.update_job(job_id, updates)
    if updated is None:
        raise ReconcileError(f"native-job-vanished:{job['key']}")
    if updated.get("state") == "paused":
        if api.resume_job(job_id) is None:
            raise ReconcileError(f"native-resume-failed:{job['key']}")


def requested_mode(args: argparse.Namespace) -> str:
    explicit = getattr(args, "operation", None)
    if explicit in {"audit", "seed", "restore"}:
        return explicit
    if getattr(args, "seed", False):
        return "seed"
    if getattr(args, "restore", False) or getattr(args, "apply", False):
        return "restore"
    return "audit"


def reconcile(args: argparse.Namespace) -> list[dict[str, str]]:
    home = args.home.resolve(strict=True)
    scripts_root = home / "scripts"
    jobs = load_manifest(args.manifest, scripts_root, args.profile)
    requested_keys = list(getattr(args, "keys", None) or [])
    if len(requested_keys) != len(set(requested_keys)):
        raise ReconcileError("duplicate-target-key")
    manifest_keys = {job["key"] for job in jobs}
    unknown_keys = set(requested_keys) - manifest_keys
    if unknown_keys:
        raise ReconcileError(f"unknown-target-key:{sorted(unknown_keys)[0]}")
    for job in jobs:
        if not job.get("noAgent") and job.get("workdir") != str(home):
            raise ReconcileError(f"profile-workdir-required:{job['key']}")
        if job.get("noAgent") and job.get("workdir") is not None:
            raise ReconcileError(f"script-workdir-forbidden:{job['key']}")
    now = datetime.now(timezone.utc)
    desired = {
        job["key"]: job
        for job in jobs
        if job.get("expiresAt") is None or job["expiresAt"] > now
    }
    if requested_keys:
        inactive_keys = set(requested_keys) - set(desired)
        if inactive_keys:
            raise ReconcileError(f"inactive-target-key:{sorted(inactive_keys)[0]}")
        desired = {key: desired[key] for key in requested_keys}
    api = native_api()
    operation = requested_mode(args)
    mutating = operation in {"seed", "restore"}
    native = api.list_jobs(include_disabled=True)
    if not isinstance(native, list) or not all(isinstance(job, dict) for job in native):
        raise ReconcileError("invalid-native-job-list")
    by_key: dict[str, dict[str, Any]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for job in native:
        name = job.get("name")
        if not isinstance(name, str):
            raise ReconcileError("native-job-name-missing")
        by_name.setdefault(name.casefold(), []).append(job)
        key = managed_key(job, args.profile)
        if key is not None:
            if key in by_key:
                raise ReconcileError(f"duplicate-managed-key:{key}")
            by_key[key] = job

    changes: list[dict[str, str]] = []
    for key, job in desired.items():
        existing = by_key.get(key)
        if existing is None:
            collisions = by_name.get(job["name"].casefold(), [])
            if collisions:
                if operation == "seed":
                    raise ReconcileError(f"seed-name-collision:{key}")
                if not job.get("adoptExisting") or len(collisions) != 1:
                    raise ReconcileError(f"unmanaged-name-collision:{key}")
                existing = collisions[0]
                if managed_key(existing, args.profile) not in (None, key):
                    raise ReconcileError(f"managed-name-collision:{key}")
        if existing is None:
            changes.append({"key": key, "action": "create"})
            if mutating:
                create_native(api, job, args.profile)
        elif operation != "seed" and not is_current(existing, job, args.profile, api):
            changes.append({"key": key, "action": "update"})
            if operation == "restore":
                update_native(api, existing, job, args.profile)

    if operation != "seed":
        for key, existing in sorted(by_key.items()):
            if requested_keys and key not in desired:
                continue
            if key in desired:
                continue
            changes.append({"key": key, "action": "remove"})
            if operation == "restore":
                job_id = existing.get("id")
                if not isinstance(job_id, str) or not api.remove_job(job_id):
                    raise ReconcileError(f"native-remove-failed:{key}")
    return changes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument(
        "--key",
        action="append",
        dest="keys",
        default=[],
        help="Limit audit or mutation to one manifest key; repeat as needed.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--audit", action="store_const", const="audit", dest="operation")
    mode.add_argument("--seed", action="store_const", const="seed", dest="operation")
    mode.add_argument("--restore", action="store_const", const="restore", dest="operation")
    mode.add_argument(
        "--check",
        action="store_const",
        const="audit",
        dest="operation",
        help=argparse.SUPPRESS,
    )
    mode.add_argument(
        "--apply",
        action="store_const",
        const="restore",
        dest="operation",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    with reconcile_lock(args.home.resolve(strict=True)):
        changes = reconcile(args)
    print(json.dumps({"status": "ok", "changes": changes}, separators=(",", ":")))
    return 0 if args.operation in {"seed", "restore"} or not changes else 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReconcileError, OSError, ValueError) as exc:
        print(str(exc)[:300], file=sys.stderr)
        raise SystemExit(1)
