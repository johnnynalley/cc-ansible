#!/usr/bin/env python3
"""Audit private OpenClaw behavior-canary evidence without exposing its text."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
AGENTS = ("main", "dubble", "vega", "antares", "rigel")
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_TRANSCRIPT_BYTES = 16 * 1024 * 1024
MAX_TRANSCRIPT_ROWS = 20_000
INTERNAL_FINAL_TERMS = re.compile(
    r"\b(?:antares|dispute|pass|reviewer|star|vega)\b", re.IGNORECASE
)
DANGEROUS_TOOLS = {
    "apply_patch",
    "browser",
    "canvas",
    "cron",
    "edit",
    "exec",
    "gateway",
    "image",
    "image_generate",
    "memory_get",
    "memory_search",
    "message",
    "music_generate",
    "nodes",
    "process",
    "tts",
    "video_generate",
    "web_fetch",
    "web_search",
    "write",
}
TOOL_CALL_TYPES = {
    "functionCall",
    "function_call",
    "toolCall",
    "toolUse",
    "tool_call",
    "tool_use",
}


class BehaviorAuditError(RuntimeError):
    """Raised when private canary evidence violates the behavior contract."""


def _fail(code: str) -> None:
    raise BehaviorAuditError(code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        _fail(code)


def _regular_file(path: Path, label: str, *, max_bytes: int | None = None) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise BehaviorAuditError(f"{label}-unavailable") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        _fail(f"{label}-not-regular-file")
    if max_bytes is not None and metadata.st_size > max_bytes:
        _fail(f"{label}-too-large")
    return path.resolve()


def _directory(path: Path, label: str) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise BehaviorAuditError(f"{label}-unavailable") from exc
    if path.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        _fail(f"{label}-not-directory")
    return path.resolve()


def _regular_under(
    path: Path,
    root: Path,
    label: str,
    *,
    max_bytes: int | None = None,
) -> Path:
    resolved_root = _directory(root, f"{label}-root")
    _require(path.is_absolute(), f"{label}-not-absolute")
    _require(".." not in path.parts, f"{label}-parent-traversal")
    lexical = Path(os.path.abspath(path))
    try:
        relative = lexical.relative_to(resolved_root)
    except ValueError:
        _fail(f"{label}-outside-root")
    current = resolved_root
    for component in relative.parts:
        current = current / component
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise BehaviorAuditError(f"{label}-unavailable") from exc
        if stat.S_ISLNK(metadata.st_mode):
            _fail(f"{label}-symlink-component")
    return _regular_file(current, label, max_bytes=max_bytes)


def _load_json(path: Path, label: str) -> Any:
    resolved = _regular_file(path, label, max_bytes=MAX_JSON_BYTES)
    try:
        return json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BehaviorAuditError(f"{label}-invalid-json") from exc


def _load_store(state_root: Path, agent: str) -> dict[str, Any]:
    path = state_root / "agents" / agent / "sessions" / "sessions.json"
    resolved = _regular_under(
        path,
        state_root,
        f"{agent}-session-index",
        max_bytes=MAX_JSON_BYTES,
    )
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BehaviorAuditError(f"{agent}-session-index-invalid-json") from exc
    _require(isinstance(payload, dict), f"{agent}-session-index-invalid-shape")
    return payload


def _session_entry(
    stores: dict[str, dict[str, Any]], agent: str, session_key: str
) -> dict[str, Any]:
    entry = stores[agent].get(session_key)
    _require(isinstance(entry, dict), f"{agent}-session-missing")
    return entry


def _agent_result_text(path: Path, label: str) -> str:
    payload = _load_json(path, label)
    _require(isinstance(payload, dict), f"{label}-invalid-shape")
    _require(payload.get("status") == "ok", f"{label}-not-ok")
    result = payload.get("result")
    _require(isinstance(result, dict), f"{label}-result-missing")
    response_payloads = result.get("payloads")
    _require(isinstance(response_payloads, list), f"{label}-payloads-missing")
    texts: list[str] = []
    for response in response_payloads:
        _require(isinstance(response, dict), f"{label}-payload-invalid")
        _require(
            not response.get("mediaUrl") and not response.get("mediaUrls"),
            f"{label}-unexpected-media",
        )
        text = response.get("text")
        if isinstance(text, str) and text.strip():
            texts.append(text.strip())
    _require(len(texts) == 1, f"{label}-text-count")
    return texts[0]


def _message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            text = block.get("text")
            if block_type in {"text", "input_text", "output_text"} and isinstance(
                text, str
            ):
                texts.append(text)
        return "\n".join(texts).strip()
    text = message.get("text")
    return text.strip() if isinstance(text, str) else ""


def _read_transcript(
    entry: dict[str, Any], state_root: Path, label: str
) -> list[dict[str, Any]]:
    session_file = entry.get("sessionFile")
    _require(isinstance(session_file, str) and session_file, f"{label}-file-missing")
    path = Path(session_file)
    _require(path.is_absolute(), f"{label}-file-not-absolute")
    resolved = _regular_under(
        path,
        state_root,
        f"{label}-file",
        max_bytes=MAX_TRANSCRIPT_BYTES,
    )
    rows: list[dict[str, Any]] = []
    try:
        with resolved.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise BehaviorAuditError(
                        f"{label}-invalid-jsonl-line-{line_number}"
                    ) from exc
                _require(isinstance(row, dict), f"{label}-invalid-row")
                rows.append(row)
                _require(
                    len(rows) <= MAX_TRANSCRIPT_ROWS,
                    f"{label}-too-many-rows",
                )
    except (OSError, UnicodeDecodeError) as exc:
        raise BehaviorAuditError(f"{label}-read-failed") from exc
    _require(bool(rows), f"{label}-empty")
    return rows


def _messages(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row["message"]
        for row in rows
        if row.get("type") == "message" and isinstance(row.get("message"), dict)
    ]


def _last_text(messages: list[dict[str, Any]], role: str, label: str) -> str:
    for message in reversed(messages):
        if message.get("role") == role:
            text = _message_text(message)
            if text:
                return text
    _fail(f"{label}-{role}-text-missing")


def _all_text(messages: list[dict[str, Any]], role: str) -> str:
    return "\n".join(
        text
        for message in messages
        if message.get("role") == role
        for text in [_message_text(message)]
        if text
    )


def _split_model(reference: str, label: str) -> tuple[str, str]:
    provider, separator, model = reference.partition("/")
    _require(bool(separator and provider and model), f"{label}-model-invalid")
    return provider, model


def _audit_prompt_report(
    entry: dict[str, Any],
    *,
    agent: str,
    session_key: str,
    model_reference: str,
    workspace_root: Path,
    required_files: set[str],
    required_tools: set[str],
    generated_after_ms: int | None = None,
) -> dict[str, int]:
    report = entry.get("systemPromptReport")
    _require(isinstance(report, dict), f"{agent}-prompt-report-missing")
    provider, model = _split_model(model_reference, agent)
    _require(report.get("source") == "run", f"{agent}-prompt-report-not-run")
    _require(report.get("sessionKey") == session_key, f"{agent}-report-session-key")
    _require(
        report.get("sessionId") == entry.get("sessionId"),
        f"{agent}-report-session-id",
    )
    _require(report.get("provider") == provider, f"{agent}-provider-drift")
    _require(report.get("model") == model, f"{agent}-model-drift")
    expected_workspace = workspace_root if agent == "main" else workspace_root / agent
    _require(
        report.get("workspaceDir") == str(expected_workspace),
        f"{agent}-workspace-drift",
    )
    if generated_after_ms is not None:
        generated_at = report.get("generatedAt")
        _require(
            isinstance(generated_at, int) and generated_at >= generated_after_ms,
            f"{agent}-prompt-report-stale",
        )
    injected = report.get("injectedWorkspaceFiles")
    _require(isinstance(injected, list), f"{agent}-bootstrap-report-missing")
    injected_names = {
        item.get("name")
        for item in injected
        if isinstance(item, dict) and item.get("missing") is False
    }
    _require(required_files <= injected_names, f"{agent}-bootstrap-files-missing")
    tools = report.get("tools")
    _require(isinstance(tools, dict), f"{agent}-tool-report-missing")
    entries = tools.get("entries")
    _require(isinstance(entries, list), f"{agent}-tool-entries-missing")
    tool_names = {item.get("name") for item in entries if isinstance(item, dict)}
    _require(required_tools <= tool_names, f"{agent}-required-tool-missing")
    _require(
        not DANGEROUS_TOOLS.intersection(tool_names),
        f"{agent}-dangerous-tool-present",
    )
    return {
        "bootstrapFiles": len(injected_names),
        "effectiveTools": len(tool_names),
    }


def _child_for_parent(
    stores: dict[str, dict[str, Any]],
    agent: str,
    parent_key: str,
    *,
    expected_depth: int,
    expected_role: str,
) -> tuple[str, dict[str, Any]]:
    matches = [
        (key, entry)
        for key, entry in stores[agent].items()
        if isinstance(entry, dict) and entry.get("spawnedBy") == parent_key
    ]
    _require(len(matches) == 1, f"{agent}-child-count")
    key, entry = matches[0]
    _require(entry.get("status") == "done", f"{agent}-child-not-done")
    _require(entry.get("spawnDepth") == expected_depth, f"{agent}-spawn-depth")
    _require(entry.get("subagentRole") == expected_role, f"{agent}-role-drift")
    return key, entry


def _children_for_parent(
    stores: dict[str, dict[str, Any]], parent_key: str
) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (agent, key, entry)
        for agent, entries in stores.items()
        for key, entry in entries.items()
        if isinstance(entry, dict) and entry.get("spawnedBy") == parent_key
    ]


def _parse_timestamp_ms(value: Any, label: str) -> int:
    _require(isinstance(value, str) and value, f"{label}-timestamp-missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BehaviorAuditError(f"{label}-timestamp-invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _tool_call_name(block: dict[str, Any]) -> str | None:
    name = block.get("name")
    if isinstance(name, str):
        return name
    function = block.get("function")
    if isinstance(function, dict) and isinstance(function.get("name"), str):
        return function["name"]
    return None


def _tool_call_arguments(block: dict[str, Any]) -> dict[str, Any] | None:
    value = block.get("arguments", block.get("args", block.get("input")))
    function = block.get("function")
    if value is None and isinstance(function, dict):
        value = function.get("arguments", function.get("args", function.get("input")))
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _assistant_tool_calls(
    messages: list[dict[str, Any]], label: str
) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") not in TOOL_CALL_TYPES:
                continue
            name = _tool_call_name(block)
            _require(isinstance(name, str) and name, f"{label}-tool-name-missing")
            arguments = _tool_call_arguments(block)
            _require(arguments is not None, f"{label}-tool-arguments-missing")
            calls.append((name, arguments))
    return calls


def _argument(arguments: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in arguments:
            return arguments[name]
    return None


def _audit_star_transcript(
    messages: list[dict[str, Any]],
    *,
    nonce: str,
    star_text: str,
) -> dict[str, int]:
    _require(
        _last_text(messages, "assistant", "main") == star_text,
        "star-result-transcript-mismatch",
    )
    visible_texts = [
        text
        for message in messages
        if message.get("role") == "assistant"
        for text in [_message_text(message)]
        if text
    ]
    _require(visible_texts == [star_text], "star-visible-answer-count")
    calls = _assistant_tool_calls(messages, "main")
    _require(
        all(name in {"sessions_spawn", "sessions_yield"} for name, _ in calls),
        "star-unexpected-tool-call",
    )
    spawn_calls = [arguments for name, arguments in calls if name == "sessions_spawn"]
    _require(len(spawn_calls) == 1, "star-spawn-count")
    required_facts = ("Cedar", "Birch", "$12", "$10", "$30", "MFA", "IMAP")
    arguments = spawn_calls[0]
    _require(
        _argument(arguments, "agentId", "agent_id", "agent") == "vega",
        "star-spawn-agent-0",
    )
    _require(arguments.get("mode") == "run", "star-spawn-mode-0")
    _require(arguments.get("cleanup") == "keep", "star-spawn-cleanup-0")
    task = _argument(arguments, "task", "prompt", "message")
    _require(isinstance(task, str) and nonce in task, "star-spawn-task-0")
    _require(
        all(fact.casefold() in task.casefold() for fact in required_facts),
        "star-spawn-facts-0",
    )
    _require("antares" in task.casefold(), "star-nested-review-missing")

    call_names = [name for name, _ in calls]
    first_spawn = call_names.index("sessions_spawn")
    yields = [
        index for index, name in enumerate(call_names) if name == "sessions_yield"
    ]
    _require(
        len(yields) == 1 and yields[0] > first_spawn,
        "star-vega-yield-missing",
    )
    return {"spawnCalls": 1, "yieldCalls": len(yields)}


def _audit_vega_orchestration(
    messages: list[dict[str, Any]],
    *,
    nonce: str,
    antares_user: str,
    antares_final: str,
    vega_final: str,
) -> dict[str, int]:
    _require(
        _last_text(messages, "assistant", "vega") == vega_final,
        "vega-final-transcript-mismatch",
    )
    visible_texts = [
        text
        for message in messages
        if message.get("role") == "assistant"
        for text in [_message_text(message)]
        if text
    ]
    _require(visible_texts == [vega_final], "vega-visible-packet-count")
    calls = _assistant_tool_calls(messages, "vega")
    _require(
        all(name in {"sessions_spawn", "sessions_yield"} for name, _ in calls),
        "vega-unexpected-tool-call",
    )
    spawn_calls = [arguments for name, arguments in calls if name == "sessions_spawn"]
    _require(len(spawn_calls) == 1, "vega-spawn-count")
    arguments = spawn_calls[0]
    _require(
        _argument(arguments, "agentId", "agent_id", "agent") == "antares",
        "vega-spawn-agent",
    )
    _require(arguments.get("mode") == "run", "vega-spawn-mode")
    _require(arguments.get("cleanup") == "keep", "vega-spawn-cleanup")
    task = _argument(arguments, "task", "prompt", "message")
    required_facts = ("Cedar", "Birch", "$12", "$10", "$30", "MFA", "IMAP")
    _require(isinstance(task, str) and nonce in task, "vega-spawn-task")
    _require(
        all(fact.casefold() in task.casefold() for fact in required_facts),
        "vega-spawn-facts",
    )
    _require(
        "preliminary packet" in task.casefold(),
        "antares-missing-vega-packet",
    )
    _require(task.strip() in antares_user, "antares-task-transcript-mismatch")
    call_names = [name for name, _ in calls]
    spawn_index = call_names.index("sessions_spawn")
    yields = [
        index for index, name in enumerate(call_names) if name == "sessions_yield"
    ]
    _require(
        len(yields) == 1 and yields[0] > spawn_index,
        "vega-antares-yield-missing",
    )
    _require(
        antares_final in _all_text(messages, "user"), "vega-missing-antares-result"
    )
    _require(nonce in vega_final, "vega-final-lineage")
    _require(
        re.search(r"\b(?:PASS|FAIL|DISPUTE)\b", vega_final) is not None,
        "vega-final-verdict-missing",
    )
    return {"spawnCalls": 1, "yieldCalls": len(yields)}


def _audit_heartbeat_transcript(
    rows: list[dict[str, Any]], started_at_ms: int
) -> dict[str, int]:
    new_messages: list[dict[str, Any]] = []
    for row in rows:
        if row.get("type") != "message" or not isinstance(row.get("message"), dict):
            continue
        if _parse_timestamp_ms(row.get("timestamp"), "rigel") >= started_at_ms:
            new_messages.append(row["message"])
    _require(bool(new_messages), "rigel-new-transcript-missing")
    heartbeat_calls: list[dict[str, Any]] = []
    visible_texts: list[str] = []
    tool_errors = 0
    for message in new_messages:
        if message.get("role") == "assistant":
            text = _message_text(message)
            if text:
                visible_texts.append(text)
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if (
                        block.get("type") in TOOL_CALL_TYPES
                        and _tool_call_name(block) == "heartbeat_respond"
                    ):
                        arguments = _tool_call_arguments(block)
                        _require(arguments is not None, "rigel-heartbeat-arguments")
                        heartbeat_calls.append(arguments)
        if message.get("role") in {"tool", "toolResult"} and (
            message.get("isError") is True or message.get("is_error") is True
        ):
            tool_errors += 1
        content = message.get("content")
        if isinstance(content, list):
            tool_errors += sum(
                1
                for block in content
                if isinstance(block, dict)
                and (
                    block.get("isError") is True
                    or block.get("is_error") is True
                    or block.get("type") == "tool_result_error"
                )
            )
    _require(len(heartbeat_calls) == 1, "rigel-heartbeat-call-count")
    _require(
        heartbeat_calls[0].get("notify") is False,
        "rigel-heartbeat-notify-enabled",
    )
    _require(not visible_texts, "rigel-visible-assistant-text")
    _require(tool_errors == 0, "rigel-tool-error")
    return {"newMessages": len(new_messages), "heartbeatCalls": 1}


def _audit_heartbeat_event(
    path: Path, started_at_ms: int
) -> dict[str, int | str | bool]:
    event = _load_json(path, "heartbeat-event")
    _require(isinstance(event, dict), "heartbeat-event-invalid-shape")
    _require(event.get("status") == "ok-token", "heartbeat-event-status")
    _require(event.get("silent") is True, "heartbeat-event-not-silent")
    _require(
        not {"accountId", "channel", "to"}.intersection(event),
        "heartbeat-event-route-present",
    )
    timestamp = event.get("ts")
    _require(
        isinstance(timestamp, int) and timestamp >= started_at_ms,
        "heartbeat-event-stale",
    )
    preview = event.get("preview")
    if isinstance(preview, str):
        lowered = preview.casefold()
        _require("heartbeat_ok" not in lowered, "heartbeat-control-token-preview")
        _require("thinking process" not in lowered, "heartbeat-reasoning-preview")
        _require("exec failed" not in lowered, "heartbeat-tool-error-preview")
    return {"status": "ok-token", "silent": True, "ts": timestamp}


def audit_behavior(
    *,
    state_root: Path,
    workspace_root: Path,
    dubble_result: Path,
    dubble_session_key: str,
    dubble_marker: str,
    star_result: Path,
    star_session_key: str,
    nonce: str,
    heartbeat_event: Path,
    heartbeat_session_key: str,
    heartbeat_started_at_ms: int,
    primary_model: str,
    antares_model: str,
) -> dict[str, Any]:
    resolved_state = _directory(state_root, "state-root")
    resolved_workspace = _directory(workspace_root, "workspace-root")
    stores = {agent: _load_store(resolved_state, agent) for agent in AGENTS}

    dubble_text = _agent_result_text(dubble_result, "dubble-result")
    _require(dubble_text == dubble_marker, "dubble-marker-mismatch")
    dubble_entry = _session_entry(stores, "dubble", dubble_session_key)
    dubble_report = _audit_prompt_report(
        dubble_entry,
        agent="dubble",
        session_key=dubble_session_key,
        model_reference=primary_model,
        workspace_root=resolved_workspace,
        required_files={"AGENTS.md", "SOUL.md"},
        required_tools={"read", "session_status"},
    )
    dubble_messages = _messages(
        _read_transcript(dubble_entry, resolved_state, "dubble")
    )
    _require(
        _last_text(dubble_messages, "assistant", "dubble") == dubble_text,
        "dubble-result-transcript-mismatch",
    )
    _require(
        not _assistant_tool_calls(dubble_messages, "dubble"),
        "dubble-unexpected-tool-call",
    )

    star_text = _agent_result_text(star_result, "star-result")
    _require(len(star_text) <= 300, "star-final-too-long")
    _require("\n" not in star_text, "star-final-not-one-line")
    _require(
        star_text.count(".") + star_text.count("!") + star_text.count("?") <= 2,
        "star-final-too-many-sentences",
    )
    _require(INTERNAL_FINAL_TERMS.search(star_text) is None, "star-final-internal-meta")
    _require(nonce not in star_text, "star-final-leaked-nonce")
    for required_fact in ("Cedar", "$24", "$30", "MFA", "IMAP"):
        _require(
            required_fact.casefold() in star_text.casefold(), "star-final-fact-gap"
        )

    main_entry = _session_entry(stores, "main", star_session_key)
    main_report = _audit_prompt_report(
        main_entry,
        agent="main",
        session_key=star_session_key,
        model_reference=primary_model,
        workspace_root=resolved_workspace,
        required_files={"AGENTS.md", "SOUL.md", "USER.md"},
        required_tools={"sessions_spawn", "sessions_yield"},
    )

    top_level_children = _children_for_parent(stores, star_session_key)
    _require(len(top_level_children) == 1, "star-top-level-child-count")
    _require(top_level_children[0][0] == "vega", "star-top-level-child-agent")
    vega_key, vega_entry = _child_for_parent(
        stores,
        "vega",
        star_session_key,
        expected_depth=1,
        expected_role="orchestrator",
    )
    vega_children = _children_for_parent(stores, vega_key)
    _require(len(vega_children) == 1, "vega-child-count-all-agents")
    _require(vega_children[0][0] == "antares", "vega-child-agent")
    antares_key, antares_entry = _child_for_parent(
        stores,
        "antares",
        vega_key,
        expected_depth=2,
        expected_role="leaf",
    )
    vega_report = _audit_prompt_report(
        vega_entry,
        agent="vega",
        session_key=vega_key,
        model_reference=primary_model,
        workspace_root=resolved_workspace,
        required_files={"AGENTS.md", "SOUL.md"},
        required_tools={"read", "session_status", "sessions_spawn", "sessions_yield"},
    )
    antares_report = _audit_prompt_report(
        antares_entry,
        agent="antares",
        session_key=antares_key,
        model_reference=antares_model,
        workspace_root=resolved_workspace,
        required_files={"AGENTS.md", "SOUL.md"},
        required_tools={"read", "session_status"},
    )

    vega_messages = _messages(_read_transcript(vega_entry, resolved_state, "vega"))
    antares_messages = _messages(
        _read_transcript(antares_entry, resolved_state, "antares")
    )
    vega_user = _all_text(vega_messages, "user")
    vega_final = _last_text(vega_messages, "assistant", "vega")
    antares_user = _all_text(antares_messages, "user")
    antares_final = _last_text(antares_messages, "assistant", "antares")
    _require(nonce in vega_user and nonce in vega_final, "vega-nonce-lineage")
    _require(nonce in antares_user and nonce in antares_final, "antares-nonce-lineage")
    _require(
        re.search(r"\b(?:PASS|FAIL|DISPUTE)\b", antares_final) is not None,
        "antares-verdict-missing",
    )
    vega_orchestration = _audit_vega_orchestration(
        vega_messages,
        nonce=nonce,
        antares_user=antares_user,
        antares_final=antares_final,
        vega_final=vega_final,
    )
    main_messages = _messages(_read_transcript(main_entry, resolved_state, "main"))
    star_transcript = _audit_star_transcript(
        main_messages,
        nonce=nonce,
        star_text=star_text,
    )

    rigel_entry = _session_entry(stores, "rigel", heartbeat_session_key)
    rigel_report = _audit_prompt_report(
        rigel_entry,
        agent="rigel",
        session_key=heartbeat_session_key,
        model_reference=primary_model,
        workspace_root=resolved_workspace,
        required_files={"HEARTBEAT.md"},
        required_tools={"heartbeat_respond", "read"},
        generated_after_ms=heartbeat_started_at_ms,
    )
    rigel_transcript = _audit_heartbeat_transcript(
        _read_transcript(rigel_entry, resolved_state, "rigel"),
        heartbeat_started_at_ms,
    )
    heartbeat = _audit_heartbeat_event(heartbeat_event, heartbeat_started_at_ms)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "ok",
        "agentsValidated": list(AGENTS),
        "checks": {
            "dubble": {
                "responseMarker": True,
                "transcriptMatches": True,
                **dubble_report,
            },
            "star": {
                "childCount": 2,
                "conciseFinal": True,
                "nestedReview": True,
                "packetPassedToReviewer": True,
                "resultMatchesTranscript": True,
                **star_transcript,
                "main": main_report,
                "vega": {**vega_report, **vega_orchestration},
                "antares": antares_report,
            },
            "rigel": {
                **rigel_report,
                **rigel_transcript,
                "event": heartbeat,
            },
        },
        "evidenceHashes": {
            "dubbleResult": hashlib.sha256(
                _regular_file(dubble_result, "dubble-result").read_bytes()
            ).hexdigest(),
            "starResult": hashlib.sha256(
                _regular_file(star_result, "star-result").read_bytes()
            ).hexdigest(),
            "heartbeatEvent": hashlib.sha256(
                _regular_file(heartbeat_event, "heartbeat-event").read_bytes()
            ).hexdigest(),
        },
    }


def _write_json_atomic(path: Path, payload: Any) -> None:
    parent = _directory(path.parent, "output-parent")
    if path.exists() and (path.is_symlink() or not path.is_file()):
        _fail("output-not-regular-file")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise BehaviorAuditError("output-write-failed") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--dubble-result", required=True, type=Path)
    parser.add_argument("--dubble-session-key", required=True)
    parser.add_argument("--dubble-marker", required=True)
    parser.add_argument("--star-result", required=True, type=Path)
    parser.add_argument("--star-session-key", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--heartbeat-event", required=True, type=Path)
    parser.add_argument("--heartbeat-session-key", required=True)
    parser.add_argument("--heartbeat-started-at-ms", required=True, type=int)
    parser.add_argument("--primary-model", required=True)
    parser.add_argument("--antares-model", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = audit_behavior(
            state_root=args.state_root,
            workspace_root=args.workspace_root,
            dubble_result=args.dubble_result,
            dubble_session_key=args.dubble_session_key,
            dubble_marker=args.dubble_marker,
            star_result=args.star_result,
            star_session_key=args.star_session_key,
            nonce=args.nonce,
            heartbeat_event=args.heartbeat_event,
            heartbeat_session_key=args.heartbeat_session_key,
            heartbeat_started_at_ms=args.heartbeat_started_at_ms,
            primary_model=args.primary_model,
            antares_model=args.antares_model,
        )
        _write_json_atomic(args.output, report)
    except (BehaviorAuditError, OSError):
        print(json.dumps({"status": "error", "errorCode": "behavior-audit-failed"}))
        return 1
    print(
        json.dumps(
            {
                "status": "ok",
                "agentCount": len(report["agentsValidated"]),
                "starChildCount": report["checks"]["star"]["childCount"],
                "rigelSilent": report["checks"]["rigel"]["event"]["silent"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
