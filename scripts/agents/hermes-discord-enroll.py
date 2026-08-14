#!/usr/bin/env python3
"""Privately enroll the existing OpenClaw Discord identities into Hermes."""

from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MAX_INPUT_BYTES = 2_000_000
API_ROOT = "https://discord.com/api/v10"
PROFILE_GROUPS = {
    "astra": "hermes-astra",
    "dubble": "hermes-dubble",
    "rigel": "hermes-rigel",
}
EXPECTED_CHANNELS = {
    "astra": ("astra", "astra-logs", "rigel"),
    "dubble": ("db", "db-logs"),
}
RIGEL_PROMPT = (
    "This is the dedicated Rigel academic channel. Act as Johnny's academic "
    "study and deadline assistant. Use verified course records, calendar data, "
    "and explicit user facts only. Never infer an exam, deadline, course, "
    "mastery claim, or alert from the channel name, archived text, generated "
    "memory, or a prior alert. Interactive tutoring remains available when a "
    "semester is inactive. Keep answers concise and never emit control tokens, "
    "hidden reasoning, tool errors, heartbeat acknowledgements, or all-clear "
    "summaries."
)


class EnrollmentError(RuntimeError):
    """A fail-closed enrollment precondition or write failure."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise EnrollmentError(code)


def regular_private_file(
    path: Path, label: str, *, allow_group_read: bool = False
) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise EnrollmentError(f"{label}-unavailable") from exc
    require(stat.S_ISREG(metadata.st_mode) and not path.is_symlink(), f"{label}-unsafe")
    require(metadata.st_size <= MAX_INPUT_BYTES, f"{label}-too-large")
    forbidden_mode = 0o037 if allow_group_read else 0o077
    require(metadata.st_mode & forbidden_mode == 0, f"{label}-permissions")
    return metadata


def read_text(path: Path, label: str, *, allow_group_read: bool = False) -> str:
    regular_private_file(path, label, allow_group_read=allow_group_read)
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            value = handle.read(MAX_INPUT_BYTES + 1)
    except (OSError, UnicodeError) as exc:
        raise EnrollmentError(f"{label}-unreadable") from exc
    require(len(value.encode("utf-8")) <= MAX_INPUT_BYTES, f"{label}-too-large")
    return value


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(read_text(path, label))
    except json.JSONDecodeError as exc:
        raise EnrollmentError(f"{label}-invalid-json") from exc
    require(isinstance(payload, dict), f"{label}-not-object")
    return payload


def read_dotenv(path: Path, *, allow_group_read: bool = False) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in read_text(
        path, "source-env", allow_group_read=allow_group_read
    ).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        require("=" in line, "source-env-invalid-line")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        require(key.replace("_", "").isalnum() and key[:1].isalpha(), "source-env-key")
        require("\n" not in value and "\r" not in value, "source-env-value")
        values[key] = value
    return values


def secret(values: dict[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    require(20 <= len(value) <= 4096, f"missing-{key.lower()}")
    return value


def api_json(token: str, path: str) -> Any:
    request = urllib.request.Request(
        f"{API_ROOT}{path}",
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": "ARK-Hermes-Cutover/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            require(response.status == 200, "discord-api-status")
            content = response.read(MAX_INPUT_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise EnrollmentError("discord-api-unavailable") from exc
    require(len(content) <= MAX_INPUT_BYTES, "discord-api-response-too-large")
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise EnrollmentError("discord-api-invalid-json") from exc


def bot_and_channels(
    token: str,
    names: tuple[str, ...],
    source_channel_ids: set[str],
) -> tuple[str, dict[str, str]]:
    identity = api_json(token, "/users/@me")
    require(isinstance(identity, dict), "discord-identity-invalid")
    bot_id = str(identity.get("id", ""))
    require(bot_id.isdigit(), "discord-identity-missing")
    require(source_channel_ids, "source-channel-set-empty")
    require(
        all(channel_id.isdigit() for channel_id in source_channel_ids),
        "source-channel-id-invalid",
    )
    matches: dict[str, list[str]] = {name: [] for name in names}
    for source_channel_id in sorted(source_channel_ids):
        channel = api_json(token, f"/channels/{source_channel_id}")
        require(isinstance(channel, dict), "discord-channel-invalid")
        channel_id = str(channel.get("id", ""))
        guild_id = str(channel.get("guild_id", ""))
        require(channel_id == source_channel_id, "discord-channel-id-mismatch")
        require(guild_id.isdigit(), "discord-channel-guild-missing")
        channel_name = channel.get("name")
        if channel_name in matches:
            matches[channel_name].append(channel_id)
    for name, ids in matches.items():
        require(len(ids) == 1, f"discord-channel-{name}-not-unique")
    resolved = {name: ids[0] for name, ids in matches.items()}
    require(len(set(resolved.values())) == len(resolved), "discord-channel-id-duplicate")
    return bot_id, resolved


def source_enabled_channels(config: dict[str, Any], account: str) -> set[str]:
    try:
        discord = config["channels"]["discord"]
        if account == "default":
            sources = [discord, discord.get("accounts", {}).get("default", {})]
        else:
            sources = [discord["accounts"][account]]
    except (KeyError, TypeError) as exc:
        raise EnrollmentError(f"source-discord-{account}-missing") from exc
    enabled: set[str] = set()
    for source in sources:
        guilds = source.get("guilds", {}) if isinstance(source, dict) else {}
        require(isinstance(guilds, dict), f"source-discord-{account}-guilds")
        for guild in guilds.values():
            channels = guild.get("channels", {}) if isinstance(guild, dict) else {}
            require(isinstance(channels, dict), f"source-discord-{account}-channels")
            for channel_id, channel in channels.items():
                if isinstance(channel, dict) and channel.get("enabled") is True:
                    enabled.add(str(channel_id))
    return enabled


def source_owner(config: dict[str, Any]) -> str:
    try:
        discord = config["channels"]["discord"]
    except (KeyError, TypeError) as exc:
        raise EnrollmentError("source-discord-missing") from exc
    candidates: set[str] = set()
    for source in (discord, discord.get("accounts", {}).get("default", {})):
        allow = source.get("allowFrom", []) if isinstance(source, dict) else []
        require(isinstance(allow, list), "source-owner-allowlist-invalid")
        candidates.update(str(value) for value in allow if str(value).isdigit())
    require(len(candidates) == 1, "source-owner-not-unique")
    return next(iter(candidates))


def build_enrollment(env: dict[str, str], config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    astra_token = secret(env, "DISCORD_BOT_TOKEN")
    dubble_token = secret(env, "DISCORD_DUBBLE_BOT_TOKEN")
    anthropic_key = secret(env, "ANTHROPIC_API_KEY")
    astra_enabled = source_enabled_channels(config, "default")
    dubble_enabled = source_enabled_channels(config, "dubble")
    astra_bot, astra_channels = bot_and_channels(
        astra_token,
        EXPECTED_CHANNELS["astra"],
        astra_enabled,
    )
    dubble_bot, dubble_channels = bot_and_channels(
        dubble_token,
        EXPECTED_CHANNELS["dubble"],
        dubble_enabled,
    )
    require(astra_bot != dubble_bot, "discord-bot-identities-not-distinct")
    require(set(astra_channels.values()) <= astra_enabled, "source-astra-route-mismatch")
    require(set(dubble_channels.values()) <= dubble_enabled, "source-dubble-route-mismatch")
    owner = source_owner(config)
    astra = astra_channels["astra"]
    logs = astra_channels["astra-logs"]
    rigel = astra_channels["rigel"]
    dubble = dubble_channels["db"]
    dubble_logs = dubble_channels["db-logs"]
    enrollment = {
        "schemaVersion": SCHEMA_VERSION,
        "consumerCount": 2,
        "logicalProfiles": ["astra", "dubble", "rigel"],
        "profiles": {
            "astra": {
                "allowedUsers": [owner],
                "adminUsers": [owner],
                "allowedChannels": [astra, rigel],
                "freeResponseChannels": [astra, rigel],
                "ignoredChannels": [logs],
                "homeChannel": astra,
                "logChannel": logs,
                "rigelChannel": rigel,
                "channelPrompts": {rigel: RIGEL_PROMPT},
                "channelSkillBindings": [
                    {"id": rigel, "skills": ["source-grounded-study"]}
                ],
            },
            "dubble": {
                "allowedUsers": [],
                "adminUsers": [owner],
                "allowedChannels": [dubble],
                "freeResponseChannels": [dubble],
                "ignoredChannels": [dubble_logs],
                "homeChannel": dubble,
                "logChannel": dubble_logs,
                "rigelChannel": None,
                "channelPrompts": {},
                "channelSkillBindings": [],
            },
            "rigel": {
                "discordConsumer": "astra",
                "schedulerDeliveryChannel": rigel,
            },
        },
        "botIdentityFingerprints": sorted(
            hashlib.sha256(value.encode("ascii")).hexdigest() for value in (astra_bot, dubble_bot)
        ),
    }
    credentials = {
        "astra": "\n".join(
            (
                f"DISCORD_BOT_TOKEN={astra_token}",
                f"DISCORD_ALLOWED_USERS={owner}",
                f"DISCORD_HOME_CHANNEL={astra}",
                "DISCORD_HOME_CHANNEL_NAME=Astra",
                "",
            )
        ),
        "dubble": "\n".join(
            (
                f"ANTHROPIC_API_KEY={anthropic_key}",
                f"DISCORD_BOT_TOKEN={dubble_token}",
                f"DISCORD_HOME_CHANNEL={dubble}",
                "DISCORD_HOME_CHANNEL_NAME=Dubble",
                "",
            )
        ),
        "rigel": f"ANTHROPIC_API_KEY={anthropic_key}\n",
    }
    return enrollment, credentials


def atomic_write(path: Path, content: str, *, group: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        os.fchown(descriptor, 0, grp.getgrnam(group).gr_gid)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def backup_existing(paths: list[Path], backup_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.chown(backup_dir, 0, 0)
    for path in paths:
        if path.exists():
            require(path.is_file() and not path.is_symlink(), "backup-source-unsafe")
            destination = backup_dir / path.as_posix().lstrip("/").replace("/", "__")
            shutil.copy2(path, destination, follow_symlinks=False)
            os.chown(destination, 0, 0)
            os.chmod(destination, 0o600)


def verify_target(target_root: Path, enrollment_path: Path) -> dict[str, Any]:
    enrollment = read_json(enrollment_path, "target-enrollment")
    require(enrollment.get("schemaVersion") == SCHEMA_VERSION, "target-enrollment-version")
    require(enrollment.get("consumerCount") == 2, "target-consumer-count")
    require(enrollment.get("logicalProfiles") == ["astra", "dubble", "rigel"], "target-profiles")
    fingerprints = enrollment.get("botIdentityFingerprints")
    require(isinstance(fingerprints, list) and len(set(fingerprints)) == 2, "target-bot-distinctness")
    for profile, group in PROFILE_GROUPS.items():
        path = target_root / profile / ".env"
        metadata = path.lstat()
        require(stat.S_ISREG(metadata.st_mode) and not path.is_symlink(), "target-env-unsafe")
        require(stat.S_IMODE(metadata.st_mode) == 0o440, "target-env-mode")
        require(metadata.st_uid == 0 and metadata.st_gid == grp.getgrnam(group).gr_gid, "target-env-owner")
        env = read_dotenv(path, allow_group_read=True)
        require("DISCORD_BOT_TOKEN" in env if profile != "rigel" else "DISCORD_BOT_TOKEN" not in env, f"target-{profile}-discord")
        require("ANTHROPIC_API_KEY" in env if profile != "astra" else "ANTHROPIC_API_KEY" not in env, f"target-{profile}-provider")
    return {"status": "ok", "consumers": 2, "profiles": 3, "channels": 4}


def enroll(
    source_env: Path,
    source_config: Path,
    target_root: Path,
    enrollment_path: Path,
    backup_dir: Path,
) -> dict[str, Any]:
    require(os.geteuid() == 0, "root-required")
    env = read_dotenv(source_env)
    config = read_json(source_config, "source-config")
    enrollment, credentials = build_enrollment(env, config)
    paths = [enrollment_path, *(target_root / profile / ".env" for profile in PROFILE_GROUPS)]
    backup_existing(paths, backup_dir)
    for profile, content in credentials.items():
        atomic_write(
            target_root / profile / ".env",
            content,
            group=PROFILE_GROUPS[profile],
            mode=0o440,
        )
    atomic_write(
        enrollment_path,
        json.dumps(enrollment, sort_keys=True, separators=(",", ":")) + "\n",
        group="root",
        mode=0o400,
    )
    return verify_target(target_root, enrollment_path)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--mode", choices=("enroll", "verify"), required=True)
    value.add_argument("--source-env", type=Path, default=Path("/home/johnny/.openclaw/.env"))
    value.add_argument("--source-config", type=Path, default=Path("/home/johnny/.openclaw/openclaw.json"))
    value.add_argument("--target-root", type=Path, default=Path("/etc/hermes"))
    value.add_argument(
        "--enrollment",
        type=Path,
        default=Path("/etc/hermes/private-discord-enrollment.json"),
    )
    value.add_argument("--backup-dir", type=Path)
    return value


def main() -> int:
    arguments = parser().parse_args()
    try:
        if arguments.mode == "enroll":
            require(arguments.backup_dir is not None, "backup-dir-required")
            result = enroll(
                arguments.source_env,
                arguments.source_config,
                arguments.target_root,
                arguments.enrollment,
                arguments.backup_dir,
            )
        else:
            result = verify_target(arguments.target_root, arguments.enrollment)
    except (EnrollmentError, OSError, KeyError) as exc:
        print(json.dumps({"schemaVersion": SCHEMA_VERSION, "status": "error", "reason": str(exc)}))
        return 1
    print(json.dumps({"schemaVersion": SCHEMA_VERSION, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
