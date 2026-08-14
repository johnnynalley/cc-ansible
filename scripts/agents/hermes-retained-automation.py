#!/usr/bin/env python3
"""Run fixed retained collectors and stage only bounded non-secret output."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


MAX_OUTPUT = 262_144


class CollectorError(Exception):
    """Raised when a retained collector does not produce safe staged output."""


def run(argv: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: int = 300) -> str:
    result = subprocess.run(
        argv,
        cwd=cwd,
        env={**os.environ, **(env or {})},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "collector-failed").strip().replace("\n", " ")
        raise CollectorError(f"{Path(argv[0]).name}:rc={result.returncode}:{detail[:300]}")
    if len(result.stdout.encode("utf-8")) > MAX_OUTPUT:
        raise CollectorError("collector-output-too-large")
    return result.stdout


def atomic_text(path: Path, content: str, mode: int = 0o640) -> None:
    encoded = content.encode("utf-8")
    if not encoded or len(encoded) > MAX_OUTPUT:
        raise CollectorError("staged-output-size")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            if not content.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path) -> Any:
    try:
        stat = path.stat()
        if not path.is_file() or path.is_symlink() or stat.st_size > MAX_OUTPUT:
            raise CollectorError(f"invalid-json-artifact:{path.name}")
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CollectorError(f"invalid-json-artifact:{path.name}") from exc


def daily_summary(workspace: Path, output_root: Path) -> None:
    scripts = workspace / "scripts"
    run([sys.executable, str(scripts / "collect-media-summary.py")], cwd=workspace)
    run([str(scripts / "daily_personal_collect.py")], cwd=workspace)
    destination = output_root / "daily-summary.md"
    run(
        [sys.executable, str(scripts / "daily-summary-assemble.py")],
        cwd=workspace,
        env={"DAILY_SUMMARY_SCRATCH_OUT": str(destination)},
    )
    content = destination.read_text(encoding="utf-8")
    atomic_text(destination, content)


def fortnite_progress(workspace: Path, output_root: Path) -> None:
    scripts = workspace / "scripts"
    output = run([sys.executable, str(scripts / "fortnite-progress-snapshot.py")], cwd=workspace)
    try:
        result = json.loads(output)
    except json.JSONDecodeError as exc:
        raise CollectorError("fortnite-command-json") from exc
    if not isinstance(result, dict) or result.get("status") != "ok":
        raise CollectorError("fortnite-command-status")
    progress = workspace / "fortnite-progress"
    payload = {
        "status": "ok",
        "command": result,
        "latest": read_json(progress / "latest.json"),
        "trends": read_json(progress / "trends" / "latest-trends.json"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    atomic_text(output_root / "fortnite-progress.json", encoded)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", choices=("daily-summary", "fortnite-progress"))
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.task == "daily-summary":
            daily_summary(args.workspace, args.output_root)
        else:
            fortnite_progress(args.workspace, args.output_root)
        print(json.dumps({"status": "ok", "task": args.task}, separators=(",", ":")))
        return 0
    except (CollectorError, OSError, subprocess.SubprocessError) as exc:
        print(f"Retained automation failed ({args.task}): {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
