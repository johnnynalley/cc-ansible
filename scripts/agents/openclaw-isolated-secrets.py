#!/usr/bin/env python3
"""Create the isolated OpenClaw secret payload without exposing secret values."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import grp
import re
import secrets
import stat
import tempfile
from pathlib import Path

MAX_SOURCE_BYTES = 1024 * 1024
MIN_PROVIDER_KEY_BYTES = 16
MIN_GATEWAY_TOKEN_BYTES = 32
ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


class SecretBootstrapError(RuntimeError):
    """Raised for a safe, operator-facing bootstrap failure."""


def _identity_id(value: str, database: str) -> int:
    if value.isdigit():
        return int(value)
    try:
        if database == "user":
            return pwd.getpwnam(value).pw_uid
        return grp.getgrnam(value).gr_gid
    except KeyError as exc:
        raise SecretBootstrapError(f"unknown {database}: {value}") from exc


def _decode_quoted(value: str, quote: str) -> str:
    if len(value) < 2 or value[-1] != quote:
        raise SecretBootstrapError("unterminated quoted dotenv value")
    body = value[1:-1]
    if quote == "'":
        return body

    output: list[str] = []
    index = 0
    escapes = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"'}
    while index < len(body):
        character = body[index]
        if character != "\\":
            output.append(character)
            index += 1
            continue
        index += 1
        if index >= len(body) or body[index] not in escapes:
            raise SecretBootstrapError("unsupported escape in quoted dotenv value")
        output.append(escapes[body[index]])
        index += 1
    return "".join(output)


def parse_dotenv_key(text: str, key: str) -> str:
    if not ENV_KEY_RE.fullmatch(key):
        raise SecretBootstrapError("invalid dotenv key name")

    matches: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        candidate, raw_value = line.split("=", 1)
        if candidate.strip() != key:
            continue
        value = raw_value.strip()
        if value.startswith(("'", '"')):
            value = _decode_quoted(value, value[0])
        elif any(character.isspace() for character in value):
            raise SecretBootstrapError("unquoted dotenv value contains whitespace")
        matches.append(value)

    if len(matches) != 1:
        raise SecretBootstrapError(
            f"expected exactly one {key} assignment; found {len(matches)}"
        )
    value = matches[0]
    if len(value.encode("utf-8")) < MIN_PROVIDER_KEY_BYTES:
        raise SecretBootstrapError("provider credential is unexpectedly short")
    if "\x00" in value or "\n" in value or "\r" in value:
        raise SecretBootstrapError("provider credential contains forbidden bytes")
    return value


def read_protected_source(path: Path, owner_uid: int) -> str:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SecretBootstrapError("credential source is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise SecretBootstrapError(
            "credential source must be a regular non-symlink file"
        )
    if metadata.st_uid != owner_uid:
        raise SecretBootstrapError("credential source has an unexpected owner")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise SecretBootstrapError(
            "credential source must not grant group or world access"
        )
    if metadata.st_size <= 0 or metadata.st_size > MAX_SOURCE_BYTES:
        raise SecretBootstrapError(
            "credential source size is outside the allowed range"
        )
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "r", encoding="utf-8", errors="strict") as handle:
            return handle.read(MAX_SOURCE_BYTES + 1)
    except (OSError, UnicodeError) as exc:
        raise SecretBootstrapError(
            "credential source could not be read safely"
        ) from exc


def _existing_gateway_token(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
            raise SecretBootstrapError("existing secret payload is not a regular file")
        payload = json.loads(path.read_text(encoding="utf-8"))
        token = payload["gateway"]["token"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SecretBootstrapError("existing secret payload is invalid") from exc
    if (
        not isinstance(token, str)
        or len(token.encode("utf-8")) < MIN_GATEWAY_TOKEN_BYTES
    ):
        raise SecretBootstrapError("existing Gateway token is invalid")
    return token


def _validate_output_parent(parent: Path, owner_uid: int) -> None:
    try:
        metadata = parent.lstat()
    except OSError as exc:
        raise SecretBootstrapError("output directory is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode) or parent.is_symlink():
        raise SecretBootstrapError("output directory must be a non-symlink directory")
    if metadata.st_uid != owner_uid:
        raise SecretBootstrapError("output directory has an unexpected owner")
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        raise SecretBootstrapError(
            "output directory must not be group or world writable"
        )


def write_secret_payload(
    output: Path,
    provider_key: str,
    output_uid: int,
    output_gid: int,
) -> bool:
    _validate_output_parent(output.parent, output_uid)
    gateway_token = _existing_gateway_token(output) or secrets.token_urlsafe(48)
    payload = {
        "providers": {"openrouter": {"apiKey": provider_key}},
        "gateway": {"token": gateway_token},
    }
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")

    if output.exists():
        try:
            if output.read_bytes() == encoded:
                os.chown(output, output_uid, output_gid, follow_symlinks=False)
                os.chmod(output, 0o640, follow_symlinks=False)
                return False
        except OSError as exc:
            raise SecretBootstrapError(
                "existing secret payload could not be checked"
            ) from exc

    descriptor, temporary_name = tempfile.mkstemp(
        dir=output.parent, prefix=f".{output.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o640)
        os.fchown(descriptor, output_uid, output_gid)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
        directory_descriptor = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise SecretBootstrapError(
            "secret payload could not be replaced atomically"
        ) from exc
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-key", default="OPENROUTER_API_KEY")
    parser.add_argument("--source-owner", default="johnny")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--output-owner", default="root")
    parser.add_argument("--output-group", default="openclaw")
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        source_uid = _identity_id(arguments.source_owner, "user")
        output_uid = _identity_id(arguments.output_owner, "user")
        output_gid = _identity_id(arguments.output_group, "group")
        source = read_protected_source(arguments.source, source_uid)
        provider_key = parse_dotenv_key(source, arguments.source_key)
        changed = write_secret_payload(
            arguments.output, provider_key, output_uid, output_gid
        )
    except SecretBootstrapError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        return 1
    print(json.dumps({"status": "ok", "changed": changed}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
