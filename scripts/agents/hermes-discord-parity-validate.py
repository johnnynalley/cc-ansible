#!/usr/bin/env python3
"""Validate Astra's root-managed Discord parity plugin and policy."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

import yaml

sys.dont_write_bytecode = True

PLUGIN = "discord-parity"
EXPECTED_FILES = ("__init__.py", "plugin.yaml")
SUPPORTED_PROFILES = ("astra", "dubble")
EXPECTED_GUILDS = {"astra": {"1209365945882251294"}, "dubble": {"1209365945882251294"}}
EXPECTED_CHANNELS = {
    "astra": {
        "1482585492330381343",
        "1482589440663617638",
        "1488752822466904256",
        "1501040629025865779",
        "1501040923042254970",
        "1501040923570606223",
    },
    "dubble": {"1483229851350728784"},
}
EXPECTED_ACTIONS = [
    "send_message", "edit_message", "add_reaction", "remove_reaction",
    "list_reactions", "create_poll", "search_messages", "list_threads",
    "thread_messages", "thread_reply", "channel_permissions", "emoji_list", "send_sticker",
    "role_info", "voice_status", "event_list", "event_create",
    "channel_create", "category_create", "channel_edit", "category_edit",
    "channel_delete", "category_delete", "channel_move", "thread_edit",
]


class ValidationError(RuntimeError):
    """Fail-closed validation error."""


def require(value: bool, message: str) -> None:
    if not value:
        raise ValidationError(message)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_tree(root: Path) -> dict[str, str]:
    info = os.lstat(root)
    require(root.is_absolute(), "plugin-root-not-absolute")
    require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode), "plugin-root-kind")
    require(info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o750, "plugin-root-authority")
    names = sorted(item.name for item in os.scandir(root))
    require(names == list(EXPECTED_FILES), "plugin-inventory-drift")
    result: dict[str, str] = {}
    for name in EXPECTED_FILES:
        path = root / name
        item = os.lstat(path)
        require(stat.S_ISREG(item.st_mode) and not stat.S_ISLNK(item.st_mode), f"plugin-file-kind:{name}")
        require(item.st_uid == 0 and stat.S_IMODE(item.st_mode) == 0o440, f"plugin-file-authority:{name}")
        result[name] = _hash(path)
    return result


class Context:
    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []

    def register_tool(self, **kwargs: Any) -> None:
        self.tools.append(kwargs)


def validate_plugin(root: Path) -> None:
    spec = importlib.util.spec_from_file_location("hermes_discord_parity", root / "__init__.py")
    require(spec is not None and spec.loader is not None, "plugin-import-spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    context = Context()
    module.register(context)
    require(len(context.tools) == 1, "plugin-tool-count")
    tool = context.tools[0]
    require(tool.get("name") == "discord_parity", "plugin-tool-name")
    require(tool.get("toolset") == "discord_parity", "plugin-toolset")
    require(callable(tool.get("handler")) and callable(tool.get("check_fn")), "plugin-callables")
    parameters = tool.get("schema", {}).get("parameters", {})
    require(parameters.get("additionalProperties") is False, "plugin-schema-open")
    require(parameters.get("required") == ["action"], "plugin-required-drift")
    require(parameters.get("properties", {}).get("action", {}).get("enum") == EXPECTED_ACTIONS, "plugin-actions-drift")


def validate_config(path: Path, profile: str) -> None:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    require(isinstance(config, dict), "config-invalid")
    enabled = config.get("plugins", {}).get("enabled")
    require(
        isinstance(enabled, list)
        and all(isinstance(item, str) for item in enabled)
        and len(enabled) == len(set(enabled))
        and PLUGIN in enabled,
        "plugin-enable-state-drift",
    )
    require("discord_parity" in config.get("toolsets", []), "toolset-disabled")
    require("discord_parity" not in config.get("agent", {}).get("disabled_toolsets", []), "toolset-denied")


def validate_policy(path: Path, profile: str) -> None:
    info = os.lstat(path)
    require(path.is_absolute() and stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode), "policy-kind")
    require(info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o440, "policy-authority")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(value.get("schemaVersion") == 1, "policy-schema")
    require(set(value.get("guilds", [])) == EXPECTED_GUILDS[profile], "policy-guilds")
    require(set(value.get("channels", [])) == EXPECTED_CHANNELS[profile], "policy-channels")
    expected_roots = ["/tmp", "/var/lib/hermes/astra/.hermes/profiles/astra"] if profile == "astra" else []
    require(value.get("fileRoots") == expected_roots, "policy-file-roots")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--profile", choices=SUPPORTED_PROFILES, required=True)
    args = parser.parse_args()
    try:
        require(validate_tree(args.source_root) == validate_tree(args.runtime_root), "plugin-runtime-hash-drift")
        validate_plugin(args.runtime_root)
        validate_config(args.config, args.profile)
        validate_policy(args.policy, args.profile)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"status": "ok", "plugin": PLUGIN, "actions": EXPECTED_ACTIONS}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
