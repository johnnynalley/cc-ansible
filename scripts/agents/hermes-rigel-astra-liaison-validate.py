#!/usr/bin/env python3
"""Validate Rigel's root-managed Astra calendar liaison boundary."""

from __future__ import annotations

import argparse
import grp
import hashlib
import importlib.util
import json
import os
import socket
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
    spec = importlib.util.spec_from_file_location("validated_rigel_astra_liaison", root / "__init__.py")
    require(spec is not None and spec.loader is not None, "plugin-import-failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_plugin(root: Path) -> list[str]:
    metadata = yaml.safe_load((root / "plugin.yaml").read_text(encoding="utf-8"))
    require(
        isinstance(metadata, dict)
        and metadata.get("name") == "rigel-astra-liaison"
        and metadata.get("version") == "1.0.0"
        and metadata.get("module") == "__init__",
        "plugin-metadata-drift",
    )
    context = Context()
    load_plugin(root).register(context)
    require([item.get("name") for item in context.tools] == ["rigel_ask_astra"], "plugin-tool-drift")
    require({item.get("toolset") for item in context.tools} == {"rigel_astra_liaison"}, "plugin-toolset-drift")
    return ["rigel_ask_astra"]


def validate_config(path: Path) -> None:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), "config-invalid")
    plugins = value.get("plugins", {}).get("enabled", [])
    toolsets = value.get("toolsets", [])
    require(isinstance(plugins, list) and "rigel-astra-liaison" in plugins, "plugin-not-enabled")
    require(isinstance(toolsets, list) and "rigel_astra_liaison" in toolsets, "toolset-not-enabled")


def validate_policy(path: Path, module: Any) -> None:
    module.POLICY = path
    module._load_policy()


def validate_socket(path: Path, group_name: str) -> None:
    info = os.lstat(path)
    require(stat.S_ISSOCK(info.st_mode) and not stat.S_ISLNK(info.st_mode), "broker-socket-shape")
    require(info.st_gid == grp.getgrnam(group_name).gr_gid, "broker-socket-group")
    require(stat.S_IMODE(info.st_mode) == 0o660, "broker-socket-mode")


def probe_forbidden_socket(path: Path) -> None:
    require(str(path) in {"/run/docker.sock", "/var/run/docker.sock"}, "probe-path-denied")
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.settimeout(2)
        client.connect(str(path))
    except (FileNotFoundError, PermissionError):
        return
    except OSError as exc:
        raise ValidationError(f"forbidden-socket-probe-{exc.errno}") from exc
    finally:
        client.close()
    raise ValidationError("forbidden-socket-accessible")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--socket", type=Path)
    parser.add_argument("--socket-group")
    parser.add_argument("--probe-forbidden-socket", type=Path)
    args = parser.parse_args()
    try:
        if args.probe_forbidden_socket is not None:
            require(
                all(
                    value is None
                    for value in (
                        args.source_root,
                        args.runtime_root,
                        args.config,
                        args.policy,
                        args.socket,
                        args.socket_group,
                    )
                ),
                "probe-arguments-invalid",
            )
            probe_forbidden_socket(args.probe_forbidden_socket)
            print(json.dumps({"status": "ok", "socketAccessible": False}, sort_keys=True))
            return 0
        require(
            all(
                value is not None
                for value in (
                    args.source_root,
                    args.runtime_root,
                    args.config,
                    args.policy,
                    args.socket,
                    args.socket_group,
                )
            ),
            "validation-arguments-missing",
        )
        source_hashes = validate_tree(args.source_root)
        runtime_hashes = validate_tree(args.runtime_root)
        require(source_hashes == runtime_hashes, "plugin-runtime-hash-drift")
        tools = validate_plugin(args.runtime_root)
        validate_config(args.config)
        validate_policy(args.policy, load_plugin(args.runtime_root))
        validate_socket(args.socket, args.socket_group)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"status": "ok", "plugin": "rigel-astra-liaison", "tools": tools}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
