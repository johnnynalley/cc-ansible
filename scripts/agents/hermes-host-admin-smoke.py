#!/usr/bin/env python3
"""Exercise every enrolled host status path as the real Astra identity."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.dont_write_bytecode = True


def load(root: Path):
    spec = importlib.util.spec_from_file_location("smoke_host_admin", root / "__init__.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("plugin-import-failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin", type=Path, required=True)
    args = parser.parse_args()
    try:
        module = load(args.plugin)
        listing = json.loads(module._handle_hosts({}))
        if listing.get("status") != "ok" or not listing.get("hosts"):
            raise RuntimeError(f"host-list-failed:{listing.get('code', 'invalid-response')}")

        def check(host: str) -> dict[str, str]:
            value = json.loads(module._handle_request({"host": host, "action": "status"}))
            if value.get("status") != "ok" or value.get("action") != "status":
                raise RuntimeError(f"host-status-failed:{host}:{value.get('code', 'invalid-response')}")
            return {"host": host, "status": "ok"}

        with ThreadPoolExecutor(max_workers=min(6, len(listing["hosts"]))) as executor:
            results = list(executor.map(check, listing["hosts"]))
        print(json.dumps({"status": "ok", "results": results}, sort_keys=True))
    except Exception as exc:
        print(f"hermes-host-admin-smoke-error:{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
