#!/usr/bin/env python3
"""Manifest, relocate, and verify OpenClaw file-backed session stores."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

DERIVED_SESSION_SNAPSHOT_FIELDS = {
    "skillsSnapshot",
    "systemPromptReport",
}
TRANSIENT_ACTIVE_RUNTIME_STATE_FIELDS = {
    "contextBudgetStatus",
    "contextTokens",
    "fallbackNoticeActiveModel",
    "fallbackNoticeReason",
    "fallbackNoticeSelectedModel",
    "liveModelSwitchPending",
    "model",
    "modelProvider",
    "systemSent",
}
MODEL_OVERRIDE_FIELDS = {
    "modelOverride",
    "modelOverrideFallbackOriginModel",
    "modelOverrideFallbackOriginProvider",
    "modelOverrideSource",
    "providerOverride",
}
AUTH_OVERRIDE_FIELDS = {
    "authProfileOverride",
    "authProfileOverrideCompactionCount",
    "authProfileOverrideSource",
}
MIGRATION_BLOCKING_ACTIVE_RUNTIME_FIELDS = {
    "agentRuntimeOverride",
    "elevatedLevel",
    "execAsk",
    "execHost",
    "execNode",
    "execSecurity",
}
DELIVERY_RECOVERY_FIELDS = {
    "pendingFinalDelivery",
    "pendingFinalDeliveryAttemptCount",
    "pendingFinalDeliveryContext",
    "pendingFinalDeliveryCreatedAt",
    "pendingFinalDeliveryIntentId",
    "pendingFinalDeliveryLastAttemptAt",
    "pendingFinalDeliveryLastError",
    "pendingFinalDeliveryText",
    "restartRecoveryDeliveryContext",
    "restartRecoveryDeliveryRunId",
}


class SessionRelocationError(RuntimeError):
    """Raised when a session store cannot be relocated without ambiguity."""


def _resolved_directory(path: Path, label: str) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SessionRelocationError(f"{label} is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        raise SessionRelocationError(f"{label} must be a non-symlink directory")
    return path.resolve()


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _is_lexically_within(root: Path, candidate: Path) -> bool:
    return _is_within(Path(os.path.abspath(root)), Path(os.path.abspath(candidate)))


def _regular_file(path: Path, label: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SessionRelocationError(f"{label} is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise SessionRelocationError(f"{label} must be a non-symlink regular file")
    return metadata


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_store(path: Path) -> dict[str, Any]:
    _regular_file(path, "session index")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SessionRelocationError("session index is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise SessionRelocationError("session index must contain a JSON object")
    return payload


def _classify_file(name: str) -> str:
    if name == "sessions.json":
        return "index"
    if any(marker in name for marker in (".deleted.", ".bak", ".backup")):
        return "deleted_or_backup"
    if name.endswith(".trajectory.jsonl"):
        return "trajectory_jsonl"
    if name.endswith(".trajectory-path.json"):
        return "trajectory_path"
    if name.endswith(".jsonl"):
        return "session_jsonl"
    return "other"


def _session_files(state_root: Path, sessions_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for directory, directory_names, file_names in os.walk(sessions_dir):
        directory_path = Path(directory)
        for name in directory_names:
            if (directory_path / name).is_symlink():
                raise SessionRelocationError(
                    "session tree contains a symlink directory"
                )
        for name in file_names:
            file_path = directory_path / name
            metadata = _regular_file(file_path, "session artifact")
            resolved = file_path.resolve()
            if not _is_within(state_root, resolved):
                raise SessionRelocationError("session artifact escapes the state root")
            rows.append(
                {
                    "relativePath": str(file_path.relative_to(state_root)),
                    "kind": _classify_file(name),
                    "size": metadata.st_size,
                    "mtimeNs": metadata.st_mtime_ns,
                    "mode": stat.S_IMODE(metadata.st_mode),
                    "sha256": _sha256(file_path),
                }
            )
    return sorted(rows, key=lambda row: row["relativePath"])


def _path_category(
    value: str,
    state_root: Path,
    workspace_root: Path,
) -> str | None:
    candidate = Path(value)
    if not candidate.is_absolute():
        return None
    if _is_lexically_within(workspace_root, candidate):
        return "workspace"
    if _is_lexically_within(state_root, candidate):
        return "state"
    return "outside"


def _reference_role(key_path: tuple[str | int, ...]) -> str | None:
    """Classify only exact, reviewed SessionEntry path locations."""

    if len(key_path) < 2 or not isinstance(key_path[0], str):
        return None
    relative = key_path[1:]
    direct_roles = {
        ("sessionFile",): "session-transcript",
        ("workspaceDir",): "active-workspace",
        ("spawnedWorkspaceDir",): "spawned-workspace",
        ("spawnedCwd",): "spawned-cwd",
    }
    if relative in direct_roles:
        return direct_roles[relative]
    if relative == ("systemPromptReport", "workspaceDir"):
        return "derived-bootstrap-root"
    if (
        len(relative) == 4
        and relative[0] == "systemPromptReport"
        and relative[1] == "injectedWorkspaceFiles"
        and isinstance(relative[2], int)
        and relative[3] == "path"
    ):
        return "derived-bootstrap-path"
    return None


def _redacted_metadata_location(key_path: tuple[str | int, ...]) -> str:
    """Describe a SessionEntry field path without exposing the session key."""

    relative = key_path[1:] if key_path else ()
    return "/".join(str(component) for component in relative) or "<entry>"


def _collect_references(
    payload: Any,
    state_root: Path,
    workspace_root: Path,
) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []

    def visit(value: Any, key_path: tuple[str | int, ...] = ()) -> None:
        if isinstance(value, str):
            category = _path_category(value, state_root, workspace_root)
            if category is None:
                return
            role = _reference_role(key_path)
            if role is None:
                if category in {"state", "workspace"}:
                    raise SessionRelocationError(
                        "managed-root path found in an unapproved metadata location: "
                        + _redacted_metadata_location(key_path)
                    )
                return
            if category == "outside":
                raise SessionRelocationError(
                    "approved metadata path points outside the managed roots"
                )
            candidate = Path(value)
            try:
                resolved = candidate.resolve(strict=True)
            except OSError as exc:
                raise SessionRelocationError(
                    "approved metadata path does not resolve"
                ) from exc
            expected_root = workspace_root if category == "workspace" else state_root
            if not _is_within(expected_root, resolved):
                raise SessionRelocationError(
                    "approved metadata path resolves outside its managed root"
                )
            relative = candidate.relative_to(expected_root)
            if ".." in relative.parts:
                raise SessionRelocationError(
                    "approved metadata path contains parent traversal"
                )
            current = expected_root
            for component in relative.parts:
                current /= component
                if current.is_symlink():
                    raise SessionRelocationError(
                        "approved metadata path traverses a symlink"
                    )
            if "\n" in str(relative) or "\x00" in str(relative):
                raise SessionRelocationError(
                    "approved metadata path contains an unsupported separator"
                )
            if resolved.is_dir():
                path_kind = "directory"
            elif resolved.is_file():
                path_kind = "file"
            else:
                raise SessionRelocationError(
                    "approved metadata path is not a regular file or directory"
                )
            references.append(
                {
                    "field": str(key_path[-1]),
                    "role": role,
                    "category": category,
                    "relativePath": str(relative) or ".",
                    "pathKind": path_kind,
                }
            )
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, (*key_path, index))
            return
        if isinstance(value, dict):
            for child_field, item in value.items():
                visit(item, (*key_path, child_field))

    visit(payload)
    return references


def inspect_session_stores(
    state_root: Path,
    workspace_root: Path,
    agents: list[str],
) -> dict[str, Any]:
    resolved_state = _resolved_directory(state_root, "state root")
    resolved_workspace = _resolved_directory(workspace_root, "workspace root")
    if _is_within(resolved_workspace, resolved_state):
        raise SessionRelocationError("state root must not be inside the workspace root")
    if not agents:
        raise SessionRelocationError("at least one agent is required")

    agent_reports: list[dict[str, Any]] = []
    aggregate_kinds: Counter[str] = Counter()
    aggregate_fields: Counter[str] = Counter()
    aggregate_roles: Counter[str] = Counter()
    aggregate_categories: Counter[str] = Counter()
    aggregate_bytes = 0
    aggregate_entries = 0
    aggregate_delivery_recovery_entries = 0
    aggregate_delivery_recovery_fields: Counter[str] = Counter()

    for agent in agents:
        if not agent or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789-_"
            for character in agent
        ):
            raise SessionRelocationError("agent id contains unsupported characters")
        sessions_dir = resolved_state / "agents" / agent / "sessions"
        resolved_sessions = _resolved_directory(
            sessions_dir, "agent sessions directory"
        )
        if not _is_within(resolved_state, resolved_sessions):
            raise SessionRelocationError(
                "agent sessions directory escapes the state root"
            )
        index_path = resolved_sessions / "sessions.json"
        store = _read_store(index_path)
        delivery_recovery_entries, delivery_recovery_fields = (
            _active_delivery_recovery_inventory(store)
        )
        references = _collect_references(store, resolved_state, resolved_workspace)
        files = _session_files(resolved_state, resolved_sessions)
        kinds = Counter(row["kind"] for row in files)
        fields = Counter(row["field"] for row in references)
        roles = Counter(row["role"] for row in references)
        categories = Counter(row["category"] for row in references)
        bytes_total = sum(int(row["size"]) for row in files)
        aggregate_kinds.update(kinds)
        aggregate_fields.update(fields)
        aggregate_roles.update(roles)
        aggregate_categories.update(categories)
        aggregate_bytes += bytes_total
        aggregate_entries += len(store)
        aggregate_delivery_recovery_entries += delivery_recovery_entries
        aggregate_delivery_recovery_fields.update(delivery_recovery_fields)
        agent_reports.append(
            {
                "agent": agent,
                "entries": len(store),
                "references": len(references),
                "referenceFields": dict(sorted(fields.items())),
                "referenceRoles": dict(sorted(roles.items())),
                "referenceCategories": dict(sorted(categories.items())),
                "referenceDetails": references,
                "fileKinds": dict(sorted(kinds.items())),
                "fileCount": len(files),
                "bytes": bytes_total,
                "files": files,
                "activeDeliveryRecoveryEntries": delivery_recovery_entries,
                "activeDeliveryRecoveryFields": dict(
                    sorted(delivery_recovery_fields.items())
                ),
            }
        )

    return {
        "schemaVersion": 1,
        "stateRoot": str(resolved_state),
        "workspaceRoot": str(resolved_workspace),
        "agents": agent_reports,
        "summary": {
            "agentCount": len(agent_reports),
            "entries": aggregate_entries,
            "references": sum(aggregate_fields.values()),
            "referenceFields": dict(sorted(aggregate_fields.items())),
            "referenceRoles": dict(sorted(aggregate_roles.items())),
            "referenceCategories": dict(sorted(aggregate_categories.items())),
            "fileKinds": dict(sorted(aggregate_kinds.items())),
            "fileCount": sum(aggregate_kinds.values()),
            "bytes": aggregate_bytes,
            "activeDeliveryRecoveryEntries": aggregate_delivery_recovery_entries,
            "activeDeliveryRecoveryFields": dict(
                sorted(aggregate_delivery_recovery_fields.items())
            ),
        },
    }


def _read_manifest(path: Path) -> dict[str, Any]:
    _regular_file(path, "source manifest")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SessionRelocationError("source manifest is not valid JSON") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schemaVersion") != 1
        or not isinstance(payload.get("agents"), list)
        or not isinstance(payload.get("summary"), dict)
    ):
        raise SessionRelocationError("source manifest has an unsupported schema")
    return payload


def _mapped_path(
    value: str,
    key_path: tuple[str | int, ...],
    source_state: Path,
    source_workspace: Path,
    target_state: Path,
    target_workspace: Path,
) -> tuple[str, bool]:
    candidate = Path(value)
    if not candidate.is_absolute():
        return value, False

    source_category = _path_category(value, source_state, source_workspace)
    target_category = _path_category(value, target_state, target_workspace)
    role = _reference_role(key_path)
    if source_category in {"state", "workspace"} and role is None:
        raise SessionRelocationError(
            "managed-root path found in an unapproved metadata location: "
            + _redacted_metadata_location(key_path)
        )
    if role is None:
        return value, False
    if source_category == "workspace":
        relative = candidate.relative_to(source_workspace)
        return str(target_workspace / relative), True
    if source_category == "state":
        relative = candidate.relative_to(source_state)
        return str(target_state / relative), True
    if target_category in {"state", "workspace"}:
        return value, False
    raise SessionRelocationError(
        "approved metadata path points outside the source and target roots"
    )


def _rewrite_payload(
    payload: Any,
    source_state: Path,
    source_workspace: Path,
    target_state: Path,
    target_workspace: Path,
) -> tuple[Any, Counter[str]]:
    counts: Counter[str] = Counter()

    def visit(value: Any, key_path: tuple[str | int, ...] = ()) -> Any:
        if isinstance(value, str):
            mapped, changed = _mapped_path(
                value,
                key_path,
                source_state,
                source_workspace,
                target_state,
                target_workspace,
            )
            if changed:
                counts[str(key_path[-1])] += 1
            return mapped
        if isinstance(value, list):
            return [visit(item, (*key_path, index)) for index, item in enumerate(value)]
        if isinstance(value, dict):
            return {key: visit(item, (*key_path, key)) for key, item in value.items()}
        return value

    return visit(payload), counts


def _clear_derived_session_snapshots(payload: Any) -> tuple[Any, Counter[str]]:
    """Remove prompt/skill caches so the modern workspace is rebuilt natively."""

    if not isinstance(payload, dict):
        raise SessionRelocationError("session index must contain a JSON object")
    counts: Counter[str] = Counter()
    cleaned: dict[str, Any] = {}
    for key, entry in payload.items():
        if not isinstance(entry, dict):
            cleaned[key] = entry
            continue
        next_entry = dict(entry)
        for field in DERIVED_SESSION_SNAPSHOT_FIELDS:
            if field in next_entry:
                del next_entry[field]
                counts[field] += 1
        cleaned[key] = next_entry
    return cleaned, counts


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _delete_fields(
    entry: dict[str, Any], fields: set[str], counts: Counter[str]
) -> None:
    for field in fields:
        if field in entry:
            del entry[field]
            counts[field] += 1


def _active_delivery_recovery_inventory(
    payload: Any,
) -> tuple[int, Counter[str]]:
    """Count replay-capable delivery state without reading message content."""

    if not isinstance(payload, dict):
        raise SessionRelocationError("session index must contain a JSON object")
    entries = 0
    counts: Counter[str] = Counter()
    for entry in payload.values():
        if not isinstance(entry, dict) or entry.get("archivedAt") is not None:
            continue
        present = DELIVERY_RECOVERY_FIELDS.intersection(entry)
        if present:
            entries += 1
            counts.update(present)
    return entries, counts


def _quarantine_active_delivery_recovery(
    payload: Any,
) -> tuple[Any, int, Counter[str]]:
    """Remove copied recovery intent so a rehearsal cannot replay production."""

    if not isinstance(payload, dict):
        raise SessionRelocationError("session index must contain a JSON object")
    entries = 0
    counts: Counter[str] = Counter()
    cleaned: dict[str, Any] = {}
    for key, entry in payload.items():
        if not isinstance(entry, dict) or entry.get("archivedAt") is not None:
            cleaned[key] = entry
            continue
        next_entry = dict(entry)
        present = DELIVERY_RECOVERY_FIELDS.intersection(next_entry)
        if present:
            entries += 1
            _delete_fields(next_entry, present, counts)
        cleaned[key] = next_entry
    return cleaned, entries, counts


def _clear_active_runtime_state(
    payload: Any,
) -> tuple[Any, Counter[str], Counter[str]]:
    """Clear generated state while preserving explicit user-owned preferences."""

    if not isinstance(payload, dict):
        raise SessionRelocationError("session index must contain a JSON object")
    counts: Counter[str] = Counter()
    preserved: Counter[str] = Counter()
    cleaned: dict[str, Any] = {}
    for key, entry in payload.items():
        if not isinstance(entry, dict) or entry.get("archivedAt") is not None:
            cleaned[key] = entry
            continue
        next_entry = dict(entry)
        blocking_fields = sorted(
            field
            for field in MIGRATION_BLOCKING_ACTIVE_RUNTIME_FIELDS
            if next_entry.get(field) is not None
        )
        if blocking_fields:
            raise SessionRelocationError(
                "active session contains authority-bearing runtime state: "
                + ", ".join(blocking_fields)
            )

        model_source = next_entry.get("modelOverrideSource")
        model_override = _nonempty_string(next_entry.get("modelOverride"))
        auto_fallback_provenance = (
            model_override
            and _nonempty_string(next_entry.get("modelOverrideFallbackOriginProvider"))
            and _nonempty_string(next_entry.get("modelOverrideFallbackOriginModel"))
        )
        if model_source == "auto" or (
            model_source is None and auto_fallback_provenance
        ):
            _delete_fields(next_entry, MODEL_OVERRIDE_FIELDS, counts)
        elif model_source == "user" or (model_source is None and model_override):
            if not model_override:
                raise SessionRelocationError(
                    "active session has a user model source without a model override"
                )
            next_entry["modelOverrideSource"] = "user"
            _delete_fields(
                next_entry,
                {
                    "modelOverrideFallbackOriginModel",
                    "modelOverrideFallbackOriginProvider",
                },
                counts,
            )
            preserved["userModelSelection"] += 1
        elif model_source is not None:
            raise SessionRelocationError(
                "active session has an unknown model override source"
            )
        elif _nonempty_string(next_entry.get("providerOverride")):
            raise SessionRelocationError(
                "active session has a provider override without a model override"
            )

        auth_source = next_entry.get("authProfileOverrideSource")
        auth_override = _nonempty_string(next_entry.get("authProfileOverride"))
        auto_auth = auth_source == "auto" or (
            auth_source is None
            and next_entry.get("authProfileOverrideCompactionCount") is not None
        )
        if auto_auth:
            _delete_fields(next_entry, AUTH_OVERRIDE_FIELDS, counts)
        elif auth_source == "user" or (auth_source is None and auth_override):
            raise SessionRelocationError(
                "active session contains a user-owned auth profile override"
            )
        elif auth_source is not None:
            raise SessionRelocationError(
                "active session has an unknown auth profile override source"
            )

        _delete_fields(next_entry, TRANSIENT_ACTIVE_RUNTIME_STATE_FIELDS, counts)
        cleaned[key] = next_entry
    return cleaned, counts, preserved


def _write_json_atomic(
    path: Path,
    payload: Any,
    mode: int = 0o600,
    owner_uid: int | None = None,
    owner_gid: int | None = None,
) -> None:
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        if owner_uid is not None or owner_gid is not None:
            os.fchown(
                descriptor,
                -1 if owner_uid is None else owner_uid,
                -1 if owner_gid is None else owner_gid,
            )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise SessionRelocationError(
            "JSON output could not be replaced atomically"
        ) from exc


def rewrite_session_stores(
    target_state_root: Path,
    source_state_root: Path,
    source_workspace_root: Path,
    target_workspace_root: Path,
    agents: list[str],
    modernize_derived_snapshots: bool = False,
    modernize_active_runtime_state: bool = False,
    quarantine_delivery_recovery: bool = False,
) -> dict[str, Any]:
    target_state = _resolved_directory(target_state_root, "target state root")
    target_workspace = _resolved_directory(
        target_workspace_root, "target workspace root"
    )
    source_state = _resolved_directory(source_state_root, "source state root")
    source_workspace = _resolved_directory(
        source_workspace_root, "source workspace root"
    )
    if source_state == target_state or source_workspace == target_workspace:
        raise SessionRelocationError("source and target roots must differ")
    if _is_within(source_workspace, source_state):
        raise SessionRelocationError("source state must not be inside source workspace")
    if _is_within(target_workspace, target_state):
        raise SessionRelocationError("target state must not be inside target workspace")
    for source_root in (source_state, source_workspace):
        for target_root in (target_state, target_workspace):
            if _is_within(source_root, target_root) or _is_within(
                target_root, source_root
            ):
                raise SessionRelocationError("source and target roots must not overlap")

    changed_files = 0
    reference_counts: Counter[str] = Counter()
    cleared_snapshot_counts: Counter[str] = Counter()
    cleared_runtime_counts: Counter[str] = Counter()
    preserved_runtime_counts: Counter[str] = Counter()
    quarantined_delivery_entries = 0
    quarantined_delivery_fields: Counter[str] = Counter()
    for agent in agents:
        index_path = target_state / "agents" / agent / "sessions" / "sessions.json"
        metadata = _regular_file(index_path, "target session index")
        payload = _read_store(index_path)
        candidate: Any = payload
        if modernize_derived_snapshots:
            candidate, cleared = _clear_derived_session_snapshots(candidate)
            cleared_snapshot_counts.update(cleared)
        if modernize_active_runtime_state:
            candidate, cleared, preserved = _clear_active_runtime_state(candidate)
            cleared_runtime_counts.update(cleared)
            preserved_runtime_counts.update(preserved)
        if quarantine_delivery_recovery:
            candidate, entries, cleared = _quarantine_active_delivery_recovery(
                candidate
            )
            quarantined_delivery_entries += entries
            quarantined_delivery_fields.update(cleared)
        rewritten, counts = _rewrite_payload(
            candidate,
            source_state,
            source_workspace,
            target_state,
            target_workspace,
        )
        if rewritten != payload:
            _write_json_atomic(
                index_path,
                rewritten,
                stat.S_IMODE(metadata.st_mode),
                metadata.st_uid,
                metadata.st_gid,
            )
            changed_files += 1
        reference_counts.update(counts)

    verified = inspect_session_stores(target_state, target_workspace, agents)
    return {
        "schemaVersion": 1,
        "changedFiles": changed_files,
        "rewrittenReferences": sum(reference_counts.values()),
        "rewrittenFields": dict(sorted(reference_counts.items())),
        "clearedDerivedSnapshots": sum(cleared_snapshot_counts.values()),
        "clearedDerivedSnapshotFields": dict(sorted(cleared_snapshot_counts.items())),
        "clearedActiveRuntimeState": sum(cleared_runtime_counts.values()),
        "clearedActiveRuntimeStateFields": dict(sorted(cleared_runtime_counts.items())),
        "preservedActiveRuntimeState": dict(sorted(preserved_runtime_counts.items())),
        "quarantinedDeliveryRecoveryEntries": quarantined_delivery_entries,
        "quarantinedDeliveryRecoveryFields": sum(quarantined_delivery_fields.values()),
        "quarantinedDeliveryRecoveryFieldCounts": dict(
            sorted(quarantined_delivery_fields.items())
        ),
        "targetSummary": verified["summary"],
    }


def verify_relocation(
    source_state_root: Path,
    source_workspace_root: Path,
    target_state_root: Path,
    target_workspace_root: Path,
    agents: list[str],
    source_manifest_path: Path | None = None,
    source_index_root: Path | None = None,
    modernize_derived_snapshots: bool = False,
    modernize_active_runtime_state: bool = False,
    quarantine_delivery_recovery: bool = False,
) -> dict[str, Any]:
    if (source_manifest_path is None) != (source_index_root is None):
        raise SessionRelocationError(
            "immutable verification requires both source manifest and index root"
        )
    if source_manifest_path is None:
        source = inspect_session_stores(
            source_state_root,
            source_workspace_root,
            agents,
        )
        immutable_indexes = None
    else:
        source = _read_manifest(source_manifest_path)
        immutable_indexes = _resolved_directory(
            source_index_root,
            "source index snapshot root",
        )
    target = inspect_session_stores(target_state_root, target_workspace_root, agents)
    source_state = Path(os.path.abspath(source_state_root))
    source_workspace = Path(os.path.abspath(source_workspace_root))
    target_state = Path(target["stateRoot"])
    target_workspace = Path(target["workspaceRoot"])
    quarantined_delivery_entries = 0
    quarantined_delivery_fields: Counter[str] = Counter()

    if source.get("stateRoot") != str(source_state) or source.get(
        "workspaceRoot"
    ) != str(source_workspace):
        raise SessionRelocationError(
            "source manifest roots do not match the requested mapping"
        )
    if len(source["agents"]) != len(target["agents"]):
        raise SessionRelocationError("source and target agent counts differ")

    if source["summary"]["fileCount"] != target["summary"]["fileCount"]:
        raise SessionRelocationError("source and target session file counts differ")
    for source_agent, target_agent in zip(
        source["agents"], target["agents"], strict=True
    ):
        if source_agent["agent"] != target_agent["agent"]:
            raise SessionRelocationError("source and target agent order differs")
        source_files = {
            row["relativePath"]: row
            for row in source_agent["files"]
            if row["kind"] != "index"
        }
        target_files = {
            row["relativePath"]: row
            for row in target_agent["files"]
            if row["kind"] != "index"
        }
        if source_files.keys() != target_files.keys():
            raise SessionRelocationError(
                "source and target session artifact sets differ"
            )
        for relative_path, source_row in source_files.items():
            target_row = target_files[relative_path]
            if (
                source_row["size"] != target_row["size"]
                or source_row["sha256"] != target_row["sha256"]
            ):
                raise SessionRelocationError(
                    "a target session artifact differs from its source"
                )

        if immutable_indexes is None:
            source_index = (
                source_state
                / "agents"
                / source_agent["agent"]
                / "sessions"
                / "sessions.json"
            )
        else:
            source_index = immutable_indexes / source_agent["agent"] / "sessions.json"
            _regular_file(source_index, "source index snapshot")
            source_index_rows = [
                row for row in source_agent["files"] if row["kind"] == "index"
            ]
            if (
                len(source_index_rows) != 1
                or _sha256(source_index) != source_index_rows[0]["sha256"]
            ):
                raise SessionRelocationError(
                    "source index snapshot does not match its manifest"
                )
        target_index = (
            target_state
            / "agents"
            / target_agent["agent"]
            / "sessions"
            / "sessions.json"
        )
        source_index_payload: Any = _read_store(source_index)
        if modernize_derived_snapshots:
            source_index_payload, _ = _clear_derived_session_snapshots(
                source_index_payload
            )
        if modernize_active_runtime_state:
            source_index_payload, _, _ = _clear_active_runtime_state(
                source_index_payload
            )
        if quarantine_delivery_recovery:
            source_index_payload, entries, cleared = (
                _quarantine_active_delivery_recovery(source_index_payload)
            )
            quarantined_delivery_entries += entries
            quarantined_delivery_fields.update(cleared)
        expected, _ = _rewrite_payload(
            source_index_payload,
            source_state,
            source_workspace,
            target_state,
            target_workspace,
        )
        if expected != _read_store(target_index):
            raise SessionRelocationError(
                "target session metadata differs beyond the approved path mapping"
            )

    if (
        quarantine_delivery_recovery
        and target["summary"]["activeDeliveryRecoveryEntries"] != 0
    ):
        raise SessionRelocationError(
            "target session metadata still contains active delivery recovery state"
        )

    return {
        "schemaVersion": 1,
        "status": "ok",
        "agents": len(agents),
        "entries": target["summary"]["entries"],
        "references": target["summary"]["references"],
        "fileCount": target["summary"]["fileCount"],
        "bytes": target["summary"]["bytes"],
        "quarantinedDeliveryRecoveryEntries": quarantined_delivery_entries,
        "quarantinedDeliveryRecoveryFields": sum(quarantined_delivery_fields.values()),
    }


def verify_artifact_preservation(
    source_manifest_path: Path,
    target_state_root: Path,
    target_workspace_root: Path,
    agents: list[str],
) -> dict[str, Any]:
    """Verify immutable session artifacts while allowing native index updates."""

    source = _read_manifest(source_manifest_path)
    target = inspect_session_stores(target_state_root, target_workspace_root, agents)
    if len(source["agents"]) != len(target["agents"]):
        raise SessionRelocationError("source and target agent counts differ")

    artifact_files = 0
    artifact_bytes = 0
    for source_agent, target_agent in zip(
        source["agents"], target["agents"], strict=True
    ):
        if source_agent["agent"] != target_agent["agent"]:
            raise SessionRelocationError("source and target agent order differs")
        source_files = {
            row["relativePath"]: row
            for row in source_agent["files"]
            if row["kind"] != "index"
        }
        target_files = {
            row["relativePath"]: row
            for row in target_agent["files"]
            if row["kind"] != "index"
        }
        if source_files.keys() != target_files.keys():
            raise SessionRelocationError(
                "source and target session artifact sets differ"
            )
        for relative_path, source_row in source_files.items():
            target_row = target_files[relative_path]
            if (
                source_row["kind"] != target_row["kind"]
                or source_row["size"] != target_row["size"]
                or source_row["sha256"] != target_row["sha256"]
            ):
                raise SessionRelocationError(
                    "a target session artifact differs from its source"
                )
            artifact_files += 1
            artifact_bytes += int(target_row["size"])

    if target["summary"]["activeDeliveryRecoveryEntries"] != 0:
        raise SessionRelocationError(
            "target session metadata contains active delivery recovery state"
        )
    return {
        "schemaVersion": 1,
        "status": "ok",
        "agents": len(agents),
        "artifactFiles": artifact_files,
        "artifactBytes": artifact_bytes,
        "activeDeliveryRecoveryEntries": 0,
    }


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--agent", action="append", dest="agents", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--state-root", type=Path, required=True)
    inspect_parser.add_argument("--workspace-root", type=Path, required=True)
    inspect_parser.add_argument("--output", type=Path, required=True)
    _add_common_arguments(inspect_parser)

    rewrite_parser = subparsers.add_parser("rewrite")
    rewrite_parser.add_argument("--source-state-root", type=Path, required=True)
    rewrite_parser.add_argument("--source-workspace-root", type=Path, required=True)
    rewrite_parser.add_argument("--target-state-root", type=Path, required=True)
    rewrite_parser.add_argument("--target-workspace-root", type=Path, required=True)
    rewrite_parser.add_argument("--output", type=Path, required=True)
    rewrite_parser.add_argument("--modernize-derived-snapshots", action="store_true")
    rewrite_parser.add_argument("--modernize-active-runtime-state", action="store_true")
    rewrite_parser.add_argument("--quarantine-delivery-recovery", action="store_true")
    _add_common_arguments(rewrite_parser)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--source-state-root", type=Path, required=True)
    verify_parser.add_argument("--source-workspace-root", type=Path, required=True)
    verify_parser.add_argument("--target-state-root", type=Path, required=True)
    verify_parser.add_argument("--target-workspace-root", type=Path, required=True)
    verify_parser.add_argument("--source-manifest", type=Path)
    verify_parser.add_argument("--source-index-root", type=Path)
    verify_parser.add_argument("--output", type=Path, required=True)
    verify_parser.add_argument("--modernize-derived-snapshots", action="store_true")
    verify_parser.add_argument("--modernize-active-runtime-state", action="store_true")
    verify_parser.add_argument("--quarantine-delivery-recovery", action="store_true")
    _add_common_arguments(verify_parser)

    artifact_parser = subparsers.add_parser("verify-artifacts")
    artifact_parser.add_argument("--source-manifest", type=Path, required=True)
    artifact_parser.add_argument("--target-state-root", type=Path, required=True)
    artifact_parser.add_argument("--target-workspace-root", type=Path, required=True)
    artifact_parser.add_argument("--output", type=Path, required=True)
    _add_common_arguments(artifact_parser)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        if arguments.command == "inspect":
            report = inspect_session_stores(
                arguments.state_root,
                arguments.workspace_root,
                arguments.agents,
            )
            summary = report["summary"]
        elif arguments.command == "rewrite":
            report = rewrite_session_stores(
                arguments.target_state_root,
                arguments.source_state_root,
                arguments.source_workspace_root,
                arguments.target_workspace_root,
                arguments.agents,
                arguments.modernize_derived_snapshots,
                arguments.modernize_active_runtime_state,
                arguments.quarantine_delivery_recovery,
            )
            summary = {
                "changedFiles": report["changedFiles"],
                "rewrittenReferences": report["rewrittenReferences"],
            }
        elif arguments.command == "verify":
            report = verify_relocation(
                arguments.source_state_root,
                arguments.source_workspace_root,
                arguments.target_state_root,
                arguments.target_workspace_root,
                arguments.agents,
                arguments.source_manifest,
                arguments.source_index_root,
                arguments.modernize_derived_snapshots,
                arguments.modernize_active_runtime_state,
                arguments.quarantine_delivery_recovery,
            )
            summary = report
        else:
            report = verify_artifact_preservation(
                arguments.source_manifest,
                arguments.target_state_root,
                arguments.target_workspace_root,
                arguments.agents,
            )
            summary = report
        _write_json_atomic(arguments.output, report)
    except SessionRelocationError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        return 1
    print(json.dumps({"status": "ok", "summary": summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
