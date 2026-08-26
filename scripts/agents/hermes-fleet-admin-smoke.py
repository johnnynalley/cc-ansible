#!/usr/bin/env python3
"""Invoke Astra's fleet administration plugin through a real session."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

sys.dont_write_bytecode = True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-root", type=Path, required=True)
    parser.add_argument("--session-id")
    parser.add_argument("--target", choices=["astra", "dubble", "rigel"], required=True)
    parser.add_argument("--mutation-check", action="store_true")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("smoke_fleet_admin", args.plugin_root / "__init__.py")
    if spec is None or spec.loader is None:
        raise SystemExit("plugin-import-failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    session_id = args.session_id
    if session_id is None:
        policy = module._load_policy()
        database = sqlite3.connect(f"file:{module.STATE_DB}?mode=ro", uri=True, timeout=2)
        try:
            placeholders = ",".join("?" for _ in policy["allowedChannelIds"])
            row = database.execute(
                "SELECT id FROM sessions WHERE source=? AND user_id=? "
                f"AND chat_id IN ({placeholders}) ORDER BY rowid DESC LIMIT 1",
                (
                    policy["allowedSource"],
                    policy["allowedUserIds"][0],
                    *policy["allowedChannelIds"],
                ),
            ).fetchone()
        finally:
            database.close()
        if row is None:
            raise SystemExit("owner-session-unavailable")
        session_id = row[0]
    def invoke(request: dict[str, object]) -> dict[str, object]:
        return json.loads(module._handler(request, session_id=session_id))

    value = invoke({"target": args.target, "operation": "inspect"})
    if value.get("status") != "ok" or value.get("target") != args.target or value.get("operation") != "inspect":
        print(json.dumps(value, sort_keys=True))
        return 1
    mutation_round_trip = False
    if args.mutation_check:
        path = f".fleet-admin-acceptance-{args.target}.txt"
        content = f"fleet-admin-acceptance:{args.target}\n"
        created_sha: str | None = None
        initial = invoke(
            {"target": args.target, "operation": "read", "root": "workspace", "path": path}
        )
        if initial.get("status") == "ok":
            raise SystemExit("acceptance-canary-already-exists")
        try:
            written = invoke(
                {
                    "target": args.target,
                    "operation": "write",
                    "root": "workspace",
                    "path": path,
                    "content": content,
                    "expectedSha256": "absent",
                }
            )
            created_sha = str(written.get("sha256") or "")
            if (
                written.get("status") != "ok"
                or created_sha != hashlib.sha256(content.encode("utf-8")).hexdigest()
            ):
                raise RuntimeError("acceptance-write-failed")
            observed = invoke(
                {"target": args.target, "operation": "read", "root": "workspace", "path": path}
            )
            if observed.get("status") != "ok" or observed.get("content") != content:
                raise RuntimeError("acceptance-readback-failed")
            deleted = invoke(
                {
                    "target": args.target,
                    "operation": "delete",
                    "root": "workspace",
                    "path": path,
                    "expectedSha256": created_sha,
                }
            )
            if deleted.get("status") != "ok":
                raise RuntimeError("acceptance-delete-failed")
            created_sha = None
            final = invoke(
                {"target": args.target, "operation": "read", "root": "workspace", "path": path}
            )
            if final.get("status") == "ok":
                raise RuntimeError("acceptance-canary-remained")
            mutation_round_trip = True
        finally:
            if created_sha:
                invoke(
                    {
                        "target": args.target,
                        "operation": "delete",
                        "root": "workspace",
                        "path": path,
                        "expectedSha256": created_sha,
                    }
                )

    print(
        json.dumps(
            {
                "status": "ok",
                "target": value["target"],
                "serviceActive": value.get("service", {}).get("active"),
                "workspaceFiles": value.get("workspace", {}).get("files"),
                "bootstrapFiles": len(value.get("bootstrap", {})),
                "mutationRoundTrip": mutation_round_trip,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
