#!/usr/bin/env python3
"""Run a synthetic Rigel syllabus workflow without exposing live course data."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import pwd
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


class SmokeError(RuntimeError):
    """A bounded synthetic academic workflow check failed."""


CANONICAL_ACCOUNT = Path("/var/lib/hermes/rigel")
CANONICAL_PROFILE = CANONICAL_ACCOUNT / ".hermes/profiles/rigel"
COURSE_ID = "acceptance-1000"
TEST_MODEL = "gpt-5.6-sol"
EXPECTED_EVENTS = {
    "midterm": "2026-09-15",
    "project": "2026-10-20",
    "final": "2026-12-10",
}
REQUIRED_FILE_TOOLS = {"patch", "read_file", "search_files", "write_file"}
TOOL_INVENTORY_PROBE = """import json
from agent.todo_stop import max_todo_stop_nudges, todo_stop_guard_enabled
from hermes_cli.config import load_config_readonly
from model_tools import get_tool_definitions

definitions = get_tool_definitions(
    enabled_toolsets=["file", "skills", "todo"],
    quiet_mode=True,
)
config = load_config_readonly()
print(json.dumps({
    "maxTodoStopNudges": max_todo_stop_nudges(config),
    "todoStopGuard": todo_stop_guard_enabled(config),
    "toolNames": sorted(item["function"]["name"] for item in definitions),
}))
"""
FILE_READ_PROBE = """import json
from pathlib import Path
from tools.file_tools import _resolve_path_for_task, read_file_tool

expected_root = Path.cwd().resolve()
report = {}
for relative in (
    "courses/inbox/synthetic-syllabus.md",
    "courses/semester-context.md",
):
    resolved = Path(_resolve_path_for_task(relative)).resolve()
    try:
        payload = json.loads(read_file_tool(relative))
    except Exception:
        payload = {"error": "unreadable-result"}
    report[relative] = {
        "error": bool(payload.get("error")),
        "hasContent": bool(payload.get("content")),
        "resolvedMatchesExpected": resolved == (expected_root / relative).resolve(),
    }
print(json.dumps(report, sort_keys=True))
"""
SYNTHETIC_SYLLABUS = """# ACCEPTANCE 1000 - Synthetic Systems

Term: Fall 2026
Semester dates: August 24, 2026 through December 15, 2026
Instructor: Test Instructor
Office hours: Tuesday 1:00 PM-2:00 PM
Required text: Synthetic Systems, 1st edition, ISBN 978-0-00-000000-0

## Grading

- Midterm Exam: 25%, September 15, 2026 at 10:00 AM CDT
- Research Project: 20%, due October 20, 2026 at 11:59 PM CDT
- Final Exam: 35%, December 10, 2026 at 10:00 AM CST
- Weekly homework: 20% total; no individual homework is worth 10%

## Weekly topics

1. Source evaluation
2. Structured note taking
3. Retrieval practice
"""
SYNTHETIC_CONFIG = f"""model:
  provider: openai-codex
  default: {TEST_MODEL}
plugins:
  enabled: []
  disabled: []
toolsets:
  - file
  - skills
  - todo
agent:
  verify_on_stop: false
  verify_guidance: true
  max_verify_nudges: 2
  todo_stop_guard: true
  max_todo_stop_nudges: 8
  disabled_toolsets:
    - terminal
    - code_execution
    - delegation
    - web
    - memory
