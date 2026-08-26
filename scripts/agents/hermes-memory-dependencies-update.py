#!/usr/bin/env python3
"""Install stable memory packages without violating Hermes base requirements."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import subprocess
import sys

from packaging.requirements import Requirement


def active_base_requirements(distribution: str) -> list[str]:
    requirements = [
        Requirement(raw)
        for raw in (importlib.metadata.requires(distribution) or [])
    ]
    return [
        str(requirement)
        for requirement in requirements
        if requirement.marker is None or requirement.marker.evaluate()
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uv", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--distribution", default="hermes-agent")
    parser.add_argument("--package", action="append", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_requirements = active_base_requirements(args.distribution)
    if not base_requirements:
        print("hermes-memory-dependencies-error:no-active-base-requirements", file=sys.stderr)
        return 2
    command = [
        args.uv,
        "pip",
        "install",
        "--strict",
        "--upgrade",
        "--prerelease",
        "disallow",
        "--python",
        args.python,
    ]
    if args.dry_run:
        command.append("--dry-run")
    command.extend(args.package)
    command.extend(base_requirements)
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        return completed.returncode
    print(
        json.dumps(
            {
                "baseRequirementCount": len(base_requirements),
                "memoryPackageCount": len(args.package),
                "status": "ready" if args.dry_run else "installed",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
