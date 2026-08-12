#!/usr/bin/env python3
"""Archive and remove one failed synthetic OpenClaw security session."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any

MAX_INDEX_BYTES = 32 * 1024 * 1024
MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9-]{8,128}$")


class SecuritySessionCleanupError(RuntimeError):
    """Raised when a synthetic session cannot be isolated safely."""


def _fail(message: str) -> None:
    raise SecuritySessionCleanupError(message)


def _directory(path: Path, label: str) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SecuritySessionCleanupError(f"{label} is unavailable") from exc
    if path.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        _fail(f"{label} must be a non-symlink directory")
    return path.resolve()


def _regular_file(path: Path, label: str, max_bytes: int) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SecuritySessionCleanupError(f"{label} is unavailable") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        _fail(f"{label} must be a non-symlink regular file")
    if metadata.st_size > max_bytes:
        _fail(f"{label} is too large")
    return path.resolve()


def _regular_under(path: Path, root: Path, label: str, max_bytes: int) -> Path:
    resolved_root = _directory(root, f"{label} root")
    if not path.is_absolute() or ".." in path.parts:
        _fail(f"{label} has an unsafe path")
    lexical = Path(os.path.abspath(path))
    try:
        relative = lexical.relative_to(resolved_root)
    except ValueError:
        _fail(f"{label} is outside its root")
    current = resolved_root
    for component in relative.parts:
        current = current / component
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise SecuritySessionCleanupError(f"{label} is unavailable") from exc
        if stat.S_ISLNK(metadata.st_mode):
            _fail(f"{label} contains a symlink")
    return _regular_file(current, label, max_bytes)


def _load_index(path: Path, root: Path, label: str) -> dict[str, Any]:
    resolved = _regular_under(path, root, label, MAX_INDEX_BYTES)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SecuritySessionCleanupError(f"{label} is invalid") from exc
    if not isinstance(payload, dict):
        _fail(f"{label} has an unsupported shape")
    return payload


def _optional_regular_under(
    path: Path, root: Path, label: str, max_bytes: int
) -> Path | None:
    if not path.exists() and not path.is_symlink():
        return None
    return _regular_under(path, root, label, max_bytes)


def _copy_private(source: Path, destination: Path) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with source.open("rb") as source_handle, os.fdopen(
            descriptor, "wb"
        ) as destination_handle:
            descriptor = -1
            shutil.copyfileobj(source_handle, destination_handle)
            destination_handle.flush()
            os.fsync(destination_handle.fileno())
        os.replace(temporary, destination)
    except OSError as exc:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        temporary.unlink(missing_ok=True)
        raise SecuritySessionCleanupError("artifact archive failed") from exc


def cleanup_security_session(
    *,
    mode: str,
    state_root: Path,
    before_index: Path,
    session_key: str,
    evidence_root: Path,
) -> dict[str, Any]:
    if mode not in {"plan", "apply"}:
        _fail("unsupported cleanup mode")
    if not session_key.startswith("agent:main:explicit:security-"):
        _fail("session key is outside the synthetic security namespace")
    resolved_state = _directory(state_root, "state root")
    sessions_root = _directory(
        resolved_state / "agents" / "main" / "sessions", "main sessions root"
    )
    resolved_evidence = _directory(evidence_root, "evidence root")
    before = _load_index(before_index, resolved_evidence, "before session index")
    current_path = sessions_root / "sessions.json"
    current = _load_index(current_path, resolved_state, "current session index")
    if session_key in before:
        _fail("synthetic session existed before the rehearsal")
    added_keys = set(current) - set(before)
    if not added_keys:
        return {
            "status": "ok",
            "mode": mode,
            "sessionFound": False,
            "artifactCount": 0,
            "artifactsRemoved": 0,
        }
    if added_keys != {session_key}:
        _fail("unexpected sessions appeared during the rehearsal")
    entry = current.get(session_key)
    if not isinstance(entry, dict):
        _fail("synthetic session entry has an unsupported shape")
    session_id = entry.get("sessionId")
    session_file_value = entry.get("sessionFile")
    if not isinstance(session_id, str) or SAFE_SESSION_ID.fullmatch(session_id) is None:
        _fail("synthetic session id is invalid")
    if not isinstance(session_file_value, str) or not session_file_value:
        _fail("synthetic session file is missing")

    transcript = _regular_under(
        Path(session_file_value),
        sessions_root,
        "synthetic transcript",
        MAX_ARTIFACT_BYTES,
    )
    if not (
        transcript.name == f"{session_id}.jsonl"
        or transcript.name.startswith(f"{session_id}-")
    ):
        _fail("synthetic transcript name does not match the session id")
    candidates = [transcript]
    transcript_stem = transcript.name[: -len(".jsonl")]
    pointer_path = sessions_root / f"{transcript_stem}.trajectory-path.json"
    pointer = _optional_regular_under(
        pointer_path, sessions_root, "synthetic trajectory pointer", MAX_INDEX_BYTES
    )
    if pointer is not None:
        try:
            pointer_payload = json.loads(pointer.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SecuritySessionCleanupError(
                "synthetic trajectory pointer is invalid"
            ) from exc
        if not isinstance(pointer_payload, dict):
            _fail("synthetic trajectory pointer has an unsupported shape")
        runtime_file = pointer_payload.get("runtimeFile")
        if not isinstance(runtime_file, str) or not runtime_file:
            _fail("synthetic trajectory pointer has no runtime file")
        trajectory = _regular_under(
            Path(runtime_file),
            sessions_root,
            "synthetic trajectory",
            MAX_ARTIFACT_BYTES,
        )
        if trajectory.name != f"{transcript_stem}.trajectory.jsonl":
            _fail("synthetic trajectory name does not match the session id")
        candidates.extend([pointer, trajectory])
    else:
        trajectory = _optional_regular_under(
            sessions_root / f"{transcript_stem}.trajectory.jsonl",
            sessions_root,
            "synthetic trajectory",
            MAX_ARTIFACT_BYTES,
        )
        if trajectory is not None:
            candidates.append(trajectory)

    unique_artifacts = sorted(set(candidates), key=lambda path: path.name)
    archive = resolved_evidence / "failed-session-artifacts"
    if archive.exists() or archive.is_symlink():
        _fail("failed-session artifact archive already exists")
    archive.mkdir(mode=0o700)
    for artifact in unique_artifacts:
        _copy_private(artifact, archive / artifact.name)

    removed = 0
    if mode == "apply":
        for artifact in unique_artifacts:
            try:
                artifact.unlink()
            except OSError as exc:
                raise SecuritySessionCleanupError(
                    "synthetic artifact removal failed"
                ) from exc
            removed += 1

    return {
        "status": "ok",
        "mode": mode,
        "sessionFound": True,
        "sessionId": session_id,
        "artifactCount": len(unique_artifacts),
        "artifactsRemoved": removed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("plan", "apply"), required=True)
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--before-index", required=True, type=Path)
    parser.add_argument("--session-key", required=True)
    parser.add_argument("--evidence-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = cleanup_security_session(
            mode=args.mode,
            state_root=args.state_root,
            before_index=args.before_index,
            session_key=args.session_key,
            evidence_root=args.evidence_root,
        )
    except SecuritySessionCleanupError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
