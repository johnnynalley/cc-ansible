#!/usr/bin/env python3
"""Validate the credential-free Hermes Discord cutover contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Any

EXPECTED_AUTHORITY = {
    "liveChangeAuthorized": False,
    "credentialEnrollmentAuthorized": False,
    "gatewayStartAuthorized": False,
    "schedulerActivationAuthorized": False,
    "openclawStopAuthorized": False,
    "openclawCleanupAuthorized": False,
    "messageReplayAuthorized": False,
    "shadowDiscordCredentialAuthorized": False,
}
EXPECTED_INVARIANTS = {
    "oneActiveConsumerPerDiscordIdentity": True,
    "threeLogicalHermesProfiles": True,
    "threeDistinctDiscordApplications": True,
    "threeDistinctDiscordBotTokens": True,
    "rigelUsesDedicatedDeliveryConsumer": True,
    "astraRigelFallbackRemovedOnlyAfterThirdIdentityProof": True,
    "nativeHermesTokenLocksRequired": True,
    "noSharedProfileHome": True,
    "noSharedCredentialFile": True,
    "rootOwnedCredentialFiles": True,
    "credentialFilesAgentWritable": False,
    "credentialFilesServiceReadable": True,
    "credentialValuesInRepository": False,
    "credentialValuesInCommandLine": False,
    "credentialValuesInLogsOrEvidence": False,
    "allowAllUsers": False,
    "allowBots": "none",
    "unknownDirectMessages": "ignore",
    "historyBackfill": False,
    "missedMessageBackfill": False,
    "groupSessionsPerUser": True,
    "threadRequireMention": True,
    "toolProgress": "off",
    "reasoningVisible": False,
    "controlTokensVisible": False,
}
EXPECTED_PROFILES = {
    "astra": {
        "deliveryOwner": "astra",
        "authorizationMode": "user-and-channel",
        "proactiveDelivery": True,
        "requiresAllowedUsers": True,
        "requiresAllowedRoles": False,
        "requiresHomeChannel": True,
        "hasConsumer": True,
    },
    "dubble": {
        "deliveryOwner": "dubble",
        "authorizationMode": "guild-everyone-role-plus-channel-scope-plus-admin-user",
        "proactiveDelivery": False,
        "requiresAllowedUsers": False,
        "requiresAllowedRoles": True,
        "requiresHomeChannel": False,
        "hasConsumer": True,
    },
    "rigel": {
        "deliveryOwner": "rigel",
        "authorizationMode": "user-and-channel",
        "proactiveDelivery": True,
        "requiresAllowedUsers": True,
        "requiresAllowedRoles": False,
        "requiresHomeChannel": True,
        "hasConsumer": True,
    },
}
EXPECTED_PROFILE_KEYS = {
    "name",
    "deliveryOwner",
    "service",
    "home",
    "managedDir",
    "credentialFile",
    "applicationIdentityRef",
    "botTokenRef",
    "authorizationMode",
    "allowedUsersRef",
    "allowedRolesRef",
    "allowedChannelsRef",
    "freeResponseChannelsRef",
    "homeChannelRef",
    "adminUsersRef",
    "regularUserCommands",
    "proactiveDelivery",
}
EXPECTED_PRECONDITIONS = {
    "complete-openclaw-backup",
    "complete-hermes-profile-backup",
    "openclaw-sessions-idle",
    "openclaw-schedules-idle",
    "hermes-regressions-passed",
    "private-discord-enrollment-reviewed",
    "dedicated-rigel-identity-and-channel-access-proved",
    "rollback-command-reviewed",
}
EXPECTED_SOURCE_STOP = [
    "stop-and-disable-openclaw-user-gateway",
    "stop-and-disable-openclaw-isolated-gateway",
    "stop-and-disable-openclaw-isolated-codex",
    "prove-openclaw-processes-and-discord-consumers-absent",
    "run-source-delivery-cutover-audit",
    "archive-source-delivery-evidence-without-replay",
]
EXPECTED_TARGET_START = [
    "start-astra-delivery-gateway",
    "prove-astra-routing-and-single-delivery",
    "start-dubble-delivery-gateway",
    "prove-dubble-routing-and-single-delivery",
    "start-rigel-delivery-gateway",
    "prove-rigel-routing-and-single-delivery",
    "enable-reviewed-hermes-schedules",
    "prove-rigel-idle-silence",
]
EXPECTED_ROLLBACK = [
    "pause-hermes-schedules",
    "wait-for-hermes-sessions-idle",
    "stop-and-disable-all-hermes-gateways",
    "prove-hermes-processes-and-discord-consumers-absent",
    "quarantine-hermes-discord-credential-files",
    "restore-openclaw-state-if-required",
    "start-openclaw-user-gateway",
    "prove-one-openclaw-delivery",
    "prove-no-hermes-delivery",
    "restore-openclaw-schedule-state",
]
EXPECTED_CASES = {
    "authorized-profile-route",
    "unauthorized-user",
    "unauthorized-channel",
    "unknown-direct-message",
    "duplicate-token-or-identity",
    "bot-loop-prevention",
    "restart-no-backfill",
    "attachment-containment",
    "openclaw-queue-drain",
    "cutover-gap-message",
    "rollback-single-route",
    "rigel-idle-after-cutover",
}


class DiscordCutoverAuditError(RuntimeError):
    """Raised when the Discord handoff contract is incomplete or unsafe."""


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise DiscordCutoverAuditError(f"{label} must be a regular file")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiscordCutoverAuditError(f"{label} is unavailable or invalid") from exc
    if not isinstance(payload, dict):
        raise DiscordCutoverAuditError(f"{label} must be a JSON object")
    return payload


def _private_ref(value: Any, label: str, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, str) or not value.startswith("private-enrollment:"):
        raise DiscordCutoverAuditError(f"{label} must be a private enrollment ref")


def _role_ref(value: Any, label: str, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, str) or not value.startswith(
        ("private-enrollment:", "policy:")
    ):
        raise DiscordCutoverAuditError(
            f"{label} must be a private enrollment or root policy ref"
        )


def _validate_source_pins(pins: Any, repository_root: Path) -> dict[str, str]:
    expected = {
        "shadowTarget": "files/hermes/shadow-target.json",
        "stateMigration": "files/hermes/openclaw-state-migration-contract.json",
        "sourceDeliveryAudit": "scripts/agents/openclaw-delivery-cutover-audit.py",
    }
    if not isinstance(pins, dict) or set(pins) != set(expected):
        raise DiscordCutoverAuditError("source pin set is incomplete")
    results: dict[str, str] = {}
    for name, canonical_path in expected.items():
        row = pins[name]
        if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
            raise DiscordCutoverAuditError(f"invalid source pin: {name}")
        if row["path"] != canonical_path:
            raise DiscordCutoverAuditError(f"noncanonical source pin: {name}")
        path = PurePosixPath(row["path"])
        if path.is_absolute() or ".." in path.parts:
            raise DiscordCutoverAuditError(f"unsafe source pin path: {name}")
        expected_hash = row["sha256"]
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise DiscordCutoverAuditError(f"invalid source pin hash: {name}")
        try:
            actual_hash = hashlib.sha256(
                (repository_root / path).read_bytes()
            ).hexdigest()
        except OSError as exc:
            raise DiscordCutoverAuditError(f"source pin unavailable: {name}") from exc
        if actual_hash != expected_hash:
            raise DiscordCutoverAuditError(f"source pin drift: {name}")
        results[name] = actual_hash
    return results


def _validate_profiles(rows: Any) -> dict[str, Any]:
    if not isinstance(rows, list) or len(rows) != 3:
        raise DiscordCutoverAuditError("exactly three profile routes are required")
    seen_names: set[str] = set()
    unique_profile_fields = {
        "home": set(),
        "managedDir": set(),
    }
    unique_consumer_fields = {
        "service": set(),
        "credentialFile": set(),
        "applicationIdentityRef": set(),
        "botTokenRef": set(),
    }
    for row in rows:
        if not isinstance(row, dict) or set(row) != EXPECTED_PROFILE_KEYS:
            raise DiscordCutoverAuditError("profile route schema drift")
        name = row.get("name")
        expected = EXPECTED_PROFILES.get(name)
        if expected is None or name in seen_names:
            raise DiscordCutoverAuditError("profile route identity drift")
        seen_names.add(name)
        if row["deliveryOwner"] != expected["deliveryOwner"]:
            raise DiscordCutoverAuditError(f"delivery owner drift for {name}")
        expected_service = (
            f"hermes-gateway-{name}.service" if expected["hasConsumer"] else None
        )
        if row["service"] != expected_service:
            raise DiscordCutoverAuditError(f"service drift for {name}")
        if row["home"] != f"/var/lib/hermes/{name}/.hermes/profiles/{name}":
            raise DiscordCutoverAuditError(f"home drift for {name}")
        if row["managedDir"] != f"/etc/hermes/{name}":
            raise DiscordCutoverAuditError(f"managed directory drift for {name}")
        expected_credential = (
            f"/etc/hermes/{name}/.env" if expected["hasConsumer"] else None
        )
        if row["credentialFile"] != expected_credential:
            raise DiscordCutoverAuditError(f"credential path drift for {name}")
        if row["authorizationMode"] != expected["authorizationMode"]:
            raise DiscordCutoverAuditError(f"authorization mode drift for {name}")
        if row["proactiveDelivery"] is not expected["proactiveDelivery"]:
            raise DiscordCutoverAuditError(f"delivery policy drift for {name}")
        for field in ("allowedChannelsRef", "freeResponseChannelsRef", "adminUsersRef"):
            _private_ref(row[field], f"{name}.{field}")
        for field in ("applicationIdentityRef", "botTokenRef"):
            _private_ref(
                row[field], f"{name}.{field}", optional=not expected["hasConsumer"]
            )
            if expected["hasConsumer"] and row[field] is None:
                raise DiscordCutoverAuditError(f"consumer identity missing for {name}")
        _role_ref(row["allowedRolesRef"], f"{name}.allowedRolesRef", optional=True)
        _private_ref(row["allowedUsersRef"], f"{name}.allowedUsersRef", optional=True)
        _private_ref(row["homeChannelRef"], f"{name}.homeChannelRef", optional=True)
        if expected["requiresAllowedUsers"] != (row["allowedUsersRef"] is not None):
            raise DiscordCutoverAuditError(f"allowed-user policy drift for {name}")
        if expected["requiresAllowedRoles"] != (row["allowedRolesRef"] is not None):
            raise DiscordCutoverAuditError(f"allowed-role policy drift for {name}")
        if expected["requiresHomeChannel"] != (row["homeChannelRef"] is not None):
            raise DiscordCutoverAuditError(f"home-channel policy drift for {name}")
        if row["regularUserCommands"] != []:
            raise DiscordCutoverAuditError(
                f"regular slash commands must be empty for {name}"
            )
        for field, values in unique_profile_fields.items():
            values.add(row[field])
        if expected["hasConsumer"]:
            for field, values in unique_consumer_fields.items():
                values.add(row[field])
    if seen_names != set(EXPECTED_PROFILES):
        raise DiscordCutoverAuditError("profile route set is incomplete")
    for field, values in unique_profile_fields.items():
        if len(values) != 3:
            raise DiscordCutoverAuditError(
                f"shared profile field is forbidden: {field}"
            )
    for field, values in unique_consumer_fields.items():
        if len(values) != 3:
            raise DiscordCutoverAuditError(
                f"Discord consumer field is not distinct: {field}"
            )
    return {"profiles": sorted(seen_names), "distinctIdentities": 3}


def _validate_cutover(cutover: Any) -> None:
    if not isinstance(cutover, dict):
        raise DiscordCutoverAuditError("cutover contract is required")
    if (
        cutover.get("attended") is not True
        or cutover.get("maintenanceWindowRequired") is not True
    ):
        raise DiscordCutoverAuditError("cutover must be attended and bounded")
    if set(cutover.get("preconditions", [])) != EXPECTED_PRECONDITIONS:
        raise DiscordCutoverAuditError("cutover preconditions are incomplete")
    if cutover.get("sourceStopOrder") != EXPECTED_SOURCE_STOP:
        raise DiscordCutoverAuditError("source stop order drift")
    if cutover.get("targetStartOrder") != EXPECTED_TARGET_START:
        raise DiscordCutoverAuditError("target start order drift")
    if cutover.get("healthReceiverDisposition") != "keep-running":
        raise DiscordCutoverAuditError("Health receiver must stay running")
    enrollment = cutover.get("credentialEnrollment")
    expected_enrollment = {
        "when": "after-source-stop-proof",
        "method": "owner-attended-root-only-enrollment",
        "reuseExistingBotIdentity": "preferred-when-uncompromised",
        "rotation": "required-if-exposed-or-compromised",
        "tokenComparison": "private-keyed-distinctness-only",
        "valuesInEvidence": False,
        "singleSurvivingCredentialPerBot": True,
        "slashCommandRegistration": "enable-only-after-distinct-application-proof",
    }
    if enrollment != expected_enrollment:
        raise DiscordCutoverAuditError("credential enrollment boundary drift")
    success = cutover.get("productionSuccessState")
    if (
        not isinstance(success, dict)
        or success.get("activeConsumerCountPerDiscordIdentity") != 1
    ):
        raise DiscordCutoverAuditError("single-consumer success proof is missing")
    if success.get("openclawState") != "preserved-restorable":
        raise DiscordCutoverAuditError("OpenClaw rollback state is not preserved")
    if success.get("hermesGateways") != "three-active-distinct-identities":
        raise DiscordCutoverAuditError("Discord consumer topology drift")
    if success.get("logicalProfiles") != "astra-dubble-rigel":
        raise DiscordCutoverAuditError("logical profile topology drift")
    if success.get("rigelDelivery") != "rigel-dedicated-consumer":
        raise DiscordCutoverAuditError("Rigel delivery topology drift")


def _validate_rollback(rollback: Any) -> None:
    if not isinstance(rollback, dict) or rollback.get("attended") is not True:
        raise DiscordCutoverAuditError("rollback must be attended")
    if rollback.get("triggerOnAnyPromotionFailure") is not True:
        raise DiscordCutoverAuditError("promotion failure must trigger rollback")
    if rollback.get("order") != EXPECTED_ROLLBACK:
        raise DiscordCutoverAuditError("rollback order drift")
    for key in ("hermesMessageReplay", "openclawCleanup", "hermesCleanup"):
        if rollback.get(key) is not False:
            raise DiscordCutoverAuditError(f"unsafe rollback authority: {key}")
    if rollback.get("healthReceiverDisposition") != "keep-running":
        raise DiscordCutoverAuditError("rollback cannot stop the Health receiver")


def _validate_regressions(path: Path) -> int:
    payload = _load_json(path, "Discord regressions")
    if payload.get("schemaVersion") != 1 or payload.get("mode") != "promotion-cases":
        raise DiscordCutoverAuditError("Discord regression header drift")
    rows = payload.get("cases")
    if not isinstance(rows, list):
        raise DiscordCutoverAuditError("Discord regression cases are required")
    ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "id",
            "risk",
            "scenario",
            "required",
            "forbidden",
        }:
            raise DiscordCutoverAuditError("Discord regression schema drift")
        ids.append(row["id"])
        if row["risk"] != "blocking":
            raise DiscordCutoverAuditError(
                "every Discord regression must block promotion"
            )
        for key in ("scenario", "required", "forbidden"):
            if not isinstance(row[key], str) or not row[key].strip():
                raise DiscordCutoverAuditError(f"empty Discord regression field: {key}")
    if len(ids) != len(set(ids)) or set(ids) != EXPECTED_CASES:
        raise DiscordCutoverAuditError("Discord regression case set drift")
    return len(rows)


def audit_contract(contract_path: Path, repository_root: Path) -> dict[str, Any]:
    contract = _load_json(contract_path, "Discord cutover contract")
    if contract.get("schemaVersion") != 2 or contract.get("mode") != "design-only":
        raise DiscordCutoverAuditError("Discord cutover contract header drift")
    if contract.get("authority") != EXPECTED_AUTHORITY:
        raise DiscordCutoverAuditError("Discord cutover authority drift")
    if contract.get("invariants") != EXPECTED_INVARIANTS:
        raise DiscordCutoverAuditError("Discord cutover invariants drift")
    pins = _validate_source_pins(contract.get("sourcePins"), repository_root)
    profiles = _validate_profiles(contract.get("profiles"))
    shadow = contract.get("shadow")
    if not isinstance(shadow, dict) or any(
        shadow.get(key) != value
        for key, value in {
            "openclawProductionDelivery": True,
            "hermesGatewayState": "stopped-and-disabled",
            "hermesCredentialFiles": "present-empty-or-provider-only",
            "discordTokenCount": 0,
            "discordApplicationEnrollmentCount": 0,
            "discordRouteCount": 0,
            "slashCommandRegistration": False,
            "productionSchedules": False,
        }.items()
    ):
        raise DiscordCutoverAuditError("shadow Discord boundary drift")
    _validate_cutover(contract.get("cutover"))
    _validate_rollback(contract.get("rollback"))
    evidence = contract.get("runtimeEvidence")
    if not isinstance(evidence, dict) or evidence.get("privateMode") != "0600":
        raise DiscordCutoverAuditError("private runtime evidence is required")
    if evidence.get("contentFreeNormalOutput") is not True:
        raise DiscordCutoverAuditError("normal audit output must be content-free")
    promotion_path = contract.get("promotionCases")
    if promotion_path != "files/hermes/discord-regressions.json":
        raise DiscordCutoverAuditError("Discord promotion path drift")
    case_count = _validate_regressions(repository_root / promotion_path)
    return {
        "schemaVersion": 2,
        "status": "ok",
        "mode": "design-only",
        "sourcePins": len(pins),
        "profiles": profiles["profiles"],
        "distinctIdentities": profiles["distinctIdentities"],
        "promotionCases": case_count,
        "liveChangeAuthorized": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    parser.add_argument(
        "--repository-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = audit_contract(args.contract, args.repository_root.resolve())
    except DiscordCutoverAuditError as exc:
        print(json.dumps({"schemaVersion": 2, "status": "error", "reason": str(exc)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
