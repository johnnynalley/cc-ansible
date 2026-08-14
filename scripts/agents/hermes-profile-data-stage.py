#!/usr/bin/env python3
"""Plan, stage, and verify isolated Hermes profile data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


COPY_BUFFER_SIZE = 1024 * 1024
SELECTED_MODES = {"data-stage", "operator-reference"}
BUCKET_BY_MODE = {
    "data-stage": "writable",
    "operator-reference": "managed",
}
SENSITIVE_COMPONENTS = {"credential", "credentials", "secret", "secrets"}
SENSITIVE_NAMES = {
    ".env",
    ".npmrc",
    "auth-profiles.json",
    "credentials.json",
    "secrets.json",
}
SENSITIVE_SUFFIXES = {".key", ".p12", ".pem", ".token"}
SAFETY_KEYS = {
    "sourceMutationAllowed",
    "sourceMountAllowed",
    "hardLinksAllowed",
    "symlinksAllowed",
    "specialFilesAllowed",
    "executableBitsRetained",
    "rawPromptInjectionAllowed",
    "memoryImportAllowed",
    "reviewerMemoryImportAllowed",
    "structuredTransformImportAllowed",
    "credentialImportAllowed",
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
CONTRACT_KEYS = {
    "schemaVersion",
    "mode",
    "sourceRoot",
    "sourcePins",
    "selectedImportModes",
    "profiles",
    "ownership",
    "limits",
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
LIMIT_KEYS = {"maxObjects", "maxTotalBytes", "maxSingleFileBytes"}


class ProfileDataError(RuntimeError):
    """Raised when a profile-data transaction is unsafe or incomplete."""


@dataclass(frozen=True)
class Record:
    source_relative: str
    target_relative: str
    profile: str
    bucket: str
    kind: str
    device: int
    inode: int
    size: int
    mtime_ns: int
    mode: int
    uid: int
    gid: int
    source: Path

    @property
    def stability_tuple(self) -> tuple[Any, ...]:
        return (
            self.source_relative,
            self.target_relative,
            self.profile,
            self.bucket,
            self.kind,
            self.device,
            self.inode,
            self.size,
            self.mtime_ns,
            self.mode,
            self.uid,
            self.gid,
        )


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise ProfileDataError(f"{label}-not-regular")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProfileDataError(f"{label}-invalid") from exc
    if not isinstance(payload, dict):
        raise ProfileDataError(f"{label}-invalid-root")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ProfileDataError("hash-input-not-regular")
        while True:
            chunk = os.read(descriptor, COPY_BUFFER_SIZE)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)
    except OSError as exc:
        raise ProfileDataError("hash-input-unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _safe_relative(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise ProfileDataError(f"{label}-unsafe")
    if any(ord(character) < 32 for character in value):
        raise ProfileDataError(f"{label}-unsafe")
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ProfileDataError(f"{label}-unsafe")
    return path


def _directory(path: Path, label: str, require_empty: bool = False) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ProfileDataError(f"{label}-unavailable") from exc
    if path.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise ProfileDataError(f"{label}-not-directory")
    if require_empty:
        with os.scandir(path) as entries:
            if next(entries, None) is not None:
                raise ProfileDataError(f"{label}-not-empty")
    return path.resolve()


def _looks_sensitive(relative: str) -> bool:
    path = PurePosixPath(relative)
    parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    return bool(
        parts.intersection(SENSITIVE_COMPONENTS)
        or name in SENSITIVE_NAMES
        or any(name.endswith(suffix) for suffix in SENSITIVE_SUFFIXES)
    )


def _validate_contract(
    contract: dict[str, Any], repository_root: Path
) -> tuple[dict[str, Any], dict[str, Any], str]:
    if set(contract) != CONTRACT_KEYS:
        raise ProfileDataError("contract-fields-invalid")
    if contract.get("schemaVersion") != 1:
        raise ProfileDataError("contract-schema-invalid")
    if contract.get("mode") != "inactive-reviewed-profile-data":
        raise ProfileDataError("contract-mode-invalid")
    if set(contract.get("selectedImportModes") or []) != SELECTED_MODES:
        raise ProfileDataError("contract-selected-modes-invalid")
    safety = contract.get("safety")
    if (
        not isinstance(safety, dict)
        or set(safety) != SAFETY_KEYS
        or any(value is not False for value in safety.values())
    ):
        raise ProfileDataError("contract-safety-authority-enabled")
    execution = contract.get("execution")
    if (
        not isinstance(execution, dict)
        or set(execution) != EXECUTION_KEYS
        or any(value is not True for value in execution.values())
    ):
        raise ProfileDataError("contract-execution-gate-disabled")
    limits = contract.get("limits")
    if not isinstance(limits, dict) or set(limits) != LIMIT_KEYS or any(
        not isinstance(limits.get(key), int) or isinstance(limits.get(key), bool)
        or limits[key] <= 0
        for key in ("maxObjects", "maxTotalBytes", "maxSingleFileBytes")
    ):
        raise ProfileDataError("contract-limits-invalid")
    profiles = contract.get("profiles")
    if not isinstance(profiles, dict) or set(profiles) != {"astra", "dubble", "rigel"}:
        raise ProfileDataError("contract-profiles-invalid")
    ownership = contract.get("ownership")
    if not isinstance(ownership, dict) or set(ownership) != OWNERSHIP_KEYS:
        raise ProfileDataError("contract-ownership-invalid")
    for key in ("operatorUid", "operatorGid"):
        if (
            not isinstance(ownership.get(key), int)
            or isinstance(ownership.get(key), bool)
            or ownership[key] < 0
        ):
            raise ProfileDataError(f"contract-{key}-invalid")
    for key in (
        "generationRootMode",
        "writableDirectoryMode",
        "writableFileMode",
        "managedDirectoryMode",
        "managedFileMode",
    ):
        value = ownership.get(key)
        if not isinstance(value, str) or len(value) != 4 or any(
            character not in "01234567" for character in value
        ):
            raise ProfileDataError(f"contract-{key}-invalid")
    expected_modes = {
        "generationRootMode": "0711",
        "writableDirectoryMode": "0750",
        "writableFileMode": "0640",
        "managedDirectoryMode": "0550",
        "managedFileMode": "0440",
    }
    if any(ownership[key] != value for key, value in expected_modes.items()):
        raise ProfileDataError("contract-ownership-mode-invalid")
    seen_paths: set[Path] = set()
    for name, profile in profiles.items():
        if not isinstance(profile, dict):
            raise ProfileDataError(f"profile-{name}-invalid")
        if set(profile) != PROFILE_KEYS:
            raise ProfileDataError(f"profile-{name}-fields-invalid")
        for key in ("uid", "gid"):
            if (
                not isinstance(profile.get(key), int)
                or isinstance(profile.get(key), bool)
                or profile[key] < 0
            ):
                raise ProfileDataError(f"profile-{name}-{key}-invalid")
        parsed_paths: dict[str, Path] = {}
        for key in (
            "writableRoot",
            "managedRoot",
            "writableRuntimeRoot",
            "managedRuntimeRoot",
        ):
            path = Path(str(profile.get(key, "")))
            if not path.is_absolute() or ".." in path.parts or path in seen_paths:
                raise ProfileDataError(f"profile-{name}-{key}-invalid")
            seen_paths.add(path)
            parsed_paths[key] = path
        if (
            parsed_paths["writableRoot"].name != "writable"
            or parsed_paths["managedRoot"].name != "managed"
            or parsed_paths["writableRoot"].parent
            != parsed_paths["managedRoot"].parent
            or parsed_paths["writableRoot"].parent.name != name
            or parsed_paths["writableRuntimeRoot"].name != "imported-data"
            or parsed_paths["managedRuntimeRoot"].name != "managed-data"
            or parsed_paths["writableRuntimeRoot"].parent
            != parsed_paths["managedRuntimeRoot"].parent
            or parsed_paths["writableRuntimeRoot"].parent.name != name
        ):
            raise ProfileDataError(f"profile-{name}-root-layout-invalid")
    source_pins = contract.get("sourcePins")
    if not isinstance(source_pins, dict) or set(source_pins) != {
        "profileImport",
        "workspacePolicy",
    }:
        raise ProfileDataError("contract-source-pins-invalid")
    loaded: dict[str, dict[str, Any]] = {}
    for key in ("profileImport", "workspacePolicy"):
        pin = source_pins.get(key)
        if not isinstance(pin, dict) or set(pin) != {"path", "sha256"}:
            raise ProfileDataError(f"source-pin-{key}-invalid")
        relative = _safe_relative(pin.get("path"), f"source-pin-{key}")
        source_path = repository_root / relative.as_posix()
        expected = pin.get("sha256")
        if not isinstance(expected, str) or len(expected) != 64:
            raise ProfileDataError(f"source-pin-{key}-hash-invalid")
        if _sha256(source_path) != expected:
            raise ProfileDataError(f"source-pin-{key}-hash-drift")
        loaded[key] = _load_json(source_path, f"source-pin-{key}")
    contract_hash = hashlib.sha256(
        json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return loaded["profileImport"], loaded["workspacePolicy"], contract_hash


def _selected_mappings(
    profile_import: dict[str, Any], workspace_policy: dict[str, Any]
) -> list[dict[str, Any]]:
    if profile_import.get("schemaVersion") != 1 or workspace_policy.get("schemaVersion") != 1:
        raise ProfileDataError("source-contract-schema-invalid")
    rules = {
        row.get("id"): row
        for row in workspace_policy.get("rules", [])
        if isinstance(row, dict)
    }
    selected: list[dict[str, Any]] = []
    for mapping in profile_import.get("workspaceMappings", []):
        if not isinstance(mapping, dict) or mapping.get("importMode") not in SELECTED_MODES:
            continue
        rule_id = mapping.get("sourceRuleId")
        rule = rules.get(rule_id)
        expected_owner = (
            "executor-writable"
            if mapping["importMode"] == "data-stage"
            else "operator-readonly"
        )
        if (
            not isinstance(rule, dict)
            or rule.get("disposition") != "retain"
            or rule.get("ownerClass") != expected_owner
            or mapping.get("ownerClass") != expected_owner
            or mapping.get("rawPromptInjection") is not False
            or rule.get("scope") not in {"exact", "tree"}
        ):
            raise ProfileDataError(f"mapping-{rule_id}-invalid")
        selected.append(
            {
                "id": rule_id,
                "scope": rule["scope"],
                "pattern": _safe_relative(rule["pattern"], f"mapping-{rule_id}").as_posix(),
                "sensitivity": rule.get("sensitivity"),
                "profile": mapping["profile"],
                "target": _safe_relative(
                    mapping["targetNamespace"], f"mapping-{rule_id}-target"
                ).as_posix(),
                "mode": mapping["importMode"],
                "bucket": BUCKET_BY_MODE[mapping["importMode"]],
            }
        )
    if len(selected) != 20 or len({row["id"] for row in selected}) != 20:
        raise ProfileDataError("selected-mapping-inventory-invalid")
    return selected


def _record(
    source_root: Path,
    source_path: Path,
    target_relative: PurePosixPath,
    mapping: dict[str, Any],
) -> Record:
    try:
        metadata = source_path.lstat()
    except OSError as exc:
        raise ProfileDataError(f"source-{mapping['id']}-unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode):
        kind = "symlink"
    elif stat.S_ISDIR(metadata.st_mode):
        kind = "directory"
    elif stat.S_ISREG(metadata.st_mode):
        kind = "file"
    else:
        kind = "special"
    source_relative = source_path.relative_to(source_root).as_posix()
    if kind in {"symlink", "special"}:
        raise ProfileDataError(f"retained-{kind}-rejected:{mapping['id']}")
    if _looks_sensitive(source_relative) and not mapping.get("sensitivity"):
        raise ProfileDataError(f"retained-sensitive-path-unclassified:{mapping['id']}")
    return Record(
        source_relative=source_relative,
        target_relative=target_relative.as_posix(),
        profile=mapping["profile"],
        bucket=mapping["bucket"],
        kind=kind,
        device=metadata.st_dev,
        inode=metadata.st_ino,
        size=metadata.st_size,
        mtime_ns=metadata.st_mtime_ns,
        mode=stat.S_IMODE(metadata.st_mode),
        uid=metadata.st_uid,
        gid=metadata.st_gid,
        source=source_path,
    )


def _snapshot(source_root: Path, mappings: list[dict[str, Any]]) -> dict[str, Record]:
    records: dict[str, Record] = {}
    targets: set[tuple[str, str, str]] = set()
    for mapping in mappings:
        selector = source_root / mapping["pattern"]
        if mapping["scope"] == "exact":
            candidates = [(selector, PurePosixPath(mapping["target"]))]
        else:
            try:
                metadata = selector.lstat()
            except OSError as exc:
                raise ProfileDataError(f"source-{mapping['id']}-unavailable") from exc
            if selector.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
                raise ProfileDataError(f"source-{mapping['id']}-not-directory")
            candidates = []
            pending = [selector]
            while pending:
                directory = pending.pop()
                relative_suffix = directory.relative_to(selector)
                candidates.append(
                    (directory, PurePosixPath(mapping["target"]) / relative_suffix)
                )
                try:
                    entries = sorted(os.scandir(directory), key=lambda item: item.name)
                except OSError as exc:
                    raise ProfileDataError(f"source-{mapping['id']}-unreadable") from exc
                for entry in entries:
                    path = Path(entry.path)
                    suffix = path.relative_to(selector)
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(path)
                    else:
                        candidates.append(
                            (path, PurePosixPath(mapping["target"]) / suffix)
                        )
        for source_path, target_relative in candidates:
            record = _record(source_root, source_path, target_relative, mapping)
            key = record.source_relative
            target_key = (record.profile, record.bucket, record.target_relative)
            if key in records or target_key in targets:
                raise ProfileDataError(f"profile-data-collision:{mapping['id']}")
            records[key] = record
            targets.add(target_key)
    return records


def _require_stable(before: dict[str, Record], after: dict[str, Record]) -> None:
    if before.keys() != after.keys() or any(
        before[key].stability_tuple != after[key].stability_tuple for key in before
    ):
        raise ProfileDataError("selected-source-changed-during-stage")


def _copy_regular(source: Path, target: Path, expected: Record) -> tuple[int, str]:
    source_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    target_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    source_fd = target_fd = -1
    digest = hashlib.sha256()
    copied = 0
    try:
        source_fd = os.open(source, source_flags)
        opened = os.fstat(source_fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
            != (expected.device, expected.inode, expected.size, expected.mtime_ns)
        ):
            raise ProfileDataError("source-file-changed-before-copy")
        target_fd = os.open(target, target_flags, 0o600)
        while True:
            chunk = os.read(source_fd, COPY_BUFFER_SIZE)
            if not chunk:
                break
            digest.update(chunk)
            copied += len(chunk)
            view = memoryview(chunk)
            while view:
                view = view[os.write(target_fd, view) :]
        os.fsync(target_fd)
        after = os.fstat(source_fd)
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
        ):
            raise ProfileDataError("source-file-changed-during-copy")
    except OSError as exc:
        raise ProfileDataError("profile-data-copy-failed") from exc
    finally:
        if target_fd >= 0:
            os.close(target_fd)
        if source_fd >= 0:
            os.close(source_fd)
    return copied, digest.hexdigest()


def _mode(contract: dict[str, Any], bucket: str, kind: str) -> int:
    ownership = contract["ownership"]
    key = (
        ("writableDirectoryMode" if kind == "directory" else "writableFileMode")
        if bucket == "writable"
        else ("managedDirectoryMode" if kind == "directory" else "managedFileMode")
    )
    return int(ownership[key], 8)


def _ids(contract: dict[str, Any], profile: str, bucket: str) -> tuple[int, int]:
    if bucket == "writable":
        return contract["profiles"][profile]["uid"], contract["profiles"][profile]["gid"]
    return contract["ownership"]["operatorUid"], contract["profiles"][profile]["gid"]


def _summary(records: dict[str, Record]) -> dict[str, Any]:
    files = [record for record in records.values() if record.kind == "file"]
    by_profile: dict[str, dict[str, int]] = {}
    for profile in ("astra", "dubble", "rigel"):
        profile_files = [record for record in files if record.profile == profile]
        by_profile[profile] = {
            "files": len(profile_files),
            "bytes": sum(record.size for record in profile_files),
            "writableFiles": sum(record.bucket == "writable" for record in profile_files),
            "managedFiles": sum(record.bucket == "managed" for record in profile_files),
        }
    return {
        "objects": len(records),
        "files": len(files),
        "bytes": sum(record.size for record in files),
        "profiles": by_profile,
    }


def _enforce_limits(contract: dict[str, Any], records: dict[str, Record]) -> None:
    summary = _summary(records)
    limits = contract["limits"]
    if summary["objects"] > limits["maxObjects"]:
        raise ProfileDataError("profile-data-object-limit-exceeded")
    if summary["bytes"] > limits["maxTotalBytes"]:
        raise ProfileDataError("profile-data-total-byte-limit-exceeded")
    if any(
        record.kind == "file" and record.size > limits["maxSingleFileBytes"]
        for record in records.values()
    ):
        raise ProfileDataError("profile-data-file-byte-limit-exceeded")


def plan(
    contract_path: Path, repository_root: Path, source_root: Path
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Record], str]:
    contract = _load_json(contract_path, "contract")
    profile_import, workspace_policy, contract_hash = _validate_contract(
        contract, repository_root
    )
    if source_root.resolve() != Path(contract["sourceRoot"]).resolve():
        raise ProfileDataError("source-root-contract-mismatch")
    source = _directory(source_root, "source-root")
    mappings = _selected_mappings(profile_import, workspace_policy)
    records = _snapshot(source, mappings)
    _enforce_limits(contract, records)
    return contract, profile_import, mappings, records, contract_hash


def _create_generation(
    contract: dict[str, Any], target_root: Path, records: dict[str, Record]
) -> None:
    for profile in ("astra", "dubble", "rigel"):
        profile_root = target_root / profile
        profile_root.mkdir(mode=0o750)
        os.chown(
            profile_root,
            contract["ownership"]["operatorUid"],
            contract["profiles"][profile]["gid"],
        )
        for bucket in ("writable", "managed"):
            root = profile_root / bucket
            root.mkdir(mode=0o750)
            uid, gid = _ids(contract, profile, bucket)
            os.chown(root, uid, gid)

    directories: set[tuple[str, str, PurePosixPath]] = set()
    for record in records.values():
        path = PurePosixPath(record.target_relative)
        if record.kind == "directory":
            directories.add((record.profile, record.bucket, path))
        directories.update(
            (record.profile, record.bucket, parent)
            for parent in path.parents
            if parent != PurePosixPath(".")
        )
    for profile, bucket, relative in sorted(
        directories, key=lambda row: (row[0], row[1], len(row[2].parts), str(row[2]))
    ):
        destination = target_root / profile / bucket / relative.as_posix()
        if not destination.exists():
            destination.mkdir(mode=0o750)
        uid, gid = _ids(contract, profile, bucket)
        os.chown(destination, uid, gid, follow_symlinks=False)
        os.chmod(
            destination,
            0o750 if bucket == "managed" else _mode(contract, bucket, "directory"),
        )


def _seal_managed_directories(contract: dict[str, Any], target_root: Path) -> None:
    for profile in contract["profiles"]:
        root = target_root / profile / "managed"
        directories = [
            path
            for path, _, kind in _walk_generation(root)
            if kind == "directory"
        ]
        directories.append(root)
        for path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
            os.chmod(path, _mode(contract, "managed", "directory"))


def stage(
    contract_path: Path,
    repository_root: Path,
    source_root: Path,
    target_root: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    contract, _, mappings, before, contract_hash = plan(
        contract_path, repository_root, source_root
    )
    target = _directory(target_root, "target-root", require_empty=True)
    os.chown(
        target,
        contract["ownership"]["operatorUid"],
        contract["ownership"]["operatorGid"],
    )
    os.chmod(target, int(contract["ownership"]["generationRootMode"], 8))
    _create_generation(contract, target, before)
    manifest_files: list[dict[str, Any]] = []
    for record in sorted(
        before.values(), key=lambda item: (item.profile, item.bucket, item.target_relative)
    ):
        if record.kind != "file":
            continue
        destination = target / record.profile / record.bucket / record.target_relative
        copied, digest = _copy_regular(record.source, destination, record)
        uid, gid = _ids(contract, record.profile, record.bucket)
        os.chown(destination, uid, gid, follow_symlinks=False)
        os.chmod(destination, _mode(contract, record.bucket, "file"))
        if _sha256(destination) != digest:
            raise ProfileDataError("profile-data-copy-hash-mismatch")
        manifest_files.append(
            {
                "profile": record.profile,
                "bucket": record.bucket,
                "sourceRelative": record.source_relative,
                "targetRelative": record.target_relative,
                "bytes": copied,
                "sha256": digest,
            }
        )
    _seal_managed_directories(contract, target)
    after = _snapshot(source_root.resolve(), mappings)
    _require_stable(before, after)
    manifest_directories = [
        {
            "profile": profile,
            "bucket": bucket,
            "targetRelative": path.relative_to(target / profile / bucket).as_posix(),
        }
        for profile in sorted(contract["profiles"])
        for bucket in ("managed", "writable")
        for path, _, kind in _walk_generation(target / profile / bucket)
        if kind == "directory"
    ]
    manifest_directories.sort(
        key=lambda row: (row["profile"], row["bucket"], row["targetRelative"])
    )
    manifest = {
        "schemaVersion": 1,
        "status": "ok",
        "contractSha256": contract_hash,
        "summary": _summary(before),
        "directories": manifest_directories,
        "files": manifest_files,
    }
    _write_json_atomic(manifest_path, manifest)
    verify(contract_path, repository_root, target, manifest_path, writable_drift=False)
    return manifest["summary"]


def _walk_generation(root: Path) -> list[tuple[Path, os.stat_result, str]]:
    rows: list[tuple[Path, os.stat_result, str]] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise ProfileDataError("target-generation-unreadable") from exc
        for entry in entries:
            path = Path(entry.path)
            metadata = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                kind = "symlink"
            elif stat.S_ISDIR(metadata.st_mode):
                kind = "directory"
                pending.append(path)
            elif stat.S_ISREG(metadata.st_mode):
                kind = "file"
            else:
                kind = "special"
            rows.append((path, metadata, kind))
    return rows


def _require_directory_metadata(
    path: Path, expected_uid: int, expected_gid: int, expected_mode: int, label: str
) -> None:
    directory = _directory(path, label)
    metadata = directory.stat()
    if metadata.st_uid != expected_uid or metadata.st_gid != expected_gid:
        raise ProfileDataError(f"{label}-owner-drift")
    if stat.S_IMODE(metadata.st_mode) != expected_mode:
        raise ProfileDataError(f"{label}-mode-drift")


def _validate_manifest(
    manifest: dict[str, Any], contract: dict[str, Any], contract_hash: str
) -> tuple[
    set[tuple[str, str]],
    set[tuple[str, str]],
    set[tuple[str, str]],
    set[tuple[str, str]],
    dict[str, Any],
]:
    if (
        set(manifest)
        != {
            "schemaVersion",
            "status",
            "contractSha256",
            "summary",
            "directories",
            "files",
        }
        or manifest.get("schemaVersion") != 1
        or manifest.get("status") != "ok"
        or manifest.get("contractSha256") != contract_hash
        or not isinstance(manifest.get("directories"), list)
        or not isinstance(manifest.get("files"), list)
        or not isinstance(manifest.get("summary"), dict)
    ):
        raise ProfileDataError("manifest-contract-invalid")
    expected_managed: set[tuple[str, str]] = set()
    expected_writable: set[tuple[str, str]] = set()
    expected_managed_directories: set[tuple[str, str]] = set()
    expected_writable_directories: set[tuple[str, str]] = set()
    for row in manifest["directories"]:
        if (
            not isinstance(row, dict)
            or set(row) != {"profile", "bucket", "targetRelative"}
            or row.get("profile") not in contract["profiles"]
            or row.get("bucket") not in {"writable", "managed"}
        ):
            raise ProfileDataError("manifest-directory-invalid")
        relative = _safe_relative(row.get("targetRelative"), "manifest-directory")
        key = (row["profile"], relative.as_posix())
        expected = (
            expected_writable_directories
            if row["bucket"] == "writable"
            else expected_managed_directories
        )
        if key in expected:
            raise ProfileDataError("manifest-directory-duplicate")
        expected.add(key)
    source_paths: set[str] = set()
    profile_summary = {
        profile: {"files": 0, "bytes": 0, "writableFiles": 0, "managedFiles": 0}
        for profile in contract["profiles"]
    }
    total_bytes = 0
    for row in manifest["files"]:
        if (
            not isinstance(row, dict)
            or set(row)
            != {
                "profile",
                "bucket",
                "sourceRelative",
                "targetRelative",
                "bytes",
                "sha256",
            }
            or row.get("profile") not in contract["profiles"]
        ):
            raise ProfileDataError("manifest-file-invalid")
        bucket = row.get("bucket")
        if bucket not in {"writable", "managed"}:
            raise ProfileDataError("manifest-file-bucket-invalid")
        source_relative = _safe_relative(row.get("sourceRelative"), "manifest-source")
        target_relative = _safe_relative(row.get("targetRelative"), "manifest-target")
        byte_count = row.get("bytes")
        digest = row.get("sha256")
        if (
            not isinstance(byte_count, int)
            or isinstance(byte_count, bool)
            or byte_count < 0
            or byte_count > contract["limits"]["maxSingleFileBytes"]
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ProfileDataError("manifest-file-metadata-invalid")
        source_key = source_relative.as_posix()
        target_key = (row["profile"], target_relative.as_posix())
        expected = expected_writable if bucket == "writable" else expected_managed
        if source_key in source_paths or target_key in expected:
            raise ProfileDataError("manifest-file-duplicate")
        source_paths.add(source_key)
        expected.add(target_key)
        profile_row = profile_summary[row["profile"]]
        profile_row["files"] += 1
        profile_row["bytes"] += byte_count
        profile_row[f"{bucket}Files"] += 1
        total_bytes += byte_count
    summary = manifest["summary"]
    if (
        set(summary) != {"objects", "files", "bytes", "profiles"}
        or not isinstance(summary.get("objects"), int)
        or isinstance(summary.get("objects"), bool)
        or summary["objects"] < len(manifest["files"])
        or summary["objects"] > contract["limits"]["maxObjects"]
        or summary.get("files") != len(manifest["files"])
        or summary.get("bytes") != total_bytes
        or total_bytes > contract["limits"]["maxTotalBytes"]
        or summary.get("profiles") != profile_summary
    ):
        raise ProfileDataError("manifest-summary-invalid")
    return (
        expected_managed,
        expected_writable,
        expected_managed_directories,
        expected_writable_directories,
        summary,
    )


def verify(
    contract_path: Path,
    repository_root: Path,
    target_root: Path,
    manifest_path: Path,
    writable_drift: bool,
) -> dict[str, Any]:
    contract = _load_json(contract_path, "contract")
    _, _, contract_hash = _validate_contract(contract, repository_root)
    target = _directory(target_root, "target-root")
    manifest = _load_json(manifest_path, "manifest")
    (
        _,
        _,
        expected_managed_directory_rows,
        expected_writable_directory_rows,
        _,
    ) = _validate_manifest(
        manifest, contract, contract_hash
    )
    _require_directory_metadata(
        target,
        contract["ownership"]["operatorUid"],
        contract["ownership"]["operatorGid"],
        int(contract["ownership"]["generationRootMode"], 8),
        "target-root",
    )
    expected_managed: set[Path] = set()
    expected_writable: set[Path] = set()
    for row in manifest["files"]:
        bucket = row.get("bucket")
        relative = _safe_relative(row.get("targetRelative"), "manifest-target")
        path = target / row["profile"] / bucket / relative.as_posix()
        expected = expected_writable if bucket == "writable" else expected_managed
        expected.add(path)
        if not writable_drift or bucket == "managed":
            if not path.is_file() or path.is_symlink():
                raise ProfileDataError("manifest-file-missing")
            if path.stat().st_size != row.get("bytes") or _sha256(path) != row.get("sha256"):
                raise ProfileDataError("manifest-file-hash-drift")
    actual_managed: set[Path] = set()
    actual_managed_directories: set[tuple[str, str]] = set()
    actual_writable_directories: set[tuple[str, str]] = set()
    try:
        top_entries = sorted(os.scandir(target), key=lambda item: item.name)
    except OSError as exc:
        raise ProfileDataError("target-root-unreadable") from exc
    if [entry.name for entry in top_entries] != sorted(contract["profiles"]) or any(
        not entry.is_dir(follow_symlinks=False) for entry in top_entries
    ):
        raise ProfileDataError("target-profile-inventory-drift")
    for profile in contract["profiles"]:
        profile_root = target / profile
        _require_directory_metadata(
            profile_root,
            contract["ownership"]["operatorUid"],
            contract["profiles"][profile]["gid"],
            0o750,
            f"target-{profile}",
        )
        try:
            profile_entries = sorted(os.scandir(profile_root), key=lambda item: item.name)
        except OSError as exc:
            raise ProfileDataError("target-profile-unreadable") from exc
        if [entry.name for entry in profile_entries] != ["managed", "writable"] or any(
            not entry.is_dir(follow_symlinks=False) for entry in profile_entries
        ):
            raise ProfileDataError("target-bucket-inventory-drift")
        for bucket in ("writable", "managed"):
            root = _directory(target / profile / bucket, f"target-{profile}-{bucket}")
            expected_uid, expected_gid = _ids(contract, profile, bucket)
            _require_directory_metadata(
                root,
                expected_uid,
                expected_gid,
                _mode(contract, bucket, "directory"),
                f"target-{profile}-{bucket}",
            )
            for path, metadata, kind in _walk_generation(root):
                if kind in {"symlink", "special"}:
                    raise ProfileDataError("target-object-kind-rejected")
                mode = stat.S_IMODE(metadata.st_mode)
                if metadata.st_uid != expected_uid or metadata.st_gid != expected_gid:
                    raise ProfileDataError("target-object-owner-drift")
                if kind == "file" and mode & 0o111:
                    raise ProfileDataError("target-executable-bit-rejected")
                if bucket == "managed":
                    if mode != _mode(contract, bucket, kind):
                        raise ProfileDataError("managed-object-mode-drift")
                    if kind == "file":
                        actual_managed.add(path)
                    else:
                        actual_managed_directories.add(
                            (profile, path.relative_to(root).as_posix())
                        )
                else:
                    allowed = _mode(contract, bucket, kind)
                    if mode & ~allowed or mode & 0o022:
                        raise ProfileDataError("writable-object-mode-unsafe")
                    if kind == "directory":
                        actual_writable_directories.add(
                            (profile, path.relative_to(root).as_posix())
                        )
    if actual_managed != expected_managed:
        raise ProfileDataError("managed-file-inventory-drift")
    if actual_managed_directories != expected_managed_directory_rows:
        raise ProfileDataError("managed-directory-inventory-drift")
    if not writable_drift:
        actual_writable = {
            path
            for profile in contract["profiles"]
            for path, _, kind in _walk_generation(target / profile / "writable")
            if kind == "file"
        }
        if actual_writable != expected_writable:
            raise ProfileDataError("writable-file-inventory-drift")
        if actual_writable_directories != expected_writable_directory_rows:
            raise ProfileDataError("writable-directory-inventory-drift")
    return {
        "status": "ok",
        "profiles": sorted(contract["profiles"]),
        "managedFiles": len(expected_managed),
        "writableBaselineFiles": len(expected_writable),
        "writableDriftAllowed": writable_drift,
    }


def verify_runtime(
    contract_path: Path,
    repository_root: Path,
    profile_name: str,
) -> dict[str, Any]:
    contract = _load_json(contract_path, "contract")
    _validate_contract(contract, repository_root)
    profile = contract["profiles"].get(profile_name)
    if not isinstance(profile, dict):
        raise ProfileDataError("runtime-profile-invalid")
    if os.geteuid() != profile["uid"] or os.getegid() != profile["gid"]:
        raise ProfileDataError("runtime-profile-identity-invalid")
    pairs = (
        (Path(profile["writableRoot"]), Path(profile["writableRuntimeRoot"]), "writable"),
        (Path(profile["managedRoot"]), Path(profile["managedRuntimeRoot"]), "managed"),
    )
    for source, runtime, label in pairs:
        _directory(source, f"runtime-{label}-source")
        _directory(runtime, f"runtime-{label}-mount")
        try:
            if not os.path.samefile(source, runtime):
                raise ProfileDataError(f"runtime-{label}-bind-mismatch")
        except OSError as exc:
            raise ProfileDataError(f"runtime-{label}-bind-unavailable") from exc
        try:
            read_only = bool(os.statvfs(runtime).f_flag & os.ST_RDONLY)
        except OSError as exc:
            raise ProfileDataError(f"runtime-{label}-mount-flags-unavailable") from exc
        if read_only != (label == "managed"):
            raise ProfileDataError(f"runtime-{label}-mount-mode-invalid")
    return {"status": "ok", "profile": profile_name, "runtimeBinds": 2}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    parent = _directory(path.parent, "output-parent")
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ProfileDataError("output-path-unsafe")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise ProfileDataError("output-write-failed") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--target-root", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument(
        "--mode", choices=("plan", "stage", "verify", "runtime"), required=True
    )
    parser.add_argument("--allow-writable-drift", action="store_true")
    parser.add_argument("--profile")
    arguments = parser.parse_args()
    try:
        if arguments.mode == "plan":
            if arguments.source_root is None:
                raise ProfileDataError("source-root-required")
            _, _, _, records, _ = plan(
                arguments.contract, arguments.repository_root, arguments.source_root
            )
            result = {"status": "ok", "mode": "plan", "summary": _summary(records)}
        elif arguments.mode == "stage":
            if None in (arguments.source_root, arguments.target_root, arguments.manifest):
                raise ProfileDataError("stage-paths-required")
            summary = stage(
                arguments.contract,
                arguments.repository_root,
                arguments.source_root,
                arguments.target_root,
                arguments.manifest,
            )
            result = {"status": "ok", "mode": "stage", "summary": summary}
        elif arguments.mode == "verify":
            if arguments.target_root is None or arguments.manifest is None:
                raise ProfileDataError("verify-paths-required")
            result = verify(
                arguments.contract,
                arguments.repository_root,
                arguments.target_root,
                arguments.manifest,
                arguments.allow_writable_drift,
            )
        else:
            if arguments.profile is None:
                raise ProfileDataError("runtime-profile-required")
            result = verify_runtime(
                arguments.contract,
                arguments.repository_root,
                arguments.profile,
            )
    except ProfileDataError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
