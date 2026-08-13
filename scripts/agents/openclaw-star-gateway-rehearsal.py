#!/usr/bin/env python3
"""Run one channel-less Star turn through the persistent Gateway lifecycle."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

MAX_PROMPT_BYTES = 32 * 1024
MAX_RPC_BYTES = 8 * 1024 * 1024
MAX_HISTORY_MESSAGES = 200

RpcRunner = Callable[[str, dict[str, Any], bool], dict[str, Any]]


class StarGatewayRehearsalError(RuntimeError):
    """Raised when Star does not reach one complete Gateway-owned reply."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StarGatewayRehearsalError(message)


def _regular_file(path: Path, label: str, *, executable: bool = False) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise StarGatewayRehearsalError(f"{label}-unavailable") from exc
    _require(
        stat.S_ISREG(metadata.st_mode) and not path.is_symlink(),
        f"{label}-not-regular",
    )
    if executable:
        _require(os.access(path, os.X_OK), f"{label}-not-executable")
    return path.resolve()


def _directory(path: Path, label: str) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise StarGatewayRehearsalError(f"{label}-unavailable") from exc
    _require(
        stat.S_ISDIR(metadata.st_mode) and not path.is_symlink(),
        f"{label}-not-directory",
    )
    return path.resolve()


def _read_prompt(path: Path) -> str:
    prompt_path = _regular_file(path, "prompt")
    try:
        raw = prompt_path.read_bytes()
    except OSError as exc:
        raise StarGatewayRehearsalError("prompt-read-failed") from exc
    _require(0 < len(raw) <= MAX_PROMPT_BYTES, "prompt-size-invalid")
    try:
        prompt = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StarGatewayRehearsalError("prompt-not-utf8") from exc
    _require(bool(prompt.strip()), "prompt-empty")
    return prompt


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    parent = _directory(path.parent, "output-parent")
    _require(not path.exists(), "output-already-exists")
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=parent,
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
        raise StarGatewayRehearsalError("output-write-failed") from exc


def _build_rpc_runner(
    openclaw_cli: Path,
    runtime_root: Path,
    home: Path,
    state_root: Path,
    config: Path,
    workspace: Path,
    rpc_timeout_seconds: int,
) -> RpcRunner:
    cli = _regular_file(openclaw_cli, "openclaw-cli", executable=True)
    runtime = _directory(runtime_root, "runtime-root")
    _require(cli.is_relative_to(runtime), "openclaw-cli-outside-runtime")
    resolved_home = _directory(home, "openclaw-home")
    resolved_state = _directory(state_root, "state-root")
    resolved_config = _regular_file(config, "openclaw-config")
    resolved_workspace = _directory(workspace, "workspace")
    _require(1 <= rpc_timeout_seconds <= 300, "rpc-timeout-invalid")

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

    def run(
        method: str,
        params: dict[str, Any],
        expect_final: bool = False,
    ) -> dict[str, Any]:
        command = [
            str(cli),
            "gateway",
            "call",
            method,
            "--params",
            json.dumps(params, separators=(",", ":")),
            "--json",
            "--timeout",
            str(rpc_timeout_seconds * 1000),
        ]
        if expect_final:
            command.append("--expect-final")
        completed = subprocess.run(
            command,
            env=environment,
            capture_output=True,
            timeout=rpc_timeout_seconds + 10,
            check=False,
        )
        _require(completed.returncode == 0, "gateway-rpc-nonzero")
        _require(not completed.stderr.strip(), "gateway-rpc-stderr")
        _require(len(completed.stdout) <= MAX_RPC_BYTES, "gateway-rpc-too-large")
        try:
            response = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StarGatewayRehearsalError("gateway-rpc-invalid-json") from exc
        _require(isinstance(response, dict), "gateway-rpc-invalid-shape")
        return response

    return run


def _initial_yield(response: dict[str, Any]) -> None:
    _require(response.get("status") == "ok", "star-initial-status")
    result = response.get("result")
    _require(isinstance(result, dict), "star-initial-result")
    payloads = result.get("payloads")
    meta = result.get("meta")
    _require(payloads == [], "star-initial-visible-payload")
    _require(isinstance(meta, dict), "star-initial-meta")
    _require(meta.get("yielded") is True, "star-initial-not-yielded")
    _require(meta.get("livenessState") == "paused", "star-initial-not-paused")


