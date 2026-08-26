#!/usr/bin/env python3
"""Run Astra's Docker handlers without printing inventory or host details."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin", type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location(
        "hermes_agent_docker_inventory_smoke", args.plugin / "__init__.py"
    )
    if spec is None or spec.loader is None:
        return 1
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report_hosts, update_hosts = module._load_endpoints()
    for host in report_hosts:
        value = json.loads(module._handle_inventory({"host": host}))
        if value.get("status") != "ok":
            code = value.get("code", "invalid-response")
            print(f"{host}: {code}", file=sys.stderr)
            return 1
        reports = value.get("reports")
        if (
            not isinstance(reports, list)
            or len(reports) != 1
            or reports[0].get("host") != host
        ):
            print(f"{host}: invalid-response", file=sys.stderr)
            return 1
    for host in update_hosts:
        value = json.loads(module._handle_update({"host": host, "action": "status"}))
        if value.get("status") != "ok":
            code = value.get("code", "invalid-response")
            print(f"{host}: {code}", file=sys.stderr)
            return 1
        results = value.get("results")
        if (
            not isinstance(results, list)
            or len(results) != 1
            or results[0].get("host") != host
            or results[0].get("action") != "status"
            or results[0].get("outcome") != "ready"
        ):
            print(f"{host}: invalid-update-response", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
