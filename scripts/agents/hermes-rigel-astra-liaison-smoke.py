#!/usr/bin/env python3
"""Exercise Rigel's real provenance-gated calendar liaison without writes."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

sys.dont_write_bytecode = True


def load_plugin(root: Path):
    spec = importlib.util.spec_from_file_location("smoke_rigel_astra_liaison", root / "__init__.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("plugin-import-failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def request() -> dict[str, object]:
    return {
        "operation": "calendar_check",
        "events": [
            {
                "eventId": "hermes-liaison-readonly-smoke",
                "course": "Hermes Validation",
                "event": "Read-only calendar smoke",
                "startsAt": "2099-01-15T10:00:00-06:00",
                "endsAt": "2099-01-15T11:00:00-06:00",
                "description": "Read-only liaison validation; never add",
                "weight": "none",
            }
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin", type=Path, required=True)
    args = parser.parse_args()
    try:
        plugin = load_plugin(args.plugin)
        denied = json.loads(plugin._handler(request(), session_id=None))
        if denied.get("status") != "error" or denied.get("code") != "session-denied":
            raise RuntimeError("missing-provenance-not-denied")
        policy = plugin._load_policy()
        database = sqlite3.connect(f"file:{plugin.STATE_DB}?mode=ro", uri=True, timeout=2)
        try:
            rows = database.execute("SELECT id FROM sessions LIMIT 2000").fetchall()
        finally:
            database.close()
        eligible = None
        for (session_id,) in rows:
            try:
                plugin._authorize_session(session_id, policy)
            except (OSError, ValueError, sqlite3.Error):
                continue
            eligible = session_id
            break
        if eligible is None:
            raise RuntimeError("eligible-discord-session-unavailable")
        result = json.loads(plugin._handler(request(), session_id=eligible))
        if result.get("schemaVersion") != 1 or result.get("status") != "ok":
            code = result.get("code") if isinstance(result.get("code"), str) else "invalid-response"
            raise RuntimeError(f"authorized-calendar-check-{code}")
        states = [item.get("state") for item in result.get("results", []) if isinstance(item, dict)]
        if states != ["NOT_ON_CALENDAR"]:
            raise RuntimeError("calendar-smoke-state-unexpected")
    except Exception as exc:
        print(json.dumps({"status": "error", "code": str(exc)}, sort_keys=True))
        return 1
    print(
        json.dumps(
            {
                "status": "ok",
                "missingProvenanceDenied": True,
                "authorizedCheck": True,
                "states": states,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
