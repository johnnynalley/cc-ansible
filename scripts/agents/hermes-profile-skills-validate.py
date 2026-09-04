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
from pathlib import Path, PurePosixPath
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
    if contract.get("mode") != "reviewed-native-parity":
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


def require_safe_directory(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        fail("path-missing", f"{label}: {exc}")
    if stat.S_ISLNK(mode):
        fail("symlink-rejected", f"{label}: {path}")
    if not stat.S_ISDIR(mode):
        fail("directory-required", f"{label}: {path}")


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


def native_skill_path(profile: dict[str, Any], skill: dict[str, Any]) -> Path:
    native_root = Path(profile["nativeRoot"])
    if not native_root.is_absolute():
        fail("native-root-not-absolute", str(native_root))
    return native_root / skill["name"] / "SKILL.md"


def validate_unmounted_shared_reader_target(
    target: Path, profile_name: str, skill_name: str
) -> None:
    """Require the host-side target for a service-only read-only bind to be empty."""
    require_safe_directory(target, f"{profile_name}/{skill_name}/shared-mount")
    if any(target.iterdir()):
        fail("shared-mount-not-empty", str(target))


def supporting_files(
    skill: dict[str, Any], allowed_suffixes: set[str]
) -> list[dict[str, str]]:
    rows = skill.get("supportingFiles", [])
    if not isinstance(rows, list):
        fail("skill-supporting-files-invalid", skill.get("name", "unknown"))
    validated: list[dict[str, str]] = []
    names: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
            fail("skill-supporting-file-row-invalid", repr(row))
        relative = PurePosixPath(row["path"])
        digest = row["sha256"]
        if (
            relative.is_absolute()
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative.as_posix() == "SKILL.md"
            or relative.suffix not in allowed_suffixes
        ):
            fail("skill-supporting-file-path-rejected", row["path"])
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            fail("skill-supporting-file-hash-invalid", row["path"])
        if relative.as_posix() in names:
            fail("skill-supporting-file-duplicate", row["path"])
        names.add(relative.as_posix())
        validated.append({"path": relative.as_posix(), "sha256": digest})
    return validated


def validate_supporting_files(
    skill_root: Path,
    profile_name: str,
    skill: dict[str, Any],
    allowed_suffixes: set[str],
    require_exact_contract: bool,
) -> set[Path]:
    paths: set[Path] = set()
    for row in supporting_files(skill, allowed_suffixes):
        path = skill_root / row["path"]
        require_safe_path(path, f"{profile_name}/{skill['name']}/{row['path']}")
        if stat.S_IMODE(path.lstat().st_mode) & 0o111:
            fail("skill-supporting-file-executable", str(path))
        if require_exact_contract and sha256(path) != row["sha256"]:
            fail("skill-supporting-file-hash-drift", str(path))
        paths.add(path.resolve())
    return paths


def validate_skill(
    path: Path,
    profile_name: str,
    skill: dict[str, Any],
    parse_frontmatter: Any,
    validate_frontmatter: Any,
    scan_skill: Any,
    description_limit: int,
    require_exact_contract: bool,
) -> None:
    require_safe_path(path, f"{profile_name}/{skill['name']}")
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        fail("skill-read-failed", f"{path}: {exc}")
    if require_exact_contract and sha256(path) != skill["sha256"]:
        fail("skill-hash-drift", str(path))
    if not content.startswith("---\n"):
        fail("skill-frontmatter-offset", str(path))
    frontmatter_error = validate_frontmatter(content, new_skill=True)
    if frontmatter_error:
        fail("skill-frontmatter-invalid", f"{path}: {frontmatter_error}")
    frontmatter, body = parse_frontmatter(content)
    if frontmatter.get("name") != skill["name"]:
        fail("skill-name-drift", str(path))
    if (
        require_exact_contract
        and frontmatter.get("description") != skill["description"]
    ):
        fail("skill-description-drift", str(path))
    if len(frontmatter["description"]) > description_limit:
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


def exact_skill_directory(
    entry: Path,
    skill: dict[str, Any],
    allowed_suffixes: set[str],
    label: str,
) -> None:
    mode = entry.lstat().st_mode
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        fail("skill-directory-invalid", f"{label}: {entry}")
    expected_files = {
        "SKILL.md",
        *(row["path"] for row in supporting_files(skill, allowed_suffixes)),
    }
    actual_files: set[str] = set()
    for child in entry.rglob("*"):
        child_mode = child.lstat().st_mode
        if stat.S_ISLNK(child_mode):
            fail("skill-tree-symlink-rejected", f"{label}: {child}")
        if stat.S_ISDIR(child_mode):
            continue
        if not stat.S_ISREG(child_mode):
            fail("skill-tree-entry-invalid", f"{label}: {child}")
        actual_files.add(child.relative_to(entry).as_posix())
    if actual_files != expected_files:
        fail(
            "skill-tree-inventory-drift",
            f"{label}: {entry} expected={sorted(expected_files)} actual={sorted(actual_files)}",
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=(
            "source",
            "native",
            "plan-native",
        ),
        required=True,
    )
    parser.add_argument("--root", type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--hermes-source", type=Path, required=True)
    parser.add_argument(
        "--allow-unmounted-shared-readers",
        action="store_true",
        help=(
            "Validate empty host-side targets for shared read-only skills that "
            "are mounted only inside the Gateway service namespace"
        ),
    )
    args = parser.parse_args()

    if args.allow_unmounted_shared_readers and args.mode != "native":
        fail(
            "unmounted-shared-reader-mode-invalid",
            "--allow-unmounted-shared-readers requires --mode native",
        )

    sys.path.insert(0, str(args.hermes_source))
    try:
        from agent.skill_utils import (
            get_all_skills_dirs,
            iter_skill_index_files,
            parse_frontmatter,
        )
        from tools.skill_manager_tool import _validate_frontmatter
        from tools.skills_guard import scan_skill
        from tools.skills_tool import skill_view
    except ImportError as exc:
        fail("hermes-native-import-failed", str(exc))

    contract = load_contract(args.contract)
    validation = contract.get("validation") or {}
    if validation.get("supportingFilesAllowed") is not True:
        fail("supporting-files-policy-disabled", repr(validation))
    allowed_suffixes = set(validation.get("supportingFileSuffixes") or [])
    if allowed_suffixes != {".md", ".json", ".jsonl"}:
        fail("supporting-file-suffix-policy-invalid", repr(sorted(allowed_suffixes)))
    if args.mode in {"source", "plan-native"} and args.root is None:
        fail("source-root-required", "--root is required for source or plan-native mode")
    profiles = contract.get("profiles")
    if not isinstance(profiles, dict) or set(profiles) != {"astra", "dubble", "rigel"}:
        fail("profile-inventory-invalid", repr(sorted((profiles or {}).keys())))
    if args.profile:
        if args.profile not in profiles:
            fail("profile-unknown", args.profile)
        profiles = {args.profile: profiles[args.profile]}

    ownership = contract.get("nativeOwnership") or {}
    expected_ownership = {
        "canonicalSharedSkill": "self-evolution",
        "writerProfile": "astra",
        "readOnlyProfiles": ["dubble", "rigel"],
    }
    if args.mode in {"native", "plan-native"} and ownership != expected_ownership:
        fail("native-ownership-invalid", repr(ownership))

    seen_names: set[tuple[str, str]] = set()
    expected_source_paths: set[Path] = set()
    native_plan = {
        "absent": 0,
        "exact": 0,
        "sharedMountAbsent": 0,
        "sharedMountReady": 0,
        "nativeMetadataEntries": 0,
        "unrelatedSkillDirectories": 0,
    }
    for profile_name, profile in profiles.items():
        skipped_unmounted_shared_skills: set[str] = set()
        skills = profile.get("skills")
        if not isinstance(skills, list) or not skills:
            fail("profile-skills-empty", profile_name)
        expected_names = {skill["name"] for skill in skills}
        if len(expected_names) != len(skills):
            fail("profile-skill-name-duplicate", profile_name)
        if args.mode == "plan-native":
            native_root = Path(profile["nativeRoot"])
            require_safe_directory(native_root, f"{profile_name}/native-root")
            expected_targets = expected_names | {"managed"}
            for entry in native_root.iterdir():
                mode = entry.lstat().st_mode
                if stat.S_ISLNK(mode):
                    fail("native-root-entry-invalid", f"{profile_name}: {entry}")
                if entry.name.startswith("."):
                    if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                        fail(
                            "native-metadata-entry-invalid",
                            f"{profile_name}: {entry}",
                        )
                    native_plan["nativeMetadataEntries"] += 1
                    continue
                if not stat.S_ISDIR(mode):
                    fail("native-root-entry-invalid", f"{profile_name}: {entry}")
                if entry.name not in expected_targets:
                    native_plan["unrelatedSkillDirectories"] += 1
        for skill in skills:
            key = (profile_name, skill["name"])
            if key in seen_names:
                fail("skill-duplicate", repr(key))
            seen_names.add(key)
            if args.mode in {"source", "plan-native"}:
                path = source_skill_path(args.root, skill)
                expected_source_paths.add(path.resolve())
            elif args.mode == "native":
                path = native_skill_path(profile, skill)
            else:
                fail("unsupported-mode", args.mode)
            shared_reader = (
                skill["name"] == ownership["canonicalSharedSkill"]
                and profile_name in ownership["readOnlyProfiles"]
            )
            if (
                args.mode == "native"
                and args.allow_unmounted_shared_readers
                and shared_reader
            ):
                validate_unmounted_shared_reader_target(
                    path.parent, profile_name, skill["name"]
                )
                skipped_unmounted_shared_skills.add(skill["name"])
                continue
            validate_skill(
                path,
                profile_name,
                skill,
                parse_frontmatter,
                _validate_frontmatter,
                scan_skill,
                int(contract["validation"]["descriptionPromptLimit"]),
                args.mode != "native",
            )
            support_paths = validate_supporting_files(
                path.parent,
                profile_name,
                skill,
                allowed_suffixes,
                args.mode != "native",
            )
            if args.mode in {"source", "plan-native"}:
                expected_source_paths.update(support_paths)
            if args.mode == "plan-native":
                target = native_skill_path(profile, skill).parent
                if shared_reader:
                    if not target.exists():
                        native_plan["sharedMountAbsent"] += 1
                    else:
                        require_safe_directory(
                            target,
                            f"{profile_name}/{skill['name']}/shared-mount",
                        )
                        if any(target.iterdir()):
                            fail("shared-mount-not-empty", str(target))
                        native_plan["sharedMountReady"] += 1
                elif not target.exists():
                    native_plan["absent"] += 1
                else:
                    exact_skill_directory(
                        target,
                        skill,
                        allowed_suffixes,
                        f"{profile_name}/native-plan",
                    )
                    validate_skill(
                        target / "SKILL.md",
                        profile_name,
                        skill,
                        parse_frontmatter,
                        _validate_frontmatter,
                        scan_skill,
                        int(contract["validation"]["descriptionPromptLimit"]),
                        True,
                    )
                    validate_supporting_files(
                        target,
                        profile_name,
                        skill,
                        allowed_suffixes,
                        True,
                    )
                    native_plan["exact"] += 1
            if args.mode == "native":
                try:
                    loaded = json.loads(
                        skill_view(skill["name"], preprocess=False)
                    )
                except (json.JSONDecodeError, TypeError) as exc:
                    fail(
                        "native-skill-view-invalid",
                        f"{profile_name}/{skill['name']}: {exc}",
                    )
                if not loaded.get("success"):
                    fail(
                        "native-skill-view-failed",
                        f"{profile_name}/{skill['name']}: {loaded.get('error')}",
                    )

        if args.mode == "native":
            # Hermes indexes the profile-owned native skill tree.
            discovery_root = Path(profile["nativeRoot"]).resolve()
            indexed_paths = {
                path.resolve()
                for skills_dir in get_all_skills_dirs()
                if skills_dir.is_dir()
                for path in iter_skill_index_files(skills_dir, "SKILL.md")
            }
            expected_paths = {
                (discovery_root / skill["name"] / "SKILL.md").resolve()
                for skill in skills
                if skill["name"] not in skipped_unmounted_shared_skills
            }
            if not expected_paths.issubset(indexed_paths):
                fail(
                    "native-skill-index-missing",
                    f"{profile_name}: missing={sorted(map(str, expected_paths - indexed_paths))}",
                )

    if args.mode in {"source", "plan-native"} and not args.profile:
        source_root = args.root / "files" / "hermes" / "profile-skills"
        actual = {path.resolve() for path in source_root.rglob("*") if path.is_file()}
        if actual != expected_source_paths:
            fail(
                "source-skill-inventory-drift",
                f"expected={len(expected_source_paths)} actual={len(actual)}",
            )

    result = {
        "status": "ok",
        "mode": args.mode,
        "profiles": sorted(profiles),
        "skills": len(seen_names),
        "uid": os.geteuid(),
    }
    if args.mode == "plan-native":
        result["nativePlan"] = native_plan
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
