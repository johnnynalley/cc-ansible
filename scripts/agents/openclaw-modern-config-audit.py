#!/usr/bin/env python3
"""Audit a rendered modern OpenClaw config without initializing OpenClaw."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


class AuditError(RuntimeError):
    """Raised when the rendered config violates the modernization contract."""


EXPECTED_TOP_LEVEL = {
    "agents",
    "auth",
    "bindings",
    "channels",
    "commands",
    "cron",
    "discovery",
    "gateway",
    "logging",
    "memory",
    "messages",
    "plugins",
    "secrets",
    "session",
    "skills",
    "tools",
    "update",
}
CHANNEL_LESS_TOP_LEVEL = EXPECTED_TOP_LEVEL - {"bindings", "channels", "cron"}

EXPECTED_AGENTS = ["main", "dubble", "vega", "antares", "rigel"]
EXPECTED_PLUGINS = [
    "codex",
    "device-pair",
    "discord",
    "google",
    "lossless-claw",
    "ollama",
    "openai",
    "openclaw-mem0",
]
BEHAVIOR_CANARY_PLUGINS = ["codex", "ollama", "openai"]
BEHAVIOR_CANARY_AGENT_TOOLS = {
    "dubble": {
        "heartbeat_respond",
        "read",
        "session_status",
        "sessions_send",
        "sessions_yield",
    },
    "vega": {
        "read",
        "session_status",
        "sessions_spawn",
        "sessions_yield",
        "subagents",
    },
    "antares": {"read", "session_status"},
    "rigel": {
        "heartbeat_respond",
        "read",
        "session_status",
        "sessions_send",
        "sessions_yield",
    },
}
BEHAVIOR_CANARY_DENIES = {
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
SECURITY_CANARY_DENIES = BEHAVIOR_CANARY_DENIES | {
    "group:automation",
    "group:fs",
    "group:messaging",
    "group:nodes",
    "read",
}
NATIVE_MUTATION_DENIES = {
    "apply_patch",
    "canvas",
    "cron",
    "edit",
    "exec",
    "gateway",
    "message",
    "nodes",
    "process",
    "write",
}
RETIRED_FRAGMENTS = (
    "/home/johnny",
    "brave",
    "cognitive-stack",
    "github-copilot",
    "internal-token-delivery-guard",
    "nextcloud-talk",
    "openrouter",
    "perplexity",
    "self-evolution-gate",
)
SECRET_FIELD_NAMES = {"apikey", "authtoken", "password", "secret", "token"}


def _fail(message: str) -> None:
    raise AuditError(message)


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _at(config: dict[str, Any], *path: str) -> Any:
    current: Any = config
    for key in path:
        if not isinstance(current, dict) or key not in current:
            _fail(f"missing-config-path:{'.'.join(path)}")
        current = current[key]
    return current


def _is_file_secret_ref(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("source") == "file"
        and value.get("provider") == "production"
        and isinstance(value.get("id"), str)
        and value["id"].startswith("/")
        and set(value) == {"source", "provider", "id"}
    )


def _walk(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = (*path, key)
            if key.casefold() in SECRET_FIELD_NAMES:
                _require(
                    _is_file_secret_ref(child),
                    f"credential-not-file-secret-ref:{'.'.join(child_path)}",
                )
            _walk(child, child_path)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _walk(child, (*path, str(index)))
        return
    if isinstance(value, str):
        lowered = value.casefold()
        for fragment in RETIRED_FRAGMENTS:
            if fragment.casefold() in lowered:
                _fail(f"retired-fragment:{'.'.join(path)}:{fragment}")


def _audit_provider_auth_boundary(config: dict[str, Any]) -> None:
    auth = _at(config, "auth")
    _require(
        auth
        == {
            "profiles": {
                "ollama-cloud:default": {
                    "provider": "ollama-cloud",
                    "mode": "token",
                }
            },
            "order": {"ollama-cloud": ["ollama-cloud:default"]},
        },
        "gateway-provider-auth-boundary",
    )


def _audit_agents(
    config: dict[str, Any], heartbeat_mode: str, deployment_mode: str
) -> None:
    agents = _at(config, "agents")
    defaults = _at(agents, "defaults")
    listed = _at(agents, "list")
    _require(isinstance(listed, list), "agents-list-not-array")
    _require(
        [agent.get("id") for agent in listed if isinstance(agent, dict)]
        == EXPECTED_AGENTS,
        "agent-order-or-membership-mismatch",
    )
    _require(defaults.get("skipBootstrap") is True, "bootstrap-seeding-enabled")
    _require(defaults.get("skills") == [], "dynamic-agent-skills-enabled")
    _require(
        defaults.get("contextInjection") == "continuation-skip",
        "unsafe-context-injection-mode",
    )
    _require(defaults.get("bootstrapMaxChars") == 6500, "bootstrap-file-budget-drift")
    _require(
        defaults.get("bootstrapTotalMaxChars") == 10000,
        "bootstrap-total-budget-drift",
    )
    _require(
        _at(defaults, "contextPruning", "mode") == "cache-ttl",
        "context-pruning-not-modernized",
    )
    _require(
        _at(defaults, "compaction", "mode") == "safeguard",
        "compaction-not-safeguarded",
    )
    _require(
        _at(defaults, "compaction", "qualityGuard", "enabled") is True,
        "compaction-quality-guard-disabled",
    )
    _require(
        _at(defaults, "compaction", "notifyUser") is False,
        "compaction-user-noise-enabled",
    )
    subagents = _at(defaults, "subagents")
    _require("model" not in subagents, "global-subagent-model-override-present")
    _require(
        subagents.get("maxSpawnDepth") == 2,
        "star-orchestrator-depth-drift",
    )
    _require(
        subagents.get("allowAgents") == ["rigel", "vega"],
        "default-subagent-route-drift",
    )

    by_id = {agent["id"]: agent for agent in listed}
    _require(by_id["main"].get("default") is True, "main-not-default-agent")
    _require(
        _at(by_id["main"], "subagents", "allowAgents") == ["rigel", "vega"],
        "main-subagent-route-drift",
    )
    _require(
        _at(by_id["vega"], "subagents", "allowAgents") == ["antares"],
        "vega-reviewer-route-drift",
    )
    for leaf_id in ("dubble", "antares", "rigel"):
        _require(
            _at(by_id[leaf_id], "subagents", "allowAgents") == [],
            f"leaf-subagent-route:{leaf_id}",
        )
    _require(
        _at(by_id["antares"], "model", "primary").startswith("ollama-cloud/"),
        "antares-not-independent-provider",
    )

    for agent_id in ("main", "dubble", "rigel"):
        heartbeat = _at(by_id[agent_id], "heartbeat")
        expected_heartbeat_cadence = (
            "30m"
            if heartbeat_mode == "production"
            else (
                "24h"
                if heartbeat_mode == "controlled-rigel" and agent_id == "rigel"
                else "0m"
            )
        )
        _require(
            heartbeat.get("every") == expected_heartbeat_cadence,
            f"heartbeat-cadence:{agent_id}",
        )
        if deployment_mode != "production":
            _require(
                heartbeat.get("target") == "none",
                f"heartbeat-target:{agent_id}",
            )
            _require(
                not {"accountId", "activeHours", "to"}.intersection(heartbeat),
                f"heartbeat-route-present:{agent_id}",
            )
        else:
            _require(
                heartbeat.get("target") == "discord",
                f"heartbeat-target:{agent_id}",
            )
            _require(bool(heartbeat.get("to")), f"heartbeat-recipient:{agent_id}")
        _require(
            heartbeat.get("includeReasoning") is False,
            f"heartbeat-reasoning-enabled:{agent_id}",
        )
        _require(
            heartbeat.get("suppressToolErrorWarnings") is True,
            f"heartbeat-tool-warning-noise:{agent_id}",
        )
        _require(
            heartbeat.get("lightContext") is True
            and heartbeat.get("isolatedSession") is True,
            f"heartbeat-context-not-isolated:{agent_id}",
        )
    _require(
        "activeHours" not in _at(by_id["rigel"], "heartbeat"),
        "rigel-heartbeat-not-always-on",
    )

    dubble_tools = set(_at(by_id["dubble"], "tools", "allow"))
    if deployment_mode != "production":
        for agent_id, expected_tools in BEHAVIOR_CANARY_AGENT_TOOLS.items():
            _require(
                set(_at(by_id[agent_id], "tools", "allow")) == expected_tools,
                f"canary-agent-tool-drift:{agent_id}",
            )
    else:
        _require("message" not in dubble_tools, "dubble-message-tool-present")
    rigel_tools = set(_at(by_id["rigel"], "tools", "allow"))
    _require("heartbeat_respond" in rigel_tools, "rigel-native-heartbeat-tool-missing")
    _require("message" not in rigel_tools, "rigel-message-tool-present")
    _require(
        not rigel_tools.intersection(
            {"exec", "process", "write", "edit", "apply_patch"}
        ),
        "rigel-host-mutation-tool-present",
    )


def _audit_tools(config: dict[str, Any], deployment_mode: str) -> None:
    tools = _at(config, "tools")
    _require(_at(tools, "fs", "workspaceOnly") is True, "filesystem-not-workspace-only")
    exec_config = _at(tools, "exec")
    _require(exec_config.get("host") == "gateway", "exec-host-drift")
    if deployment_mode == "behavior-canary":
        _require(tools.get("profile") == "minimal", "canary-tool-profile-drift")
        _require(
            set(tools.get("alsoAllow", []))
            == {
                "agents_list",
                "heartbeat_respond",
                "read",
                "session_status",
                "sessions_history",
                "sessions_list",
                "sessions_send",
                "sessions_spawn",
                "sessions_yield",
                "subagents",
            },
            "canary-tool-allowlist-drift",
        )
        _require(
            BEHAVIOR_CANARY_DENIES <= set(tools.get("deny", [])),
            "canary-tool-denylist-incomplete",
        )
    elif deployment_mode == "security-canary":
        _require(tools.get("profile") == "minimal", "canary-tool-profile-drift")
        _require(
            set(tools.get("alsoAllow", [])) == {"agents_list", "heartbeat_respond"},
            "security-canary-tool-allowlist-drift",
        )
        _require(
            SECURITY_CANARY_DENIES <= set(tools.get("deny", [])),
            "security-canary-tool-denylist-incomplete",
        )
    else:
        _require(tools.get("profile") == "coding", "production-tool-profile-drift")
        _require(
            set(tools.get("alsoAllow", [])) == {"agents_list", "heartbeat_respond"},
            "production-tool-allowlist-drift",
        )
        _require(
            NATIVE_MUTATION_DENIES <= set(tools.get("deny", [])),
            "production-control-tool-denylist-incomplete",
        )
    _require(exec_config.get("mode") == "auto", "exec-not-guardian-reviewed")
    _require(
        "security" not in exec_config and "ask" not in exec_config,
        "legacy-exec-policy",
    )
    _require(exec_config.get("strictInlineEval") is True, "inline-eval-not-guarded")
    _require("applyPatch" not in exec_config, "gateway-apply-patch-enabled")
    _require(exec_config.get("notifyOnExit") is False, "exec-exit-noise-enabled")
    _require(_at(tools, "elevated", "enabled") is False, "elevated-tools-enabled")
    cross_context = _at(tools, "message", "crossContext")
    _require(
        cross_context.get("allowWithinProvider") is False
        and cross_context.get("allowAcrossProviders") is False,
        "cross-context-messaging-enabled",
    )
    _require(_at(tools, "sessions", "visibility") == "all", "star-session-visibility")
    _require(_at(tools, "agentToAgent", "enabled") is True, "agent-delegation-disabled")
    _require(
        _at(tools, "agentToAgent", "allow") == ["main", "vega", "antares", "rigel"],
        "agent-delegation-target-drift",
    )
    ollama_denies = set(_at(tools, "byProvider", "ollama-cloud", "deny"))
    _require(
        {"group:runtime", "write", "edit", "apply_patch", "cron", "gateway", "message"}
        <= ollama_denies,
        "ollama-provider-tools-too-broad",
    )


def _audit_channels_and_bindings(config: dict[str, Any]) -> None:
    heartbeat = _at(config, "channels", "defaults", "heartbeat")
    _require(
        heartbeat == {"showOk": False, "showAlerts": True, "useIndicator": False},
        "channel-heartbeat-visibility-drift",
    )
    discord = _at(config, "channels", "discord")
    _require(discord.get("dmPolicy") == "allowlist", "discord-dm-policy-open")
    _require(discord.get("groupPolicy") == "allowlist", "discord-group-policy-open")
    _require(bool(discord.get("allowFrom")), "discord-owner-allowlist-empty")
    _require(bool(discord.get("guilds")), "discord-guild-allowlist-empty")
    _require(
        _at(discord, "actions", "channels") is False, "discord-channel-mutation-enabled"
    )
    _require(
        _at(discord, "execApprovals", "enabled") is True, "discord-approvals-disabled"
    )
    _require(
        _at(discord, "accounts", "dubble", "execApprovals", "enabled") is False,
        "dubble-can-approve-exec",
    )

    bindings = _at(config, "bindings")
    _require(
        isinstance(bindings, list) and len(bindings) == 3, "binding-count-mismatch"
    )
    _require(
        [binding.get("agentId") for binding in bindings] == ["rigel", "main", "dubble"],
        "binding-order-mismatch",
    )
    _require(
        _at(bindings[0], "match", "peer", "kind") == "channel"
        and bool(_at(bindings[0], "match", "peer", "id")),
        "rigel-peer-binding-missing",
    )
    for binding in bindings:
        _require(_at(binding, "match", "channel") == "discord", "non-discord-binding")


def _audit_gateway_and_control_plane(
    config: dict[str, Any], deployment_mode: str
) -> None:
    gateway = _at(config, "gateway")
    _require(gateway.get("bind") == "loopback", "gateway-not-loopback")
    _require(_at(gateway, "auth", "mode") == "token", "gateway-auth-mode")
    _require(_at(gateway, "auth", "allowTailscale") is False, "tailscale-token-bypass")
    _require(_at(gateway, "tailscale", "mode") == "off", "gateway-controls-tailscale")
    _require(_at(gateway, "terminal", "enabled") is False, "gateway-terminal-enabled")
    _require(_at(gateway, "reload", "mode") == "off", "service-can-reload-config")
    _require(_at(config, "commands", "restart") is False, "chat-restart-enabled")
    control_ui = _at(gateway, "controlUi")
    if deployment_mode != "production":
        _require(
            _at(config, "commands", "ownerAllowFrom") == [],
            "canary-command-route-present",
        )
        _require(
            control_ui == {"enabled": False},
            "canary-control-ui-enabled",
        )
    else:
        _require(bool(_at(config, "commands", "ownerAllowFrom")), "command-owner-empty")
        _require(control_ui.get("enabled") is True, "production-control-ui-disabled")
        _require(
            bool(control_ui.get("allowedOrigins")),
            "production-control-ui-origin-empty",
        )
    _require(_at(config, "logging", "level") == "info", "debug-logging-enabled")
    _require(_at(config, "update", "channel") == "stable", "unstable-update-channel")
    _require(
        _at(config, "update", "checkOnStart") is False, "service-self-update-probe"
    )
    _require(
        _at(config, "update", "auto", "enabled") is False, "service-self-update-enabled"
    )
    workshop = _at(config, "skills", "workshop")
    _require(
        _at(workshop, "autonomous", "enabled") is True,
        "self-evolution-capture-disabled",
    )
    _require(workshop.get("approvalPolicy") == "pending", "self-evolution-auto-apply")
    _require(
        workshop.get("allowSymlinkTargetWrites") is False,
        "skill-symlink-writes-enabled",
    )


def _audit_plugins(config: dict[str, Any], deployment_mode: str) -> None:
    plugins = _at(config, "plugins")
    _require("installs" not in plugins, "legacy-plugin-install-records-present")
    _require("load" not in plugins, "plugin-path-injection-present")
    entries = _at(plugins, "entries")
    if deployment_mode != "production":
        _require(
            plugins.get("allow") == BEHAVIOR_CANARY_PLUGINS,
            "canary-plugin-allowlist-mismatch",
        )
        _require("slots" not in plugins, "canary-plugin-slot-present")
        _require(
            sorted(entries) == sorted(BEHAVIOR_CANARY_PLUGINS),
            "canary-plugin-entry-mismatch",
        )
    else:
        _require(plugins.get("allow") == EXPECTED_PLUGINS, "plugin-allowlist-mismatch")
        _require(
            _at(plugins, "slots")
            == {"contextEngine": "lossless-claw", "memory": "openclaw-mem0"},
            "compatibility-plugin-slot-drift",
        )
        _require(sorted(entries) == sorted(EXPECTED_PLUGINS), "plugin-entry-mismatch")

    codex = _at(entries, "codex", "config", "appServer")
    _require(codex.get("mode") == "guardian", "codex-guardian-disabled")
    _require(codex.get("transport") == "websocket", "codex-not-process-separated")
    _require(codex.get("homeScope") == "agent", "codex-home-not-agent-scoped")
    _require(
        isinstance(codex.get("url"), str)
        and codex["url"].startswith("ws://127.0.0.1:"),
        "codex-app-server-not-loopback",
    )
    _require(_is_file_secret_ref(codex.get("authToken")), "codex-auth-not-secret-ref")
    _require(
        codex.get("remoteWorkspaceRoot")
        == _at(config, "agents", "defaults", "workspace"),
        "codex-remote-workspace-drift",
    )
    if deployment_mode == "behavior-canary":
        _require(codex.get("sandbox") == "read-only", "canary-codex-sandbox-drift")
    else:
        _require(codex.get("sandbox") == "workspace-write", "codex-sandbox-drift")
    expected_approval_policy = (
        "never" if deployment_mode == "security-canary" else "on-request"
    )
    _require(
        codex.get("approvalPolicy") == expected_approval_policy,
        "codex-approval-policy",
    )
    _require(codex.get("approvalsReviewer") == "auto_review", "codex-reviewer-policy")
    _require(codex.get("codeModeOnly") is True, "codex-code-mode-not-enforced")

    if deployment_mode != "production":
        return

    lossless = _at(entries, "lossless-claw")
    summary_model = _at(lossless, "config", "summaryModel")
    _require(
        summary_model.startswith("openai/"), "lossless-summary-provider-not-modernized"
    )
    _require(
        _at(lossless, "llm", "allowedModels") == [summary_model],
        "lossless-model-policy-drift",
    )
    _require(
        _at(lossless, "config", "databasePath").startswith("/var/lib/openclaw/"),
        "lossless-database-outside-service-state",
    )

    mem0 = _at(entries, "openclaw-mem0", "config")
    _require(mem0.get("mode") == "open-source", "mem0-not-open-source")
    _require(mem0.get("autoCapture") is False, "mem0-unreviewed-auto-capture")
    _require(
        _at(mem0, "oss", "embedder", "provider") == "gemini", "mem0-embedder-drift"
    )
    _require(
        _at(mem0, "oss", "llm", "provider") == "google", "mem0-llm-not-native-google"
    )
    _require(
        _at(mem0, "oss", "vectorStore", "provider") == "qdrant", "mem0-store-drift"
    )
    _require(
        _at(mem0, "oss", "historyDbPath").startswith("/var/lib/openclaw/"),
        "mem0-history-outside-service-state",
    )
    _require("anonymousTelemetryId" not in mem0, "mem0-telemetry-id-migrated")


def audit_config(
    config: dict[str, Any],
    heartbeat_mode: str = "production",
    deployment_mode: str = "production",
) -> dict[str, Any]:
    _require(isinstance(config, dict), "config-root-not-object")
    _require(
        heartbeat_mode in {"canary", "controlled-rigel", "production"},
        "unknown-heartbeat-audit-mode",
    )
    _require(
        deployment_mode in {"behavior-canary", "production", "security-canary"},
        "unknown-deployment-audit-mode",
    )
    if deployment_mode == "behavior-canary":
        _require(
            heartbeat_mode in {"canary", "controlled-rigel"},
            "behavior-canary-heartbeats-not-canary",
        )
        expected_top_level = CHANNEL_LESS_TOP_LEVEL
    elif deployment_mode == "security-canary":
        _require(
            heartbeat_mode == "canary",
            "security-canary-heartbeats-not-canary",
        )
        expected_top_level = CHANNEL_LESS_TOP_LEVEL
    else:
        _require(
            heartbeat_mode != "controlled-rigel",
            "controlled-rigel-outside-behavior-canary",
        )
        expected_top_level = EXPECTED_TOP_LEVEL
    _require(set(config) == expected_top_level, "top-level-config-drift")
    _walk(config)
    _audit_provider_auth_boundary(config)
    _audit_agents(config, heartbeat_mode, deployment_mode)
    _audit_tools(config, deployment_mode)
    if deployment_mode == "production":
        _audit_channels_and_bindings(config)
    _audit_gateway_and_control_plane(config, deployment_mode)
    _audit_plugins(config, deployment_mode)

    canonical = json.dumps(config, separators=(",", ":"), sort_keys=True).encode()
    return {
        "status": "ok",
        "agentCount": len(_at(config, "agents", "list")),
        "bindingCount": len(config.get("bindings", [])),
        "deploymentMode": deployment_mode,
        "heartbeatMode": heartbeat_mode,
        "pluginCount": len(_at(config, "plugins", "allow")),
        "sha256": hashlib.sha256(canonical).hexdigest(),
    }


def load_and_audit(
    path: Path,
    heartbeat_mode: str = "production",
    deployment_mode: str = "production",
) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        config = json.load(handle)
    return audit_config(config, heartbeat_mode, deployment_mode)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--heartbeat-mode",
        choices=("canary", "controlled-rigel", "production"),
        default="production",
    )
    parser.add_argument(
        "--deployment-mode",
        choices=("behavior-canary", "production", "security-canary"),
        default="production",
    )
    args = parser.parse_args()
    try:
        result = load_and_audit(
            args.config,
            heartbeat_mode=args.heartbeat_mode,
            deployment_mode=args.deployment_mode,
        )
    except (AuditError, json.JSONDecodeError, OSError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
