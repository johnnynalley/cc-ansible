#!/usr/bin/env python3
"""Prove that profile transcript sources belong only to approved public routes."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


MAX_INDEX_BYTES = 64 * 1024 * 1024
DISCORD_ID_RE = re.compile(r"(?<!\d)\d{17,20}(?!\d)")
ROUTE_FIELDS = (
    "channel",
    "chatType",
    "deliveryContext",
    "groupChannel",
    "groupId",
    "lastChannel",
    "lastThreadId",
    "lastTo",
    "origin",
    "route",
    "space",
)
SOURCE_CLASSES = (
    "approved-public",
    "unresolved-thread-parent",
    "direct",
    "other-channel",
    "unknown-route",
    "conflicting-route-evidence",
    "unindexed",
)


class PrivacyAuditError(RuntimeError):
    """Raised when source or route evidence violates the reviewed boundary."""


@dataclass(frozen=True)
class SourceManifest:
    names: tuple[str, ...]
    bytes: int
    sha256: str


def require(value: bool, code: str) -> None:
    if not value:
        raise PrivacyAuditError(code)


def regular_file(path: Path, label: str, max_bytes: int) -> tuple[Path, bytes]:
    require(path.is_absolute(), f"{label}-relative")
    info = os.lstat(path)
    require(stat.S_ISREG(info.st_mode), f"{label}-not-regular")
    require(not stat.S_ISLNK(info.st_mode), f"{label}-symlink")
    require(info.st_size <= max_bytes, f"{label}-too-large")
    raw = path.read_bytes()
    after = os.lstat(path)
    require(
        (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
        f"{label}-race",
    )
    return path.resolve(strict=True), raw


def source_manifest(source_dir: Path) -> SourceManifest:
    require(source_dir.is_absolute(), "source-relative")
    info = os.lstat(source_dir)
    require(stat.S_ISDIR(info.st_mode), "source-not-directory")
    require(not stat.S_ISLNK(info.st_mode), "source-directory-symlink")
    names: list[str] = []
    total_bytes = 0
    aggregate = hashlib.sha256()
    for entry in sorted(os.scandir(source_dir), key=lambda item: item.name):
        if not entry.name.endswith(".jsonl") or entry.name.endswith(
            ".trajectory.jsonl"
        ):
            continue
        path = source_dir / entry.name
        before = os.lstat(path)
        require(stat.S_ISREG(before.st_mode), "source-session-not-regular")
        require(not stat.S_ISLNK(before.st_mode), "source-session-symlink")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
                total_bytes += len(chunk)
        after = os.lstat(path)
        require(
            (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            )
            == (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ),
            "source-race",
        )
        names.append(path.name)
        aggregate.update(path.name.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(str(after.st_size).encode("ascii"))
        aggregate.update(b"\0")
        aggregate.update(digest.hexdigest().encode("ascii"))
        aggregate.update(b"\n")
    require(bool(names), "source-session-set-empty")
    return SourceManifest(tuple(names), total_bytes, aggregate.hexdigest())


def write_approved_manifest(
    path: Path,
    source: SourceManifest,
    approved_names: list[str],
    policy_digest: str,
    index_digest: str,
) -> str:
    require(path.is_absolute(), "approved-manifest-relative")
    parent = path.parent
    parent_info = os.lstat(parent)
    require(stat.S_ISDIR(parent_info.st_mode), "approved-manifest-parent-not-directory")
    require(not stat.S_ISLNK(parent_info.st_mode), "approved-manifest-parent-symlink")
    if path.exists() or path.is_symlink():
        target_info = os.lstat(path)
        require(stat.S_ISREG(target_info.st_mode), "approved-manifest-not-regular")
        require(not stat.S_ISLNK(target_info.st_mode), "approved-manifest-symlink")
    require(bool(approved_names), "approved-manifest-empty")
    payload = {
        "schemaVersion": 1,
        "status": "approved-public-subset",
        "sourceFileCount": len(source.names),
        "sourceBytes": source.bytes,
        "sourceManifestSha256": source.sha256,
        "sessionIndexManifestSha256": index_digest,
        "policySha256": policy_digest,
        "approvedFileCount": len(approved_names),
        "approvedFiles": approved_names,
    }
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=parent
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as target:
            target.write(encoded)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return hashlib.sha256(encoded).hexdigest()


def load_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    _, raw = regular_file(path, label, MAX_INDEX_BYTES)
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PrivacyAuditError(f"{label}-invalid-json") from exc
    require(isinstance(payload, dict), f"{label}-invalid-shape")
    return payload, hashlib.sha256(raw).hexdigest()


def text_set(value: Any, label: str) -> set[str]:
    require(isinstance(value, list) and bool(value), f"{label}-invalid")
    result: set[str] = set()
    for item in value:
        require(isinstance(item, str) and item, f"{label}-invalid")
        require(DISCORD_ID_RE.fullmatch(item) is not None, f"{label}-invalid")
        require(item not in result, f"{label}-duplicate")
        result.add(item)
    return result


def load_policy(path: Path) -> tuple[set[str], set[str], str]:
    payload, digest = load_json(path, "policy")
    require(payload.get("schemaVersion") == 1, "policy-schema")
    require(set(payload) == {"schemaVersion", "guilds", "channels", "fileRoots"}, "policy-fields")
    require(payload.get("fileRoots") == [], "policy-file-roots-not-empty")
    return (
        text_set(payload.get("guilds"), "policy-guilds"),
        text_set(payload.get("channels"), "policy-channels"),
        digest,
    )


def nested_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from nested_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from nested_strings(item)


def route_class(
    session_key: str,
    entry: dict[str, Any],
    approved_guilds: set[str],
    approved_channels: set[str],
) -> str:
    route_values: list[Any] = [session_key]
    route_values.extend(entry.get(field) for field in ROUTE_FIELDS)
    strings = list(nested_strings(route_values))
    lowered = {value.lower() for value in strings}
    ids = {
        match.group(0)
        for value in strings
        for match in DISCORD_ID_RE.finditer(value)
    }
    origin = entry.get("origin") if isinstance(entry.get("origin"), dict) else {}
    chat_type = entry.get("chatType") or origin.get("chatType")
    provider_discord = "discord" in lowered or any(
        "discord" in value.lower() for value in strings
    )
    direct = chat_type == "direct" or any(
        token in {"direct", "dm"}
        for value in lowered
        for token in re.split(r"[^a-z]+", value)
        if token
    )
    if provider_discord and direct:
        return "direct"
    if not provider_discord or chat_type != "channel":
        return "unknown-route"
    guild_match = bool(ids & approved_guilds)
    channel_match = bool(ids & approved_channels)
    has_thread = any(
        entry.get(field) not in (None, "")
        for field in ("lastThreadId",)
    ) or any(
        isinstance(container, dict)
        and any(container.get(field) not in (None, "") for field in ("thread", "threadId"))
        for container in (entry.get("deliveryContext"), entry.get("origin"), entry.get("route"))
    )
    if guild_match and channel_match:
        return "approved-public"
    if guild_match and has_thread:
        return "unresolved-thread-parent"
    return "other-channel"


def audit(args: argparse.Namespace) -> dict[str, Any]:
    before = source_manifest(args.source_dir)
    source_root = args.source_dir.resolve(strict=True)
    source_names = set(before.names)
    approved_guilds, approved_channels, policy_digest = load_policy(args.policy)
    evidence: dict[str, set[str]] = collections.defaultdict(set)
    index_entries = 0
    file_pointers = 0
    relocated_file_pointers = 0
    stale_file_pointers = 0
    no_file_pointers = 0
    index_aggregate = hashlib.sha256()

    require(bool(args.session_index), "session-index-set-empty")
    for ordinal, path in enumerate(args.session_index):
        payload, digest = load_json(path, f"session-index-{ordinal}")
        index_aggregate.update(str(ordinal).encode("ascii"))
        index_aggregate.update(b"\0")
        index_aggregate.update(digest.encode("ascii"))
        index_aggregate.update(b"\n")
        for session_key, entry in payload.items():
            if session_key == "_README":
                continue
            require(isinstance(entry, dict), "session-index-entry-invalid")
            index_entries += 1
            session_file = entry.get("sessionFile")
            if session_file is None:
                no_file_pointers += 1
                continue
            require(
                isinstance(session_file, str) and session_file,
                "session-file-invalid",
            )
            candidate = Path(session_file)
            require(candidate.is_absolute(), "session-file-relative")
            if candidate.name not in source_names:
                stale_file_pointers += 1
                continue
            canonical = source_root / candidate.name
            require(canonical.is_file(), "canonical-session-missing")
            if candidate.parent != source_root:
                relocated_file_pointers += 1
            if candidate.exists():
                item = os.lstat(candidate)
                require(stat.S_ISREG(item.st_mode), "session-file-not-regular")
                require(not stat.S_ISLNK(item.st_mode), "session-file-symlink")
            file_pointers += 1
            evidence[canonical.name].add(
                route_class(
                    session_key,
                    entry,
                    approved_guilds,
                    approved_channels,
                )
            )

    classes: collections.Counter[str] = collections.Counter()
    approved_names: list[str] = []
    for name in before.names:
        classifications = evidence.get(name, set())
        if not classifications:
            classes["unindexed"] += 1
        elif len(classifications) != 1:
            classes["conflicting-route-evidence"] += 1
        else:
            classification = next(iter(classifications))
            classes[classification] += 1
            if classification == "approved-public":
                approved_names.append(name)
    classes = collections.Counter({name: classes[name] for name in SOURCE_CLASSES})
    blockers = [
        name
        for name in SOURCE_CLASSES
        if name != "approved-public" and classes[name]
    ]
    after = source_manifest(args.source_dir)
    require(before == after, "source-manifest-drift")
    output = {
        "schemaVersion": 1,
        "status": "approved" if not blockers else "blocked",
        "sourceFiles": len(before.names),
        "sourceBytes": before.bytes,
        "sourceManifestSha256": before.sha256,
        "sessionIndexes": len(args.session_index),
        "sessionIndexManifestSha256": index_aggregate.hexdigest(),
        "sessionIndexEntries": index_entries,
        "sessionFilePointers": file_pointers,
        "relocatedSessionFilePointers": relocated_file_pointers,
        "staleSessionFilePointers": stale_file_pointers,
        "sessionEntriesWithoutFilePointers": no_file_pointers,
        "policySha256": policy_digest,
        "sourceClassifications": dict(classes),
        "blockers": blockers,
    }
    approved_manifest = getattr(args, "approved_manifest", None)
    if approved_manifest is not None:
        output["approvedSelectionSha256"] = write_approved_manifest(
            approved_manifest,
            before,
            approved_names,
            policy_digest,
            index_aggregate.hexdigest(),
        )
    return output


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--source-dir", type=Path, required=True)
    value.add_argument("--session-index", type=Path, action="append", default=[])
    value.add_argument("--policy", type=Path, required=True)
    value.add_argument("--approved-manifest", type=Path)
    return value


def main() -> int:
    try:
        output = audit(parser().parse_args())
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0 if output["status"] == "approved" else 2
    except (OSError, PrivacyAuditError) as exc:
        code = str(exc) if isinstance(exc, PrivacyAuditError) else type(exc).__name__
        print(f"hermes-profile-memory-privacy-audit-error:{code}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
