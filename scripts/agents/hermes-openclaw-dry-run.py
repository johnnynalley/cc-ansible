#!/usr/bin/env python3
"""Run the pinned Hermes importer against a root-built shape-only source view."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import grp
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


class DryRunError(RuntimeError):
    """Raised when the protected dry-run boundary is not satisfied."""


PLACEHOLDER = "Source object present; raw content withheld from importer dry run.\n"
STANDARD_DOCS = (
    "AGENTS.md",
    "BOOTSTRAP.md",
    "HEARTBEAT.md",
    "IDENTITY.md",
    "MEMORY.md",
    "SOUL.md",
    "TOOLS.md",
    "USER.md",
)
SKILL_ROOTS = (
    ("workspace-skills", "workspace/skills"),
    ("project-skills", "workspace/.agents/skills"),
    ("shared-skills", "skills"),
)
SAFE_THINKING = {"adaptive", "always", "auto", "high", "low", "medium", "minimal", "none", "off", "xhigh"}
SAFE_MODES = {"always", "auto", "both", "daily", "idle", "manual", "natural", "none", "off", "smart"}
MAX_SOURCE_OBJECTS = 20000
MAX_ALLOWLIST_PATTERNS = 10000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    require_regular(path, "JSON source")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DryRunError("A required JSON source is unreadable or malformed") from exc
    if not isinstance(value, dict):
        raise DryRunError("A required JSON source is not an object")
    return value


def require_directory(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise DryRunError(f"{label} is missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise DryRunError(f"{label} must be a non-symlink directory")


def require_regular(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise DryRunError(f"{label} is missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise DryRunError(f"{label} must be a non-symlink regular file")


def require_pinned_venv_python(runtime: dict[str, Any]) -> None:
    python = Path(runtime["python"])
    metadata = python.lstat()
    if not stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_gid != 0:
        raise DryRunError("The Hermes venv Python must be the pinned root-owned symlink")
    if os.readlink(python) != runtime["pythonLinkTarget"]:
        raise DryRunError("The Hermes venv Python symlink target differs from the contract")
    resolved = python.resolve(strict=True)
    if str(resolved) != runtime["pythonResolvedTarget"]:
        raise DryRunError("The Hermes venv Python resolved target differs from the contract")
    require_regular(resolved, "Hermes resolved Python runtime")
    resolved_metadata = resolved.stat()
    if resolved_metadata.st_uid != 0 or resolved_metadata.st_gid != 0:
        raise DryRunError("The Hermes resolved Python runtime is not root-owned")
    if stat.S_IMODE(resolved_metadata.st_mode) & 0o022:
        raise DryRunError("The Hermes resolved Python runtime is group- or world-writable")
    if sha256_file(resolved) != runtime["pythonResolvedSha256"]:
        raise DryRunError("The Hermes resolved Python runtime hash differs from the contract")

    venv_config = Path(runtime["venvConfig"])
    require_regular(venv_config, "Hermes venv config")
    venv_metadata = venv_config.stat()
    if venv_metadata.st_uid != 0 or venv_metadata.st_gid != 0:
        raise DryRunError("The Hermes venv config is not root-owned")
    if stat.S_IMODE(venv_metadata.st_mode) & 0o022:
        raise DryRunError("The Hermes venv config is group- or world-writable")
    if sha256_file(venv_config) != runtime["venvConfigSha256"]:
        raise DryRunError("The Hermes venv config hash differs from the contract")


def regular_children(root: Path, suffix: str | None = None) -> list[Path]:
    if not root.exists():
        return []
    require_directory(root, "allowlisted source directory")
    files: list[Path] = []
    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        metadata = entry.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise DryRunError("An allowlisted source directory contains a symlink")
        if stat.S_ISREG(metadata.st_mode) and (suffix is None or entry.name.endswith(suffix)):
            files.append(entry)
    return files


def skill_sources(root: Path) -> tuple[list[Path], int]:
    if not root.exists():
        return [], 0
    require_directory(root, "skill source")
    skills: list[Path] = []
    symlink_count = 0
    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        metadata = entry.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            symlink_count += 1
            continue
        if not stat.S_ISDIR(metadata.st_mode):
            continue
        descriptor = entry / "SKILL.md"
        if descriptor.exists():
            require_regular(descriptor, "skill descriptor")
            skills.append(descriptor)
    return skills, symlink_count


def collect_source_objects(
    source: Path,
    workspace: Path,
) -> tuple[dict[str, list[Path]], dict[str, int]]:
    objects: dict[str, list[Path]] = {"config": [], "approvals": [], "docs": [], "dailyMemory": []}
    skill_symlink_counts: dict[str, int] = {}
    config = source / "openclaw.json"
    approvals = source / "exec-approvals.json"
    require_regular(config, "OpenClaw config")
    objects["config"].append(config)
    if approvals.exists():
        require_regular(approvals, "OpenClaw approval policy")
        objects["approvals"].append(approvals)

    require_directory(workspace, "OpenClaw workspace")
    for name in STANDARD_DOCS:
        candidate = workspace / name
        if candidate.exists():
            require_regular(candidate, "allowlisted workspace document")
            objects["docs"].append(candidate)
    objects["dailyMemory"] = regular_children(workspace / "memory", suffix=".md")

    for label, relative in SKILL_ROOTS:
        objects[label], skill_symlink_counts[label] = skill_sources(source / relative)

    total = sum(len(entries) for entries in objects.values()) + sum(skill_symlink_counts.values())
    if total > MAX_SOURCE_OBJECTS:
        raise DryRunError("The allowlisted source inventory exceeds its object bound")
    return objects, skill_symlink_counts


def source_fingerprint(
    objects: dict[str, list[Path]],
    skill_symlink_counts: dict[str, int],
) -> tuple[dict[str, tuple[int, str]], dict[str, Any]]:
    internal: dict[str, tuple[int, str]] = {}
    categories: dict[str, int] = {}
    aggregate = hashlib.sha256()
    for category in sorted(objects):
        entries = objects[category]
        symlink_count = skill_symlink_counts.get(category, 0)
        categories[category] = len(entries) + symlink_count
        if symlink_count:
            aggregate.update(category.encode("utf-8"))
            aggregate.update(b"\0anonymous-symlink-count\0")
            aggregate.update(str(symlink_count).encode("ascii"))
            aggregate.update(b"\n")
        for path in entries:
            digest = sha256_file(path)
            size = path.stat().st_size
            key = str(path)
            internal[key] = (size, digest)
            aggregate.update(category.encode("utf-8"))
            aggregate.update(b"\0")
            aggregate.update(path.name.encode("utf-8"))
            aggregate.update(b"\0")
            aggregate.update(str(size).encode("ascii"))
            aggregate.update(b"\0")
            aggregate.update(digest.encode("ascii"))
            aggregate.update(b"\n")
    return internal, {
        "objectCount": len(internal) + sum(skill_symlink_counts.values()),
        "categories": categories,
        "aggregateSha256": aggregate.hexdigest(),
    }


def bounded_int(value: Any, minimum: int = 0, maximum: int = 86400) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if minimum <= value <= maximum else None


def safe_mode(value: Any, allowed: set[str] = SAFE_MODES) -> str | None:
    if isinstance(value, str) and value in allowed:
        return value
    return None


def shape_openclaw_config(config: dict[str, Any], staged_workspace: Path) -> dict[str, Any]:
    shaped: dict[str, Any] = {}
    agents = config.get("agents") if isinstance(config.get("agents"), dict) else {}
    defaults = agents.get("defaults") if isinstance(agents.get("defaults"), dict) else {}
    shaped_defaults: dict[str, Any] = {"workspace": str(staged_workspace)}

    for key, maximum in (("contextTokens", 10000000), ("timeoutSeconds", 86400)):
        value = bounded_int(defaults.get(key), maximum=maximum)
        if value is not None:
            shaped_defaults[key] = value
    if isinstance(defaults.get("verboseDefault"), bool):
        shaped_defaults["verboseDefault"] = defaults["verboseDefault"]
    thinking = safe_mode(defaults.get("thinkingDefault"), SAFE_THINKING)
    if thinking:
        shaped_defaults["thinkingDefault"] = thinking
    timezone_value = defaults.get("userTimezone")
    if isinstance(timezone_value, str) and re.fullmatch(r"[A-Za-z_]+(?:/[A-Za-z0-9_+.-]+)+", timezone_value):
        shaped_defaults["userTimezone"] = timezone_value

    compaction = defaults.get("compaction") if isinstance(defaults.get("compaction"), dict) else {}
    compaction_mode = safe_mode(compaction.get("mode"))
    if compaction:
        shaped_defaults["compaction"] = {"mode": compaction_mode or "auto"}

    human_delay = defaults.get("humanDelay") if isinstance(defaults.get("humanDelay"), dict) else {}
    shaped_delay: dict[str, Any] = {}
    delay_mode = safe_mode(human_delay.get("mode"))
    if delay_mode:
        shaped_delay["mode"] = delay_mode
    if isinstance(human_delay.get("enabled"), bool):
        shaped_delay["enabled"] = human_delay["enabled"]
    for key in ("minMs", "maxMs"):
        value = bounded_int(human_delay.get(key), maximum=600000)
        if value is not None:
            shaped_delay[key] = value
    if shaped_delay:
        shaped_defaults["humanDelay"] = shaped_delay

    sandbox = defaults.get("sandbox") if isinstance(defaults.get("sandbox"), dict) else {}
    backend = sandbox.get("backend")
    if backend in {"docker", "local", "podman", "ssh"}:
        shaped_defaults["sandbox"] = {"backend": backend}

    agent_list = agents.get("list") if isinstance(agents.get("list"), list) else []
    shaped["agents"] = {
        "defaults": shaped_defaults,
        "list": [{} for _ in agent_list],
    }
    bindings = config.get("bindings") if isinstance(config.get("bindings"), list) else []
    if bindings:
        shaped["bindings"] = [{} for _ in bindings]

    if config.get("cron"):
        shaped["cron"] = {"present": True}

    session = config.get("session") if isinstance(config.get("session"), dict) else {}
    shaped_session: dict[str, Any] = {}
    reset = session.get("reset") if isinstance(session.get("reset"), dict) else {}
    shaped_reset: dict[str, Any] = {}
    reset_mode = safe_mode(reset.get("mode"))
    if reset_mode:
        shaped_reset["mode"] = reset_mode
    at_hour = bounded_int(reset.get("atHour"), maximum=23)
    idle_minutes = bounded_int(reset.get("idleMinutes"), maximum=10080)
    if at_hour is not None:
        shaped_reset["atHour"] = at_hour
    if idle_minutes is not None:
        shaped_reset["idleMinutes"] = idle_minutes
    if shaped_reset:
        shaped_session["reset"] = shaped_reset
    triggers = session.get("resetTriggers") or session.get("reset_triggers")
    if isinstance(triggers, list):
        safe_triggers = [item for item in triggers if item in {"daily", "idle"}]
        if safe_triggers:
            shaped_session["resetTriggers"] = safe_triggers
    for key in ("identityLinks", "maintenance", "scope", "sendPolicy", "threadBindings"):
        if session.get(key):
            shaped_session[key] = {"present": True}
    if shaped_session:
        shaped["session"] = shaped_session

    tools = config.get("tools") if isinstance(config.get("tools"), dict) else {}
    if tools:
        exec_config = tools.get("exec") if isinstance(tools.get("exec"), dict) else {}
        timeout_value = bounded_int(exec_config.get("timeoutSec") or exec_config.get("timeout"), maximum=86400)
        shaped["tools"] = {"exec": {"timeoutSec": timeout_value}} if timeout_value is not None else {"present": True}

    approvals = config.get("approvals") if isinstance(config.get("approvals"), dict) else {}
    if approvals:
        approval_mode = approvals.get("mode") or approvals.get("defaultMode")
        exec_approvals = approvals.get("exec") if isinstance(approvals.get("exec"), dict) else {}
        approval_mode = exec_approvals.get("mode") or approval_mode
        shaped["approvals"] = {"mode": safe_mode(approval_mode) or "manual", "rulesPresent": True}

    for key in ("memory", "ui", "logging", "diagnostics"):
        if config.get(key):
            shaped[key] = {"present": True}

    skills = config.get("skills") if isinstance(config.get("skills"), dict) else {}
    entries = skills.get("entries") if isinstance(skills.get("entries"), dict) else {}
    if skills:
        shaped["skills"] = {
            "entries": {f"skill-{index:04d}": {} for index in range(1, len(entries) + 1)},
            "present": True,
        }
    return shaped


def approval_pattern_count(path: Path | None) -> int:
    if path is None:
        return 0
    data = load_json(path)
    patterns: set[str] = set()
    agents = data.get("agents") if isinstance(data.get("agents"), dict) else {}
    for agent in agents.values():
        if not isinstance(agent, dict):
            continue
        allowlist = agent.get("allowlist") if isinstance(agent.get("allowlist"), list) else []
        for entry in allowlist:
            if isinstance(entry, dict) and isinstance(entry.get("pattern"), str):
                patterns.add(entry["pattern"])
    if len(patterns) > MAX_ALLOWLIST_PATTERNS:
        raise DryRunError("The legacy approval inventory exceeds its pattern bound")
    return len(patterns)


def ensure_owned(path: Path, uid: int, gid: int, mode: int) -> None:
    os.chown(path, uid, gid, follow_symlinks=False)
    os.chmod(path, mode, follow_symlinks=False)


def write_text(path: Path, content: str, uid: int, gid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    ensure_owned(path, uid, gid, 0o440)


def write_json(path: Path, value: Any, uid: int = 0, gid: int = 0, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    ensure_owned(path, uid, gid, mode)


def stage_shape_view(
    source: Path,
    workspace: Path,
    target_config: Path,
    generation: Path,
    executor_gid: int,
) -> tuple[Path, Path, dict[str, Any]]:
    require_directory(source, "OpenClaw source")
    require_directory(workspace, "OpenClaw workspace")
    require_regular(target_config, "Hermes Astra config")
    objects, before_symlink_counts = collect_source_objects(source, workspace)
    before_internal, before_public = source_fingerprint(objects, before_symlink_counts)

    source_view = generation / "source"
    target_view = generation / "target"
    source_view.mkdir(parents=True)
    target_view.mkdir()
    for directory in (generation, source_view, target_view):
        ensure_owned(directory, 0, executor_gid, 0o750)

    raw_config = load_json(source / "openclaw.json")
    shaped_config = shape_openclaw_config(raw_config, source_view / "workspace")
    write_json(source_view / "openclaw.json", shaped_config, 0, executor_gid, 0o440)

    approvals_path = objects["approvals"][0] if objects["approvals"] else None
    pattern_count = approval_pattern_count(approvals_path)
    if pattern_count:
        shaped_approvals = {
            "agents": {
                "shape-only": {
                    "allowlist": [
                        {"pattern": f"legacy-pattern-{index:04d}"}
                        for index in range(1, pattern_count + 1)
                    ]
                }
            }
        }
        write_json(source_view / "exec-approvals.json", shaped_approvals, 0, executor_gid, 0o440)

    doc_names = {path.name for path in objects["docs"]}
    for name in sorted(doc_names):
        write_text(source_view / "workspace" / name, PLACEHOLDER, 0, executor_gid)

    daily_count = len(objects["dailyMemory"])
    for index in range(1, daily_count + 1):
        write_text(
            source_view / "workspace" / "memory" / f"entry-{index:04d}.md",
            PLACEHOLDER,
            0,
            executor_gid,
        )
    if daily_count:
        learnings = source_view / "workspace" / ".learnings"
        learnings.mkdir(parents=True, exist_ok=True)
        ensure_owned(learnings, 0, executor_gid, 0o750)
        write_text(learnings / "PRESENT.md", PLACEHOLDER, 0, executor_gid)

    for label, relative in SKILL_ROOTS:
        count = len(objects[label]) + before_symlink_counts[label]
        for index in range(1, count + 1):
            write_text(
                source_view / relative / f"skill-{index:04d}" / "SKILL.md",
                PLACEHOLDER,
                0,
                executor_gid,
            )

    shutil.copyfile(target_config, target_view / "config.yaml")
    ensure_owned(target_view / "config.yaml", 0, executor_gid, 0o440)

    for root, directories, files in os.walk(generation):
        root_path = Path(root)
        for name in directories:
            path = root_path / name
            if path.is_symlink():
                raise DryRunError("The shape-only view unexpectedly contains a symlink")
            ensure_owned(path, 0, executor_gid, 0o550)
        for name in files:
            path = root_path / name
            if path.is_symlink():
                raise DryRunError("The shape-only view unexpectedly contains a symlink")
            ensure_owned(path, 0, executor_gid, 0o440)
    ensure_owned(generation, 0, executor_gid, 0o550)

    after_objects, after_symlink_counts = collect_source_objects(source, workspace)
    after_internal, _ = source_fingerprint(after_objects, after_symlink_counts)
    if before_internal != after_internal or before_symlink_counts != after_symlink_counts:
        raise DryRunError("The allowlisted OpenClaw source changed while the protected view was staged")

    shape_summary = {
        "schemaVersion": 1,
        "rawContentCopied": False,
        "source": before_public,
        "legacyAllowlistPatternCount": pattern_count,
        "stagedDocumentCount": len(doc_names),
        "stagedDailyMemoryPlaceholderCount": daily_count,
        "stagedSkillPlaceholderCounts": {
            label: len(objects[label]) + before_symlink_counts[label]
            for label, _ in SKILL_ROOTS
        },
        "representedSkillSymlinkCount": sum(before_symlink_counts.values()),
        "symlinkTargetsRead": False,
    }
    return source_view, target_view, shape_summary


def tree_manifest(root: Path) -> dict[str, tuple[int, int, int, str]]:
    manifest: dict[str, tuple[int, int, int, str]] = {}
    for current, directories, files in os.walk(root):
        current_path = Path(current)
        for name in sorted(directories + files):
            path = current_path / name
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise DryRunError("A protected dry-run tree contains a symlink")
            relative = path.relative_to(root).as_posix()
            if stat.S_ISDIR(metadata.st_mode):
                digest = "directory"
            elif stat.S_ISREG(metadata.st_mode):
                digest = sha256_file(path)
            else:
                raise DryRunError("A protected dry-run tree contains a special file")
            manifest[relative] = (
                stat.S_IMODE(metadata.st_mode),
                metadata.st_uid,
                metadata.st_gid,
                digest,
            )
    return manifest


def structural_report(report: dict[str, Any], selected: list[str]) -> dict[str, Any]:
    if report.get("mode") != "dry-run":
        raise DryRunError("The importer did not return a dry-run report")
    if report.get("migrate_secrets") != "[redacted]":
        raise DryRunError("The importer report has an unexpected secret-migration marker")
    if report.get("output_dir") is not None or report.get("workspace_target") is not None:
        raise DryRunError("The importer report indicates a write-capable destination")
    selection = report.get("selection") if isinstance(report.get("selection"), dict) else {}
    if selection.get("selected") != sorted(selected):
        raise DryRunError("The importer selected options differ from the contract")

    items = report.get("items") if isinstance(report.get("items"), list) else []
    counts = Counter()
    kinds: dict[str, Counter[str]] = {}
    for item in items:
        if not isinstance(item, dict):
            raise DryRunError("The importer returned a malformed item")
        kind = item.get("kind")
        status_value = item.get("status")
        if not isinstance(kind, str) or not isinstance(status_value, str):
            raise DryRunError("The importer returned an unclassified item")
        counts[status_value] += 1
        kinds.setdefault(kind, Counter())[status_value] += 1

    return {
        "schemaVersion": 1,
        "mode": "dry-run",
        "selectedOptions": sorted(selected),
        "summary": dict(sorted(counts.items())),
        "kinds": {
            kind: dict(sorted(statuses.items())) for kind, statuses in sorted(kinds.items())
        },
        "rawImporterReportPersisted": False,
        "itemDetailsPersisted": False,
        "secretMigrationArgumentPassed": False,
        "forbiddenOptionsSelected": False,
    }


def validate_contract(contract: dict[str, Any]) -> None:
    expected_top = {"schemaVersion", "mode", "runtime", "paths", "executor", "selectedOptions", "forbiddenOptions", "sourceShape", "execution", "report"}
    if set(contract) != expected_top:
        raise DryRunError("The dry-run contract has unknown or missing top-level fields")
    if contract.get("schemaVersion") != 1 or contract.get("mode") != "shape-only-dry-run":
        raise DryRunError("The dry-run contract schema or mode is unsupported")
    runtime = contract.get("runtime") or {}
    if set(runtime) != {
        "release",
        "commit",
        "python",
        "pythonLinkTarget",
        "pythonResolvedTarget",
        "pythonResolvedSha256",
        "venvConfig",
        "venvConfigSha256",
        "engine",
        "engineSha256",
    }:
        raise DryRunError("The dry-run runtime contract is incomplete or ambiguous")
    selected = contract.get("selectedOptions")
    forbidden = contract.get("forbiddenOptions")
    if not isinstance(selected, list) or not selected or selected != sorted(set(selected)):
        raise DryRunError("Selected importer options must be a sorted unique list")
    if not isinstance(forbidden, list) or forbidden != sorted(set(forbidden)):
        raise DryRunError("Forbidden importer options must be a sorted unique list")
    if set(selected) & set(forbidden):
        raise DryRunError("An importer option is both selected and forbidden")
    source_shape = contract.get("sourceShape") or {}
    execution = contract.get("execution") or {}
    report = contract.get("report") or {}
    if any(source_shape.values()):
        raise DryRunError("The source-shape contract authorizes unsafe content")
    if any(execution.values()):
        raise DryRunError("The execution contract authorizes mutation or activation")
    if report != {
        "rawImporterReportPersisted": False,
        "itemDetailsPersisted": False,
        "sourceValuesPersisted": False,
        "aggregateOnlyStdout": True,
        "mode": "0600",
    }:
        raise DryRunError("The report contract is not aggregate-only and private")
    executor = contract.get("executor") or {}
    if any(executor.get(key) for key in ("network", "capabilities", "sourceWritable", "targetWritable")):
        raise DryRunError("The importer executor contract grants excess authority")


def run_importer(
    contract: dict[str, Any],
    source_view: Path,
    target_view: Path,
    unit_name: str,
) -> dict[str, Any]:
    runtime = contract["runtime"]
    executor = contract["executor"]
    selected = contract["selectedOptions"]
    command = [
        "/usr/bin/systemd-run",
        "--wait",
        "--pipe",
        "--collect",
        "--quiet",
        f"--unit={unit_name}",
        "--property=Type=exec",
        f"--property=User={executor['user']}",
        f"--property=Group={executor['group']}",
        "--property=NoNewPrivileges=yes",
        "--property=PrivateNetwork=yes",
        "--property=PrivateTmp=yes",
        "--property=ProtectHome=yes",
        "--property=ProtectSystem=strict",
        "--property=CapabilityBoundingSet=",
        "--property=RestrictAddressFamilies=AF_UNIX",
        "--property=MemoryMax=512M",
        "--property=TasksMax=64",
        "--property=UMask=0077",
        f"--property=ReadOnlyPaths={source_view}",
        f"--property=ReadOnlyPaths={target_view}",
        "--property=InaccessiblePaths=/var/lib/hermes/astra",
        "--property=InaccessiblePaths=/var/lib/hermes/dubble",
        "--property=InaccessiblePaths=/var/lib/hermes/rigel",
        f"--property=WorkingDirectory={target_view}",
        f"--setenv=HOME={target_view}",
        f"--setenv=HERMES_HOME={target_view}",
        runtime["python"],
        runtime["engine"],
        "--source",
        str(source_view),
        "--target",
        str(target_view),
        "--include",
        ",".join(selected),
        "--json",
    ]
    forbidden_arguments = {"--execute", "--migrate-secrets", "--output-dir", "--workspace-target", "--overwrite"}
    if forbidden_arguments & set(command):
        raise DryRunError("The importer command contains a forbidden mutation argument")
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    )
    if result.returncode != 0:
        raise DryRunError("The sandboxed importer dry run failed")
    start = result.stdout.find("{")
    if start < 0:
        raise DryRunError("The sandboxed importer returned no JSON report")
    try:
        report = json.loads(result.stdout[start:])
    except json.JSONDecodeError as exc:
        raise DryRunError("The sandboxed importer returned malformed JSON") from exc
    if not isinstance(report, dict):
        raise DryRunError("The sandboxed importer report is not an object")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        print(json.dumps({"status": "error", "error": "operator-root-required"}))
        return 2

    contract_path = Path(args.contract)
    try:
        contract = load_json(contract_path)
        validate_contract(contract)
        runtime = contract["runtime"]
        paths = contract["paths"]
        engine = Path(runtime["engine"])
        require_regular(engine, "Hermes importer engine")
        if sha256_file(engine) != runtime["engineSha256"]:
            raise DryRunError("The installed Hermes importer hash differs from the contract")
        require_pinned_venv_python(runtime)

        pwd.getpwnam(contract["executor"]["user"])
        executor_gid = grp.getgrnam(contract["executor"]["group"]).gr_gid
        work_root = Path(paths["workRoot"])
        evidence_root = Path(paths["evidenceRoot"])
        work_root.mkdir(parents=True, exist_ok=True)
        ensure_owned(work_root, 0, executor_gid, 0o710)
        evidence_root.mkdir(parents=True, exist_ok=True)
        ensure_owned(evidence_root, 0, 0, 0o700)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        evidence = evidence_root / stamp
        if evidence.exists():
            raise DryRunError("The timestamped evidence directory already exists")
        generation = Path(tempfile.mkdtemp(prefix=f"{stamp}-", dir=work_root))
        ensure_owned(generation, 0, executor_gid, 0o750)
        try:
            source_view, target_view, shape_summary = stage_shape_view(
                Path(paths["source"]),
                Path(paths["workspace"]),
                Path(paths["astraConfig"]),
                generation,
                executor_gid,
            )
            source_before = tree_manifest(source_view)
            target_before = tree_manifest(target_view)
            report = run_importer(
                contract,
                source_view,
                target_view,
                f"hermes-openclaw-dry-run-{stamp.lower()}",
            )
            if source_before != tree_manifest(source_view):
                raise DryRunError("The importer changed its read-only source view")
            if target_before != tree_manifest(target_view):
                raise DryRunError("The importer changed its read-only target view")
            structural = structural_report(report, contract["selectedOptions"])
            evidence.mkdir(mode=0o700)
            write_json(evidence / "source-shape.json", shape_summary)
            write_json(evidence / "report.json", structural)
        finally:
            shutil.rmtree(generation)

        if generation.exists():
            raise DryRunError("The temporary protected view was not removed")
        proof = {
            "schemaVersion": 1,
            "status": "ok",
            "runtimeRelease": runtime["release"],
            "runtimeCommit": runtime["commit"],
            "engineSha256": runtime["engineSha256"],
            "sourceViewReadOnly": True,
            "targetViewReadOnly": True,
            "privateNetwork": True,
            "rawContentCopied": False,
            "rawImporterReportPersisted": False,
            "secretMigrationArgumentPassed": False,
            "forbiddenOptionsSelected": False,
            "temporaryViewRemoved": True,
            "summary": structural["summary"],
        }
        write_json(evidence / "proof.json", proof)

        print(json.dumps({"status": "ok", "summary": structural["summary"], "evidence": str(evidence)}))
        return 0
    except (DryRunError, KeyError, OSError, subprocess.TimeoutExpired) as exc:
        error_id = hashlib.sha256(str(exc).encode("utf-8")).hexdigest()[:12]
        print(json.dumps({"status": "error", "error": "protected-dry-run-failed", "errorId": error_id}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
