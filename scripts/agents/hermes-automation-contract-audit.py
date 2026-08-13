#!/usr/bin/env python3
"""Validate the credential-free Hermes automation and Health contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

EXPECTED_AUTHORITY = {
    "liveChangeAuthorized": False,
    "schedulerActivationAuthorized": False,
    "openclawStopAuthorized": False,
    "healthReceiverChangeAuthorized": False,
    "siriRelayCreationAuthorized": False,
    "messageDeliveryAuthorized": False,
    "sourceMutationAuthorized": False,
    "sourceCleanupAuthorized": False,
}
EXPECTED_INVARIANTS = {
    "freshSourceInventoryRequiredAtCutover": True,
    "unknownSourceScheduleBlocksCutover": True,
    "oneActiveSchedulerPerLane": True,
    "legacyPromptsCopiedVerbatim": False,
    "commandJobsRunInsideMessagingGateway": False,
    "agentJobsCreateNestedCronJobs": False,
    "agentJobsDeliverDirectlyToDiscord": False,
    "agentJobsWriteLocalStructuredProposals": True,
    "deterministicJobsUseNoAgentMode": True,
    "deterministicIdleStdout": "empty",
    "deterministicJobsUseModelTokens": False,
    "pendingOneShotsRebuiltFromReviewedPlans": True,
    "completedOneShotsReplayed": False,
    "healthReceiverExternallyOwned": True,
    "healthRawDataAvailableToModels": False,
    "healthAggregateOnly": True,
    "siriRelayRetired": True,
}
EXPECTED_SOURCE_PINS = {
    "stateMigration": "files/hermes/openclaw-state-migration-contract.json",
    "discordCutover": "files/hermes/discord-cutover-contract.json",
    "rigelJob": "files/hermes/jobs/rigel-academic-alerts.json",
    "healthReceiverPlaybook": "playbooks/agents/openclaw-health-receiver.yml",
    "controlPlaneInventory": "scripts/agents/openclaw-control-plane-inventory.py",
}
EXPECTED_SCHEDULE_IDS = {
    "cron-self-evolution-maintenance",
    "cron-reddit-hdd-deal-watch",
    "cron-release-advisor",
    "cron-archive-astra-logs",
    "cron-self-evolution-daily",
    "cron-warframe-drops-sync",
    "cron-daily-summary-updates",
    "cron-fortnite-calendar-sync",
    "cron-daily-summary-media",
    "cron-fortnite-progress",
    "cron-daily-summary-personal",
    "cron-daily-summary-scratch",
    "cron-daily-summary-compose",
    "cron-daily-summary-watchdog",
    "cron-session-janitor-scorecard",
    "cron-warframe-reminder-prime-time-493",
    "cron-warframe-reminder-prime-time-raid",
    "cron-stw-0010",
    "cron-stw-0035",
    "cron-stw-0100",
    "cron-nightly-memory-summary",
    "cron-nightly-workspace-snapshot",
    "cron-warframe-reminder-lunethae",
    "cron-weekly-memory-promotion",
    "cron-weekly-social-seeds",
    "cron-warframe-reminder-snootydeath",
    "cron-ops-repo-drift",
    "cron-session-janitor-stale",
    "heartbeat-astra",
    "heartbeat-dubble",
    "heartbeat-rigel",
}
EXPECTED_SUMMARY = {
    "cronJobs": 28,
    "heartbeatSchedules": 3,
    "totalSchedules": 31,
    "cronPayloadKinds": {"agentTurn": 18, "command": 10},
    "dispositions": {
        "agent-backed": 16,
        "external": 10,
        "deterministic-script-only": 5,
        "retire": 0,
    },
}
EXPECTED_HEALTH = {
    "disposition": "external",
    "currentState": "legacy-user-service-active",
    "cutoverState": "dedicated-system-service-active",
    "targetPlaybook": "playbooks/agents/openclaw-health-receiver.yml",
    "continuity": "keep-running-through-hermes-cutover",
    "rawDatabaseOwner": "health-receiver-only",
    "modelAccess": "aggregate-report-only",
    "separateAttendedCutover": True,
}
EXPECTED_SIRI = {
    "disposition": "retire",
    "currentState": "no-active-unit",
    "targetState": "absent",
    "recreationAuthorized": False,
}
EXPECTED_PRECONDITIONS = {
    "fresh-redacted-source-inventory",
    "every-source-lane-reconciled",
    "all-target-schedules-disabled",
    "automation-worker-has-no-messaging-token",
    "external-publisher-scope-proven",
    "health-receiver-continuity-proven",
    "rollback-reviewed",
}
EXPECTED_HANDOFF_ORDER = [
    "wait-for-openclaw-schedules-and-heartbeats-idle",
    "stop-openclaw-scheduler-with-gateway-handoff",
    "prove-no-openclaw-scheduled-worker-remains",
    "activate-external-systemd-lanes",
    "activate-hermes-automation-lanes-disabled-to-enabled",
    "activate-rigel-deterministic-lane",
    "prove-single-run-and-single-delivery-per-lane",
    "prove-idle-lanes-produce-no-discord-output",
]
EXPECTED_ROLLBACK_ORDER = [
    "pause-all-hermes-and-external-target-schedules",
    "wait-for-target-workers-idle",
    "prove-target-scheduled-workers-absent",
    "restore-openclaw-gateway-and-scheduler",
    "reconcile-pending-one-shots-without-replay",
    "prove-one-source-scheduler-per-lane",
    "prove-health-receiver-still-active",
]
EXPECTED_CASES = {
    "unknown-source-job",
    "stable-source-missing",
    "expired-one-shot",
    "new-one-shot",
    "command-gateway-escape",
    "agent-direct-discord",
    "recursive-schedule-creation",
    "deterministic-idle",
    "agent-noop",
    "scheduler-overlap",
    "health-continuity",
    "health-data-containment",
    "siri-remains-retired",
    "rollback-order",
}
ROW_KEYS = {"id", "source", "disposition", "target"}
SOURCE_KEYS = {
    "type",
    "name",
    "payload",
    "enabled",
    "deleteAfterRun",
    "schedule",
}
SCHEDULE_KEYS = {"kind", "value", "timezone"}
TARGET_KEYS = {"owner", "mode", "name", "output", "activation"}
SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,95}$")
SAFE_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")


class AutomationContractError(RuntimeError):
    """Raised when automation parity or isolation is incomplete."""


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise AutomationContractError(f"{label} must be a regular file")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AutomationContractError(f"{label} is unavailable or invalid") from exc
    if not isinstance(payload, dict):
        raise AutomationContractError(f"{label} must be a JSON object")
    return payload


def _validate_source_pins(pins: Any, repository_root: Path) -> int:
    if not isinstance(pins, dict) or set(pins) != set(EXPECTED_SOURCE_PINS):
        raise AutomationContractError("automation source pin set is incomplete")
    for name, expected_path in EXPECTED_SOURCE_PINS.items():
        row = pins[name]
        if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
            raise AutomationContractError(f"invalid automation source pin: {name}")
        if row["path"] != expected_path:
            raise AutomationContractError(f"noncanonical automation source: {name}")
        relative = PurePosixPath(row["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise AutomationContractError(f"unsafe automation source path: {name}")
        expected_hash = row["sha256"]
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise AutomationContractError(f"invalid automation source hash: {name}")
        try:
            actual_hash = hashlib.sha256(
                (repository_root / relative).read_bytes()
            ).hexdigest()
        except OSError as exc:
            raise AutomationContractError(
                f"automation source unavailable: {name}"
            ) from exc
        if actual_hash != expected_hash:
            raise AutomationContractError(f"automation source drift: {name}")
    return len(pins)


def _validate_source_schedule(row: dict[str, Any]) -> None:
    source = row["source"]
    schedule = source["schedule"]
    source_type = source["type"]
    kind = schedule["kind"]
    value = schedule["value"]
    timezone = schedule["timezone"]
    if source_type not in {"cron", "heartbeat"}:
        raise AutomationContractError("unknown automation source type")
    if source_type == "heartbeat":
        if source["payload"] != "heartbeat" or (kind, value, timezone) != (
            "every",
            "30m",
            "America/Chicago",
        ):
            raise AutomationContractError("heartbeat source contract drift")
    elif source["payload"] not in {"agentTurn", "command"}:
        raise AutomationContractError("cron payload contract drift")
    if kind == "every":
        if not isinstance(value, str) or not value:
            raise AutomationContractError("invalid interval schedule")
        if source_type == "cron" and not value.isdigit():
            raise AutomationContractError("cron interval must use milliseconds")
    elif kind == "cron":
        if source_type != "cron" or not isinstance(value, str) or not value.strip():
            raise AutomationContractError("invalid cron schedule")
        if timezone not in {"America/Chicago", "UTC"}:
            raise AutomationContractError("invalid cron timezone")
    elif kind == "at":
        if (
            source_type != "cron"
            or not isinstance(value, str)
            or not SAFE_AT_RE.fullmatch(value)
            or timezone is not None
        ):
            raise AutomationContractError("invalid one-shot schedule")
    else:
        raise AutomationContractError("unknown schedule kind")
    expected_ephemeral = kind == "at"
    if source["deleteAfterRun"] is not expected_ephemeral:
        raise AutomationContractError("one-shot lifecycle drift")


def _validate_target(row: dict[str, Any]) -> None:
    source = row["source"]
    target = row["target"]
    disposition = row["disposition"]
    if target["activation"] != "disabled-until-cutover":
        raise AutomationContractError("target schedule activated prematurely")
    if disposition == "external":
        if source["payload"] != "command" or not target["owner"].startswith("systemd:"):
            raise AutomationContractError("external command ownership drift")
        if (target["mode"], target["output"]) != (
            "systemd-service-timer",
            "local-artifact-or-proposal",
        ):
            raise AutomationContractError("external command boundary drift")
    elif disposition == "agent-backed":
        if target["owner"] != "hermes-automation":
            raise AutomationContractError("agent schedule owner drift")
        if (target["mode"], target["output"]) != (
            "agent-plan",
            "local-structured-proposal",
        ):
            raise AutomationContractError("agent delivery boundary drift")
    elif disposition == "deterministic-script-only":
        if target["owner"] not in {"hermes-automation", "hermes-rigel"}:
            raise AutomationContractError("deterministic schedule owner drift")
        if (target["mode"], target["output"]) != (
            "no-agent-script",
            "local-event-queue",
        ):
            raise AutomationContractError("deterministic delivery boundary drift")
    elif disposition == "retire":
        raise AutomationContractError("no current schedule is approved for retirement")
    else:
        raise AutomationContractError("unknown schedule disposition")


def _validate_schedules(rows: Any) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    if not isinstance(rows, list) or len(rows) != 31:
        raise AutomationContractError("exactly 31 source schedules are required")
    ids: set[str] = set()
    source_names: set[str] = set()
    target_names: set[str] = set()
    disposition_counts: Counter[str] = Counter()
    source_type_counts: Counter[str] = Counter()
    cron_payload_counts: Counter[str] = Counter()
    cron_rows: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != ROW_KEYS:
            raise AutomationContractError("automation row schema drift")
        source = row["source"]
        target = row["target"]
        if not isinstance(source, dict) or set(source) != SOURCE_KEYS:
            raise AutomationContractError("automation source schema drift")
        if (
            not isinstance(source["schedule"], dict)
            or set(source["schedule"]) != SCHEDULE_KEYS
        ):
            raise AutomationContractError("automation schedule schema drift")
        if not isinstance(target, dict) or set(target) != TARGET_KEYS:
            raise AutomationContractError("automation target schema drift")
        identifier = row["id"]
        if not isinstance(identifier, str) or not SAFE_ID_RE.fullmatch(identifier):
            raise AutomationContractError("invalid automation identifier")
        if identifier in ids:
            raise AutomationContractError("duplicate automation identifier")
        ids.add(identifier)
        source_name = source["name"]
        target_name = target["name"]
        if not isinstance(source_name, str) or not source_name.strip():
            raise AutomationContractError("empty automation source name")
        if not isinstance(target_name, str) or not SAFE_ID_RE.fullmatch(target_name):
            raise AutomationContractError("invalid automation target name")
        if source_name in source_names or target_name in target_names:
            raise AutomationContractError("duplicate automation source or target")
        source_names.add(source_name)
        target_names.add(target_name)
        if source["enabled"] is not True:
            raise AutomationContractError("source schedule state drift")
        _validate_source_schedule(row)
        _validate_target(row)
        disposition_counts[row["disposition"]] += 1
        source_type_counts[source["type"]] += 1
        if source["type"] == "cron":
            cron_payload_counts[source["payload"]] += 1
            cron_rows[source_name] = row
    if ids != EXPECTED_SCHEDULE_IDS:
        raise AutomationContractError("automation source set drift")
    counts = {
        "cronJobs": source_type_counts["cron"],
        "heartbeatSchedules": source_type_counts["heartbeat"],
        "totalSchedules": len(rows),
        "agent-backed": disposition_counts["agent-backed"],
        "external": disposition_counts["external"],
        "deterministic-script-only": disposition_counts["deterministic-script-only"],
        "retire": disposition_counts["retire"],
        "agentTurn": cron_payload_counts["agentTurn"],
        "command": cron_payload_counts["command"],
    }
    return cron_rows, counts


def _validate_handoff(contract: dict[str, Any]) -> None:
    handoff = contract.get("handoff")
    if not isinstance(handoff, dict):
        raise AutomationContractError("automation handoff contract is required")
    if set(handoff.get("preconditions", [])) != EXPECTED_PRECONDITIONS:
        raise AutomationContractError("automation handoff preconditions drift")
    if handoff.get("order") != EXPECTED_HANDOFF_ORDER:
        raise AutomationContractError("automation handoff order drift")
    if handoff.get("healthReceiverDisposition") != "keep-running":
        raise AutomationContractError("Health receiver continuity drift")
    if handoff.get("sourceHistoryReplay") is not False:
        raise AutomationContractError("source history replay is forbidden")
    if handoff.get("completedOneShotReplay") is not False:
        raise AutomationContractError("completed one-shot replay is forbidden")
    rollback = contract.get("rollback")
    if (
        not isinstance(rollback, dict)
        or rollback.get("order") != EXPECTED_ROLLBACK_ORDER
    ):
        raise AutomationContractError("automation rollback order drift")
    if rollback.get("healthReceiverDisposition") != "keep-running":
        raise AutomationContractError("rollback cannot stop the Health receiver")
    if rollback.get("siriRelayDisposition") != "remain-absent":
        raise AutomationContractError("rollback cannot restore the Siri relay")


def _validate_regressions(path: Path) -> int:
    payload = _load_json(path, "automation regressions")
    if payload.get("schemaVersion") != 1 or payload.get("mode") != "promotion-cases":
        raise AutomationContractError("automation regression header drift")
    rows = payload.get("cases")
    if not isinstance(rows, list):
        raise AutomationContractError("automation regression cases are required")
    identifiers: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "id",
            "risk",
            "required",
            "forbidden",
        }:
            raise AutomationContractError("automation regression schema drift")
        identifiers.append(row["id"])
        if row["risk"] != "blocking":
            raise AutomationContractError("every automation regression must block")
        if not all(
            isinstance(row[key], str) and row[key].strip()
            for key in ("required", "forbidden")
        ):
            raise AutomationContractError("empty automation regression field")
    if len(identifiers) != len(set(identifiers)) or set(identifiers) != EXPECTED_CASES:
        raise AutomationContractError("automation regression case set drift")
    return len(rows)


def _inventory_schedule_matches(
    expected: dict[str, Any], actual: dict[str, Any]
) -> bool:
    source_schedule = expected["source"]["schedule"]
    if not isinstance(actual, dict) or set(actual) != {
        "kind",
        "expression",
        "timezone",
        "everyMs",
        "at",
    }:
        return False
    kind = source_schedule["kind"]
    if actual["kind"] != kind or actual["timezone"] != source_schedule["timezone"]:
        return False
    if kind == "every":
        return (
            actual["everyMs"] == int(source_schedule["value"])
            and actual["expression"] is None
            and actual["at"] is None
        )
    if kind == "cron":
        return (
            actual["expression"] == source_schedule["value"]
            and actual["everyMs"] is None
            and actual["at"] is None
        )
    return (
        actual["at"] == source_schedule["value"]
        and actual["expression"] is None
        and actual["everyMs"] is None
    )


def _validate_source_inventory(
    inventory_path: Path, expected_rows: dict[str, dict[str, Any]]
) -> int:
    inventory = _load_json(inventory_path, "source automation inventory")
    if (
        inventory.get("schemaVersion") != 1
        or inventory.get("databaseQuickCheck") != "ok"
    ):
        raise AutomationContractError("source automation inventory is unhealthy")
    rows = inventory.get("jobs")
    summary = inventory.get("summary")
    if not isinstance(rows, list) or not isinstance(summary, dict):
        raise AutomationContractError("source automation inventory is incomplete")
    actual_rows: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise AutomationContractError("source automation inventory row is invalid")
        if row["name"] in actual_rows:
            raise AutomationContractError("duplicate source automation inventory row")
        actual_rows[row["name"]] = row
    if summary.get("jobCount") != len(rows) or summary.get("enabledCount") != len(rows):
        raise AutomationContractError("source automation inventory counts drift")
    unknown = set(actual_rows) - set(expected_rows)
    if unknown:
        raise AutomationContractError("unknown source schedule blocks cutover")
    required = {
        name
        for name, row in expected_rows.items()
        if row["source"]["deleteAfterRun"] is False
    }
    if required - set(actual_rows):
        raise AutomationContractError("stable source schedule is missing")
    for name, actual in actual_rows.items():
        expected = expected_rows[name]
        source = expected["source"]
        payload = actual.get("payload")
        if (
            actual.get("enabled") is not True
            or actual.get("deleteAfterRun") is not source["deleteAfterRun"]
            or not isinstance(payload, dict)
            or payload.get("kind") != source["payload"]
            or not _inventory_schedule_matches(expected, actual.get("schedule"))
        ):
            raise AutomationContractError("source schedule metadata drift")
    return len(rows)


def audit_contract(
    contract_path: Path,
    repository_root: Path,
    source_inventory_path: Path | None = None,
) -> dict[str, Any]:
    contract = _load_json(contract_path, "automation contract")
    if contract.get("schemaVersion") != 1 or contract.get("mode") != "design-only":
        raise AutomationContractError("automation contract header drift")
    if contract.get("authority") != EXPECTED_AUTHORITY:
        raise AutomationContractError("automation authority drift")
    if contract.get("invariants") != EXPECTED_INVARIANTS:
        raise AutomationContractError("automation invariants drift")
    if contract.get("sourceSummary") != EXPECTED_SUMMARY:
        raise AutomationContractError("automation source summary drift")
    pin_count = _validate_source_pins(contract.get("sourcePins"), repository_root)
    cron_rows, counts = _validate_schedules(contract.get("schedules"))
    expected_counts = {
        "cronJobs": 28,
        "heartbeatSchedules": 3,
        "totalSchedules": 31,
        "agent-backed": 16,
        "external": 10,
        "deterministic-script-only": 5,
        "retire": 0,
        "agentTurn": 18,
        "command": 10,
    }
    if counts != expected_counts:
        raise AutomationContractError("automation schedule counts drift")
    integrations = contract.get("integrations")
    if not isinstance(integrations, dict) or set(integrations) != {
        "healthReceiver",
        "siriRelay",
    }:
        raise AutomationContractError("automation integration set drift")
    if integrations["healthReceiver"] != EXPECTED_HEALTH:
        raise AutomationContractError("Health receiver contract drift")
    if integrations["siriRelay"] != EXPECTED_SIRI:
        raise AutomationContractError("Siri retirement contract drift")
    _validate_handoff(contract)
    promotion_path = contract.get("promotionCases")
    if promotion_path != "files/hermes/automation-regressions.json":
        raise AutomationContractError("automation promotion path drift")
    case_count = _validate_regressions(repository_root / promotion_path)
    compared = source_inventory_path is not None
    present_jobs = (
        _validate_source_inventory(source_inventory_path, cron_rows)
        if source_inventory_path is not None
        else None
    )
    return {
        "schemaVersion": 1,
        "status": "ok",
        "mode": "design-only",
        "sourcePins": pin_count,
        "schedules": counts["totalSchedules"],
        "cronJobs": counts["cronJobs"],
        "heartbeats": counts["heartbeatSchedules"],
        "promotionCases": case_count,
        "sourceInventoryCompared": compared,
        "presentSourceJobs": present_jobs,
        "liveChangeAuthorized": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    parser.add_argument(
        "--repository-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--source-inventory", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = audit_contract(
            args.contract,
            args.repository_root.resolve(),
            args.source_inventory,
        )
    except AutomationContractError as exc:
        print(json.dumps({"schemaVersion": 1, "status": "error", "reason": str(exc)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
