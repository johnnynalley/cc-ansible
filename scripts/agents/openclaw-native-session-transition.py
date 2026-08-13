#!/usr/bin/env python3
"""Apply a fail-closed session transition through OpenClaw's native Gateway RPC."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

PLANNER_PATH = Path(__file__).with_name("openclaw-session-transition.py")
PLANNER_SPEC = importlib.util.spec_from_file_location(
    "openclaw_session_transition", PLANNER_PATH
)
if PLANNER_SPEC is None or PLANNER_SPEC.loader is None:
    raise RuntimeError("session transition planner cannot be loaded")
PLANNER = importlib.util.module_from_spec(PLANNER_SPEC)
sys.modules[PLANNER_SPEC.name] = PLANNER
PLANNER_SPEC.loader.exec_module(PLANNER)

RpcRunner = Callable[[str, dict[str, Any]], dict[str, Any]]


class NativeSessionTransitionError(RuntimeError):
    """Raised when the native transition cannot be completed safely."""


def _directory(path: Path, label: str, *, create: bool = False) -> Path:
    if create:
        try:
            path.mkdir(parents=True, mode=0o700, exist_ok=False)
        except OSError as exc:
            raise NativeSessionTransitionError(f"{label} is unavailable") from exc
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise NativeSessionTransitionError(f"{label} is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        raise NativeSessionTransitionError(f"{label} must be a non-symlink directory")
    return path.resolve()


def _regular_file(path: Path, label: str, *, executable: bool = False) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise NativeSessionTransitionError(f"{label} is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise NativeSessionTransitionError(f"{label} must be a non-symlink file")
    if executable and not os.access(path, os.X_OK):
        raise NativeSessionTransitionError(f"{label} is not executable")
    return path.resolve()


def _write_private_json(path: Path, payload: Any) -> None:
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise NativeSessionTransitionError("private evidence write failed") from exc


def _build_rpc_runner(
    openclaw_cli: Path,
    runtime_root: Path,
    home: Path,
    state_root: Path,
    config: Path,
    workspace: Path,
    timeout_seconds: int,
) -> RpcRunner:
    cli = _regular_file(openclaw_cli, "OpenClaw CLI", executable=True)
    runtime = _directory(runtime_root, "OpenClaw runtime root")
    if not cli.is_relative_to(runtime):
        raise NativeSessionTransitionError("OpenClaw CLI is outside the runtime root")
    resolved_home = _directory(home, "OpenClaw home")
    resolved_state = _directory(state_root, "OpenClaw state root")
    resolved_config = _regular_file(config, "OpenClaw config")
    resolved_workspace = _directory(workspace, "OpenClaw workspace")
    if timeout_seconds < 1 or timeout_seconds > 300:
        raise NativeSessionTransitionError("RPC timeout is outside the safe range")

    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(resolved_home),
            "OPENCLAW_HOME": str(resolved_home),
            "OPENCLAW_STATE_DIR": str(resolved_state),
            "OPENCLAW_CONFIG_PATH": str(resolved_config),
            "OPENCLAW_WORKSPACE_DIR": str(resolved_workspace),
            "OPENCLAW_SKIP_CHANNELS": "1",
            "OPENCLAW_SKIP_CRON": "1",
            "MEM0_TELEMETRY": "false",
            "NO_COLOR": "1",
        }
    )

    def run(method: str, params: dict[str, Any]) -> dict[str, Any]:
        completed = subprocess.run(
            [
                str(cli),
                "gateway",
                "call",
                method,
                "--params",
                json.dumps(params, separators=(",", ":")),
                "--timeout",
                str(timeout_seconds * 1000),
                "--json",
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 5,
            check=False,
        )
        if completed.returncode != 0 or completed.stderr.strip():
            raise NativeSessionTransitionError("OpenClaw Gateway RPC failed")
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise NativeSessionTransitionError(
                "OpenClaw Gateway RPC returned invalid JSON"
            ) from exc
        if not isinstance(response, dict):
            raise NativeSessionTransitionError(
                "OpenClaw Gateway RPC returned an unsupported shape"
            )
        return response

    return run


def _list_active_sessions(rpc: RpcRunner) -> dict[str, Any]:
    return rpc(
        "sessions.list",
        {
            "limit": 1000,
            "offset": 0,
            "configuredAgentsOnly": True,
            "archived": False,
            "includeDerivedTitles": False,
            "includeLastMessage": False,
        },
    )


def _list_archived_sessions(rpc: RpcRunner) -> dict[str, Any]:
    return rpc(
        "sessions.list",
        {
            "limit": 1000,
            "offset": 0,
            "configuredAgentsOnly": True,
            "archived": True,
            "includeDerivedTitles": False,
            "includeLastMessage": False,
        },
    )


def _index_session_rows(
    payload: dict[str, Any], label: str
) -> dict[str, dict[str, Any]]:
    sessions = payload.get("sessions")
    if not isinstance(sessions, list):
        raise NativeSessionTransitionError(f"{label} has no sessions array")
    if payload.get("hasMore") is not False:
        raise NativeSessionTransitionError(f"{label} is incomplete")
    if payload.get("totalCount") != len(sessions):
        raise NativeSessionTransitionError(f"{label} count does not match")
    indexed: dict[str, dict[str, Any]] = {}
    for row in sessions:
        if not isinstance(row, dict) or not isinstance(row.get("key"), str):
            raise NativeSessionTransitionError(f"{label} contains an invalid row")
        if row["key"] in indexed:
            raise NativeSessionTransitionError(f"{label} contains duplicate keys")
        indexed[row["key"]] = row
    return indexed


def _native_heartbeat_agent(key: str, agents: set[str]) -> str:
    parts = key.split(":")
    if (
        len(parts) != 4
        or parts[0] != "agent"
        or parts[1] not in agents
        or parts[2:] != ["main", "heartbeat"]
    ):
        raise NativeSessionTransitionError(
            "native heartbeat restore key has an unsupported shape"
        )
    return parts[1]


def _plan_input_with_restored_rows(
    active: dict[str, Any],
    archived_rows: dict[str, dict[str, Any]],
    restore_keys: set[str],
) -> dict[str, Any]:
    sessions = list(active["sessions"])
    for key in sorted(restore_keys):
        restored = dict(archived_rows[key])
        restored.pop("archived", None)
        restored.pop("archivedAt", None)
        sessions.append(restored)
    return {"sessions": sessions, "totalCount": len(sessions), "hasMore": False}


def run_transition(
    mode: str,
    output_dir: Path,
    agents: list[str],
    rpc: RpcRunner,
    required_archive_keys: set[str] | None = None,
    restore_native_heartbeat_keys: set[str] | None = None,
) -> dict[str, Any]:
    if mode not in {"plan", "apply", "restore"}:
        raise NativeSessionTransitionError("unsupported transition mode")
    evidence = _directory(output_dir, "transition evidence", create=True)

    agent_set = set(agents)
    restore_keys = restore_native_heartbeat_keys or set()
    if mode == "restore" and not restore_keys:
        raise NativeSessionTransitionError(
            "restore mode requires a native heartbeat session key"
        )
    restore_agents = {
        key: _native_heartbeat_agent(key, agent_set) for key in restore_keys
    }

    before = _list_active_sessions(rpc)
    _write_private_json(evidence / "sessions-before.json", before)
    active_rows = _index_session_rows(before, "active session response")
    archived_rows: dict[str, dict[str, Any]] = {}
    restore_planned: set[str] = set()
    if restore_keys:
        archived_before = _list_archived_sessions(rpc)
        _write_private_json(evidence / "sessions-archived-before.json", archived_before)
        archived_rows = _index_session_rows(
            archived_before, "archived session response"
        )
        if set(active_rows).intersection(archived_rows):
            raise NativeSessionTransitionError(
                "active and archived session responses overlap"
            )
        restore_planned = restore_keys.intersection(archived_rows)

    plan_input = _plan_input_with_restored_rows(before, archived_rows, restore_planned)
    try:
        plan = PLANNER.build_transition_plan(plan_input, agents)
    except PLANNER.SessionTransitionError as exc:
        raise NativeSessionTransitionError(
            "session transition classification failed"
        ) from exc
    _write_private_json(evidence / "transition-plan.json", plan)
    planned_archive_keys = {
        action["key"] for action in plan["actions"] if action["action"] == "archive"
    }
    if (
        required_archive_keys is not None
        and planned_archive_keys != required_archive_keys
    ):
        raise NativeSessionTransitionError(
            "native archive plan does not match the required synthetic sessions"
        )

    restored = 0
    archived = 0
    if mode in {"apply", "restore"}:
        for key in sorted(restore_planned):
            response = rpc(
                "sessions.patch",
                {
                    "key": key,
                    "agentId": restore_agents[key],
                    "archived": False,
                },
            )
            if response.get("ok") is not True:
                raise NativeSessionTransitionError(
                    "OpenClaw rejected a native heartbeat session restore"
                )
            restored += 1

        if mode == "apply":
            for action in plan["actions"]:
                if action["action"] != "archive":
                    continue
                response = rpc(
                    "sessions.patch",
                    {
                        "key": action["key"],
                        "agentId": action["agentId"],
                        "archived": True,
                    },
                )
                if response.get("ok") is not True:
                    raise NativeSessionTransitionError(
                        "OpenClaw rejected a native session archive"
                    )
                archived += 1

        after = _list_active_sessions(rpc)
        _write_private_json(evidence / "sessions-after.json", after)
        after_rows = _index_session_rows(after, "post-transition active response")
        if not restore_planned.issubset(after_rows):
            raise NativeSessionTransitionError(
                "native heartbeat session restore did not converge"
            )
        if mode == "apply":
            try:
                clean = PLANNER.build_transition_plan(
                    after,
                    agents,
                    require_clean=True,
                )
            except PLANNER.SessionTransitionError as exc:
                raise NativeSessionTransitionError(
                    "native session transition did not converge"
                ) from exc
            _write_private_json(evidence / "transition-clean.json", clean)
            if archived != plan["summary"]["archive"]:
                raise NativeSessionTransitionError(
                    "native archive count changed during apply"
                )

    return {
        "status": "ok",
        "mode": mode,
        "summary": {
            "retain": plan["summary"]["retain"],
            "restorePlanned": len(restore_planned),
            "restored": restored,
            "archivePlanned": plan["summary"]["archive"],
            "archived": archived,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("plan", "apply", "restore"), required=True)
    parser.add_argument("--openclaw", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--agent", action="append", dest="agents", required=True)
    parser.add_argument(
        "--required-archive-key",
        action="append",
        dest="required_archive_keys",
    )
    parser.add_argument(
        "--restore-native-heartbeat-key",
        action="append",
        dest="restore_native_heartbeat_keys",
    )
    parser.add_argument("--timeout-seconds", type=int, default=20)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        rpc = _build_rpc_runner(
            arguments.openclaw,
            arguments.runtime_root,
            arguments.home,
            arguments.state_root,
            arguments.config,
            arguments.workspace,
            arguments.timeout_seconds,
        )
        report = run_transition(
            arguments.mode,
            arguments.output_dir,
            arguments.agents,
            rpc,
            (
                set(arguments.required_archive_keys)
                if arguments.required_archive_keys is not None
                else None
            ),
            (
                set(arguments.restore_native_heartbeat_keys)
                if arguments.restore_native_heartbeat_keys is not None
                else None
            ),
        )
    except NativeSessionTransitionError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