"""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def require(condition: bool, code: str) -> None:
    if not condition:
        raise SmokeError(code)


def require_managed_interpreter(path: Path) -> None:
    require(path.is_absolute() and path.is_file(), "hermes-python-invalid")
    try:
        resolved = path.resolve(strict=True)
        mode = resolved.stat().st_mode
    except OSError as exc:
        raise SmokeError("hermes-python-invalid") from exc
    require(resolved.is_file() and not resolved.is_symlink(), "hermes-python-invalid")
    require(mode & 0o022 == 0, "hermes-python-writable")


def classify_agent_failure(stderr: bytes) -> str:
    text = stderr.decode("utf-8", errors="replace").casefold()
    if "bwrap:" in text or "bubblewrap" in text:
        bwrap_signatures = (
            ("bind", ("bind mount", "ro-bind", "--bind")),
            ("chdir", ("chdir", "working directory")),
            ("identity", ("uid map", "gid map", "setuid", "setgid")),
            ("namespace", ("namespace", "unshare")),
            ("destination", ("no such file or directory", "can't mkdir", "can't create")),
            ("permission", ("permission denied", "operation not permitted")),
        )
        for reason, needles in bwrap_signatures:
            if any(needle in text for needle in needles):
                return f"bubblewrap-{reason}"
        return "bubblewrap-other"
    signatures = (
        ("cli-arguments", ("unrecognized arguments", "usage: hermes")),
        ("filesystem-permission", ("permission denied", "read-only file system")),
        ("authentication", ("not authenticated", "credential", "log in", "login")),
        ("model-routing", ("model not found", "unknown model", "provider")),
        ("skill-loading", ("skill not found", "failed to load skill")),
        ("runtime-exception", ("traceback (most recent call last)",)),
    )
    for category, needles in signatures:
        if any(needle in text for needle in needles):
            return category
    return "unclassified"


def classify_agent_response(stdout: bytes) -> dict[str, bool]:
    text = stdout.decode("utf-8", errors="replace").casefold()
    blocker_terms = ("unable", "cannot", "can't", "blocked", "not available")
    completion_terms = ("complete", "completed", "saved", "ingested")
    unavailable_terms = ("not available", "unavailable", "do not have access")
    return {
        "blockedClaim": any(term in text for term in blocker_terms),
        "completionClaim": any(term in text for term in completion_terms),
        "mentionsWriteFile": "write_file" in text,
        "toolUnavailableClaim": any(term in text for term in unavailable_terms),
    }


def synthetic_response_preview(stdout: bytes) -> str:
    text = stdout.decode("utf-8", errors="replace").strip()
    require(len(text.encode("utf-8")) <= 512, "agent-response-preview-too-large")
    return text


def classify_tool_result(content: Any) -> tuple[bool, dict[str, int] | None]:
    if isinstance(content, bytes):
        text = content.decode("utf-8", errors="replace")
    else:
        text = str(content or "")
    lowered = text.casefold().strip()
    is_error = (
        lowered.startswith("error")
        or "tool_error" in lowered
        or '"iserror":true' in lowered.replace(" ", "")
    )
    summary = None
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict):
        is_error = is_error or bool(payload.get("error"))
        candidate = payload.get("summary")
        if isinstance(candidate, dict):
            statuses = ("pending", "in_progress", "completed", "cancelled")
            if all(isinstance(candidate.get(status), int) for status in statuses):
                summary = {status: int(candidate[status]) for status in statuses}
    return is_error, summary


def classify_tool_error_category(content: Any) -> str | None:
    try:
        payload = json.loads(str(content or ""))
    except (TypeError, json.JSONDecodeError):
        return "other" if classify_tool_result(content)[0] else None
    if not isinstance(payload, dict) or not payload.get("error"):
        return None
    message = str(payload.get("error") or "").casefold()
    categories = (
        ("not-found", ("not found", "does not exist", "no such file")),
        ("pagination", ("offset", "limit", "line number")),
        ("access-denied", ("access denied", "cannot be read directly")),
        ("permission", ("permission denied", "read-only file system")),
        ("directory", ("is a directory", "expected a file")),
    )
    for category, needles in categories:
        if any(needle in message for needle in needles):
            return category
    return "other"


def classify_synthetic_read_path(value: Any) -> str:
    path = str(value or "").strip()
    expected = {
        "courses/inbox/synthetic-syllabus.md": "syllabus-input",
        "courses/semester-context.md": "semester-context",
    }
    if path in expected:
        return expected[path]
    if not path:
        return "missing"
    candidate = Path(path)
    if candidate.is_absolute():
        return "absolute"
    if ".." in candidate.parts:
        return "traversal"
    return "unexpected-relative"


def classify_synthetic_event(title: Any) -> str | None:
    normalized = str(title or "").casefold()
    if "midterm" in normalized:
        return "midterm"
    if "project" in normalized:
        return "project"
    if "final" in normalized:
        return "final"
    return None


def load_schedule_validator(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("hermes_rigel_schedule", path)
    require(spec is not None and spec.loader is not None, "schedule-import-spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def secure_copy(source: Path, target: Path, uid: int, gid: int, mode: int) -> None:
    require(source.is_file() and not source.is_symlink(), f"source-invalid:{source.name}")
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    os.chown(target, uid, gid)
    os.chmod(target, mode)


def secure_copy_tree(source: Path, target: Path, uid: int, gid: int) -> None:
    require(source.is_dir() and not source.is_symlink(), "skill-source-invalid")
    shutil.copytree(source, target, symlinks=False)
    for path in [target, *target.rglob("*")]:
        require(not path.is_symlink(), "skill-tree-symlink")
        os.chown(path, uid, gid)
        os.chmod(path, 0o700 if path.is_dir() else 0o400)


def build_sandbox_layout(root: Path, uid: int, gid: int) -> Path:
    account = root / "account"
    profile = account / ".hermes/profiles/rigel"
    imported = profile / "imported-data"
    courses = imported / "courses"
    memory = imported / "memory"
    for directory in (account, profile, imported, courses, memory):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chown(directory, uid, gid)
        os.chmod(directory, 0o700)
    return account


def build_sandbox(root: Path, uid: int, gid: int, args: argparse.Namespace) -> Path:
    account = build_sandbox_layout(root, uid, gid)
    profile = account / ".hermes/profiles/rigel"
    courses = profile / "imported-data/courses"

    secure_copy(args.profile_home / "auth.json", profile / "auth.json", uid, gid, 0o600)
    for name in ("AGENTS.md", "SOUL.md", "USER.md", "HEARTBEAT.md"):
        secure_copy(args.profile_home / name, profile / name, uid, gid, 0o400)
    config = profile / "config.yaml"
    config.write_text(SYNTHETIC_CONFIG, encoding="utf-8")
    os.chown(config, uid, gid)
    os.chmod(config, 0o400)
    secure_copy_tree(
        args.skills_root / "academic",
        profile / "skills/academic",
        uid,
        gid,
    )

    (courses / "inbox").mkdir(mode=0o700)
    os.chown(courses / "inbox", uid, gid)
    syllabus = courses / "inbox/synthetic-syllabus.md"
    syllabus.write_text(SYNTHETIC_SYLLABUS, encoding="utf-8")
    os.chown(syllabus, uid, gid)
    os.chmod(syllabus, 0o600)
    semester = courses / "semester-context.md"
    semester.write_text(
        "# Semester Context\n\n## Active Courses\n\nNone yet.\n",
        encoding="utf-8",
    )
    os.chown(semester, uid, gid)
    os.chmod(semester, 0o600)
    return account


def prompt() -> str:
    return f"""Run the managed academic skill's syllabus-ingestion workflow in this isolated acceptance workspace.

