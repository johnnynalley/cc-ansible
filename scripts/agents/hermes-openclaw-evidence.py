#!/usr/bin/env python3
"""Build and audit a complete read-only, secret-redacted OpenClaw evidence view."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = 1
CONTRACT_KEYS = {
    "schemaVersion",
    "mode",
    "sourceRoot",
    "runtime",
    "completeness",
    "redactions",
    "sanitization",
    "requiredVisiblePaths",
}
RUNTIME_KEYS = {
    "stateRoot",
    "upperRoot",
    "workRoot",
    "mergedRoot",
    "manifestPath",
    "viewRoot",
    "profilePath",
    "profileUser",
    "profileGroup",
}
COMPLETENESS_KEYS = {
    "defaultDisposition",
    "everySourcePathInventoried",
    "sourceMutationAllowed",
    "sourceContentCopied",
    "sourceSymlinksFollowed",
    "unclassifiedOmissionAllowed",
    "secretSourceDeletionAllowed",
    "redactedPathInventoryRequired",
    "runtimeMountRequired",
}
RULE_KEYS = {"id", "scope", "pattern", "strategy", "reason"}
RULE_SCOPES = {"exact", "tree", "root-glob", "basename-glob"}
RULE_STRATEGIES = {
    "marker",
    "opaque-inventory",
    "sanitized-json",
    "sanitized-json-or-marker",
}


class EvidenceError(RuntimeError):
    """Raised when the evidence view would be incomplete or unsafe."""


@dataclass(frozen=True)
class Rule:
    rule_id: str
    scope: str
    pattern: str
    strategy: str
    reason: str

    @property
    def depth(self) -> int:
        return len(PurePosixPath(self.pattern).parts)

    @property
    def literal_chars(self) -> int:
        return len(self.pattern.replace("*", "").replace("?", ""))

    def score(self, relative: str) -> tuple[int, int, int] | None:
        path = PurePosixPath(relative)
        if self.scope == "exact":
            return (5, self.depth, self.literal_chars) if relative == self.pattern else None
        if self.scope == "tree":
            if relative == self.pattern or relative.startswith(f"{self.pattern}/"):
                return (4, self.depth, self.literal_chars)
            return None
        if self.scope == "root-glob":
            if "/" not in relative and fnmatch.fnmatchcase(relative, self.pattern):
                return (3, self.depth, self.literal_chars)
            return None
        if fnmatch.fnmatchcase(path.name, self.pattern):
            return (2, self.depth, self.literal_chars)
        return None


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise EvidenceError(f"{label}-not-regular")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"{label}-invalid") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"{label}-invalid-root")
    return value


def _absolute_path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise EvidenceError(f"{label}-invalid")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise EvidenceError(f"{label}-unsafe")
    return path


def _relative_pattern(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise EvidenceError(f"{label}-unsafe")
    if any(ord(character) < 32 for character in value):
        raise EvidenceError(f"{label}-unsafe")
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise EvidenceError(f"{label}-unsafe")
    return value


def load_contract(path: Path) -> tuple[dict[str, Any], list[Rule], list[re.Pattern[str]]]:
    contract = _load_json(path, "contract")
    if set(contract) != CONTRACT_KEYS or contract.get("schemaVersion") != SCHEMA_VERSION:
        raise EvidenceError("contract-fields-invalid")
    if contract.get("mode") != "complete-readonly-redacted":
        raise EvidenceError("contract-mode-invalid")

    runtime = contract.get("runtime")
    if not isinstance(runtime, dict) or set(runtime) != RUNTIME_KEYS:
        raise EvidenceError("contract-runtime-invalid")
    for key in RUNTIME_KEYS - {"profileUser", "profileGroup"}:
        _absolute_path(runtime.get(key), f"runtime-{key}")
    for key in ("profileUser", "profileGroup"):
        if not isinstance(runtime.get(key), str) or not runtime[key]:
            raise EvidenceError(f"runtime-{key}-invalid")

    source_root = _absolute_path(contract.get("sourceRoot"), "source-root")
    state_root = _absolute_path(runtime["stateRoot"], "state-root")
    for key in ("upperRoot", "workRoot", "mergedRoot", "manifestPath"):
        try:
            _absolute_path(runtime[key], key).relative_to(state_root)
        except ValueError as exc:
            raise EvidenceError(f"runtime-{key}-outside-state-root") from exc
    if source_root == state_root or source_root in state_root.parents:
        raise EvidenceError("source-and-state-roots-overlap")

    completeness = contract.get("completeness")
    if not isinstance(completeness, dict) or set(completeness) != COMPLETENESS_KEYS:
        raise EvidenceError("contract-completeness-invalid")
    if completeness.get("defaultDisposition") != "visible-readonly":
        raise EvidenceError("contract-default-disposition-invalid")
    required_true = {
        "everySourcePathInventoried",
        "redactedPathInventoryRequired",
        "runtimeMountRequired",
    }
    required_false = {
        "sourceMutationAllowed",
        "sourceContentCopied",
        "sourceSymlinksFollowed",
        "unclassifiedOmissionAllowed",
        "secretSourceDeletionAllowed",
    }
    if any(completeness.get(key) is not True for key in required_true) or any(
        completeness.get(key) is not False for key in required_false
    ):
        raise EvidenceError("contract-completeness-gate-invalid")

    raw_rules = contract.get("redactions")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise EvidenceError("contract-redactions-invalid")
    rules: list[Rule] = []
    ids: set[str] = set()
    selectors: set[tuple[str, str]] = set()
    for index, value in enumerate(raw_rules):
        if not isinstance(value, dict) or set(value) != RULE_KEYS:
            raise EvidenceError(f"redaction-{index}-fields-invalid")
        rule_id = value.get("id")
        scope = value.get("scope")
        strategy = value.get("strategy")
        reason = value.get("reason")
        if not isinstance(rule_id, str) or not rule_id or rule_id in ids:
            raise EvidenceError(f"redaction-{index}-id-invalid")
        if scope not in RULE_SCOPES or strategy not in RULE_STRATEGIES:
            raise EvidenceError(f"redaction-{rule_id}-type-invalid")
        pattern = _relative_pattern(value.get("pattern"), f"redaction-{rule_id}")
        selector = (scope, pattern)
        if selector in selectors:
            raise EvidenceError(f"redaction-{rule_id}-selector-duplicate")
        if not isinstance(reason, str) or not reason.strip():
            raise EvidenceError(f"redaction-{rule_id}-reason-invalid")
        if strategy == "opaque-inventory" and scope != "tree":
            raise EvidenceError(f"redaction-{rule_id}-opaque-scope-invalid")
        ids.add(rule_id)
        selectors.add(selector)
        rules.append(Rule(rule_id, scope, pattern, strategy, reason))

    sanitization = contract.get("sanitization")
    if not isinstance(sanitization, dict) or set(sanitization) != {
        "redactedValue",
        "secretKeyPattern",
        "secretValuePatterns",
    }:
        raise EvidenceError("contract-sanitization-invalid")
    if sanitization.get("redactedValue") != "[REDACTED]":
        raise EvidenceError("contract-redacted-value-invalid")
    patterns = sanitization.get("secretValuePatterns")
    if not isinstance(patterns, list) or not patterns:
        raise EvidenceError("contract-secret-patterns-invalid")
    try:
        compiled = [re.compile(str(sanitization["secretKeyPattern"]))]
        compiled.extend(re.compile(str(pattern)) for pattern in patterns)
    except re.error as exc:
        raise EvidenceError("contract-secret-pattern-invalid") from exc

    visible = contract.get("requiredVisiblePaths")
    if not isinstance(visible, list) or len(visible) != len(set(visible)):
        raise EvidenceError("contract-required-visible-invalid")
    for index, value in enumerate(visible):
        _relative_pattern(value, f"required-visible-{index}")
    return contract, rules, compiled


def _kind(metadata: os.stat_result) -> str:
    if stat.S_ISDIR(metadata.st_mode):
        return "directory"
    if stat.S_ISREG(metadata.st_mode):
        return "file"
    if stat.S_ISLNK(metadata.st_mode):
        return "symlink"
    return "special"


def _select_rule(rules: list[Rule], relative: str) -> Rule | None:
    matches: list[tuple[tuple[int, int, int], Rule]] = []
    for rule in rules:
        score = rule.score(relative)
        if score is not None:
            matches.append((score, rule))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    best = matches[0][0]
    winners = [rule for score, rule in matches if score == best]
    if len(winners) != 1:
        raise EvidenceError(
            "ambiguous-redaction:" + relative + ":" + ",".join(
                sorted(rule.rule_id for rule in winners)
            )
        )
    return winners[0]


def inventory(source_root: Path, rules: list[Rule]) -> dict[str, Any]:
    try:
        root_metadata = source_root.lstat()
    except OSError as exc:
        raise EvidenceError("source-root-unavailable") from exc
    if source_root.is_symlink() or not stat.S_ISDIR(root_metadata.st_mode):
        raise EvidenceError("source-root-not-directory")

    records: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    classification_counts: Counter[str] = Counter()
    rule_counts: Counter[str] = Counter()
    digest = hashlib.sha256()
    pending = [source_root]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            relative = directory.relative_to(source_root).as_posix() or "."
            raise EvidenceError(f"source-directory-unreadable:{relative}") from exc
        child_directories: list[Path] = []
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(source_root).as_posix()
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise EvidenceError(f"source-path-unreadable:{relative}") from exc
            kind = _kind(metadata)
            rule = _select_rule(rules, relative)
            if rule is not None:
                classification = "redacted"
                rule_id = rule.rule_id
                strategy = rule.strategy
                reason = rule.reason
            elif kind in {"symlink", "special"}:
                classification = "redacted"
                rule_id = "nonregular-source-object"
                strategy = "marker"
                reason = "Non-regular source objects are inventoried but never traversed."
            else:
                classification = "visible"
                rule_id = None
                strategy = "source-readonly"
                reason = None
            record = {
                "path": relative,
                "kind": kind,
                "bytes": metadata.st_size if kind == "file" else 0,
                "mode": stat.S_IMODE(metadata.st_mode),
                "uid": metadata.st_uid,
                "gid": metadata.st_gid,
                "mtimeNs": metadata.st_mtime_ns,
                "ctimeNs": metadata.st_ctime_ns,
                "classification": classification,
                "strategy": strategy,
                "rule": rule_id,
            }
            if reason is not None:
                record["reason"] = reason
            records.append(record)
            counts[kind] += 1
            classification_counts[classification] += 1
            if rule_id:
                rule_counts[rule_id] += 1
            digest.update(
                (
                    f"{relative}\0{kind}\0{record['bytes']}\0{record['mode']}"
                    f"\0{record['uid']}\0{record['gid']}\0{metadata.st_mtime_ns}"
                    f"\0{metadata.st_ctime_ns}"
                    f"\0{classification}\0{strategy}\0{rule_id or ''}\n"
                ).encode("utf-8", "surrogateescape")
            )
            if kind == "directory":
                child_directories.append(path)
        pending.extend(reversed(child_directories))

    records.sort(key=lambda row: row["path"])
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceRoot": str(source_root),
        "sourceFingerprint": digest.hexdigest(),
        "summary": {
            "paths": len(records),
            "kinds": dict(sorted(counts.items())),
            "classifications": dict(sorted(classification_counts.items())),
            "redactionRules": dict(sorted(rule_counts.items())),
            "fileBytes": sum(row["bytes"] for row in records),
        },
        "paths": records,
    }


def _is_under_opaque_rule(relative: str, rules: list[Rule]) -> bool:
    for rule in rules:
        if rule.scope != "tree" or rule.strategy != "opaque-inventory":
            continue
        if relative == rule.pattern or relative.startswith(f"{rule.pattern}/"):
            return True
    return False


def _write_marker(destination: Path, record: dict[str, Any]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "redacted",
        "sourcePath": record["path"],
        "sourceKind": record["kind"],
        "sourceBytes": record["bytes"],
        "sourceMode": record["mode"],
        "sourceUid": record["uid"],
        "sourceGid": record["gid"],
        "classificationRule": record.get("rule"),
        "reason": record.get("reason"),
        "sourcePreserved": True,
        "contentAvailableToAstra": False,
    }
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.chmod(destination, 0o400)


def _sanitize_json_value(
    value: Any,
    key_pattern: re.Pattern[str],
    value_patterns: list[re.Pattern[str]],
    redacted: str,
) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            if key_pattern.search(str(key)):
                result[str(key)] = redacted
            else:
                result[str(key)] = _sanitize_json_value(
                    child, key_pattern, value_patterns, redacted
                )
        return result
    if isinstance(value, list):
        return [
            _sanitize_json_value(child, key_pattern, value_patterns, redacted)
            for child in value
        ]
    if isinstance(value, str) and any(pattern.search(value) for pattern in value_patterns):
        return redacted
    return value


def _write_sanitized_json(
    source: Path,
    destination: Path,
    record: dict[str, Any],
    contract: dict[str, Any],
    patterns: list[re.Pattern[str]],
) -> bool:
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        if record["strategy"] == "sanitized-json":
            raise EvidenceError(f"sanitized-json-invalid:{record['path']}")
        _write_marker(destination, record)
        return False
    sanitized = _sanitize_json_value(
        value,
        patterns[0],
        patterns[1:],
        contract["sanitization"]["redactedValue"],
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(sanitized, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.chmod(destination, 0o400)
    return True


def validate_sanitized_sources(
    source_root: Path,
    contract: dict[str, Any],
    patterns: list[re.Pattern[str]],
    manifest: dict[str, Any],
) -> dict[str, int]:
    strict = 0
    fallback = 0
    for record in manifest["paths"]:
        if record["strategy"] not in {
            "sanitized-json",
            "sanitized-json-or-marker",
        }:
            continue
        try:
            value = json.loads(
                (source_root / record["path"]).read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            if record["strategy"] == "sanitized-json":
                raise EvidenceError(
                    f"sanitized-json-invalid:{record['path']}"
                ) from exc
            fallback += 1
            continue
        _sanitize_json_value(
            value,
            patterns[0],
            patterns[1:],
            contract["sanitization"]["redactedValue"],
        )
        strict += 1
    return {"sanitizedJson": strict, "markerFallback": fallback}


def _atomic_json(path: Path, payload: dict[str, Any], mode: int = 0o400) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _require_generated_path(path: Path, state_root: Path, expected_name: str) -> None:
    try:
        relative = path.relative_to(state_root)
    except ValueError as exc:
        raise EvidenceError(f"generated-{expected_name}-outside-state-root") from exc
    if relative != Path(expected_name):
        raise EvidenceError(f"generated-{expected_name}-unexpected-path")


def prepare(
    contract: dict[str, Any],
    rules: list[Rule],
    patterns: list[re.Pattern[str]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise EvidenceError("prepare-requires-root")
    runtime = contract["runtime"]
    source_root = Path(contract["sourceRoot"])
    state_root = Path(runtime["stateRoot"])
    upper_root = Path(runtime["upperRoot"])
    work_root = Path(runtime["workRoot"])
    manifest_path = Path(runtime["manifestPath"])
    _require_generated_path(upper_root, state_root, "upper")
    _require_generated_path(work_root, state_root, "work")
    _require_generated_path(manifest_path, state_root, "manifest.json")

    state_root.mkdir(parents=True, exist_ok=True)
    os.chmod(state_root, 0o700)
    for generated in (upper_root, work_root):
        if generated.exists():
            if generated.is_symlink() or not generated.is_dir():
                raise EvidenceError(f"generated-{generated.name}-unsafe")
            shutil.rmtree(generated)
        generated.mkdir(mode=0o700)

    records = {row["path"]: row for row in manifest["paths"]}
    opaque_trees = 0
    for rule in rules:
        if rule.scope != "tree" or rule.strategy != "opaque-inventory":
            continue
        record = records.get(rule.pattern)
        if record is None:
            continue
        if record["kind"] != "directory":
            raise EvidenceError(f"opaque-source-missing:{rule.rule_id}")
        destination = upper_root / rule.pattern
        destination.mkdir(parents=True, mode=0o700)
        try:
            os.setxattr(destination, "trusted.overlay.opaque", b"y")
        except OSError as exc:
            raise EvidenceError(f"opaque-xattr-failed:{rule.rule_id}") from exc
        members = [
            row
            for row in manifest["paths"]
            if row["path"] == rule.pattern
            or row["path"].startswith(f"{rule.pattern}/")
        ]
        marker = destination / "REDACTED-INVENTORY.json"
        _atomic_json(
            marker,
            {
                "status": "redacted",
                "sourcePath": rule.pattern,
                "classificationRule": rule.rule_id,
                "reason": rule.reason,
                "sourcePreserved": True,
                "contentAvailableToAstra": False,
                "sourcePathCount": len(members),
                "sourcePaths": [
                    {
                        "path": row["path"],
                        "kind": row["kind"],
                        "bytes": row["bytes"],
                        "mode": row["mode"],
                        "uid": row["uid"],
                        "gid": row["gid"],
                        "mtimeNs": row["mtimeNs"],
                        "ctimeNs": row["ctimeNs"],
                    }
                    for row in members
                ],
            },
        )
        os.chmod(destination, 0o500)
        opaque_trees += 1

    sanitized = 0
    markers = 0
    for record in manifest["paths"]:
        relative = record["path"]
        if _is_under_opaque_rule(relative, rules):
            continue
        if record["classification"] != "redacted":
            continue
        destination = upper_root / relative
        source = source_root / relative
        if record["strategy"] in {"sanitized-json", "sanitized-json-or-marker"}:
            if _write_sanitized_json(
                source, destination, record, contract, patterns
            ):
                sanitized += 1
            else:
                markers += 1
        else:
            _write_marker(destination, record)
            markers += 1

    for required in contract["requiredVisiblePaths"]:
        record = records.get(required)
        if record is None or record["classification"] != "visible":
            raise EvidenceError(f"required-visible-path-failed:{required}")

    manifest["preparation"] = {
        "status": "ok",
        "sanitizedJsonFiles": sanitized,
        "markerFiles": markers,
        "opaqueTrees": opaque_trees,
    }
    _atomic_json(manifest_path, manifest)
    _atomic_json(upper_root / ".hermes-evidence-manifest.json", manifest)
    return manifest["preparation"]


def audit(
    contract: dict[str, Any], rules: list[Rule], manifest_path: Path
) -> dict[str, Any]:
    saved = _load_json(manifest_path, "manifest")
    current = inventory(Path(contract["sourceRoot"]), rules)
    required = set(contract["requiredVisiblePaths"])
    current_records = {row["path"]: row for row in current["paths"]}
    missing = sorted(required - current_records.keys())
    redacted = sorted(
        path
        for path in required
        if path in current_records
        and current_records[path]["classification"] != "visible"
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": (
            "ok"
            if not missing
            and not redacted
            and saved.get("sourceFingerprint") == current["sourceFingerprint"]
            and saved.get("summary", {}).get("paths") == current["summary"]["paths"]
            else "drift"
        ),
        "savedFingerprint": saved.get("sourceFingerprint"),
        "currentFingerprint": current["sourceFingerprint"],
        "savedPaths": saved.get("summary", {}).get("paths"),
        "currentPaths": current["summary"]["paths"],
        "missingRequiredVisible": missing,
        "redactedRequiredVisible": redacted,
    }


def verify_view(
    contract: dict[str, Any], rules: list[Rule], view_root: Path
) -> dict[str, Any]:
    try:
        metadata = view_root.lstat()
    except OSError as exc:
        raise EvidenceError("view-root-unavailable") from exc
    if view_root.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise EvidenceError("view-root-unsafe")
    try:
        readonly = bool(os.statvfs(view_root).f_flag & os.ST_RDONLY)
    except OSError as exc:
        raise EvidenceError("view-statvfs-failed") from exc
    if not readonly:
        raise EvidenceError("view-not-readonly")

    manifest = _load_json(
        view_root / ".hermes-evidence-manifest.json", "view-manifest"
    )
    rows = manifest.get("paths")
    if (
        not isinstance(rows, list)
        or manifest.get("sourceRoot") != contract["sourceRoot"]
        or manifest.get("summary", {}).get("paths") != len(rows)
    ):
        raise EvidenceError("view-manifest-invalid")

    opaque_rules = {
        rule.pattern: rule
        for rule in rules
        if rule.scope == "tree" and rule.strategy == "opaque-inventory"
    }
    visible = 0
    replacements = 0
    opaque = 0
    for record in rows:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise EvidenceError("view-manifest-record-invalid")
        relative = record["path"]
        destination = view_root / relative
        if record.get("classification") == "visible":
            try:
                target_metadata = destination.lstat()
            except OSError as exc:
                raise EvidenceError(f"view-visible-missing:{relative}") from exc
            if _kind(target_metadata) != record.get("kind"):
                raise EvidenceError(f"view-visible-kind-drift:{relative}")
            visible += 1
            continue

        opaque_root = next(
            (
                root
                for root in opaque_rules
                if relative == root or relative.startswith(f"{root}/")
            ),
            None,
        )
        if opaque_root is not None:
            if relative != opaque_root:
                continue
            marker = destination / "REDACTED-INVENTORY.json"
            if not destination.is_dir() or marker.is_symlink() or not marker.is_file():
                raise EvidenceError(f"view-opaque-invalid:{relative}")
            opaque += 1
            continue

        try:
            target_metadata = destination.lstat()
        except OSError as exc:
            raise EvidenceError(f"view-replacement-missing:{relative}") from exc
        if _kind(target_metadata) != "file":
            raise EvidenceError(f"view-replacement-unsafe:{relative}")
        replacements += 1

    required_missing = [
        relative
        for relative in contract["requiredVisiblePaths"]
        if not (view_root / relative).exists()
    ]
    if required_missing:
        raise EvidenceError("view-required-missing:" + ",".join(required_missing))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "ok",
        "sourceFingerprint": manifest.get("sourceFingerprint"),
        "paths": len(rows),
        "visiblePaths": visible,
        "replacementPaths": replacements,
        "opaqueTrees": opaque,
        "readOnly": True,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build or audit the complete OpenClaw evidence projection."
    )
    parser.add_argument(
        "command", choices=("plan", "prepare", "audit", "verify-view")
    )
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--view-root", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        contract, rules, patterns = load_contract(args.contract)
        source_root = Path(contract["sourceRoot"])
        if args.command != "verify-view":
            source_root = args.source_root or source_root
            if source_root.resolve() != Path(contract["sourceRoot"]).resolve():
                raise EvidenceError("source-root-contract-mismatch")
        if args.command == "audit":
            manifest_path = args.manifest or Path(contract["runtime"]["manifestPath"])
            result = audit(contract, rules, manifest_path)
            status = 0 if result["status"] == "ok" else 3
        elif args.command == "verify-view":
            view_root = args.view_root or Path(contract["runtime"]["viewRoot"])
            result = verify_view(contract, rules, view_root)
            status = 0
        else:
            manifest = inventory(source_root, rules)
            manifest["contractSha256"] = hashlib.sha256(
                args.contract.read_bytes()
            ).hexdigest()
            manifest["sanitizationPlan"] = validate_sanitized_sources(
                source_root, contract, patterns, manifest
            )
            if args.command == "prepare":
                result = {
                    "status": "ok",
                    "summary": manifest["summary"],
                    "sanitization": manifest["sanitizationPlan"],
                    "preparation": prepare(contract, rules, patterns, manifest),
                }
            else:
                result = {
                    "status": "ok",
                    "summary": manifest["summary"],
                    "sourceFingerprint": manifest["sourceFingerprint"],
                    "sanitization": manifest["sanitizationPlan"],
                }
            status = 0
    except EvidenceError as exc:
        result = {"status": "error", "error": str(exc)}
        status = 1
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
