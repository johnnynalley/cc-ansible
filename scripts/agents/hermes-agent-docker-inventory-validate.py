#!/usr/bin/env python3
"""Validate Astra's root-managed native Docker access plugin."""

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

PLUGIN = "agent-docker-inventory"
EXPECTED_FILES = ("__init__.py", "plugin.yaml")
EXPECTED_ENABLED = ["star-dispatch-privacy", PLUGIN, "hermes-lcm"]
EXPECTED_REPORT_ENDPOINTS = {
    "192.168.1.153",
    "192.168.1.136",
    "192.168.1.78",
    "192.168.1.31",
}
EXPECTED_UPDATE_HOSTS = ["all", "docker-vm", "media-vm", "nextcloud-vm"]


class ValidationError(RuntimeError):
    """Fail-closed plugin validation error."""


def require(value: bool, message: str) -> None:
    if not value:
        raise ValidationError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_tree(root: Path) -> dict[str, str]:
    require(root.is_absolute(), "plugin-root-not-absolute")
    root_stat = os.lstat(root)
    require(stat.S_ISDIR(root_stat.st_mode), "plugin-root-not-directory")
    require(not stat.S_ISLNK(root_stat.st_mode), "plugin-root-symlink")
    require(root_stat.st_uid == 0, "plugin-root-owner")
    require(stat.S_IMODE(root_stat.st_mode) == 0o750, "plugin-root-mode")
    names = sorted(entry.name for entry in os.scandir(root))
    require(names == list(EXPECTED_FILES), "plugin-inventory-drift")
    result = {}
    for name in EXPECTED_FILES:
        path = root / name
        path_stat = os.lstat(path)
        require(stat.S_ISREG(path_stat.st_mode), f"plugin-file-kind:{name}")
        require(not stat.S_ISLNK(path_stat.st_mode), f"plugin-file-link:{name}")
        require(path_stat.st_uid == 0, f"plugin-file-owner:{name}")
        require(stat.S_IMODE(path_stat.st_mode) == 0o440, f"plugin-file-mode:{name}")
        result[name] = digest(path)
    return result


class ToolContext:
    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []
        self.hooks: list[str] = []

    def register_tool(self, **kwargs: Any) -> None:
        self.tools.append(kwargs)

    def register_hook(self, name: str, *_: Any, **__: Any) -> None:
        self.hooks.append(name)