def _active_run_count(payload: dict[str, Any]) -> int:
    sessions = payload.get("sessions")
    _require(isinstance(sessions, list), "sessions-list-missing")
    _require(payload.get("hasMore") is False, "sessions-list-incomplete")
    _require(payload.get("totalCount") == len(sessions), "sessions-list-count")
    return sum(
        1
        for row in sessions
        if isinstance(row, dict) and row.get("hasActiveRun") is True
    )


def _assistant_texts(payload: dict[str, Any]) -> list[str]:
    messages = payload.get("messages")
    _require(isinstance(messages, list), "history-messages-missing")
    texts: list[str] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        parts = [
            block["text"].strip()
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
            and block["text"].strip()
        ]
        if parts:
            texts.append("\n".join(parts))
    return texts


def run_rehearsal(
    *,
    rpc: RpcRunner,
    prompt: str,
    agent: str,
    session_key: str,
    wait_seconds: int,
    poll_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    _require(agent == "main", "unsupported-star-agent")
    _require(
        session_key.startswith("agent:main:explicit:behavior-star-"),
        "unsupported-star-session-key",
    )
    _require(1 <= wait_seconds <= 1800, "wait-timeout-invalid")
    _require(0.1 <= poll_seconds <= 10, "poll-interval-invalid")

    initial = rpc(
        "agent",
        {
            "message": prompt,
            "agentId": agent,
            "sessionKey": session_key,
            "deliver": False,
            "timeout": wait_seconds,
            "cleanupBundleMcpOnRunEnd": False,
            "idempotencyKey": str(uuid.uuid4()),
        },
        True,
    )
    _initial_yield(initial)

    deadline = monotonic() + wait_seconds
    final_text: str | None = None
    final_active_count = -1
    while monotonic() < deadline:
        sessions = rpc(
            "sessions.list",
            {
                "limit": 1000,
                "offset": 0,
                "configuredAgentsOnly": True,
                "archived": False,
                "includeDerivedTitles": False,
                "includeLastMessage": False,
            },
            False,
        )
        history = rpc(
            "chat.history",
            {"sessionKey": session_key, "limit": MAX_HISTORY_MESSAGES},
            False,
        )
        final_active_count = _active_run_count(sessions)
        assistant_texts = _assistant_texts(history)
        _require(len(assistant_texts) <= 1, "star-visible-answer-count")
        if assistant_texts and final_active_count == 0:
            final_text = assistant_texts[0]
            break
        sleep(poll_seconds)

    _require(final_text is not None, "star-followup-timeout")
    return {
        "status": "ok",
        "summary": "completed",
        "result": {
            "payloads": [{"text": final_text}],
            "meta": {
                "completionSource": "gateway-followup",
                "initialYielded": True,
                "activeRunCount": final_active_count,
            },
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openclaw", required=True, type=Path)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--prompt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--session-key", required=True)
    parser.add_argument("--wait-seconds", type=int, default=900)
    parser.add_argument("--poll-seconds", type=float, default=2)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=300)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    started = time.monotonic()
    try:
        prompt = _read_prompt(arguments.prompt)
        rpc = _build_rpc_runner(
            arguments.openclaw,
            arguments.runtime_root,
            arguments.home,
            arguments.state_root,
            arguments.config,
            arguments.workspace,
            arguments.rpc_timeout_seconds,
        )
        report = run_rehearsal(
            rpc=rpc,
            prompt=prompt,
            agent=arguments.agent,
            session_key=arguments.session_key,
            wait_seconds=arguments.wait_seconds,
            poll_seconds=arguments.poll_seconds,
        )
        _write_private_json(arguments.output, report)
    except StarGatewayRehearsalError as exc:
        print(json.dumps({"status": "error", "errorCode": str(exc)}))
        return 1
    print(
        json.dumps(
            {
                "status": "ok",
                "initialYielded": True,
                "payloadCount": 1,
                "activeRunCount": 0,
                "durationMs": int((time.monotonic() - started) * 1000),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
