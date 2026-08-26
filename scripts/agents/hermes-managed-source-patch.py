#!/usr/bin/env python3
"""Promote the reviewed Hermes parity patch on a maintained update branch."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


OFFICIAL_ORIGINS = {
    "https://github.com/NousResearch/hermes-agent.git",
    "https://github.com/NousResearch/hermes-agent",
    "git@github.com:NousResearch/hermes-agent.git",
}
PATCH_PATHS = {
    "agent/conversation_loop.py",
    "agent/todo_stop.py",
    "agent/turn_context.py",
    "cron/executions.py",
    "cron/scheduler.py",
    "gateway/platforms/base.py",
    "gateway/run.py",
    "gateway/shutdown_flush.py",
    "hermes_cli/cron.py",
    "hermes_cli/config_defaults.py",
    "plugins/memory/mem0/__init__.py",
    "run_agent.py",
    "tests/agent/test_todo_stop.py",
    "tests/cron/test_execution_ledger.py",
    "tests/cron/test_scheduler.py",
    "tests/gateway/test_queued_event_shutdown_replay.py",
    "tests/plugins/memory/test_mem0_shutdown.py",
    "tests/run_agent/test_memory_sync_interrupted.py",
    "tools/lazy_deps.py",
}
REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


def run(command: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        raise RuntimeError(f"command failed ({command[0]}): {detail[0] if detail else completed.returncode}")
    return completed


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["/usr/bin/git", *args], cwd=root, check=check)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--patch", required=True, type=Path)
    parser.add_argument("--validator", required=True, type=Path)
    parser.add_argument("--branch", default="astra-managed-parity")
    parser.add_argument("--target-branch", default="main")
    parser.add_argument("--staging-root", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def validate_inputs(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    root = args.source_root.resolve(strict=True)
    patch = args.patch.resolve(strict=True)
    validator = args.validator.resolve(strict=True)
    if root.is_symlink() or not (root / ".git").exists():
        raise ValueError("source root must be a real Git checkout")
    if patch.is_symlink() or not patch.is_file():
        raise ValueError("patch must be a regular file")
    if validator.is_symlink() or not validator.is_file():
        raise ValueError("validator must be a regular file")
    if not REF_RE.fullmatch(args.branch) or not REF_RE.fullmatch(args.target_branch):
        raise ValueError("invalid branch name")
    origin = git(root, "remote", "get-url", "origin").stdout.strip()
    if origin not in OFFICIAL_ORIGINS:
        raise ValueError("Hermes checkout origin is not official")
    status = git(root, "status", "--porcelain=v1").stdout
    if status:
        raise ValueError("Hermes checkout has uncommitted changes")
    return root, patch, validator


def validator_ok(validator: Path, root: Path) -> bool:
    completed = run(
        [sys.executable, str(validator), "--source-root", str(root)],
        cwd=root,
        check=False,
    )
    return completed.returncode == 0


def main() -> int:
    args = parse_args()
    worktree: Path | None = None
    previous_branch_head: str | None = None
    branch_ref_changed = False
    original_branch: str | None = None
    applied = False
    try:
        root, patch, validator = validate_inputs(args)
        current = git(root, "branch", "--show-current").stdout.strip()
        original_branch = current
        head = git(root, "rev-parse", "HEAD").stdout.strip()
        if current == args.branch and validator_ok(validator, root):
            print(json.dumps({"branch": current, "changed": False, "head": head, "status": "current"}, sort_keys=True))
            return 0
        if current not in {args.target_branch, args.branch}:
            raise ValueError(f"expected {args.target_branch} or {args.branch}, found {current or 'detached'}")
        if current == args.target_branch and validator_ok(validator, root):
            print(json.dumps({"branch": current, "changed": False, "head": head, "status": "upstream"}, sort_keys=True))
            return 0
        target_ref = f"refs/heads/{args.target_branch}"
        if git(root, "show-ref", "--verify", "--quiet", target_ref, check=False).returncode != 0:
            raise ValueError(f"target branch does not exist: {args.target_branch}")
        base_head = git(root, "rev-parse", target_ref).stdout.strip()
        branch_exists = git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{args.branch}", check=False).returncode == 0
        if branch_exists:
            previous_branch_head = git(root, "rev-parse", f"refs/heads/{args.branch}").stdout.strip()

        staging_root = args.staging_root.resolve()
        staging_root.mkdir(parents=True, exist_ok=True)
        if staging_root.is_symlink() or not staging_root.is_dir():
            raise ValueError("staging root must be a real directory")
        worktree = Path(tempfile.mkdtemp(prefix="managed-parity-patch-", dir=staging_root))
        worktree.rmdir()
        git(root, "worktree", "add", "--detach", str(worktree), base_head)
        git(worktree, "apply", "--check", "--whitespace=error-all", str(patch))
        git(worktree, "apply", "--whitespace=error-all", str(patch))
        changed = {
            line[3:]
            for line in git(
                worktree,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ).stdout.splitlines()
        }
        if changed != PATCH_PATHS:
            raise ValueError(f"patch changed unexpected paths: {sorted(changed)}")
        run([sys.executable, str(validator), "--source-root", str(worktree)], cwd=worktree)
        env = os.environ.copy()
        env["PYTHONPYCACHEPREFIX"] = str(worktree / ".managed-pycache")
        compile_result = subprocess.run(
            [sys.executable, "-m", "py_compile", *sorted(PATCH_PATHS)],
            cwd=worktree,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            raise RuntimeError("patched Hermes sources failed bytecode compilation")
        shutil.rmtree(worktree / ".managed-pycache", ignore_errors=True)
        for test_path in (
            "tests/agent/test_todo_stop.py",
            "tests/plugins/memory/test_mem0_shutdown.py",
            "tests/run_agent/test_memory_sync_interrupted.py",
        ):
            test_result = subprocess.run(
                [sys.executable, test_path],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            shutil.rmtree(worktree / ".managed-pycache", ignore_errors=True)
            if test_result.returncode != 0:
                detail = (test_result.stderr or test_result.stdout).strip().splitlines()
                raise RuntimeError(
                    f"patched Hermes regression failed ({test_path}): "
                    + (
                        " | ".join(detail[-12:])
                        if detail
                        else str(test_result.returncode)
                    )
                )
        if not args.apply:
            print(json.dumps({"branch": args.branch, "changed": False, "head": base_head, "status": "ready"}, sort_keys=True))
            return 0
        git(worktree, "add", "--", *sorted(PATCH_PATHS))
        git(
            worktree,
            "-c", "user.name=Astra Managed Runtime",
            "-c", "user.email=astra-managed-runtime@localhost",
            "commit", "-m", "fix(runtime): preserve managed Hermes parity",
            "--", *sorted(PATCH_PATHS),
        )
        managed_head = git(worktree, "rev-parse", "HEAD").stdout.strip()
        if git(worktree, "status", "--porcelain=v1").stdout:
            raise ValueError("managed patch worktree is not clean after commit")
        git(root, "worktree", "remove", "--force", str(worktree))
        worktree = None
        if current == args.branch:
            git(root, "switch", args.target_branch)
        git(root, "branch", "-f", args.branch, managed_head)
        branch_ref_changed = True
        git(root, "switch", args.branch)
        if git(root, "rev-parse", "HEAD").stdout.strip() != managed_head:
            raise ValueError("live checkout did not switch to managed commit")
        applied = True
        print(json.dumps({"branch": args.branch, "changed": True, "head": managed_head, "status": "applied"}, sort_keys=True))
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"hermes-managed-source-patch-error:{exc}", file=sys.stderr)
        return 2
    finally:
        if worktree is not None and worktree.exists():
            try:
                git(args.source_root.resolve(), "worktree", "remove", "--force", str(worktree))
            except Exception:
                pass
        if branch_ref_changed and not applied:
            try:
                root = args.source_root.resolve()
                current = git(root, "branch", "--show-current").stdout.strip()
                if current == args.branch:
                    git(root, "switch", args.target_branch)
                if previous_branch_head is None:
                    git(root, "branch", "-D", args.branch)
                else:
                    git(root, "branch", "-f", args.branch, previous_branch_head)
                if original_branch == args.branch:
                    git(root, "switch", args.branch)
            except Exception:
                pass
        elif not applied and original_branch == args.branch:
            try:
                root = args.source_root.resolve()
                if git(root, "branch", "--show-current").stdout.strip() != args.branch:
                    git(root, "switch", args.branch)
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
