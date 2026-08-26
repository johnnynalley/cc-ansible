#!/usr/bin/env python3
"""Validate exhaustive OpenClaw-to-Hermes capability classification."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


HEARTBEATS = {"heartbeat-astra", "heartbeat-dubble", "heartbeat-rigel"}
ALLOWED_DISPOSITIONS = {
    "native",
    "native-equivalent",
    "retained-external",
    "preserved-inactive",
    "reenrollment-required",
}
REQUIRED_CAPABILITIES = {
    "identity-and-instructions",
    "self-evolution",
    "native-terminal",
    "native-file-and-code",
    "ops-repository",
    "managed-host-inspection",
    "calendar",
    "mail",
    "web",
    "browser",
    "vision",
    "image-generation",
    "tts",
    "outbound-messaging",
    "discord-native",
    "discord-openclaw-actions",
    "discord-attachments",
    "nextcloud-talk",
    "remote-dashboard",
    "device-node",
    "canvas-artifacts",
    "model-routing",
    "model-fallbacks",
    "google-auxiliary-provider",
    "copilot-provider",
    "docker-operations",
    "cron",
    "mem0",
    "lossless-context",
    "sessions-and-search",
    "durable-profile-data",
    "hardware-tracker",
    "fortnite-tracker",
    "daily-summary",
    "astra-star-delegation",
    "dubble-astra-handoff",
    "profile-backups",
    "source-archive",
}


class ParityError(RuntimeError):
    """Raised when a source capability is absent or misclassified."""


def load(
    path: Path, template_context: dict[str, Any] | None = None
) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ParityError(
            f"json-read-failed:{path.name}:errno={exc.errno}"
        ) from exc
    except UnicodeError as exc:
        raise ParityError(f"invalid-encoding:{path.name}") from exc
    if path.suffix == ".j2":
        if template_context is None:
            raise ParityError(f"template-context-missing:{path.name}")
        try:
            from jinja2 import Environment, StrictUndefined

            text = Environment(
                autoescape=False,
                undefined=StrictUndefined,
            ).from_string(text).render(**template_context)
        except (ImportError, RuntimeError, ValueError) as exc:
            raise ParityError(f"template-render-failed:{path.name}") from exc
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParityError(
            f"invalid-json:{path.name}:line={exc.lineno}:column={exc.colno}"
        ) from exc
    if not isinstance(value, dict):
        raise ParityError(f"invalid-object:{path.name}")
    return value


def source_schedule(job: dict[str, Any]) -> str:
    schedule = job.get("schedule")
    if isinstance(schedule, dict):
        kind = schedule.get("kind")
        expression = schedule.get("expr")
        milliseconds = schedule.get("everyMs")
        run_at = schedule.get("at")
    else:
        kind = job.get("schedule_kind")
        expression = job.get("schedule_expr")
        milliseconds = job.get("every_ms")
        run_at = job.get("at")
    if kind == "cron" and isinstance(expression, str) and expression:
        return expression
    if kind == "every" and isinstance(milliseconds, int) and not isinstance(
        milliseconds, bool
    ):
        if milliseconds % 3_600_000 == 0:
            return f"every {milliseconds // 3_600_000}h"
        if milliseconds % 60_000 == 0:
            return f"every {milliseconds // 60_000}m"
    if kind == "at" and isinstance(run_at, str) and run_at:
        return f"at {run_at}"
    raise ParityError("source-schedule-unsupported")


def load_source_jobs(path: Path) -> list[dict[str, Any]]:
    if path.suffix in {".sqlite", ".db"}:
        try:
            connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            with connection:
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(cron_jobs)")
                }
                required = {
                    "job_id",
                    "name",
                    "enabled",
                    "schedule_kind",
                    "schedule_expr",
                    "every_ms",
                    "at",
                    "schedule_tz",
                }
                if not required <= columns:
                    raise ParityError("source-sqlite-schema")
                rows = [
                    dict(row)
                    for row in connection.execute(
                        """
                        SELECT job_id AS id, name, enabled, schedule_kind,
                               schedule_expr, every_ms, at, schedule_tz
                          FROM cron_jobs
                        """
                    )
                ]
        except sqlite3.Error as exc:
            raise ParityError(
                f"sqlite-read-failed:{path.name}:{type(exc).__name__}"
            ) from exc
        finally:
            if "connection" in locals():
                connection.close()
    else:
        rows = load(path).get("jobs")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ParityError("source-jobs-invalid")
    enabled = [row for row in rows if row.get("enabled") in {True, 1}]
    identifiers = [row.get("id") for row in enabled]
    if not all(isinstance(value, str) and value for value in identifiers):
        raise ParityError("source-job-id-invalid")
    if len(identifiers) != len(set(identifiers)):
        raise ParityError("source-job-id-duplicate")
    return enabled


def validate(args: argparse.Namespace) -> dict[str, Any]:
    parity = load(args.contract)
    skills = load(args.skills)
    automation = load(args.automation)
    manifest_context = {
        "hermes_rigel_dedicated_discord_enabled": (
            args.rigel_delivery_mode == "dedicated"
        ),
        "hermes_automation_rigel_channel_id": "1000000000000001",
        "hermes_rigel_discord_channel_id": "1000000000000001",
        "hermes_automation_logs_channel_id": "1000000000000002",
        "hermes_automation_social_channel_id": "1000000000000003",
        "hermes_automation_owner_user_id": "1000000000000004",
        "hermes_native_update_profile_home": "/var/lib/hermes/astra/profile",
        "hermes_dubble_parent_channel_id": "1000000000000005",
        "hermes_dubble_guild_id": "1000000000000006",
    }
    astra_manifest = load(args.astra_manifest, manifest_context)
    dubble_manifest = load(args.dubble_manifest, manifest_context)
    rigel_manifest = load(args.rigel_manifest, manifest_context)

    if parity.get("schemaVersion") != 3:
        raise ParityError("contract-schema")
    source = parity.get("source")
    if not isinstance(source, dict):
        raise ParityError("contract-source")
    if source.get("root") != "/home/johnny/.openclaw":
        raise ParityError("contract-source-root")
    if source.get("completeTreeRequired") is not True:
        raise ParityError("contract-complete-tree")
    if source.get("unclassifiedOmissionAllowed") is not False:
        raise ParityError("contract-unclassified-omission")
    if source.get("cronState") != "/home/johnny/.openclaw/state/openclaw.sqlite":
        raise ParityError("contract-current-cron-state")
    if source.get("historicalCronState") != (
        "/home/johnny/.openclaw/cron/jobs.json.migrated"
    ):
        raise ParityError("contract-historical-cron-state")
    contracts = parity.get("contracts")
    if not isinstance(contracts, dict):
        raise ParityError("contract-links")
    if contracts.get("completeEvidence") != (
        "files/hermes/openclaw-evidence-contract.json"
    ):
        raise ParityError("contract-complete-evidence")
    if contracts.get("bootstrapParity") != (
        "files/hermes/bootstrap-parity-contract.json"
    ):
        raise ParityError("contract-bootstrap-parity")
    logical_profiles = parity.get("logicalProfiles")
    if not isinstance(logical_profiles, dict) or set(logical_profiles) != {
        "astra",
        "dubble",
        "rigel",
    }:
        raise ParityError("logical-profile-inventory")
    expected_delivery = {
        "astra": ("astra", "dedicated-gateway"),
        "dubble": ("dubble", "dedicated-gateway"),
        "rigel": ("rigel", "dedicated-gateway"),
    }
    target_profiles = skills.get("profiles")
    if not isinstance(target_profiles, dict):
        raise ParityError("target-profile-inventory")
    for name, row in logical_profiles.items():
        if not isinstance(row, dict) or set(row) != {
            "sourceAgentRoot",
            "targetProfile",
            "deliveryConsumer",
            "deliveryMode",
            "fullParityRequired",
            "independentAcceptanceRequired",
        }:
            raise ParityError(f"logical-profile-row:{name}")
        if row["sourceAgentRoot"] != f"/home/johnny/.openclaw/agents/{'main' if name == 'astra' else name}":
            raise ParityError(f"logical-profile-source:{name}")
        if row["targetProfile"] != name or name not in target_profiles:
            raise ParityError(f"logical-profile-target:{name}")
        if (row["deliveryConsumer"], row["deliveryMode"]) != expected_delivery[name]:
            raise ParityError(f"logical-profile-delivery:{name}")
        if row["fullParityRequired"] is not True:
            raise ParityError(f"logical-profile-parity:{name}")
        if row["independentAcceptanceRequired"] is not True:
            raise ParityError(f"logical-profile-acceptance:{name}")
    source_skills = parity.get("astraSourceSkills")
    if not isinstance(source_skills, list) or not all(
        isinstance(value, str) and value for value in source_skills
    ):
        raise ParityError("contract-skills")
    if len(source_skills) != source.get("astraSkillCount"):
        raise ParityError("source-skill-count")
    if len(source_skills) != len(set(source_skills)):
        raise ParityError("source-skill-duplicate")

    profile = skills.get("profiles", {}).get("astra", {})
    target_skills = {
        row.get("name") for row in profile.get("skills", []) if isinstance(row, dict)
    }
    missing_skills = sorted(set(source_skills) - target_skills)
    if missing_skills:
        raise ParityError(f"missing-skills:{','.join(missing_skills)}")

    capabilities = parity.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        raise ParityError("capabilities-empty")
    capability_ids = []
    dispositions: dict[str, int] = {}
    for row in capabilities:
        if not isinstance(row, dict) or set(row) != {
            "id",
            "source",
            "disposition",
            "target",
            "validation",
        }:
            raise ParityError("capability-row")
        if not all(isinstance(row[key], str) and row[key] for key in row):
            raise ParityError("capability-value")
        if row["disposition"] not in ALLOWED_DISPOSITIONS:
            raise ParityError(f"capability-disposition:{row['id']}")
        capability_ids.append(row["id"])
        dispositions[row["disposition"]] = dispositions.get(row["disposition"], 0) + 1
    if len(capability_ids) != len(set(capability_ids)):
        raise ParityError("capability-duplicate")
    if set(capability_ids) != REQUIRED_CAPABILITIES:
        missing = sorted(REQUIRED_CAPABILITIES - set(capability_ids))
        extra = sorted(set(capability_ids) - REQUIRED_CAPABILITIES)
        raise ParityError(f"capability-inventory:missing={missing}:extra={extra}")

    expected_source_counts = {
        "pairedControlClients": 4,
        "pairedCliOperators": 1,
        "pairedIosNodes": 1,
        "nextcloudTalkBindings": 3,
        "observedNextcloudTalkSessions": 0,
    }
    for key, expected in expected_source_counts.items():
        if source.get(key) != expected:
            raise ParityError(f"source-capability-count:{key}")

    if automation.get("schemaVersion") != 3:
        raise ParityError("automation-schema")
    lanes = automation.get("lanes")
    if not isinstance(lanes, dict):
        raise ParityError("automation-lanes")
    historical_lanes = automation.get("historicalLanes")
    if not isinstance(historical_lanes, dict):
        raise ParityError("automation-historical-lanes")
    expected_total = source.get("enabledCronCount", 0) + source.get(
        "logicalHeartbeatCount", 0
    )
    if len(lanes) != expected_total or set(lanes) & HEARTBEATS != HEARTBEATS:
        raise ParityError("automation-lane-count")
    if len(historical_lanes) != source.get("historicalOnlyCronCount"):
        raise ParityError("automation-historical-lane-count")
    if set(lanes) & set(historical_lanes):
        raise ParityError("automation-current-historical-overlap")
    automation_source = automation.get("source")
    if not isinstance(automation_source, dict):
        raise ParityError("automation-source")
    expected_source = {
        "cronState": source.get("cronState"),
        "historicalCronState": source.get("historicalCronState"),
        "currentEnabledCronRows": source.get("enabledCronCount"),
        "historicalEnabledCronRows": source.get("historicalEnabledCronCount"),
        "sharedCronRows": source.get("sharedCronCount"),
        "historicalOnlyCronRows": source.get("historicalOnlyCronCount"),
        "logicalHeartbeats": source.get("logicalHeartbeatCount"),
        "totalActiveReconciledLanes": expected_total,
        "totalHistoricalReconciledLanes": source.get("historicalOnlyCronCount"),
    }
    for key, expected in expected_source.items():
        if automation_source.get(key) != expected:
            raise ParityError(f"automation-source-count:{key}")

    manifests = (astra_manifest, dubble_manifest, rigel_manifest)
    jobs: list[dict[str, Any]] = []
    for manifest in manifests:
        if manifest.get("schemaVersion") != 1 or not isinstance(
            manifest.get("jobs"), list
        ):
            raise ParityError("manifest-schema")
        jobs.extend(manifest["jobs"])
    names = {job.get("name") for job in jobs if isinstance(job, dict)}
    if len(names) != len(jobs):
        raise ParityError("manifest-name-duplicate")
    production = automation.get("production", {})
    expected_astra_jobs = production.get(
        "astraDedicatedNativeCronJobs"
        if args.rigel_delivery_mode == "dedicated"
        else "astraFallbackNativeCronJobs"
    )
    if len(astra_manifest["jobs"]) != expected_astra_jobs:
        raise ParityError("astra-job-count")
    if len(dubble_manifest["jobs"]) != production.get("dubbleNativeCronJobs"):
        raise ParityError("dubble-job-count")
    expected_rigel_jobs = (
        production.get("rigelNativeCronJobs")
        if args.rigel_delivery_mode == "dedicated"
        else 0
    )
    if len(rigel_manifest["jobs"]) != expected_rigel_jobs:
        raise ParityError("rigel-job-count")
    if len(jobs) != production.get("nativeCronJobs"):
        raise ParityError("native-job-count")
    for job in jobs:
        if not isinstance(job, dict):
            raise ParityError("manifest-job-invalid")
        if job.get("noAgent"):
            if job.get("workdir") is not None:
                raise ParityError(f"script-workdir-present:{job.get('name')}")
        elif not isinstance(job.get("workdir"), str) or not job.get("workdir"):
            raise ParityError(f"agent-workdir-missing:{job.get('name')}")
    daily_jobs = [job for job in astra_manifest["jobs"] if job.get("key") == "daily-summary"]
    if len(daily_jobs) != 1:
        raise ParityError("daily-summary-job-missing")
    daily = daily_jobs[0]
    daily_delivery = daily.get("deliver")
    if (
        not isinstance(daily_delivery, str)
        or not daily_delivery.startswith("discord:")
        or not daily_delivery.removeprefix("discord:")
        or daily.get("continuity") is not True
        or daily.get("skills") != ["daily-summary-thread"]
        or not {"terminal", "file", "discord", "discord_parity"}
        <= set(daily.get("enabledToolsets") or [])
    ):
        raise ParityError("daily-summary-continuity-contract")

    for lane_id, row in lanes.items():
        if not isinstance(row, dict) or not all(
            isinstance(row.get(key), str) and row.get(key)
            for key in ("name", "schedule", "disposition", "target")
        ):
            raise ParityError(f"lane-invalid:{lane_id}")
        disposition = row["disposition"]
        if disposition not in {"replaced", "collapsed", "native-equivalent"}:
            raise ParityError(f"disposition-invalid:{lane_id}")
        if disposition in {"replaced", "collapsed"} and row["target"] not in names:
            raise ParityError(f"target-job-missing:{lane_id}")

    for lane_id, row in historical_lanes.items():
        if not isinstance(row, dict) or not all(
            isinstance(row.get(key), str) and row.get(key)
            for key in (
                "name",
                "schedule",
                "disposition",
                "runtimeDisposition",
                "target",
            )
        ):
            raise ParityError(f"historical-lane-invalid:{lane_id}")
        if row["disposition"] != "preserved-historical":
            raise ParityError(f"historical-disposition-invalid:{lane_id}")
        if row["runtimeDisposition"] != "preserved-inactive":
            raise ParityError(f"historical-runtime-disposition-invalid:{lane_id}")
        if row["target"] in names:
            raise ParityError(f"historical-target-reactivated:{lane_id}")
        if not row["target"].startswith("legacy-openclaw/"):
            raise ParityError(f"historical-evidence-target-missing:{lane_id}")

    dubble = dubble_manifest["jobs"]
    if any("terminal" in job.get("enabledToolsets", []) for job in dubble):
        raise ParityError("dubble-terminal-enabled")
    if not any("astra_handoff" in job.get("enabledToolsets", []) for job in dubble):
        raise ParityError("dubble-handoff-missing")

    if args.source_jobs is not None:
        enabled = load_source_jobs(args.source_jobs)
        expected_ids = set(lanes) - HEARTBEATS
        actual_ids = {job.get("id") for job in enabled}
        if actual_ids != expected_ids:
            raise ParityError("source-job-id-drift")
        by_id = {job["id"]: job for job in enabled}
        for lane_id in expected_ids:
            lane = lanes[lane_id]
            source_job = by_id[lane_id]
            if source_job.get("name") != lane["name"]:
                raise ParityError(f"source-job-name-drift:{lane_id}")
            if source_schedule(source_job) != lane["schedule"]:
                raise ParityError(f"source-job-schedule-drift:{lane_id}")

        historical_path = getattr(args, "historical_source_jobs", None)
        if historical_path is not None:
            historical = load_source_jobs(historical_path)
            historical_ids = {job["id"] for job in historical}
            historical_only_ids = historical_ids - actual_ids
            shared_ids = historical_ids & actual_ids
            if historical_only_ids != set(historical_lanes):
                raise ParityError("historical-source-job-id-drift")
            if len(historical) != source.get("historicalEnabledCronCount"):
                raise ParityError("historical-source-job-count-drift")
            if len(shared_ids) != source.get("sharedCronCount"):
                raise ParityError("shared-source-job-count-drift")
            if len(historical_only_ids) != source.get("historicalOnlyCronCount"):
                raise ParityError("historical-only-job-count-drift")
            historical_by_id = {job["id"]: job for job in historical}
            for lane_id in historical_only_ids:
                lane = historical_lanes[lane_id]
                source_job = historical_by_id[lane_id]
                if source_job.get("name") != lane["name"]:
                    raise ParityError(f"historical-job-name-drift:{lane_id}")
                if source_schedule(source_job) != lane["schedule"]:
                    raise ParityError(f"historical-job-schedule-drift:{lane_id}")

    return {
        "schemaVersion": 3,
        "status": "ok",
        "sourceSkills": len(source_skills),
        "capabilities": len(capabilities),
        "sourceLanes": len(lanes),
        "historicalLanes": len(historical_lanes),
        "nativeJobs": len(jobs),
        "dispositions": dict(sorted(dispositions.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--skills", type=Path, required=True)
    parser.add_argument("--automation", type=Path, required=True)
    parser.add_argument("--astra-manifest", type=Path, required=True)
    parser.add_argument("--dubble-manifest", type=Path, required=True)
    parser.add_argument("--rigel-manifest", type=Path, required=True)
    parser.add_argument(
        "--rigel-delivery-mode",
        choices=("fallback", "dedicated"),
        required=True,
    )
    parser.add_argument("--source-jobs", type=Path)
    parser.add_argument("--historical-source-jobs", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(validate(args), sort_keys=True))
        return 0
    except ParityError as exc:
        print(f"Hermes OpenClaw parity validation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
