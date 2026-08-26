#!/usr/bin/env python3
"""Exercise Rigel's native academic file capabilities without printing content."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import sys
from pathlib import Path


class SmokeError(RuntimeError):
    """A bounded academic capability check failed."""


SUPPORTED_SAMPLE_TYPES = {"pdf": ".pdf", "docx": ".docx", "pptx": ".pptx"}


def parse_sample(raw: str) -> tuple[str, Path]:
    kind, separator, value = raw.partition("=")
    if separator != "=" or kind not in SUPPORTED_SAMPLE_TYPES or not value:
        raise argparse.ArgumentTypeError(
            "sample must be pdf=PATH, docx=PATH, or pptx=PATH"
        )
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise argparse.ArgumentTypeError(
            "sample path must be relative and traversal-free"
        )
    if path.suffix.lower() != SUPPORTED_SAMPLE_TYPES[kind]:
        raise argparse.ArgumentTypeError(
            f"{kind} sample must end in {SUPPORTED_SAMPLE_TYPES[kind]}"
        )
    return kind, path


def decode_tool_result(raw: str, operation: str) -> dict:
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SmokeError(f"{operation}-non-json-result") from exc
    if not isinstance(result, dict):
        raise SmokeError(f"{operation}-non-object-result")
    return result


def require_success(result: dict, operation: str) -> None:
    if result.get("error") or result.get("success") is False:
        reason = str(result.get("error") or result.get("note") or "tool-error")
        reason = " ".join(reason.split())[:300]
        raise SmokeError(f"{operation}-failed:{reason}")


def drop_privileges(user: str) -> None:
    if os.geteuid() != 0:
        raise SmokeError("drop-user-requires-root")
    account = pwd.getpwnam(user)
    # Match systemd/runuser account membership, including the credential-free
    # runtime readers group required to import Hermes's shared source tree.
    os.initgroups(user, account.pw_gid)
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    os.environ["HOME"] = account.pw_dir


def validate_inputs(root: Path, samples: list[tuple[str, Path]]) -> Path:
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise SmokeError("invalid-root")
    resolved = root.resolve(strict=True)
    if resolved != root:
        raise SmokeError("noncanonical-root")
    if {kind for kind, _ in samples} != set(SUPPORTED_SAMPLE_TYPES):
        raise SmokeError("exactly-one-sample-per-type-required")
    for kind, relative in samples:
        sample = root / relative
        if sample.is_symlink() or not sample.is_file():
            raise SmokeError(f"{kind}-sample-invalid")
        try:
            sample.resolve(strict=True).relative_to(root)
        except ValueError as exc:
            raise SmokeError(f"{kind}-sample-escaped-root") from exc
    for relative in (Path("courses"), Path("memory")):
        directory = root / relative
        if directory.is_symlink() or not directory.is_dir():
            raise SmokeError(f"missing-{relative}-directory")
    return resolved


def run(args: argparse.Namespace) -> dict:
    root = validate_inputs(args.root, args.sample)
    os.environ["TERMINAL_CWD"] = str(root)
    os.environ["HERMES_HOME"] = str(args.profile_home)
    sys.path.insert(0, str(args.runtime_root))

    if args.drop_user:
        drop_privileges(args.drop_user)
    if args.expected_uid is not None and os.geteuid() != args.expected_uid:
        raise SmokeError("unexpected-effective-uid")

    from tools.file_tools import read_file_tool, write_file_tool

    extracted: dict[str, dict[str, int | bool]] = {}
    for kind, relative in args.sample:
        result = decode_tool_result(
            read_file_tool(
                str(relative),
                offset=1,
                limit=5,
                task_id=f"rigel-academic-{kind}",
            ),
            f"read-{kind}",
        )
        require_success(result, f"read-{kind}")
        if result.get("extracted_document") is not True:
            raise SmokeError(f"{kind}-not-extracted")
        if not isinstance(result.get("content"), str) or not result["content"].strip():
            raise SmokeError(f"{kind}-empty-extraction")
        if int(result.get("total_lines", 0)) < 1 or int(result.get("file_size", 0)) < 1:
            raise SmokeError(f"{kind}-invalid-metadata")
        extracted[kind] = {
            "extracted": True,
            "sampleLines": min(int(result["total_lines"]), 5),
            "sourceBytes": int(result["file_size"]),
        }

    sentinel = f"rigel-academic-smoke-{os.getpid()}"
    write_targets = [
        Path("courses") / f".{sentinel}.md",
        Path("memory") / f".{sentinel}.md",
    ]
    try:
        for relative in write_targets:
            result = decode_tool_result(
                write_file_tool(
                    str(relative), sentinel, task_id="rigel-academic-write"
                ),
                f"write-{relative.parent}",
            )
            require_success(result, f"write-{relative.parent}")
            target = root / relative
            if not target.is_file() or target.read_text(encoding="utf-8") != sentinel:
                raise SmokeError(f"write-readback-{relative.parent}-failed")

        outside = Path("/etc") / f".{sentinel}"
        denied = decode_tool_result(
            write_file_tool(
                str(outside), sentinel, task_id="rigel-academic-denied"
            ),
            "write-outside",
        )
        if not denied.get("error") and denied.get("success") is not False:
            raise SmokeError("outside-write-not-denied")
        if outside.exists():
            raise SmokeError("outside-write-created-file")
    finally:
        for relative in write_targets:
            try:
                (root / relative).unlink()
            except FileNotFoundError:
                pass

    if any((root / relative).exists() for relative in write_targets):
        raise SmokeError("smoke-artifact-cleanup-failed")

    return {
        "status": "ready",
        "effectiveUid": os.geteuid(),
        "documents": extracted,
        "writableRoots": ["courses", "memory"],
        "outsideWriteDenied": True,
        "residualFiles": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--profile-home", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--sample", action="append", type=parse_sample, required=True)
    parser.add_argument("--drop-user")
    parser.add_argument("--expected-uid", type=int)
    return parser.parse_args()


def main() -> int:
    try:
        print(json.dumps(run(parse_args()), sort_keys=True))
    except (OSError, SmokeError) as exc:
        print(f"hermes-rigel-academic-smoke-error:{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
