#!/usr/bin/env python3
"""Import one profile's canonical OpenClaw sessions into isolated Hermes LCM."""

from __future__ import annotations

import argparse
import collections
import hashlib
import importlib.util
import json
import os
import sqlite3
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any


class ImportBoundaryError(RuntimeError):
    """Raised when the source or importer violates the reviewed boundary."""

    def __init__(self, code: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.details = details or {}


@dataclass(frozen=True)
class SourceManifest:
    files: tuple[Path, ...]
    bytes: int
    sha256: str
    trajectory_files: int


@dataclass(frozen=True)
class InvalidRecordAllowance:
    filename_sha256: str
    line: int
    length: int
    sha256: str


@dataclass(frozen=True)
class SourceSelection:
    files: tuple[Path, ...]
    manifest_sha256: str


def require(value: bool, code: str) -> None:
    if not value:
        raise ImportBoundaryError(code)


def canonical_source_manifest(source_dir: Path) -> SourceManifest:
    require(source_dir.is_absolute(), "source-relative")
    info = os.lstat(source_dir)
    require(stat.S_ISDIR(info.st_mode), "source-not-directory")
    require(not stat.S_ISLNK(info.st_mode), "source-directory-symlink")

    canonical: list[Path] = []
    trajectory_files = 0
    for entry in sorted(os.scandir(source_dir), key=lambda item: item.name):
        path = source_dir / entry.name
        item = os.lstat(path)
        if entry.name.endswith(".trajectory.jsonl"):
            require(stat.S_ISREG(item.st_mode), "trajectory-not-regular")
            require(not stat.S_ISLNK(item.st_mode), "trajectory-symlink")
            trajectory_files += 1
            continue
        if entry.name.endswith(".jsonl"):
            require(stat.S_ISREG(item.st_mode), "session-not-regular")
            require(not stat.S_ISLNK(item.st_mode), "session-symlink")
            canonical.append(path)
        elif stat.S_ISDIR(item.st_mode):
            nested = next(path.rglob("*.jsonl"), None)
            require(nested is None, "nested-session-jsonl")

    require(bool(canonical), "canonical-session-set-empty")
    aggregate = hashlib.sha256()
    total_bytes = 0
    for path in canonical:
        before = os.lstat(path)
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
                total_bytes += len(chunk)
        after = os.lstat(path)
        require(
            (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            )
            == (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ),
            "source-race",
        )
        aggregate.update(path.name.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(str(after.st_size).encode("ascii"))
        aggregate.update(b"\0")
        aggregate.update(digest.hexdigest().encode("ascii"))
        aggregate.update(b"\n")
    return SourceManifest(
        files=tuple(canonical),
        bytes=total_bytes,
        sha256=aggregate.hexdigest(),
        trajectory_files=trajectory_files,
    )


def load_importer(path: Path) -> ModuleType:
    require(path.is_absolute(), "importer-relative")
    info = os.lstat(path)
    require(stat.S_ISREG(info.st_mode), "importer-not-regular")
    require(not stat.S_ISLNK(info.st_mode), "importer-symlink")
    spec = importlib.util.spec_from_file_location("hermes_lcm_lossless_import", path)
    require(spec is not None and spec.loader is not None, "importer-spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    require(callable(getattr(module, "import_jsonl_sessions", None)), "importer-api")
    return module


def selected_source_manifest(files: tuple[Path, ...]) -> str:
    aggregate = hashlib.sha256()
    for path in files:
        info = os.lstat(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        aggregate.update(path.name.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(str(info.st_size).encode("ascii"))
        aggregate.update(b"\0")
        aggregate.update(digest.encode("ascii"))
        aggregate.update(b"\n")
    return aggregate.hexdigest()


def load_source_selection(path: Path, source: SourceManifest) -> SourceSelection:
    require(path.is_absolute(), "include-manifest-relative")
    info = os.lstat(path)
    require(stat.S_ISREG(info.st_mode), "include-manifest-not-regular")
    require(not stat.S_ISLNK(info.st_mode), "include-manifest-symlink")
    require(info.st_size <= 1024 * 1024, "include-manifest-too-large")
    raw = path.read_bytes()
    after = os.lstat(path)
    require(
        (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
        "include-manifest-race",
    )
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImportBoundaryError("include-manifest-invalid-json") from exc
    require(isinstance(payload, dict), "include-manifest-invalid-shape")
    require(
        set(payload)
        == {
            "schemaVersion",
            "status",
            "sourceFileCount",
            "sourceBytes",
            "sourceManifestSha256",
            "sessionIndexManifestSha256",
            "policySha256",
            "approvedFileCount",
            "approvedFiles",
        },
        "include-manifest-fields",
    )
    require(payload.get("schemaVersion") == 1, "include-manifest-schema")
    require(payload.get("status") == "approved-public-subset", "include-manifest-status")
    require(payload.get("sourceFileCount") == len(source.files), "include-manifest-source-count")
    require(payload.get("sourceBytes") == source.bytes, "include-manifest-source-bytes")
    require(
        payload.get("sourceManifestSha256") == source.sha256,
        "include-manifest-source-hash",
    )
    for field in ("sessionIndexManifestSha256", "policySha256"):
        value = payload.get(field)
        require(
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value),
            f"include-manifest-{field}-invalid",
        )
    names = payload.get("approvedFiles")
    require(isinstance(names, list) and bool(names), "include-manifest-empty")
    require(payload.get("approvedFileCount") == len(names), "include-manifest-approved-count")
    require(all(isinstance(name, str) for name in names), "include-manifest-name-invalid")
    require(len(set(names)) == len(names), "include-manifest-name-duplicate")
    by_name = {item.name: item for item in source.files}
    require(
        all(
            name.endswith(".jsonl")
            and not name.endswith(".trajectory.jsonl")
            and Path(name).name == name
            and name in by_name
            for name in names
        ),
        "include-manifest-name-boundary",
    )
    files = tuple(by_name[name] for name in sorted(names))
    return SourceSelection(files=files, manifest_sha256=hashlib.sha256(raw).hexdigest())


def enable_content_tool_call_id_compat(importer: ModuleType) -> str:
    probe = {
        "type": "toolCall",
        "id": "hermes-profile-import-probe",
        "name": "compatibility_probe",
        "arguments": {},
    }
    if importer._jsonl_openai_tool_call(probe) is not None:
        return "native"
    original = importer._jsonl_openai_tool_call

    def normalized_content_item(item: dict[str, Any]) -> dict[str, Any]:
        item_type = importer._jsonl_string_type(item.get("type")) or ""
        explicit_call_id = any(
            item.get(key) not in (None, "")
            for key in (
                "call_id",
                "callId",
                "tool_call_id",
                "toolCallId",
                "tool_use_id",
                "toolUseId",
            )
        )
        if (
            item_type in importer.JSONL_OPENCLAW_TOOL_CALL_TYPES
            and not explicit_call_id
            and item.get("id") not in (None, "")
        ):
            normalized = dict(item)
            normalized["tool_call_id"] = item["id"]
            return normalized
        return item

    require(
        original(normalized_content_item(probe)) is not None,
        "content-tool-call-id-compat-unavailable",
    )

    def calls_from_content(content: Any) -> list[dict[str, Any]]:
        if not isinstance(content, list):
            return []
        calls: list[dict[str, Any]] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = importer._jsonl_string_type(item.get("type")) or ""
            if item_type not in importer.JSONL_TOOL_CALL_TYPES and "toolCall" not in item:
                continue
            call = original(normalized_content_item(item))
            if call is not None:
                calls.append(call)
        return calls

    def malformed_content_types(content: Any) -> list[str]:
        if not isinstance(content, list):
            return []
        malformed: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if importer._jsonl_content_item_has_malformed_tool_call_type(item):
                malformed.append("non-string tool call type")
                continue
            item_type = importer._jsonl_string_type(item.get("type")) or ""
            if item_type not in importer.JSONL_TOOL_CALL_TYPES and "toolCall" not in item:
                continue
            if original(normalized_content_item(item)) is None:
                malformed.append(item_type or "toolCall")
        return malformed

    importer._jsonl_tool_calls_from_content = calls_from_content
    importer._jsonl_malformed_tool_call_content_types = malformed_content_types
    return "content-tool-call-id-fallback"


def warning_kinds(warnings: Any) -> list[str]:
    if not isinstance(warnings, list):
        return ["invalid-warning-container"]
    result = set()
    for warning in warnings:
        if not isinstance(warning, str):
            result.add("invalid-warning-entry")
            continue
        result.add(warning.rsplit(": ", 1)[-1][:160])
    return sorted(result)


def malformed_tool_call_shapes(
    importer: ModuleType, files: tuple[Path, ...]
) -> dict[str, int]:
    counts: collections.Counter[str] = collections.Counter()
    for path in files:
        filename_digest = hashlib.sha256(path.name.encode("utf-8")).hexdigest()
        with path.open("r", encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    stripped = line.strip()
                    first = (
                        "object"
                        if stripped.startswith("{")
                        else "array"
                        if stripped.startswith("[")
                        else "other"
                    )
                    last = (
                        "object"
                        if stripped.endswith("}")
                        else "array"
                        if stripped.endswith("]")
                        else "other"
                    )
                    digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
                    counts[
                        f"invalid-json;filenameSha256={filename_digest};"
                        f"line={line_number};length={len(line)};first={first};"
                        f"last={last};sha256={digest}"
                    ] += 1
                    continue
                if not isinstance(row, dict):
                    continue
                message = importer._jsonl_row_message(row)
                role = importer._jsonl_role(
                    message, importer._jsonl_effective_row_type(row, message)
                )
                content = importer._jsonl_content(message, role)
                if not isinstance(content, list):
                    continue
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    if not importer._jsonl_malformed_tool_call_content_types([item]):
                        continue
                    nested = item.get("toolCall")
                    raw = nested if isinstance(nested, dict) else item
                    raw_type = raw.get("type")
                    if isinstance(raw_type, str):
                        type_shape = (
                            raw_type
                            if raw_type in importer.JSONL_TOOL_CALL_TYPES
                            else "other-string"
                        )
                    elif raw_type is None:
                        type_shape = "missing"
                    else:
                        type_shape = f"non-string-{type(raw_type).__name__}"
                    has_id = any(
                        key in raw and raw.get(key) not in (None, "")
                        for key in (
                            "id",
                            "call_id",
                            "callId",
                            "tool_call_id",
                            "toolCallId",
                            "tool_use_id",
                            "toolUseId",
                        )
                    )
                    function = raw.get("function")
                    has_name = any(
                        key in raw and raw.get(key) not in (None, "")
                        for key in (
                            "name",
                            "tool_name",
                            "toolName",
                            "tool_use_name",
                            "toolUseName",
                        )
                    ) or (
                        isinstance(function, dict)
                        and function.get("name") not in (None, "")
                    )
                    has_arguments = any(
                        key in raw
                        for key in (
                            "arguments",
                            "tool_input",
                            "toolInput",
                            "tool_use_input",
                            "toolUseInput",
                            "input",
                            "parameters",
                        )
                    ) or (
                        isinstance(function, dict) and "arguments" in function
                    )
                    id_keys = "+".join(
                        key
                        for key in (
                            "id",
                            "call_id",
                            "callId",
                            "tool_call_id",
                            "toolCallId",
                            "tool_use_id",
                            "toolUseId",
                        )
                        if key in raw
                    ) or "none"
                    argument_keys = "+".join(
                        key
                        for key in (
                            "arguments",
                            "tool_input",
                            "toolInput",
                            "tool_use_input",
                            "toolUseInput",
                            "input",
                            "parameters",
                        )
                        if key in raw
                    ) or "none"
                    shape = (
                        f"type={type_shape};nested={isinstance(nested, dict)};"
                        f"id={has_id};idKeys={id_keys};name={has_name};"
                        f"arguments={has_arguments};argumentKeys={argument_keys}"
                    )
                    counts[shape] += 1
    return dict(sorted(counts.items()))


def parse_invalid_record_allowances(
    values: list[str],
) -> tuple[InvalidRecordAllowance, ...]:
    allowances: list[InvalidRecordAllowance] = []
    seen: set[tuple[str, int]] = set()
    for value in values:
        parts = value.split(":")
        require(len(parts) == 4, "invalid-record-allowance-shape")
        filename_sha256, raw_line, raw_length, line_sha256 = parts
        require(
            len(filename_sha256) == 64
            and all(character in "0123456789abcdef" for character in filename_sha256),
            "invalid-record-filename-hash",
        )
        require(
            len(line_sha256) == 64
            and all(character in "0123456789abcdef" for character in line_sha256),
            "invalid-record-line-hash",
        )
        try:
            line = int(raw_line)
            length = int(raw_length)
        except ValueError as exc:
            raise ImportBoundaryError("invalid-record-allowance-number") from exc
        require(line > 0 and length > 0, "invalid-record-allowance-range")
        key = (filename_sha256, line)
        require(key not in seen, "invalid-record-allowance-duplicate")
        seen.add(key)
        allowances.append(
            InvalidRecordAllowance(
                filename_sha256=filename_sha256,
                line=line,
                length=length,
                sha256=line_sha256,
            )
        )
    return tuple(allowances)


def stage_allowed_invalid_records(
    files: tuple[Path, ...],
    allowances: tuple[InvalidRecordAllowance, ...],
    staging_root: Path,
) -> tuple[tuple[Path, ...], int]:
    by_filename_hash: dict[str, list[Path]] = collections.defaultdict(list)
    for path in files:
        digest = hashlib.sha256(path.name.encode("utf-8")).hexdigest()
        by_filename_hash[digest].append(path)

    by_path: dict[Path, dict[int, InvalidRecordAllowance]] = collections.defaultdict(dict)
    for allowance in allowances:
        matches = by_filename_hash.get(allowance.filename_sha256, [])
        require(len(matches) == 1, "invalid-record-source-file-boundary")
        by_path[matches[0]][allowance.line] = allowance

    staged: list[Path] = []
    excluded = 0
    for path in files:
        path_allowances = by_path.get(path)
        if not path_allowances:
            staged.append(path)
            continue
        target = staging_root / path.name
        with path.open("r", encoding="utf-8") as source, target.open(
            "x", encoding="utf-8"
        ) as destination:
            os.chmod(target, 0o600)
            matched: set[int] = set()
            for line_number, line in enumerate(source, start=1):
                allowance = path_allowances.get(line_number)
                if allowance is None:
                    destination.write(line)
                    continue
                require(len(line) == allowance.length, "invalid-record-length-drift")
                require(
                    hashlib.sha256(line.encode("utf-8")).hexdigest()
                    == allowance.sha256,
                    "invalid-record-hash-drift",
                )
                try:
                    json.loads(line)
                except json.JSONDecodeError:
                    pass
                else:
                    raise ImportBoundaryError("invalid-record-became-valid")
                matched.add(line_number)
                excluded += 1
            require(
                matched == set(path_allowances),
                "invalid-record-line-boundary",
            )
        staged.append(target)
    require(excluded == len(allowances), "invalid-record-exclusion-count")
    return tuple(staged), excluded


def quick_check(path: Path) -> str:
    require(path.is_file(), "target-missing-after-apply")
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return str(connection.execute("PRAGMA quick_check").fetchone()[0])
    finally:
        connection.close()


def execute(args: argparse.Namespace) -> dict[str, Any]:
    before = canonical_source_manifest(args.source_dir)
    include_manifest = getattr(args, "include_manifest", None)
    selection = (
        load_source_selection(include_manifest, before)
        if include_manifest is not None
        else SourceSelection(files=before.files, manifest_sha256="")
    )
    importer = load_importer(args.importer)
    compatibility = enable_content_tool_call_id_compat(importer)
    allowances = parse_invalid_record_allowances(
        list(getattr(args, "allow_invalid_record", []))
    )

    def import_files(files: tuple[Path, ...]) -> Any:
        return importer.import_jsonl_sessions(
            files=files,
            target_db=args.target_db,
            namespace=args.namespace,
            agent=args.agent,
            import_id=args.import_id,
            apply=args.apply,
        )

    excluded_invalid_rows = 0
    if allowances:
        with tempfile.TemporaryDirectory(
            prefix="hermes-profile-lcm-import-"
        ) as directory:
            staging_root = Path(directory)
            os.chmod(staging_root, 0o700)
            staged_files, excluded_invalid_rows = stage_allowed_invalid_records(
                selection.files,
                allowances,
                staging_root,
            )
            result = import_files(staged_files)
    else:
        result = import_files(selection.files)
    raw = result.to_dict()
    after = canonical_source_manifest(args.source_dir)
    require(before == after, "source-manifest-drift")
    kinds = warning_kinds(raw.get("warnings", []))
    invalid_rows = int(raw.get("invalid_rows", -1))
    if invalid_rows:
        raise ImportBoundaryError(
            "invalid-source-rows",
            {
                "invalidRows": invalid_rows,
                "warningCount": len(raw.get("warnings", [])),
                "warningKinds": kinds,
                "malformedToolCallShapes": malformed_tool_call_shapes(
                    importer, before.files
                ),
            },
        )
    if kinds:
        raise ImportBoundaryError(
            f"source-warnings:{len(raw.get('warnings', []))}:"
            f"warning-kinds:{','.join(kinds)}"
        )

    imported = int(raw.get("imported", 0))
    skipped_existing = int(raw.get("skipped_existing", 0))
    mode = "apply" if args.apply else "dry-run"
    status = "ready"
    if args.apply:
        status = "migrated" if imported else "already-migrated"
    output: dict[str, Any] = {
        "status": status,
        "mode": mode,
        "agent": args.agent,
        "compatibility": compatibility,
        "sourceFileCount": len(before.files),
        "selectedFileCount": len(selection.files),
        "selectedSourceManifestSha256": selected_source_manifest(selection.files),
        "trajectoryFileCount": before.trajectory_files,
        "sourceBytes": before.bytes,
        "sourceManifestSha256": before.sha256,
        "conversations": int(raw.get("conversations", 0)),
        "scanned": int(raw.get("scanned", 0)),
        "eligible": int(raw.get("eligible", 0)),
        "wouldImport": int(raw.get("would_import", 0)),
        "imported": imported,
        "skippedExisting": skipped_existing,
        "skippedEmpty": int(raw.get("skipped_empty", 0)),
        "excludedInvalidRows": excluded_invalid_rows,
        "invalidRows": invalid_rows,
        "warningCount": 0,
        "warningKinds": [],
        "importId": str(raw.get("import_id", "")),
    }
    if selection.manifest_sha256:
        output["includeManifestSha256"] = selection.manifest_sha256
    if args.apply:
        output["quickCheck"] = quick_check(args.target_db)
        require(output["quickCheck"] == "ok", "target-integrity")
    return output


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--importer", type=Path, required=True)
    value.add_argument("--source-dir", type=Path, required=True)
    value.add_argument("--target-db", type=Path, required=True)
    value.add_argument("--namespace", required=True)
    value.add_argument("--agent", required=True)
    value.add_argument("--import-id", required=True)
    value.add_argument("--allow-invalid-record", action="append", default=[])
    value.add_argument("--include-manifest", type=Path)
    value.add_argument("--apply", action="store_true")
    return value


def main() -> int:
    try:
        output = execute(parser().parse_args())
    except Exception as exc:
        details = exc.details if isinstance(exc, ImportBoundaryError) else {}
        print(
            json.dumps(
                {"status": "error", "error": str(exc), "details": details},
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 1
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
