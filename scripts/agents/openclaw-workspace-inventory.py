#!/usr/bin/env python3
"""Classify a legacy OpenClaw workspace without reading file contents."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import stat
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

DISPOSITIONS = {"replace", "retain", "archive", "retire", "discard"}
SCOPES = {"exact", "tree", "glob", "top-level-glob"}
OWNER_CLASSES = {"executor-writable", "operator-readonly"}
SENSITIVE_COMPONENTS = {"credential", "credentials", "secrets"}
SENSITIVE_NAMES = {
    ".env",
    ".npmrc",
    "auth-profiles.json",
    "credentials.json",
    "secrets.json",
}
SENSITIVE_SUFFIXES = {".key", ".p12", ".pem", ".token"}


class WorkspaceInventoryError(RuntimeError):
    """Raised when workspace classification is incomplete or unsafe."""


@dataclass(frozen=True)
class Rule:
    rule_id: str
    scope: str
    pattern: str
    disposition: str
    reason: str
    target: str | None
    owner_class: str | None
    sensitivity: str | None

    @property
    def depth(self) -> int:
        return len(PurePosixPath(self.pattern).parts)

    @property
    def literal_chars(self) -> int:
        return len(self.pattern.replace("*", "").replace("?", ""))

    def match_score(self, relative_path: str) -> tuple[int, int, int] | None:
        if self.scope == "exact":
            return (
                (self.depth, 4, self.literal_chars)
                if relative_path == self.pattern
                else None
            )
        if self.scope == "tree":
            if relative_path == self.pattern or relative_path.startswith(
                f"{self.pattern}/"
            ):
                return (self.depth, 3, self.literal_chars)
            return None
        if self.scope == "top-level-glob":
            if "/" not in relative_path and fnmatch.fnmatchcase(
                relative_path, self.pattern
            ):
                return (self.depth, 2, self.literal_chars)
            return None
        if PurePosixPath(relative_path).match(self.pattern):
            return (self.depth, 1, self.literal_chars)
        return None


def _relative_pattern(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise WorkspaceInventoryError(f"{label} must be a nonempty relative path")
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise WorkspaceInventoryError(f"{label} contains an unsafe path component")
    return value


def load_policy(path: Path) -> tuple[list[Rule], str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceInventoryError("policy is unavailable or invalid JSON") from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise WorkspaceInventoryError("policy schemaVersion must be 1")
    archive_contract = payload.get("archiveContract")
    if not isinstance(archive_contract, str) or not archive_contract.strip():
        raise WorkspaceInventoryError("policy archiveContract is required")
    rows = payload.get("rules")
    if not isinstance(rows, list) or not rows:
        raise WorkspaceInventoryError("policy rules must be a nonempty array")

    rules: list[Rule] = []
    seen_ids: set[str] = set()
    seen_selectors: set[tuple[str, str]] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise WorkspaceInventoryError(f"policy rule {index} must be an object")
        rule_id = row.get("id")
        if not isinstance(rule_id, str) or not rule_id:
            raise WorkspaceInventoryError(f"policy rule {index} needs an id")
        if rule_id in seen_ids:
            raise WorkspaceInventoryError(f"duplicate policy rule id: {rule_id}")
        seen_ids.add(rule_id)
        scope = row.get("scope")
        if scope not in SCOPES:
            raise WorkspaceInventoryError(f"invalid scope for rule {rule_id}")
        pattern = _relative_pattern(row.get("pattern"), f"rule {rule_id} pattern")
        selector = (scope, pattern)
        if selector in seen_selectors:
            raise WorkspaceInventoryError(f"duplicate policy selector: {selector}")
        seen_selectors.add(selector)
        disposition = row.get("disposition")
        if disposition not in DISPOSITIONS:
            raise WorkspaceInventoryError(f"invalid disposition for rule {rule_id}")
        reason = row.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise WorkspaceInventoryError(f"rule {rule_id} needs a reason")
        target = row.get("target")
        owner_class = row.get("ownerClass")
        if disposition == "retain":
            target = _relative_pattern(target, f"rule {rule_id} target")
            if owner_class not in OWNER_CLASSES:
                raise WorkspaceInventoryError(
                    f"retained rule {rule_id} needs a valid ownerClass"
                )
        elif target is not None or owner_class is not None:
            raise WorkspaceInventoryError(
                f"non-retained rule {rule_id} cannot declare target ownership"
            )
        sensitivity = row.get("sensitivity")
        if sensitivity is not None and not isinstance(sensitivity, str):
            raise WorkspaceInventoryError(
                f"rule {rule_id} sensitivity must be a string"
            )
        rules.append(
            Rule(
                rule_id=rule_id,
                scope=scope,
                pattern=pattern,
                disposition=disposition,
                reason=reason,
                target=target,
                owner_class=owner_class,
                sensitivity=sensitivity,
            )
        )
    return rules, archive_contract


def _select_rule(rules: list[Rule], relative_path: str) -> Rule:
    candidates: list[tuple[tuple[int, int, int], Rule]] = []
    for rule in rules:
        score = rule.match_score(relative_path)
        if score is not None:
            candidates.append((score, rule))
    if not candidates:
        raise WorkspaceInventoryError(f"unclassified path: {relative_path}")
    candidates.sort(key=lambda item: item[0], reverse=True)
    best_score = candidates[0][0]
    winners = [rule for score, rule in candidates if score == best_score]
    if len(winners) != 1:
        ids = ", ".join(sorted(rule.rule_id for rule in winners))
        raise WorkspaceInventoryError(
            f"ambiguous policy match for {relative_path}: {ids}"
        )
    return winners[0]


def _path_kind(metadata: os.stat_result) -> str:
    if stat.S_ISREG(metadata.st_mode):
        return "file"
    if stat.S_ISDIR(metadata.st_mode):
        return "directory"
    if stat.S_ISLNK(metadata.st_mode):
        return "symlink"
    return "special"


def _looks_sensitive(relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    lowered_parts = [part.lower() for part in path.parts]
    name = path.name.lower()
    return (
        any(part in SENSITIVE_COMPONENTS for part in lowered_parts)
        or name in SENSITIVE_NAMES
        or any(name.endswith(suffix) for suffix in SENSITIVE_SUFFIXES)
    )


def inventory_workspace(source_root: Path, rules: list[Rule]) -> dict[str, Any]:
    try:
        root_metadata = source_root.lstat()
    except OSError as exc:
        raise WorkspaceInventoryError("source workspace is unavailable") from exc
    if not stat.S_ISDIR(root_metadata.st_mode) or source_root.is_symlink():
        raise WorkspaceInventoryError(
            "source workspace must be a non-symlink directory"
        )

    counts: Counter[str] = Counter()
    disposition_counts: Counter[str] = Counter()
    disposition_bytes: Counter[str] = Counter()
    owner_counts: Counter[str] = Counter()
    rule_counts: Counter[str] = Counter()
    rule_bytes: Counter[str] = Counter()
    retained_targets: defaultdict[str, set[str]] = defaultdict(set)
    classified_paths = 0

    pending = [source_root]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            relative = directory.relative_to(source_root).as_posix() or "."
            raise WorkspaceInventoryError(
                f"cannot enumerate workspace directory: {relative}"
            ) from exc
        for entry in entries:
            path = Path(entry.path)
            relative_path = path.relative_to(source_root).as_posix()
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise WorkspaceInventoryError(
                    f"cannot stat workspace path: {relative_path}"
                ) from exc
            kind = _path_kind(metadata)
            if kind == "special":
                raise WorkspaceInventoryError(
                    f"special filesystem object is not supported: {relative_path}"
                )
            rule = _select_rule(rules, relative_path)
            if (
                rule.disposition == "retain"
                and _looks_sensitive(relative_path)
                and rule.sensitivity is None
            ):
                raise WorkspaceInventoryError(
                    f"retained sensitive-looking path lacks classification: {relative_path}"
                )
            classified_paths += 1
            counts[kind] += 1
            disposition_counts[rule.disposition] += 1
            rule_counts[rule.rule_id] += 1
            if kind == "file":
                disposition_bytes[rule.disposition] += metadata.st_size
                rule_bytes[rule.rule_id] += metadata.st_size
            if rule.owner_class:
                owner_counts[rule.owner_class] += 1
                retained_targets[rule.target or ""].add(rule.owner_class)
            if kind == "directory":
                pending.append(path)

    conflicting_targets = {
        target: sorted(owners)
        for target, owners in retained_targets.items()
        if len(owners) > 1
    }
    if conflicting_targets:
        raise WorkspaceInventoryError(
            "retained target has conflicting owner classes: "
            + json.dumps(conflicting_targets, sort_keys=True)
        )

    rule_summaries = []
    for rule in rules:
        rule_summaries.append(
            {
                "id": rule.rule_id,
                "disposition": rule.disposition,
                "ownerClass": rule.owner_class,
                "matchedPaths": rule_counts[rule.rule_id],
                "fileBytes": rule_bytes[rule.rule_id],
            }
        )
    return {
        "status": "ok",
        "schemaVersion": 1,
        "summary": {
            "classifiedPaths": classified_paths,
            "kinds": dict(sorted(counts.items())),
            "dispositions": dict(sorted(disposition_counts.items())),
            "bytesByDisposition": dict(sorted(disposition_bytes.items())),
            "retainedOwnerClasses": dict(sorted(owner_counts.items())),
        },
        "rules": rule_summaries,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify a legacy OpenClaw workspace without reading contents"
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        rules, archive_contract = load_policy(args.policy)
        result = inventory_workspace(args.source, rules)
        result["archiveContract"] = archive_contract
    except WorkspaceInventoryError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
