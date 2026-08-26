#!/usr/bin/env python3
"""Validate Astra's owner-only fleet administration boundary."""

from __future__ import annotations

import argparse
import grp
import hashlib
import importlib.util
import json
import os
import pwd
import socket
import stat
import sys
from pathlib import Path
from typing import Any

import yaml

sys.dont_write_bytecode = True
EXPECTED_FILES = {"__init__.py", "plugin.yaml"}
EXPECTED_TOOL = "fleet_agent_admin"
EXPECTED_TOOLSET = "fleet_admin"
EXPECTED_ENV_KEY = "GATEWAY_RELAY_FLEET_ADMIN_KEY"


class ValidationError(RuntimeError):
    pass


class Context:
    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []

    def register_tool(self, **kwargs: Any) -> None:
        self.tools.append(kwargs)


def require(value: bool, code: str) -> None:
    if not value:
        raise ValidationError(code)


def validate_tree(root: Path) -> dict[str, str]:
    info = os.lstat(root)
    require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode), "plugin-root-shape")
    names = {item.name for item in root.iterdir()}
    require(names == EXPECTED_FILES, "plugin-inventory-drift")
    hashes: dict[str, str] = {}
    for name in sorted(names):
        path = root / name
        item = os.lstat(path)
        require(stat.S_ISREG(item.st_mode) and not stat.S_ISLNK(item.st_mode), "plugin-file-shape")
        require(item.st_uid == 0, "plugin-owner-drift")
        require(stat.S_IMODE(item.st_mode) == 0o440, "plugin-mode-drift")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def load_plugin(root: Path):
    spec = importlib.util.spec_from_file_location("validated_fleet_admin", root / "__init__.py")
    require(spec is not None and spec.loader is not None, "plugin-import-failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_plugin(root: Path) -> Any:
    metadata = yaml.safe_load((root / "plugin.yaml").read_text(encoding="utf-8"))
    require(
        isinstance(metadata, dict)
        and metadata.get("name") == "fleet-admin"
        and metadata.get("version") == "1.0.0"
        and metadata.get("module") == "__init__",
        "plugin-metadata-drift",
    )
    module = load_plugin(root)
    context = Context()
    module.register(context)
    require([item.get("name") for item in context.tools] == [EXPECTED_TOOL], "plugin-tool-drift")
    require({item.get("toolset") for item in context.tools} == {EXPECTED_TOOLSET}, "plugin-toolset-drift")
    return module


def validate_config(path: Path) -> None:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), "config-invalid")
    plugins = value.get("plugins", {}).get("enabled", [])
    toolsets = value.get("toolsets", [])
    require(isinstance(plugins, list) and "fleet-admin" in plugins, "plugin-not-enabled")
    require(isinstance(toolsets, list) and EXPECTED_TOOLSET in toolsets, "toolset-not-enabled")


def validate_policy(path: Path, module: Any) -> None:
    module.POLICY = path
    module._load_policy()


def validate_socket(path: Path, group_name: str) -> None:
    parent = os.lstat(path.parent)
    require(stat.S_ISDIR(parent.st_mode) and not stat.S_ISLNK(parent.st_mode), "broker-runtime-shape")
    require(parent.st_uid == 0, "broker-runtime-owner")
    require(parent.st_gid == grp.getgrnam(group_name).gr_gid, "broker-runtime-group")
    require(stat.S_IMODE(parent.st_mode) == 0o750, "broker-runtime-mode")
    info = os.lstat(path)
    require(stat.S_ISSOCK(info.st_mode) and not stat.S_ISLNK(info.st_mode), "broker-socket-shape")
    require(info.st_uid == 0, "broker-socket-owner")
    require(info.st_gid == grp.getgrnam(group_name).gr_gid, "broker-socket-group")
    require(stat.S_IMODE(info.st_mode) == 0o660, "broker-socket-mode")


def validate_environment(path: Path) -> None:
    info = os.lstat(path)
    require(stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode), "environment-shape")
    require(info.st_uid == 0 and info.st_gid == 0, "environment-owner")
    require(stat.S_IMODE(info.st_mode) == 0o400, "environment-mode")
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    require(len(lines) == 1 and lines[0].startswith(EXPECTED_ENV_KEY + "="), "environment-content")
    require(32 <= len(lines[0].split("=", 1)[1]) <= 256, "environment-key-length")


def validate_state_db(path: Path, user_name: str) -> None:
    info = os.lstat(path)
    require(stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode), "state-db-shape")
    require(info.st_uid == pwd.getpwnam(user_name).pw_uid, "state-db-owner")
    require(not stat.S_IMODE(info.st_mode) & 0o022, "state-db-mode")


def validate_secret_sanitizer() -> None:
    from tools.environments.local import _is_hermes_internal_secret, build_subprocess_env

    marker = "fleet-admin-sanitizer-canary"
    require(_is_hermes_internal_secret(EXPECTED_ENV_KEY), "fleet-key-not-internal")
    sanitized = build_subprocess_env(base={EXPECTED_ENV_KEY: marker})
    require(EXPECTED_ENV_KEY not in sanitized and marker not in sanitized.values(), "fleet-key-not-scrubbed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--socket-group", required=True)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--state-db", type=Path, required=True)
    args = parser.parse_args()
    try:
        source_hashes = validate_tree(args.source_root)
        runtime_hashes = validate_tree(args.runtime_root)
        require(source_hashes == runtime_hashes, "plugin-runtime-hash-drift")
        module = validate_plugin(args.runtime_root)
        validate_config(args.config)
        validate_policy(args.policy, module)
        validate_socket(args.socket, args.socket_group)
        validate_environment(args.environment)
        validate_state_db(args.state_db, "hermes-astra")
        validate_secret_sanitizer()
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"status": "ok", "plugin": "fleet-admin", "tool": EXPECTED_TOOL}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
