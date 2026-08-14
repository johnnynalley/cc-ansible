#!/usr/bin/env python3
"""Validate reviewed Hermes-native profile skills and deployed roots."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any


def fail(code: str, detail: str) -> None:
    raise SystemExit(f"{code}: {detail}")


def load_contract(path: Path) -> dict[str, Any]:
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail("contract-invalid", str(exc))
    if contract.get("schemaVersion") != 1:
        fail("contract-schema", repr(contract.get("schemaVersion")))
    if contract.get("mode") != "reviewed-native-seed":
        fail("contract-mode", repr(contract.get("mode")))
    return contract


def require_safe_path(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        fail("path-missing", f"{label}: {exc}")
    if stat.S_ISLNK(mode):
        fail("symlink-rejected", f"{label}: {path}")
    if not stat.S_ISREG(mode):
        fail("regular-file-required", f"{label}: {path}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(131072), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_skill_path(root: Path, skill: dict[str, Any]) -> Path:
    source = Path(skill["source"])
    if source.is_absolute() or ".." in source.parts:
        fail("unsafe-source-path", str(source))
    return root / source


def installed_skill_path(profile: dict[str, Any], skill: dict[str, Any]) -> Path:
    managed_root = Path(profile["managedRoot"])
    if not managed_root.is_absolute():
        fail("managed-root-not-absolute", str(managed_root))
    return managed_root / skill["name"] / "SKILL.md"


def runtime_skill_path(profile: dict[str, Any], skill: dict[str, Any]) -> Path:
    runtime_root = Path(profile["runtimeRoot"])
    if not runtime_root.is_absolute():
        fail("runtime-root-not-absolute", str(runtime_root))
    return runtime_root / skill["name"] / "SKILL.md"


def validate_skill(
    path: Path,
    profile_name: str,
    skill: dict[str, Any],
    parse_frontmatter: Any,
    validate_frontmatter: Any,
    scan_skill: Any,
    description_limit: int,
) -> None:
    require_safe_path(path, f"{profile_name}/{skill['name']}")
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        fail("skill-read-failed", f"{path}: {exc}")
    if sha256(path) != skill["sha256"]:
        fail("skill-hash-drift", str(path))
    if not content.startswith("---\n"):
        fail("skill-frontmatter-offset", str(path))
    frontmatter_error = validate_frontmatter(content, new_skill=True)
    if frontmatter_error:
        fail("skill-frontmatter-invalid", f"{path}: {frontmatter_error}")
    frontmatter, body = parse_frontmatter(content)
    if frontmatter.get("name") != skill["name"]:
        fail("skill-name-drift", str(path))
    if frontmatter.get("description") != skill["description"]:
        fail("skill-description-drift", str(path))
    if len(skill["description"]) > description_limit:
        fail("skill-description-prompt-truncated", str(path))
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", skill["name"]):
        fail("skill-name-invalid", skill["name"])
    if not body.strip():
        fail("skill-body-empty", str(path))
    forbidden_fields = {
        "allowed-tools",
        "required_environment_variables",
        "required_credential_files",
        "prerequisites",
    }
    present = forbidden_fields.intersection(frontmatter)
    if present:
        fail("skill-capability-field-rejected", f"{path}: {sorted(present)}")
    hermes_metadata = (frontmatter.get("metadata") or {}).get("hermes") or {}
    if "blueprint" in hermes_metadata or "config" in hermes_metadata:
        fail("skill-runtime-metadata-rejected", str(path))
    if "!`" in body:
        fail("skill-inline-expansion-rejected", str(path))
    result = scan_skill(path.parent, source="managed-local")
    if result.verdict != "safe" or result.findings:
        finding_ids = [finding.pattern_id for finding in result.findings]
        fail("skill-native-scan-failed", f"{path}: {result.verdict} {finding_ids}")


def exact_skill_tree(root: Path, expected_names: set[str], label: str) -> None:
    try:
        entries = list(root.iterdir())
    except OSError as exc:
        fail("skill-root-unreadable", f"{label}: {exc}")
    actual_names = {entry.name for entry in entries}
    if actual_names != expected_names:
        fail(
            "skill-root-inventory-drift",
            f"{label}: expected={sorted(expected_names)} actual={sorted(actual_names)}",
        )
    for entry in entries:
        mode = entry.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            fail("skill-directory-invalid", f"{label}: {entry}")
        children = list(entry.iterdir())
        if [child.name for child in children] != ["SKILL.md"]:
            fail(
                "skill-supporting-file-rejected",
                f"{label}: {entry} contains {[child.name for child in children]}",
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument(
        "--mode", choices=("source", "installed", "runtime"), required=True
    )
    parser.add_argument("--root", type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--hermes-source", type=Path, required=True)
    args = parser.parse_args()

    sys.path.insert(0, str(args.hermes_source))
    try:
        from agent.skill_utils import (
            get_all_skills_dirs,
            iter_skill_index_files,
            parse_frontmatter,
        )
        from tools.skill_manager_tool import _validate_frontmatter
        from tools.skills_guard import scan_skill
    except ImportError as exc:
        fail("hermes-native-import-failed", str(exc))

    contract = load_contract(args.contract)
    if args.mode == "source" and args.root is None:
        fail("source-root-required", "--root is required for source mode")
    profiles = contract.get("profiles")
    if not isinstance(profiles, dict) or set(profiles) != {"astra", "dubble", "rigel"}:
        fail("profile-inventory-invalid", repr(sorted((profiles or {}).keys())))
    if args.profile:
        if args.profile not in profiles:
            fail("profile-unknown", args.profile)
        profiles = {args.profile: profiles[args.profile]}

    seen_names: set[tuple[str, str]] = set()
    expected_source_paths: set[Path] = set()
    for profile_name, profile in profiles.items():
        skills = profile.get("skills")
        if not isinstance(skills, list) or not skills:
            fail("profile-skills-empty", profile_name)
        expected_names = {skill["name"] for skill in skills}
        if len(expected_names) != len(skills):
            fail("profile-skill-name-duplicate", profile_name)
        if args.mode in {"installed", "runtime"}:
            tree_root = Path(
                profile["managedRoot"]
                if args.mode == "installed"
                else profile["runtimeRoot"]
            )
            exact_skill_tree(tree_root, expected_names, profile_name)
        for skill in skills:
            key = (profile_name, skill["name"])
            if key in seen_names:
                fail("skill-duplicate", repr(key))
            seen_names.add(key)
            if args.mode == "source":
                path = source_skill_path(args.root, skill)
                expected_source_paths.add(path.resolve())
            elif args.mode == "installed":
                path = installed_skill_path(profile, skill)
            else:
                path = runtime_skill_path(profile, skill)
            validate_skill(
                path,
                profile_name,
                skill,
                parse_frontmatter,
                _validate_frontmatter,
                scan_skill,
                int(contract["validation"]["descriptionPromptLimit"]),
            )

        if args.mode == "runtime":
            runtime_root = Path(profile["runtimeRoot"]).resolve()
            indexed_paths = {
                path.resolve()
                for skills_dir in get_all_skills_dirs()
                if skills_dir.is_dir()
                for path in iter_skill_index_files(skills_dir, "SKILL.md")
            }
            expected_paths = {
                (runtime_root / skill["name"] / "SKILL.md").resolve()
                for skill in skills
            }
            if not expected_paths.issubset(indexed_paths):
                fail(
                    "native-skill-index-missing",
                    f"{profile_name}: missing={sorted(map(str, expected_paths - indexed_paths))}",
                )

    if args.mode == "source" and not args.profile:
        source_root = args.root / "files" / "hermes" / "profile-skills"
        actual = {path.resolve() for path in source_root.rglob("*") if path.is_file()}
        if actual != expected_source_paths:
            fail(
                "source-skill-inventory-drift",
                f"expected={len(expected_source_paths)} actual={len(actual)}",
            )

    print(
        json.dumps(
            {
                "status": "ok",
                "mode": args.mode,
                "profiles": sorted(profiles),
                "skills": len(seen_names),
                "uid": os.geteuid(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
