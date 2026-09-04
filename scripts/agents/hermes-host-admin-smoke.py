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
    parser.add_argument("--media-series-id", type=int)
    parser.add_argument("--media-season-number", type=int)
    args = parser.parse_args()
    try:
        if (args.media_series_id is None) != (args.media_season_number is None):
            raise RuntimeError("media-search-arguments-incomplete")
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

        response = {"status": "ok", "results": results}
        if args.media_series_id is not None:
            media = json.loads(
                module._handle_request(
                    {
                        "host": "docker-vm",
                        "action": "media-release-search",
                        "seriesId": args.media_series_id,
                        "seasonNumber": args.media_season_number,
                    }
                )
            )
            if media.get("status") != "ok" or media.get("action") != "media-release-search":
                raise RuntimeError(
                    f"media-search-failed:{media.get('code', 'invalid-response')}"
                )
            body = media.get("body", {})
            candidates = body.get("candidates")
            if not isinstance(candidates, list):
                raise RuntimeError("media-search-invalid-candidates")
            response["mediaSearch"] = {
                "seriesId": body.get("seriesId"),
                "seasonNumber": body.get("seasonNumber"),
                "candidateCount": len(candidates),
                "candidates": candidates,
            }
        print(json.dumps(response, sort_keys=True))
    except Exception as exc:
        print(f"hermes-host-admin-smoke-error:{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