The synthetic syllabus is at courses/inbox/synthetic-syllabus.md. The exact course ID is {COURSE_ID}. Treat the current working directory as the entire academic workspace. Do not inspect parent paths, use network tools, write provider memory, or contact Astra. For this isolated test, valid canonical courses/academic-state.json state is the complete calendar-handoff artifact; external delivery is outside scope.

The complete academic skill is already preloaded and its canonical scheduler
schema is inline. Do not call skill_view, search for another protocol/template,
or inspect unrelated paths. Read only the supplied syllabus and current
semester context, then perform the required writes. Submit independent native
tool calls together when possible so source inspection does not consume the
bounded completion budget.

Before any file write, create a native TodoStore checklist covering all four
canonical outputs plus final read-back validation. Keep exactly one item
in_progress while working, and update each item only after its deliverable is
written and verified.

Complete these writes before responding, in this order:
1. courses/{COURSE_ID}/syllabus-raw.md
2. courses/{COURSE_ID}/syllabus-context.md
3. courses/semester-context.md, containing {COURSE_ID}
4. courses/academic-state.json, conforming exactly to the academic skill's canonical scheduler schema and containing every qualifying exam or major deadline

Do not include weekly homework as a calendar event. Do not discuss external
calendar delivery or liaison status in the response; this test ends when the
canonical handoff artifact is valid. A confirmation with any
pending or in-progress todo, or without all four valid files, is an incomplete
run.

