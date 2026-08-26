#!/usr/bin/env python3
"""Validate exact OpenClaw bootstrap/reference reconciliation for Astra."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Any


BOOTSTRAP_NAMES = {
    "AGENTS.md",
    "CHARTER.md",
    "COMMS.md",
    "HEARTBEAT.md",
    "IDENTITY.md",
    "JOB.md",
    "MEMORY.md",
    "MOTIVATIONS.md",
    "SOUL.md",
    "TOOLS.md",
    "USER.md",
}
REFERENCE_DISPOSITIONS = {"semantic-reference", "archival-evidence"}
BOOTSTRAP_DISPOSITIONS = {
    "native-merged-and-evidence",
    "native-seeded-and-evidence",
}
TARGET_KINDS = {"plain", "ansible-vault-plaintext"}
TARGET_RUNTIME_POLICIES = {"exact", "seeded-mutable"}


class ParityError(RuntimeError):
    """Raised when an exact bootstrap or reference invariant fails."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ParityError(f"json-read-failed:{path.name}:errno={exc.errno}") from exc
    except UnicodeError as exc:
        raise ParityError(f"invalid-encoding:{path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ParityError(
            f"invalid-json:{path.name}:line={exc.lineno}:column={exc.colno}"
        ) from exc
    if not isinstance(value, dict):
        raise ParityError(f"invalid-object:{path.name}")
    return value


def relative_path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ParityError(f"invalid-path:{label}")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or "." in pure.parts:
        raise ParityError(f"unsafe-path:{label}")
    return Path(*pure.parts)


