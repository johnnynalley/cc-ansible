#!/usr/bin/env python3
"""Validate the root-managed Astra Star dispatch-privacy plugin."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import yaml

sys.dont_write_bytecode = True

PLUGIN = "star-dispatch-privacy"
EXPECTED_FILES = ("__init__.py", "plugin.yaml")
EXPECTED_HOOKS = {
    "on_session_finalize",
    "on_session_reset",
    "post_tool_call",
    "pre_llm_call",
    "pre_tool_call",
    "transform_llm_output",
}


class ValidationError(RuntimeError):
    """Raised for a fail-closed plugin validation error."""


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
    with os.scandir(root) as entries:
        names = sorted(entry.name for entry in entries)
    source_names = sorted(name for name in names if name != "__pycache__")
    require(source_names == list(EXPECTED_FILES), "plugin-inventory-drift")
    if "__pycache__" in names:
        cache = root / "__pycache__"
        cache_stat = os.lstat(cache)
        require(stat.S_ISDIR(cache_stat.st_mode), "plugin-cache-not-directory")
        require(not stat.S_ISLNK(cache_stat.st_mode), "plugin-cache-symlink")
        require(cache_stat.st_uid == 0, "plugin-cache-owner")
        require(cache_stat.st_mode & 0o022 == 0, "plugin-cache-writable")
        with os.scandir(cache) as entries:
            for entry in entries:
                path = cache / entry.name
                path_stat = os.lstat(path)
                require(
                    entry.name.endswith(".pyc")
                    and stat.S_ISREG(path_stat.st_mode)
                    and not stat.S_ISLNK(path_stat.st_mode),
                    f"plugin-cache-inventory:{entry.name}",
                )
                require(
                    path_stat.st_uid == 0,
                    f"plugin-cache-owner:{entry.name}",
                )
                require(
                    path_stat.st_mode & 0o022 == 0,
                    f"plugin-cache-writable:{entry.name}",
                )
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


class HookContext:
    def __init__(self) -> None:
        self.hooks: dict[str, object] = {}
        self.tools: list[str] = []

    def register_hook(self, name: str, callback: object) -> None:
        require(name not in self.hooks, f"duplicate-hook:{name}")
        self.hooks[name] = callback

    def register_tool(self, name: str, **_: object) -> None:
        self.tools.append(name)


def validate_plugin(runtime_root: Path) -> list[str]:
    spec = importlib.util.spec_from_file_location(
        "hermes_star_dispatch_privacy", runtime_root / "__init__.py"
    )
    require(spec is not None and spec.loader is not None, "plugin-import-spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    context = HookContext()
    module.register(context)
    require(set(context.hooks) == EXPECTED_HOOKS, "plugin-hook-drift")
    require(context.tools == [], "plugin-must-not-register-tools")
    return sorted(context.hooks)


def validate_config(path: Path) -> None:
    require(path.is_absolute() and path.is_file(), "config-missing")
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    require(isinstance(config, dict), "config-invalid")
    plugins = config.get("plugins")
    require(isinstance(plugins, dict), "plugins-config-missing")
    enabled = plugins.get("enabled")
    require(
        isinstance(enabled, list)
        and all(isinstance(item, str) for item in enabled)
        and len(enabled) == len(set(enabled))
        and PLUGIN in enabled,
        "plugin-enable-state-drift",
    )
    disabled = plugins.get("disabled", [])
    require(isinstance(disabled, list) and PLUGIN not in disabled, "plugin-disabled")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        source_hashes = validate_tree(args.source_root)
        runtime_hashes = validate_tree(args.runtime_root)
        require(source_hashes == runtime_hashes, "plugin-runtime-hash-drift")
        validate_config(args.config)
        hooks = validate_plugin(args.runtime_root)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"status": "ok", "plugin": PLUGIN, "hooks": hooks}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
