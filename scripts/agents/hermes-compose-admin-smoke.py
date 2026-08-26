#!/usr/bin/env python3
"""Exercise every enrolled Compose status and read-only plan path as Astra."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.dont_write_bytecode = True


def load(root: Path):
    spec = importlib.util.spec_from_file_location("smoke_compose_admin", root / "__init__.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("plugin-import-failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin", type=Path, required=True)
    args = parser.parse_args()
    sample = {
        "schemaVersion": 1,
        "services": {
            "probe": {
                "image": "docker.io/library/alpine:3.22.1",
                "readOnly": True,
                "memoryMb": 64,
                "pidsLimit": 32,
            }
        },
    }
    try:
        module = load(args.plugin)
        listing = json.loads(module._handle_hosts({}))
        if listing.get("status") != "ok" or not listing.get("hosts"):
            raise RuntimeError(f"host-list-failed:{listing.get('code', 'invalid-response')}")

        def check(host: str) -> dict[str, str]:
            status = json.loads(module._handle_request({"host": host, "action": "status"}))
            if status.get("status") != "ok" or status.get("action") != "status":
                raise RuntimeError(f"host-status-failed:{host}:{status.get('code', 'invalid-response')}")
            plan = json.loads(module._handle_request({"host": host, "action": "plan", "stack": "acceptance-probe", "spec": sample}))
            if plan.get("status") != "ok" or plan.get("action") != "plan" or plan.get("body", {}).get("outcome") not in {"create", "change", "noop"}:
                raise RuntimeError(f"host-plan-failed:{host}:{plan.get('code', 'invalid-response')}")
            return {"host": host, "status": "ok"}

        with ThreadPoolExecutor(max_workers=min(4, len(listing["hosts"]))) as executor:
            results = list(executor.map(check, listing["hosts"]))
        print(json.dumps({"status": "ok", "results": results}, sort_keys=True))
    except Exception as exc:
        print(f"hermes-compose-admin-smoke-error:{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
