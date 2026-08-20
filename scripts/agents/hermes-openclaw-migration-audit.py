#!/usr/bin/env python3
"""Audit OpenClaw-to-Hermes migration coverage without reading source contents."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import stat
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

DISPOSITIONS = {"archive", "discard", "replace", "retain", "retire"}
ACTIONS = {
    "curated-import",
    "delegate-workspace-policy",
    "discard-after-proof",
    "drain-and-archive",
    "re-enroll-secret",
    "rebuild-disabled",
    "retain-external",
    "review-rebuild",
    "sealed-archive",
    "source-preserving-conversion",
}
ACTIVATIONS = {"cutover-only", "offline-only", "post-parity"}
EXPECTED_SOURCE_PROTECTION = {
    "sourceMutationAuthorized": False,
    "sourceArchiveAuthorized": False,
    "sourceCleanupAuthorized": False,
    "liveMigrationAuthorized": False,
    "secretCopyAuthorized": False,
    "messagingActivationAuthorized": False,
    "schedulerActivationAuthorized": False,
}
EXPECTED_HANDLERS = {
    "archive": ("sealed-archive", "offline-only"),
    "discard": ("discard-after-proof", "post-parity"),
    "replace": ("review-rebuild", "post-parity"),
    "retain": ("curated-import", "post-parity"),
    "retire": ("sealed-archive", "offline-only"),
}
ACTION_ACTIVATIONS = {
    "curated-import": {"post-parity"},
    "delegate-workspace-policy": {"post-parity"},
    "discard-after-proof": {"post-parity"},
    "drain-and-archive": {"cutover-only"},
    "re-enroll-secret": {"cutover-only"},
    "rebuild-disabled": {"post-parity"},
    "retain-external": {"post-parity"},
    "review-rebuild": {"post-parity"},
    "sealed-archive": {"offline-only"},
    "source-preserving-conversion": {"post-parity"},
}
REQUIRED_RULE_ACTIONS = {
    "active-environment": "re-enroll-secret",
    "agents-runtime-state": "sealed-archive",
    "credential-store": "re-enroll-secret",
    "cron-state": "rebuild-disabled",
    "delivery-queue": "drain-and-archive",
    "device-enrollment": "re-enroll-secret",
    "discord-enrollment": "re-enroll-secret",
    "gateway-environment": "re-enroll-secret",
    "identity-state": "re-enroll-secret",
    "lcm-database": "source-preserving-conversion",
    "openclaw-config": "re-enroll-secret",
    "primary-workspace": "delegate-workspace-policy",
    "secret-store": "re-enroll-secret",
}
REQUIRED_DATABASE_BACKUPS = {
    "lcm-database": "sqlite-consistent-backup-after-openclaw-stop",
    "openclaw-database": "sqlite-consistent-backup-after-openclaw-stop",
    "state-database": "sqlite-consistent-backup-after-openclaw-stop",
}


class MigrationAuditError(RuntimeError):
    """Raised when migration classification is incomplete or unsafe."""


@dataclass(frozen=True)
class StateRule:
    rule_id: str
    scope: str
    pattern: str
    expected_kind: str
    action: str
    activation: str
    sensitivity: str | None
    backup_method: str | None

    @property
    def literal_chars(self) -> int:
        return len(self.pattern.replace("*", "").replace("?", ""))

    def match_score(self, name: str) -> tuple[int, int] | None:
        if self.scope == "exact":
            return (2, self.literal_chars) if name == self.pattern else None
        return (
            (1, self.literal_chars) if fnmatch.fnmatchcase(name, self.pattern) else None
        )


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationAuditError(f"{label} is unavailable or invalid JSON") from exc
    if not isinstance(payload, dict):
        raise MigrationAuditError(f"{label} must be a JSON object")
    return payload


def _required_text(row: dict[str, Any], key: str, label: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MigrationAuditError(f"{label} requires nonempty {key}")
    return value


def _top_level_pattern(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "/" in value:
        raise MigrationAuditError(f"{label} must be a nonempty top-level pattern")
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise MigrationAuditError(f"{label} contains an unsafe path component")
    return value


def _validate_workspace_contract(
    workspace: Any, workspace_policy_path: Path
) -> dict[str, Any]:
    if not isinstance(workspace, dict):
        raise MigrationAuditError("contract workspace section is required")
    policy_name = _required_text(workspace, "policy", "workspace")
    if policy_name != "files/openclaw/workspace-migration-policy.json":
        raise MigrationAuditError("workspace policy source is not canonical")
    expected_hash = _required_text(workspace, "policySha256", "workspace")
    if len(expected_hash) != 64 or any(
        character not in "0123456789abcdef" for character in expected_hash
    ):
        raise MigrationAuditError("workspace policySha256 must be lowercase SHA-256")
    try:
        actual_hash = hashlib.sha256(workspace_policy_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise MigrationAuditError("workspace policy is unavailable") from exc
    if actual_hash != expected_hash:
        raise MigrationAuditError("workspace policy hash drift")

    policy = _load_json(workspace_policy_path, "workspace policy")
    if policy.get("schemaVersion") != 1:
        raise MigrationAuditError("workspace policy schemaVersion must be 1")
    policy_rules = policy.get("rules")
    if not isinstance(policy_rules, list) or not policy_rules:
        raise MigrationAuditError("workspace policy rules must be nonempty")
    policy_dispositions: set[str] = set()
    policy_by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(policy_rules):
        if not isinstance(row, dict):
            raise MigrationAuditError(f"workspace policy rule {index} is invalid")
        rule_id = _required_text(row, "id", f"workspace policy rule {index}")
        if rule_id in policy_by_id:
            raise MigrationAuditError(f"duplicate workspace policy id: {rule_id}")
        disposition = row.get("disposition")
        if disposition not in DISPOSITIONS:
            raise MigrationAuditError(
                f"invalid workspace disposition for rule {rule_id}"
            )
        policy_dispositions.add(disposition)
        policy_by_id[rule_id] = row
    if policy_dispositions != DISPOSITIONS:
        raise MigrationAuditError(
            "workspace policy does not exercise every disposition"
        )

    handlers = workspace.get("dispositionHandlers")
    if not isinstance(handlers, dict) or set(handlers) != DISPOSITIONS:
        raise MigrationAuditError("workspace handlers must cover every disposition")
    for disposition, (
        expected_action,
        expected_activation,
    ) in EXPECTED_HANDLERS.items():
        handler = handlers.get(disposition)
        if not isinstance(handler, dict):
            raise MigrationAuditError(f"workspace handler {disposition} is invalid")
        action = _required_text(handler, "action", f"handler {disposition}")
        activation = _required_text(handler, "activation", f"handler {disposition}")
        _required_text(handler, "destination", f"handler {disposition}")
        if (action, activation) != (expected_action, expected_activation):
            raise MigrationAuditError(
                f"unsafe workspace handler for disposition {disposition}"
            )

    overrides = workspace.get("ruleOverrides")
    if not isinstance(overrides, dict) or set(overrides) != {"health-database"}:
        raise MigrationAuditError("Health database override is required and exclusive")
    health_source = policy_by_id.get("health-database")
    if not health_source or health_source.get("disposition") != "replace":
        raise MigrationAuditError("workspace Health database source rule drift")
    health = overrides["health-database"]
    if not isinstance(health, dict):
        raise MigrationAuditError("Health database override is invalid")
    if health.get("action") != "retain-external":
        raise MigrationAuditError("Health database must remain externally owned")
    if health.get("activation") != "post-parity":
        raise MigrationAuditError("Health database activation gate is invalid")
    if health.get("backupMethod") != "sqlite-consistent-backup-after-receiver-stop":
        raise MigrationAuditError("Health database requires a consistent SQLite backup")
    _required_text(health, "destination", "Health database override")

    return {
        "policySha256": actual_hash,
        "policyRules": len(policy_rules),
        "policyDispositions": sorted(policy_dispositions),
        "handlerCount": len(handlers),
        "overrideCount": len(overrides),
    }


def _load_state_rules(state_root: Any) -> list[StateRule]:
    if not isinstance(state_root, dict):
        raise MigrationAuditError("contract stateRoot section is required")
    rows = state_root.get("rules")
    if not isinstance(rows, list) or not rows:
        raise MigrationAuditError("stateRoot rules must be nonempty")

    rules: list[StateRule] = []
    ids: set[str] = set()
    selectors: set[tuple[str, str]] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise MigrationAuditError(f"state rule {index} must be an object")
        label = f"state rule {index}"
        rule_id = _required_text(row, "id", label)
        if rule_id in ids:
            raise MigrationAuditError(f"duplicate state rule id: {rule_id}")
        ids.add(rule_id)
        scope = row.get("scope")
        if scope not in {"exact", "glob"}:
            raise MigrationAuditError(f"invalid scope for state rule {rule_id}")
        pattern = _top_level_pattern(row.get("pattern"), f"rule {rule_id} pattern")
        if scope == "exact" and any(character in pattern for character in "*?"):
            raise MigrationAuditError(f"exact state rule {rule_id} has wildcards")
        if scope == "glob" and not any(character in pattern for character in "*?"):
            raise MigrationAuditError(f"glob state rule {rule_id} has no wildcard")
        selector = (scope, pattern)
        if selector in selectors:
            raise MigrationAuditError(f"duplicate state selector: {selector}")
        selectors.add(selector)
        expected_kind = row.get("expectedKind")
        if expected_kind not in {"directory", "file"}:
            raise MigrationAuditError(f"invalid expectedKind for state rule {rule_id}")
        action = row.get("action")
        if action not in ACTIONS:
            raise MigrationAuditError(f"invalid action for state rule {rule_id}")
        activation = row.get("activation")
        if (
            activation not in ACTIVATIONS
            or activation not in ACTION_ACTIVATIONS[action]
        ):
            raise MigrationAuditError(f"unsafe activation for state rule {rule_id}")
        _required_text(row, "destination", f"state rule {rule_id}")
        _required_text(row, "reason", f"state rule {rule_id}")
        sensitivity = row.get("sensitivity")
        if sensitivity is not None and not isinstance(sensitivity, str):
            raise MigrationAuditError(f"invalid sensitivity for state rule {rule_id}")
        if action == "re-enroll-secret" and sensitivity != "secret":
            raise MigrationAuditError(
                f"re-enrollment rule {rule_id} must be secret-classified"
            )
        if sensitivity == "secret" and action not in {
            "re-enroll-secret",
            "sealed-archive",
        }:
            raise MigrationAuditError(f"secret rule {rule_id} permits unsafe handling")
        backup_method = row.get("backupMethod")
        if backup_method is not None and not isinstance(backup_method, str):
            raise MigrationAuditError(f"invalid backupMethod for state rule {rule_id}")
        rules.append(
            StateRule(
                rule_id=rule_id,
                scope=scope,
                pattern=pattern,
                expected_kind=expected_kind,
                action=action,
                activation=activation,
                sensitivity=sensitivity,
                backup_method=backup_method,
            )
        )

    by_id = {rule.rule_id: rule for rule in rules}
    for rule_id, expected_action in REQUIRED_RULE_ACTIONS.items():
        rule = by_id.get(rule_id)
        if rule is None or rule.action != expected_action:
            raise MigrationAuditError(
                f"required state rule {rule_id} must use {expected_action}"
            )
    for rule_id, expected_method in REQUIRED_DATABASE_BACKUPS.items():
        rule = by_id.get(rule_id)
        if rule is None or rule.backup_method != expected_method:
            raise MigrationAuditError(
                f"database state rule {rule_id} lacks consistent backup method"
            )
    return rules


def load_contract(
    contract_path: Path, workspace_policy_path: Path
) -> tuple[list[StateRule], dict[str, Any]]:
    contract = _load_json(contract_path, "migration contract")
    if contract.get("schemaVersion") != 1:
        raise MigrationAuditError("contract schemaVersion must be 1")
    if contract.get("mode") != "audit-only":
        raise MigrationAuditError("migration contract must remain audit-only")
    if contract.get("sourceProtection") != EXPECTED_SOURCE_PROTECTION:
        raise MigrationAuditError("source protection contract is not fail-closed")
    workspace_summary = _validate_workspace_contract(
        contract.get("workspace"), workspace_policy_path
    )
    rules = _load_state_rules(contract.get("stateRoot"))
    return rules, workspace_summary


def _select_rule(rules: list[StateRule], name: str) -> StateRule:
    candidates: list[tuple[tuple[int, int], StateRule]] = []
    for rule in rules:
        score = rule.match_score(name)
        if score is not None:
            candidates.append((score, rule))
    if not candidates:
        raise MigrationAuditError(f"unclassified state-root entry: {name}")
    candidates.sort(key=lambda item: item[0], reverse=True)
    best_score = candidates[0][0]
    winners = [rule for score, rule in candidates if score == best_score]
    if len(winners) != 1:
        ids = ", ".join(sorted(rule.rule_id for rule in winners))
        raise MigrationAuditError(f"ambiguous state-root entry {name}: {ids}")
    return winners[0]


def _path_kind(metadata: os.stat_result) -> str:
    if stat.S_ISREG(metadata.st_mode):
        return "file"
    if stat.S_ISDIR(metadata.st_mode):
        return "directory"
    if stat.S_ISLNK(metadata.st_mode):
        return "symlink"
    return "special"


def inventory_state_root(source_root: Path, rules: list[StateRule]) -> dict[str, Any]:
    try:
        root_metadata = source_root.lstat()
    except OSError as exc:
        raise MigrationAuditError("OpenClaw state root is unavailable") from exc
    if not stat.S_ISDIR(root_metadata.st_mode) or source_root.is_symlink():
        raise MigrationAuditError("OpenClaw state root must be a non-symlink directory")

    action_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    rule_counts: Counter[str] = Counter()
    try:
        entries = sorted(os.scandir(source_root), key=lambda entry: entry.name)
    except OSError as exc:
        raise MigrationAuditError("cannot enumerate OpenClaw state root") from exc
    for entry in entries:
        try:
            metadata = entry.stat(follow_symlinks=False)
        except OSError as exc:
            raise MigrationAuditError(
                f"cannot stat state-root entry: {entry.name}"
            ) from exc
        kind = _path_kind(metadata)
        if kind in {"special", "symlink"}:
            raise MigrationAuditError(
                f"unsupported {kind} state-root entry: {entry.name}"
            )
        rule = _select_rule(rules, entry.name)
        if kind != rule.expected_kind:
            raise MigrationAuditError(
                f"state-root kind drift for {entry.name}: expected "
                f"{rule.expected_kind}, got {kind}"
            )
        action_counts[rule.action] += 1
        kind_counts[kind] += 1
        rule_counts[rule.rule_id] += 1

    return {
        "status": "ok",
        "schemaVersion": 1,
        "mode": "metadata-only",
        "summary": {
            "classifiedEntries": sum(rule_counts.values()),
            "actions": dict(sorted(action_counts.items())),
            "kinds": dict(sorted(kind_counts.items())),
        },
        "rules": [
            {
                "id": rule.rule_id,
                "action": rule.action,
                "matchedEntries": rule_counts[rule.rule_id],
            }
            for rule in rules
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit OpenClaw-to-Hermes state coverage without reading contents"
    )
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--workspace-policy", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        rules, workspace_summary = load_contract(args.contract, args.workspace_policy)
        result = inventory_state_root(args.state_root, rules)
        result["workspace"] = workspace_summary
        result["sourceProtection"] = EXPECTED_SOURCE_PROTECTION
    except MigrationAuditError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
