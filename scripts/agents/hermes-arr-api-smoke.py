#!/usr/bin/env python3
"""Exercise read-only Arr API access as the real Astra identity."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True


def load_plugin(root: Path):
    spec = importlib.util.spec_from_file_location("smoke_arr_api", root / "__init__.py")
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
        module = load_plugin(args.plugin)
        listing = json.loads(module._handle_list({}))
        if listing.get("status") != "ok" or not listing.get("services"):
            raise RuntimeError(
                f"service-list-failed:{listing.get('code', 'invalid-response')}"
            )
        results = []
        for item in listing["services"]:
            value = json.loads(
                module._handle_request(
                    {
                        "service": item["name"],
                        "method": "GET",
                        "path": item["statusPath"],
                    }
                )
            )
            if value.get("status") != "ok" or value.get("httpStatus") != 200:
                raise RuntimeError(
                    f"status-probe-failed:{item['name']}:{value.get('code', 'invalid-response')}"
                )
            results.append({"service": item["name"], "httpStatus": value["httpStatus"]})
        schema = json.loads(module._handle_prowlarr_schema({"query": "apiKey"}))
        schema_body = schema.get("body", {})
        if (
            schema.get("status") != "ok"
            or schema.get("httpStatus") != 200
            or not isinstance(schema_body, dict)
            or schema_body.get("totalMatches", 0) < 1
            or not schema_body.get("matches")
        ):
            raise RuntimeError(
                f"prowlarr-schema-search-failed:{schema.get('code', 'invalid-response')}"
            )
        rejected = json.loads(
            module._handle_prowlarr_indexer(
                {
                    "method": "POST",
                    "path": "/api/v1/indexer/test",
                    "definition": {"fields": []},
                    "secrets": {"apiKey": "non-secret-smoke-placeholder"},
                }
            )
        )
        if rejected.get("code") != "secret-field-mismatch":
            raise RuntimeError(
                "prowlarr-secret-boundary-failed:"
                + rejected.get("code", "invalid-response")
            )
        print(json.dumps({"status": "ok", "results": results}, sort_keys=True))
    except Exception as exc:
        print(f"hermes-arr-api-smoke-error:{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
