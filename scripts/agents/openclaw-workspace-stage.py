#!/usr/bin/env python3
"""Build a verified modern OpenClaw workspace generation from reviewed inputs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

POLICY_MODULE_PATH = Path(__file__).with_name("openclaw-workspace-inventory.py")
POLICY_SPEC = importlib.util.spec_from_file_location(
    "openclaw_workspace_inventory", POLICY_MODULE_PATH
)
POLICY = importlib.util.module_from_spec(POLICY_SPEC)
assert POLICY_SPEC and POLICY_SPEC.loader
sys.modules[POLICY_SPEC.name] = POLICY
POLICY_SPEC.loader.exec_module(POLICY)

SCHEMA_VERSION = 1
COPY_BUFFER_SIZE = 1024 * 1024
OWNER_MODES = {
    "executor-writable": {"directory": 0o750, "file": 0o640},
    "operator-readonly": {"directory": 0o750, "file": 0o640},
}


class WorkspaceStageError(RuntimeError):
    """Raised when a workspace generation cannot be staged safely."""


@dataclass(frozen=True)
class SourceRecord:
    relative_path: str
    kind: str
    device: int
    inode: int
    size: int
    mtime_ns: int
    mode: int
    uid: int
    gid: int
    rule: Any | None = None

    @property
    def stability_tuple(self) -> tuple[Any, ...]:
        return (
            self.kind,
            self.device,
            self.inode,
            self.size,
            self.mtime_ns,
            self.mode,
            self.uid,
            self.gid,
            getattr(self.rule, "rule_id", None),
        )


@dataclass(frozen=True)
class TargetRecord:
    source: Path
    source_relative: str
    target_relative: str
    kind: str
    owner_class: str
    origin: str


def _safe_relative(value: str, label: str) -> PurePosixPath:
    if not value or value.startswith("/") or any(ord(char) < 32 for char in value):
        raise WorkspaceStageError(f"{label}-unsafe")
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise WorkspaceStageError(f"{label}-unsafe")
    return path


def _directory(path: Path, label: str) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise WorkspaceStageError(f"{label}-unavailable") from exc
    if path.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise WorkspaceStageError(f"{label}-not-directory")
    return path.resolve()


def _snapshot_tree(
    root: Path,
    rules: list[Any] | None = None,
) -> dict[str, SourceRecord]:
    records: dict[str, SourceRecord] = {}
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise WorkspaceStageError("source-enumeration-failed") from exc
        for entry in entries:
            relative = Path(entry.path).relative_to(root).as_posix()
            _safe_relative(relative, "source-path")
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise WorkspaceStageError("source-stat-failed") from exc
            if stat.S_ISDIR(metadata.st_mode):
                kind = "directory"
                pending.append(Path(entry.path))
            elif stat.S_ISREG(metadata.st_mode):
                kind = "file"
            elif stat.S_ISLNK(metadata.st_mode):
                kind = "symlink"
            else:
                kind = "special"
            rule = POLICY._select_rule(rules, relative) if rules is not None else None
            records[relative] = SourceRecord(
                relative_path=relative,
                kind=kind,
                device=metadata.st_dev,
                inode=metadata.st_ino,
                size=metadata.st_size,
                mtime_ns=metadata.st_mtime_ns,
                mode=stat.S_IMODE(metadata.st_mode),
                uid=metadata.st_uid,
                gid=metadata.st_gid,
                rule=rule,
            )
    return records


def _retained_target(relative: str, rule: Any) -> str:
    source_path = _safe_relative(relative, "retained-source")
    selector = _safe_relative(rule.pattern, "retained-selector")
    target_root = _safe_relative(rule.target, "retained-target")
    if rule.scope == "exact":
        if source_path != selector:
            raise WorkspaceStageError("exact-retain-selector-mismatch")
        return target_root.as_posix()
    if rule.scope != "tree":
        raise WorkspaceStageError("retained-glob-mapping-unsupported")
    try:
        suffix = source_path.relative_to(selector)
    except ValueError as exc:
        raise WorkspaceStageError("tree-retain-selector-mismatch") from exc
    return (target_root / suffix).as_posix()


def _build_target_plan(
    source: Path,
    source_records: dict[str, SourceRecord],
    overlay: Path,
    overlay_records: dict[str, SourceRecord],
) -> dict[str, TargetRecord]:
    planned: dict[str, TargetRecord] = {}

    def add(record: TargetRecord) -> None:
        _safe_relative(record.target_relative, "target-path")
        existing = planned.get(record.target_relative)
        if existing is not None:
            raise WorkspaceStageError("workspace-target-collision")
        planned[record.target_relative] = record

    for relative, source_record in sorted(source_records.items()):
        rule = source_record.rule
        if rule.disposition != "retain":
            continue
        if source_record.kind in {"symlink", "special"}:
            raise WorkspaceStageError("retained-object-kind-unsupported")
        target_relative = _retained_target(relative, rule)
        add(
            TargetRecord(
                source=source / relative,
                source_relative=relative,
                target_relative=target_relative,
                kind=source_record.kind,
                owner_class=rule.owner_class,
                origin="retained",
            )
        )

    for relative, overlay_record in sorted(overlay_records.items()):
        if overlay_record.kind in {"symlink", "special"}:
            raise WorkspaceStageError("overlay-object-kind-unsupported")
        add(
            TargetRecord(
                source=overlay / relative,
                source_relative=relative,
                target_relative=relative,
                kind=overlay_record.kind,
                owner_class="operator-readonly",
                origin="modern-overlay",
            )
        )

    file_targets = {
        PurePosixPath(relative)
        for relative, record in planned.items()
        if record.kind == "file"
    }
    for relative in planned:
        path = PurePosixPath(relative)
        if any(parent in file_targets for parent in path.parents):
            raise WorkspaceStageError("workspace-target-parent-is-file")
    writable_directories = {
        PurePosixPath(relative)
        for relative, record in planned.items()
        if record.kind == "directory" and record.owner_class == "executor-writable"
    }
    for relative, record in planned.items():
        if record.owner_class != "operator-readonly":
            continue
        if any(
            parent in writable_directories for parent in PurePosixPath(relative).parents
        ):
            raise WorkspaceStageError("readonly-target-under-writable-directory")
    return planned


def _owner_ids(
    owner_class: str,
    executor_uid: int,
    workspace_gid: int,
    operator_uid: int,
    operator_gid: int,
) -> tuple[int, int]:
    if owner_class == "executor-writable":
        return executor_uid, workspace_gid
    if owner_class == "operator-readonly":
        return operator_uid, operator_gid
    raise WorkspaceStageError("unknown-owner-class")


def _copy_regular_file(source: Path, target: Path) -> tuple[int, str]:
    try:
        before = source.lstat()
    except OSError as exc:
        raise WorkspaceStageError("source-file-unavailable") from exc
    if source.is_symlink() or not stat.S_ISREG(before.st_mode):
        raise WorkspaceStageError("source-file-not-regular")
    source_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    target_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    digest = hashlib.sha256()
    copied = 0
    source_descriptor = -1
    target_descriptor = -1
    try:
        source_descriptor = os.open(source, source_flags)
        opened = os.fstat(source_descriptor)
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
        ) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
            raise WorkspaceStageError("source-file-changed-before-copy")
        target_descriptor = os.open(target, target_flags, 0o600)
        while True:
            chunk = os.read(source_descriptor, COPY_BUFFER_SIZE)
            if not chunk:
                break
            digest.update(chunk)
            copied += len(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(target_descriptor, view)
                view = view[written:]
        os.fsync(target_descriptor)
        after = os.fstat(source_descriptor)
        if (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns):
            raise WorkspaceStageError("source-file-changed-during-copy")
    except OSError as exc:
        raise WorkspaceStageError("workspace-file-copy-failed") from exc
    finally:
        if target_descriptor >= 0:
            os.close(target_descriptor)
        if source_descriptor >= 0:
            os.close(source_descriptor)
    return copied, digest.hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise WorkspaceStageError("target-file-not-regular")
        while True:
            chunk = os.read(descriptor, COPY_BUFFER_SIZE)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)
    except OSError as exc:
        raise WorkspaceStageError("target-file-verification-failed") from exc
    finally:
        if "descriptor" in locals():
            os.close(descriptor)


def _require_stable_snapshot(
    before: dict[str, SourceRecord], after: dict[str, SourceRecord], label: str
) -> None:
    if before.keys() != after.keys() or any(
        before[path].stability_tuple != after[path].stability_tuple for path in before
    ):
        raise WorkspaceStageError(f"{label}-changed-during-stage")


def _prepare_workspace_plan(
    source_root: Path,
    overlay_root: Path,
    policy_path: Path,
) -> tuple[
    Path,
    Path,
    dict[str, SourceRecord],
    dict[str, SourceRecord],
    dict[str, TargetRecord],
    str,
]:
    source = _directory(source_root, "source-root")
    overlay = _directory(overlay_root, "overlay-root")
    if (
        source == overlay
        or source.is_relative_to(overlay)
        or overlay.is_relative_to(source)
    ):
        raise WorkspaceStageError("workspace-input-roots-overlap")
    rules, archive_contract = POLICY.load_policy(policy_path)
    source_records = _snapshot_tree(source, rules)
    overlay_records = _snapshot_tree(overlay)
    plan = _build_target_plan(source, source_records, overlay, overlay_records)
    return (
        source,
        overlay,
        source_records,
        overlay_records,
        plan,
        archive_contract,
    )


def plan_workspace(
    source_root: Path,
    overlay_root: Path,
    policy_path: Path,
) -> dict[str, Any]:
    (
        source,
        overlay,
        source_before,
        overlay_before,
        plan,
        archive_contract,
    ) = _prepare_workspace_plan(source_root, overlay_root, policy_path)
    # Reuse the already parsed rule objects attached to the first snapshot.
    rules = list(
        {record.rule.rule_id: record.rule for record in source_before.values()}.values()
    )
    source_after = _snapshot_tree(source, rules)
    overlay_after = _snapshot_tree(overlay)
    _require_stable_snapshot(source_before, source_after, "source-workspace")
    _require_stable_snapshot(overlay_before, overlay_after, "modern-overlay")
    files = [record for record in plan.values() if record.kind == "file"]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "ok",
        "mode": "plan",
        "archiveContract": archive_contract,
        "summary": {
            "sourceObjects": len(source_before),
            "overlayObjects": len(overlay_before),
            "plannedObjects": len(plan),
            "plannedFiles": len(files),
            "plannedBytes": sum(
                (
                    source_before[record.source_relative].size
                    if record.origin == "retained"
                    else overlay_before[record.source_relative].size
                )
                for record in files
            ),
            "filesByOrigin": {
                origin: sum(1 for record in files if record.origin == origin)
                for origin in ("retained", "modern-overlay")
            },
            "filesByOwnerClass": {
                owner_class: sum(
                    1 for record in files if record.owner_class == owner_class
                )
                for owner_class in ("executor-writable", "operator-readonly")
            },
        },
    }


def stage_workspace(
    source_root: Path,
    overlay_root: Path,
    target_root: Path,
    policy_path: Path,
    executor_uid: int,
    workspace_gid: int,
    operator_uid: int,
    operator_gid: int,
) -> dict[str, Any]:
    (
        source,
        overlay,
        source_before,
        overlay_before,
        plan,
        archive_contract,
    ) = _prepare_workspace_plan(source_root, overlay_root, policy_path)
    target = _directory(target_root, "target-root")
    roots = (source, overlay, target)
    if any(
        left != right and (left.is_relative_to(right) or right.is_relative_to(left))
        for index, left in enumerate(roots)
        for right in roots[index + 1 :]
    ):
        raise WorkspaceStageError("target-overlaps-source")
    with os.scandir(target) as target_entries:
        if next(target_entries, None) is not None:
            raise WorkspaceStageError("target-root-not-empty")
    rules = list(
        {record.rule.rule_id: record.rule for record in source_before.values()}.values()
    )

    explicit_directories = {
        PurePosixPath(relative): record
        for relative, record in plan.items()
        if record.kind == "directory"
    }
    required_directories: set[PurePosixPath] = set(explicit_directories)
    for relative in plan:
        required_directories.update(PurePosixPath(relative).parents)
    required_directories.discard(PurePosixPath("."))

    for relative in sorted(required_directories, key=lambda item: len(item.parts)):
        destination = target / relative.as_posix()
        destination.mkdir(mode=0o750)
        record = explicit_directories.get(relative)
        owner_class = record.owner_class if record else "operator-readonly"
        uid, gid = _owner_ids(
            owner_class,
            executor_uid,
            workspace_gid,
            operator_uid,
            operator_gid,
        )
        os.chown(destination, uid, gid, follow_symlinks=False)
        os.chmod(destination, OWNER_MODES[owner_class]["directory"])

    file_manifest: list[dict[str, Any]] = []
    origin_counts = {"retained": 0, "modern-overlay": 0}
    owner_counts = {"executor-writable": 0, "operator-readonly": 0}
    total_bytes = 0
    for relative, record in sorted(plan.items()):
        if record.kind != "file":
            continue
        destination = target / relative
        copied, source_hash = _copy_regular_file(record.source, destination)
        target_hash = _sha256(destination)
        if target_hash != source_hash:
            raise WorkspaceStageError("workspace-file-hash-mismatch")
        uid, gid = _owner_ids(
            record.owner_class,
            executor_uid,
            workspace_gid,
            operator_uid,
            operator_gid,
        )
        os.chown(destination, uid, gid, follow_symlinks=False)
        os.chmod(destination, OWNER_MODES[record.owner_class]["file"])
        source_metadata = record.source.stat(follow_symlinks=False)
        os.utime(
            destination,
            ns=(source_metadata.st_atime_ns, source_metadata.st_mtime_ns),
            follow_symlinks=False,
        )
        total_bytes += copied
        origin_counts[record.origin] += 1
        owner_counts[record.owner_class] += 1
        file_manifest.append(
            {
                "origin": record.origin,
                "ownerClass": record.owner_class,
                "sourceRelative": record.source_relative,
                "targetRelative": record.target_relative,
                "bytes": copied,
                "sha256": target_hash,
            }
        )

    source_after = _snapshot_tree(source, rules)
    overlay_after = _snapshot_tree(overlay)
    _require_stable_snapshot(source_before, source_after, "source-workspace")
    _require_stable_snapshot(overlay_before, overlay_after, "modern-overlay")

    target_records = _snapshot_tree(target)
    expected_target_paths = set(plan) | {
        relative.as_posix() for relative in required_directories
    }
    if set(target_records) != expected_target_paths:
        raise WorkspaceStageError("target-generation-has-unplanned-paths")
    for relative, target_record in target_records.items():
        planned_record = plan.get(relative)
        owner_class = (
            planned_record.owner_class
            if planned_record is not None
            else "operator-readonly"
        )
        expected_uid, expected_gid = _owner_ids(
            owner_class,
            executor_uid,
            workspace_gid,
            operator_uid,
            operator_gid,
        )
        if target_record.kind not in {"directory", "file"}:
            raise WorkspaceStageError("target-generation-object-kind-invalid")
        if (
            target_record.uid != expected_uid
            or target_record.gid != expected_gid
            or target_record.mode != OWNER_MODES[owner_class][target_record.kind]
        ):
            raise WorkspaceStageError("target-generation-ownership-invalid")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "ok",
        "archiveContract": archive_contract,
        "summary": {
            "sourceObjects": len(source_before),
            "targetObjects": len(target_records),
            "files": len(file_manifest),
            "bytes": total_bytes,
            "filesByOrigin": origin_counts,
            "filesByOwnerClass": owner_counts,
        },
        "files": file_manifest,
    }


def _write_json_atomic(path: Path, payload: Any) -> None:
    parent = _directory(path.parent, "output-parent")
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise WorkspaceStageError("output-not-regular-file")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
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
        raise WorkspaceStageError("output-write-failed") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--overlay", required=True, type=Path)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--executor-uid", type=int)
    parser.add_argument("--workspace-gid", type=int)
    parser.add_argument("--operator-uid", type=int, default=0)
    parser.add_argument("--operator-gid", type=int)
    arguments = parser.parse_args()
    try:
        if arguments.plan_only:
            report = plan_workspace(
                arguments.source,
                arguments.overlay,
                arguments.policy,
            )
        else:
            if (
                arguments.target is None
                or arguments.executor_uid is None
                or arguments.workspace_gid is None
                or arguments.operator_gid is None
            ):
                raise WorkspaceStageError("stage-ownership-arguments-required")
            report = stage_workspace(
                arguments.source,
                arguments.overlay,
                arguments.target,
                arguments.policy,
                arguments.executor_uid,
                arguments.workspace_gid,
                arguments.operator_uid,
                arguments.operator_gid,
            )
        _write_json_atomic(arguments.output, report)
    except (WorkspaceStageError, POLICY.WorkspaceInventoryError, OSError) as exc:
        print(
            json.dumps(
                {"status": "error", "errorCode": "workspace-stage-failed"},
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps({"status": "ok", "summary": report["summary"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
