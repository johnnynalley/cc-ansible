#!/usr/bin/env python3
"""Normalize reviewed OpenClaw state into isolated Hermes profile data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable


CONTRACT_KEYS = {
    "schemaVersion",
    "mode",
    "sourceRoot",
    "sourcePins",
    "profiles",
    "ownership",
    "limits",
    "transforms",
    "safety",
    "execution",
}
PROFILE_KEYS = {
    "uid",
    "gid",
    "writableRoot",
    "managedRoot",
    "writableRuntimeRoot",
    "managedRuntimeRoot",
}
OWNERSHIP_KEYS = {
    "operatorUid",
    "operatorGid",
    "generationRootMode",
    "writableDirectoryMode",
    "writableFileMode",
    "managedDirectoryMode",
    "managedFileMode",
}
LIMIT_KEYS = {
    "maxInputs",
    "maxInputBytes",
    "maxOutputs",
    "maxOutputBytes",
    "maxCollectionItems",
    "maxStringBytes",
}
SAFETY_KEYS = {
    "sourceMutationAllowed",
    "sourceMountAllowed",
    "rawSourceExposureAllowed",
    "rawPromptInjectionAllowed",
    "symlinksAllowed",
    "specialFilesAllowed",
    "executableBitsRetained",
    "credentialsAllowed",
    "gatewayActivationAllowed",
    "schedulerActivationAllowed",
    "messagingActivationAllowed",
    "modelInvocationAllowed",
}
EXECUTION_KEYS = {
    "backupRequired",
    "transactionRollbackRequired",
    "sourceStabilityRequired",
    "contentHashVerificationRequired",
    "managedRuntimeReadOnly",
    "writableRuntimeProfileIsolated",
}
TRANSFORM_KEYS = {"id", "profile", "ownerClass", "sources", "output", "transform"}
EXPECTED_TRANSFORMS = {
    "dubble-users",
    "freshrss-state",
    "reddit-sync-state",
    "sobriety-state",
    "nextcloud-task-state",
}
EXPECTED_TRANSFORM_LAYOUT = {
    "dubble-users": {
        "sources": ["dubble/users"],
        "output": "data/users/index.json",
        "transform": "empty-user-registry",
    },
    "freshrss-state": {
        "sources": ["freshrss/state.json"],
        "output": "data/integrations/freshrss/state.json",
        "transform": "freshrss-state-v1",
    },
    "reddit-sync-state": {
        "sources": ["reddit/sync-state.json"],
        "output": "data/integrations/reddit/sync-state.json",
        "transform": "reddit-sync-state-v1",
    },
    "sobriety-state": {
        "sources": ["sober-tracking/state.json"],
        "output": "data/sober-tracking/state.json",
        "transform": "sobriety-state-v1",
    },
    "nextcloud-task-state": {
        "sources": ["tasks/nextcloud-tasks.json"],
        "output": "data/tasks/nextcloud-tasks.json",
        "transform": "nextcloud-task-state-v1",
    },
}
EXPECTED_MODES = {
    "generationRootMode": "0711",
    "writableDirectoryMode": "0750",
    "writableFileMode": "0640",
    "managedDirectoryMode": "0550",
    "managedFileMode": "0440",
}


class TransformError(RuntimeError):
    """Raised when a transform input or output violates the reviewed contract."""


@dataclass(frozen=True)
class InputRecord:
    relative: str
    kind: str
    device: int
    inode: int
    size: int
    mtime_ns: int
    mode: int
    sha256: str
    payload: bytes

    @property
    def stability_tuple(self) -> tuple[Any, ...]:
        return (
            self.relative,
            self.kind,
            self.device,
            self.inode,
            self.size,
            self.mtime_ns,
            self.mode,
            self.sha256,
        )


@dataclass(frozen=True)
class OutputRecord:
    transform_id: str
    profile: str
    bucket: str
    target_relative: str
    source_digest: str
    payload: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()


def require(condition: bool, code: str) -> None:
    if not condition:
        raise TransformError(code)


def safe_relative(value: Any, code: str) -> PurePosixPath:
    require(isinstance(value, str) and value and not value.startswith("/"), code)
    require(not any(ord(character) < 32 for character in value), code)
    result = PurePosixPath(value)
    require(all(part not in {"", ".", ".."} for part in result.parts), code)
    return result


def load_json_file(path: Path, code: str) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        require(stat.S_ISREG(metadata.st_mode) and not path.is_symlink(), code)
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TransformError(code) from exc
    require(isinstance(value, dict), code)
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        metadata = os.fstat(descriptor)
        require(stat.S_ISREG(metadata.st_mode), "hash-input-not-regular")
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)
    except OSError as exc:
        raise TransformError("hash-input-unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def checked_string(value: Any, code: str, limit: int) -> str:
    require(isinstance(value, str), code)
    encoded = value.encode("utf-8")
    require(len(encoded) <= limit, code)
    require(not any(ord(character) < 32 and character not in "\n\r\t" for character in value), code)
    return value


def checked_date(value: Any, code: str) -> str:
    text = checked_string(value, code, 10)
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise TransformError(code) from exc
    return text


def checked_timestamp(value: Any, code: str) -> str:
    text = checked_string(value, code, 64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TransformError(code) from exc
    require(parsed.tzinfo is not None, code)
    return text


def checked_number(value: Any, code: str, *, integer: bool = False) -> int | float:
    if integer:
        require(isinstance(value, int) and not isinstance(value, bool), code)
    else:
        require(isinstance(value, (int, float)) and not isinstance(value, bool), code)
    require(value >= 0, code)
    return value


def canonical_json(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def validate_contract(
    contract_path: Path, repository_root: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    contract = load_json_file(contract_path, "contract-invalid")
    require(set(contract) == CONTRACT_KEYS, "contract-fields-invalid")
    require(contract["schemaVersion"] == 1, "contract-schema-invalid")
    require(
        contract["mode"] == "inactive-reviewed-profile-transforms",
        "contract-mode-invalid",
    )
    require(
        isinstance(contract["safety"], dict)
        and set(contract["safety"]) == SAFETY_KEYS
        and all(value is False for value in contract["safety"].values()),
        "contract-safety-enabled",
    )
    require(
        isinstance(contract["execution"], dict)
        and set(contract["execution"]) == EXECUTION_KEYS
        and all(value is True for value in contract["execution"].values()),
        "contract-execution-disabled",
    )
    require(
        isinstance(contract["limits"], dict)
        and set(contract["limits"]) == LIMIT_KEYS
        and all(
            isinstance(contract["limits"][key], int)
            and not isinstance(contract["limits"][key], bool)
            and contract["limits"][key] > 0
            for key in LIMIT_KEYS
        ),
        "contract-limits-invalid",
    )
    require(
        isinstance(contract["profiles"], dict)
        and set(contract["profiles"]) == {"astra", "dubble", "rigel"},
        "contract-profiles-invalid",
    )
    roots: set[Path] = set()
    for profile_name, profile in contract["profiles"].items():
        require(isinstance(profile, dict) and set(profile) == PROFILE_KEYS, f"profile-{profile_name}-invalid")
        require(
            all(
                isinstance(profile[key], int)
                and not isinstance(profile[key], bool)
                and profile[key] >= 0
                for key in ("uid", "gid")
            ),
            f"profile-{profile_name}-identity-invalid",
        )
        for key in (
            "writableRoot",
            "managedRoot",
            "writableRuntimeRoot",
            "managedRuntimeRoot",
        ):
            path = Path(profile[key])
            require(path.is_absolute() and ".." not in path.parts, f"profile-{profile_name}-path-invalid")
            require(path not in roots, "profile-root-collision")
            roots.add(path)
    ownership = contract["ownership"]
    require(isinstance(ownership, dict) and set(ownership) == OWNERSHIP_KEYS, "contract-ownership-invalid")
    require(
        all(
            isinstance(ownership[key], int)
            and not isinstance(ownership[key], bool)
            and ownership[key] >= 0
            for key in ("operatorUid", "operatorGid")
        )
        and all(ownership[key] == value for key, value in EXPECTED_MODES.items()),
        "contract-ownership-policy-invalid",
    )
    pins = contract["sourcePins"]
    require(isinstance(pins, dict) and set(pins) == {"profileImport", "workspacePolicy"}, "contract-pins-invalid")
    loaded: dict[str, dict[str, Any]] = {}
    for name, pin in pins.items():
        require(isinstance(pin, dict) and set(pin) == {"path", "sha256"}, f"pin-{name}-invalid")
        relative = safe_relative(pin["path"], f"pin-{name}-path-invalid")
        expected = pin["sha256"]
        require(isinstance(expected, str) and len(expected) == 64, f"pin-{name}-hash-invalid")
        path = repository_root / relative.as_posix()
        require(file_sha256(path) == expected, f"pin-{name}-drift")
        loaded[name] = load_json_file(path, f"pin-{name}-json-invalid")

    transforms = contract["transforms"]
    require(isinstance(transforms, list) and len(transforms) == 5, "transform-count-invalid")
    require(
        {row.get("id") for row in transforms if isinstance(row, dict)} == EXPECTED_TRANSFORMS,
        "transform-inventory-invalid",
    )
    targets: set[tuple[str, str, str]] = set()
    for row in transforms:
        require(isinstance(row, dict) and set(row) == TRANSFORM_KEYS, "transform-fields-invalid")
        expected_layout = EXPECTED_TRANSFORM_LAYOUT[row["id"]]
        require(
            row["sources"] == expected_layout["sources"]
            and row["output"] == expected_layout["output"]
            and row["transform"] == expected_layout["transform"],
            f"transform-{row['id']}-layout-drift",
        )
        require(row["profile"] in contract["profiles"], f"transform-{row['id']}-profile-invalid")
        require(row["ownerClass"] in {"executor-writable", "operator-readonly"}, f"transform-{row['id']}-owner-invalid")
        require(isinstance(row["sources"], list) and row["sources"], f"transform-{row['id']}-sources-invalid")
        for source in row["sources"]:
            safe_relative(source, f"transform-{row['id']}-source-invalid")
        output = safe_relative(row["output"], f"transform-{row['id']}-output-invalid")
        bucket = "writable" if row["ownerClass"] == "executor-writable" else "managed"
        target = (row["profile"], bucket, output.as_posix())
        require(target not in targets, "transform-target-collision")
        targets.add(target)

    profile_import = loaded["profileImport"]
    workspace_policy = loaded["workspacePolicy"]
    import_rows = {
        row.get("sourceRuleId"): row
        for row in profile_import.get("workspaceMappings", [])
        if isinstance(row, dict) and row.get("importMode") == "structured-transform"
    }
    policy_rows = {
        row.get("id"): row
        for row in workspace_policy.get("rules", [])
        if isinstance(row, dict)
    }
    require(set(import_rows) == EXPECTED_TRANSFORMS, "profile-import-transform-drift")
    for row in transforms:
        imported = import_rows[row["id"]]
        policy = policy_rows.get(row["id"])
        require(
            imported.get("profile") == row["profile"]
            and imported.get("ownerClass") == row["ownerClass"]
            and imported.get("rawPromptInjection") is False
            and isinstance(policy, dict)
            and policy.get("disposition") == "retain"
            and policy.get("ownerClass") == row["ownerClass"],
            f"transform-{row['id']}-source-contract-drift",
        )
    contract_hash = hashlib.sha256(canonical_json(contract)).hexdigest()
    return contract, profile_import, workspace_policy, contract_hash


def snapshot_input(path: Path, source_root: Path, max_bytes: int) -> InputRecord:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise TransformError("transform-input-unavailable") from exc
    relative = path.relative_to(source_root).as_posix()
    if stat.S_ISDIR(metadata.st_mode):
        require(not path.is_symlink(), "transform-input-symlink")
        try:
            with os.scandir(path) as entries:
                require(next(entries, None) is None, "transform-directory-not-empty")
        except OSError as exc:
            raise TransformError("transform-directory-unreadable") from exc
        payload = b""
        kind = "empty-directory"
        digest = hashlib.sha256(payload).hexdigest()
    else:
        require(stat.S_ISREG(metadata.st_mode) and not path.is_symlink(), "transform-input-not-regular")
        require(metadata.st_size <= max_bytes, "transform-input-too-large")
        try:
            descriptor = os.open(
                path,
                os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            )
            with os.fdopen(descriptor, "rb") as handle:
                opened = os.fstat(handle.fileno())
                require(
                    (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
                    == (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns),
                    "transform-input-raced",
                )
                payload = handle.read(max_bytes + 1)
        except OSError as exc:
            raise TransformError("transform-input-unreadable") from exc
        require(len(payload) <= max_bytes, "transform-input-too-large")
        kind = "file"
        digest = hashlib.sha256(payload).hexdigest()
    return InputRecord(
        relative=relative,
        kind=kind,
        device=metadata.st_dev,
        inode=metadata.st_ino,
        size=metadata.st_size,
        mtime_ns=metadata.st_mtime_ns,
        mode=stat.S_IMODE(metadata.st_mode),
        sha256=digest,
        payload=payload,
    )


def parse_json_payload(record: InputRecord, code: str) -> dict[str, Any]:
    require(record.kind == "file", code)
    try:
        value = json.loads(record.payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TransformError(code) from exc
    require(isinstance(value, dict), code)
    return value


def transform_empty_users(inputs: list[InputRecord], _: dict[str, int]) -> dict[str, Any]:
    require(len(inputs) == 1 and inputs[0].kind == "empty-directory", "dubble-users-not-empty")
    return {"schemaVersion": 1, "users": {}}


def transform_freshrss(inputs: list[InputRecord], limits: dict[str, int]) -> dict[str, Any]:
    require(len(inputs) == 1, "freshrss-input-count")
    value = parse_json_payload(inputs[0], "freshrss-invalid-json")
    require(set(value) == {"lastRun", "matched", "candidateCount"}, "freshrss-schema")
    return {
        "schemaVersion": 1,
        "lastRun": checked_timestamp(value["lastRun"], "freshrss-last-run"),
        "matched": checked_number(value["matched"], "freshrss-matched", integer=True),
        "candidateCount": checked_number(value["candidateCount"], "freshrss-candidates", integer=True),
    }


def transform_reddit(inputs: list[InputRecord], limits: dict[str, int]) -> dict[str, Any]:
    require(len(inputs) == 1, "reddit-input-count")
    value = parse_json_payload(inputs[0], "reddit-invalid-json")
    require(set(value) == {"lastSync", "status", "error"}, "reddit-schema")
    return {
        "schemaVersion": 1,
        "lastSync": checked_timestamp(value["lastSync"], "reddit-last-sync"),
        "status": checked_string(value["status"], "reddit-status", 80),
        "error": checked_string(value["error"], "reddit-error", limits["maxStringBytes"]),
    }


def validate_optional_money(value: Any, code: str) -> int | float | None:
    if value is None:
        return None
    return checked_number(value, code)


def transform_sobriety(inputs: list[InputRecord], limits: dict[str, int]) -> dict[str, Any]:
    require(len(inputs) == 1, "sobriety-input-count")
    value = parse_json_payload(inputs[0], "sobriety-invalid-json")
    required = {"startDate", "substance", "dailySpend", "checkIns", "milestonesHit", "relapses"}
    optional = {"silent", "vaping"}
    require(required <= set(value) and set(value) <= required | optional, "sobriety-schema")
    maximum = limits["maxCollectionItems"]
    check_ins = value["checkIns"]
    require(isinstance(check_ins, list) and len(check_ins) <= maximum, "sobriety-checkins")
    normalized_check_ins = []
    for item in check_ins:
        require(isinstance(item, dict) and set(item) == {"date", "mood", "cravings", "notes"}, "sobriety-checkin-schema")
        mood = checked_number(item["mood"], "sobriety-mood", integer=True)
        cravings = checked_number(item["cravings"], "sobriety-cravings", integer=True)
        require(1 <= mood <= 10 and 1 <= cravings <= 10, "sobriety-checkin-range")
        normalized_check_ins.append(
            {
                "date": checked_date(item["date"], "sobriety-checkin-date"),
                "mood": mood,
                "cravings": cravings,
                "notes": checked_string(item["notes"], "sobriety-checkin-notes", limits["maxStringBytes"]),
            }
        )
    milestones = value["milestonesHit"]
    require(isinstance(milestones, list) and len(milestones) <= maximum, "sobriety-milestones")
    normalized_milestones = [
        checked_string(item, "sobriety-milestone", 80) for item in milestones
    ]
    relapses = value["relapses"]
    require(isinstance(relapses, list) and len(relapses) <= maximum, "sobriety-relapses")
    normalized_relapses = []
    for item in relapses:
        require(isinstance(item, dict) and set(item) == {"date", "notes"}, "sobriety-relapse-schema")
        normalized_relapses.append(
            {
                "date": checked_date(item["date"], "sobriety-relapse-date"),
                "notes": checked_string(item["notes"], "sobriety-relapse-notes", limits["maxStringBytes"]),
            }
        )
    output: dict[str, Any] = {
        "schemaVersion": 1,
        "startDate": checked_date(value["startDate"], "sobriety-start-date"),
        "substance": checked_string(value["substance"], "sobriety-substance", 160),
        "dailySpend": validate_optional_money(value["dailySpend"], "sobriety-daily-spend"),
        "checkIns": normalized_check_ins,
        "milestonesHit": normalized_milestones,
        "relapses": normalized_relapses,
    }
    if "silent" in value:
        require(isinstance(value["silent"], bool), "sobriety-silent")
        output["silent"] = value["silent"]
    if "vaping" in value:
        vaping = value["vaping"]
        require(isinstance(vaping, dict) and set(vaping) == {"startDate", "substance", "dailySpend"}, "sobriety-vaping-schema")
        output["vaping"] = {
            "startDate": checked_date(vaping["startDate"], "sobriety-vaping-start-date"),
            "substance": checked_string(vaping["substance"], "sobriety-vaping-substance", 160),
            "dailySpend": validate_optional_money(vaping["dailySpend"], "sobriety-vaping-daily-spend"),
        }
    return output


def transform_nextcloud_tasks(inputs: list[InputRecord], limits: dict[str, int]) -> dict[str, Any]:
    require(len(inputs) == 1, "nextcloud-input-count")
    value = parse_json_payload(inputs[0], "nextcloud-invalid-json")
    require(set(value) == {"generatedAt", "lists"}, "nextcloud-schema")
    lists = value["lists"]
    require(isinstance(lists, dict) and len(lists) <= limits["maxCollectionItems"], "nextcloud-lists")
    normalized_lists: dict[str, list[dict[str, Any]]] = {}
    item_count = 0
    for name in sorted(lists):
        checked_name = checked_string(name, "nextcloud-list-name", 240)
        items = lists[name]
        require(isinstance(items, list), "nextcloud-list-items")
        item_count += len(items)
        require(item_count <= limits["maxCollectionItems"], "nextcloud-items-too-many")
        normalized_items = []
        for item in items:
            require(
                isinstance(item, dict)
                and set(item) == {"file", "summary", "status", "due", "description", "percent"},
                "nextcloud-item-schema",
            )
            normalized: dict[str, Any] = {}
            for key, maximum in (("file", 1024), ("summary", 1024), ("status", 80)):
                normalized[key] = checked_string(item[key], f"nextcloud-item-{key}", maximum)
            for key, maximum in (("due", 128), ("description", limits["maxStringBytes"]), ("percent", 32)):
                raw = item[key]
                require(raw is None or isinstance(raw, str), f"nextcloud-item-{key}")
                normalized[key] = None if raw is None else checked_string(raw, f"nextcloud-item-{key}", maximum)
            normalized_items.append(normalized)
        normalized_lists[checked_name] = normalized_items
    return {
        "schemaVersion": 1,
        "generatedAt": checked_timestamp(value["generatedAt"], "nextcloud-generated-at"),
        "lists": normalized_lists,
    }


TRANSFORMERS: dict[str, Callable[[list[InputRecord], dict[str, int]], dict[str, Any]]] = {
    "empty-user-registry": transform_empty_users,
    "freshrss-state-v1": transform_freshrss,
    "reddit-sync-state-v1": transform_reddit,
    "sobriety-state-v1": transform_sobriety,
    "nextcloud-task-state-v1": transform_nextcloud_tasks,
}


def build_outputs(
    contract: dict[str, Any], source_root: Path
) -> tuple[dict[str, InputRecord], list[OutputRecord]]:
    inputs: dict[str, InputRecord] = {}
    outputs: list[OutputRecord] = []
    limits = contract["limits"]
    for transform in contract["transforms"]:
        selected = []
        for source_relative in transform["sources"]:
            if source_relative not in inputs:
                inputs[source_relative] = snapshot_input(
                    source_root / source_relative,
                    source_root,
                    limits["maxInputBytes"],
                )
            selected.append(inputs[source_relative])
        source_digest = hashlib.sha256(
            canonical_json(
                {
                    "transform": transform["id"],
                    "inputs": [
                        {"path": item.relative, "sha256": item.sha256}
                        for item in selected
                    ],
                }
            )
        ).hexdigest()
        transformer = TRANSFORMERS.get(transform["transform"])
        require(transformer is not None, f"transform-{transform['id']}-unknown")
        payload = canonical_json(transformer(selected, limits))
        require(len(payload) <= limits["maxOutputBytes"], f"transform-{transform['id']}-output-too-large")
        outputs.append(
            OutputRecord(
                transform_id=transform["id"],
                profile=transform["profile"],
                bucket="writable" if transform["ownerClass"] == "executor-writable" else "managed",
                target_relative=safe_relative(transform["output"], "transform-output-invalid").as_posix(),
                source_digest=source_digest,
                payload=payload,
            )
        )
    require(len(inputs) <= limits["maxInputs"], "transform-input-limit")
    require(sum(item.size for item in inputs.values()) <= limits["maxInputBytes"], "transform-input-byte-limit")
    require(len(outputs) <= limits["maxOutputs"], "transform-output-limit")
    require(sum(len(item.payload) for item in outputs) <= limits["maxOutputBytes"], "transform-output-byte-limit")
    return inputs, outputs


def source_set_digest(inputs: dict[str, InputRecord]) -> str:
    return hashlib.sha256(
        canonical_json(
            {
                "inputs": [
                    {"path": item.relative, "kind": item.kind, "sha256": item.sha256}
                    for item in sorted(inputs.values(), key=lambda row: row.relative)
                ]
            }
        )
    ).hexdigest()


def output_summary(inputs: dict[str, InputRecord], outputs: list[OutputRecord]) -> dict[str, Any]:
    return {
        "inputs": len(inputs),
        "inputBytes": sum(item.size for item in inputs.values()),
        "outputs": len(outputs),
        "outputBytes": sum(len(item.payload) for item in outputs),
        "profiles": {
            profile: {
                "outputs": sum(item.profile == profile for item in outputs),
                "writableOutputs": sum(item.profile == profile and item.bucket == "writable" for item in outputs),
                "managedOutputs": sum(item.profile == profile and item.bucket == "managed" for item in outputs),
            }
            for profile in ("astra", "dubble", "rigel")
        },
    }


def plan(
    contract_path: Path, repository_root: Path, source_root: Path
) -> tuple[dict[str, Any], str, dict[str, InputRecord], list[OutputRecord]]:
    contract, _, _, contract_hash = validate_contract(contract_path, repository_root)
    require(source_root.resolve() == Path(contract["sourceRoot"]).resolve(), "source-root-mismatch")
    try:
        metadata = source_root.lstat()
    except OSError as exc:
        raise TransformError("source-root-unavailable") from exc
    require(stat.S_ISDIR(metadata.st_mode) and not source_root.is_symlink(), "source-root-unsafe")
    inputs, outputs = build_outputs(contract, source_root.resolve())
    return contract, contract_hash, inputs, outputs


def ids(contract: dict[str, Any], profile: str, bucket: str) -> tuple[int, int]:
    if bucket == "writable":
        return contract["profiles"][profile]["uid"], contract["profiles"][profile]["gid"]
    return contract["ownership"]["operatorUid"], contract["profiles"][profile]["gid"]


def mode(contract: dict[str, Any], bucket: str, kind: str) -> int:
    key = (
        "writableDirectoryMode"
        if bucket == "writable" and kind == "directory"
        else "writableFileMode"
        if bucket == "writable"
        else "managedDirectoryMode"
        if kind == "directory"
        else "managedFileMode"
    )
    return int(contract["ownership"][key], 8)


def write_exclusive(path: Path, payload: bytes, uid: int, gid: int, file_mode: int) -> None:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        view = memoryview(payload)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fsync(descriptor)
        os.fchown(descriptor, uid, gid)
        os.fchmod(descriptor, file_mode)
    except OSError as exc:
        raise TransformError("transform-output-write-failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def create_generation(contract: dict[str, Any], target: Path, outputs: list[OutputRecord]) -> None:
    os.chown(target, contract["ownership"]["operatorUid"], contract["ownership"]["operatorGid"])
    os.chmod(target, int(contract["ownership"]["generationRootMode"], 8))
    for profile in ("astra", "dubble", "rigel"):
        profile_root = target / profile
        profile_root.mkdir(mode=0o750)
        os.chown(
            profile_root,
            contract["ownership"]["operatorUid"],
            contract["profiles"][profile]["gid"],
        )
        for bucket in ("writable", "managed"):
            root = profile_root / bucket
            root.mkdir(mode=0o750)
            uid, gid = ids(contract, profile, bucket)
            os.chown(root, uid, gid)
    directories: set[tuple[str, str, PurePosixPath]] = set()
    for output in outputs:
        relative = PurePosixPath(output.target_relative)
        directories.update(
            (output.profile, output.bucket, parent)
            for parent in relative.parents
            if parent != PurePosixPath(".")
        )
    for profile, bucket, relative in sorted(
        directories, key=lambda row: (row[0], row[1], len(row[2].parts), row[2].as_posix())
    ):
        path = target / profile / bucket / relative.as_posix()
        path.mkdir(mode=0o750, exist_ok=True)
        uid, gid = ids(contract, profile, bucket)
        os.chown(path, uid, gid)
        os.chmod(path, 0o750 if bucket == "managed" else mode(contract, bucket, "directory"))
    for output in outputs:
        path = target / output.profile / output.bucket / output.target_relative
        uid, gid = ids(contract, output.profile, output.bucket)
        write_exclusive(path, output.payload, uid, gid, mode(contract, output.bucket, "file"))
    for profile in contract["profiles"]:
        managed = target / profile / "managed"
        paths = [managed]
        for root, directories_found, _ in os.walk(managed):
            paths.extend(Path(root) / name for name in directories_found)
        for path in sorted(set(paths), key=lambda item: len(item.parts), reverse=True):
            os.chmod(path, mode(contract, "managed", "directory"))


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        payload = canonical_json(value)
        view = memoryview(payload)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fsync(descriptor)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def stage(
    contract_path: Path,
    repository_root: Path,
    source_root: Path,
    target_root: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    contract, contract_hash, inputs_before, outputs = plan(contract_path, repository_root, source_root)
    try:
        target_metadata = target_root.lstat()
    except OSError as exc:
        raise TransformError("target-root-unavailable") from exc
    require(stat.S_ISDIR(target_metadata.st_mode) and not target_root.is_symlink(), "target-root-unsafe")
    with os.scandir(target_root) as entries:
        require(next(entries, None) is None, "target-root-not-empty")
    create_generation(contract, target_root, outputs)
    inputs_after, outputs_after = build_outputs(contract, source_root.resolve())
    require(
        inputs_before.keys() == inputs_after.keys()
        and all(inputs_before[key].stability_tuple == inputs_after[key].stability_tuple for key in inputs_before),
        "transform-source-changed-during-stage",
    )
    require(
        [(item.transform_id, item.source_digest, item.sha256) for item in outputs]
        == [(item.transform_id, item.source_digest, item.sha256) for item in outputs_after],
        "transform-output-changed-during-stage",
    )
    summary = output_summary(inputs_before, outputs)
    manifest = {
        "schemaVersion": 1,
        "status": "ok",
        "contractSha256": contract_hash,
        "sourceSetSha256": source_set_digest(inputs_before),
        "summary": summary,
        "files": [
            {
                "transformId": item.transform_id,
                "profile": item.profile,
                "bucket": item.bucket,
                "targetRelative": item.target_relative,
                "sourceSha256": item.source_digest,
                "bytes": len(item.payload),
                "sha256": item.sha256,
            }
            for item in sorted(outputs, key=lambda row: (row.profile, row.bucket, row.target_relative))
        ],
    }
    write_json_atomic(manifest_path, manifest)
    verify(contract_path, repository_root, target_root, manifest_path, allow_writable_drift=False)
    return summary


def walk_generation(root: Path) -> tuple[list[Path], list[Path]]:
    paths: list[Path] = []
    directory_paths: list[Path] = []
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in directories:
            path = current_path / name
            require(not path.is_symlink(), "target-symlink-rejected")
            directory_paths.append(path)
        for name in files:
            path = current_path / name
            metadata = path.lstat()
            require(stat.S_ISREG(metadata.st_mode) and not path.is_symlink(), "target-special-rejected")
            paths.append(path)
    return paths, directory_paths


def verify(
    contract_path: Path,
    repository_root: Path,
    target_root: Path,
    manifest_path: Path,
    *,
    allow_writable_drift: bool,
) -> dict[str, Any]:
    contract, _, _, contract_hash = validate_contract(contract_path, repository_root)
    manifest = load_json_file(manifest_path, "manifest-invalid")
    require(
        set(manifest)
        == {"schemaVersion", "status", "contractSha256", "sourceSetSha256", "summary", "files"}
        and manifest["schemaVersion"] == 1
        and manifest["status"] == "ok"
        and manifest["contractSha256"] == contract_hash,
        "manifest-contract-invalid",
    )
    rows = manifest["files"]
    require(isinstance(rows, list) and len(rows) == 5, "manifest-files-invalid")
    expected_paths: set[Path] = set()
    for row in rows:
        require(
            isinstance(row, dict)
            and set(row)
            == {"transformId", "profile", "bucket", "targetRelative", "sourceSha256", "bytes", "sha256"},
            "manifest-row-invalid",
        )
        require(row["transformId"] in EXPECTED_TRANSFORMS, "manifest-transform-invalid")
        require(row["profile"] in contract["profiles"] and row["bucket"] in {"writable", "managed"}, "manifest-profile-invalid")
        relative = safe_relative(row["targetRelative"], "manifest-target-invalid")
        path = target_root / row["profile"] / row["bucket"] / relative.as_posix()
        require(path not in expected_paths, "manifest-target-duplicate")
        expected_paths.add(path)
        metadata = path.lstat()
        uid, gid = ids(contract, row["profile"], row["bucket"])
        require(
            stat.S_ISREG(metadata.st_mode)
            and not path.is_symlink()
            and metadata.st_uid == uid
            and metadata.st_gid == gid
            and stat.S_IMODE(metadata.st_mode) == mode(contract, row["bucket"], "file"),
            "manifest-file-metadata-drift",
        )
        if row["bucket"] == "managed" or not allow_writable_drift:
            require(metadata.st_size == row["bytes"] and file_sha256(path) == row["sha256"], "manifest-file-content-drift")
    for profile in contract["profiles"]:
        profile_root = target_root / profile
        profile_metadata = profile_root.lstat()
        require(
            stat.S_ISDIR(profile_metadata.st_mode)
            and not profile_root.is_symlink()
            and profile_metadata.st_uid == contract["ownership"]["operatorUid"]
            and profile_metadata.st_gid == contract["profiles"][profile]["gid"]
            and stat.S_IMODE(profile_metadata.st_mode) == 0o750,
            "profile-root-metadata-drift",
        )
        for bucket in ("writable", "managed"):
            root = profile_root / bucket
            root_metadata = root.lstat()
            uid, gid = ids(contract, profile, bucket)
            require(
                stat.S_ISDIR(root_metadata.st_mode)
                and not root.is_symlink()
                and root_metadata.st_uid == uid
                and root_metadata.st_gid == gid
                and stat.S_IMODE(root_metadata.st_mode)
                == mode(contract, bucket, "directory"),
                "bucket-root-metadata-drift",
            )
            actual_file_rows, actual_directory_rows = walk_generation(root)
            actual_files = set(actual_file_rows)
            actual_directories = set(actual_directory_rows)
            expected_bucket = {
                path for path in expected_paths if path.is_relative_to(root)
            }
            expected_directories = {
                parent
                for path in expected_bucket
                for parent in path.parents
                if parent != root and parent.is_relative_to(root)
            }
            if bucket == "managed" or not allow_writable_drift:
                require(actual_files == expected_bucket, "transform-file-inventory-drift")
                require(
                    actual_directories == expected_directories,
                    "transform-directory-inventory-drift",
                )
            else:
                for path in actual_files:
                    metadata = path.lstat()
                    require(
                        metadata.st_uid == uid
                        and metadata.st_gid == gid
                        and not (stat.S_IMODE(metadata.st_mode) & 0o111)
                        and not (stat.S_IMODE(metadata.st_mode) & 0o022),
                        "writable-transform-unsafe-drift",
                    )
            for path in actual_directories:
                metadata = path.lstat()
                require(
                    metadata.st_uid == uid
                    and metadata.st_gid == gid
                    and stat.S_IMODE(metadata.st_mode)
                    == mode(contract, bucket, "directory"),
                    "transform-directory-metadata-drift",
                )
    return manifest["summary"]


def verify_runtime(contract_path: Path, repository_root: Path, profile: str) -> None:
    contract, _, _, _ = validate_contract(contract_path, repository_root)
    require(profile in contract["profiles"], "runtime-profile-invalid")
    row = contract["profiles"][profile]
    require(
        os.geteuid() == row["uid"] and os.getegid() == row["gid"],
        "runtime-profile-identity-invalid",
    )
    for bucket, source_key, target_key, expected_read_only in (
        ("writable", "writableRoot", "writableRuntimeRoot", False),
        ("managed", "managedRoot", "managedRuntimeRoot", True),
    ):
        source = Path(row[source_key])
        target = Path(row[target_key])
        try:
            source_metadata = source.lstat()
            target_metadata = target.lstat()
            require(
                stat.S_ISDIR(source_metadata.st_mode)
                and stat.S_ISDIR(target_metadata.st_mode)
                and not source.is_symlink()
                and not target.is_symlink(),
                f"runtime-{bucket}-bind-unsafe",
            )
            require(source.samefile(target), f"runtime-{bucket}-bind-mismatch")
        except OSError as exc:
            raise TransformError(f"runtime-{bucket}-bind-unavailable") from exc
        try:
            read_only = bool(os.statvfs(target).f_flag & os.ST_RDONLY)
        except OSError as exc:
            raise TransformError(f"runtime-{bucket}-mount-mode-unavailable") from exc
        require(
            read_only == expected_read_only,
            f"runtime-{bucket}-mount-mode-invalid",
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--target-root", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--profile", choices=("astra", "dubble", "rigel"))
    parser.add_argument("--allow-writable-drift", action="store_true")
    parser.add_argument("--mode", choices=("plan", "stage", "verify", "runtime"), required=True)
    arguments = parser.parse_args()
    try:
        if arguments.mode == "plan":
            require(arguments.source_root is not None, "plan-source-required")
            contract, contract_hash, inputs, outputs = plan(
                arguments.contract, arguments.repository_root, arguments.source_root
            )
            result = {
                "status": "ok",
                "mode": "plan",
                "contractSha256": contract_hash,
                "sourceSetSha256": source_set_digest(inputs),
                "summary": output_summary(inputs, outputs),
            }
        elif arguments.mode == "stage":
            require(
                arguments.source_root is not None
                and arguments.target_root is not None
                and arguments.manifest is not None,
                "stage-paths-required",
            )
            result = {
                "status": "ok",
                "mode": "stage",
                "summary": stage(
                    arguments.contract,
                    arguments.repository_root,
                    arguments.source_root,
                    arguments.target_root,
                    arguments.manifest,
                ),
            }
        elif arguments.mode == "verify":
            require(arguments.target_root is not None and arguments.manifest is not None, "verify-paths-required")
            result = {
                "status": "ok",
                "mode": "verify",
                "summary": verify(
                    arguments.contract,
                    arguments.repository_root,
                    arguments.target_root,
                    arguments.manifest,
                    allow_writable_drift=arguments.allow_writable_drift,
                ),
            }
        else:
            require(arguments.profile is not None, "runtime-profile-required")
            verify_runtime(arguments.contract, arguments.repository_root, arguments.profile)
            result = {"status": "ok", "mode": "runtime", "profile": arguments.profile}
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (TransformError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
