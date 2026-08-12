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

SCHEMA_VERSION = 4
MANIFEST_SCHEMA_VERSION = 3
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
    removed_credential_paths: list[str],
    rewritten_paths: list[str],
) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            child_path = (*path, str(key))
            normalized = canonical_key(str(key))
            upper_key = str(key).upper()
            if normalized in SECRET_KEYS or upper_key.endswith(SECRET_SUFFIXES):
                removed_credential_paths.append(json_pointer(child_path))
                continue
            result[key] = sanitize_and_rewrite(
                child,
                path=child_path,
                replacements=replacements,
                removed_credential_paths=removed_credential_paths,
                rewritten_paths=rewritten_paths,
            )
        return result
    if isinstance(value, list):
        return [
            sanitize_and_rewrite(
                child,
                path=(*path, str(index)),
                replacements=replacements,
                removed_credential_paths=removed_credential_paths,
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


def parse_plugin_ids(values: list[str]) -> set[str]:
    plugins: set[str] = set()
    for value in values:
        plugin_id = value.strip()
        if not plugin_id:
            raise RehearsalError("managed plugin id cannot be empty")
        if plugin_id in plugins:
            raise RehearsalError(f"duplicate managed plugin id: {plugin_id}")
        plugins.add(plugin_id)
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
    gateway_secret_file = Path(args.gateway_secret_file)
    if not gateway_secret_file.is_absolute():
        raise RehearsalError("Gateway secret file must be an absolute path")
    require_regular_file(gateway_secret_file)
    gateway_secret_metadata = gateway_secret_file.stat()
    if stat.S_IMODE(gateway_secret_metadata.st_mode) & 0o077:
        raise RehearsalError("Gateway secret file must be owner-readable only")
    if gateway_secret_file.resolve().parent != output.resolve().parent:
        raise RehearsalError(
            "Gateway secret file must remain inside the generated config directory"
        )
    replacements = sorted(
        [(source_workspace, target_workspace), (source_state, target_state)],
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
    removed_credential_paths: list[str] = []
    rewritten_paths: list[str] = []
    transformed = sanitize_and_rewrite(
        parsed,
        path=(),
        replacements=replacements,
        removed_credential_paths=removed_credential_paths,
        rewritten_paths=rewritten_paths,
    )

    if "env" in transformed:
        transformed["env"] = {}
        removed_credential_paths.append("/env")

    replaced_secret_provider_config = "secrets" in transformed
    transformed["secrets"] = {
        "providers": {
            "doctor_rehearsal": {
                "source": "file",
                "path": str(gateway_secret_file.resolve()),
                "mode": "json",
            }
        },
        "defaults": {"file": "doctor_rehearsal"},
    }

    gateway = transformed.setdefault("gateway", {})
    if not isinstance(gateway, dict):
        raise RehearsalError("gateway config must be an object")
    gateway["mode"] = "local"
    gateway["bind"] = "loopback"
    gateway["port"] = args.gateway_port
    gateway.pop("remote", None)
    gateway["auth"] = {
        "mode": "token",
        "token": {
            "source": "file",
            "provider": "doctor_rehearsal",
            "id": "/gateway/token",
        },
        "allowTailscale": False,
        "rateLimit": {
            "maxAttempts": 5,
            "windowMs": 60000,
            "lockoutMs": 300000,
            "exemptLoopback": False,
        },
    }
    gateway["tailscale"] = {"mode": "off", "resetOnExit": False}

    channels = transformed.pop("channels", None)
    disabled_channels: list[str] = []
    if isinstance(channels, dict):
        for channel_id in channels:
            if channel_id in {"defaults", "modelByChannel"}:
                continue
            disabled_channels.append(str(channel_id))

    disabled_memory_search_paths: list[str] = []
    if getattr(args, "disable_memory_search", False):
        memory_search_candidates: list[tuple[tuple[str, ...], Any]] = [
            (("memorySearch",), transformed.get("memorySearch")),
        ]
        agents = transformed.get("agents")
        if isinstance(agents, dict):
            defaults = agents.get("defaults")
            if isinstance(defaults, dict):
                memory_search_candidates.append(
                    (
                        ("agents", "defaults", "memorySearch"),
                        defaults.get("memorySearch"),
                    )
                )
            agent_entries = agents.get("list")
            if isinstance(agent_entries, list):
                for index, agent in enumerate(agent_entries):
                    if isinstance(agent, dict):
                        memory_search_candidates.append(
                            (
                                ("agents", "list", str(index), "memorySearch"),
                                agent.get("memorySearch"),
                            )
                        )
        for candidate_path, memory_search in memory_search_candidates:
            if memory_search is None:
                continue
            if not isinstance(memory_search, dict):
                raise RehearsalError(
                    "memorySearch config must be an object when present: "
                    + json_pointer(candidate_path)
                )
            memory_search["enabled"] = False
            disabled_memory_search_paths.append(json_pointer(candidate_path))

    update = transformed.get("update")
    if isinstance(update, dict):
        update["checkOnStart"] = False
        auto_update = update.get("auto")
        if isinstance(auto_update, dict):
            auto_update["enabled"] = False

    plugins = transformed.setdefault("plugins", {})
    if not isinstance(plugins, dict):
        raise RehearsalError("plugins config must be an object")
    plugins.pop("installs", None)
    managed_plugins = parse_plugin_ids(args.managed_plugin)
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
    if entries is None:
        entries = {}
        plugins["entries"] = entries
    if isinstance(entries, dict):
        for plugin_id in retired_plugins:
            entries.pop(plugin_id, None)

    disabled_runtime_plugins = set(getattr(args, "disable_plugin_runtime", []))
    unmanaged_disabled_plugins = disabled_runtime_plugins - set(managed_plugins)
    if unmanaged_disabled_plugins:
        raise RehearsalError(
            "runtime-disabled plugins are not managed plugins: "
            + ", ".join(sorted(unmanaged_disabled_plugins))
        )
    for plugin_id in sorted(disabled_runtime_plugins):
        entry = entries.setdefault(plugin_id, {})
        if not isinstance(entry, dict):
            raise RehearsalError(
                f"plugin entry must be an object when present: {plugin_id}"
            )
        entry["enabled"] = False

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

    suspended_plugin_slots: dict[str, str] = {}
    if getattr(args, "suspend_managed_plugin_slots", False) and slots:
        suspended_plugin_slots = {
            slot: plugin_id
            for slot, plugin_id in slots.items()
            if plugin_id in managed_plugins
        }
        retained_slots = {
            slot: plugin_id
            for slot, plugin_id in slots.items()
            if plugin_id not in managed_plugins
        }
        if retained_slots:
            plugins["slots"] = retained_slots
        else:
            plugins.pop("slots", None)

    plugins.pop("load", None)

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
        "disabledMemorySearchPaths": sorted(disabled_memory_search_paths),
        "disabledRuntimePlugins": sorted(disabled_runtime_plugins),
        "managedPlugins": sorted(managed_plugins),
        "gatewayAuth": "fresh-file-secretref",
        "replacedSecretProviderConfig": replaced_secret_provider_config,
        "removedCredentialPaths": sorted(set(removed_credential_paths)),
        "retiredPlugins": sorted(retired_plugins),
        "rewrittenPaths": sorted(set(rewritten_paths)),
        "sourceConfigSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "suspendedPluginSlots": suspended_plugin_slots,
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


def sqlite_checkpoint(args: argparse.Namespace) -> dict[str, Any]:
    database = Path(args.database)
    require_regular_file(database)

    connection = sqlite3.connect(database, timeout=30)
    try:
        connection.execute("PRAGMA busy_timeout=30000")
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
        checkpoint_row = connection.execute(
            "PRAGMA wal_checkpoint(TRUNCATE)"
        ).fetchone()
        if checkpoint_row is None or len(checkpoint_row) != 3:
            raise RehearsalError("SQLite checkpoint returned an invalid result")
        busy, log_frames, checkpointed_frames = (int(value) for value in checkpoint_row)
        if busy != 0:
            raise RehearsalError(
                f"SQLite checkpoint remained busy with {log_frames} WAL frames"
            )
        if log_frames not in {-1, 0} or checkpointed_frames not in {-1, 0}:
            raise RehearsalError(
                "SQLite TRUNCATE checkpoint left uncheckpointed WAL frames: "
                f"log={log_frames}, checkpointed={checkpointed_frames}"
            )
        quick_check = sqlite_quick_check(connection)
        if quick_check != "ok":
            raise RehearsalError(f"SQLite checkpoint quick_check failed: {quick_check}")
    finally:
        connection.close()

    removed_sidecars: list[str] = []
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{database}{suffix}")
        try:
            metadata = sidecar.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RehearsalError(
                f"SQLite sidecar is not a regular non-symlink file: {sidecar}"
            )
        if suffix == "-wal" and metadata.st_size != 0:
            raise RehearsalError(
                f"SQLite WAL remains non-empty after TRUNCATE checkpoint: {sidecar}"
            )
        sidecar.unlink()
        removed_sidecars.append(sidecar.name)

    immutable_uri = database.resolve().as_uri() + "?mode=ro&immutable=1"
    verification = sqlite3.connect(immutable_uri, uri=True)
    try:
        quick_check = sqlite_quick_check(verification)
        if quick_check != "ok":
            raise RehearsalError(
                f"checkpointed SQLite immutable quick_check failed: {quick_check}"
            )
    finally:
        verification.close()

    result = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "ok",
        "journalMode": journal_mode,
        "checkpoint": {
            "busy": busy,
            "checkpointedFrames": checkpointed_frames,
            "logFrames": log_frames,
        },
        "quickCheck": "ok",
        "removedSidecars": sorted(removed_sidecars),
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


def parse_ignored_sqlite_columns(
    values: list[str], available_columns: dict[str, list[str]]
) -> dict[str, set[str]]:
    ignored: dict[str, set[str]] = {}
    for value in values:
        table, separator, column = value.partition(".")
        if not separator or not table or not column:
            raise RehearsalError(
                "ignored SQLite columns must use the form table.column"
            )
        if table not in available_columns:
            raise RehearsalError(f"ignored SQLite column uses unknown table: {table}")
        if column not in available_columns[table]:
            raise RehearsalError(
                f"ignored SQLite column does not exist: {table}.{column}"
            )
        ignored.setdefault(table, set()).add(column)
    for table, columns in ignored.items():
        if len(columns) == len(available_columns[table]):
            raise RehearsalError(
                f"refusing to ignore every column in SQLite table: {table}"
            )
    return ignored


def sqlite_summary(args: argparse.Namespace) -> dict[str, Any]:
    database = Path(args.database)
    require_regular_file(database)
    connection = sqlite3.connect(
        database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True
    )
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
        available_columns = {
            name: [
                row[1]
                for row in connection.execute(
                    f"PRAGMA table_info({quote_identifier(name)})"
                )
            ]
            for name, create_sql in table_rows
            if not create_sql.upper().startswith("CREATE VIRTUAL TABLE")
        }
        ignored_columns = parse_ignored_sqlite_columns(
            args.ignore_column, available_columns
        )
        ignored_excluded_tables = set(ignored_columns) & excluded_tables
        if ignored_excluded_tables:
            raise RehearsalError(
                "SQLite summary cannot ignore columns in excluded tables: "
                + ", ".join(sorted(ignored_excluded_tables))
            )
        tables: dict[str, Any] = {}
        for name, create_sql in table_rows:
            if name in excluded_tables:
                continue
            if create_sql.upper().startswith("CREATE VIRTUAL TABLE"):
                tables[name] = {"kind": "virtual"}
                continue
            columns = [
                column
                for column in available_columns[name]
                if column not in ignored_columns.get(name, set())
            ]
            order_columns = [
                row[1]
                for row in connection.execute(
                    f"PRAGMA table_info({quote_identifier(name)})"
                )
                if int(row[5]) > 0 and row[1] in columns
            ]
            if not order_columns:
                order_columns = columns
            statement = "SELECT " + ", ".join(
                quote_identifier(column) for column in columns
            )
            statement += f" FROM {quote_identifier(name)}"
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
                "columns": columns,
                "ignoredColumns": sorted(ignored_columns.get(name, set())),
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
        "ignoredColumns": {
            table: sorted(columns) for table, columns in sorted(ignored_columns.items())
        },
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


def canonical_symlink_target_roots(args: argparse.Namespace) -> tuple[Path, ...]:
    roots: set[Path] = set()
    for raw_root in getattr(args, "allow_symlink_target_root", []):
        supplied = Path(raw_root)
        if not supplied.is_absolute():
            raise RehearsalError(f"symlink target root is not absolute: {supplied}")
        resolved = supplied.resolve(strict=True)
        if supplied != resolved:
            raise RehearsalError(f"symlink target root is not canonical: {supplied}")
        require_directory(resolved)
        roots.add(resolved)
    return tuple(sorted(roots, key=str))


def manifest_safe_symlink(
    child: Path,
    relative: str,
    metadata: os.stat_result,
    allowed_roots: tuple[Path, ...],
) -> dict[str, Any]:
    try:
        resolved = child.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise RehearsalError(
            f"manifest symlink does not resolve safely: {relative}"
        ) from error
    if not any(is_within(resolved, root) for root in allowed_roots):
        raise RehearsalError(f"manifest symlink escapes reviewed roots: {relative}")
    if not resolved.is_dir() and not resolved.is_file():
        raise RehearsalError(
            f"manifest symlink target is not a regular file or directory: {relative}"
        )
    return {
        "relativePath": relative,
        "type": "symlink",
        "mode": stat.S_IMODE(metadata.st_mode),
        "uid": metadata.st_uid,
        "gid": metadata.st_gid,
        "target": os.readlink(child),
        "resolvedTarget": str(resolved),
        "targetType": "directory" if resolved.is_dir() else "file",
    }


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
        "uid": metadata.st_uid,
        "gid": metadata.st_gid,
        "target": os.readlink(child),
        "resolvedTarget": str(resolved),
    }


def manifest_tree(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root)
    require_directory(root)
    exclusions = tuple(sorted(set(args.exclude)))
    plugin_skill_roots = canonical_plugin_skill_roots(args)
    symlink_target_roots = canonical_symlink_target_roots(args)
    root_metadata = root.lstat()
    entries: list[dict[str, Any]] = [
        {
            "relativePath": ".",
            "type": "directory",
            "mode": stat.S_IMODE(root_metadata.st_mode),
            "uid": root_metadata.st_uid,
            "gid": root_metadata.st_gid,
        }
    ]
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
                if relative_root.as_posix() == "plugin-skills":
                    entries.append(
                        manifest_plugin_skill_symlink(
                            child, relative, metadata, plugin_skill_roots
                        )
                    )
                elif symlink_target_roots:
                    entries.append(
                        manifest_safe_symlink(
                            child, relative, metadata, symlink_target_roots
                        )
                    )
                else:
                    raise RehearsalError(
                        f"manifest refuses directory symlink: {relative}"
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
                    "uid": metadata.st_uid,
                    "gid": metadata.st_gid,
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
                if symlink_target_roots:
                    entries.append(
                        manifest_safe_symlink(
                            child, relative, metadata, symlink_target_roots
                        )
                    )
                    continue
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
                    "uid": metadata.st_uid,
                    "gid": metadata.st_gid,
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
        "allowedSymlinkTargetRoots": [str(path) for path in symlink_target_roots],
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
        "--managed-plugin",
        action="append",
        default=[],
        help="retained external plugin id; repeat for every managed plugin",
    )
    transform.add_argument(
        "--retire-plugin",
        action="append",
        default=[],
        help="legacy global plugin id to remove from the transformed config",
    )
    transform.add_argument(
        "--suspend-managed-plugin-slots",
        action="store_true",
        help=(
            "temporarily remove slots owned by managed plugins while copied "
            "legacy install records are retired"
        ),
    )
    transform.add_argument(
        "--disable-memory-search",
        action="store_true",
        help="disable configured embedding search in the credential-free copy",
    )
    transform.add_argument(
        "--disable-plugin-runtime",
        action="append",
        default=[],
        help=(
            "managed external-service plugin to preserve but disable only in "
            "the credential-free rehearsal"
        ),
    )
    transform.add_argument("--gateway-port", type=int, default=19789)
    transform.add_argument("--gateway-secret-file", required=True)
    transform.add_argument("--forbidden-literal", action="append", default=[])
    transform.set_defaults(handler=transform_config)

    backup = subparsers.add_parser("sqlite-backup")
    backup.add_argument("--source", required=True)
    backup.add_argument("--target", required=True)
    backup.add_argument("--output")
    backup.add_argument("--scrub-agent-auth", action="store_true")
    backup.set_defaults(handler=sqlite_backup)

    checkpoint = subparsers.add_parser("sqlite-checkpoint")
    checkpoint.add_argument("--database", required=True)
    checkpoint.add_argument("--output")
    checkpoint.set_defaults(handler=sqlite_checkpoint)

    summary = subparsers.add_parser("sqlite-summary")
    summary.add_argument("--database", required=True)
    summary.add_argument("--output", required=True)
    summary.add_argument("--exclude-table", action="append", default=[])
    summary.add_argument(
        "--ignore-column",
        action="append",
        default=[],
        metavar="TABLE.COLUMN",
    )
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
    manifest.add_argument(
        "--allow-symlink-target-root",
        action="append",
        default=[],
        help="canonical root allowed for explicitly reviewed manifest symlinks",
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
