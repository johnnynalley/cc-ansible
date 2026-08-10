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

ALLOWED_PATH_FIELDS = {
    "path",
    "sessionFile",
    "spawnedCwd",
    "spawnedWorkspaceDir",
    "workspaceDir",
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


def _collect_references(
    payload: Any,
    state_root: Path,
    workspace_root: Path,
) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []

    def visit(value: Any, field: str | None = None) -> None:
        if isinstance(value, str):
            category = _path_category(value, state_root, workspace_root)
            if category is None:
                return
            if field not in ALLOWED_PATH_FIELDS:
                if category in {"state", "workspace"}:
                    raise SessionRelocationError(
                        "state-root path found in an unapproved metadata field"
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
            references.append({"field": field, "category": category})
            return
        if isinstance(value, list):
            for item in value:
                visit(item, field)
            return
        if isinstance(value, dict):
            for child_field, item in value.items():
                visit(item, child_field)

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
    aggregate_bytes = 0
    aggregate_entries = 0

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
        references = _collect_references(store, resolved_state, resolved_workspace)
        files = _session_files(resolved_state, resolved_sessions)
        kinds = Counter(row["kind"] for row in files)
        fields = Counter(row["field"] for row in references)
        bytes_total = sum(int(row["size"]) for row in files)
        aggregate_kinds.update(kinds)
        aggregate_fields.update(fields)
        aggregate_bytes += bytes_total
        aggregate_entries += len(store)
        agent_reports.append(
            {
                "agent": agent,
                "entries": len(store),
                "references": len(references),
                "referenceFields": dict(sorted(fields.items())),
                "fileKinds": dict(sorted(kinds.items())),
                "fileCount": len(files),
                "bytes": bytes_total,
                "files": files,
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
            "fileKinds": dict(sorted(aggregate_kinds.items())),
            "fileCount": sum(aggregate_kinds.values()),
            "bytes": aggregate_bytes,
        },
    }


def _mapped_path(
    value: str,
    field: str | None,
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
    if source_category in {"state", "workspace"} and field not in ALLOWED_PATH_FIELDS:
        raise SessionRelocationError(
            "state-root path found in an unapproved metadata field"
        )
    if field not in ALLOWED_PATH_FIELDS:
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

    def visit(value: Any, field: str | None = None) -> Any:
        if isinstance(value, str):
            mapped, changed = _mapped_path(
                value,
                field,
                source_state,
                source_workspace,
                target_state,
                target_workspace,
            )
            if changed and field:
                counts[field] += 1
            return mapped
        if isinstance(value, list):
            return [visit(item, field) for item in value]
        if isinstance(value, dict):
            return {key: visit(item, key) for key, item in value.items()}
        return value

    return visit(payload), counts


def _write_json_atomic(path: Path, payload: Any, mode: int = 0o600) -> None:
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
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
) -> dict[str, Any]:
    target_state = _resolved_directory(target_state_root, "target state root")
    target_workspace = _resolved_directory(
        target_workspace_root, "target workspace root"
    )
    source_state = Path(os.path.abspath(source_state_root))
    source_workspace = Path(os.path.abspath(source_workspace_root))
    if source_state == target_state or source_workspace == target_workspace:
        raise SessionRelocationError("source and target roots must differ")
    if not _is_lexically_within(source_state, source_workspace):
        raise SessionRelocationError("source workspace must be inside source state")
    if _is_within(target_workspace, target_state):
        raise SessionRelocationError("target state must not be inside target workspace")

    changed_files = 0
    reference_counts: Counter[str] = Counter()
    for agent in agents:
        index_path = target_state / "agents" / agent / "sessions" / "sessions.json"
        metadata = _regular_file(index_path, "target session index")
        payload = _read_store(index_path)
        rewritten, counts = _rewrite_payload(
            payload,
            source_state,
            source_workspace,
            target_state,
            target_workspace,
        )
        if rewritten != payload:
            _write_json_atomic(index_path, rewritten, stat.S_IMODE(metadata.st_mode))
            changed_files += 1
        reference_counts.update(counts)

    verified = inspect_session_stores(target_state, target_workspace, agents)
    return {
        "schemaVersion": 1,
        "changedFiles": changed_files,
        "rewrittenReferences": sum(reference_counts.values()),
        "rewrittenFields": dict(sorted(reference_counts.items())),
        "targetSummary": verified["summary"],
    }


def verify_relocation(
    source_state_root: Path,
    source_workspace_root: Path,
    target_state_root: Path,
    target_workspace_root: Path,
    agents: list[str],
) -> dict[str, Any]:
    source = inspect_session_stores(source_state_root, source_workspace_root, agents)
    target = inspect_session_stores(target_state_root, target_workspace_root, agents)
    source_state = Path(source["stateRoot"])
    source_workspace = Path(source["workspaceRoot"])
    target_state = Path(target["stateRoot"])
    target_workspace = Path(target["workspaceRoot"])

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

        source_index = (
            source_state
            / "agents"
            / source_agent["agent"]
            / "sessions"
            / "sessions.json"
        )
        target_index = (
            target_state
            / "agents"
            / target_agent["agent"]
            / "sessions"
            / "sessions.json"
        )
        expected, _ = _rewrite_payload(
            _read_store(source_index),
            source_state,
            source_workspace,
            target_state,
            target_workspace,
        )
        if expected != _read_store(target_index):
            raise SessionRelocationError(
                "target session metadata differs beyond the approved path mapping"
            )

    return {
        "schemaVersion": 1,
        "status": "ok",
        "agents": len(agents),
        "entries": target["summary"]["entries"],
        "references": target["summary"]["references"],
        "fileCount": target["summary"]["fileCount"],
        "bytes": target["summary"]["bytes"],
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
    _add_common_arguments(rewrite_parser)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--source-state-root", type=Path, required=True)
    verify_parser.add_argument("--source-workspace-root", type=Path, required=True)
    verify_parser.add_argument("--target-state-root", type=Path, required=True)
    verify_parser.add_argument("--target-workspace-root", type=Path, required=True)
    verify_parser.add_argument("--output", type=Path, required=True)
    _add_common_arguments(verify_parser)
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
            )
            summary = {
                "changedFiles": report["changedFiles"],
                "rewrittenReferences": report["rewrittenReferences"],
            }
        else:
            report = verify_relocation(
                arguments.source_state_root,
                arguments.source_workspace_root,
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
