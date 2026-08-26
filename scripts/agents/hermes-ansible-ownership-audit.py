#!/usr/bin/env python3

"""Fail closed when Hermes Ansible references an unclassified host path."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "files/hermes/ansible-ownership-contract.json"
PATH_TOKEN = re.compile(r"(^|[\s\"'=(:,\[])(/(?!/)[^\s\"'`,;)\]]+)")
REQUIRED_RULE_KEYS = {
    "id",
    "prefix",
    "classification",
    "owner",
    "normalConvergence",
    "backup",
}
HOST_ROOTS = {
    "bin",
    "boot",
    "dev",
    "etc",
    "home",
    "lib",
    "lib64",
    "mnt",
    "opt",
    "proc",
    "root",
    "run",
    "sbin",
    "snap",
    "srv",
    "sys",
    "tmp",
    "usr",
    "var",
}


class OwnershipAuditError(RuntimeError):
    pass


def load_contract(path: Path) -> dict[str, Any]:
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OwnershipAuditError(f"contract-read:{exc}") from exc
    if contract.get("schemaVersion") != 1:
        raise OwnershipAuditError("contract-schema")
    scope = contract.get("scope")
    rules = contract.get("rules")
    if not isinstance(scope, dict) or not isinstance(rules, list) or not rules:
        raise OwnershipAuditError("contract-shape")
    required_classes = set(scope.get("requiredClassifications", []))
    if not required_classes or scope.get("unclassifiedReferenceAllowed") is not False:
        raise OwnershipAuditError("contract-scope")
    prefixes: set[str] = set()
    identifiers: set[str] = set()
    observed_classes: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != REQUIRED_RULE_KEYS:
            raise OwnershipAuditError("contract-rule-shape")
        prefix = rule["prefix"]
        identifier = rule["id"]
        classification = rule["classification"]
        if not all(isinstance(value, str) and value for value in rule.values()):
            raise OwnershipAuditError("contract-rule-value")
        if not prefix.startswith("/") or prefix in prefixes or identifier in identifiers:
            raise OwnershipAuditError("contract-rule-identity")
        if classification not in required_classes:
            raise OwnershipAuditError(f"contract-rule-class:{classification}")
        prefixes.add(prefix)
        identifiers.add(identifier)
        observed_classes.add(classification)
    missing_classes = sorted(required_classes - observed_classes)
    if missing_classes:
        raise OwnershipAuditError(
            "contract-unused-classes:" + ",".join(missing_classes)
        )
    return contract


def source_paths(root: Path, contract: dict[str, Any]) -> list[Path]:
    globs = contract["scope"].get("sourceGlobs")
    if not isinstance(globs, list) or not globs:
        raise OwnershipAuditError("contract-source-globs")
    paths: set[Path] = set()
    for pattern in globs:
        if not isinstance(pattern, str) or not pattern:
            raise OwnershipAuditError("contract-source-glob-value")
        matches = {path for path in root.glob(pattern) if path.is_file()}
        if not matches:
            raise OwnershipAuditError(f"source-glob-empty:{pattern}")
        paths.update(matches)
    return sorted(paths)


def extract_paths(path: Path) -> list[tuple[int, str]]:
    references: list[tuple[int, str]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        for match in PATH_TOKEN.finditer(line):
            value = match.group(2).rstrip(".:")
            first_component = value.removeprefix("/").split("/", 1)[0]
            if value != "/" and first_component in HOST_ROOTS:
                references.append((line_number, value))
    return references


def classify(value: str, rules: list[dict[str, str]]) -> dict[str, str] | None:
    matches = [rule for rule in rules if value.startswith(rule["prefix"])]
    if not matches:
        return None
    longest = max(len(rule["prefix"]) for rule in matches)
    winners = [rule for rule in matches if len(rule["prefix"]) == longest]
    if len(winners) != 1:
        raise OwnershipAuditError(f"ambiguous-classification:{value}")
    return winners[0]


def audit(root: Path, contract: dict[str, Any]) -> dict[str, Any]:
    rules = contract["rules"]
    sources = source_paths(root, contract)
    classifications: Counter[str] = Counter()
    rules_used: Counter[str] = Counter()
    unclassified: list[dict[str, Any]] = []
    reference_count = 0
    for source in sources:
        for line_number, value in extract_paths(source):
            reference_count += 1
            rule = classify(value, rules)
            if rule is None:
                unclassified.append(
                    {
                        "source": source.relative_to(root).as_posix(),
                        "line": line_number,
                        "path": value,
                    }
                )
                continue
            classifications[rule["classification"]] += 1
            rules_used[rule["id"]] += 1
    if unclassified:
        sample = ";".join(
            f"{item['source']}:{item['line']}:{item['path']}"
            for item in unclassified[:20]
        )
        raise OwnershipAuditError(
            f"unclassified-path-reference:total={len(unclassified)}:sample={sample}"
        )
    return {
        "status": "ok",
        "schemaVersion": contract["schemaVersion"],
        "sourceCount": len(sources),
        "referenceCount": reference_count,
        "classificationCounts": dict(sorted(classifications.items())),
        "usedRuleCount": len(rules_used),
        "declaredRuleCount": len(rules),
        "unclassifiedCount": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--root", type=Path, default=ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        contract = load_contract(args.contract)
        result = audit(args.root.resolve(), contract)
    except OwnershipAuditError as exc:
        print(f"hermes-ownership-audit-error:{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
