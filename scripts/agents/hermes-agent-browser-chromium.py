#!/usr/bin/env python3
"""Select and execute Astra's newest locally installed agent-browser Chromium."""

from __future__ import annotations

import os
from pathlib import Path
import pwd
import re
import stat
import sys


BROWSER_ROOT = Path("/var/lib/hermes/astra/.agent-browser/browsers")
EXPECTED_OWNER = "hermes-astra"
VERSION_RE = re.compile(r"chrome-(\d+(?:\.\d+)+)")


def _version(path: Path) -> tuple[int, ...] | None:
    match = VERSION_RE.fullmatch(path.name)
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def select_browser(root: Path, expected_uid: int) -> Path:
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError("invalid agent-browser root")
    canonical_root = root.resolve(strict=True)
    if canonical_root != root:
        raise ValueError("agent-browser root must be canonical")

    candidates: list[tuple[tuple[int, ...], Path]] = []
    for directory in root.iterdir():
        version = _version(directory)
        if version is None or directory.is_symlink() or not directory.is_dir():
            continue
        if directory.resolve(strict=True).parent != canonical_root:
            continue

        browser = directory / "chrome"
        try:
            browser_stat = browser.lstat()
        except FileNotFoundError:
            continue
        if (
            stat.S_ISLNK(browser_stat.st_mode)
            or not stat.S_ISREG(browser_stat.st_mode)
            or browser.resolve(strict=True) != browser
            or browser_stat.st_uid != expected_uid
            or browser_stat.st_mode & 0o111 == 0
        ):
            continue
        candidates.append((version, browser))

    if not candidates:
        raise FileNotFoundError("no trusted Astra agent-browser Chromium found")
    return max(candidates, key=lambda item: item[0])[1]


def main() -> int:
    try:
        expected_uid = pwd.getpwnam(EXPECTED_OWNER).pw_uid
        browser = select_browser(BROWSER_ROOT, expected_uid)
    except (KeyError, OSError, ValueError) as exc:
        print(f"Hermes agent-browser selector failed: {exc}", file=sys.stderr)
        return 1

    if sys.argv[1:] == ["--check"]:
        print(f"agent-browser-chromium:ok:{browser.parent.name}")
        return 0

    os.execv(browser, [str(browser), *sys.argv[1:]])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
