#!/usr/bin/env python3
"""Audit the modern OpenClaw bootstrap bundle without initializing OpenClaw."""

from __future__ import annotations

import argparse
import json
import re
import stat
from pathlib import Path


class AuditError(RuntimeError):
    """Raised when the bootstrap bundle violates its deployment contract."""


EXPECTED_FILES = {
    ".": {"AGENTS.md", "HEARTBEAT.md", "SOUL.md", "TOOLS.md", "USER.md"},
    "antares": {"AGENTS.md", "SOUL.md", "TOOLS.md"},
    "dubble": {"AGENTS.md", "HEARTBEAT.md", "SOUL.md", "TOOLS.md"},
    "rigel": {"AGENTS.md", "HEARTBEAT.md", "SOUL.md", "TOOLS.md", "USER.md"},
    "vega": {"AGENTS.md", "SOUL.md", "TOOLS.md"},
}

WORKSPACE_MAX_CHARS = {
    ".": 10_000,
    "antares": 2_500,
    "dubble": 5_000,
    "rigel": 6_000,
    "vega": 2_500,
}

TOTAL_MAX_CHARS = 26_000
FILE_MAX_CHARS = 6_000
OPAQUE_PLATFORM_ID = re.compile(r"(?<!\d)\d{16,22}(?!\d)")

FORBIDDEN_FRAGMENTS = (
    "/home/johnny",
    "agent:main:discord:",
    "HEARTBEAT_OK",
    "NO_REPLY",
    "ARTBEAT_OK",
    "BEAT_OK",
    "ANNOUNCE_SKIP",
    "REPLY_SKIP",
    "cognitive-stack",
    "Spring 2026",
    "Known course IDs",
)

ROLE_FORBIDDEN = {
    "dubble/AGENTS.md": ("sessions_history", "timeoutSeconds: 300"),
    "rigel/AGENTS.md": ("sessions_history", "Astra_SESSION_KEY"),
    "rigel/HEARTBEAT.md": ("list files", "Thinking Process:"),
}

REQUIRED_FRAGMENTS = {
    "AGENTS.md": (
        "Reconstruct the active objective",
        "Build the causal model",
        "Manifest descriptions define responsibility",
        "Keep both reports internal",
        "configured proposal queue",
    ),
    "HEARTBEAT.md": (
        "heartbeat_respond",
        "notify=false",
        "notify=true",
    ),
    "vega/AGENTS.md": (
        "current primary sources",
        "contradictory evidence",
        "confidence",
        "internal packet",
    ),
    "antares/AGENTS.md": (
        "independent challenger",
        "PASS",
        "FAIL",
        "DISPUTE",
        "residual risk",
    ),
    "dubble/AGENTS.md": (
        "AUTH.yaml",
        "sessions_send",
        'agentId: "main"',
        "native completion event",
        "Do not inspect\n   transcripts on a timer",
    ),
    "dubble/HEARTBEAT.md": (
        "heartbeat_respond",
        "notify=false",
        "metadata proves",
    ),
    "rigel/AGENTS.md": (
        "skills/academic/SKILL.md",
        "courses/semester-context.md",
        "sessions_send",
        'agentId: "main"',
        "Do not hardcode a session key",
    ),
    "rigel/HEARTBEAT.md": (
        "30-minute heartbeat remains enabled around the clock",
        "non-failing existence check",
        "heartbeat_respond",
        "notify=false",
        "notify=true",
    ),
}


def _relative_file_set(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    }


def _expected_relative_files() -> set[str]:
    expected: set[str] = set()
    for workspace, names in EXPECTED_FILES.items():
        for name in names:
            expected.add(name if workspace == "." else f"{workspace}/{name}")
    return expected


def _read_regular_ascii(path: Path, root: Path) -> str:
    relative = path.relative_to(root).as_posix()
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise AuditError(f"not-regular-file:{relative}")
    if metadata.st_nlink != 1:
        raise AuditError(f"hardlink-not-allowed:{relative}")
    if metadata.st_mode & 0o111:
        raise AuditError(f"executable-bootstrap-file:{relative}")
    try:
        text = path.read_text(encoding="ascii")
    except UnicodeDecodeError as error:
        raise AuditError(f"non-ascii-bootstrap-file:{relative}") from error
    if not text.endswith("\n"):
        raise AuditError(f"missing-final-newline:{relative}")
    if len(text) > FILE_MAX_CHARS:
        raise AuditError(f"file-budget-exceeded:{relative}:{len(text)}")
    return text


def audit_bundle(root: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise AuditError("bundle-root-not-directory")

    actual = _relative_file_set(root)
    expected = _expected_relative_files()
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise AuditError(
            "bundle-layout-mismatch:"
            + json.dumps({"missing": missing, "unexpected": unexpected})
        )

    texts: dict[str, str] = {}
    workspace_totals = {workspace: 0 for workspace in EXPECTED_FILES}
    for relative in sorted(actual):
        text = _read_regular_ascii(root / relative, root)
        texts[relative] = text
        workspace = relative.split("/", maxsplit=1)[0] if "/" in relative else "."
        workspace_totals[workspace] += len(text)

        for fragment in FORBIDDEN_FRAGMENTS:
            if fragment in text:
                raise AuditError(f"forbidden-fragment:{relative}:{fragment}")
        if OPAQUE_PLATFORM_ID.search(text):
            raise AuditError(f"opaque-platform-id:{relative}")
        for fragment in ROLE_FORBIDDEN.get(relative, ()):
            if fragment in text:
                raise AuditError(f"role-forbidden-fragment:{relative}:{fragment}")

    for relative, fragments in REQUIRED_FRAGMENTS.items():
        text = texts[relative]
        for fragment in fragments:
            if fragment not in text:
                raise AuditError(f"missing-required-fragment:{relative}:{fragment}")

    for workspace, total in workspace_totals.items():
        if total > WORKSPACE_MAX_CHARS[workspace]:
            raise AuditError(f"workspace-budget-exceeded:{workspace}:{total}")

    total_chars = sum(workspace_totals.values())
    if total_chars > TOTAL_MAX_CHARS:
        raise AuditError(f"bundle-budget-exceeded:{total_chars}")

    return {
        "status": "ok",
        "fileCount": len(actual),
        "totalChars": total_chars,
        "totalMaxChars": TOTAL_MAX_CHARS,
        "workspaceChars": workspace_totals,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = audit_bundle(args.root)
    except (AuditError, FileNotFoundError, OSError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