def require_regular(path: Path, label: str) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ParityError(f"missing-file:{label}:errno={exc.errno}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ParityError(f"not-regular:{label}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ParityError(f"file-read-failed:{label}:errno={exc.errno}") from exc


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def validate_hash(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ParityError(f"invalid-sha256:{label}")
    return value


def reference_aggregate(rows: list[dict[str, Any]]) -> str:
    lines = []
    for row in sorted(rows, key=lambda item: item["sourcePath"]):
        name = Path(row["sourcePath"]).relative_to("references").as_posix()
        lines.append(f"{row['sha256']}  {name}\n")
    return digest("".join(lines).encode("utf-8"))


def validate_target_pins(
    contract: dict[str, Any], repo_root: Path, profile_root: Path | None
) -> dict[str, dict[str, Any]]:
    rows = contract.get("managedTargetPins")
    if not isinstance(rows, list) or not rows:
        raise ParityError("managed-target-pins-empty")
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "id",
            "kind",
            "sourcePath",
            "sha256",
            "runtimePolicy",
            "runtimePath",
        }:
            raise ParityError("managed-target-pin-row")
        target_id = row.get("id")
        if not isinstance(target_id, str) or not target_id or target_id in by_id:
            raise ParityError("managed-target-pin-id")
        kind = row.get("kind")
        if kind not in TARGET_KINDS:
            raise ParityError(f"managed-target-pin-kind:{target_id}")
        runtime_policy = row.get("runtimePolicy")
        if runtime_policy not in TARGET_RUNTIME_POLICIES:
            raise ParityError(f"managed-target-runtime-policy:{target_id}")
        source_path = relative_path(row.get("sourcePath"), f"target:{target_id}")
        expected = validate_hash(row.get("sha256"), f"target:{target_id}")
        if kind == "plain" and profile_root is None:
            content = require_regular(repo_root / source_path, f"target:{target_id}")
            if digest(content) != expected:
                raise ParityError(f"managed-target-hash:{target_id}")
        elif profile_root is None:
            content = require_regular(repo_root / source_path, f"target:{target_id}")
            if not content.startswith(b"$ANSIBLE_VAULT;"):
                raise ParityError(f"managed-target-not-vault:{target_id}")
        relative_path(row.get("runtimePath"), f"runtime-target:{target_id}")
        if profile_root is not None:
            runtime = profile_root / row["runtimePath"]
            runtime_content = require_regular(runtime, f"runtime-target:{target_id}")
            if runtime_policy == "exact" and digest(runtime_content) != expected:
                raise ParityError(f"runtime-target-hash:{target_id}")
            if runtime_policy == "seeded-mutable":
                if not runtime_content:
                    raise ParityError(f"runtime-target-empty:{target_id}")
                try:
                    runtime_content.decode("utf-8")
                except UnicodeError as exc:
                    raise ParityError(
                        f"runtime-target-encoding:{target_id}"
                    ) from exc
        by_id[target_id] = row
    return by_id


def runtime_evidence_path(
    evidence_root: Path, source_root: Path, configured: str
) -> Path:
    relative = relative_path(configured, "runtime-evidence")
    if source_root == evidence_root / "workspace":
        if relative.parts[:1] != ("legacy-openclaw",) or len(relative.parts) < 2:
            raise ParityError("runtime-evidence-view-layout")
        relative = Path(*relative.parts[1:])
    return evidence_root / relative


def validate(args: argparse.Namespace) -> dict[str, Any]:
    contract = load_json(args.contract)
    if contract.get("schemaVersion") != 1:
        raise ParityError("contract-schema")
    if contract.get("mode") != "complete-openclaw-bootstrap-reference-parity":
        raise ParityError("contract-mode")

    source_root = args.source_root or Path(str(contract.get("sourceRoot", "")))
    repo_root = args.repo_root
    profile_root = args.profile_root if args.runtime else None
    evidence_root = (args.evidence_root or profile_root) if args.runtime else None
    if args.runtime and profile_root is None:
        raise ParityError("runtime-profile-root-required")
    if args.runtime and evidence_root is None:
        raise ParityError("runtime-evidence-root-required")

    loader = contract.get("nativeLoader")
    if loader != {
        "profileRoot": "/var/lib/hermes/astra/.hermes/profiles/astra",
        "terminalCwd": "/var/lib/hermes/astra/.hermes/profiles/astra",
        "SOUL.md": "profile-root",
        "AGENTS.md": "terminal-cwd-profile-root",
        "MEMORY.md": "native-memory-store",
        "USER.md": "native-memory-store",
    }:
        raise ParityError("native-loader-contract")

    target_pins = validate_target_pins(contract, repo_root, profile_root)

    bootstrap_rows = contract.get("bootstrapFiles")
    if not isinstance(bootstrap_rows, list) or not bootstrap_rows:
        raise ParityError("bootstrap-files-empty")
    bootstrap_names: set[str] = set()
    bootstrap_bytes = 0
    bootstrap_lines = 0
    for row in bootstrap_rows:
        if not isinstance(row, dict) or set(row) != {
            "sourcePath",
            "sha256",
            "bytes",
            "lines",
            "disposition",
            "nativeTargetIds",
            "runtimeEvidence",
        }:
            raise ParityError("bootstrap-row")
        source_path = relative_path(row.get("sourcePath"), "bootstrap-source")
        if len(source_path.parts) != 1:
            raise ParityError(f"bootstrap-source-depth:{source_path.as_posix()}")
        name = source_path.as_posix()
        if name in bootstrap_names:
            raise ParityError(f"bootstrap-duplicate:{name}")
        bootstrap_names.add(name)
        if row.get("disposition") not in BOOTSTRAP_DISPOSITIONS:
            raise ParityError(f"bootstrap-disposition:{name}")
        target_ids = row.get("nativeTargetIds")
        if (
            not isinstance(target_ids, list)
            or not target_ids
            or not all(isinstance(value, str) and value in target_pins for value in target_ids)
        ):
            raise ParityError(f"bootstrap-targets:{name}")
        expected_evidence = f"legacy-openclaw/workspace/{name}"
        if row.get("runtimeEvidence") != expected_evidence:
            raise ParityError(f"bootstrap-evidence-target:{name}")
        expected_hash = validate_hash(row.get("sha256"), f"bootstrap:{name}")
        content = require_regular(source_root / source_path, f"bootstrap:{name}")
        if digest(content) != expected_hash:
            raise ParityError(f"bootstrap-hash:{name}")
        if row.get("bytes") != len(content) or row.get("lines") != content.count(b"\n"):
            raise ParityError(f"bootstrap-size:{name}")
        bootstrap_bytes += len(content)
        bootstrap_lines += content.count(b"\n")
        if evidence_root is not None:
            evidence = runtime_evidence_path(
                evidence_root, source_root, expected_evidence
            )
            if digest(require_regular(evidence, f"bootstrap-evidence:{name}")) != expected_hash:
                raise ParityError(f"bootstrap-evidence-hash:{name}")

    if bootstrap_names != BOOTSTRAP_NAMES:
        missing = sorted(BOOTSTRAP_NAMES - bootstrap_names)
        extra = sorted(bootstrap_names - BOOTSTRAP_NAMES)
        raise ParityError(f"bootstrap-inventory:missing={missing}:extra={extra}")
    summary = contract.get("bootstrapSummary")
    if summary != {
        "files": len(bootstrap_rows),
        "bytes": bootstrap_bytes,
        "lines": bootstrap_lines,
    }:
        raise ParityError("bootstrap-summary")

    reference_rows = contract.get("referenceFiles")
    if not isinstance(reference_rows, list) or not reference_rows:
        raise ParityError("reference-files-empty")
    reference_paths: set[str] = set()
    reference_bytes = 0
    for row in reference_rows:
        if not isinstance(row, dict) or set(row) != {
            "sourcePath",
            "sha256",
            "bytes",
            "disposition",
            "runtimeEvidence",
        }:
            raise ParityError("reference-row")
        source_path = relative_path(row.get("sourcePath"), "reference-source")
        name = source_path.as_posix()
        if source_path.parts[:1] != ("references",) or len(source_path.parts) < 2:
            raise ParityError(f"reference-source-root:{name}")
        if name in reference_paths:
            raise ParityError(f"reference-duplicate:{name}")
        reference_paths.add(name)
        if row.get("disposition") not in REFERENCE_DISPOSITIONS:
            raise ParityError(f"reference-disposition:{name}")
        expected_evidence = f"legacy-openclaw/workspace/{name}"
        if row.get("runtimeEvidence") != expected_evidence:
            raise ParityError(f"reference-evidence-target:{name}")
        expected_hash = validate_hash(row.get("sha256"), f"reference:{name}")
        content = require_regular(source_root / source_path, f"reference:{name}")
        if digest(content) != expected_hash or row.get("bytes") != len(content):
            raise ParityError(f"reference-content:{name}")
        reference_bytes += len(content)
        if evidence_root is not None:
            evidence = runtime_evidence_path(
                evidence_root, source_root, expected_evidence
            )
            if digest(require_regular(evidence, f"reference-evidence:{name}")) != expected_hash:
                raise ParityError(f"reference-evidence-hash:{name}")

    actual_reference_paths = {
        path.relative_to(source_root).as_posix()
        for path in (source_root / "references").rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if actual_reference_paths != reference_paths:
        missing = sorted(actual_reference_paths - reference_paths)
        extra = sorted(reference_paths - actual_reference_paths)
        raise ParityError(f"reference-inventory:missing={missing}:extra={extra}")

    source_manifest = load_json(source_root / "references/reference-manifest.json")
    active_rows = source_manifest.get("references")
    if not isinstance(active_rows, list):
        raise ParityError("source-reference-manifest")
    active_paths = {
        row.get("path") for row in active_rows if isinstance(row, dict)
    }
    if None in active_paths or not all(isinstance(value, str) for value in active_paths):
        raise ParityError("source-reference-manifest-path")
    semantic_paths = {
        row["sourcePath"]
        for row in reference_rows
        if row["disposition"] == "semantic-reference"
    }
    expected_semantic = active_paths | {"references/reference-manifest.json"}
    if semantic_paths != expected_semantic:
        raise ParityError("semantic-reference-inventory")

    aggregate = reference_aggregate(reference_rows)
    reference_summary = contract.get("referenceSummary")
    if reference_summary != {
        "files": len(reference_rows),
        "bytes": reference_bytes,
        "semanticReferences": len(semantic_paths),
        "archivalEvidence": len(reference_rows) - len(semantic_paths),
        "aggregateSha256": aggregate,
        "aggregateAlgorithm": "sha256 of sorted '<file-sha256>  <path-within-references>\\n' rows",
    }:
        raise ParityError("reference-summary")

    return {
        "schemaVersion": 1,
        "status": "ok",
        "runtime": args.runtime,
        "bootstrapFiles": len(bootstrap_rows),
        "bootstrapBytes": bootstrap_bytes,
        "referenceFiles": len(reference_rows),
        "referenceBytes": reference_bytes,
        "semanticReferences": len(semantic_paths),
        "archivalEvidence": len(reference_rows) - len(semantic_paths),
        "managedTargets": len(target_pins),
        "referenceAggregateSha256": aggregate,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--profile-root", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--runtime", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(validate(args), sort_keys=True))
        return 0
    except ParityError as exc:
        print(f"Hermes bootstrap parity validation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
