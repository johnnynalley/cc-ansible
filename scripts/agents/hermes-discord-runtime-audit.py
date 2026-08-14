#!/usr/bin/env python3
"""Fail silently unless a Hermes Discord runtime is actually usable."""

from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import sys
import time


REQUIRED_MODULES = ("discord", "aiohttp", "brotlicffi")
ESTABLISHED = "01"
HTTPS_PORT_HEX = "01BB"


def require_imports() -> None:
    for module in REQUIRED_MODULES:
        importlib.import_module(module)


def socket_inodes(pid: int, proc_root: Path = Path("/proc")) -> set[str]:
    process = proc_root / str(pid)
    if process.stat().st_uid != os.geteuid():
        raise PermissionError("gateway process belongs to another identity")

    inodes: set[str] = set()
    for descriptor in (process / "fd").iterdir():
        try:
            target = os.readlink(descriptor)
        except FileNotFoundError:
            continue
        if target.startswith("socket:[") and target.endswith("]"):
            inodes.add(target[8:-1])
    return inodes


def has_established_tls(pid: int, proc_root: Path = Path("/proc")) -> bool:
    inodes = socket_inodes(pid, proc_root)
    if not inodes:
        return False

    process_net = proc_root / str(pid) / "net"
    for table_name in ("tcp", "tcp6"):
        table = process_net / table_name
        try:
            rows = table.read_text(encoding="ascii").splitlines()[1:]
        except FileNotFoundError:
            continue
        for row in rows:
            fields = row.split()
            if len(fields) < 10:
                continue
            remote_port = fields[2].rsplit(":", 1)[-1].upper()
            if (
                fields[3] == ESTABLISHED
                and remote_port == HTTPS_PORT_HEX
                and fields[9] in inodes
            ):
                return True
    return False


def wait_for_established_tls(pid: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        if has_established_tls(pid):
            return
        if time.monotonic() >= deadline:
            raise TimeoutError("gateway opened no established TLS session")
        time.sleep(0.5)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--imports-only", action="store_true")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    if args.imports_only == (args.pid is not None):
        parser.error("choose exactly one of --imports-only or --pid")
    if args.pid is not None and args.pid <= 1:
        parser.error("--pid must identify a non-init process")
    if not 0 < args.timeout <= 120:
        parser.error("--timeout must be between 0 and 120 seconds")
    return args


def main() -> int:
    args = parse_args()
    try:
        require_imports()
        if args.pid is not None:
            wait_for_established_tls(args.pid, args.timeout)
    except Exception as exc:
        print(f"Hermes Discord runtime audit failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
