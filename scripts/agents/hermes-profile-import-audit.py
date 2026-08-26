#!/usr/bin/env python3
"""Validate profile ownership for curated OpenClaw-to-Hermes imports."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

EXPECTED_SAFETY = {
    "sourceMutationAuthorized": False,
    "runtimeActivationAuthorized": False,
    "rawSessionImportAuthorized": False,
    "rawTranscriptImportAuthorized": False,
    "credentialImportAuthorized": False,
    "automaticMemoryApprovalAuthorized": False,
    "crossProfileMountsAuthorized": False,
    "executableRetentionAuthorized": False,
    "symlinkRetentionAuthorized": False,
}
EXPECTED_PROFILES = {
    "astra": {
        "serviceUser": "hermes-astra",
        "targetRoot": "/var/lib/hermes/astra/.hermes/profiles/astra",
        "behaviorSource": "files/hermes/profiles/astra/SOUL.md",
    },
    "dubble": {
        "serviceUser": "hermes-dubble",
        "targetRoot": "/var/lib/hermes/dubble/.hermes/profiles/dubble",
        "behaviorSource": "files/hermes/profiles/dubble/SOUL.md",
    },
    "rigel": {
        "serviceUser": "hermes-rigel",
        "targetRoot": "/var/lib/hermes/rigel/.hermes/profiles/rigel",
        "behaviorSource": "files/hermes/profiles/rigel/SOUL.md",
    },
}
IMPORT_MODES = {
    "data-stage",
    "memory-curation",
    "operator-reference",
    "private-reviewer-curation",
    "structured-transform",
}
EXPOSURES = {
    "approved-memory",
    "on-demand",
    "private-review-only",
    "root-policy",
    "schedule-input",
}
MODE_EXPOSURES = {
    "data-stage": {"on-demand"},
    "memory-curation": {"approved-memory"},
    "operator-reference": {"on-demand", "root-policy"},
    "private-reviewer-curation": {"private-review-only"},
    "structured-transform": {"on-demand", "root-policy", "schedule-input"},
}
MODE_OWNER_CLASSES = {
    "data-stage": {"executor-writable"},
    "memory-curation": {"executor-writable"},
    "operator-reference": {"operator-readonly"},
    "private-reviewer-curation": {"executor-writable"},
    "structured-transform": {"executor-writable", "operator-readonly"},
}
REVIEWER_RULES = {"antares-memory-data", "vega-memory-data"}
MEMORY_RULES = {"dubble-memory", "legacy-memory-tree"}
ACADEMIC_DATA_RULES = {"rigel-memory"}


class ProfileImportAuditError(RuntimeError):
    """Raised when a profile import contract is incomplete or unsafe."""


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileImportAuditError(
            f"{label} is unavailable or invalid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise ProfileImportAuditError(f"{label} must be a JSON object")
    return payload


def _required_text(row: dict[str, Any], key: str, label: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProfileImportAuditError(f"{label} requires nonempty {key}")
    return value


def _relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise ProfileImportAuditError(f"{label} must be a nonempty relative path")
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ProfileImportAuditError(f"{label} contains an unsafe path component")
    return value


def _validate_pinned_source(
    source: Any, expected_path: str, actual_path: Path, label: str
) -> str:
    if not isinstance(source, dict):
        raise ProfileImportAuditError(f"{label} source contract is required")
    if source.get("path") != expected_path:
        raise ProfileImportAuditError(f"{label} source path is not canonical")
    expected_hash = _required_text(source, "sha256", f"{label} source")
    if len(expected_hash) != 64 or any(
        character not in "0123456789abcdef" for character in expected_hash
    ):
        raise ProfileImportAuditError(f"{label} source hash is invalid")
    try:
        actual_hash = hashlib.sha256(actual_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ProfileImportAuditError(f"{label} source is unavailable") from exc
    if actual_hash != expected_hash:
        raise ProfileImportAuditError(f"{label} source hash drift")
    return actual_hash


def _validate_profiles(profiles: Any, repository_root: Path) -> None:
    if not isinstance(profiles, dict) or profiles != EXPECTED_PROFILES:
        raise ProfileImportAuditError("profile identity or target-root drift")
    users: set[str] = set()
    roots: set[str] = set()
    for profile, expected in EXPECTED_PROFILES.items():
        users.add(expected["serviceUser"])
        roots.add(expected["targetRoot"])
        behavior = repository_root / expected["behaviorSource"]
        try:
            metadata = behavior.lstat()
        except OSError as exc:
            raise ProfileImportAuditError(
                f"behavior source is unavailable for profile {profile}"
            ) from exc
        if not stat.S_ISREG(metadata.st_mode) or behavior.is_symlink():
            raise ProfileImportAuditError(
                f"behavior source must be a regular non-symlink for profile {profile}"
            )
    if len(users) != 3 or len(roots) != 3:
        raise ProfileImportAuditError("profile identities and roots must be distinct")


def _load_workspace_retained(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if policy.get("schemaVersion") != 1:
        raise ProfileImportAuditError("workspace policy schemaVersion must be 1")
    rows = policy.get("rules")
    if not isinstance(rows, list) or not rows:
        raise ProfileImportAuditError("workspace policy rules must be nonempty")
    retained: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ProfileImportAuditError(f"workspace policy rule {index} is invalid")
        if row.get("disposition") != "retain":
            continue
        rule_id = _required_text(row, "id", f"workspace retain rule {index}")
        if rule_id in retained:
            raise ProfileImportAuditError(f"duplicate workspace retain id: {rule_id}")
        if row.get("ownerClass") not in {"executor-writable", "operator-readonly"}:
            raise ProfileImportAuditError(
                f"workspace retain rule {rule_id} has invalid owner class"
            )
        retained[rule_id] = row
    return retained


def _load_state_curated(state_contract: dict[str, Any]) -> set[str]:
    if state_contract.get("schemaVersion") != 1:
        raise ProfileImportAuditError("state migration schemaVersion must be 1")
    state_root = state_contract.get("stateRoot")
    if not isinstance(state_root, dict) or not isinstance(
        state_root.get("rules"), list
    ):
        raise ProfileImportAuditError("state migration rules are unavailable")
    curated = {
        row.get("id")
        for row in state_root["rules"]
        if isinstance(row, dict) and row.get("action") == "curated-import"
    }
    if None in curated or not curated:
        raise ProfileImportAuditError("state migration curated rules are invalid")
    return curated


def _validate_mapping_shape(
    row: Any, index: int, require_owner_class: bool
) -> dict[str, str]:
    if not isinstance(row, dict):
        raise ProfileImportAuditError(f"import mapping {index} must be an object")
    label = f"import mapping {index}"
    source_rule_id = _required_text(row, "sourceRuleId", label)
    profile = row.get("profile")
    if profile not in EXPECTED_PROFILES:
        raise ProfileImportAuditError(f"invalid profile for mapping {source_rule_id}")
    target_namespace = _relative_path(
        row.get("targetNamespace"), f"mapping {source_rule_id} targetNamespace"
    )
    import_mode = row.get("importMode")
    if import_mode not in IMPORT_MODES:
        raise ProfileImportAuditError(
            f"invalid import mode for mapping {source_rule_id}"
        )
    exposure = row.get("exposure")
    if exposure not in EXPOSURES or exposure not in MODE_EXPOSURES[import_mode]:
        raise ProfileImportAuditError(f"unsafe exposure for mapping {source_rule_id}")
    if row.get("rawPromptInjection") is not False:
        raise ProfileImportAuditError(
            f"raw prompt injection must be disabled for mapping {source_rule_id}"
        )
    result = {
        "sourceRuleId": source_rule_id,
        "profile": profile,
        "targetNamespace": target_namespace,
        "importMode": import_mode,
        "exposure": exposure,
    }
    if require_owner_class:
        owner_class = row.get("ownerClass")
        if owner_class not in {"executor-writable", "operator-readonly"}:
            raise ProfileImportAuditError(
                f"invalid owner class for mapping {source_rule_id}"
            )
        if owner_class not in MODE_OWNER_CLASSES[import_mode]:
            raise ProfileImportAuditError(
                f"owner class is incompatible for mapping {source_rule_id}"
            )
        result["ownerClass"] = owner_class
    elif "ownerClass" in row:
        raise ProfileImportAuditError(
            f"state-root mapping {source_rule_id} cannot invent an owner class"
        )
    allowed_keys = {
        "sourceRuleId",
        "profile",
        "targetNamespace",
        "importMode",
        "exposure",
        "rawPromptInjection",
    }
    if require_owner_class:
        allowed_keys.add("ownerClass")
    unknown_keys = sorted(set(row) - allowed_keys)
    if unknown_keys:
        raise ProfileImportAuditError(
            f"unknown mapping keys for {source_rule_id}: {', '.join(unknown_keys)}"
        )
    return result


def _validate_workspace_mappings(
    rows: Any, retained: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    if not isinstance(rows, list) or not rows:
        raise ProfileImportAuditError("workspace mappings must be nonempty")
    mappings: dict[str, dict[str, str]] = {}
    targets: set[tuple[str, str]] = set()
    profile_counts: Counter[str] = Counter()
    mode_counts: Counter[str] = Counter()
    for index, row in enumerate(rows):
        mapping = _validate_mapping_shape(row, index, require_owner_class=True)
        rule_id = mapping["sourceRuleId"]
        if rule_id in mappings:
            raise ProfileImportAuditError(f"duplicate workspace mapping: {rule_id}")
        source = retained.get(rule_id)
        if source is None:
            raise ProfileImportAuditError(
                f"workspace mapping is not a retained source: {rule_id}"
            )
        if mapping["ownerClass"] != source.get("ownerClass"):
            raise ProfileImportAuditError(
                f"workspace owner-class drift for mapping {rule_id}"
            )
        target = (mapping["profile"], mapping["targetNamespace"])
        if target in targets:
            raise ProfileImportAuditError(
                f"duplicate profile target namespace: {target[0]}/{target[1]}"
            )
        targets.add(target)
        mappings[rule_id] = mapping
        profile_counts[mapping["profile"]] += 1
        mode_counts[mapping["importMode"]] += 1

    missing = sorted(set(retained) - set(mappings))
    extra = sorted(set(mappings) - set(retained))
    if missing or extra:
        raise ProfileImportAuditError(
            f"workspace retained mapping mismatch: missing={missing}, extra={extra}"
        )
    for rule_id, mapping in mappings.items():
        expected_profile = (
            "dubble"
            if rule_id.startswith("dubble-")
            else "rigel" if rule_id.startswith("rigel-") else "astra"
        )
        if mapping["profile"] != expected_profile:
            raise ProfileImportAuditError(
                f"cross-profile source assignment for mapping {rule_id}"
            )
    for rule_id in REVIEWER_RULES:
        mapping = mappings.get(rule_id)
        if not mapping or mapping["importMode"] != "private-reviewer-curation":
            raise ProfileImportAuditError(
                f"reviewer source {rule_id} must remain private review evidence"
            )
    for rule_id in MEMORY_RULES:
        mapping = mappings.get(rule_id)
        if not mapping or mapping["importMode"] != "memory-curation":
            raise ProfileImportAuditError(
                f"memory source {rule_id} must use approved curation"
            )
    for rule_id in ACADEMIC_DATA_RULES:
        mapping = mappings.get(rule_id)
        if not mapping or (
            mapping["importMode"] != "data-stage"
            or mapping["exposure"] != "on-demand"
            or mapping["profile"] != "rigel"
        ):
            raise ProfileImportAuditError(
                f"academic data source {rule_id} must remain isolated Rigel data"
            )
    return {
        "mappingCount": len(mappings),
        "profiles": dict(sorted(profile_counts.items())),
        "importModes": dict(sorted(mode_counts.items())),
    }


def _validate_state_mappings(rows: Any, curated_ids: set[str]) -> dict[str, Any]:
    if not isinstance(rows, list) or not rows:
        raise ProfileImportAuditError("state-root mappings must be nonempty")
    mappings: dict[str, dict[str, str]] = {}
    targets: set[tuple[str, str]] = set()
    for index, row in enumerate(rows):
        mapping = _validate_mapping_shape(row, index, require_owner_class=False)
        rule_id = mapping["sourceRuleId"]
        if rule_id in mappings:
            raise ProfileImportAuditError(f"duplicate state-root mapping: {rule_id}")
        if mapping["profile"] != "astra":
            raise ProfileImportAuditError(
                f"state-root curation cannot cross into profile {mapping['profile']}"
            )
        target = (mapping["profile"], mapping["targetNamespace"])
        if target in targets:
            raise ProfileImportAuditError(
                f"duplicate state-root target namespace: {target[0]}/{target[1]}"
            )
        targets.add(target)
        mappings[rule_id] = mapping
    missing = sorted(curated_ids - set(mappings))
    extra = sorted(set(mappings) - curated_ids)
    if missing or extra:
        raise ProfileImportAuditError(
            f"state-root curated mapping mismatch: missing={missing}, extra={extra}"
        )
    if mappings.get("memory-state", {}).get("importMode") != "memory-curation":
        raise ProfileImportAuditError(
            "OpenClaw provider memory must use approved curation"
        )
    return {"mappingCount": len(mappings), "sourceRuleIds": sorted(mappings)}


def load_and_validate(
    contract_path: Path,
    workspace_policy_path: Path,
    state_migration_path: Path,
    repository_root: Path,
) -> dict[str, Any]:
    contract = _load_json(contract_path, "profile import contract")
    if contract.get("schemaVersion") != 1:
        raise ProfileImportAuditError("profile import schemaVersion must be 1")
    if contract.get("mode") != "audit-only":
        raise ProfileImportAuditError("profile import contract must remain audit-only")
    if contract.get("safety") != EXPECTED_SAFETY:
        raise ProfileImportAuditError(
            "profile import safety contract is not fail-closed"
        )

    sources = contract.get("sourceContracts")
    if not isinstance(sources, dict) or set(sources) != {
        "workspacePolicy",
        "stateMigration",
    }:
        raise ProfileImportAuditError("profile import source contracts are incomplete")
    workspace_hash = _validate_pinned_source(
        sources["workspacePolicy"],
        "files/openclaw/workspace-migration-policy.json",
        workspace_policy_path,
        "workspace policy",
    )
    state_hash = _validate_pinned_source(
        sources["stateMigration"],
        "files/hermes/openclaw-state-migration-contract.json",
        state_migration_path,
        "state migration",
    )
    _validate_profiles(contract.get("profiles"), repository_root)

    workspace_policy = _load_json(workspace_policy_path, "workspace policy")
    retained = _load_workspace_retained(workspace_policy)
    state_contract = _load_json(state_migration_path, "state migration contract")
    curated_ids = _load_state_curated(state_contract)
    workspace_summary = _validate_workspace_mappings(
        contract.get("workspaceMappings"), retained
    )
    state_summary = _validate_state_mappings(
        contract.get("stateRootMappings"), curated_ids
    )
    return {
        "status": "ok",
        "schemaVersion": 1,
        "mode": "audit-only",
        "profiles": sorted(EXPECTED_PROFILES),
        "workspace": workspace_summary,
        "stateRoot": state_summary,
        "sources": {
            "workspacePolicySha256": workspace_hash,
            "stateMigrationSha256": state_hash,
        },
        "safety": EXPECTED_SAFETY,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate profile ownership for curated OpenClaw imports"
    )
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--workspace-policy", type=Path, required=True)
    parser.add_argument("--state-migration", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = load_and_validate(
            args.contract,
            args.workspace_policy,
            args.state_migration,
            args.repository_root,
        )
    except ProfileImportAuditError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
