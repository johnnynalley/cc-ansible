#!/usr/bin/env python3
"""Prepare and verify credential-free OpenClaw Doctor rehearsal state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import stat
import tempfile
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 2
REDACTED = "doctor-rehearsal-redacted"
SECRET_KEYS = {
    "accesstoken",
    "apikey",
    "authorization",
    "clientsecret",
    "cookie",
    "password",
    "refreshtoken",
    "secret",
    "token",
}
SECRET_SUFFIXES = ("_API_KEY", "_PASSWORD", "_SECRET", "_TOKEN")


class RehearsalError(RuntimeError):
    """Raised when a rehearsal safety invariant is not satisfied."""


def canonical_key(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def json_pointer(parts: Iterable[str]) -> str:
    escaped = [part.replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(escaped)


def require_regular_file(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise RehearsalError(f"required file is missing: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RehearsalError(f"required path is not a regular non-symlink file: {path}")


def require_directory(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise RehearsalError(f"required directory is missing: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RehearsalError(f"required path is not a non-symlink directory: {path}")


def ensure_output_parent(path: Path) -> None:
    require_directory(path.parent)
    current = path.parent
    while True:
        metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise RehearsalError(f"output parent traverses a symlink: {current}")
        if current == current.parent:
            break
        current = current.parent


def atomic_write_json(path: Path, payload: Any, mode: int = 0o600) -> None:
    ensure_output_parent(path)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def rewrite_string(
    value: str,
    replacements: list[tuple[str, str]],
) -> tuple[str, bool]:
    for source, target in replacements:
        if value == source:
            return target, True
        if value.startswith(source + os.sep):
            return target + value[len(source) :], True
    return value, False


def sanitize_and_rewrite(
    value: Any,
    *,
    path: tuple[str, ...],
    replacements: list[tuple[str, str]],
    redacted_paths: list[str],
    rewritten_paths: list[str],
) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            child_path = (*path, str(key))
            normalized = canonical_key(str(key))
            upper_key = str(key).upper()
            if normalized in SECRET_KEYS or upper_key.endswith(SECRET_SUFFIXES):
                result[key] = REDACTED
                redacted_paths.append(json_pointer(child_path))
                continue
            result[key] = sanitize_and_rewrite(
                child,
                path=child_path,
                replacements=replacements,
                redacted_paths=redacted_paths,
                rewritten_paths=rewritten_paths,
            )
        return result
    if isinstance(value, list):
        return [
            sanitize_and_rewrite(
                child,
                path=(*path, str(index)),
                replacements=replacements,
                redacted_paths=redacted_paths,
                rewritten_paths=rewritten_paths,
            )
            for index, child in enumerate(value)
        ]
    if isinstance(value, str):
        rewritten, changed = rewrite_string(value, replacements)
        if changed:
            rewritten_paths.append(json_pointer(path))
        return rewritten
    return value


def find_source_references(value: Any, prefixes: tuple[str, ...]) -> list[str]:
    references: list[str] = []

    def visit(child: Any, path: tuple[str, ...]) -> None:
        if isinstance(child, dict):
            for key, nested in child.items():
                visit(nested, (*path, str(key)))
        elif isinstance(child, list):
            for index, nested in enumerate(child):
                visit(nested, (*path, str(index)))
        elif isinstance(child, str) and any(prefix in child for prefix in prefixes):
            references.append(json_pointer(path))

    visit(value, ())
    return references


def parse_plugin_paths(values: list[str]) -> dict[str, Path]:
    plugins: dict[str, Path] = {}
    for value in values:
        plugin_id, separator, raw_path = value.partition("=")
        if not separator or not plugin_id or not raw_path:
            raise RehearsalError(
                "managed plugin paths must use the form plugin-id=/absolute/path"
            )
        if plugin_id in plugins:
            raise RehearsalError(f"duplicate managed plugin id: {plugin_id}")
        path = Path(raw_path)
        if not path.is_absolute():
            raise RehearsalError(f"managed plugin path is not absolute: {raw_path}")
        require_directory(path)
        require_regular_file(path / "openclaw.plugin.json")
        plugins[plugin_id] = path.resolve()
    return plugins


def transform_config(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.source)
    output = Path(args.output)
    require_regular_file(source)
    if output.exists():
        raise RehearsalError(f"refusing to overwrite transformed config: {output}")
    try:
        parsed = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RehearsalError(f"failed to read source config: {error}") from error
    if not isinstance(parsed, dict):
        raise RehearsalError("source config must contain a JSON object")

    source_state = str(Path(args.source_state_root).resolve())
    source_workspace = str(Path(args.source_workspace_root).resolve())
    target_state = str(Path(args.target_state_root).resolve())
    target_workspace = str(Path(args.target_workspace_root).resolve())
    replacements = sorted(
        [(source_workspace, target_workspace), (source_state, target_state)],
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
    redacted_paths: list[str] = []
    rewritten_paths: list[str] = []
    transformed = sanitize_and_rewrite(
        parsed,
        path=(),
        replacements=replacements,
        redacted_paths=redacted_paths,
        rewritten_paths=rewritten_paths,
    )

    if "env" in transformed:
        transformed["env"] = {}
        redacted_paths.append("/env")

    gateway = transformed.setdefault("gateway", {})
    if not isinstance(gateway, dict):
        raise RehearsalError("gateway config must be an object")
    gateway["mode"] = "local"
    gateway["bind"] = "loopback"
    gateway["port"] = args.gateway_port
    gateway.pop("remote", None)
    auth = gateway.setdefault("auth", {})
    if not isinstance(auth, dict):
        auth = {}
        gateway["auth"] = auth
    auth["mode"] = "token"
    auth["token"] = REDACTED
    if "/gateway/auth/token" not in redacted_paths:
        redacted_paths.append("/gateway/auth/token")

    channels = transformed.get("channels")
    disabled_channels: list[str] = []
    if isinstance(channels, dict):
        for channel_id, channel_config in channels.items():
            if channel_id in {"defaults", "modelByChannel"}:
                continue
            if isinstance(channel_config, dict):
                channel_config["enabled"] = False
                disabled_channels.append(str(channel_id))

    update = transformed.get("update")
    if isinstance(update, dict):
        update["checkOnStart"] = False
        auto_update = update.get("auto")
        if isinstance(auto_update, dict):
            auto_update["enabled"] = False

    plugins = transformed.setdefault("plugins", {})
    if not isinstance(plugins, dict):
        raise RehearsalError("plugins config must be an object")
    managed_plugins = parse_plugin_paths(args.plugin_path)
    retired_plugins = set(args.retire_plugin)
    overlap = retired_plugins & set(managed_plugins)
    if overlap:
        raise RehearsalError(
            "plugins cannot be both managed and retired: " + ", ".join(sorted(overlap))
        )

    allow = plugins.get("allow")
    if allow is not None and not isinstance(allow, list):
        raise RehearsalError("plugins.allow must be an array when present")
    retained_allow = [
        plugin_id
        for plugin_id in (allow or [])
        if isinstance(plugin_id, str) and plugin_id not in retired_plugins
    ]
    for plugin_id in sorted(managed_plugins):
        if plugin_id not in retained_allow:
            retained_allow.append(plugin_id)
    plugins["allow"] = retained_allow

    entries = plugins.get("entries")
    if entries is not None and not isinstance(entries, dict):
        raise RehearsalError("plugins.entries must be an object when present")
    if isinstance(entries, dict):
        for plugin_id in retired_plugins:
            entries.pop(plugin_id, None)

    slots = plugins.get("slots")
    if slots is not None and not isinstance(slots, dict):
        raise RehearsalError("plugins.slots must be an object when present")
    retired_slots = {
        slot: plugin_id
        for slot, plugin_id in (slots or {}).items()
        if plugin_id in retired_plugins
    }
    if retired_slots:
        raise RehearsalError(
            "plugin slots still reference retired plugins: "
            + ", ".join(
                f"{slot}={plugin_id}"
                for slot, plugin_id in sorted(retired_slots.items())
            )
        )

    load = plugins.setdefault("load", {})
    if not isinstance(load, dict):
        load = {}
        plugins["load"] = load
    load["paths"] = [
        str(managed_plugins[plugin_id]) for plugin_id in sorted(managed_plugins)
    ]

    remaining = find_source_references(transformed, (source_state, source_workspace))
    if remaining:
        raise RehearsalError(
            "transformed config retains production path references at: "
            + ", ".join(sorted(remaining))
        )
    serialized = json.dumps(transformed, sort_keys=True)
    if any(secret in serialized for secret in args.forbidden_literal):
        raise RehearsalError(
            "transformed config retains an explicitly forbidden literal"
        )

    atomic_write_json(output, transformed)
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "ok",
        "disabledChannels": sorted(disabled_channels),
        "managedPlugins": sorted(managed_plugins),
        "redactedPaths": sorted(set(redacted_paths)),
        "retiredPlugins": sorted(retired_plugins),
        "rewrittenPaths": sorted(set(rewritten_paths)),
        "sourceConfigSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "targetConfigSha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    if args.report:
        atomic_write_json(Path(args.report), result)
    return result


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def sqlite_table_rows(connection: sqlite3.Connection) -> list[tuple[str, str]]:
    return list(
        connection.execute(
            "SELECT name, COALESCE(sql, '') FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    )


def sqlite_quick_check(connection: sqlite3.Connection) -> str:
    rows = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
    return "ok" if rows == ["ok"] else "; ".join(rows)


def sqlite_backup(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.source)
    target = Path(args.target)
    require_regular_file(source)
    ensure_output_parent(target)
    if target.exists():
        raise RehearsalError(f"refusing to overwrite SQLite backup: {target}")

    source_uri = source.resolve().as_uri() + "?mode=ro"
    source_connection = sqlite3.connect(source_uri, uri=True, timeout=30)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.execute("PRAGMA busy_timeout=30000")
        source_connection.backup(target_connection)
        if args.scrub_agent_auth:
            table_names = {name for name, _ in sqlite_table_rows(target_connection)}
            with target_connection:
                for table in ("auth_profile_state", "auth_profile_store"):
                    if table in table_names:
                        target_connection.execute(
                            f"DELETE FROM {quote_identifier(table)}"
                        )
        target_connection.commit()
        quick_check = sqlite_quick_check(target_connection)
        if quick_check != "ok":
            raise RehearsalError(f"SQLite backup quick_check failed: {quick_check}")
        counts: dict[str, int | str] = {}
        for name, create_sql in sqlite_table_rows(target_connection):
            if create_sql.upper().startswith("CREATE VIRTUAL TABLE"):
                counts[name] = "virtual"
                continue
            counts[name] = int(
                target_connection.execute(
                    f"SELECT COUNT(*) FROM {quote_identifier(name)}"
                ).fetchone()[0]
            )
    finally:
        target_connection.close()
        source_connection.close()
    os.chmod(target, 0o600)
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "ok",
        "quickCheck": "ok",
        "scrubbedAgentAuth": bool(args.scrub_agent_auth),
        "tables": counts,
    }
    if args.output:
        atomic_write_json(Path(args.output), result)
    return result


def encode_sqlite_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"blobSha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}
    if isinstance(value, float):
        return {"float": value.hex()}
    return value


def sqlite_summary(args: argparse.Namespace) -> dict[str, Any]:
    database = Path(args.database)
    require_regular_file(database)
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        quick_check = sqlite_quick_check(connection)
        if quick_check != "ok":
            raise RehearsalError(f"SQLite quick_check failed: {quick_check}")
        schema_rows = list(
            connection.execute(
                "SELECT type, name, tbl_name, COALESCE(sql, '') FROM sqlite_master "
                "ORDER BY type, name"
            )
        )
        schema_hash = hashlib.sha256(
            json.dumps(schema_rows, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest()
        table_rows = sqlite_table_rows(connection)
        available_tables = {name for name, _ in table_rows}
        excluded_tables = set(args.exclude_table)
        unknown_exclusions = excluded_tables - available_tables
        if unknown_exclusions:
            raise RehearsalError(
                "SQLite summary excludes unknown tables: "
                + ", ".join(sorted(unknown_exclusions))
            )
        tables: dict[str, Any] = {}
        for name, create_sql in table_rows:
            if name in excluded_tables:
                continue
            if create_sql.upper().startswith("CREATE VIRTUAL TABLE"):
                tables[name] = {"kind": "virtual"}
                continue
            columns = [
                row[1]
                for row in connection.execute(
                    f"PRAGMA table_info({quote_identifier(name)})"
                )
            ]
            order_columns = [
                row[1]
                for row in connection.execute(
                    f"PRAGMA table_info({quote_identifier(name)})"
                )
                if int(row[5]) > 0
            ]
            if not order_columns:
                order_columns = columns
            statement = f"SELECT * FROM {quote_identifier(name)}"
            if order_columns:
                statement += " ORDER BY " + ", ".join(
                    quote_identifier(column) for column in order_columns
                )
            digest = hashlib.sha256()
            row_count = 0
            for row in connection.execute(statement):
                digest.update(
                    json.dumps(
                        [encode_sqlite_value(value) for value in row],
                        separators=(",", ":"),
                        ensure_ascii=True,
                    ).encode()
                )
                digest.update(b"\n")
                row_count += 1
            tables[name] = {
                "kind": "table",
                "rowCount": row_count,
                "rowsSha256": digest.hexdigest(),
            }
    finally:
        connection.close()
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "ok",
        "quickCheck": "ok",
        "excludedTables": sorted(excluded_tables),
        "schemaSha256": schema_hash,
        "tables": tables,
    }
    atomic_write_json(Path(args.output), result)
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def is_excluded(relative_path: str, exclusions: tuple[str, ...]) -> bool:
    return any(
        relative_path == exclusion or relative_path.startswith(exclusion + "/")
        for exclusion in exclusions
    )


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def canonical_plugin_skill_roots(args: argparse.Namespace) -> tuple[Path, ...]:
    roots: set[Path] = set()
    for raw_root in getattr(args, "allow_plugin_skill_target_root", []):
        supplied = Path(raw_root)
        if not supplied.is_absolute():
            raise RehearsalError(
                f"plugin skill target root is not absolute: {supplied}"
            )
        resolved = supplied.resolve(strict=True)
        if supplied != resolved:
            raise RehearsalError(
                f"plugin skill target root is not canonical: {supplied}"
            )
        require_directory(resolved)
        roots.add(resolved)
    return tuple(sorted(roots, key=str))


def manifest_plugin_skill_symlink(
    child: Path,
    relative: str,
    metadata: os.stat_result,
    allowed_roots: tuple[Path, ...],
) -> dict[str, Any]:
    relative_parts = Path(relative).parts
    if len(relative_parts) != 2 or relative_parts[0] != "plugin-skills":
        raise RehearsalError(f"manifest refuses directory symlink: {relative}")
    if not allowed_roots:
        raise RehearsalError(f"manifest refuses directory symlink: {relative}")
    try:
        resolved = child.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise RehearsalError(
            f"plugin skill symlink does not resolve safely: {relative}"
        ) from error
    require_directory(resolved)
    if not any(is_within(resolved, root) for root in allowed_roots):
        raise RehearsalError(
            f"plugin skill symlink escapes reviewed immutable roots: {relative}"
        )
    require_regular_file(resolved / "SKILL.md")
    return {
        "relativePath": relative,
        "type": "symlink",
        "mode": stat.S_IMODE(metadata.st_mode),
        "target": os.readlink(child),
        "resolvedTarget": str(resolved),
    }


def manifest_tree(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root)
    require_directory(root)
    exclusions = tuple(sorted(set(args.exclude)))
    plugin_skill_roots = canonical_plugin_skill_roots(args)
    entries: list[dict[str, Any]] = []
    total_bytes = 0
    for current_root, directories, files in os.walk(root, followlinks=False):
        current = Path(current_root)
        relative_root = current.relative_to(root)
        retained_directories: list[str] = []
        for name in sorted(directories):
            child = current / name
            relative = (relative_root / name).as_posix()
            if is_excluded(relative, exclusions):
                continue
            metadata = child.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                entries.append(
                    manifest_plugin_skill_symlink(
                        child, relative, metadata, plugin_skill_roots
                    )
                )
                continue
            if relative_root.as_posix() == "plugin-skills" and plugin_skill_roots:
                raise RehearsalError(
                    f"plugin skill entry is not a generated symlink: {relative}"
                )
            if not stat.S_ISDIR(metadata.st_mode):
                raise RehearsalError(f"manifest found non-directory entry: {relative}")
            retained_directories.append(name)
            entries.append(
                {
                    "relativePath": relative,
                    "type": "directory",
                    "mode": stat.S_IMODE(metadata.st_mode),
                }
            )
        directories[:] = retained_directories
        for name in sorted(files):
            child = current / name
            relative = (relative_root / name).as_posix()
            if is_excluded(relative, exclusions):
                continue
            metadata = child.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise RehearsalError(f"manifest refuses file symlink: {relative}")
            if relative_root.as_posix() == "plugin-skills" and plugin_skill_roots:
                raise RehearsalError(
                    f"plugin skill entry is not a generated symlink: {relative}"
                )
            if not stat.S_ISREG(metadata.st_mode):
                raise RehearsalError(f"manifest found non-regular file: {relative}")
            total_bytes += metadata.st_size
            entries.append(
                {
                    "relativePath": relative,
                    "type": "file",
                    "mode": stat.S_IMODE(metadata.st_mode),
                    "size": metadata.st_size,
                    "sha256": sha256_file(child),
                }
            )
    entries.sort(key=lambda entry: (entry["relativePath"], entry["type"]))
    result = {
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "status": "ok",
        "root": str(root.resolve()),
        "exclusions": list(exclusions),
        "allowedPluginSkillTargetRoots": [str(path) for path in plugin_skill_roots],
        "entries": entries,
        "summary": {
            "entries": len(entries),
            "files": sum(entry["type"] == "file" for entry in entries),
            "directories": sum(entry["type"] == "directory" for entry in entries),
            "symlinks": sum(entry["type"] == "symlink" for entry in entries),
            "bytes": total_bytes,
        },
    }
    atomic_write_json(Path(args.output), result)
    return result


def diff_manifests(args: argparse.Namespace) -> dict[str, Any]:
    before_path = Path(args.before)
    after_path = Path(args.after)
    require_regular_file(before_path)
    require_regular_file(after_path)
    before = json.loads(before_path.read_text(encoding="utf-8"))
    after = json.loads(after_path.read_text(encoding="utf-8"))
    before_entries = {entry["relativePath"]: entry for entry in before["entries"]}
    after_entries = {entry["relativePath"]: entry for entry in after["entries"]}
    added = sorted(set(after_entries) - set(before_entries))
    removed = sorted(set(before_entries) - set(after_entries))
    modified = sorted(
        path
        for path in set(before_entries) & set(after_entries)
        if before_entries[path] != after_entries[path]
    )
    result = {
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "status": "ok",
        "added": added,
        "removed": removed,
        "modified": modified,
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "modified": len(modified),
        },
    }
    atomic_write_json(Path(args.output), result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    transform = subparsers.add_parser("transform-config")
    transform.add_argument("--source", required=True)
    transform.add_argument("--output", required=True)
    transform.add_argument("--report")
    transform.add_argument("--source-state-root", required=True)
    transform.add_argument("--source-workspace-root", required=True)
    transform.add_argument("--target-state-root", required=True)
    transform.add_argument("--target-workspace-root", required=True)
    transform.add_argument(
        "--plugin-path",
        action="append",
        default=[],
        metavar="ID=PATH",
        help="root-managed plugin path; repeat for every retained external plugin",
    )
    transform.add_argument(
        "--retire-plugin",
        action="append",
        default=[],
        help="legacy global plugin id to remove from the transformed config",
    )
    transform.add_argument("--gateway-port", type=int, default=19789)
    transform.add_argument("--forbidden-literal", action="append", default=[])
    transform.set_defaults(handler=transform_config)

    backup = subparsers.add_parser("sqlite-backup")
    backup.add_argument("--source", required=True)
    backup.add_argument("--target", required=True)
    backup.add_argument("--output")
    backup.add_argument("--scrub-agent-auth", action="store_true")
    backup.set_defaults(handler=sqlite_backup)

    summary = subparsers.add_parser("sqlite-summary")
    summary.add_argument("--database", required=True)
    summary.add_argument("--output", required=True)
    summary.add_argument("--exclude-table", action="append", default=[])
    summary.set_defaults(handler=sqlite_summary)

    manifest = subparsers.add_parser("manifest")
    manifest.add_argument("--root", required=True)
    manifest.add_argument("--output", required=True)
    manifest.add_argument("--exclude", action="append", default=[])
    manifest.add_argument(
        "--allow-plugin-skill-target-root",
        action="append",
        default=[],
        help=(
            "canonical immutable plugin root allowed as a generated "
            "plugin-skills symlink target"
        ),
    )
    manifest.set_defaults(handler=manifest_tree)

    diff = subparsers.add_parser("diff")
    diff.add_argument("--before", required=True)
    diff.add_argument("--after", required=True)
    diff.add_argument("--output", required=True)
    diff.set_defaults(handler=diff_manifests)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = args.handler(args)
    except (OSError, RehearsalError, sqlite3.DatabaseError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")
    print(json.dumps({"status": result.get("status", "ok")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
