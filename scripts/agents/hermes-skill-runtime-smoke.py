#!/usr/bin/env python3
"""Exercise approval-free, profile-local Hermes skill writes safely."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def parse_result(raw: str, action: str) -> dict[str, Any]:
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{action} returned invalid JSON") from exc
    require(isinstance(result, dict), f"{action} returned a non-object result")
    require(result.get("success") is True, f"{action} failed: {result.get('error')}")
    require(result.get("staged") is not True, f"{action} was staged for approval")
    return result


def pending_ids(home: Path) -> set[str]:
    pending = home / "pending" / "skills"
    if not pending.exists():
        return set()
    return {path.name for path in pending.glob("*.json") if path.is_file()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--managed-skill", required=True)
    parser.add_argument("--home")
    parser.add_argument("--account-home")
    parser.add_argument("--managed-dir")
    parser.add_argument("--managed-skills-root")
    args = parser.parse_args()

    home_raw = args.home or os.environ.get("HERMES_HOME", "")
    require(bool(home_raw), "HERMES_HOME is required")
    home = Path(home_raw).resolve()
    require(home.name == args.profile, "HERMES_HOME does not match --profile")
    os.environ["HERMES_HOME"] = str(home)
    if args.account_home:
        os.environ["HOME"] = str(Path(args.account_home).resolve())
    if args.managed_dir:
        os.environ["HERMES_MANAGED_DIR"] = str(Path(args.managed_dir).resolve())

    from tools.skill_manager_tool import _guard_agent_created_enabled, skill_manage
    from tools.write_approval import SKILLS, write_approval_enabled

    skills = home / "skills"
    managed_root = Path(args.managed_skills_root).resolve() if args.managed_skills_root else skills / "managed"
    managed = managed_root / args.managed_skill
    require((managed / "SKILL.md").is_file(), "managed skill is missing")
    require(not os.access(managed, os.W_OK), "managed skill directory is writable")
    require(not os.access(managed / "SKILL.md", os.W_OK), "managed SKILL.md is writable")
    require(write_approval_enabled(SKILLS) is False, "skill write approval is enabled")
    require(_guard_agent_created_enabled() is True, "agent-created skill guard is disabled")

    name = f"codex-runtime-smoke-{args.profile}"
    test_dir = skills / name
    require(not test_dir.exists(), "test skill already exists")
    before_pending = pending_ids(home)
    actions: list[str] = []

    content = (
        "---\n"
        f"name: {name}\n"
        "description: Temporary runtime skill test.\n"
        "---\n\n"
        "# Runtime Smoke\n\n"
        "Marker: v1\n"
    )

    try:
        parse_result(skill_manage(action="create", name=name, content=content), "create")
        actions.append("create")
        require((test_dir / "SKILL.md").is_file(), "created SKILL.md is missing")

        parse_result(
            skill_manage(
                action="patch",
                name=name,
                old_string="Marker: v1",
                new_string="Marker: v2",
            ),
            "patch",
        )
        actions.append("patch")
        require("Marker: v2" in (test_dir / "SKILL.md").read_text(), "patch did not persist")

        parse_result(
            skill_manage(
                action="write_file",
                name=name,
                file_path="references/smoke.txt",
                file_content="temporary runtime validation\n",
            ),
            "write_file",
        )
        actions.append("write_file")
        require((test_dir / "references" / "smoke.txt").is_file(), "support file is missing")

        parse_result(
            skill_manage(
                action="remove_file",
                name=name,
                file_path="references/smoke.txt",
            ),
            "remove_file",
        )
        actions.append("remove_file")

        parse_result(skill_manage(action="delete", name=name), "delete")
        actions.append("delete")
        require(not test_dir.exists(), "deleted test skill remains")
        require(pending_ids(home) == before_pending, "skill approval records changed")
    finally:
        if test_dir.exists():
            shutil.rmtree(test_dir)

    print(
        json.dumps(
            {
                "actions": actions,
                "agentCreatedGuard": True,
                "managedSkillProtected": True,
                "pendingUnchanged": True,
                "profile": args.profile,
                "status": "ok",
                "writeApproval": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