def validate_plugin(runtime_root: Path) -> list[str]:
    spec = importlib.util.spec_from_file_location(
        "hermes_agent_docker_inventory", runtime_root / "__init__.py"
    )
    require(spec is not None and spec.loader is not None, "plugin-import-spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    context = ToolContext()
    module.register(context)
    require(context.hooks == ["pre_tool_call"], "plugin-hook-set-drift")
    require(len(context.tools) == 2, "plugin-tool-count-drift")
    require(
        [tool.get("name") for tool in context.tools]
        == ["docker_inventory", "docker_update"],
        "plugin-tool-order-drift",
    )
    tool = context.tools[0]
    require(tool.get("name") == "docker_inventory", "plugin-tool-name-drift")
    require(tool.get("toolset") == "agent_docker", "plugin-toolset-drift")
    require(callable(tool.get("handler")), "plugin-handler-missing")
    require(callable(tool.get("check_fn")), "plugin-check-missing")
    schema = tool.get("schema")
    require(isinstance(schema, dict), "plugin-schema-missing")
    parameters = schema.get("parameters")
    require(isinstance(parameters, dict), "plugin-parameters-missing")
    require(parameters.get("additionalProperties") is False, "plugin-schema-open")
    host = parameters.get("properties", {}).get("host", {})
    require(
        host.get("enum")
        == ["all", "docker-vm", "media-vm", "nextcloud-vm", "jn-t14s-lin"],
        "plugin-host-allowlist-drift",
    )
    update = context.tools[1]
    require(update.get("toolset") == "agent_docker", "update-toolset-drift")
    require(callable(update.get("handler")), "update-handler-missing")
    require(callable(update.get("check_fn")), "update-check-missing")
    update_schema = update.get("schema")
    require(isinstance(update_schema, dict), "update-schema-missing")
    update_parameters = update_schema.get("parameters")
    require(isinstance(update_parameters, dict), "update-parameters-missing")
    require(
        update_parameters.get("additionalProperties") is False,
        "update-schema-open",
    )
    update_properties = update_parameters.get("properties", {})
    require(
        update_properties.get("host", {}).get("enum") == EXPECTED_UPDATE_HOSTS,
        "update-host-allowlist-drift",
    )
    require(
        update_properties.get("action", {}).get("enum") == ["status", "run"],
        "update-action-allowlist-drift",
    )
    return [tool["name"], update["name"]]


def validate_config(path: Path) -> None:
    require(path.is_absolute() and path.is_file(), "config-missing")
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    require(isinstance(config, dict), "config-invalid")
    plugins = config.get("plugins")
    require(isinstance(plugins, dict), "plugins-config-missing")
    require(plugins.get("enabled") == EXPECTED_ENABLED, "plugin-set-or-order-drift")
    require(plugins.get("disabled") == [], "plugin-disabled-drift")
    toolsets = config.get("toolsets", [])
    require(isinstance(toolsets, list), "toolsets-config-invalid")
    for toolset in ("agent_docker", "terminal", "file", "code_execution", "cronjob"):
        require(toolset in toolsets, f"toolset-not-enabled:{toolset}")
    disabled = config.get("agent", {}).get("disabled_toolsets", [])
    require(isinstance(disabled, list), "disabled-toolsets-config-invalid")
    for toolset in ("computer_use", "discord_admin", "homeassistant"):
        require(toolset in disabled, f"restricted-toolset-enabled:{toolset}")
    for toolset in ("terminal", "file", "code_execution", "cronjob"):
        require(toolset not in disabled, f"native-toolset-disabled:{toolset}")
    terminal = config.get("terminal", {})
    require(terminal.get("backend") == "local", "terminal-backend-not-local")
    require(
        terminal.get("cwd")
        == "/var/lib/hermes/astra/.hermes/profiles/astra/imported-data",
        "terminal-cwd-drift",
    )
    deny = config.get("approvals", {}).get("deny", [])
    require(isinstance(deny, list), "approval-deny-config-invalid")
    for pattern in ("*sudo*", "*docker*", "*podman*", "*curl*|*sh*"):
        require(pattern in deny, f"approval-deny-missing:{pattern}")


def validate_known_hosts(path: Path) -> None:
    require(path.is_absolute(), "known-hosts-not-absolute")
    info = os.lstat(path)
    require(stat.S_ISREG(info.st_mode), "known-hosts-not-file")
    require(not stat.S_ISLNK(info.st_mode), "known-hosts-symlink")
    require(info.st_uid == 0, "known-hosts-owner")
    require(stat.S_IMODE(info.st_mode) == 0o440, "known-hosts-mode")
    lines = [line for line in path.read_text(encoding="ascii").splitlines() if line]
    require(len(lines) == 4, "known-hosts-count-drift")
    actual = set()
    for line in lines:
        parts = line.split()
        require(len(parts) == 3, "known-hosts-shape")
        require(parts[1] == "ssh-ed25519", "known-hosts-key-type")
        actual.add(parts[0])
    require(actual == EXPECTED_REPORT_ENDPOINTS, "known-hosts-host-drift")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--known-hosts", type=Path, required=True)
    args = parser.parse_args()
    try:
        source_hashes = validate_tree(args.source_root)
        runtime_hashes = validate_tree(args.runtime_root)
        require(source_hashes == runtime_hashes, "plugin-runtime-hash-drift")
        validate_config(args.config)
        validate_known_hosts(args.known_hosts)
        tools = validate_plugin(args.runtime_root)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"status": "ok", "plugin": PLUGIN, "tools": tools}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
