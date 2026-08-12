#!/usr/bin/python3
"""Emit a redacted migration inventory from an OpenClaw configuration."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
SAFE_LABEL_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:/-]{0,127}$")
SAFE_MODEL_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")
SECRET_KEY_TOKENS = {
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
}
EXPECTED_TOP_LEVEL = {
    "agents",
    "auth",
    "bindings",
    "channels",
    "commands",
    "cron",
    "env",
    "gateway",
    "hooks",
    "logging",
    "memory",
    "messages",
    "meta",
    "models",
    "plugins",
    "session",
    "skills",
    "tools",
    "update",
    "wizard",
}
EXPECTED_AGENT_KEYS = {
    "default",
    "heartbeat",
    "id",
    "identity",
    "memorySearch",
    "model",
    "models",
    "name",
    "subagents",
    "thinkingDefault",
    "tools",
    "workspace",
}
EXPECTED_HEARTBEAT_KEYS = {
    "accountId",
    "activeHours",
    "directPolicy",
    "every",
    "includeReasoning",
    "isolatedSession",
    "lightContext",
    "skipWhenBusy",
    "suppressToolErrorWarnings",
    "target",
    "to",
}
EXPECTED_BINDING_KEYS = {"agentId", "match"}
EXPECTED_BINDING_MATCH_KEYS = {"accountId", "channel", "guildId", "peer"}
KNOWN_ROOTS = (
    (Path("/home/johnny/.openclaw/workspace"), "$LEGACY_WORKSPACE"),
    (Path("/opt/cc-ansible"), "$REPO"),
)


class InventoryError(Exception):
    """Raised when the source config does not match the expected contract."""


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def safe_label(value: Any) -> str | None:
    if not isinstance(value, str) or not SAFE_LABEL_RE.fullmatch(value):
        return None
    return value


def safe_model(value: Any) -> str | None:
    if not isinstance(value, str) or not SAFE_MODEL_RE.fullmatch(value):
        return None
    return value


def redacted_label(value: Any) -> str | None:
    label = safe_label(value)
    return label if label is not None else None


def normalized_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value.startswith("/") or "\x00" in value:
        return None
    path = Path(value)
    for root, label in KNOWN_ROOTS:
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        return label if not relative.parts else f"{label}/{relative.as_posix()}"
    return f"$OTHER/{fingerprint(value)}"


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise InventoryError(f"invalid-{label}")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise InventoryError(f"invalid-{label}")
    return value


def safe_key_names(value: dict[str, Any]) -> list[str]:
    return sorted(
        (
            label
            if (label := safe_label(key)) is not None
            else f"opaque:{fingerprint(key)}"
        )
        for key in value
    )


def credential_kind(value: Any) -> str:
    if value is None:
        return "absent"
    if isinstance(value, str):
        return "plaintext"
    if isinstance(value, dict):
        source = value.get("source")
        if source in {"env", "exec", "file"}:
            return f"secret-ref:{source}"
        return "structured-unknown"
    return f"unexpected:{type(value).__name__}"


def secret_key(value: str) -> bool:
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    tokens = [token.lower() for token in re.split(r"[^a-zA-Z0-9]+", separated) if token]
    if any(token in SECRET_KEY_TOKENS for token in tokens):
        return True
    pairs = set(zip(tokens, tokens[1:]))
    return bool({("access", "token"), ("api", "key"), ("secret", "key")} & pairs)


def credential_surface_counts(value: Any) -> dict[str, int]:
    counts: Counter[str] = Counter()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if isinstance(key, str) and secret_key(key):
                    counts[credential_kind(child)] += 1
                else:
                    walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return dict(sorted(counts.items()))


def safe_string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    items = require_list(value, label)
    result: list[str] = []
    for item in items:
        safe = safe_label(item)
        if safe is None:
            raise InventoryError(f"invalid-{label}")
        result.append(safe)
    return sorted(set(result))


def model_policy(value: Any) -> dict[str, Any]:
    if value is None:
        return {"primary": None, "fallbacks": []}
    model = require_mapping(value, "model-policy")
    primary = safe_model(model.get("primary"))
    fallbacks_raw = model.get("fallbacks", [])
    fallbacks = require_list(fallbacks_raw, "model-fallbacks")
    if any(safe_model(item) is None for item in fallbacks):
        raise InventoryError("invalid-model-fallbacks")
    return {
        "primary": primary,
        "fallbacks": sorted(set(fallbacks)),
        "unknownKeys": sorted(set(model) - {"fallbacks", "primary"}),
    }


def model_catalog(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    catalog = require_mapping(value, "model-catalog")
    result: list[dict[str, Any]] = []
    for model_ref, settings_raw in sorted(catalog.items()):
        if safe_model(model_ref) is None:
            raise InventoryError("invalid-model-catalog-reference")
        settings = require_mapping(settings_raw, "model-catalog-entry")
        runtime_raw = settings.get("agentRuntime")
        runtime = (
            require_mapping(runtime_raw, "agent-runtime")
            if runtime_raw is not None
            else {}
        )
        result.append(
            {
                "model": model_ref,
                "agentRuntime": redacted_label(runtime.get("id")),
                "settingKeys": safe_key_names(settings),
            }
        )
    return result


def heartbeat_inventory(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    heartbeat = require_mapping(value, "heartbeat")
    active_hours_raw = heartbeat.get("activeHours")
    active_hours = (
        require_mapping(active_hours_raw, "heartbeat-active-hours")
        if active_hours_raw is not None
        else {}
    )
    return {
        "every": redacted_label(heartbeat.get("every")),
        "target": redacted_label(heartbeat.get("target")),
        "directPolicy": redacted_label(heartbeat.get("directPolicy")),
        "includeReasoning": (
            heartbeat.get("includeReasoning")
            if isinstance(heartbeat.get("includeReasoning"), bool)
            else None
        ),
        "isolatedSession": (
            heartbeat.get("isolatedSession")
            if isinstance(heartbeat.get("isolatedSession"), bool)
            else None
        ),
        "lightContext": (
            heartbeat.get("lightContext")
            if isinstance(heartbeat.get("lightContext"), bool)
            else None
        ),
        "skipWhenBusy": (
            heartbeat.get("skipWhenBusy")
            if isinstance(heartbeat.get("skipWhenBusy"), bool)
            else None
        ),
        "suppressToolErrorWarnings": (
            heartbeat.get("suppressToolErrorWarnings")
            if isinstance(heartbeat.get("suppressToolErrorWarnings"), bool)
            else None
        ),
        "hasRecipient": bool(heartbeat.get("to")),
        "hasAccount": bool(heartbeat.get("accountId")),
        "activeHours": {
            "configured": bool(active_hours),
            "keys": safe_key_names(active_hours),
        },
        "unknownKeys": sorted(set(heartbeat) - EXPECTED_HEARTBEAT_KEYS),
    }


def tool_policy(value: Any) -> dict[str, Any]:
    if value is None:
        return {"profile": None, "allow": [], "deny": [], "unknownKeys": []}
    tools = require_mapping(value, "agent-tools")
    return {
        "profile": redacted_label(tools.get("profile")),
        "allow": safe_string_list(tools.get("allow"), "agent-tools-allow"),
        "deny": safe_string_list(tools.get("deny"), "agent-tools-deny"),
        "unknownKeys": sorted(set(tools) - {"allow", "deny", "profile"}),
    }


def memory_search(value: Any) -> dict[str, Any]:
    if value is None:
        return {"configured": False}
    settings = require_mapping(value, "memory-search")
    return {
        "configured": True,
        "enabled": (
            settings.get("enabled")
            if isinstance(settings.get("enabled"), bool)
            else None
        ),
        "provider": redacted_label(settings.get("provider")),
        "keys": safe_key_names(settings),
    }


def optional_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def subagent_policy(value: Any) -> dict[str, Any]:
    settings = require_mapping(value or {}, "subagents")
    known_keys = {
        "allowAgents",
        "archiveAfterMinutes",
        "delegationMode",
        "maxConcurrent",
        "model",
        "runTimeoutSeconds",
        "thinking",
    }
    return {
        "allowAgents": safe_string_list(
            settings.get("allowAgents"), "subagent-allow-agents"
        ),
        "model": model_policy(settings.get("model")),
        "thinking": redacted_label(settings.get("thinking")),
        "delegationMode": redacted_label(settings.get("delegationMode")),
        "maxConcurrent": optional_nonnegative_int(settings.get("maxConcurrent")),
        "runTimeoutSeconds": optional_nonnegative_int(
            settings.get("runTimeoutSeconds")
        ),
        "archiveAfterMinutes": optional_nonnegative_int(
            settings.get("archiveAfterMinutes")
        ),
        "keys": safe_key_names(settings),
        "unknownKeys": sorted(set(settings) - known_keys),
    }


def agent_inventory(value: Any) -> dict[str, Any]:
    agent = require_mapping(value, "agent-entry")
    agent_id = safe_label(agent.get("id"))
    if agent_id is None:
        raise InventoryError("invalid-agent-id")
    return {
        "id": agent_id,
        "default": bool(agent.get("default")),
        "hasName": isinstance(agent.get("name"), str) and bool(agent.get("name")),
        "hasIdentity": isinstance(agent.get("identity"), dict)
        and bool(agent.get("identity")),
        "workspace": normalized_path(agent.get("workspace")),
        "model": model_policy(agent.get("model")),
        "modelCatalog": model_catalog(agent.get("models")),
        "thinkingDefault": redacted_label(agent.get("thinkingDefault")),
        "memorySearch": memory_search(agent.get("memorySearch")),
        "tools": tool_policy(agent.get("tools")),
        "subagents": subagent_policy(agent.get("subagents")),
        "heartbeat": heartbeat_inventory(agent.get("heartbeat")),
        "unknownKeys": sorted(set(agent) - EXPECTED_AGENT_KEYS),
    }


def binding_inventory(value: Any, discord_account_names: set[str]) -> dict[str, Any]:
    binding = require_mapping(value, "binding")
    match = require_mapping(binding.get("match"), "binding-match")
    account = match.get("accountId")
    return {
        "agentId": redacted_label(binding.get("agentId")),
        "channel": redacted_label(match.get("channel")),
        "account": account if account in discord_account_names else None,
        "hasOpaqueAccount": bool(account) and account not in discord_account_names,
        "hasGuild": bool(match.get("guildId")),
        "hasPeer": isinstance(match.get("peer"), dict) and bool(match.get("peer")),
        "peerKeys": (
            safe_key_names(match.get("peer", {}))
            if isinstance(match.get("peer"), dict)
            else []
        ),
        "unknownKeys": sorted(set(binding) - EXPECTED_BINDING_KEYS),
        "unknownMatchKeys": sorted(set(match) - EXPECTED_BINDING_MATCH_KEYS),
    }


def discord_account_inventory(name: str, value: Any) -> dict[str, Any]:
    account = require_mapping(value, "discord-account")
    allow_from = account.get("allowFrom", [])
    guilds = account.get("guilds", {})
    return {
        "name": name,
        "token": credential_kind(account.get("token")),
        "allowFromCount": len(require_list(allow_from, "discord-allow-from")),
        "guildCount": len(require_mapping(guilds, "discord-guilds")),
        "dmPolicy": redacted_label(account.get("dmPolicy")),
        "groupPolicy": redacted_label(account.get("groupPolicy")),
        "streaming": redacted_label(account.get("streaming")),
        "execApprovalsEnabled": bool(
            require_mapping(
                account.get("execApprovals", {}), "discord-exec-approvals"
            ).get("enabled")
        ),
        "credentialSurfaces": credential_surface_counts(account),
        "keys": safe_key_names(account),
    }


def discord_inventory(value: Any) -> dict[str, Any]:
    discord = require_mapping(value, "discord")
    accounts = require_mapping(discord.get("accounts", {}), "discord-accounts")
    account_names: set[str] = set()
    account_rows: list[dict[str, Any]] = []
    for name, account in sorted(accounts.items()):
        safe_name = safe_label(name)
        if safe_name is None:
            raise InventoryError("invalid-discord-account-name")
        account_names.add(safe_name)
        account_rows.append(discord_account_inventory(safe_name, account))
    return {
        "enabled": bool(discord.get("enabled")),
        "token": credential_kind(discord.get("token")),
        "allowFromCount": len(
            require_list(discord.get("allowFrom", []), "discord-allow-from")
        ),
        "guildCount": len(require_mapping(discord.get("guilds", {}), "discord-guilds")),
        "dmPolicy": redacted_label(discord.get("dmPolicy")),
        "groupPolicy": redacted_label(discord.get("groupPolicy")),
        "streaming": redacted_label(discord.get("streaming")),
        "accounts": account_rows,
        "accountNames": sorted(account_names),
        "credentialSurfaces": credential_surface_counts(discord),
        "keys": safe_key_names(discord),
    }


def plugin_inventory(value: Any) -> dict[str, Any]:
    plugins = require_mapping(value, "plugins")
    entries = require_mapping(plugins.get("entries", {}), "plugin-entries")
    rows: list[dict[str, Any]] = []
    for plugin_id, entry_raw in sorted(entries.items()):
        safe_id = safe_label(plugin_id)
        if safe_id is None:
            raise InventoryError("invalid-plugin-id")
        entry = require_mapping(entry_raw, "plugin-entry")
        rows.append(
            {
                "id": safe_id,
                "enabled": bool(entry.get("enabled")),
                "keys": safe_key_names(entry),
                "credentialSurfaces": credential_surface_counts(entry),
            }
        )
    slots = require_mapping(plugins.get("slots", {}), "plugin-slots")
    return {
        "allow": safe_string_list(plugins.get("allow"), "plugin-allow"),
        "entries": rows,
        "slots": {
            safe_label(slot) or f"opaque:{fingerprint(slot)}": redacted_label(owner)
            for slot, owner in sorted(slots.items())
        },
        "credentialSurfaces": credential_surface_counts(plugins),
        "keys": safe_key_names(plugins),
    }


def hooks_inventory(value: Any) -> dict[str, Any]:
    hooks = require_mapping(value, "hooks")
    internal = require_mapping(hooks.get("internal", {}), "internal-hooks")
    entries = require_mapping(internal.get("entries", {}), "internal-hook-entries")
    rows = []
    for hook_id, entry_raw in sorted(entries.items()):
        safe_id = safe_label(hook_id)
        if safe_id is None:
            raise InventoryError("invalid-hook-id")
        entry = require_mapping(entry_raw, "internal-hook-entry")
        rows.append(
            {
                "id": safe_id,
                "enabled": bool(entry.get("enabled")),
                "keys": safe_key_names(entry),
                "credentialSurfaces": credential_surface_counts(entry),
            }
        )
    return {
        "internalEnabled": bool(internal.get("enabled")),
        "internalEntries": rows,
        "keys": safe_key_names(hooks),
    }


def gateway_inventory(value: Any) -> dict[str, Any]:
    gateway = require_mapping(value, "gateway")
    auth = require_mapping(gateway.get("auth", {}), "gateway-auth")
    tailscale = require_mapping(gateway.get("tailscale", {}), "gateway-tailscale")
    trusted_proxies = gateway.get("trustedProxies", [])
    return {
        "mode": redacted_label(gateway.get("mode")),
        "bind": redacted_label(gateway.get("bind")),
        "port": gateway.get("port") if isinstance(gateway.get("port"), int) else None,
        "authMode": redacted_label(auth.get("mode")),
        "authCredential": credential_kind(
            auth.get("token") if "token" in auth else auth.get("password")
        ),
        "allowTailscale": (
            auth.get("allowTailscale")
            if isinstance(auth.get("allowTailscale"), bool)
            else None
        ),
        "tailscaleMode": redacted_label(tailscale.get("mode")),
        "tailscaleServiceName": redacted_label(tailscale.get("serviceName")),
        "trustedProxyCount": len(
            require_list(trusted_proxies, "gateway-trusted-proxies")
        ),
        "controlUiKeys": safe_key_names(
            require_mapping(gateway.get("controlUi", {}), "gateway-control-ui")
        ),
        "credentialSurfaces": credential_surface_counts(gateway),
        "keys": safe_key_names(gateway),
    }


def auth_inventory(value: Any) -> dict[str, Any]:
    auth = require_mapping(value, "auth")
    profiles = require_mapping(auth.get("profiles", {}), "auth-profiles")
    counts: Counter[tuple[str, str]] = Counter()
    for profile_name, profile_raw in profiles.items():
        if not isinstance(profile_name, str):
            raise InventoryError("invalid-auth-profile-name")
        profile = require_mapping(profile_raw, "auth-profile")
        provider = safe_label(profile.get("provider"))
        mode = safe_label(profile.get("mode"))
        if provider is None or mode is None:
            raise InventoryError("invalid-auth-profile")
        counts[(provider, mode)] += 1
    order = require_mapping(auth.get("order", {}), "auth-order")
    order_rows = []
    for provider, profile_names in sorted(order.items()):
        safe_provider = safe_label(provider)
        if safe_provider is None:
            raise InventoryError("invalid-auth-order-provider")
        order_rows.append(
            {
                "provider": safe_provider,
                "profileCount": len(
                    require_list(profile_names, "auth-order-profile-list")
                ),
            }
        )
    return {
        "profiles": [
            {"provider": provider, "mode": mode, "count": count}
            for (provider, mode), count in sorted(counts.items())
        ],
        "order": order_rows,
        "credentialSurfaces": credential_surface_counts(auth),
        "keys": safe_key_names(auth),
    }


def models_inventory(value: Any) -> dict[str, Any]:
    models = require_mapping(value, "models")
    providers = require_mapping(models.get("providers", {}), "model-providers")
    rows = []
    for provider_id, provider_raw in sorted(providers.items()):
        safe_provider = safe_label(provider_id)
        if safe_provider is None:
            raise InventoryError("invalid-model-provider-id")
        provider = require_mapping(provider_raw, "model-provider")
        catalog = require_list(provider.get("models", []), "provider-model-list")
        model_ids = []
        for entry_raw in catalog:
            entry = require_mapping(entry_raw, "provider-model-entry")
            model_id = safe_model(entry.get("id"))
            if model_id is None:
                raise InventoryError("invalid-provider-model-id")
            model_ids.append(model_id)
        rows.append(
            {
                "id": safe_provider,
                "api": redacted_label(provider.get("api")),
                "hasBaseUrl": isinstance(provider.get("baseUrl"), str)
                and bool(provider.get("baseUrl")),
                "modelIds": sorted(set(model_ids)),
                "keys": safe_key_names(provider),
                "credentialSurfaces": credential_surface_counts(provider),
            }
        )
    return {
        "providers": rows,
        "credentialSurfaces": credential_surface_counts(models),
        "keys": safe_key_names(models),
    }


def inventory_config(path: Path) -> dict[str, Any]:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise InventoryError("config-not-regular-file")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InventoryError("invalid-config-json") from exc
    config = require_mapping(config, "config-root")
    agents = require_mapping(config.get("agents"), "agents")
    agent_rows = [
        agent_inventory(item) for item in require_list(agents.get("list"), "agent-list")
    ]
    agent_ids = [row["id"] for row in agent_rows]
    if len(agent_ids) != len(set(agent_ids)):
        raise InventoryError("duplicate-agent-id")
    channels = require_mapping(config.get("channels"), "channels")
    discord = discord_inventory(channels.get("discord"))
    bindings = [
        binding_inventory(item, set(discord["accountNames"]))
        for item in require_list(config.get("bindings"), "bindings")
    ]
    defaults = require_mapping(agents.get("defaults", {}), "agent-defaults")
    root_credentials = {
        key: credential_surface_counts(value)
        for key, value in sorted(config.items())
        if credential_surface_counts(value)
    }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "configMode": f"{stat.S_IMODE(metadata.st_mode):04o}",
        "topLevelKeys": safe_key_names(config),
        "unclassifiedTopLevelKeys": sorted(set(config) - EXPECTED_TOP_LEVEL),
        "summary": {
            "agentCount": len(agent_rows),
            "bindingCount": len(bindings),
            "channelCount": len(channels),
            "pluginEntryCount": len(
                require_mapping(
                    require_mapping(config.get("plugins"), "plugins").get(
                        "entries", {}
                    ),
                    "plugin-entries",
                )
            ),
        },
        "agentDefaults": {
            "model": model_policy(defaults.get("model")),
            "heartbeat": heartbeat_inventory(defaults.get("heartbeat")),
            "memorySearch": memory_search(defaults.get("memorySearch")),
            "subagents": subagent_policy(defaults.get("subagents")),
            "keys": safe_key_names(defaults),
        },
        "agents": agent_rows,
        "bindings": bindings,
        "channels": {"discord": discord},
        "auth": auth_inventory(config.get("auth", {})),
        "models": models_inventory(config.get("models", {})),
        "plugins": plugin_inventory(config.get("plugins")),
        "hooks": hooks_inventory(config.get("hooks", {})),
        "gateway": gateway_inventory(config.get("gateway")),
        "credentialSurfacesByRoot": root_credentials,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = inventory_config(args.config)
    except (InventoryError, OSError):
        result = {
            "schemaVersion": SCHEMA_VERSION,
            "status": "error",
            "errorCode": "inventory-failed",
        }
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
