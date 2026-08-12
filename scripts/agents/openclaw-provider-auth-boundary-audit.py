#!/usr/bin/env python3
"""Audit the OpenClaw Gateway and Codex provider-auth separation boundary."""

from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
import sqlite3
import stat
import tempfile
from pathlib import Path
from typing import Any


class AuthBoundaryError(RuntimeError):
    """Raised when provider authentication crosses the reviewed boundary."""


AUTH_TABLES = ("auth_profile_state", "auth_profile_store")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuthBoundaryError(message)


def _regular_file(path: Path, label: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise AuthBoundaryError(f"{label}-unavailable") from exc
    _require(stat.S_ISREG(metadata.st_mode), f"{label}-not-regular")
    _require(not path.is_symlink(), f"{label}-symlink")
    return metadata


def _directory(path: Path, label: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise AuthBoundaryError(f"{label}-unavailable") from exc
    _require(stat.S_ISDIR(metadata.st_mode), f"{label}-not-directory")
    _require(not path.is_symlink(), f"{label}-symlink")
    return metadata


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    _regular_file(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthBoundaryError(f"{label}-invalid-json") from exc
    _require(isinstance(value, dict), f"{label}-not-object")
    return value


def _identity_id(value: str, database: str) -> int:
    if value.isdigit():
        return int(value)
    try:
        if database == "user":
            return pwd.getpwnam(value).pw_uid
        return grp.getgrnam(value).gr_gid
    except KeyError as exc:
        raise AuthBoundaryError("executor-auth-identity-unknown") from exc


def _audit_gateway_config(path: Path) -> dict[str, int]:
    config = _load_json_object(path, "gateway-config")
    auth = config.get("auth")
    _require(isinstance(auth, dict), "gateway-auth-not-object")
    profiles = auth.get("profiles")
    order = auth.get("order")
    _require(isinstance(profiles, dict), "gateway-auth-profiles-not-object")
    _require(isinstance(order, dict), "gateway-auth-order-not-object")

    selected_profiles = {
        profile_id.casefold()
        for provider_profiles in order.values()
        if isinstance(provider_profiles, list)
        for profile_id in provider_profiles
        if isinstance(profile_id, str)
    }
    openai_profiles = []
    for profile_id, profile in profiles.items():
        if not isinstance(profile, dict):
            raise AuthBoundaryError("gateway-auth-profile-not-object")
        provider = profile.get("provider")
        if (
            isinstance(profile_id, str) and profile_id.casefold().startswith("openai:")
        ) or (isinstance(provider, str) and provider.casefold() == "openai"):
            openai_profiles.append(str(profile_id))

    _require(not openai_profiles, "gateway-openai-auth-profile-present")
    _require(
        "openai" not in {str(key).casefold() for key in order},
        "gateway-openai-auth-order-present",
    )
    _require(
        not any(profile.startswith("openai:") for profile in selected_profiles),
        "gateway-openai-auth-selected",
    )
    return {"profileCount": len(profiles), "openaiProfileCount": 0}


def _sqlite_auth_counts(path: Path) -> dict[str, int]:
    _regular_file(path, "agent-database")
    connection = sqlite3.connect(
        path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30
    )
    try:
        connection.execute("PRAGMA query_only=ON")
        quick_check = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
        _require(quick_check == ["ok"], "agent-database-quick-check-failed")
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        counts = {
            table: (
                int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                if table in tables
                else 0
            )
            for table in AUTH_TABLES
        }
    except sqlite3.Error as exc:
        raise AuthBoundaryError("agent-database-read-failed") from exc
    finally:
        connection.close()
    for table, count in counts.items():
        _require(count == 0, f"gateway-agent-auth-not-empty:{table}")
    return counts


def _audit_gateway_state(state_root: Path, agents: list[str]) -> list[dict[str, Any]]:
    _directory(state_root, "gateway-state")
    agents_root = state_root / "agents"
    _directory(agents_root, "gateway-agents-state")
    expected_agents = set(agents)
    actual_agents = {
        entry.name
        for entry in os.scandir(agents_root)
        if entry.is_dir(follow_symlinks=False)
    }
    _require(
        actual_agents <= expected_agents,
        "unexpected-gateway-agent-state:"
        + ",".join(sorted(actual_agents - expected_agents)),
    )

    results = []
    for agent in agents:
        agent_root = agents_root / agent / "agent"
        legacy_auth = agent_root / "auth-profiles.json"
        _require(not os.path.lexists(legacy_auth), f"legacy-auth-file-present:{agent}")
        database = agent_root / "openclaw-agent.sqlite"
        counts = (
            _sqlite_auth_counts(database)
            if os.path.lexists(database)
            else {table: 0 for table in AUTH_TABLES}
        )
        results.append(
            {
                "agent": agent,
                "databasePresent": os.path.lexists(database),
                "authProfileStateRows": counts["auth_profile_state"],
                "authProfileStoreRows": counts["auth_profile_store"],
            }
        )
    return results


def _audit_executor_auth(path: Path, owner: str, group: str) -> dict[str, Any]:
    metadata = _regular_file(path, "executor-auth")
    owner_uid = _identity_id(owner, "user")
    group_gid = _identity_id(group, "group")
    _require(metadata.st_uid == owner_uid, "executor-auth-owner")
    _require(metadata.st_gid == group_gid, "executor-auth-group")
    _require(stat.S_IMODE(metadata.st_mode) == 0o600, "executor-auth-mode")
    _require(metadata.st_size > 0, "executor-auth-empty")
    return {"present": True, "mode": "0600", "bytes": metadata.st_size}


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def audit(args: argparse.Namespace) -> dict[str, Any]:
    agents = list(dict.fromkeys(args.agent))
    _require(bool(agents), "agents-empty")
    config_result = _audit_gateway_config(args.gateway_config)
    state_result = _audit_gateway_state(args.gateway_state, agents)
    executor_result = _audit_executor_auth(
        args.executor_auth, args.executor_owner, args.executor_group
    )
    return {
        "schemaVersion": 1,
        "status": "ok",
        "gatewayConfig": config_result,
        "gatewayAgents": state_result,
        "executorAuth": executor_result,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-config", type=Path, required=True)
    parser.add_argument("--gateway-state", type=Path, required=True)
    parser.add_argument("--executor-auth", type=Path, required=True)
    parser.add_argument("--executor-owner", default="openclaw-codex")
    parser.add_argument("--executor-group", default="openclaw-codex")
    parser.add_argument("--agent", action="append", default=[])
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = audit(args)
        if args.output:
            _atomic_write(args.output, result)
    except (AuthBoundaryError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
