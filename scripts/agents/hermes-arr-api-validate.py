#!/usr/bin/env python3
"""Validate Astra's root-managed Arr API plugin and broker socket."""

from __future__ import annotations

import argparse
import grp
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
EXPECTED_FILES = {"__init__.py", "plugin.yaml"}


class ValidationError(RuntimeError):
    pass


class Context:
    def __init__(self) -> None:
        self.hooks: list[tuple[str, Any]] = []
        self.tools: list[dict[str, Any]] = []

    def register_hook(self, name: str, callback: Any) -> None:
        self.hooks.append((name, callback))

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
    path = root / "__init__.py"
    spec = importlib.util.spec_from_file_location("validated_arr_api", path)
    require(spec is not None and spec.loader is not None, "plugin-import-failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_plugin(root: Path) -> list[str]:
    metadata = yaml.safe_load((root / "plugin.yaml").read_text(encoding="utf-8"))
    require(
        isinstance(metadata, dict)
        and metadata.get("name") == "arr-api"
        and metadata.get("version") == "1.1.0"
        and metadata.get("module") == "__init__",
        "plugin-metadata-drift",
    )
    module = load_plugin(root)
    context = Context()
    module.register(context)
    names = [item.get("name") for item in context.tools]
    require(
        names
        == [
            "arr_services",
            "arr_api_request",
            "prowlarr_indexer_schema",
            "prowlarr_indexer_apply",
        ],
        "plugin-tool-drift",
    )
    require({item.get("toolset") for item in context.tools} == {"arr_api"}, "plugin-toolset-drift")
    require([name for name, _ in context.hooks] == ["pre_tool_call"], "plugin-hook-drift")
    return names


def validate_config(path: Path) -> None:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), "config-invalid")
    plugins = value.get("plugins", {}).get("enabled", [])
    toolsets = value.get("toolsets", [])
    require(isinstance(plugins, list) and "arr-api" in plugins, "plugin-not-enabled")
    require(isinstance(toolsets, list) and "arr_api" in toolsets, "toolset-not-enabled")


def validate_socket(path: Path, group_name: str) -> None:
    info = os.lstat(path)
    expected_gid = grp.getgrnam(group_name).gr_gid
    require(stat.S_ISSOCK(info.st_mode) and not stat.S_ISLNK(info.st_mode), "broker-socket-shape")
    require(info.st_gid == expected_gid, "broker-socket-group")
    require(stat.S_IMODE(info.st_mode) == 0o660, "broker-socket-mode")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--socket", type=Path, default=Path("/run/hermes-arr-api/broker.sock"))
    parser.add_argument("--socket-group", default="hermes-arr-api")
    args = parser.parse_args()
    try:
        source_hashes = validate_tree(args.source_root)
        runtime_hashes = validate_tree(args.runtime_root)
        require(source_hashes == runtime_hashes, "plugin-runtime-hash-drift")
        tools = validate_plugin(args.runtime_root)
        validate_config(args.config)
        validate_socket(args.socket, args.socket_group)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"status": "ok", "plugin": "arr-api", "tools": tools}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
