#!/usr/bin/env python3
"""Prune superseded OpenClaw rehearsal generations without breaking rollback."""

from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
import pwd
import re
import shutil
import stat
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STAMP = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")
MAX_PLAN_BYTES = 4 * 1024 * 1024
MAX_ROLLBACK_BYTES = 32 * 1024 * 1024
MAX_ROLLBACK_MEMBERS = 128


class RehearsalRetentionError(RuntimeError):
    """Raised when rehearsal generations cannot be classified safely."""


@dataclass(frozen=True)
class RootSpec:
    label: str
    generations_root: Path
    selector: Path
    selected_suffix: tuple[str, ...]


@dataclass(frozen=True)
class FamilyPolicy:
    name: str
    roots: tuple[RootSpec, ...]
    backup_root: Path
    control_uid: int
    content_uids: tuple[int, ...]
    content_gids: tuple[int, ...]
    quiescent_uids: tuple[int, ...]


def _fail(message: str) -> None:
    raise RehearsalRetentionError(message)


def _mode(metadata: os.stat_result) -> int:
    return stat.S_IMODE(metadata.st_mode)


def _owned_directory(path: Path, label: str, expected_uids: tuple[int, ...]) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RehearsalRetentionError(f"{label} is unavailable") from exc
    if path.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        _fail(f"{label} must be a non-symlink directory")
    if metadata.st_uid not in expected_uids:
        _fail(f"{label} has an unexpected owner")
    if _mode(metadata) & 0o022:
        _fail(f"{label} is group/world writable")
    return path.resolve(strict=True)


def _owner_only_directory(path: Path, label: str, expected_uid: int) -> Path:
    resolved = _owned_directory(path, label, (expected_uid,))
    metadata = resolved.lstat()
    if _mode(metadata) & 0o077:
        _fail(f"{label} must be owner-only")
    return resolved


def _owned_regular(
    path: Path,
    label: str,
    expected_uids: tuple[int, ...],
    max_bytes: int,
    *,
    owner_only: bool = True,
) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RehearsalRetentionError(f"{label} is unavailable") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        _fail(f"{label} must be a non-symlink regular file")
    if metadata.st_uid not in expected_uids:
        _fail(f"{label} has an unexpected owner")
    if owner_only:
        if _mode(metadata) & 0o077:
            _fail(f"{label} must be owner-only")
    elif _mode(metadata) & 0o022:
        _fail(f"{label} is group/world writable")
    if metadata.st_size > max_bytes:
        _fail(f"{label} is too large")
    return path.resolve(strict=True)


def _stamp_from_target(spec: RootSpec, target: Path) -> str:
    root = spec.generations_root.resolve(strict=True)
    try:
        resolved = target.resolve(strict=True)
        relative = resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise RehearsalRetentionError(
            f"{spec.label} selector target is outside its generation root"
        ) from exc
    expected_parts = 1 + len(spec.selected_suffix)
    if len(relative.parts) != expected_parts:
        _fail(f"{spec.label} selector target has an unexpected depth")
    stamp = relative.parts[0]
    if STAMP.fullmatch(stamp) is None:
        _fail(f"{spec.label} selector target has an invalid stamp")
    if tuple(relative.parts[1:]) != spec.selected_suffix:
        _fail(f"{spec.label} selector target has an unexpected suffix")
    return stamp


def _selector_stamp(spec: RootSpec) -> str:
    try:
        metadata = spec.selector.lstat()
    except OSError as exc:
        raise RehearsalRetentionError(
            f"{spec.label} current selector is unavailable"
        ) from exc
    if not stat.S_ISLNK(metadata.st_mode):
        _fail(f"{spec.label} current selector must be a symlink")
    target = Path(os.readlink(spec.selector))
    if not target.is_absolute():
        target = spec.selector.parent / target
    return _stamp_from_target(spec, target)


