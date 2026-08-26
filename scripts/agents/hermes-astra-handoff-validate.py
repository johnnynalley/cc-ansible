#!/usr/bin/env python3
"""Validate Dubble's fixed-target native Hermes peer handoff plugin."""

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

FILES = ("__init__.py", "plugin.yaml")


class ValidationError(RuntimeError):
    pass


def require(value: bool, code: str) -> None:
    if not value:
        raise ValidationError(code)


def tree(root: Path) -> dict[str, str]:
    info = os.lstat(root)
    require(root.is_absolute(), "root-relative")
    require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode), "root-kind")
    require(info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o750, "root-authority")
    require(sorted(item.name for item in os.scandir(root)) == list(FILES), "inventory-drift")
    result = {}
    for name in FILES:
        path = root / name
        item = os.lstat(path)
        require(stat.S_ISREG(item.st_mode) and not stat.S_ISLNK(item.st_mode), f"file-kind:{name}")
        require(item.st_uid == 0 and stat.S_IMODE(item.st_mode) == 0o440, f"file-authority:{name}")
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


class Context:
    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []

    def register_tool(self, **kwargs: Any) -> None:
        self.tools.append(kwargs)


def validate_plugin(root: Path) -> None:
    spec = importlib.util.spec_from_file_location("hermes_astra_handoff", root / "__init__.py")
    require(spec is not None and spec.loader is not None, "import-spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    context = Context()
    module.register(context)
    require(len(context.tools) == 1, "tool-count")
    tool = context.tools[0]
    require(tool.get("name") == "astra_handoff", "tool-name")
    require(tool.get("toolset") == "astra_handoff", "toolset")
    parameters = tool.get("schema", {}).get("parameters", {})
    require(parameters.get("required") == ["message"], "required")
    require(parameters.get("additionalProperties") is False, "schema-open")
    source = (root / "__init__.py").read_text(encoding="utf-8")
    require('"peer", "dm", "astra"' in source, "fixed-target-missing")
    require("shell=True" not in source, "shell-enabled")


def validate_config(path: Path) -> None:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    plugins = config.get("plugins", {}).get("enabled")
    base_plugins = ["discord-parity", "astra-handoff"]
    memory_plugins = [*base_plugins, "hermes-lcm"]
    require(plugins in [base_plugins, memory_plugins], "plugin-set")
    if plugins == memory_plugins:
        require(config.get("context", {}).get("engine") == "lcm", "lcm-context")
        require(config.get("memory", {}).get("provider") == "mem0", "mem0-provider")
    require("astra_handoff" in config.get("toolsets", []), "toolset-disabled")
    require(config.get("bot_peers") == {"astra": {"url": "http://127.0.0.1:8642"}}, "peer-config")
    require("terminal" in config.get("agent", {}).get("disabled_toolsets", []), "terminal-enabled")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        require(tree(args.source_root) == tree(args.runtime_root), "runtime-hash-drift")
        validate_plugin(args.runtime_root)
        validate_config(args.config)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"status": "ok", "plugin": "astra-handoff"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