Finish with exactly: "Syllabus ingestion complete." Do not print file contents."""


def sandbox_prefix(account: Path, args: argparse.Namespace) -> list[str]:
    canonical_workdir = CANONICAL_PROFILE / "imported-data"
    return [
        str(args.systemd_run),
        "--quiet",
        "--wait",
        "--pipe",
        "--collect",
        f"--unit=hermes-rigel-workflow-{os.getpid()}",
        "--property=Type=exec",
        f"--property=User={args.user}",
        f"--property=Group={args.user}",
        "--property=NoNewPrivileges=yes",
        "--property=ProtectSystem=strict",
        "--property=ProtectHome=yes",
        "--property=PrivateTmp=yes",
        "--property=PrivateDevices=yes",
        "--property=RestrictSUIDSGID=yes",
        "--property=CapabilityBoundingSet=",
        f"--property=WorkingDirectory={canonical_workdir}",
        f"--property=BindPaths={account}:{CANONICAL_ACCOUNT}",
        f"--property=ReadWritePaths={CANONICAL_ACCOUNT}",
        "--setenv",
        f"HOME={CANONICAL_ACCOUNT}",
        "--setenv",
        f"HERMES_HOME={CANONICAL_PROFILE}",
        "--setenv",
        f"TERMINAL_CWD={canonical_workdir}",
        "--setenv",
        "HERMES_MANAGED_DIR=/nonexistent-hermes-managed",
        "--setenv",
        "NO_COLOR=1",
    ]


def run_sandbox_probe(account: Path, args: argparse.Namespace) -> dict[str, Any]:
    relative = Path(".hermes/profiles/rigel/imported-data/.sandbox-write-probe")
    source_probe = account / relative
    canonical_probe = CANONICAL_ACCOUNT / relative
    try:
        command = [*sandbox_prefix(account, args), "/usr/bin/touch", str(canonical_probe)]
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=min(args.timeout, 30),
            check=False,
        )
        if result.returncode != 0:
            raise SmokeError(
                "sandbox-probe-failed:"
                f"category={classify_agent_failure(result.stderr)}:"
                f"rc={result.returncode}:stdout={sha256_bytes(result.stdout)}:"
                f"stderr={sha256_bytes(result.stderr)}"
            )
        require(source_probe.is_file() and not source_probe.is_symlink(), "sandbox-write-missing")
    finally:
        source_probe.unlink(missing_ok=True)
    return {
        "status": "ready",
        "modelInvoked": False,
        "sandboxSetup": "systemd-private-account",
        "mappedWriteVerified": True,
    }


def run_tool_inventory_probe(account: Path, args: argparse.Namespace) -> dict[str, Any]:
    command = [
        *sandbox_prefix(account, args),
        "--setenv",
        f"PYTHONPATH={args.runtime_root}",
        str(args.hermes_python),
        "-c",
        TOOL_INVENTORY_PROBE,
    ]
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=min(args.timeout, 120),
        check=False,
    )
    if result.returncode != 0:
        raise SmokeError(
            "tool-inventory-probe-failed:"
            f"category={classify_agent_failure(result.stderr)}:"
            f"rc={result.returncode}:stdout={sha256_bytes(result.stdout)}:"
            f"stderr={sha256_bytes(result.stderr)}"
        )
    try:
        payload = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SmokeError("tool-inventory-invalid") from exc
    require(isinstance(payload, dict), "tool-inventory-not-object")
    names = payload.get("toolNames")
    require(isinstance(names, list), "tool-inventory-not-list")
    exposed = {str(name) for name in names}
    missing = sorted(REQUIRED_FILE_TOOLS - exposed)
    require(not missing, "model-file-tools-missing:" + ",".join(missing))
    require(payload.get("todoStopGuard") is True, "todo-stop-guard-disabled")
    require(payload.get("maxTodoStopNudges") == 8, "todo-stop-budget-drift")
    return {
        "status": "ready",
        "maxTodoStopNudges": 8,
        "modelInvoked": False,
        "requiredFileTools": sorted(REQUIRED_FILE_TOOLS),
        "requiredFileToolsPresent": True,
        "resolvedToolCount": len(exposed),
        "todoStopGuard": True,
    }


def run_file_read_probe(account: Path, args: argparse.Namespace) -> dict[str, Any]:
    command = [
        *sandbox_prefix(account, args),
        "--setenv",
        f"PYTHONPATH={args.runtime_root}",
        str(args.hermes_python),
        "-c",
        FILE_READ_PROBE,
    ]
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=min(args.timeout, 120),
        check=False,
    )
    if result.returncode != 0:
        raise SmokeError(
            "file-read-probe-failed:"
            f"category={classify_agent_failure(result.stderr)}:"
            f"rc={result.returncode}:stdout={sha256_bytes(result.stdout)}:"
            f"stderr={sha256_bytes(result.stderr)}"
        )
    try:
        payload = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SmokeError("file-read-probe-invalid") from exc
    require(isinstance(payload, dict) and len(payload) == 2, "file-read-probe-shape")
    require(
        all(
            isinstance(item, dict)
            and item.get("resolvedMatchesExpected") is True
            and item.get("error") is False
            and item.get("hasContent") is True
            for item in payload.values()
        ),
        "file-read-probe-not-ready",
    )
    return {
        "status": "ready",
        "files": len(payload),
        "modelInvoked": False,
        "readsSucceeded": True,
        "resolvedMatchesExpected": True,
    }


def run_agent(account: Path, uid: int, gid: int, args: argparse.Namespace) -> dict[str, Any]:
    canonical_workdir = CANONICAL_PROFILE / "imported-data"
    usage_path = CANONICAL_ACCOUNT / "usage.json"
    command = [
        *sandbox_prefix(account, args),
        str(args.hermes),
        "--in",
        str(canonical_workdir),
        "--skills",
        "academic",
        "--toolsets",
        "file,skills,todo",
        "--provider",
        "openai-codex",
        "--model",
        TEST_MODEL,
        "--usage-file",
        str(usage_path),
        "--oneshot",
        prompt(),
    ]
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=args.timeout,
        check=False,
    )
    if result.returncode != 0:
        raise SmokeError(
            "agent-failed:"
            f"category={classify_agent_failure(result.stderr)}:"
            f"rc={result.returncode}:stdout={sha256_bytes(result.stdout)}:"
            f"stderr={sha256_bytes(result.stderr)}"
        )
    require(bool(result.stdout.strip()), "agent-empty-response")
    usage_file = account / "usage.json"
    require(usage_file.is_file() and not usage_file.is_symlink(), "usage-missing")
    try:
        usage = json.loads(usage_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SmokeError("usage-invalid") from exc
    require(isinstance(usage, dict), "usage-not-object")
    provider = str(usage.get("provider") or usage.get("runtime", {}).get("provider") or "")
    model = str(usage.get("model") or usage.get("runtime", {}).get("model") or "")
    require(provider == "openai-codex", "provider-drift")
    require(model == TEST_MODEL, "model-drift")
    response_classification = classify_agent_response(result.stdout)
    return {
        "provider": provider,
        "model": model,
        "apiCalls": int(usage.get("api_calls") or usage.get("apiCalls") or 0),
        "responseBytes": len(result.stdout),
        "responseClassification": response_classification,
        "syntheticResponse": synthetic_response_preview(result.stdout),
        "responseSha256": sha256_bytes(result.stdout),
        "stderrBytes": len(result.stderr),
        "stderrSha256": sha256_bytes(result.stderr),
    }


def summarize_session_state(account: Path) -> dict[str, Any]:
    state = account / ".hermes/profiles/rigel/state.db"
    if not state.is_file() or state.is_symlink():
        return {"state": "missing"}
    try:
        database = sqlite3.connect(f"file:{state}?mode=ro", uri=True)
        row = database.execute(
            """
            SELECT id, model, billing_provider, billing_mode, message_count,
                   tool_call_count, api_call_count
            FROM sessions
            ORDER BY started_at DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            database.close()
            return {"state": "empty"}
        session_id = row[0]
        roles = {
            str(role): int(count)
            for role, count in database.execute(
                """
                SELECT role, COUNT(*)
                FROM messages
                WHERE session_id = ?
                GROUP BY role
                ORDER BY role
                """,
                (session_id,),
            )
        }
        tool_names = sorted(
            {
                str(name)[:80]
                for (name,) in database.execute(
                    """
                    SELECT tool_name
                    FROM messages
                    WHERE session_id = ? AND tool_name IS NOT NULL
                    """,
                    (session_id,),
                )
                if str(name).strip()
            }
        )[:16]
        tool_outcomes: dict[str, dict[str, int]] = {}
        read_call_shapes = []
        for (raw_calls,) in database.execute(
            """
            SELECT tool_calls
            FROM messages
            WHERE session_id = ? AND tool_calls IS NOT NULL
            ORDER BY rowid
            """,
            (session_id,),
        ):
            try:
                calls = json.loads(str(raw_calls))
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(calls, list):
                continue
            for call in calls:
                if not isinstance(call, dict):
                    continue
                function = call.get("function")
                if not isinstance(function, dict) or function.get("name") != "read_file":
                    continue
                raw_arguments = function.get("arguments")
                try:
                    arguments = (
                        json.loads(raw_arguments)
                        if isinstance(raw_arguments, str)
                        else raw_arguments
                    )
                except (TypeError, json.JSONDecodeError):
                    arguments = None
                if not isinstance(arguments, dict):
                    read_call_shapes.append({"arguments": "invalid"})
                    continue
                read_call_shapes.append(
                    {
                        "pathClass": classify_synthetic_read_path(arguments.get("path")),
                        "offsetType": type(arguments.get("offset")).__name__,
                        "offset": arguments.get("offset") if isinstance(arguments.get("offset"), int) else None,
                        "limitType": type(arguments.get("limit")).__name__,
                        "limit": arguments.get("limit") if isinstance(arguments.get("limit"), int) else None,
                    }
                )
        last_todo_summary = None
        for name, content in database.execute(
            """
            SELECT tool_name, content
            FROM messages
            WHERE session_id = ? AND role = 'tool' AND tool_name IS NOT NULL
            ORDER BY rowid
            """,
            (session_id,),
        ):
            normalized = str(name)[:80]
            outcome = tool_outcomes.setdefault(normalized, {"errors": 0, "results": 0})
            outcome["results"] += 1
            is_error, todo_summary = classify_tool_result(content)
            if is_error:
                outcome["errors"] += 1
                category = classify_tool_error_category(content)
                if category:
                    categories = outcome.setdefault("errorCategories", {})
                    categories[category] = categories.get(category, 0) + 1
            if normalized == "todo" and todo_summary is not None:
                last_todo_summary = todo_summary
        database.close()
    except sqlite3.Error:
        return {"state": "unreadable"}
    return {
        "state": "ready",
        "model": str(row[1] or ""),
        "billingProvider": str(row[2] or ""),
        "billingMode": str(row[3] or ""),
        "messageCount": int(row[4] or 0),
        "toolCallCount": int(row[5] or 0),
        "apiCallCount": int(row[6] or 0),
        "roles": roles,
        "lastTodoSummary": last_todo_summary,
        "toolNames": tool_names,
        "readCallShapes": read_call_shapes,
        "toolOutcomes": {name: tool_outcomes[name] for name in sorted(tool_outcomes)},
    }