def _reject_additional_selectors(spec: RootSpec) -> None:
    try:
        entries = sorted(spec.selector.parent.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise RehearsalRetentionError(
            f"{spec.label} selector parent is unavailable"
        ) from exc
    generation_root = spec.generations_root.resolve(strict=True)
    for entry in entries:
        if entry == spec.selector or not entry.is_symlink():
            continue
        try:
            entry.resolve(strict=True).relative_to(generation_root)
        except (OSError, ValueError):
            continue
        _fail(f"{spec.label} has an additional generation selector")


def _rollback_stamp(policy: FamilyPolicy, selected_stamp: str) -> str | None:
    selected_backup = _owner_only_directory(
        policy.backup_root / selected_stamp,
        f"{policy.name} selected backup",
        policy.control_uid,
    )
    archive = selected_backup / "rollback.tar.gz"
    baseline = selected_backup / "EMPTY_BASELINE"
    if baseline.exists() or baseline.is_symlink():
        if archive.exists() or archive.is_symlink():
            _fail(f"{policy.name} selected backup has conflicting rollback evidence")
        _owned_regular(
            baseline,
            f"{policy.name} empty rollback baseline",
            (policy.control_uid,),
            MAX_PLAN_BYTES,
            owner_only=False,
        )
        return None

    archive = _owned_regular(
        archive,
        f"{policy.name} rollback archive",
        (policy.control_uid,),
        MAX_ROLLBACK_BYTES,
        owner_only=False,
    )
    expected_members = {
        spec.selector.as_posix().lstrip("/"): spec for spec in policy.roots
    }
    found: dict[str, str] = {}
    try:
        with tarfile.open(archive, mode="r:*") as handle:
            members = handle.getmembers()
    except (OSError, tarfile.TarError) as exc:
        raise RehearsalRetentionError(
            f"{policy.name} rollback archive is unreadable"
        ) from exc
    if len(members) > MAX_ROLLBACK_MEMBERS:
        _fail(f"{policy.name} rollback archive has too many members")
    for member in members:
        spec = expected_members.get(member.name.lstrip("./"))
        if spec is None:
            continue
        if spec.label in found:
            _fail(f"{policy.name} rollback archive duplicates a selector")
        if not member.issym():
            _fail(f"{policy.name} rollback selector member is not a symlink")
        target = Path(member.linkname)
        if not target.is_absolute():
            target = spec.selector.parent / target
        found[spec.label] = _stamp_from_target(spec, target)

    if not found:
        return None
    if set(found) != {spec.label for spec in policy.roots}:
        _fail(f"{policy.name} rollback archive has an incomplete selector set")
    stamps = set(found.values())
    if len(stamps) != 1:
        _fail(f"{policy.name} rollback selectors disagree on the prior generation")
    rollback_stamp = stamps.pop()
    if rollback_stamp == selected_stamp:
        _fail(f"{policy.name} rollback points to the selected generation")
    return rollback_stamp


def _metadata_record(relative: str, metadata: os.stat_result, link: str) -> bytes:
    payload = [
        relative,
        str(stat.S_IFMT(metadata.st_mode)),
        f"{_mode(metadata):04o}",
        str(metadata.st_uid),
        str(metadata.st_gid),
        str(metadata.st_size),
        str(metadata.st_mtime_ns),
        link,
    ]
    return ("\0".join(payload) + "\n").encode("utf-8", errors="surrogateescape")


def _assert_uids_quiescent(expected_uids: tuple[int, ...]) -> None:
    if not expected_uids:
        return
    protected_uids = set(expected_uids)
    current_pid = os.getpid()
    try:
        processes = sorted(Path("/proc").iterdir(), key=lambda entry: entry.name)
    except OSError as exc:
        raise RehearsalRetentionError(
            "cannot inspect generation writer processes"
        ) from exc
    for process in processes:
        if not process.name.isdigit() or int(process.name) == current_pid:
            continue
        try:
            status_lines = (process / "status").read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise RehearsalRetentionError(
                "cannot inspect generation writer processes"
            ) from exc
        uid_line = next(
            (line for line in status_lines if line.startswith("Uid:")), None
        )
        if uid_line is None:
            _fail("process status lacks a UID record")
        try:
            process_uids = {int(value) for value in uid_line.split()[1:]}
        except ValueError as exc:
            raise RehearsalRetentionError("process UID record is invalid") from exc
        if process_uids & protected_uids:
            _fail("generation writer identity has a live process")


def _require_symlink_safe_removal() -> None:
    if not getattr(shutil.rmtree, "avoids_symlink_attacks", False):
        _fail("platform lacks symlink-safe recursive removal")


def _tree_metadata(
    path: Path,
    expected_uids: tuple[int, ...],
    expected_gids: tuple[int, ...],
) -> dict[str, int | str]:
    digest = hashlib.sha256()
    allocated_bytes = 0
    entry_count = 0
    group_writable_entry_count = 0
    stack: list[tuple[Path, str]] = [(path, ".")]
    while stack:
        current, relative = stack.pop()
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise RehearsalRetentionError(
                "generation metadata changed during inspection"
            ) from exc
        if metadata.st_uid not in expected_uids:
            _fail("generation content has an unexpected owner")
        if metadata.st_gid not in expected_gids:
            _fail("generation content has an unexpected group")
        is_symlink = stat.S_ISLNK(metadata.st_mode)
        if not is_symlink:
            if _mode(metadata) & 0o002:
                _fail("generation content is world writable")
            if _mode(metadata) & 0o020:
                group_writable_entry_count += 1
        link = os.readlink(current) if is_symlink else ""
        digest.update(_metadata_record(relative, metadata, link))
        allocated_bytes += metadata.st_blocks * 512
        entry_count += 1
        if is_symlink or stat.S_ISREG(metadata.st_mode):
            continue
        if not stat.S_ISDIR(metadata.st_mode):
            _fail("generation contains an unsupported filesystem object")
        if current != path and os.path.ismount(current):
            _fail("generation contains a nested mount")
        try:
            children = sorted(current.iterdir(), key=lambda child: child.name)
        except OSError as exc:
            raise RehearsalRetentionError(
                "generation directory changed during inspection"
            ) from exc
        for child in reversed(children):
            child_relative = (
                child.name if relative == "." else f"{relative}/{child.name}"
            )
            stack.append((child, child_relative))
    return {
        "allocatedBytes": allocated_bytes,
        "entryCount": entry_count,
        "groupWritableEntryCount": group_writable_entry_count,
        "metadataSha256": digest.hexdigest(),
    }


def build_plan(policy: FamilyPolicy) -> dict[str, Any]:
    _require_symlink_safe_removal()
    _assert_uids_quiescent(policy.quiescent_uids)
    _owner_only_directory(
        policy.backup_root, f"{policy.name} backup root", policy.control_uid
    )
    selected_stamps: set[str] = set()
    generation_paths: dict[str, list[tuple[RootSpec, Path]]] = {}
    for spec in policy.roots:
        root = _owned_directory(
            spec.generations_root,
            f"{spec.label} generation root",
            (policy.control_uid,),
        )
        _reject_additional_selectors(spec)
        selected_stamps.add(_selector_stamp(spec))
        try:
            children = sorted(root.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            raise RehearsalRetentionError(
                f"{spec.label} generation root is unreadable"
            ) from exc
        for child in children:
            if STAMP.fullmatch(child.name) is None:
                _fail(f"{spec.label} generation root has an unclassified entry")
            _owned_directory(
                child,
                f"{spec.label} generation {child.name}",
                policy.content_uids,
            )
            if child.lstat().st_gid not in policy.content_gids:
                _fail(f"{spec.label} generation {child.name} has an unexpected group")
            generation_paths.setdefault(child.name, []).append((spec, child))

    if len(selected_stamps) != 1:
        _fail(f"{policy.name} current selectors disagree")
    selected_stamp = selected_stamps.pop()
    rollback_stamp = _rollback_stamp(policy, selected_stamp)
    keep_stamps = {selected_stamp}
    if rollback_stamp is not None:
        keep_stamps.add(rollback_stamp)

    for stamp in keep_stamps:
        retained_paths = generation_paths.get(stamp, [])
        present_labels = {spec.label for spec, _ in retained_paths}
        if present_labels != {spec.label for spec in policy.roots}:
            _fail(f"{policy.name} retained generation is incomplete")
        for spec, path in retained_paths:
            if path.lstat().st_uid != policy.control_uid:
                _fail(f"{spec.label} retained generation has an unexpected owner")

    delete_stamps = sorted(set(generation_paths) - keep_stamps)
    candidates: list[dict[str, Any]] = []
    reclaim = 0
    for stamp in delete_stamps:
        path_records: list[dict[str, Any]] = []
        for spec, path in sorted(
            generation_paths[stamp], key=lambda item: item[0].label
        ):
            metadata = _tree_metadata(
                path,
                policy.content_uids,
                policy.content_gids,
            )
            reclaim += int(metadata["allocatedBytes"])
            path_records.append(
                {
                    "label": spec.label,
                    "path": str(path),
                    **metadata,
                }
            )
        candidates.append({"stamp": stamp, "paths": path_records})

    return {
        "schemaVersion": 1,
        "family": policy.name,
        "selectedStamp": selected_stamp,
        "rollbackStamp": rollback_stamp,
        "keepStamps": sorted(keep_stamps),
        "deleteStamps": delete_stamps,
        "candidates": candidates,
        "estimatedReclaimBytes": reclaim,
    }


def _write_private(path: Path, payload: dict[str, Any]) -> None:
    parent = _owned_directory(path.parent, "evidence output parent", (0,))
    if path.exists() or path.is_symlink():
        _fail("evidence output already exists")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(payload, handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise RehearsalRetentionError("evidence output write failed") from exc


def _load_plan(path: Path, control_uid: int) -> dict[str, Any]:
    resolved = _owned_regular(path, "retention plan", (control_uid,), MAX_PLAN_BYTES)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RehearsalRetentionError("retention plan is invalid") from exc
    if not isinstance(payload, dict):
        _fail("retention plan has an unsupported shape")
    return payload


def apply_plan(policy: FamilyPolicy, plan_path: Path) -> dict[str, Any]:
    stored = _load_plan(plan_path, policy.control_uid)
    current = build_plan(policy)
    if stored != current:
        _fail("retention plan no longer matches live generation metadata")

    roots_by_label = {
        spec.label: spec.generations_root.resolve() for spec in policy.roots
    }
    removed_paths = 0
    for candidate in stored["candidates"]:
        for path_record in candidate["paths"]:
            label = path_record["label"]
            path = Path(path_record["path"])
            expected_parent = roots_by_label.get(label)
            if expected_parent is None or path.parent.resolve() != expected_parent:
                _fail("retention candidate escaped its generation root")
            shutil.rmtree(path)
            removed_paths += 1

    selected_stamps = {_selector_stamp(spec) for spec in policy.roots}
    if selected_stamps != {stored["selectedStamp"]}:
        _fail("current selector changed during retention apply")
    for stamp in stored["keepStamps"]:
        for spec in policy.roots:
            if not (spec.generations_root / stamp).is_dir():
                _fail("retained generation disappeared during retention apply")
    for stamp in stored["deleteStamps"]:
        for spec in policy.roots:
            candidate = spec.generations_root / stamp
            if candidate.exists() or candidate.is_symlink():
                _fail("superseded generation remains after retention apply")

    return {
        "schemaVersion": 1,
        "status": "ok",
        "mode": "apply",
        "family": policy.name,
        "selectedStamp": stored["selectedStamp"],
        "rollbackStamp": stored["rollbackStamp"],
        "removedGenerationCount": len(stored["deleteStamps"]),
        "removedPathCount": removed_paths,
        "estimatedReclaimedBytes": stored["estimatedReclaimBytes"],
    }


def _policy(name: str) -> FamilyPolicy:
    try:
        migrate_uid = pwd.getpwnam("openclaw-migrate").pw_uid
        migrate_gid = grp.getgrnam("openclaw-migrate").gr_gid
    except KeyError as exc:
        raise RehearsalRetentionError(
            "openclaw-migrate account or group is unavailable"
        ) from exc
    content_uids = (0, migrate_uid)
    content_gids = (0, migrate_gid)
    if name == "doctor":
        return FamilyPolicy(
            name="doctor",
            roots=(
                RootSpec(
                    "state",
                    Path("/var/lib/openclaw-doctor-rehearsal/generations"),
                    Path("/var/lib/openclaw-doctor-rehearsal/current"),
                    ("state",),
                ),
                RootSpec(
                    "workspace",
                    Path("/usr/local/share/openclaw-doctor-rehearsal/generations"),
                    Path("/usr/local/share/openclaw-doctor-rehearsal/current"),
                    ("workspace",),
                ),
                RootSpec(
                    "config",
                    Path("/etc/openclaw-doctor-rehearsal/generations"),
                    Path("/etc/openclaw-doctor-rehearsal/current"),
                    (),
                ),
            ),
            backup_root=Path("/var/backups/openclaw-doctor-rehearsal"),
            control_uid=0,
            content_uids=content_uids,
            content_gids=content_gids,
            quiescent_uids=(migrate_uid,),
        )
    if name == "state":
        return FamilyPolicy(
            name="state",
            roots=(
                RootSpec(
                    "state",
                    Path("/var/lib/openclaw-migration-rehearsal/generations"),
                    Path("/var/lib/openclaw-migration-rehearsal/current"),
                    ("state",),
                ),
                RootSpec(
                    "workspace",
                    Path("/usr/local/share/openclaw-migration-rehearsal/generations"),
                    Path("/usr/local/share/openclaw-migration-rehearsal/current"),
                    ("workspace",),
                ),
            ),
            backup_root=Path("/var/backups/openclaw-migration-rehearsal"),
            control_uid=0,
            content_uids=content_uids,
            content_gids=content_gids,
            quiescent_uids=(migrate_uid,),
        )
    _fail("unsupported rehearsal family")


def _summary(payload: dict[str, Any], mode: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "mode": mode,
        "family": payload["family"],
        "selectedStamp": payload["selectedStamp"],
        "rollbackStamp": payload["rollbackStamp"],
        "removedGenerationCount": payload.get(
            "removedGenerationCount", len(payload.get("deleteStamps", []))
        ),
        "removedPathCount": payload.get("removedPathCount", 0),
        "estimatedReclaimedBytes": payload.get(
            "estimatedReclaimedBytes", payload.get("estimatedReclaimBytes", 0)
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=("doctor", "state"), required=True)
    parser.add_argument("--mode", choices=("plan", "apply"), required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--plan", type=Path)
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            _fail("rehearsal retention must run as root")
        policy = _policy(args.family)
        if args.mode == "plan":
            if args.plan is not None:
                _fail("plan mode does not accept --plan")
            payload = build_plan(policy)
        else:
            if args.plan is None:
                _fail("apply mode requires --plan")
            payload = apply_plan(policy, args.plan)
        _write_private(args.output, payload)
    except RehearsalRetentionError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        return 1
    print(json.dumps(_summary(payload, args.mode), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
