#!/usr/bin/env python3
"""Validate Astra's root-managed host administration plugin and endpoint set."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import sys
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import yaml

sys.dont_write_bytecode = True
EXPECTED_FILES = {"__init__.py", "plugin.yaml"}


class ValidationError(RuntimeError):
    pass


def require(value: bool, code: str) -> None:
    if not value:
        raise ValidationError(code)


def validate_tree(root: Path) -> dict[str, str]:
    info = os.lstat(root)
    require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode), "plugin-root-shape")
    require(info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o750, "plugin-root-authority")
    names = {item.name for item in root.iterdir()}
    require(names == EXPECTED_FILES, "plugin-inventory-drift")
    result: dict[str, str] = {}
    for name in sorted(names):
        path = root / name
        item = os.lstat(path)
        require(stat.S_ISREG(item.st_mode) and not stat.S_ISLNK(item.st_mode), "plugin-file-shape")
        require(item.st_uid == 0 and stat.S_IMODE(item.st_mode) == 0o440, "plugin-file-authority")
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


class Context:
    def __init__(self) -> None:
        self.hooks: list[tuple[str, Any]] = []
        self.tools: list[dict[str, Any]] = []

    def register_hook(self, name: str, callback: Any) -> None:
        self.hooks.append((name, callback))

    def register_tool(self, **kwargs: Any) -> None:
        self.tools.append(kwargs)


def validate_plugin(root: Path) -> list[str]:
    metadata = yaml.safe_load((root / "plugin.yaml").read_text(encoding="utf-8"))
    require(isinstance(metadata, dict) and metadata.get("name") == "host-admin" and metadata.get("version") == "1.0.0" and metadata.get("module") == "__init__", "plugin-metadata-drift")
    spec = importlib.util.spec_from_file_location("validated_host_admin", root / "__init__.py")
    require(spec is not None and spec.loader is not None, "plugin-import-failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    context = Context()
    module.register(context)
    names = [item.get("name") for item in context.tools]
    require(names == ["host_admin_hosts", "host_admin_request"], "plugin-tool-drift")
    require({item.get("toolset") for item in context.tools} == {"host_admin"}, "plugin-toolset-drift")
    require([item[0] for item in context.hooks] == ["pre_tool_call"], "plugin-hook-drift")
    return names


def validate_config(path: Path) -> None:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), "config-invalid")
    enabled = value.get("plugins", {}).get("enabled")
    require(isinstance(enabled, list) and "host-admin" in enabled and len(enabled) == len(set(enabled)), "plugin-not-enabled")
    require("host_admin" in value.get("toolsets", []), "toolset-not-enabled")
    require("host_admin" not in value.get("agent", {}).get("disabled_toolsets", []), "toolset-disabled")


def validate_endpoints(path: Path) -> dict[str, str]:
    info = os.lstat(path)
    require(stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode), "endpoint-shape")
    require(info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o440, "endpoint-authority")
    value = json.loads(path.read_text(encoding="ascii"))
    require(isinstance(value, dict) and set(value) == {"schemaVersion", "hosts"} and value["schemaVersion"] == 1 and isinstance(value["hosts"], list), "endpoint-invalid")
    result: dict[str, str] = {}
    for item in value["hosts"]:
        require(isinstance(item, dict) and set(item) == {"name", "address"}, "endpoint-invalid")
        require(isinstance(item["name"], str) and item["name"] not in result and isinstance(item["address"], str), "endpoint-invalid")
        ip_address(item["address"])
        result[item["name"]] = item["address"]
    require(bool(result), "endpoint-empty")
    return result


def validate_known_hosts(path: Path, endpoints: dict[str, str]) -> None:
    info = os.lstat(path)
    require(stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode), "known-hosts-shape")
    require(info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o440, "known-hosts-authority")
    addresses: set[str] = set()
    for line in path.read_text(encoding="ascii").splitlines():
        parts = line.split()
        require(len(parts) == 3 and parts[1] == "ssh-ed25519", "known-host-invalid")
        addresses.add(parts[0])
    require(addresses == set(endpoints.values()), "known-host-coverage")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--endpoints", type=Path, required=True)
    parser.add_argument("--known-hosts", type=Path, required=True)
    args = parser.parse_args()
    try:
        require(validate_tree(args.source_root) == validate_tree(args.runtime_root), "plugin-runtime-hash-drift")
        tools = validate_plugin(args.runtime_root)
        validate_config(args.config)
        endpoints = validate_endpoints(args.endpoints)
        validate_known_hosts(args.known_hosts, endpoints)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"status": "ok", "plugin": "host-admin", "hosts": len(endpoints), "tools": tools}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
