#!/usr/bin/env python3
"""Validate isolated profile Mem0 without exposing or retaining memory text."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

sys.dont_write_bytecode = True


class SmokeError(RuntimeError):
    """Raised when the isolated provider boundary does not pass."""


def require(value: bool, code: str) -> None:
    if not value:
        raise SmokeError(code)


def load_config(path: Path) -> dict[str, Any]:
    require(path.is_absolute(), "config-relative")
    info = os.lstat(path)
    require(stat.S_ISREG(info.st_mode), "config-not-regular")
    require(not stat.S_ISLNK(info.st_mode), "config-symlink")
    require(info.st_size <= 1024 * 1024, "config-too-large")
    try:
        value = json.loads(path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SmokeError("config-invalid-json") from exc
    require(isinstance(value, dict) and isinstance(value.get("oss"), dict), "config-shape")
    return value["oss"]


def points(memory: Any, filters: dict[str, str]) -> list[Any]:
    result = memory.vector_store.list(filters=filters, top_k=20)
    selected = result[0] if isinstance(result, tuple) else result
    require(isinstance(selected, list), "list-shape")
    return selected


def run(args: argparse.Namespace, factory: Callable[[dict[str, Any]], Any]) -> dict[str, Any]:
    memory = factory(load_config(args.config))
    filters = {"user_id": args.user_id, "agent_id": args.agent_id}
    before = points(memory, filters)
    if args.mode == "existing":
        require(bool(before), "existing-memory-empty")
        payload = getattr(before[0], "payload", None)
        require(isinstance(payload, dict), "existing-payload-shape")
        data = payload.get("data")
        require(isinstance(data, str) and data.strip(), "existing-memory-data")
        tokens = re.findall(r"[A-Za-z0-9]{5,}", data)
        require(bool(tokens), "existing-memory-token")
        require(bool(memory.search(data[:500], filters=filters)), "existing-semantic-recall")
        require(
            bool(memory.vector_store.keyword_search(max(tokens, key=len), top_k=5, filters=filters)),
            "existing-keyword-recall",
        )
        return {"status": "ok", "mode": args.mode, "before": len(before), "after": len(before)}

    require(args.mode == "empty-roundtrip", "mode-invalid")
    require(not before, "empty-target-not-empty")
    marker = f"dubble provider acceptance {uuid.uuid4().hex}"
    added = 0
    try:
        memory.add(
            marker,
            user_id=args.user_id,
            agent_id=args.agent_id,
            metadata={"acceptance": True},
            infer=False,
        )
        current = points(memory, filters)
        added = len(current)
        require(added > 0, "roundtrip-add-empty")
        require(bool(memory.search(marker, filters=filters)), "roundtrip-semantic-recall")
        require(
            bool(memory.vector_store.keyword_search(marker.split()[-1], top_k=5, filters=filters)),
            "roundtrip-keyword-recall",
        )
    finally:
        memory.delete_all(user_id=args.user_id, agent_id=args.agent_id)
    after = points(memory, filters)
    require(not after, "roundtrip-cleanup-failed")
    return {"status": "ok", "mode": args.mode, "before": 0, "added": added, "after": 0}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--config", type=Path, required=True)
    value.add_argument("--user-id", required=True)
    value.add_argument("--agent-id", required=True)
    value.add_argument("--mode", choices=["existing", "empty-roundtrip"], required=True)
    return value


def main() -> int:
    try:
        from mem0 import Memory

        output = run(parser().parse_args(), Memory.from_config)
    except (OSError, SmokeError) as exc:
        code = str(exc) if isinstance(exc, SmokeError) else type(exc).__name__
        print(f"profile-mem0-smoke-error:{code}", file=sys.stderr)
        return 1
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