def validate_outputs(account: Path, schedule_path: Path) -> dict[str, Any]:
    courses = account / ".hermes/profiles/rigel/imported-data/courses"
    course = courses / COURSE_ID
    required = (
        course / "syllabus-raw.md",
        course / "syllabus-context.md",
        courses / "semester-context.md",
        courses / "academic-state.json",
    )
    missing = [
        path.name for path in required if not path.is_file() or path.is_symlink()
    ]
    if missing:
        created = sorted(
            str(path.relative_to(courses))
            for path in courses.rglob("*")
            if path.is_file() and not path.is_symlink()
        )
        raise SmokeError(
            "outputs-missing=" + ",".join(missing) + ";created=" + ",".join(created[:16])
        )
    for path in required:
        require(path.stat().st_size > 0, f"output-empty:{path.name}")

    semester = (courses / "semester-context.md").read_text(encoding="utf-8")
    require(COURSE_ID in semester.casefold(), "semester-course-missing")
    try:
        state = json.loads((courses / "academic-state.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SmokeError("academic-state-invalid") from exc
    module = load_schedule_validator(schedule_path)
    try:
        events, pending = module.validate_source(state)
    except module.ScheduleError as exc:
        code = str(exc)[:80] or "unknown"
        raise SmokeError(f"scheduler-invalid:{code}") from exc
    selected = [event for event in events if event["course"].casefold() == COURSE_ID]
    categorized = {
        category: event
        for event in selected
        if (category := classify_synthetic_event(event["title"])) is not None
    }
    missing_categories = sorted(set(EXPECTED_EVENTS) - set(categorized))
    require(
        not missing_categories,
        "qualifying-events-missing=" + ",".join(missing_categories)
        + f";selected={len(selected)};categorized={len(categorized)}",
    )
    for category, expected_date in EXPECTED_EVENTS.items():
        require(
            str(categorized[category]["startsAt"]).startswith(expected_date),
            f"qualifying-event-date-drift:{category}",
        )
    require(
        not any("homework" in event["title"].casefold() for event in selected),
        "minor-event-included",
    )
    require(all(event["source"]["kind"] == "syllabus" for event in selected), "source-drift")
    return {
        "courseId": COURSE_ID,
        "requiredFiles": len(required),
        "events": len(selected),
        "pendingCalendarRequests": pending,
        "schedulerSchemaValid": True,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    require(os.geteuid() == 0, "root-required")
    account = pwd.getpwnam(args.user)
    required_paths = [(args.systemd_run, "systemd-run")]
    if args.tool_probe_only or args.file_probe_only:
        require_managed_interpreter(args.hermes_python)
        required_paths.extend(
            [
                (args.runtime_root / "model_tools.py", "model-tools"),
            ]
        )
    elif not args.probe_only:
        required_paths.extend(
            [
                (args.hermes, "hermes"),
                (args.schedule, "schedule"),
                (args.profile_home / "auth.json", "auth"),
                (args.skills_root / "academic/SKILL.md", "academic-skill"),
            ]
        )
    for path, label in required_paths:
        require(path.is_file() and not path.is_symlink(), f"{label}-invalid")

    stage_root = Path(args.stage_root)
    require(stage_root.is_absolute() and stage_root.is_dir(), "stage-root-invalid")
    temporary = Path(tempfile.mkdtemp(prefix="rigel-workflow-", dir=stage_root))
    os.chown(temporary, account.pw_uid, account.pw_gid)
    os.chmod(temporary, 0o700)
    try:
        if args.tool_probe_only:
            sandbox_account = build_sandbox_layout(
                temporary,
                account.pw_uid,
                account.pw_gid,
            )
            profile = sandbox_account / ".hermes/profiles/rigel"
            config = profile / "config.yaml"
            config.write_text(SYNTHETIC_CONFIG, encoding="utf-8")
            os.chown(config, account.pw_uid, account.pw_gid)
            os.chmod(config, 0o400)
            return {
                "status": "ready",
                "isolation": "systemd-private-account",
                "liveCourseDataMounted": False,
                "probe": run_tool_inventory_probe(sandbox_account, args),
                "residualFiles": 0,
            }
        if args.file_probe_only:
            sandbox_account = build_sandbox_layout(
                temporary,
                account.pw_uid,
                account.pw_gid,
            )
            courses = sandbox_account / ".hermes/profiles/rigel/imported-data/courses"
            inbox = courses / "inbox"
            inbox.mkdir(mode=0o700)
            os.chown(inbox, account.pw_uid, account.pw_gid)
            for path in (
                inbox / "synthetic-syllabus.md",
                courses / "semester-context.md",
            ):
                path.write_text("synthetic\n", encoding="utf-8")
                os.chown(path, account.pw_uid, account.pw_gid)
                os.chmod(path, 0o600)
            return {
                "status": "ready",
                "isolation": "systemd-private-account",
                "liveCourseDataMounted": False,
                "probe": run_file_read_probe(sandbox_account, args),
                "residualFiles": 0,
            }
        if args.probe_only:
            sandbox_account = build_sandbox_layout(
                temporary,
                account.pw_uid,
                account.pw_gid,
            )
            return {
                "status": "ready",
                "isolation": "systemd-private-account",
                "liveCourseDataMounted": False,
                "probe": run_sandbox_probe(sandbox_account, args),
                "residualFiles": 0,
            }
        sandbox_account = build_sandbox(
            temporary,
            account.pw_uid,
            account.pw_gid,
            args,
        )
        agent = run_agent(sandbox_account, account.pw_uid, account.pw_gid, args)
        session = summarize_session_state(sandbox_account)
        workflow = None
        try:
            workflow = validate_outputs(sandbox_account, args.schedule)
            require(
                not agent["responseClassification"]["blockedClaim"],
                "agent-claimed-blocker",
            )
            require(
                agent["responseClassification"]["completionClaim"],
                "agent-did-not-confirm-completion",
            )
        except SmokeError as exc:
            evidence = {
                "agent": agent,
                "session": session,
                "workflow": workflow,
            }
            raise SmokeError(
                f"{exc}:evidence="
                + json.dumps(evidence, sort_keys=True, separators=(",", ":"))
            ) from exc
        return {
            "status": "ready",
            "isolation": "systemd-private-account",
            "liveCourseDataMounted": False,
            "agent": agent,
            "session": session,
            "workflow": workflow,
            "residualFiles": 0,
        }
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default="hermes-rigel")
    parser.add_argument("--profile-home", type=Path, default=CANONICAL_PROFILE)
    parser.add_argument(
        "--skills-root",
        type=Path,
        default=CANONICAL_PROFILE / "skills",
    )
    parser.add_argument(
        "--schedule",
        type=Path,
        default=CANONICAL_PROFILE / "scripts/hermes-rigel-schedule.py",
    )
    parser.add_argument("--hermes", type=Path, default=Path("/usr/local/bin/hermes"))
    parser.add_argument(
        "--hermes-python",
        type=Path,
        default=Path("/usr/local/lib/hermes-agent/venv/bin/python"),
    )
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path("/usr/local/lib/hermes-agent"),
    )
    parser.add_argument(
        "--systemd-run", type=Path, default=Path("/usr/bin/systemd-run")
    )
    parser.add_argument("--stage-root", type=Path, default=Path("/var/lib/hermes/bootstrap"))
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--probe-only",
        action="store_true",
        help="Validate the exact transient sandbox and mapped write without invoking Hermes or a model.",
    )
    parser.add_argument(
        "--tool-probe-only",
        action="store_true",
        help="Resolve the exact synthetic model tool schemas without invoking Hermes or a model.",
    )
    parser.add_argument(
        "--file-probe-only",
        action="store_true",
        help="Resolve and read the two synthetic course inputs without invoking a model.",
    )
    return parser.parse_args()


def main() -> int:
    try:
        print(json.dumps(run(parse_args()), sort_keys=True))
    except (OSError, SmokeError, subprocess.SubprocessError) as exc:
        print(f"hermes-rigel-workflow-smoke-error:{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
